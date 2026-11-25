# Setting up usage counting (Cloudflare) and the GitHub secret

For the maintainer. About 30 minutes. You need: the Cloudflare account that holds runpapers.com, and owner access to
the `runpapers` organization on GitHub. Nothing here changes how the website looks; if anything goes wrong, Part 6
undoes it in one minute.

What you set up:
1. Cloudflare in front of the website (the "orange cloud"), so it sees each request.
2. A small Cloudflare Worker, `deploy/cloudflare/worker.js` in this repository, that counts page views by people and
   by AI agents and serves every page unchanged.
3. A read-only Cloudflare token, stored as a GitHub secret, so the nightly job can read the counts and put them on
   the website.

Cloudflare's menus move sometimes; if a name below differs slightly, look for the closest match.

## Part 1: put Cloudflare in front of the website
1. Sign in at dash.cloudflare.com and open **runpapers.com**.
2. **SSL/TLS -> Overview**: set the encryption mode to **Full (strict)**. (GitHub already serves a valid certificate;
   "strict" checks it.)
3. **SSL/TLS -> Edge Certificates**: leave **Always Use HTTPS** off (GitHub already redirects to HTTPS).
4. **Security -> Bots**: make sure **Bot Fight Mode** is **off**. It would block the AI agents and command-line tools
   that use RunPapers. If you see **AI Crawl Control** (or "AI Audit"), leave every group **allowed**.
5. **DNS -> Records**: for each of the 9 records you created (four `A` and four `AAAA` named `runpapers.com`, and the
   `CNAME` named `www`), click **Edit**, switch **Proxy status** from grey "DNS only" to orange **Proxied**, **Save**.
6. Wait two minutes, then open https://runpapers.com and https://www.runpapers.com in a private browser window. Both
   should load normally. (Check from a terminal: `curl -sI https://runpapers.com | grep -i cf-ray` prints a line
   when Cloudflare is in front.)

## Part 2: create the counting Worker
1. Left menu **Workers & Pages** -> **Create** (or **Create application**) -> **Create Worker**.
2. Name it `runpapers-counter`, click **Deploy** (it deploys a "Hello World"; we replace it next).
3. Click **Edit code**. Delete everything in the editor, open `deploy/cloudflare/worker.js` from this repository
   (on GitHub: github.com/runpapers/runpapers/blob/main/deploy/cloudflare/worker.js -> "Raw"), copy all of it, paste
   it into the editor, then click **Deploy**.
4. Go back to the Worker (**Workers & Pages -> runpapers-counter**) -> **Settings -> Bindings** -> **Add** ->
   **Analytics Engine**. Variable name: `HITS`. Dataset: `runpapers_hits`. **Save / Deploy**.
5. Still in **Settings -> Variables and Secrets** -> **Add**: Type **Secret**, Name `SALT`, Value: a random string.
   Make one with `openssl rand -hex 16` in a terminal (in Claude Code: `! openssl rand -hex 16`). You never need it
   again; it only makes the daily visitor key unguessable. **Deploy**.
6. **Settings -> Domains & Routes** -> **Add** -> **Route**. Zone: `runpapers.com`. Route: `runpapers.com/*`.
   "Failure mode": **Fail open (proceed)**, so the site keeps working if the free daily limit is ever reached. Add a
   second route `www.runpapers.com/*` the same way.
7. Check: open https://runpapers.com and one paper page again; they must look exactly as before. After a minute,
   **Workers & Pages -> runpapers-counter -> Metrics** shows requests.

## Part 3: a read-only token for the nightly job
1. Top right **profile icon -> My Profile -> API Tokens -> Create Token -> Custom token: Get started**.
2. Token name: `runpapers-stats-read`.
3. Permissions: **Account** | **Account Analytics** | **Read**. (Only this one line.)
4. Account Resources: **Include** | your account. Leave IP filtering and TTL empty.
5. **Continue to summary -> Create Token**. Copy the token now (Cloudflare shows it once). Keep the tab open for Part 4.
6. Your **Account ID**: **Workers & Pages** overview page, right side "Account ID" (copy it; it is not secret).

## Part 4: store them in GitHub
1. Open github.com/runpapers/runpapers -> **Settings** (repository settings, top right of the repository tabs).
2. Left menu **Secrets and variables -> Actions**.
3. Tab **Secrets** -> **New repository secret**. Name: `CLOUDFLARE_API_TOKEN`. Secret: paste the token from Part 3.
   **Add secret**. (GitHub never shows it again; the nightly job can use it, nobody can read it.)
4. Tab **Variables** -> **New repository variable**. Name: `CLOUDFLARE_ACCOUNT_ID`. Value: the Account ID.
   **Add variable**.
5. Close the Cloudflare tab. Tell the engineer (or the chief) that the secret and the variable are in place: the
   nightly job (`rp stats pull`, spec 004) starts using them once it is built.

## Part 5: what to watch
- The website loads normally from a phone and a laptop.
- GitHub Pages keeps its HTTPS certificate: **repository Settings -> Pages** should say the site is live with HTTPS.
  The certificate renews before 2027-02-23; the daily operator checks it and warns two weeks before.

## Part 6: undo (one minute)
- To stop counting: **Workers & Pages -> runpapers-counter -> Settings -> Domains & Routes**, delete both routes.
- To take Cloudflare out of the way entirely: **DNS -> Records**, switch the 9 records back to grey **DNS only**.
- If GitHub ever reports a certificate problem in **Settings -> Pages**: switch the records to **DNS only**, wait
  until Pages shows HTTPS again (up to a day), then switch them back to **Proxied**.
