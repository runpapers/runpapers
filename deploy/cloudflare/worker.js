// RunPapers usage counter (Cloudflare Worker on runpapers.com/*). Spec: usage numbers and status history.
//
// For every page request it serves the page from GitHub Pages unchanged, then records one data point in Workers
// Analytics Engine: who asked (person, agent, crawler or script), what (page, AGENT.md, markdown, pack.json),
// which paper, and whether the RunPapers tool marked it as a download. It stores no addresses and sets no cookies.
// Requests carrying X-RunPapers-Internal: 1 or X-RunPapers-NoCount: 1 are never recorded.
// Repeats from the same visitor within an hour are not counted; the visitor key is a hash that changes daily and
// lives only in the edge cache for that hour. If anything here fails, the page is still served.

const AGENTS = /(Claude-User|Claude-Code|ChatGPT-User|Perplexity-User|Google-Agent|Gemini-CLI|MistralAI-User|DuckAssistBot|codex|antigravity|cursor|runpapers)/i;
const CRAWLERS = /(bot\b|bot\/|crawler|spider|crawl|slurp|GPTBot|ClaudeBot|Claude-SearchBot|anthropic-ai|CCBot|Google-Extended|OAI-SearchBot|PerplexityBot|Bytespider|Amazonbot|Applebot|facebookexternalhit|Meta-External|bingpreview|Diffbot|ImagesiftBot|Timpibot)/i;
const SCRIPTS = /^(curl|wget|python-requests|python-urllib|python-httpx|aiohttp|httpx|go-http-client|node-fetch|undici|node\b|axios|okhttp|java\/|libwww)/i;

export function kindOf(ua) {
  if (!ua) return "script";
  if (AGENTS.test(ua)) return "agent";
  if (CRAWLERS.test(ua)) return "crawler";
  if (SCRIPTS.test(ua)) return "script";
  if (/Mozilla\/5\.0/.test(ua)) return "person";
  return "script";
}

export function pageOf(path) {
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

async function digest(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function record(request, response, env) {
  if (!env || !env.HITS || !["GET", "HEAD"].includes(request.method) || response.status >= 400) return;
  if (shouldSkip(request.headers)) return;
  const url = new URL(request.url);
  const { paper, type } = pageOf(url.pathname);
  if (!type) return;
  const ua = request.headers.get("User-Agent") || "";
  const kind = kindOf(ua);
  const action = (request.headers.get("X-RunPapers-Action") || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 16);
  const day = new Date().toISOString().slice(0, 10);
  const visitor = await digest(`${env.SALT || ""}|${day}|${request.headers.get("CF-Connecting-IP") || ""}|${ua}`);
  const key = new Request(`https://${url.hostname}/__seen/${await digest(`${visitor}|${url.pathname}|${action}`)}`);
  const cache = caches.default;
  if (await cache.match(key)) return;   // same visitor, same page, within the hour
  await cache.put(key, new Response("1", { headers: { "Cache-Control": "max-age=3600" } }));
  await env.HITS.writeDataPoint({
    blobs: [kind, type, paper, action, url.pathname.slice(0, 200)],
    doubles: [1],
    indexes: [paper || "site"],
  });
}

export default {
  async fetch(request, env, ctx) {
    const response = await fetch(request);
    try {
      const p = record(request, response, env).catch(() => {});
      if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(p);
    } catch (e) {
      // counting must never break the site
    }
    return response;
  },
};
