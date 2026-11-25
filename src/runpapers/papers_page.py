"""Static `/papers/` search & filter page (`papers/index.html`, `papers/index.md`) and self-hosted `/search.js`.

Uses the five controlled tag groups only (Species, Tissue/cell, Data type, Disease, Collection) with zero external
libraries, full server-side HTML readability without JavaScript, DOM-safe client updates (`createElement`/`textContent`),
bidirectional URL query sync, and available-before-requested ordering."""
import datetime
import html
import json

from . import ids, requests_log, search, vocab

PAPERS_CSS = """
:root{--rp-hematoxylin:#2A2C6B;--rp-eosin:#D9466F;--rp-eosin-ink:#C2335E;--rp-eosin-wash:#FCEEF2;
--rp-slide:#F7F7FB;--rp-coverslip:#E3E2EE;--rp-counterstain:#5D5A85;
--rp-font-sans:"IBM Plex Sans",-apple-system,"Segoe UI",Roboto,sans-serif;
--rp-font-serif:"Source Serif 4",Georgia,serif}
header .wrap{flex-wrap:wrap;height:auto;min-height:58px;padding-top:8px;padding-bottom:8px;gap:6px 18px}
.papers-head{padding:24px 0 8px}
.papers-head h1{color:var(--rp-hematoxylin);margin:8px 0 6px}
.papers-sub{color:var(--rp-counterstain);font-size:16px;margin:0 0 16px;max-width:720px}
.papers-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}
.papers-q{flex:1 1 260px;min-width:0;padding:10px 13px;border:1px solid var(--rp-coverslip);border-radius:9px;
font:16px/1.3 var(--rp-font-sans);color:var(--rp-hematoxylin);background:#fff}
.papers-q:focus,.papers-sort:focus{outline:2px solid var(--rp-eosin-ink);outline-offset:1px}
.papers-sort-wrap{display:flex;align-items:center;gap:6px;font-size:14px;color:var(--rp-counterstain)}
.papers-sort{padding:9px 10px;border:1px solid var(--rp-coverslip);border-radius:9px;background:#fff;
color:var(--rp-hematoxylin);font:14px/1.3 var(--rp-font-sans)}
.papers-submit{padding:9px 14px;border:0;border-radius:9px;background:var(--rp-eosin-ink);color:#fff;
font:600 14px/1.3 var(--rp-font-sans);cursor:pointer}
.js-ready .papers-submit{display:none}
.papers-meta-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;
margin:0 0 14px;font-size:14px;color:var(--rp-counterstain)}
.papers-clear{border:1px solid var(--rp-coverslip);background:#fff;color:var(--rp-eosin-ink);border-radius:7px;
padding:4px 10px;font:600 13px/1.3 var(--rp-font-sans);cursor:pointer}
.papers-layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:24px;align-items:start}
.papers-filters{background:var(--rp-slide);border:1px solid var(--rp-coverslip);border-radius:12px;padding:14px}
.filter-group{border:0;margin:0 0 14px;padding:0;min-width:0}
.filter-group:last-child{margin-bottom:0}
.filter-legend{font-weight:700;font-size:13px;letter-spacing:.01em;color:var(--rp-hematoxylin);margin:0 0 6px;padding:0}
.filter-list{display:flex;flex-direction:column;gap:4px;max-height:220px;overflow-y:auto;padding-right:2px}
.filter-opt{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:13.5px;
line-height:1.35;color:var(--rp-hematoxylin);cursor:pointer;padding:2px 0}
.filter-opt-left{display:flex;align-items:baseline;gap:7px;min-width:0}
.filter-opt input{margin:0;accent-color:var(--rp-eosin-ink);flex:0 0 auto}
.filter-opt.zero{color:var(--rp-counterstain);opacity:.72}
.filter-count{font-size:12px;color:var(--rp-counterstain);font-variant-numeric:tabular-nums;flex:0 0 auto}
.papers-main{min-width:0}
.papers-section-title{font-size:15px;font-weight:700;color:var(--rp-counterstain);margin:24px 0 10px;
padding-top:14px;border-top:1px solid var(--rp-coverslip)}
.paper-row{border:1px solid var(--rp-coverslip);border-radius:12px;padding:15px 17px;margin:0 0 12px;background:#fff;
overflow-wrap:anywhere}
.paper-row-requested{background:var(--rp-slide)}
.paper-title-line{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;margin:0 0 4px}
.paper-title{font:600 18.5px/1.32 var(--rp-font-serif);color:var(--rp-hematoxylin)}
a.paper-title:hover{color:var(--rp-eosin-ink);text-decoration:underline}
.flag-new{display:inline-block;font:700 11px/1.4 var(--rp-font-sans);padding:1px 7px;border-radius:10px;
background:var(--rp-eosin-wash);color:var(--rp-hematoxylin);border:1px solid var(--rp-coverslip)}
.paper-cite{font-size:13.5px;color:var(--rp-counterstain);margin:0 0 7px}
.paper-cite a{color:var(--rp-eosin-ink)}
.paper-summary{font-size:14.5px;color:var(--rp-hematoxylin);margin:0 0 8px}
.paper-tags{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}
.tag-chip{display:inline-block;font-size:12px;line-height:1.35;padding:2px 8px;border-radius:999px;
background:var(--rp-slide);border:1px solid var(--rp-coverslip);color:var(--rp-hematoxylin)}
.paper-row-requested .tag-chip{background:#fff}
.paper-panels{font-size:13.5px;color:var(--rp-hematoxylin);margin:6px 0 0;font-weight:500}
.paper-usage{font-size:12.5px;color:var(--rp-counterstain);margin:6px 0 0}
.paper-req-line{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:6px 0 4px;font-size:13.5px}
.req-status{display:inline-block;font-weight:600;padding:2px 9px;border-radius:999px;
background:var(--rp-eosin-wash);color:var(--rp-hematoxylin)}
.vote-link{font-weight:600;color:var(--rp-eosin-ink)}
.zero-box{border:1px solid var(--rp-coverslip);background:var(--rp-slide);border-radius:12px;padding:22px 20px;margin:8px 0}
.zero-msg{margin:0 0 12px;color:var(--rp-hematoxylin);font-size:15px}
.btn-request{display:inline-block;background:var(--rp-eosin-ink);color:#fff;font-weight:600;font-size:14px;
padding:8px 14px;border-radius:8px;text-decoration:none}
.btn-request:hover{text-decoration:none;opacity:.92}
@media(max-width:820px){
  .papers-layout{grid-template-columns:1fr;gap:14px}
  .filter-list{max-height:170px}
}
"""

SEARCH_JS = r"""/* Self-hosted five-group search, filter, sort, and URL sync for /papers/ (zero external libraries). */
(function () {
  "use strict";

  const GROUPS = ["species", "tissue_cell", "data_type", "disease", "collection"];
  const GROUP_TITLES = {
    species: "Species",
    tissue_cell: "Tissue/cell",
    data_type: "Data type",
    disease: "Disease",
    collection: "Collection"
  };
  const STOPWORDS = new Set([
    "a", "an", "and", "are", "as", "at", "across", "about", "between", "by", "compare", "data",
    "do", "does", "for", "from", "how", "in", "into", "is", "of", "on", "or", "paper", "papers",
    "show", "study", "studies", "that", "the", "their", "to", "using", "what", "which", "with"
  ]);
  const ID_PREFIX_RX = /^(?:https?:\/\/(?:dx\.)?doi\.org\/|https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/|doi:|pmid:)/i;
  const rxCache = new Map();

  function escapeRx(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function termRx(v) {
    let cached = rxCache.get(v);
    if (cached) return cached;
    const pat = (v.length <= 4 || /^\d+$/.test(v) || v.includes("/"))
      ? "(?<![a-z0-9])" + escapeRx(v) + "(?![a-z0-9])"
      : "(?<![a-z0-9])" + escapeRx(v);
    cached = new RegExp(pat);
    rxCache.set(v, cached);
    return cached;
  }

  function termInText(v, text) {
    if (!v || !text) return false;
    return termRx(v).test(text);
  }

  function buildVocabIndex(vocabObj) {
    const raw = vocabObj || {};
    const groups = {};
    const byLabel = {};
    const bySlug = {};
    const lookup = {};
    const synSlugs = {};
    const exclusiveAliases = {};
    const groupExpand = {};
    const globalExpand = {};

    for (const g of GROUPS) {
      const terms = Array.isArray(raw[g]) ? raw[g] : [];
      groups[g] = terms;
      byLabel[g] = {};
      bySlug[g] = {};
      lookup[g] = {};
      synSlugs[g] = {};
      exclusiveAliases[g] = {};
      groupExpand[g] = {};

      const termAliases = {};
      for (const t of terms) {
        const slug = String(t.slug || "");
        const label = String(t.label || "");
        byLabel[g][label] = t;
        bySlug[g][slug] = t;
        const aliases = [slug, label];
        if (t.scientific_name) aliases.push(String(t.scientific_name));
        if (Array.isArray(t.synonyms)) {
          for (const s of t.synonyms) aliases.push(String(s));
        }
        const lowerSet = new Set();
        for (const a of aliases) {
          const low = a.trim().toLowerCase();
          if (low) lowerSet.add(low);
        }
        termAliases[slug] = lowerSet;
        for (const low of lowerSet) {
          if (!(low in lookup[g])) lookup[g][low] = t;
          if (!synSlugs[g][low]) synSlugs[g][low] = new Set();
          synSlugs[g][low].add(slug);
        }
      }
      for (const t of terms) {
        lookup[g][String(t.slug).toLowerCase()] = t;
        lookup[g][String(t.label).toLowerCase()] = t;
        if (t.scientific_name) lookup[g][String(t.scientific_name).toLowerCase()] = t;
      }
      for (const [slug, aset] of Object.entries(termAliases)) {
        const excl = new Set();
        for (const low of aset) {
          if (synSlugs[g][low].size === 1) excl.add(low);
        }
        exclusiveAliases[g][slug] = excl;
      }
      for (const [low, owners] of Object.entries(synSlugs[g])) {
        const expanded = new Set();
        if (owners.size === 1) {
          const onlySlug = owners.values().next().value;
          for (const x of exclusiveAliases[g][onlySlug]) expanded.add(x);
        } else {
          expanded.add(low);
          for (const s of owners) {
            for (const x of exclusiveAliases[g][s]) expanded.add(x);
          }
          for (const [otherLow, otherOwners] of Object.entries(synSlugs[g])) {
            if (otherOwners.size > 1) {
              let subset = true;
              for (const os of otherOwners) {
                if (!owners.has(os)) { subset = false; break; }
              }
              if (subset) expanded.add(otherLow);
            }
          }
        }
        groupExpand[g][low] = expanded;
        if (!globalExpand[low]) globalExpand[low] = new Set();
        for (const x of expanded) globalExpand[low].add(x);
      }
    }

    function resolve(group, value) {
      if (!(group in lookup) || typeof value !== "string") return null;
      const q = value.trim();
      if (!q) return null;
      if (q in byLabel[group]) return byLabel[group][q];
      if (q in bySlug[group]) return bySlug[group][q];
      const low = q.toLowerCase();
      if (low in lookup[group]) return lookup[group][low];
      if (low.endsWith("s") && low.length > 3 && (low.slice(0, -1) in lookup[group])) {
        return lookup[group][low.slice(0, -1)];
      }
      return null;
    }

    function resolveSlug(group, value) {
      const t = resolve(group, value);
      return t ? t.slug : null;
    }

    function matchingSlugs(group, value) {
      if (!(group in groups) || typeof value !== "string") return new Set();
      const q = value.trim();
      if (!q) return new Set();
      const low = q.toLowerCase();
      for (const t of groups[group]) {
        if (
          low === String(t.slug).toLowerCase() ||
          low === String(t.label).toLowerCase() ||
          (t.scientific_name && low === String(t.scientific_name).toLowerCase())
        ) {
          return new Set([t.slug]);
        }
      }
      if (synSlugs[group][low]) return new Set(synSlugs[group][low]);
      if (low.endsWith("s") && low.length > 3 && synSlugs[group][low.slice(0, -1)]) {
        return new Set(synSlugs[group][low.slice(0, -1)]);
      }
      return new Set();
    }

    function expand(text, group) {
      const q = String(text || "").trim().toLowerCase();
      if (!q) return new Set();
      const out = new Set([q]);
      const table = (group && groupExpand[group]) ? groupExpand[group] : globalExpand;
      if (table[q]) {
        for (const x of table[q]) out.add(x);
      } else if (q.endsWith("s") && q.length > 3 && table[q.slice(0, -1)]) {
        for (const x of table[q.slice(0, -1)]) out.add(x);
      }
      return out;
    }

    return { groups, byLabel, bySlug, resolve, resolveSlug, matchingSlugs, expand };
  }

  function normalizeDoiCandidate(s) {
    const clean = decodeURIComponent(String(s || "").trim())
      .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
      .replace(/^doi:\s*/i, "")
      .replace(/[.,;:)\]]+$/, "")
      .trim()
      .toLowerCase();
    return /^10\.\d{4,9}\/\S+$/.test(clean) ? clean : null;
  }

  function parseIdentifier(raw) {
    const s = String(raw || "").trim();
    if (!s) return null;
    const pmUrl = s.match(/^https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/(\d{1,9})\/?$/i);
    if (pmUrl) return { kind: "pmid", value: pmUrl[1] };
    const pmPref = s.match(/^pmid:\s*(\d{1,9})$/i);
    if (pmPref) return { kind: "pmid", value: pmPref[1] };
    if (/^\d{1,9}$/.test(s)) return { kind: "pmid", value: s };
    if (/^pmc\d+$/i.test(s)) return { kind: "pmcid", value: s.toUpperCase() };
    const doi = normalizeDoiCandidate(s);
    if (doi) return { kind: "doi", value: doi };
    return null;
  }

  function extractRequestIdentifier(raw) {
    const direct = parseIdentifier(raw);
    if (direct && (direct.kind === "doi" || direct.kind === "pmid")) return direct.value;
    const s = String(raw || "").trim();
    const mDoi = s.match(/10\.\d{4,9}\/[^\s<>",;)\]]+/i);
    if (mDoi) return mDoi[0].toLowerCase();
    const mPmid = s.match(/\bpmid[:\s]+(\d{5,9})\b/i);
    if (mPmid) return mPmid[1];
    return null;
  }

  function requestIssueUrl(repo, rawQuery) {
    const ghRepo = repo || "runpapers/runpapers";
    const ident = extractRequestIdentifier(rawQuery);
    const trimmed = String(rawQuery || "").trim();
    const params = new URLSearchParams();
    params.set("template", "request-paper.yml");
    params.set("labels", "request");
    params.set("title", ident ? "Paper request: " + ident : "Paper request:");
    if (ident) {
      params.set("doi", ident);
    } else if (trimmed) {
      params.set("why", trimmed);
    }
    return "https://github.com/" + ghRepo + "/issues/new?" + params.toString();
  }

  function queryTokens(query) {
    const out = [];
    for (const raw of String(query || "").trim().split(/\s+/)) {
      if (!raw) continue;
      const tok = raw
        .replace(ID_PREFIX_RX, "")
        .replace(/\/+$/, "")
        .replace(/^[,;()[\]{}"']+|[,;()[\]{}"']+$/g, "")
        .toLowerCase();
      if (tok) out.push(tok);
    }
    return out;
  }

  function tokenize(text) {
    const raw = String(text || "").toLowerCase().match(/[a-z0-9][a-z0-9._-]*/g) || [];
    const filtered = raw.filter((t) => !STOPWORDS.has(t));
    return filtered.length ? filtered : raw;
  }

  function idMatch(entry, query) {
    const parsed = parseIdentifier(query);
    if (!parsed) return false;
    if (parsed.kind === "doi") {
      if (String(entry.doi || "").toLowerCase() === parsed.value) return true;
      if (entry.preprint_doi && String(entry.preprint_doi).toLowerCase() === parsed.value) return true;
      return false;
    }
    if (parsed.kind === "pmid") {
      return String(entry.pmid || "") === parsed.value;
    }
    return false;
  }

  function tokenInSearchText(tok, searchText, vocIdx) {
    if (termInText(tok, searchText)) return true;
    if (tok.length >= 4 && tok.endsWith("s") && termInText(tok.slice(0, -1), searchText)) return true;
    for (const variant of vocIdx.expand(tok)) {
      if (termInText(variant, searchText)) return true;
    }
    return false;
  }

  function valueMatches(variants, haystacks) {
    for (const h of haystacks) {
      const hl = String(h || "").toLowerCase();
      if (!hl) continue;
      for (const v of variants) {
        if (termInText(v, hl)) return true;
      }
    }
    return false;
  }

  function scoreEntry(entry, query, vocIdx) {
    const q = String(query || "").trim();
    if (!q) return 1.0;
    if (idMatch(entry, q)) return 1000.0;
    const stext = String(entry.search_text || "");
    const qToks = queryTokens(q);
    if (!qToks.length) return 0.0;
    for (const t of qToks) {
      if (!tokenInSearchText(t, stext, vocIdx)) return 0.0;
    }
    const toks = tokenize(q);
    const useToks = toks.length ? toks : qToks;
    const tagVals = [];
    for (const g of GROUPS) {
      for (const lbl of (entry.tags && entry.tags[g]) || []) tagVals.push(lbl);
    }
    const idTexts = [entry.doi || "", entry.pmid || "", entry.preprint_doi || ""];
    const titles = [entry.title || ""];
    const authors = [entry.first_author || "", entry.senior_author || "", entry.slug || ""];
    const summaries = [entry.summary || "", entry.journal || ""];
    const panels = Array.isArray(entry.panels) ? entry.panels : [];

    let total = 0.0;
    let matched = 0;
    for (const tok of useToks) {
      const variants = vocIdx.expand(tok);
      let s = 0.0;
      if (valueMatches(variants, idTexts)) s += 6.0;
      if (valueMatches(variants, tagVals)) s += 5.0;
      if (valueMatches(variants, titles)) s += 4.0;
      if (valueMatches(variants, authors)) s += 3.0;
      if (valueMatches(variants, summaries)) s += 2.0;
      if (valueMatches(variants, panels)) s += 1.5;
      if (s === 0.0 && tokenInSearchText(tok, stext, vocIdx)) s += 2.0;
      if (s > 0.0) {
        matched += 1;
        total += s;
      }
    }
    if (matched === 0) return 0.0;
    const coverage = matched / useToks.length;
    return Math.round((total * (0.5 + 0.5 * coverage)) * 10000) / 10000;
  }

  function asList(val) {
    if (!val) return [];
    if (Array.isArray(val)) return val.map((x) => String(x).trim()).filter(Boolean);
    const s = String(val).trim();
    return s ? [s] : [];
  }

  function groupFilterOk(group, wantedList, tagSlugsMap, vocIdx) {
    const wanted = asList(wantedList);
    if (!wanted.length) return true;
    const have = new Set((tagSlugsMap && tagSlugsMap[group]) || []);
    if (!have.size) return false;
    const targets = new Set();
    for (const w of wanted) {
      const matched = vocIdx.matchingSlugs(group, w);
      if (matched.size) {
        for (const s of matched) targets.add(s);
      } else if (group === "collection") {
        targets.add(w.trim().toLowerCase());
      } else {
        targets.add("__unknown__:" + w.trim().toLowerCase());
      }
    }
    for (const s of targets) {
      if (have.has(s)) return true;
    }
    return false;
  }

  function usageTotal(entry) {
    const u = entry && entry.usage;
    if (!u || typeof u !== "object") return null;
    for (const k of ["score_30d", "total_30d", "total"]) {
      if (typeof u[k] === "number") return u[k];
    }
    let sum = 0;
    let found = false;
    for (const k of ["human_views", "agent_views", "downloads"]) {
      if (typeof u[k] === "number") { sum += u[k]; found = true; }
    }
    return found ? sum : null;
  }

  function cmpStr(a, b) {
    return a < b ? -1 : (a > b ? 1 : 0);
  }

  function cmpNewest(a, b) {
    const pa = String(a.published_at || "").trim();
    const pb = String(b.published_at || "").trim();
    if (Boolean(pa) !== Boolean(pb)) return pa ? -1 : 1;
    if (pa && pb && pa !== pb) return cmpStr(pb, pa);
    const ya = Number(a.year || 0);
    const yb = Number(b.year || 0);
    if (ya !== yb) return yb - ya;
    const ta = String(a.title || "").toLowerCase();
    const tb = String(b.title || "").toLowerCase();
    if (ta !== tb) return cmpStr(ta, tb);
    return cmpStr(String(a.doi || ""), String(b.doi || ""));
  }

  function compareItems(itemA, itemB, hasQuery, sortMode) {
    const a = itemA.entry;
    const b = itemB.entry;
    const availA = a.status === "available" ? 0 : 1;
    const availB = b.status === "available" ? 0 : 1;
    if (availA !== availB) return availA - availB;

    if (availA === 1) {
      const va = Number(a.votes || 0);
      const vb = Number(b.votes || 0);
      if (va !== vb) return vb - va;
      const ya = Number(a.year || 0);
      const yb = Number(b.year || 0);
      if (ya !== yb) return yb - ya;
      const ta = String(a.title || "").toLowerCase();
      const tb = String(b.title || "").toLowerCase();
      if (ta !== tb) return cmpStr(ta, tb);
      return cmpStr(String(a.doi || ""), String(b.doi || ""));
    }

    if (hasQuery) {
      if (itemA.score !== itemB.score) return itemB.score - itemA.score;
      const ya = Number(a.year || 0);
      const yb = Number(b.year || 0);
      if (ya !== yb) return yb - ya;
      const ta = String(a.title || "").toLowerCase();
      const tb = String(b.title || "").toLowerCase();
      if (ta !== tb) return cmpStr(ta, tb);
      return cmpStr(String(a.doi || ""), String(b.doi || ""));
    }

    if (sortMode === "title") {
      const ta = String(a.title || "").toLowerCase();
      const tb = String(b.title || "").toLowerCase();
      if (ta !== tb) return cmpStr(ta, tb);
      return cmpStr(String(a.doi || ""), String(b.doi || ""));
    }

    if (sortMode === "most_used") {
      const ua = usageTotal(a);
      const ub = usageTotal(b);
      if ((ua !== null) !== (ub !== null)) return ua !== null ? -1 : 1;
      if (ua !== null && ub !== null && ua !== ub) return ub - ua;
    }

    return cmpNewest(a, b);
  }

  function filterSearchIndex(searchData, opts) {
    const options = opts || {};
    const vocIdx = options._vocIdx || buildVocabIndex(searchData && searchData.vocab);
    const entries = Array.isArray(searchData && searchData.entries) ? searchData.entries : [];
    const query = String(options.query || "");
    const hasQuery = Boolean(query.trim());
    const sortMode = options.sort || "most_used";

    const scored = [];
    for (const e of entries) {
      const tslugs = e.tag_slugs || {};
      if (!groupFilterOk("species", options.species, tslugs, vocIdx)) continue;
      if (!groupFilterOk("tissue_cell", options.tissue_cell, tslugs, vocIdx)) continue;
      if (!groupFilterOk("data_type", options.data_type, tslugs, vocIdx)) continue;
      if (!groupFilterOk("disease", options.disease, tslugs, vocIdx)) continue;
      if (!groupFilterOk("collection", options.collection, tslugs, vocIdx)) continue;
      const score = scoreEntry(e, query, vocIdx);
      if (score > 0) scored.push({ score, entry: e });
    }

    scored.sort((a, b) => compareItems(a, b, hasQuery, sortMode));
    const visible = scored.map((x) => x.entry);

    const counts = {};
    for (const g of GROUPS) {
      counts[g] = {};
      for (const t of vocIdx.groups[g]) counts[g][t.slug] = 0;
    }
    for (const e of visible) {
      const ts = e.tag_slugs || {};
      for (const g of GROUPS) {
        for (const slug of ts[g] || []) {
          if (slug in counts[g]) counts[g][slug] += 1;
        }
      }
    }

    return { entries: visible, counts };
  }

  function parseSearchParams(searchStr, vocIdx) {
    const params = new URLSearchParams(String(searchStr || "").replace(/^\?/, ""));
    const state = {
      query: params.get("q") || "",
      species: [],
      tissue_cell: [],
      data_type: [],
      disease: [],
      collection: [],
      sort: "most_used"
    };
    const rawSort = params.get("sort");
    if (rawSort === "newest" || rawSort === "title" || rawSort === "most_used") {
      state.sort = rawSort;
    }
    for (const g of GROUPS) {
      const seen = new Set();
      for (const rawVal of params.getAll(g)) {
        for (const piece of String(rawVal).split(",")) {
          const v = piece.trim();
          if (!v) continue;
          const canonical = (vocIdx && vocIdx.resolveSlug(g, v)) || v.toLowerCase();
          if (!seen.has(canonical)) {
            seen.add(canonical);
            state[g].push(canonical);
          }
        }
      }
    }
    return state;
  }

  function buildSearchParams(state, vocIdx) {
    const params = new URLSearchParams();
    const q = String((state && state.query) || "").trim();
    if (q) params.set("q", q);
    for (const g of GROUPS) {
      const seen = new Set();
      for (const raw of asList(state && state[g])) {
        const slug = (vocIdx && vocIdx.resolveSlug(g, raw)) || raw.trim().toLowerCase();
        if (slug && !seen.has(slug)) {
          seen.add(slug);
          params.append(g, slug);
        }
      }
    }
    if (state && (state.sort === "newest" || state.sort === "title")) {
      params.set("sort", state.sort);
    }
    return params.toString();
  }

  function formatPanelsSentence(panels) {
    const clean = (panels || []).map((p) => String(p || "").trim()).filter(Boolean);
    if (!clean.length) return "";
    if (clean.length === 1) return "Reproduces " + clean[0] + ".";
    if (clean.length === 2) return "Reproduces " + clean[0] + " and " + clean[1] + ".";
    return "Reproduces " + clean.slice(0, -1).join(", ") + " and " + clean[clean.length - 1] + ".";
  }

  function isPublishedWithin7Days(isoStr, nowMs) {
    if (!isoStr) return false;
    const t = Date.parse(isoStr);
    if (Number.isNaN(t)) return false;
    const ref = typeof nowMs === "number" ? nowMs : Date.now();
    const diffDays = (ref - t) / 86400000;
    return diffDays >= -1 && diffDays <= 7;
  }

  function el(doc, tag, className, text) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function buildCitationLine(doc, entry) {
    const line = el(doc, "div", "paper-cite");
    const bits = [];
    if (entry.first_author) bits.push(entry.first_author + " et al.");
    if (entry.journal) bits.push(entry.journal + (entry.year ? " " + entry.year : ""));
    else if (entry.year) bits.push(String(entry.year));
    if (bits.length) {
      line.appendChild(doc.createTextNode(bits.join(", ") + " · "));
    }
    line.appendChild(doc.createTextNode("DOI "));
    const doiLink = el(doc, "a", null, entry.doi);
    doiLink.setAttribute("href", "https://doi.org/" + encodeURIComponent(entry.doi).replace(/%2F/gi, "/"));
    doiLink.setAttribute("rel", "noopener");
    line.appendChild(doiLink);
    if (entry.pmid && /^\d+$/.test(String(entry.pmid))) {
      line.appendChild(doc.createTextNode(" · PMID "));
      const pmLink = el(doc, "a", null, String(entry.pmid));
      pmLink.setAttribute("href", "https://pubmed.ncbi.nlm.nih.gov/" + encodeURIComponent(String(entry.pmid)) + "/");
      pmLink.setAttribute("rel", "noopener");
      line.appendChild(pmLink);
    }
    return line;
  }

  function buildTagChips(doc, tags) {
    const chips = [];
    for (const g of GROUPS) {
      for (const lbl of (tags && tags[g]) || []) {
        chips.push(lbl);
      }
    }
    if (!chips.length) return null;
    const wrap = el(doc, "div", "paper-tags");
    for (const lbl of chips) {
      wrap.appendChild(el(doc, "span", "tag-chip", lbl));
    }
    return wrap;
  }

  function buildAvailableRow(doc, entry) {
    const row = el(doc, "article", "paper-row");
    row.setAttribute("data-doi", entry.doi);
    row.setAttribute("data-status", "available");

    const titleLine = el(doc, "div", "paper-title-line");
    const slug = String(entry.slug || "").replace(/[^a-z0-9-]/g, "");
    const link = el(doc, "a", "paper-title", entry.title || entry.doi);
    link.setAttribute("href", "./" + slug + "/");
    titleLine.appendChild(link);
    if (isPublishedWithin7Days(entry.published_at)) {
      titleLine.appendChild(el(doc, "span", "flag-new", "New"));
    }
    row.appendChild(titleLine);
    row.appendChild(buildCitationLine(doc, entry));

    if (entry.summary) {
      row.appendChild(el(doc, "p", "paper-summary", entry.summary));
    }
    const tagsEl = buildTagChips(doc, entry.tags);
    if (tagsEl) row.appendChild(tagsEl);

    const panelsTxt = formatPanelsSentence(entry.panels);
    if (panelsTxt) {
      row.appendChild(el(doc, "div", "paper-panels", panelsTxt));
    }
    if (entry.usage && typeof entry.usage === "object") {
      const hv = Number(entry.usage.human_views || 0).toLocaleString("en-US");
      const av = Number(entry.usage.agent_views || 0).toLocaleString("en-US");
      const dl = Number(entry.usage.downloads || 0).toLocaleString("en-US");
      row.appendChild(el(doc, "div", "paper-usage", hv + " views by people, " + av + " by AI agents, " + dl + " downloads"));
    }
    return row;
  }

  function buildRequestedRow(doc, entry, repo) {
    const row = el(doc, "article", "paper-row paper-row-requested");
    row.setAttribute("data-doi", entry.doi);
    row.setAttribute("data-status", entry.status || "requested");

    const titleLine = el(doc, "div", "paper-title-line");
    titleLine.appendChild(el(doc, "span", "paper-title", entry.title || entry.doi));
    row.appendChild(titleLine);
    row.appendChild(buildCitationLine(doc, entry));

    const reqLine = el(doc, "div", "paper-req-line");
    const votes = Number(entry.votes || 0);
    const voteWord = votes === 1 ? "1 vote" : votes + " votes";
    let statusTxt = "Requested, " + voteWord;
    let actionTxt = "Vote on GitHub";
    if (entry.status === "in_progress") {
      statusTxt = votes > 0 ? "In progress, " + voteWord : "In progress";
      actionTxt = "Follow or vote on GitHub";
    } else if (entry.status === "not_possible") {
      statusTxt = entry.status_reason ? "Not possible: " + entry.status_reason : "Not possible";
      actionTxt = "Details on GitHub";
    }
    reqLine.appendChild(el(doc, "span", "req-status", statusTxt));

    const rawIssue = String(entry.issue_url || "");
    const safeIssue = rawIssue.startsWith("https://github.com/") ? rawIssue : requestIssueUrl(repo, entry.doi);
    const act = el(doc, "a", "vote-link", actionTxt);
    act.setAttribute("href", safeIssue);
    act.setAttribute("rel", "noopener");
    reqLine.appendChild(act);
    row.appendChild(reqLine);

    const tagsEl = buildTagChips(doc, entry.tags);
    if (tagsEl) row.appendChild(tagsEl);
    return row;
  }

  function renderResults(doc, container, summaryEl, clearBtn, searchData, state, vocIdx, repo) {
    const res = filterSearchIndex(searchData, Object.assign({}, state, { _vocIdx: vocIdx }));
    const visible = res.entries;
    const counts = res.counts;

    for (const g of GROUPS) {
      for (const t of vocIdx.groups[g]) {
        const cEl = doc.querySelector('[data-count-for="' + g + ":" + t.slug + '"]');
        const n = counts[g][t.slug] || 0;
        if (cEl) cEl.textContent = String(n);
        const inp = doc.querySelector('input[type="checkbox"][data-group="' + g + '"][data-slug="' + t.slug + '"]');
        if (inp && inp.closest(".filter-opt")) {
          inp.closest(".filter-opt").classList.toggle("zero", n === 0 && !inp.checked);
        }
      }
    }

    const avail = visible.filter((e) => e.status === "available");
    const rest = visible.filter((e) => e.status !== "available");

    if (summaryEl) {
      const aPart = avail.length === 1 ? "1 available pack" : avail.length + " available packs";
      const rPart = rest.length === 1 ? "1 requested paper" : rest.length + " requested papers";
      summaryEl.textContent = aPart + " · " + rPart;
    }

    const hasActive = Boolean(String(state.query || "").trim()) || GROUPS.some((g) => asList(state[g]).length > 0);
    if (clearBtn) clearBtn.hidden = !hasActive;

    while (container.firstChild) container.removeChild(container.firstChild);

    if (!visible.length) {
      const box = el(doc, "div", "zero-box");
      const qTrim = String(state.query || "").trim();
      const msg = qTrim
        ? 'No pack matches "' + qTrim + '" yet. Request it: papers with the most votes are built first.'
        : "No pack matches the selected filters yet. Request a paper: papers with the most votes are built first.";
      box.appendChild(el(doc, "p", "zero-msg", msg));
      const btn = el(doc, "a", "btn-request", "Request this paper");
      btn.setAttribute("href", requestIssueUrl(repo, qTrim));
      btn.setAttribute("rel", "noopener");
      box.appendChild(btn);
      container.appendChild(box);
      return res;
    }

    for (const e of avail) {
      container.appendChild(buildAvailableRow(doc, e));
    }
    if (rest.length) {
      container.appendChild(el(doc, "h2", "papers-section-title", "Requested and upcoming papers"));
      for (const e of rest) {
        container.appendChild(buildRequestedRow(doc, e, repo));
      }
    }
    return res;
  }

  function initPapersPage(doc, win) {
    const rootEl = doc.getElementById("papers-app");
    if (!rootEl) return null;
    doc.documentElement.classList.add("js-ready");

    const repo = rootEl.getAttribute("data-repo") || "runpapers/runpapers";
    const qInput = doc.getElementById("papers-q");
    const sortSelect = doc.getElementById("papers-sort");
    const resultsEl = doc.getElementById("papers-results");
    const summaryEl = doc.getElementById("papers-summary");
    const clearBtn = doc.getElementById("papers-clear");
    const formEl = doc.getElementById("papers-form");

    let searchData = null;
    const inlineEl = doc.getElementById("rp-search-data");
    if (inlineEl && inlineEl.textContent) {
      try {
        searchData = JSON.parse(inlineEl.textContent);
      } catch (_err) {
        searchData = null;
      }
    }

    let vocIdx = buildVocabIndex(searchData && searchData.vocab);
    let state = parseSearchParams(win.location.search, vocIdx);

    function syncControlsFromState() {
      if (qInput) qInput.value = state.query || "";
      if (sortSelect) sortSelect.value = state.sort || "most_used";
      for (const g of GROUPS) {
        const selected = new Set(state[g] || []);
        const boxes = doc.querySelectorAll('input[type="checkbox"][data-group="' + g + '"]');
        for (const box of boxes) {
          box.checked = selected.has(box.getAttribute("data-slug"));
        }
      }
    }

    function readStateFromControls() {
      const next = {
        query: qInput ? qInput.value : "",
        species: [],
        tissue_cell: [],
        data_type: [],
        disease: [],
        collection: [],
        sort: sortSelect ? sortSelect.value : "most_used"
      };
      for (const g of GROUPS) {
        const boxes = doc.querySelectorAll('input[type="checkbox"][data-group="' + g + '"]:checked');
        for (const box of boxes) {
          next[g].push(box.getAttribute("data-slug"));
        }
      }
      return next;
    }

    function applyAndSyncUrl(pushUrl) {
      if (!searchData || !resultsEl) return;
      renderResults(doc, resultsEl, summaryEl, clearBtn, searchData, state, vocIdx, repo);
      if (pushUrl && win.history && typeof win.history.replaceState === "function") {
        const qs = buildSearchParams(state, vocIdx);
        const targetUrl = win.location.pathname + (qs ? "?" + qs : "") + (win.location.hash || "");
        if (targetUrl !== win.location.pathname + win.location.search + (win.location.hash || "")) {
          win.history.replaceState(null, "", targetUrl);
        }
      }
    }

    if (searchData) {
      syncControlsFromState();
      applyAndSyncUrl(true);
    }

    if (win.location && (win.location.protocol === "http:" || win.location.protocol === "https:") && typeof win.fetch === "function") {
      win.fetch("./search.json")
        .then((r) => (r.ok ? r.json() : null))
        .then((fresh) => {
          if (!fresh || !Array.isArray(fresh.entries)) return;
          searchData = fresh;
          vocIdx = buildVocabIndex(searchData.vocab);
          state = parseSearchParams(win.location.search, vocIdx);
          syncControlsFromState();
          applyAndSyncUrl(false);
        })
        .catch(() => {});
    }

    if (formEl) {
      formEl.addEventListener("submit", function (ev) {
        ev.preventDefault();
        state = readStateFromControls();
        applyAndSyncUrl(true);
      });
    }
    if (qInput) {
      qInput.addEventListener("input", function () {
        state = readStateFromControls();
        applyAndSyncUrl(true);
      });
    }
    if (sortSelect) {
      sortSelect.addEventListener("change", function () {
        state = readStateFromControls();
        applyAndSyncUrl(true);
      });
    }
    rootEl.addEventListener("change", function (ev) {
      const t = ev.target;
      if (t && t.matches && t.matches('input[type="checkbox"][data-group]')) {
        state = readStateFromControls();
        applyAndSyncUrl(true);
      }
    });
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        state = { query: "", species: [], tissue_cell: [], data_type: [], disease: [], collection: [], sort: state.sort || "most_used" };
        syncControlsFromState();
        applyAndSyncUrl(true);
      });
    }
    win.addEventListener("popstate", function () {
      state = parseSearchParams(win.location.search, vocIdx);
      syncControlsFromState();
      applyAndSyncUrl(false);
    });

    return {
      getState: function () { return state; },
      setState: function (next) { state = Object.assign({}, state, next); syncControlsFromState(); applyAndSyncUrl(true); }
    };
  }

  const api = {
    GROUPS,
    GROUP_TITLES,
    buildVocabIndex,
    parseIdentifier,
    extractRequestIdentifier,
    requestIssueUrl,
    queryTokens,
    filterSearchIndex,
    parseSearchParams,
    buildSearchParams,
    formatPanelsSentence,
    renderResults,
    initPapersPage
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof globalThis !== "undefined") {
    globalThis.RunPapersSearch = api;
  }
  if (typeof document !== "undefined" && typeof window !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { initPapersPage(document, window); });
    } else {
      initPapersPage(document, window);
    }
  }
})();
"""


def _esc(val):
    return html.escape(str(val if val is not None else ""))


def _format_panels_sentence(panels):
    clean = [str(p).strip() for p in (panels or []) if p and str(p).strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return f"Reproduces {clean[0]}."
    if len(clean) == 2:
        return f"Reproduces {clean[0]} and {clean[1]}."
    return f"Reproduces {', '.join(clean[:-1])} and {clean[-1]}."


def _is_new(iso_str):
    if not iso_str:
        return False
    try:
        dt = datetime.datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        days = (now_dt - dt).total_seconds() / 86400.0
        return -1.0 <= days <= 7.0
    except ValueError:
        return False


def _citation_html(entry):
    bits = []
    if entry.get("first_author"):
        bits.append(f"{_esc(entry['first_author'])} et al.")
    if entry.get("journal"):
        jn = f"<i>{_esc(entry['journal'])}</i>" + (f" {_esc(entry['year'])}" if entry.get("year") else "")
        bits.append(jn)
    elif entry.get("year"):
        bits.append(_esc(entry["year"]))
    prefix = (", ".join(bits) + " · ") if bits else ""
    doi = entry["doi"]
    pmid_part = (
        f' · PMID <a href="{_esc(ids.pubmed_url(entry["pmid"]))}" rel="noopener">{_esc(entry["pmid"])}</a>'
        if entry.get("pmid") else ""
    )
    return f'<div class="paper-cite">{prefix}DOI <a href="{_esc(ids.doi_url(doi))}" rel="noopener">{_esc(doi)}</a>{pmid_part}</div>'


def _tags_html(tags):
    chips = [lbl for g in vocab.GROUPS for lbl in (tags or {}).get(g, [])]
    if not chips:
        return ""
    return '<div class="paper-tags">' + "".join(f'<span class="tag-chip">{_esc(c)}</span>' for c in chips) + "</div>"


def _available_row_html(entry):
    new_flag = '<span class="flag-new">New</span>' if _is_new(entry.get("published_at")) else ""
    summary_html = f'<p class="paper-summary">{_esc(entry["summary"])}</p>' if entry.get("summary") else ""
    panels_txt = _format_panels_sentence(entry.get("panels"))
    panels_html = f'<div class="paper-panels">{_esc(panels_txt)}</div>' if panels_txt else ""
    usage_html = ""
    if isinstance(entry.get("usage"), dict):
        u = entry["usage"]
        usage_html = (
            f'<div class="paper-usage">{int(u.get("human_views", 0)):,} views by people, '
            f'{int(u.get("agent_views", 0)):,} by AI agents, {int(u.get("downloads", 0)):,} downloads</div>'
        )
    return (
        f'<article class="paper-row" data-doi="{_esc(entry["doi"])}" data-status="available">'
        f'<div class="paper-title-line"><a class="paper-title" href="./{_esc(entry["slug"])}/">{_esc(entry["title"])}</a>{new_flag}</div>'
        f'{_citation_html(entry)}'
        f'{summary_html}'
        f'{_tags_html(entry.get("tags"))}'
        f'{panels_html}'
        f'{usage_html}'
        f'</article>'
    )


def _requested_row_html(entry, repo):
    votes = int(entry.get("votes") or 0)
    vote_word = "1 vote" if votes == 1 else f"{votes} votes"
    st = entry.get("status") or "requested"
    if st == "in_progress":
        status_txt = f"In progress, {vote_word}" if votes > 0 else "In progress"
        action_txt = "Follow or vote on GitHub"
    elif st == "not_possible":
        reason = entry.get("status_reason")
        status_txt = f"Not possible: {reason}" if reason else "Not possible"
        action_txt = "Details on GitHub"
    else:
        status_txt = f"Requested, {vote_word}"
        action_txt = "Vote on GitHub"
    issue = entry.get("issue_url") or requests_log.issue_url(repo, entry["doi"])
    return (
        f'<article class="paper-row paper-row-requested" data-doi="{_esc(entry["doi"])}" data-status="{_esc(st)}">'
        f'<div class="paper-title-line"><span class="paper-title">{_esc(entry["title"])}</span></div>'
        f'{_citation_html(entry)}'
        f'<div class="paper-req-line"><span class="req-status">{_esc(status_txt)}</span>'
        f'<a class="vote-link" href="{_esc(issue)}" rel="noopener">{_esc(action_txt)}</a></div>'
        f'{_tags_html(entry.get("tags"))}'
        f'</article>'
    )


def papers_body_html(search_index, repo="runpapers/runpapers"):
    """Render the `<main>` body for `/papers/index.html` with full server-side rows and inline JSON."""
    initial = search.filter_search_index(search_index)
    entries = initial["entries"]
    counts = initial["counts"]
    vocab_map = search_index.get("vocab") or {}

    avail = [e for e in entries if e.get("status") == "available"]
    rest = [e for e in entries if e.get("status") != "available"]

    filter_groups_html = []
    for g in vocab.GROUPS:
        terms = vocab_map.get(g) or []
        opts = []
        for t in terms:
            slug = t["slug"]
            lbl = t["label"]
            cnt = counts.get(g, {}).get(slug, 0)
            zero_cls = " zero" if cnt == 0 else ""
            opts.append(
                f'<label class="filter-opt{zero_cls}">'
                f'<span class="filter-opt-left">'
                f'<input type="checkbox" name="{_esc(g)}" value="{_esc(slug)}" data-group="{_esc(g)}" data-slug="{_esc(slug)}">'
                f'<span>{_esc(lbl)}</span></span>'
                f'<span class="filter-count" data-count-for="{_esc(g)}:{_esc(slug)}">{cnt}</span>'
                f'</label>'
            )
        filter_groups_html.append(
            f'<fieldset class="filter-group">'
            f'<legend class="filter-legend">{_esc(vocab.GROUP_TITLES[g])}</legend>'
            f'<div class="filter-list">{"".join(opts)}</div>'
            f'</fieldset>'
        )

    rows_html = []
    if not entries:
        req_url = requests_log.issue_url(repo)
        rows_html.append(
            f'<div class="zero-box">'
            f'<p class="zero-msg">No papers are listed yet. Request a paper: papers with the most votes are built first.</p>'
            f'<a class="btn-request" href="{_esc(req_url)}" rel="noopener">Request this paper</a>'
            f'</div>'
        )
    else:
        for e in avail:
            rows_html.append(_available_row_html(e))
        if rest:
            rows_html.append('<h2 class="papers-section-title">Requested and upcoming papers</h2>')
            for e in rest:
                rows_html.append(_requested_row_html(e, repo))

    a_part = "1 available pack" if len(avail) == 1 else f"{len(avail)} available packs"
    r_part = "1 requested paper" if len(rest) == 1 else f"{len(rest)} requested papers"
    summary_txt = f"{a_part} · {r_part}"

    safe_json = (
        json.dumps(search_index, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )

    return (
        f'<div id="papers-app" data-repo="{_esc(repo)}">'
        f'<div class="papers-head"><h1>Papers</h1>'
        f'<p class="papers-sub">Published papers your own AI agent can run: reproduce the figures from the original data, then ask your own question.</p></div>'
        f'<form id="papers-form" class="papers-bar" method="get" action="">'
        f'<input id="papers-q" class="papers-q" type="search" name="q" '
        f'placeholder="Search by title, DOI, PMID, gene, cell type or species" aria-label="Search papers">'
        f'<label class="papers-sort-wrap" for="papers-sort">Sort '
        f'<select id="papers-sort" class="papers-sort" name="sort">'
        f'<option value="most_used">Most used</option>'
        f'<option value="newest">Newest</option>'
        f'<option value="title">Title</option>'
        f'</select></label>'
        f'<button type="submit" class="papers-submit">Filter</button>'
        f'</form>'
        f'<div class="papers-meta-bar">'
        f'<span id="papers-summary" aria-live="polite">{_esc(summary_txt)}</span>'
        f'<button type="button" id="papers-clear" class="papers-clear" hidden>Clear filters</button>'
        f'</div>'
        f'<div class="papers-layout">'
        f'<aside class="papers-filters" aria-label="Filter papers by tag">{"".join(filter_groups_html)}</aside>'
        f'<section id="papers-results" class="papers-main" aria-label="Matching papers">{"".join(rows_html)}</section>'
        f'</div>'
        f'<script id="rp-search-data" type="application/json">{safe_json}</script>'
        f'</div>'
    )


def papers_md(search_index, base, install="uvx runpapers", repo="runpapers/runpapers"):
    """Markdown twin `/papers/index.md` for AI agents (zero stage, badge, or tier strings)."""
    entries = search_index.get("entries") or []
    avail = [e for e in entries if e.get("status") == "available"]
    rest = [e for e in entries if e.get("status") != "available"]
    lines = [
        "# Papers · RunPapers",
        "",
        "Published papers your own AI agent can run: reproduce the figures from the original data, then ask your own question.",
        "",
        f"- Machine-readable search index: `{base}/papers/search.json`",
        f"- CLI search: `{install} search \"<query>\" --species <slug> --tissue-cell <slug> --data-type <slug> --disease <slug> --collection <slug> --json`",
        "",
        f"## Available packs ({len(avail)})",
        "",
    ]
    if avail:
        for e in avail:
            pmid_txt = f" · PMID {e['pmid']}" if e.get("pmid") else ""
            tag_list = [lbl for g in vocab.GROUPS for lbl in (e.get("tags") or {}).get(g, [])]
            tag_txt = f" · Tags: {', '.join(tag_list)}" if tag_list else ""
            panels_txt = _format_panels_sentence(e.get("panels"))
            p_part = f" {panels_txt}" if panels_txt else ""
            lines.append(
                f"- **[{e['title']}]({base}/papers/{e['slug']}/index.md)** — "
                f"{e.get('first_author', '')} et al., *{e.get('journal', '')}* {e.get('year', '')} · "
                f"DOI {e['doi']}{pmid_txt}.{p_part}{tag_txt}"
            )
    else:
        lines.append("- No packs available yet.")

    if rest:
        lines += ["", f"## Requested and upcoming papers ({len(rest)})", ""]
        for e in rest:
            pmid_txt = f" · PMID {e['pmid']}" if e.get("pmid") else ""
            votes = int(e.get("votes") or 0)
            vote_word = "1 vote" if votes == 1 else f"{votes} votes"
            st = e.get("status") or "requested"
            if st == "in_progress":
                st_txt = f"In progress, {vote_word}" if votes > 0 else "In progress"
            elif st == "not_possible":
                st_txt = f"Not possible: {e['status_reason']}" if e.get("status_reason") else "Not possible"
            else:
                st_txt = f"Requested, {vote_word}"
            issue = e.get("issue_url") or requests_log.issue_url(repo, e["doi"])
            au = f"{e['first_author']} et al., " if e.get("first_author") else ""
            jn = f"*{e['journal']}* {e.get('year', '')} · " if e.get("journal") else ""
            lines.append(
                f"- **{e['title']}** — {au}{jn}DOI {e['doi']}{pmid_txt} · {st_txt} · [Vote on GitHub]({issue})"
            )
    return "\n".join(lines) + "\n"
