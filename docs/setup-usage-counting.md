# Cloudflare setup, usage counting and sign-in-free intake

Reference for how `runpapers.com` sits behind Cloudflare and how reviewed changes in `deploy/cloudflare/` deploy
automatically. Nobody pastes Worker code by hand: once the tokens below exist, reviewed commits on `main` deploy
automatically via `deploy/cloudflare/deploy.py` and are verified end to end by `.github/workflows/usage-selftest.yml`.

What runs in Cloudflare (`runpapers-counter` on `runpapers.com/*` and `www.runpapers.com/*`):
1. **Cloudflare proxy ("orange cloud", SSL `Full (strict)`)**: serves GitHub Pages unchanged with zero cookies.
2. **Usage counting (`HITS` -> `runpapers_hits`, Spec 004)**: fail-open edge counter recording views by people, views
   by AI agents, `rp get` downloads, and crawlers without storing IP addresses or setting cookies.
3. **Sign-in-free votes, paper requests and moderated comments (`DB` -> `runpapers_intake`, Spec 006)**: protected by
   Cloudflare Turnstile, Crossref/PubMed resolution, 20 submissions/hour per-network rate limiting, email rejection, and
   hourly deletion (`17 * * * *`) of daily-salted deduplication and rate-limit hashes after 48 hours.

## Part 1: Cloudflare zone settings (one-time)
1. In dash.cloudflare.com under **runpapers.com**:
   - **SSL/TLS -> Overview**: encryption mode **Full (strict)**.
   - **SSL/TLS -> Edge Certificates**: **Always Use HTTPS** off (GitHub Pages already redirects to HTTPS).
   - **Security -> Bots**: **Bot Fight Mode** **off** (so AI agents and CLI tools are never blocked); **AI Crawl
     Control** groups left **allowed**.
2. **DNS -> Records**: all 9 records (four `A` and four `AAAA` for `runpapers.com`, plus `CNAME` `www`) set to orange
   **Proxied**. (`curl -sI https://runpapers.com | grep -i cf-ray` confirms Cloudflare is in front with no
   `set-cookie` header.)

## Part 2: Worker secrets and fail-open routes
- Worker name: `runpapers-counter`, routed to `runpapers.com/*` and `www.runpapers.com/*` with failure mode **Fail open
  (proceed)** so the website keeps serving from GitHub Pages even if a Worker limit is ever reached.
- Secrets on `runpapers-counter` (never stored in git; preserved across every deploy via `keep_bindings: ["secret_text"]`
  in `deploy/cloudflare/deploy.py`):
  - `SALT`: random hex string (`openssl rand -hex 16`) salting ephemeral daily visitor, vote-dedup, and rate-limit hashes.
  - `TURNSTILE_SECRET`: managed automatically by `deploy/cloudflare/deploy.py` from the `RunPapers` Turnstile widget.
  - `RP_INTAKE_SECRET`: shared bearer secret (`openssl rand -hex 24`) authenticating GitHub Actions issue sync and
    moderation commands (also stored in GitHub repository **Secrets** as `RP_INTAKE_SECRET`; Cloudflare never holds a
    GitHub token).

## Part 3: tokens (created once)
1. **Read-only analytics token for GitHub Actions (`runpapers-stats-read`)**:
   - Permission: **Account | Account Analytics | Read** (scoped to the RunPapers Cloudflare account).
   - Stored in GitHub (`runpapers/runpapers` -> **Settings -> Secrets and variables -> Actions**) as secret
     `CLOUDFLARE_API_TOKEN`, alongside repository variable `CLOUDFLARE_ACCOUNT_ID`.
2. **Agent deployment token (`runpapers-agent`)**:
   - Permissions on the RunPapers Cloudflare account and `runpapers.com` zone:
     - **Account | Workers Scripts | Edit**
     - **Account | D1 | Edit**
     - **Account | Turnstile | Edit**
     - **Account | Account Settings | Read**
     - **Zone (`runpapers.com`) | Workers Routes | Edit**
   - Used by the automated go-live routine (`python3 deploy/cloudflare/deploy.py` with `CLOUDFLARE_API_TOKEN` in the
     environment). Whenever reviewed changes under `deploy/cloudflare/` land on `main`, `deploy.py` automatically:
     1. Discovers or verifies `CLOUDFLARE_ACCOUNT_ID`.
     2. Ensures D1 database `runpapers_intake` exists and applies `deploy/cloudflare/migrations/*.sql` idempotently.
     3. Ensures the `RunPapers` Turnstile widget (`runpapers.com`, `www.runpapers.com`) exists.
     4. Uploads `deploy/cloudflare/worker.js` to `runpapers-counter` while keeping `HITS` (`runpapers_hits`), `SALT`,
        `RP_INTAKE_SECRET`, and the fail-open routes intact, binding `DB` (`runpapers_intake`) and `TURNSTILE_SITE_KEY`,
        upserting `TURNSTILE_SECRET`, and configuring the `17 * * * *` cleanup cron.

## Part 4: end-to-end verification (`usage-selftest`)
Open **Actions -> usage-selftest -> Run workflow** (`.github/workflows/usage-selftest.yml`, running
`deploy/cloudflare/selftest.py`).
- If at least one pack is published in `https://runpapers.com/index.json` (or `RP_PAPER` is set), it tests that paper's
  HTML page, `AGENT.md`, `index.md`, and `pack.json`; before the first pack is published, it automatically falls back to
  testing `/` across all four visitor kinds (`person`, `agent`, `crawler`, `script`), each twice to verify 1-hour
  deduplication, plus `/style.css`, a 404 page, and the `www.` 301 redirect.
- It reads the `st-<run id>` rows back from `runpapers_hits` using `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`,
  and checks both HTTPS certificates (Cloudflare's edge certificate and GitHub Pages' origin certificate).

## What is excluded from public counts and queues
- **Self-tests (`st-*`)**: `deploy/cloudflare/selftest.py` marks its requests with `X-RunPapers-Action: st-<run id>`
  (and intake self-tests carry `test_action: "st-..."`). They are ignored by `rp stats pull`, excluded from `/_rp/api/public-counts`
  and `/_rp/api/admin/queue`, and purged after verification.
- **CI, `rp usertest` and `DO_NOT_TRACK=1`**: the `rp` CLI sends `X-RunPapers-Internal: 1` whenever `CI` or
  `RUNPAPERS_INTERNAL` is set (including naive-user agent runs in `rp usertest`, and `selftest.py`'s `/index.json`
  lookup), and sends `X-RunPapers-NoCount: 1` when `DO_NOT_TRACK=1`. The Worker skips recording whenever either header is `1`.
- **Crawlers**: search and training crawlers (`GPTBot`, `ClaudeBot`, `Googlebot`, `GoogleOther`, `CCBot`, etc.) are
  classified as `crawler` in `runpapers_hits` for internal diagnostics and are never shown in public counts.

## Part 5: what to watch
- Both `usage-selftest` and the daily operator check inspect Cloudflare's edge certificate and GitHub Pages' origin
  certificate (`185.199.108.153` with SNI `runpapers.com`) and warn **14 days** before either expires (current GitHub
  Pages renewal window before 2027-02-23).

## Part 6: undo or renew origin TLS (one minute, grey-cloud fallback)
- To stop the Worker without touching DNS: delete both routes under **Workers & Pages -> runpapers-counter -> Settings
  -> Domains & Routes**.
- To take Cloudflare out of the way entirely: switch the 9 DNS records back to grey **DNS only**.
- **Grey-cloud fallback for certificate renewal**: if the 14-day certificate check warns or GitHub reports a certificate
  problem in **Settings -> Pages**, switch the 9 DNS records from **Proxied** back to grey **DNS only**, wait until
  **Settings -> Pages** shows a renewed HTTPS certificate (up to a day), then switch them back to orange **Proxied**
  and run **Actions -> usage-selftest**.
