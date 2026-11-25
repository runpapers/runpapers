// RunPapers Cloudflare Worker (`runpapers-counter` on runpapers.com/*).
//
// Self-contained single-file ES module (zero npm dependencies), deployed automatically from reviewed `main` via
// `deploy/cloudflare/deploy.py` (`docs/setup-usage-counting.md`).
//
// Two responsibilities:
// 1. Spec 004 — Usage counting on normal GET/HEAD page requests: serves every page from GitHub Pages unchanged
//    (fail-open, zero cookies, zero stored IP addresses) and writes one deduplicated data point to Workers
//    Analytics Engine (`env.HITS` -> `runpapers_hits`).
// 2. Spec 006 — Sign-in-free votes, paper requests, and moderated comments under `/_rp/api/*` backed by Cloudflare D1
//    (`env.DB` -> `runpapers_intake`), protected by Cloudflare Turnstile, Crossref/NCBI paper resolution, 20/hour
//    per-network rate limiting, email rejection, and 48-hour deletion of daily-salted deduplication/rate hashes.

const USER_AGENT = "runpapers/0.2 (+https://runpapers.com)";
const TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const RATE_LIMIT_PER_HOUR = 20;
const HASH_TTL_SECONDS = 48 * 3600;
const MAX_BODY_BYTES = 16384;

const AGENTS = /(Claude-User|Claude-Code|ChatGPT-User|Perplexity-User|Google-Agent|Gemini-CLI|MistralAI-User|DuckAssistBot|codex|antigravity|cursor|runpapers)/i;
const CRAWLERS = /(bot\b|bot\/|crawler|spider|crawl|slurp|GPTBot|ClaudeBot|Claude-SearchBot|anthropic-ai|CCBot|Google-Extended|GoogleOther|OAI-SearchBot|PerplexityBot|Bytespider|Amazonbot|Applebot|facebookexternalhit|Meta-External|bingpreview|Diffbot|ImagesiftBot|Timpibot)/i;
const SCRIPTS = /^(curl|wget|python-requests|python-urllib|python-httpx|aiohttp|httpx|go-http-client|node-fetch|undici|node\b|axios|okhttp|java\/|libwww)/i;

const DOI_PREFIXES = [
  "https://doi.org/",
  "http://doi.org/",
  "https://dx.doi.org/",
  "http://dx.doi.org/",
  "https://www.doi.org/",
  "doi.org/",
  "doi:",
  "doi ",
];
const DOI_RE = /^10\.\d{4,9}\/\S+$/;
const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
const SELFTEST_ACTION_RE = /^st-[a-zA-Z0-9_-]{1,24}$/;

// --------------------------------------------------------------------------- Spec 004: usage counter helpers

export function kindOf(ua) {
  if (!ua) return "script";
  if (AGENTS.test(ua)) return "agent";
  if (CRAWLERS.test(ua)) return "crawler";
  if (SCRIPTS.test(ua)) return "script";
  if (/Mozilla\/5\.0/.test(ua)) return "person";
  return "script";
}

export function pageOf(path) {
  if (path.startsWith("/doi/") || /^\/(guide|requests|about)\.html$/.test(path)) {
    return { paper: "", type: "" };   // legacy meta-refresh redirect stubs: counted at canonical target
  }
  const m = path.match(/^\/papers\/([a-z0-9-]+)\/(.*)$/);
  const paper = m ? m[1] : "";
  const rest = m ? m[2] : path;
  if (m && rest.startsWith("pack/")) return { paper, type: "" };
  let type = "";
  if (rest.endsWith("AGENT.md")) type = "agent";
  else if (rest.endsWith("pack.json")) type = "pack";
  else if (rest.endsWith(".md")) type = "md";
  else if (rest === "" || rest.endsWith("/") || rest.endsWith(".html")) type = "html";
  return { paper, type };   // type "" = images, fonts, styles, pack files: not counted
}

export function shouldSkip(headers) {
  if (!headers) return false;
  const internal = (headers.get("X-RunPapers-Internal") || "").trim();
  const noCount = (headers.get("X-RunPapers-NoCount") || "").trim();
  return internal === "1" || noCount === "1";
}

async function sha256Bytes(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return new Uint8Array(buf);
}

async function digest(text, byteLen = 12) {
  const bytes = await sha256Bytes(text);
  return [...bytes.slice(0, byteLen)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function nowMs(env) {
  return env && typeof env._NOW_MS === "number" ? env._NOW_MS : Date.now();
}

async function record(request, response, env) {
  if (!env || !env.HITS || !["GET", "HEAD"].includes(request.method)) return;
  if (response.status !== 200 && response.status !== 304) return;
  if (shouldSkip(request.headers)) return;
  const url = new URL(request.url);
  const { paper, type } = pageOf(url.pathname);
  if (!type) return;
  const ua = request.headers.get("User-Agent") || "";
  const kind = kindOf(ua);
  const action = (request.headers.get("X-RunPapers-Action") || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 16);
  const day = new Date(nowMs(env)).toISOString().slice(0, 10);
  const visitor = await digest(`${env.SALT || ""}|${day}|${request.headers.get("CF-Connecting-IP") || ""}|${ua}`);
  const host = url.hostname.replace(/^www\./i, "");
  const key = new Request(`https://${host}/__seen/${await digest(`${visitor}|${url.pathname}|${action}`)}`);
  const cache = caches.default;
  if (await cache.match(key)) return;   // same visitor, same page, within the hour
  await cache.put(key, new Response("1", { headers: { "Cache-Control": "max-age=3600" } }));
  await env.HITS.writeDataPoint({
    blobs: [kind, type, paper, action, url.pathname.slice(0, 200)],
    doubles: [1],
    indexes: [paper || "site"],
  });
}

// --------------------------------------------------------------------------- Spec 006: privacy, IDs, & resolution

export function containsEmail(text) {
  return Boolean(text && EMAIL_RE.test(String(text)));
}

export function networkPrefix(ip) {
  const raw = String(ip || "").trim().split("%")[0];
  if (!raw) return "unknown";
  const v4Mapped = raw.match(/^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i);
  const v4 = v4Mapped ? v4Mapped[1] : raw;
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(v4)) {
    const parts = v4.split(".");
    if (parts.every((p) => Number(p) >= 0 && Number(p) <= 255)) {
      return `${parts[0]}.${parts[1]}.${parts[2]}.0/24`;
    }
    return "unknown";
  }
  if (raw.includes(":")) {
    const [leftRaw, rightRaw] = raw.toLowerCase().split("::");
    const left = leftRaw ? leftRaw.split(":").filter(Boolean) : [];
    const right = rightRaw !== undefined ? (rightRaw ? rightRaw.split(":").filter(Boolean) : []) : [];
    if (![...left, ...right].every((h) => /^[0-9a-f]{1,4}$/.test(h))) return "unknown";
    const missing = raw.includes("::") ? Math.max(0, 8 - left.length - right.length) : 0;
    const full = [...left, ...Array(missing).fill("0"), ...right].map((h) => h.padStart(4, "0"));
    while (full.length < 3) full.push("0000");
    return `${full[0]}:${full[1]}:${full[2]}::/48`;
  }
  return "unknown";
}

export function normalizeDoi(input) {
  let t = String(input || "").trim();
  const low = t.toLowerCase();
  for (const p of DOI_PREFIXES) {
    if (low.startsWith(p)) {
      t = t.slice(p.length);
      break;
    }
  }
  try {
    t = decodeURIComponent(t);
  } catch {
    // keep raw string if percent-encoding is malformed
  }
  t = t.trim().toLowerCase();
  if (!t || /\s/.test(t) || !DOI_RE.test(t)) return null;
  return t;
}

export async function doiSlug(doi) {
  const norm = normalizeDoi(doi);
  if (!norm) return "";
  let s = norm.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (s.length > 54) {
    const suffix = await digest(norm, 4);   // 8 hex chars, matching src/runpapers/ids.py:doi_slug
    s = s.slice(0, 45).replace(/-+$/g, "") + "-" + suffix;
  }
  return s;
}

export function parsePaperQuery(input) {
  const t = String(input || "").trim();
  if (!t) return { kind: "empty", value: "" };
  const low = t.toLowerCase();
  const pmidMatch = low.match(/^(?:pmid:\s*|https?:\/\/(?:www\.)?(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov\/pubmed)\/)?(\d{1,9})\/?$/);
  if (pmidMatch) return { kind: "pmid", value: pmidMatch[1] };
  const pmcidMatch = low.match(/^(?:pmcid:\s*|https?:\/\/(?:www\.)?(?:ncbi\.nlm\.nih\.gov\/pmc\/articles|pmc\.ncbi\.nlm\.nih\.gov\/articles)\/)?(pmc\d+)\/?$/);
  if (pmcidMatch) return { kind: "pmcid", value: pmcidMatch[1].toUpperCase() };
  const doi = normalizeDoi(t);
  if (doi) return { kind: "doi", value: doi };
  return { kind: "title", value: t };
}

function normalizeTitleKey(title) {
  return String(title || "")
    .replace(/<[^>]*>/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

async function fetchJson(url) {
  const r = await fetch(url, { headers: { "User-Agent": USER_AGENT, Accept: "application/json" } });
  if (!r.ok) return null;
  return await r.json();
}

function parseCrossrefMessage(msg) {
  if (!msg || !msg.DOI) return null;
  const doi = normalizeDoi(msg.DOI);
  if (!doi) return null;
  const title = Array.isArray(msg.title) && msg.title[0] ? String(msg.title[0]).replace(/\s+/g, " ").trim() : "";
  if (!title) return null;
  const authors = Array.isArray(msg.author) ? msg.author : [];
  const firstAuthor = authors[0]
    ? [authors[0].given, authors[0].family].filter(Boolean).join(" ") || authors[0].name || ""
    : "";
  const journal = Array.isArray(msg["container-title"]) && msg["container-title"][0] ? String(msg["container-title"][0]).trim() : "";
  const parts = msg.issued && Array.isArray(msg.issued["date-parts"]) && Array.isArray(msg.issued["date-parts"][0])
    ? msg.issued["date-parts"][0]
    : [];
  const year = Number.isInteger(parts[0]) ? parts[0] : null;
  return { doi, title, first_author: firstAuthor || null, journal: journal || null, year };
}

async function lookupIdconv(idValue) {
  try {
    const data = await fetchJson(
      `https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?ids=${encodeURIComponent(idValue)}&format=json`,
    );
    const rec = data && Array.isArray(data.records) ? data.records[0] : null;
    if (!rec || rec.status === "error") return {};
    return {
      doi: rec.doi ? normalizeDoi(rec.doi) : null,
      pmid: rec.pmid ? String(rec.pmid) : null,
    };
  } catch {
    return {};
  }
}

async function lookupPubmedSummary(pmid) {
  try {
    const data = await fetchJson(
      `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=${encodeURIComponent(pmid)}&retmode=json`,
    );
    const rec = data && data.result ? data.result[String(pmid)] : null;
    if (!rec || rec.error) return null;
    let doi = null;
    for (const aid of rec.articleids || []) {
      if (aid && aid.idtype === "doi" && normalizeDoi(aid.value)) {
        doi = normalizeDoi(aid.value);
        break;
      }
    }
    const title = String(rec.title || "").replace(/\s+/g, " ").replace(/\.$/, "").trim();
    const authors = Array.isArray(rec.authors) ? rec.authors : [];
    const firstAuthor = authors[0] && authors[0].name ? String(authors[0].name) : null;
    const journal = rec.fulljournalname || rec.source || null;
    const yearMatch = String(rec.pubdate || "").match(/\b(19|20)\d{2}\b/);
    const year = yearMatch ? Number(yearMatch[0]) : null;
    return { doi, pmid: String(pmid), title, first_author: firstAuthor, journal, year };
  } catch {
    return null;
  }
}

async function lookupCrossrefDoi(doi) {
  try {
    const data = await fetchJson(`https://api.crossref.org/works/${encodeURIComponent(doi)}`);
    return data && data.message ? parseCrossrefMessage(data.message) : null;
  } catch {
    return null;
  }
}

export async function resolvePaperQuery(query) {
  const parsed = parsePaperQuery(query);
  if (parsed.kind === "empty") return null;

  if (parsed.kind === "doi") {
    const cr = await lookupCrossrefDoi(parsed.value);
    const ids = await lookupIdconv(parsed.value);
    if (cr) return { ...cr, pmid: ids.pmid || null };
    if (ids.pmid) {
      const pm = await lookupPubmedSummary(ids.pmid);
      if (pm && pm.title) return { ...pm, doi: parsed.value };
    }
    return null;
  }

  if (parsed.kind === "pmid") {
    const pm = await lookupPubmedSummary(parsed.value);
    const ids = (!pm || !pm.doi) ? await lookupIdconv(parsed.value) : { doi: pm.doi, pmid: parsed.value };
    const doi = (pm && pm.doi) || ids.doi || null;
    if (!doi) return null;
    const cr = await lookupCrossrefDoi(doi);
    if (cr) return { ...cr, pmid: parsed.value };
    if (pm && pm.title) return { ...pm, doi, pmid: parsed.value };
    return null;
  }

  if (parsed.kind === "pmcid") {
    const ids = await lookupIdconv(parsed.value);
    if (!ids.doi) return null;
    const cr = await lookupCrossrefDoi(ids.doi);
    if (cr) return { ...cr, pmid: ids.pmid || null };
    if (ids.pmid) {
      const pm = await lookupPubmedSummary(ids.pmid);
      if (pm && pm.title) return { ...pm, doi: ids.doi };
    }
    return null;
  }

  // Exact normalized title lookup via Crossref (refuses ambiguous partial matches).
  const wantTitle = normalizeTitleKey(parsed.value);
  if (wantTitle.length < 6) return null;
  try {
    const data = await fetchJson(
      `https://api.crossref.org/works?query.bibliographic=${encodeURIComponent(parsed.value)}&rows=5`,
    );
    const items = data && data.message && Array.isArray(data.message.items) ? data.message.items : [];
    for (const item of items) {
      const cand = parseCrossrefMessage(item);
      if (cand && normalizeTitleKey(cand.title) === wantTitle) {
        const ids = await lookupIdconv(cand.doi);
        return { ...cand, pmid: ids.pmid || null };
      }
    }
  } catch {
    return null;
  }
  return null;
}

// --------------------------------------------------------------------------- Spec 006: D1 cleanup, auth, & endpoints

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

async function constantTimeBearerMatch(authHeader, expectedSecret) {
  const secret = String(expectedSecret || "").trim();
  if (!secret || !authHeader || !authHeader.startsWith("Bearer ")) return false;
  const candidate = authHeader.slice(7).trim();
  if (!candidate) return false;
  const [a, b] = await Promise.all([sha256Bytes(candidate), sha256Bytes(secret)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function extractTestAction(request, body) {
  const raw = String((body && body.test_action) || request.headers.get("X-RunPapers-Action") || "").trim();
  return SELFTEST_ACTION_RE.test(raw) ? raw : "";
}

export async function cleanupExpiredHashes(db, nowSec) {
  if (!db) return;
  const cutoff = nowSec - HASH_TTL_SECONDS;
  await db.prepare("DELETE FROM dedup_hashes WHERE created_at <= ?").bind(cutoff).run();
  await db.prepare("DELETE FROM rate_windows WHERE created_at <= ?").bind(cutoff).run();
}

function scheduleCleanup(env, ctx, nowSec) {
  if (!env || !env.DB) return;
  const p = cleanupExpiredHashes(env.DB, nowSec).catch(() => {});
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(p);
}

async function checkRateLimit(db, env, ip, nowSec) {
  const utcHour = new Date(nowSec * 1000).toISOString().slice(0, 13);
  const netHash = await digest(`${env.SALT || ""}|rl|${utcHour}|${networkPrefix(ip)}`, 16);
  await db
    .prepare(
      "INSERT INTO rate_windows (net_hash, submissions, created_at) VALUES (?, 1, ?) " +
      "ON CONFLICT(net_hash) DO UPDATE SET submissions = submissions + 1",
    )
    .bind(netHash, nowSec)
    .run();
  const row = await db.prepare("SELECT submissions FROM rate_windows WHERE net_hash = ?").bind(netHash).first();
  return !row || Number(row.submissions) <= RATE_LIMIT_PER_HOUR;
}

async function verifyTurnstile(token, env) {
  const secret = String((env && env.TURNSTILE_SECRET) || "").trim();
  if (!secret) return { ok: false, status: 503, error: "Verification is temporarily unavailable. Please try again later or use GitHub." };
  if (!token || typeof token !== "string" || token.length > 2048) {
    return { ok: false, status: 403, error: "Verification is required. Please complete the check and try again." };
  }
  try {
    const r = await fetch(TURNSTILE_VERIFY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret, response: token }),
    });
    if (!r.ok) {
      return { ok: false, status: 503, error: "Verification service is temporarily unavailable. Please try again later or use GitHub." };
    }
    const data = await r.json();
    if (!data || data.success !== true) {
      return { ok: false, status: 403, error: "Verification did not pass. Please refresh and try again." };
    }
    return { ok: true };
  } catch {
    return { ok: false, status: 503, error: "Verification service is temporarily unavailable. Please try again later or use GitHub." };
  }
}

async function readJsonBody(request) {
  const len = Number(request.headers.get("content-length") || 0);
  if (len > MAX_BODY_BYTES) return { error: jsonResponse({ ok: false, error: "Submission is too large." }, 413) };
  const text = await request.text();
  if (text.length > MAX_BODY_BYTES) return { error: jsonResponse({ ok: false, error: "Submission is too large." }, 413) };
  try {
    const obj = text ? JSON.parse(text) : {};
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
      return { error: jsonResponse({ ok: false, error: "Invalid JSON request body." }, 400) };
    }
    return { body: obj };
  } catch {
    return { error: jsonResponse({ ok: false, error: "Invalid JSON request body." }, 400) };
  }
}

function sameOriginAllowed(request, url) {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  try {
    const o = new URL(origin);
    const reqHost = url.hostname.replace(/^www\./i, "");
    const origHost = o.hostname.replace(/^www\./i, "");
    return origHost === reqHost || origHost === "runpapers.com";
  } catch {
    return false;
  }
}

async function guardPreValidate(request, env, body, nowSec) {
  const testAction = extractTestAction(request, body);
  const isAuthedSelftest = Boolean(
    testAction && (await constantTimeBearerMatch(request.headers.get("Authorization") || "", env.RP_INTAKE_SECRET)),
  );
  const token = body.turnstile_token;
  if (!isAuthedSelftest && (!token || typeof token !== "string" || !token.trim())) {
    return { error: jsonResponse({ ok: false, error: "Verification is required. Please complete the check and try again." }, 403) };
  }
  const ip = request.headers.get("CF-Connecting-IP") || "";
  if (!isAuthedSelftest && !(await checkRateLimit(env.DB, env, ip, nowSec))) {
    return {
      error: jsonResponse(
        { ok: false, error: "More than 20 submissions this hour from your network. Please try again later." },
        429,
      ),
    };
  }
  return {
    testAction,
    isAuthedSelftest,
    token: typeof token === "string" ? token.trim() : "",
    ip,
    ua: request.headers.get("User-Agent") || "",
  };
}

async function guardTurnstile(guard, env) {
  if (guard.isAuthedSelftest) return null;
  const ts = await verifyTurnstile(guard.token, env);
  return ts.ok ? null : jsonResponse({ ok: false, error: ts.error }, ts.status);
}

async function recordVote(db, env, { doi, testAction, ip, ua, nowSec, isoNow }) {
  const utcDay = isoNow.slice(0, 10);
  const storageDoi = testAction ? `${testAction}:${doi}` : doi;
  const voteHash = await digest(`${env.SALT || ""}|${utcDay}|vote|${storageDoi}|${ip}|${ua}`, 16);
  const ins = await db
    .prepare("INSERT OR IGNORE INTO dedup_hashes (hash, created_at) VALUES (?, ?)")
    .bind(voteHash, nowSec)
    .run();
  const inserted = Boolean(ins && ins.meta && Number(ins.meta.changes) > 0);
  if (inserted) {
    await db
      .prepare(
        "INSERT INTO paper_votes (doi, website_votes, updated_at) VALUES (?, 1, ?) " +
        "ON CONFLICT(doi) DO UPDATE SET website_votes = website_votes + 1, updated_at = excluded.updated_at",
      )
      .bind(storageDoi, isoNow)
      .run();
  }
  const row = await db.prepare("SELECT website_votes FROM paper_votes WHERE doi = ?").bind(storageDoi).first();
  return {
    counted: inserted,
    already_voted: !inserted,
    website_votes: row ? Number(row.website_votes) : 0,
  };
}

async function loadSiteCatalog(env, url) {
  const idxUrl = (env && env.SITE_INDEX_URL) || `${url.origin}/index.json`;
  try {
    const data = await fetchJson(idxUrl);
    return {
      papers: data && Array.isArray(data.papers) ? data.papers : [],
      requests: data && Array.isArray(data.requests) ? data.requests : [],
    };
  } catch {
    return { papers: [], requests: [] };
  }
}

async function buildPublicSnapshot(db) {
  const votesOut = {};
  const voteRows = await db
    .prepare("SELECT doi, website_votes FROM paper_votes WHERE website_votes > 0 AND doi NOT LIKE 'st-%' ORDER BY doi ASC")
    .all();
  for (const r of (voteRows && voteRows.results) || []) {
    votesOut[r.doi] = Number(r.website_votes);
  }
  const commentsOut = {};
  const commentRows = await db
    .prepare(
      "SELECT id, doi, author_name, body, created_date FROM comments " +
      "WHERE status = 'approved' AND kind = 'comment' AND test_action = '' ORDER BY created_at ASC, id ASC",
    )
    .all();
  for (const r of (commentRows && commentRows.results) || []) {
    if (!commentsOut[r.doi]) commentsOut[r.doi] = [];
    commentsOut[r.doi].push({
      id: r.id,
      name: r.author_name || null,
      created_date: r.created_date,
      body: r.body,
    });
  }
  return { votes: votesOut, approved_comments: commentsOut };
}

function randomHexId(byteLen = 8) {
  const arr = new Uint8Array(byteLen);
  crypto.getRandomValues(arr);
  return [...arr].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function handleIntake(request, env, ctx) {
  const url = new URL(request.url);
  const path = url.pathname;
  if (!env || !env.DB) {
    return jsonResponse(
      { ok: false, error: "Submissions are temporarily unavailable. Please try again later or use GitHub." },
      503,
    );
  }
  const ms = nowMs(env);
  const nowSec = Math.floor(ms / 1000);
  const isoNow = new Date(ms).toISOString();

  // Read-only public snapshot of website vote counts and already-approved comments (never unapproved rows or hashes).
  if (path === "/_rp/api/public-counts") {
    if (request.method !== "GET") return jsonResponse({ ok: false, error: "Method not allowed." }, 405);
    return jsonResponse(await buildPublicSnapshot(env.DB));
  }

  // Shared-secret admin endpoints for GitHub Actions issue sync and daily maintainer moderation.
  if (path.startsWith("/_rp/api/admin/")) {
    if (!env.RP_INTAKE_SECRET) return jsonResponse({ ok: false, error: "Admin secret is not configured." }, 503);
    if (!(await constantTimeBearerMatch(request.headers.get("Authorization") || "", env.RP_INTAKE_SECRET))) {
      return jsonResponse({ ok: false, error: "Unauthorized." }, 401);
    }

    if (path === "/_rp/api/admin/public-snapshot") {
      if (request.method !== "GET") return jsonResponse({ ok: false, error: "Method not allowed." }, 405);
      return jsonResponse(await buildPublicSnapshot(env.DB));
    }

    if (path === "/_rp/api/admin/queue") {
      if (request.method !== "GET") return jsonResponse({ ok: false, error: "Method not allowed." }, 405);
      const filterAction = url.searchParams.get("test_action") || "";
      if (filterAction && !SELFTEST_ACTION_RE.test(filterAction)) {
        return jsonResponse({ ok: false, error: "Invalid test_action filter." }, 400);
      }
      const reqs = await env.DB
        .prepare(
          "SELECT doi, pmid, title, first_author, journal, year, why, status, github_issue_url, created_at, updated_at " +
          "FROM paper_requests WHERE status = 'pending_issue' AND test_action = ? ORDER BY created_at ASC",
        )
        .bind(filterAction)
        .all();
      const pendingComments = await env.DB
        .prepare(
          "SELECT id, doi, kind, author_name, body, status, screen_note, github_issue_url, created_date, created_at " +
          "FROM comments WHERE status = 'pending' AND test_action = ? ORDER BY created_at ASC",
        )
        .bind(filterAction)
        .all();
      const screenedComments = await env.DB
        .prepare(
          "SELECT id, doi, kind, author_name, body, status, screen_note, github_issue_url, created_date, created_at " +
          "FROM comments WHERE status = 'screened' AND test_action = ? ORDER BY created_at ASC",
        )
        .bind(filterAction)
        .all();
      return jsonResponse({
        ok: true,
        pending_requests: (reqs && reqs.results) || [],
        pending_comments: (pendingComments && pendingComments.results) || [],
        screened_comments: (screenedComments && screenedComments.results) || [],
      });
    }

    if (path === "/_rp/api/admin/moderate") {
      if (request.method !== "POST") return jsonResponse({ ok: false, error: "Method not allowed." }, 405);
      const parsed = await readJsonBody(request);
      if (parsed.error) return parsed.error;
      const body = parsed.body;
      const verdict = String(body.verdict || body.action || "").trim();

      if (verdict === "cleanup_selftest") {
        const ta = String(body.test_action || "").trim();
        if (ta) {
          if (!SELFTEST_ACTION_RE.test(ta)) return jsonResponse({ ok: false, error: "Invalid test_action." }, 400);
          await env.DB.prepare("DELETE FROM paper_votes WHERE doi LIKE ?").bind(`${ta}:%`).run();
          await env.DB.prepare("DELETE FROM paper_requests WHERE test_action = ? OR doi LIKE ?").bind(ta, `${ta}:%`).run();
          await env.DB.prepare("DELETE FROM comments WHERE test_action = ?").bind(ta).run();
        } else {
          await env.DB.prepare("DELETE FROM paper_votes WHERE doi LIKE 'st-%'").run();
          await env.DB.prepare("DELETE FROM paper_requests WHERE test_action LIKE 'st-%' OR doi LIKE 'st-%'").run();
          await env.DB.prepare("DELETE FROM comments WHERE test_action LIKE 'st-%'").run();
        }
        await cleanupExpiredHashes(env.DB, nowSec);
        return jsonResponse({ ok: true, cleaned: ta || "st-*" });
      }

      if (body.target === "request" || (body.doi && !body.id)) {
        const rawDoi = String(body.doi || "").trim();
        const keyDoi = rawDoi.startsWith("st-") ? rawDoi : normalizeDoi(rawDoi);
        if (!keyDoi) return jsonResponse({ ok: false, error: "Valid doi is required." }, 400);
        const issueUrl = body.github_issue_url ? String(body.github_issue_url).trim().slice(0, 300) : null;
        if (verdict === "issue_opened" || verdict === "duplicate") {
          const upd = await env.DB
            .prepare(
              "UPDATE paper_requests SET status = ?, github_issue_url = COALESCE(?, github_issue_url), updated_at = ? WHERE doi = ?",
            )
            .bind(verdict, issueUrl, isoNow, keyDoi)
            .run();
          if (!upd || !upd.meta || !upd.meta.changes) {
            return jsonResponse({ ok: false, error: "Request not found." }, 404);
          }
          return jsonResponse({ ok: true, doi: keyDoi, status: verdict });
        }
        if (verdict === "reject" || verdict === "rejected") {
          const del = await env.DB.prepare("DELETE FROM paper_requests WHERE doi = ?").bind(keyDoi).run();
          return jsonResponse({ ok: true, doi: keyDoi, deleted: Boolean(del && del.meta && del.meta.changes > 0) });
        }
        return jsonResponse({ ok: false, error: "Unsupported request moderation verdict." }, 400);
      }

      const id = String(body.id || "").trim();
      if (!id) return jsonResponse({ ok: false, error: "Comment id is required." }, 400);
      if (verdict === "reject" || verdict === "rejected") {
        // Permanently delete rejected spam / accidental personal data from D1 (AC 5).
        const del = await env.DB.prepare("DELETE FROM comments WHERE id = ?").bind(id).run();
        return jsonResponse({ ok: true, id, deleted: Boolean(del && del.meta && del.meta.changes > 0) });
      }
      const note = body.screen_note !== undefined && body.screen_note !== null
        ? String(body.screen_note).trim().slice(0, 500)
        : null;
      const issueUrl = body.github_issue_url ? String(body.github_issue_url).trim().slice(0, 300) : null;
      const nextStatus =
        verdict === "screen" || verdict === "screened" ? "screened"
        : verdict === "approve" || verdict === "approved" ? "approved"
        : verdict === "issue_opened" ? "issue_opened"
        : null;
      if (!nextStatus) return jsonResponse({ ok: false, error: "Unsupported comment moderation verdict." }, 400);
      const upd = await env.DB
        .prepare(
          "UPDATE comments SET status = ?, screen_note = COALESCE(?, screen_note), " +
          "github_issue_url = COALESCE(?, github_issue_url) WHERE id = ?",
        )
        .bind(nextStatus, note, issueUrl, id)
        .run();
      if (!upd || !upd.meta || !upd.meta.changes) {
        return jsonResponse({ ok: false, error: "Comment not found." }, 404);
      }
      return jsonResponse({ ok: true, id, status: nextStatus });
    }

    return jsonResponse({ ok: false, error: "Not found." }, 404);
  }

  // Public submission endpoints (POST only, same-origin check, Turnstile, 20/hr rate limit, 48h hash cleanup).
  if (!["/_rp/api/vote", "/_rp/api/request", "/_rp/api/comment"].includes(path)) {
    return jsonResponse({ ok: false, error: "Not found." }, 404);
  }
  if (request.method !== "POST") return jsonResponse({ ok: false, error: "Method not allowed." }, 405);
  if (!sameOriginAllowed(request, url)) return jsonResponse({ ok: false, error: "Cross-origin submissions are not allowed." }, 403);

  const parsed = await readJsonBody(request);
  if (parsed.error) return parsed.error;
  const body = parsed.body;

  const guard = await guardPreValidate(request, env, body, nowSec);
  if (guard.error) return guard.error;
  scheduleCleanup(env, ctx, nowSec);

  if (path === "/_rp/api/vote") {
    const doi = normalizeDoi(body.doi);
    if (!doi) {
      return jsonResponse({ ok: false, error: "Please provide a valid DOI (for example, 10.1016/j.cell.2026.10.012)." }, 400);
    }
    const tsErr = await guardTurnstile(guard, env);
    if (tsErr) return tsErr;
    const voteRes = await recordVote(env.DB, env, {
      doi,
      testAction: guard.testAction,
      ip: guard.ip,
      ua: guard.ua,
      nowSec,
      isoNow,
    });
    return jsonResponse({
      ok: true,
      doi,
      ...voteRes,
      ...(guard.testAction ? { isolated_test: true } : {}),
    });
  }

  if (path === "/_rp/api/request") {
    const query = String(body.query || "").trim();
    const why = body.why !== undefined && body.why !== null ? String(body.why).trim() : "";
    if (!query || query.length > 300) {
      return jsonResponse({ ok: false, error: "Please enter a DOI, PubMed ID, or full paper title." }, 400);
    }
    if (why.length > 1000) {
      return jsonResponse({ ok: false, error: "Please keep the reason under 1,000 characters." }, 400);
    }
    if (containsEmail(why) || (!normalizeDoi(query) && containsEmail(query))) {
      return jsonResponse(
        { ok: false, error: "Please remove email addresses — RunPapers does not collect emails and requests are public." },
        400,
      );
    }
    const tsErr = await guardTurnstile(guard, env);
    if (tsErr) return tsErr;
    const resolved = await resolvePaperQuery(query);
    if (!resolved) {
      return jsonResponse(
        {
          ok: false,
          error: "Could not find a published paper or preprint matching that identifier. Please check the DOI or PubMed ID and try again.",
        },
        422,
      );
    }
    const catalog = await loadSiteCatalog(env, url);
    const avail = catalog.papers.find(
      (p) => (p.doi && normalizeDoi(p.doi) === resolved.doi) || (resolved.pmid && String(p.pmid || "") === resolved.pmid),
    );
    if (avail && !guard.testAction) {
      const slug = await doiSlug(resolved.doi);
      return jsonResponse({
        ok: true,
        mode: "already_available",
        doi: resolved.doi,
        title: resolved.title,
        url: `/papers/${slug}/`,
      });
    }
    const reqKeyDoi = guard.testAction ? `${guard.testAction}:${resolved.doi}` : resolved.doi;
    const existingD1 = await env.DB
      .prepare("SELECT doi, status, github_issue_url FROM paper_requests WHERE doi = ?")
      .bind(reqKeyDoi)
      .first();
    const existingGh = !guard.testAction && catalog.requests.some(
      (r) => (r.doi && normalizeDoi(r.doi) === resolved.doi) || (resolved.pmid && String(r.pmid || "") === resolved.pmid),
    );
    if (existingD1 || existingGh) {
      const voteRes = await recordVote(env.DB, env, {
        doi: resolved.doi,
        testAction: guard.testAction,
        ip: guard.ip,
        ua: guard.ua,
        nowSec,
        isoNow,
      });
      return jsonResponse({
        ok: true,
        mode: "voted_existing",
        doi: resolved.doi,
        title: resolved.title,
        github_issue_url: (existingD1 && existingD1.github_issue_url) || null,
        ...voteRes,
        ...(guard.testAction ? { isolated_test: true } : {}),
      });
    }
    const ins = await env.DB
      .prepare(
        "INSERT OR IGNORE INTO paper_requests (doi, pmid, title, first_author, journal, year, why, status, github_issue_url, test_action, created_at, updated_at) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_issue', NULL, ?, ?, ?)",
      )
      .bind(
        reqKeyDoi,
        resolved.pmid || null,
        resolved.title,
        resolved.first_author || null,
        resolved.journal || null,
        resolved.year !== undefined && resolved.year !== null ? Number(resolved.year) : null,
        why || null,
        guard.testAction || "",
        isoNow,
        isoNow,
      )
      .run();
    const insertedReq = Boolean(ins && ins.meta && Number(ins.meta.changes) > 0);
    const voteRes = await recordVote(env.DB, env, {
      doi: resolved.doi,
      testAction: guard.testAction,
      ip: guard.ip,
      ua: guard.ua,
      nowSec,
      isoNow,
    });
    if (!insertedReq) {
      const raced = await env.DB
        .prepare("SELECT github_issue_url FROM paper_requests WHERE doi = ?")
        .bind(reqKeyDoi)
        .first();
      return jsonResponse({
        ok: true,
        mode: "voted_existing",
        doi: resolved.doi,
        title: resolved.title,
        github_issue_url: (raced && raced.github_issue_url) || null,
        ...voteRes,
        ...(guard.testAction ? { isolated_test: true } : {}),
      });
    }
    return jsonResponse({
      ok: true,
      mode: "created",
      status: "pending_issue",
      doi: resolved.doi,
      pmid: resolved.pmid || null,
      title: resolved.title,
      website_votes: voteRes.website_votes,
      ...(guard.testAction ? { isolated_test: true } : {}),
    });
  }

  // POST /_rp/api/comment
  const doi = normalizeDoi(body.doi);
  if (!doi) {
    return jsonResponse({ ok: false, error: "Please provide a valid paper DOI." }, 400);
  }
  const kind = body.kind === undefined || body.kind === null || body.kind === "" ? "comment" : String(body.kind).trim();
  if (kind !== "comment" && kind !== "problem") {
    return jsonResponse({ ok: false, error: "Kind must be 'comment' or 'problem'." }, 400);
  }
  const rawName = body.name !== undefined && body.name !== null ? String(body.name) : (body.author_name || "");
  const authorName = String(rawName).trim();
  const commentBody = String(body.body || "").trim();
  if (authorName.length > 80) {
    return jsonResponse({ ok: false, error: "Display name must be 80 characters or fewer." }, 400);
  }
  if (!commentBody || commentBody.length > 2000) {
    return jsonResponse({ ok: false, error: "Please enter a message up to 2,000 characters." }, 400);
  }
  if (containsEmail(authorName) || containsEmail(commentBody)) {
    return jsonResponse(
      { ok: false, error: "Please remove email addresses — RunPapers does not collect emails and approved comments are public." },
      400,
    );
  }
  const tsErr = await guardTurnstile(guard, env);
  if (tsErr) return tsErr;
  const id = randomHexId(8);
  const createdDate = isoNow.slice(0, 10);
  await env.DB
    .prepare(
      "INSERT INTO comments (id, doi, kind, author_name, body, status, screen_note, github_issue_url, test_action, created_date, created_at) " +
      "VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, ?, ?)",
    )
    .bind(id, doi, kind, authorName || null, commentBody, guard.testAction || "", createdDate, nowSec)
    .run();
  return jsonResponse({
    ok: true,
    id,
    doi,
    kind,
    status: "pending",
    ...(guard.testAction ? { isolated_test: true } : {}),
  });
}

// --------------------------------------------------------------------------- Worker entrypoints

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/_rp/api/")) {
      try {
        return await handleIntake(request, env, ctx);
      } catch {
        return jsonResponse(
          { ok: false, error: "Submissions are temporarily unavailable. Please try again later or use GitHub." },
          503,
        );
      }
    }
    const response = await fetch(request);
    try {
      const p = record(request, response, env).catch(() => {});
      if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(p);
    } catch (e) {
      // counting must never break the site
    }
    return response;
  },

  async scheduled(event, env, ctx) {
    if (!env || !env.DB) return;
    const nowSec = Math.floor(nowMs(env) / 1000);
    const p = cleanupExpiredHashes(env.DB, nowSec).catch(() => {});
    if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(p);
    else await p;
  },
};
