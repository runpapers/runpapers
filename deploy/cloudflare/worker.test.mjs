// node --test deploy/cloudflare/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker, { kindOf, pageOf } from "./worker.js";

test("user agents are classified", () => {
  const cases = {
    "Claude-User (claude-code/2.1; +https://support.anthropic.com/)": "agent",
    "ChatGPT-User/1.0; +https://openai.com/bot": "agent",
    "runpapers/0.1 (+https://runpapers.com)": "agent",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)": "crawler",
    "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)": "crawler",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)": "crawler",
    "curl/8.5.0": "script",
    "python-requests/2.32.3": "script",
    "": "script",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15": "person",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36": "person",
  };
  for (const [ua, want] of Object.entries(cases)) assert.equal(kindOf(ua), want, ua);
});

test("pages map to papers", () => {
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/"), { paper: "10-1016-j-cell-2026-10-012", type: "html" });
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/AGENT.md"), { paper: "10-1016-j-cell-2026-10-012", type: "agent" });
  assert.deepEqual(pageOf("/papers/10-1016-j-cell-2026-10-012/pack.json"), { paper: "10-1016-j-cell-2026-10-012", type: "pack" });
  assert.equal(pageOf("/papers/10-1016-j-cell-2026-10-012/pack/recipes/fig1b.py").type, "");
  assert.deepEqual(pageOf("/"), { paper: "", type: "html" });
  assert.equal(pageOf("/style.css").type, "");
});

function env(points, store) {
  globalThis.caches = { default: { match: async (r) => store.has(r.url), put: async (r) => store.add(r.url) } };
  return { SALT: "s", HITS: { writeDataPoint: (p) => points.push(p) } };
}

test("serves the page unchanged, counts once per visitor per hour, and survives a broken counter", async () => {
  const points = [], store = new Set(), waits = [];
  globalThis.fetch = async () => new Response("<html>ok</html>", { status: 200 });
  const ctx = { waitUntil: (p) => waits.push(p) };
  const req = () => new Request("https://runpapers.com/papers/10-1016-j-cell-2026-10-012/AGENT.md",
    { headers: { "User-Agent": "Claude-User", "CF-Connecting-IP": "203.0.113.9" } });
  const e = env(points, store);
  const r1 = await worker.fetch(req(), e, ctx);
  assert.equal(await r1.text(), "<html>ok</html>");
  await worker.fetch(req(), e, ctx);
  await Promise.all(waits);
  assert.equal(points.length, 1);
  assert.deepEqual(points[0].blobs.slice(0, 3), ["agent", "agent", "10-1016-j-cell-2026-10-012"]);
  assert.ok(!JSON.stringify(points).includes("203.0.113.9"));   // no address stored
  const broken = { SALT: "s", HITS: { writeDataPoint: () => { throw new Error("down"); } } };
  globalThis.caches = { default: { match: async () => false, put: async () => {} } };
  const r3 = await worker.fetch(req(), broken, { waitUntil: (p) => p });
  assert.equal(r3.status, 200);
});
