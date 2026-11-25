// node --test deploy/cloudflare/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker, { kindOf, pageOf, shouldSkip } from "./worker.js";

export const REAL_USER_AGENTS = [
  // User-triggered AI agents & RunPapers CLI (8)
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)", "agent"],
  ["Claude-User (claude-code/2.1; +https://support.anthropic.com/)", "agent"],
  ["Claude-Code/1.0.24 (+https://anthropic.com)", "agent"],
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot", "agent"],
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)", "agent"],
  ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Google-Agent", "agent"],
  ["Mozilla/5.0 (compatible; MistralAI-User/1.0; +https://docs.mistral.ai/robots)", "agent"],
  ["runpapers/0.2 (+https://runpapers.com)", "agent"],

  // Training & search crawlers (10)
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)", "crawler"],
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", "crawler"],
  ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot", "crawler"],
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +searchbot@anthropic.com)", "crawler"],
  ["Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)", "crawler"],
  ["Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "crawler"],
  ["Mozilla/5.0 (compatible; Google-Extended)", "crawler"],
  ["CCBot/2.0 (https://commoncrawl.org/faq/)", "crawler"],
  ["Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; https://zhanzhang.toutiao.com/)", "crawler"],
  ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/600.2.5 (KHTML, like Gecko) Version/8.0.2 Safari/600.2.5 (Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)", "crawler"],

  // Command-line & library HTTP clients (6)
  ["curl/8.5.0", "script"],
  ["Wget/1.21.4 (linux-gnu)", "script"],
  ["python-requests/2.32.3", "script"],
  ["python-httpx/0.27.2", "script"],
  ["Python-urllib/3.12", "script"],
  ["", "script"],

  // Interactive browsers (5)
  ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "person"],
  ["Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", "person"],
  ["Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15", "person"],
  ["Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0", "person"],
  ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0", "person"],
];

test("24+ real user agents are classified accurately", () => {
  assert.ok(REAL_USER_AGENTS.length >= 24, `expected >= 24 UA cases, got ${REAL_USER_AGENTS.length}`);
  for (const [ua, want] of REAL_USER_AGENTS) {
    assert.equal(kindOf(ua), want, `UA=${ua}`);
  }
});

test("pages map to papers and pack files are excluded", () => {
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/"), { paper: "10-1016-j-cell-2026-10-012", type: "html" });
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/index.html"), { paper: "10-1016-j-cell-2026-10-012", type: "html" });
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/AGENT.md"), { paper: "10-1016-j-cell-2026-10-012", type: "agent" });
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/index.md"), { paper: "10-1016-j-cell-2026-10-012", type: "md" });
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/pack.json"), { paper: "10-1016-j-cell-2026-10-012", type: "pack" });
  assert.equal(pageOf("/papers/10-1016-j-cell-2026-10-012/pack/SKILL.md").type, "");
  assert.equal(pageOf("/papers/10-1016-j-cell-2026-10-012/pack/recipes/fig1b.py").type, "");
  assert.equal(pageOf("/papers/10-1016-j-cell-2026-10-012/figures/fig1b-panel.png").type, "");
  assert.deepEqual(pageOf("/"), { paper: "", type: "html" });
  assert.deepEqual(pageOf("/papers/"), { paper: "", type: "html" });
  assert.deepEqual(pageOf("/papers/index.md"), { paper: "", type: "md" });
  assert.equal(pageOf("/style.css").type, "");
  assert.equal(pageOf("/index.json").type, "");
});

function makeEnv(points, store) {
  globalThis.caches = { default: { match: async (r) => store.has(r.url), put: async (r) => store.add(r.url) } };
  return { SALT: "s", HITS: { writeDataPoint: (p) => points.push(p) } };
}

test("serves the page unchanged, sets no cookie, stores no IP anywhere, and deduplicates within an hour", async () => {
  const points = [], store = new Set(), waits = [];
  globalThis.fetch = async () => new Response("<html>ok</html>", { status: 200, headers: { "Content-Type": "text/html" } });
  const ctx = { waitUntil: (p) => waits.push(p) };
  const clientIp = "203.0.113.9";
  const req = () => new Request("https://runpapers.com/papers/10-1016-j-cell-2026-10-012/AGENT.md", {
    headers: { "User-Agent": "Claude-User/1.0", "CF-Connecting-IP": clientIp, "X-Forwarded-For": "2001:db8::42" },
  });
  const e = makeEnv(points, store);
  const r1 = await worker.fetch(req(), e, ctx);
  assert.equal(r1.status, 200);
  assert.equal(r1.headers.get("set-cookie"), null);
  assert.equal(await r1.text(), "<html>ok</html>");

  const r2 = await worker.fetch(req(), e, ctx);
  assert.equal(r2.headers.get("set-cookie"), null);
  await Promise.all(waits);

  assert.equal(points.length, 1);
  assert.deepEqual(points[0].blobs, [
    "agent",
    "agent",
    "10-1016-j-cell-2026-10-012",
    "",
    "/papers/10-1016-j-cell-2026-10-012/AGENT.md",
  ]);
  const dumped = JSON.stringify({ points, cacheKeys: [...store] });
  assert.ok(!dumped.includes(clientIp), "IPv4 address must never appear in points or cache keys");
  assert.ok(!dumped.includes("2001:db8::42"), "IPv6 address must never appear in points or cache keys");
});

test("skips counting on X-RunPapers-Internal: 1 and X-RunPapers-NoCount: 1, while allowing st-* and get actions", async () => {
  const points = [], store = new Set(), waits = [];
  globalThis.fetch = async () => new Response("{}", { status: 200 });
  const ctx = { waitUntil: (p) => waits.push(p) };
  const e = makeEnv(points, store);
  const url = "https://runpapers.com/papers/10-1016-j-cell-2026-10-012/pack.json";

  assert.equal(shouldSkip(new Headers({ "X-RunPapers-Internal": "1" })), true);
  assert.equal(shouldSkip(new Headers({ "X-RunPapers-NoCount": "1" })), true);
  assert.equal(shouldSkip(new Headers({ "X-RunPapers-Action": "st-a1b2c3d4" })), false);

  // Internal CI / usertest run: served 200, never recorded, cache untouched.
  const rInternal = await worker.fetch(new Request(url, {
    headers: { "User-Agent": "runpapers/0.2 (+https://runpapers.com)", "X-RunPapers-Action": "get", "X-RunPapers-Internal": "1" },
  }), e, ctx);
  assert.equal(rInternal.status, 200);

  // DO_NOT_TRACK=1 user: served 200, never recorded, cache untouched.
  const rNoCount = await worker.fetch(new Request(url, {
    headers: { "User-Agent": "runpapers/0.2 (+https://runpapers.com)", "X-RunPapers-Action": "get", "X-RunPapers-NoCount": "1" },
  }), e, ctx);
  assert.equal(rNoCount.status, 200);

  await Promise.all(waits);
  assert.equal(points.length, 0);
  assert.equal(store.size, 0);

  // Self-test action (st-<hex>) without skip headers IS recorded so usage-selftest can read it back, and deduplicates.
  waits.length = 0;
  await worker.fetch(new Request(url, {
    headers: { "User-Agent": "curl/8.5.0", "X-RunPapers-Action": "st-deadbeef", "CF-Connecting-IP": "198.51.100.7" },
  }), e, ctx);
  await worker.fetch(new Request(url, {
    headers: { "User-Agent": "curl/8.5.0", "X-RunPapers-Action": "st-deadbeef", "CF-Connecting-IP": "198.51.100.7" },
  }), e, ctx);

  // Real CLI `rp get` download action IS recorded.
  await worker.fetch(new Request(url, {
    headers: { "User-Agent": "runpapers/0.2 (+https://runpapers.com)", "X-RunPapers-Action": "get", "CF-Connecting-IP": "198.51.100.8" },
  }), e, ctx);
  await Promise.all(waits);

  assert.equal(points.length, 2);
  assert.deepEqual(points[0].blobs, ["script", "pack", "10-1016-j-cell-2026-10-012", "st-deadbeef", "/papers/10-1016-j-cell-2026-10-012/pack.json"]);
  assert.deepEqual(points[1].blobs, ["agent", "pack", "10-1016-j-cell-2026-10-012", "get", "/papers/10-1016-j-cell-2026-10-012/pack.json"]);
});

test("fails open when Analytics Engine or cache is missing or throws, and ignores 404s", async () => {
  const url = "https://runpapers.com/papers/10-1016-j-cell-2026-10-012/";
  globalThis.fetch = async () => new Response("<html>paper</html>", { status: 200 });
  globalThis.caches = { default: { match: async () => false, put: async () => {} } };

  // 1. Synchronous throw in writeDataPoint
  const syncBroken = { SALT: "s", HITS: { writeDataPoint: () => { throw new Error("WAE sync down"); } } };
  const waits = [];
  const r1 = await worker.fetch(new Request(url, { headers: { "User-Agent": "Claude-User/1.0" } }), syncBroken, { waitUntil: (p) => waits.push(p) });
  assert.equal(r1.status, 200);
  assert.equal(await r1.text(), "<html>paper</html>");
  assert.equal(r1.headers.get("set-cookie"), null);

  // 2. Async rejection in writeDataPoint
  const asyncBroken = { SALT: "s", HITS: { writeDataPoint: async () => { throw new Error("WAE async down"); } } };
  const r2 = await worker.fetch(new Request(url, { headers: { "User-Agent": "Claude-User/1.0" } }), asyncBroken, { waitUntil: (p) => waits.push(p) });
  assert.equal(r2.status, 200);

  // 3. Missing HITS binding or missing env
  const r3 = await worker.fetch(new Request(url), {}, { waitUntil: (p) => waits.push(p) });
  assert.equal(r3.status, 200);
  const r4 = await worker.fetch(new Request(url), null, null);
  assert.equal(r4.status, 200);

  // 4. Broken edge cache
  globalThis.caches = { default: { match: async () => { throw new Error("cache down"); }, put: async () => {} } };
  const r5 = await worker.fetch(new Request(url), syncBroken, { waitUntil: (p) => waits.push(p) });
  assert.equal(r5.status, 200);
  await Promise.all(waits);

  // 5. 404 responses are served unchanged and never counted
  const points = [], store = new Set(), waits404 = [];
  globalThis.fetch = async () => new Response("not found", { status: 404 });
  const e = makeEnv(points, store);
  const r404 = await worker.fetch(new Request("https://runpapers.com/papers/10-1016-j-cell-2026-10-012/missing.html", {
    headers: { "User-Agent": "Mozilla/5.0 Chrome/131.0" },
  }), e, { waitUntil: (p) => waits404.push(p) });
  await Promise.all(waits404);
  assert.equal(r404.status, 404);
  assert.equal(points.length, 0);
});
