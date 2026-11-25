// End-to-end tests for self-hosted /search.js, /papers/index.html, /papers/index.md, and /papers/search.json.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, "..");
const VENV_PY = path.join(ROOT, ".venv", "bin", "python");
const PYTHON = fs.existsSync(VENV_PY) ? VENV_PY : "python3";
const require = createRequire(import.meta.url);

const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "rp-search-ui-"));
const siteDir = path.join(tmpRoot, "site");

execFileSync(PYTHON, ["-m", "runpapers.cli", "site", "build", "--out", siteDir, "--base-url", "https://runpapers.com", "--include-unreleased"], {
  cwd: ROOT,
  env: { ...process.env, RUNPAPERS_HOME: ROOT, PYTHONPATH: path.join(ROOT, "src") },
  stdio: "pipe",
});

const SearchUI = require(path.join(siteDir, "search.js"));
const searchJsonRaw = fs.readFileSync(path.join(siteDir, "papers", "search.json"), "utf8");
const papersHtmlRaw = fs.readFileSync(path.join(siteDir, "papers", "index.html"), "utf8");
const papersMdRaw = fs.readFileSync(path.join(siteDir, "papers", "index.md"), "utf8");
const searchJsRaw = fs.readFileSync(path.join(siteDir, "search.js"), "utf8");
const searchData = JSON.parse(searchJsonRaw);

test.after(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

// Minimal DOM harness sufficient to exercise renderResults() and initPapersPage() without external libraries.
function createMiniDom(initialSearch = "") {
  class MiniElement {
    constructor(doc, tagName) {
      this.ownerDocument = doc;
      this.tagName = String(tagName).toUpperCase();
      this.className = "";
      this.attributes = new Map();
      this.children = [];
      this.parentNode = null;
      this.hidden = false;
      this.checked = false;
      this.value = "";
      this._text = "";
      this._listeners = new Map();
      const self = this;
      this.classList = {
        add(...cls) {
          const cur = new Set(self.className.split(/\s+/).filter(Boolean));
          for (const c of cls) cur.add(c);
          self.className = [...cur].join(" ");
        },
        toggle(c, force) {
          const cur = new Set(self.className.split(/\s+/).filter(Boolean));
          const on = force === undefined ? !cur.has(c) : Boolean(force);
          if (on) cur.add(c); else cur.delete(c);
          self.className = [...cur].join(" ");
        },
        contains(c) {
          return self.className.split(/\s+/).includes(c);
        },
      };
    }
    set id(v) { this.setAttribute("id", v); }
    get id() { return this.getAttribute("id") || ""; }
    setAttribute(k, v) { this.attributes.set(k, String(v)); }
    getAttribute(k) { return this.attributes.has(k) ? this.attributes.get(k) : null; }
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    }
    removeChild(child) {
      const i = this.children.indexOf(child);
      if (i >= 0) {
        this.children.splice(i, 1);
        child.parentNode = null;
      }
      return child;
    }
    get firstChild() { return this.children[0] || null; }
    set textContent(v) {
      this.children = [];
      this._text = String(v ?? "");
    }
    get textContent() {
      if (!this.children.length) return this._text;
      return this.children.map((c) => c.textContent).join("");
    }
    closest(sel) {
      let cur = this;
      while (cur) {
        if (cur.matches && cur.matches(sel)) return cur;
        cur = cur.parentNode;
      }
      return null;
    }
    matches(sel) {
      if (sel.startsWith(".")) return this.classList.contains(sel.slice(1));
      if (sel === 'input[type="checkbox"][data-group]') {
        return this.tagName === "INPUT" && this.getAttribute("type") === "checkbox" && this.getAttribute("data-group") !== null;
      }
      const mCount = sel.match(/^\[data-count-for="([^"]+)"\]$/);
      if (mCount) return this.getAttribute("data-count-for") === mCount[1];
      const mBoxSlug = sel.match(/^input\[type="checkbox"\]\[data-group="([^"]+)"\]\[data-slug="([^"]+)"\]$/);
      if (mBoxSlug) {
        return this.tagName === "INPUT" && this.getAttribute("type") === "checkbox" &&
          this.getAttribute("data-group") === mBoxSlug[1] && this.getAttribute("data-slug") === mBoxSlug[2];
      }
      const mBoxChecked = sel.match(/^input\[type="checkbox"\]\[data-group="([^"]+)"\]:checked$/);
      if (mBoxChecked) {
        return this.tagName === "INPUT" && this.getAttribute("type") === "checkbox" &&
          this.getAttribute("data-group") === mBoxChecked[1] && this.checked;
      }
      const mBoxGroup = sel.match(/^input\[type="checkbox"\]\[data-group="([^"]+)"\]$/);
      if (mBoxGroup) {
        return this.tagName === "INPUT" && this.getAttribute("type") === "checkbox" &&
          this.getAttribute("data-group") === mBoxGroup[1];
      }
      return false;
    }
    addEventListener(type, fn) {
      if (!this._listeners.has(type)) this._listeners.set(type, []);
      this._listeners.get(type).push(fn);
    }
    dispatchEvent(ev) {
      ev.target = ev.target || this;
      for (const fn of this._listeners.get(ev.type) || []) fn(ev);
      if (this.parentNode && this.parentNode.dispatchEvent && ev.bubbles !== false) {
        this.parentNode.dispatchEvent(ev);
      }
    }
    walk(out = []) {
      out.push(this);
      for (const c of this.children) {
        if (c.walk) c.walk(out);
      }
      return out;
    }
    querySelectorAll(sel) {
      return this.walk().filter((n) => n !== this && n.matches && n.matches(sel));
    }
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    }
  }

  const doc = {
    documentElement: null,
    createElement(tag) { return new MiniElement(doc, tag); },
    createTextNode(txt) {
      return { tagName: "#text", textContent: String(txt ?? ""), children: [] };
    },
    getElementById(id) {
      return doc.documentElement.walk().find((n) => n.getAttribute && n.getAttribute("id") === id) || null;
    },
    querySelectorAll(sel) { return doc.documentElement.querySelectorAll(sel); },
    querySelector(sel) { return doc.documentElement.querySelector(sel); },
  };
  doc.documentElement = new MiniElement(doc, "html");
  const app = doc.createElement("div");
  app.id = "papers-app";
  app.setAttribute("data-repo", "runpapers/runpapers");
  doc.documentElement.appendChild(app);

  const form = doc.createElement("form");
  form.id = "papers-form";
  const qInput = doc.createElement("input");
  qInput.id = "papers-q";
  form.appendChild(qInput);
  const sortSelect = doc.createElement("select");
  sortSelect.id = "papers-sort";
  sortSelect.value = "most_used";
  form.appendChild(sortSelect);
  app.appendChild(form);

  const summaryEl = doc.createElement("span");
  summaryEl.id = "papers-summary";
  app.appendChild(summaryEl);

  const clearBtn = doc.createElement("button");
  clearBtn.id = "papers-clear";
  clearBtn.hidden = true;
  app.appendChild(clearBtn);

  const filters = doc.createElement("aside");
  for (const g of SearchUI.GROUPS) {
    for (const t of searchData.vocab[g]) {
      const lbl = doc.createElement("label");
      lbl.className = "filter-opt";
      const box = doc.createElement("input");
      box.setAttribute("type", "checkbox");
      box.setAttribute("data-group", g);
      box.setAttribute("data-slug", t.slug);
      lbl.appendChild(box);
      const cnt = doc.createElement("span");
      cnt.setAttribute("data-count-for", `${g}:${t.slug}`);
      cnt.textContent = "0";
      lbl.appendChild(cnt);
      filters.appendChild(lbl);
    }
  }
  app.appendChild(filters);

  const results = doc.createElement("section");
  results.id = "papers-results";
  app.appendChild(results);

  const inlineJson = doc.createElement("script");
  inlineJson.id = "rp-search-data";
  inlineJson.textContent = JSON.stringify(searchData);
  app.appendChild(inlineJson);

  const winListeners = new Map();
  const win = {
    location: { protocol: "file:", pathname: "/papers/", search: initialSearch, hash: "" },
    history: {
      replaceState(_st, _title, url) {
        const qIdx = url.indexOf("?");
        win.location.pathname = qIdx >= 0 ? url.slice(0, qIdx) : url;
        win.location.search = qIdx >= 0 ? url.slice(qIdx) : "";
      },
    },
    addEventListener(type, fn) {
      if (!winListeners.has(type)) winListeners.set(type, []);
      winListeners.get(type).push(fn);
    },
    dispatchPopState(newSearch) {
      win.location.search = newSearch;
      for (const fn of winListeners.get("popstate") || []) fn({});
    },
  };

  return { doc, win, app, qInput, sortSelect, summaryEl, clearBtn, results };
}

test("built /papers/ files contain zero tier, stage, or badge words and self-host all assets", () => {
  const forbidden = /\b(lite|full|tier|tiers|tiered|stage|badges|badge)\b/i;
  for (const [name, content] of [
    ["papers/search.json", searchJsonRaw],
    ["papers/index.html", papersHtmlRaw],
    ["papers/index.md", papersMdRaw],
    ["search.js", searchJsRaw],
  ]) {
    assert.equal(forbidden.test(content), false, `unexpected forbidden token in ${name}`);
  }
  // Server-rendered HTML has all five filter legends and available + requested rows without JS.
  for (const heading of ["Species", "Tissue/cell", "Data type", "Disease", "Collection"]) {
    assert.ok(papersHtmlRaw.includes(`<legend class="filter-legend">${heading}</legend>`), heading);
  }
  assert.ok(papersHtmlRaw.includes("Cross-species multiomic atlas of the primate basal ganglia"));
  assert.ok(papersHtmlRaw.includes("PMID"));
  assert.match(papersHtmlRaw, /Reproduces Figure 1[AB].*\./);
  assert.equal(SearchUI.formatPanelsSentence(["Figure 1B", "Figure 2F"]), "Reproduces Figure 1B and Figure 2F.");
});

test("searching marmoset, Callithrix, DOI, PMID, or SMYD2 finds 10.1016/j.cell.2026.10.012 without umbrella or mid-word leaks", () => {
  const targetDoi = "10.1016/j.cell.2026.10.012";
  for (const q of [
    "marmoset",
    "Callithrix",
    "Callithrix jacchus",
    targetDoi,
    "43020019",
    "PMID: 43020019",
    "10.64898/2025.12.15.694496",
    "SMYD2",
    "MERFISH",
  ]) {
    const res = SearchUI.filterSearchIndex(searchData, { query: q });
    assert.ok(res.entries.length >= 1, `expected match for ${q}`);
    assert.equal(res.entries[0].doi, targetDoi, `available pack must rank first for ${q}`);
    assert.equal(res.entries[0].status, "available");
  }
  // Exact ID / pack-gene queries match only 10.1016/j.cell.2026.10.012.
  for (const exactQ of [targetDoi, "43020019", "SMYD2"]) {
    const res = SearchUI.filterSearchIndex(searchData, { query: exactQ });
    assert.deepEqual(res.entries.map((e) => e.doi), [targetDoi]);
  }
  // "marmoset" and "Callithrix" never leak via "NHP" to Macaque-only papers (e.g. 10.1016/j.cell.2026.09.014).
  for (const q of ["marmoset", "Callithrix"]) {
    const dois = SearchUI.filterSearchIndex(searchData, { query: q }).entries.map((e) => e.doi);
    assert.equal(dois.includes("10.1016/j.cell.2026.09.014"), false);
    assert.equal(dois.includes("10.1016/j.cell.2026.10.028"), false);
  }
  // "rat" and "ALS" do not match mid-word substrings ("integrated", "individuals", "mammals").
  assert.deepEqual(SearchUI.filterSearchIndex(searchData, { query: "rat" }).entries, []);
  assert.deepEqual(SearchUI.filterSearchIndex(searchData, { query: "ALS" }).entries, []);
});

test("Species = Marmoset AND Data type = Patch-seq intersects groups, ORs within group, and counts match visible results", () => {
  const res = SearchUI.filterSearchIndex(searchData, {
    species: ["Marmoset"],
    data_type: ["Patch-seq"],
  });
  assert.ok(res.entries.length >= 1);
  for (const e of res.entries) {
    assert.ok(e.tag_slugs.species.includes("marmoset"), e.doi);
    assert.ok(e.tag_slugs.data_type.includes("patch-seq"), e.doi);
  }
  assert.equal(res.entries[0].doi, "10.1016/j.cell.2026.10.012");

  // Every single count next to every label equals the visible results carrying that label.
  for (const g of SearchUI.GROUPS) {
    for (const t of searchData.vocab[g]) {
      const want = res.entries.filter((e) => e.tag_slugs[g].includes(t.slug)).length;
      assert.equal(res.counts[g][t.slug], want, `${g}:${t.slug}`);
    }
  }
  assert.equal(res.counts.species["marmoset"], res.entries.length);
  assert.equal(res.counts.data_type["patch-seq"], res.entries.length);
  assert.equal(res.counts.species["squirrel-monkey"], 0);

  // Within-group OR: Marmoset OR Squirrel monkey with Patch-seq adds 10.1016/j.cell.2026.10.028.
  const resOr = SearchUI.filterSearchIndex(searchData, {
    species: ["marmoset", "squirrel-monkey"],
    data_type: ["patch-seq"],
  });
  const doisOr = resOr.entries.map((e) => e.doi);
  assert.ok(doisOr.includes("10.1016/j.cell.2026.10.012"));
  assert.ok(doisOr.includes("10.1016/j.cell.2026.10.028"));
});

test("requested papers with high votes always appear after available packs, with vote counts, sort modes, and XSS-safe zero-results prefill", () => {
  const customData = {
    vocab: searchData.vocab,
    entries: [
      ...searchData.entries.filter((e) => e.status === "available").map((e) => ({
        ...e,
        usage: { human_views: 120, agent_views: 45, downloads: 12 },
      })),
      {
        ...searchData.entries[0],
        doi: "10.9999/avail.more.used",
        pmid: "49999999",
        slug: "10-9999-avail-more-used",
        url: "/papers/10-9999-avail-more-used/",
        title: "Alpha available pack with higher usage",
        status: "available",
        published_at: "2025-01-01T00:00:00Z",
        usage: { human_views: 900, agent_views: 300, downloads: 80 },
      },
      {
        doi: "10.1234/req.top.votes",
        pmid: "38888888",
        slug: "10-1234-req-top-votes",
        url: null,
        title: "Requested primate basal ganglia study <img src=x onerror=alert(1)>",
        first_author: "Vera Voter",
        journal: "Nature",
        year: 2026,
        summary: "",
        panels: [],
        status: "requested",
        status_reason: null,
        votes: 42,
        issue_url: "https://github.com/runpapers/runpapers/issues/99",
        tags: { species: ["Marmoset"], tissue_cell: [], data_type: [], disease: [], collection: [] },
        tag_slugs: { species: ["marmoset"], tissue_cell: [], data_type: [], disease: [], collection: [] },
        search_text: "requested primate basal ganglia marmoset callithrix 10.1234/req.top.votes 38888888",
        published_at: null,
        usage: null,
      },
      {
        doi: "10.1234/req.low.votes",
        pmid: null,
        slug: "10-1234-req-low-votes",
        url: null,
        title: "Second requested marmoset study",
        first_author: "Low Voter",
        journal: "Neuron",
        year: 2026,
        summary: "",
        panels: [],
        status: "requested",
        status_reason: null,
        votes: 3,
        issue_url: "https://github.com/runpapers/runpapers/issues/100",
        tags: { species: ["Marmoset"], tissue_cell: [], data_type: [], disease: [], collection: [] },
        tag_slugs: { species: ["marmoset"], tissue_cell: [], data_type: [], disease: [], collection: [] },
        search_text: "second requested marmoset 10.1234/req.low.votes",
        published_at: null,
        usage: null,
      },
    ],
  };

  // Default "most_used" sorts available packs by usage descending, then requested papers by votes descending.
  const mostUsed = SearchUI.filterSearchIndex(customData, { sort: "most_used" }).entries;
  assert.equal(mostUsed[0].doi, "10.9999/avail.more.used");
  assert.equal(mostUsed[1].doi, "10.1016/j.cell.2026.10.012");
  assert.equal(mostUsed[2].doi, "10.1234/req.top.votes");
  assert.equal(mostUsed[2].votes, 42);
  assert.equal(mostUsed[3].doi, "10.1234/req.low.votes");

  // "newest" sorts available packs by published_at descending while keeping requested papers after available.
  const newest = SearchUI.filterSearchIndex(customData, { sort: "newest" }).entries;
  assert.equal(newest[0].doi, "10.1016/j.cell.2026.10.012");
  assert.equal(newest[1].doi, "10.9999/avail.more.used");
  assert.equal(newest[2].doi, "10.1234/req.top.votes");

  // DOM rendering escapes HTML tags via textContent and renders zero-results DOI/PMID request links.
  const { doc, results, summaryEl, clearBtn } = createMiniDom();
  const vocIdx = SearchUI.buildVocabIndex(customData.vocab);
  SearchUI.renderResults(doc, results, summaryEl, clearBtn, customData, { query: "", sort: "most_used" }, vocIdx, "runpapers/runpapers");
  assert.ok(results.textContent.includes("Requested, 42 votes"));
  assert.ok(results.textContent.includes("<img src=x onerror=alert(1)>"));
  assert.equal(results.walk().some((n) => n.tagName === "IMG"), false);

  // Zero-results state pre-fills typed DOI or PMID into the GitHub request form URL.
  SearchUI.renderResults(doc, results, summaryEl, clearBtn, customData, { query: "10.1038/s41586-026-99999-1" }, vocIdx, "runpapers/runpapers");
  const reqBtnDoi = results.walk().find((n) => n.className === "btn-request");
  assert.ok(reqBtnDoi);
  assert.ok(reqBtnDoi.getAttribute("href").includes("doi=10.1038%2Fs41586-026-99999-1"));

  SearchUI.renderResults(doc, results, summaryEl, clearBtn, customData, { query: "PMID: 39876543" }, vocIdx, "runpapers/runpapers");
  const reqBtnPmid = results.walk().find((n) => n.className === "btn-request");
  assert.ok(reqBtnPmid.getAttribute("href").includes("doi=39876543"));
});

test("URL query parameters hydrate controls on load and update bidirectionally", () => {
  const { doc, win, clearBtn, results } = createMiniDom("?species=marmoset&data_type=patch-seq");
  const ctrl = SearchUI.initPapersPage(doc, win);
  assert.deepEqual(ctrl.getState().species, ["marmoset"]);
  assert.deepEqual(ctrl.getState().data_type, ["patch-seq"]);

  const marmBox = doc.querySelector('input[type="checkbox"][data-group="species"][data-slug="marmoset"]');
  const patchBox = doc.querySelector('input[type="checkbox"][data-group="data_type"][data-slug="patch-seq"]');
  assert.equal(marmBox.checked, true);
  assert.equal(patchBox.checked, true);

  const renderedArticles = results.children.filter((n) => n.tagName === "ARTICLE");
  assert.equal(renderedArticles[0].getAttribute("data-doi"), "10.1016/j.cell.2026.10.012");

  // Unchecking patch-seq updates window.location.search via history.replaceState.
  patchBox.checked = false;
  patchBox.dispatchEvent({ type: "change" });
  assert.equal(win.location.search, "?species=marmoset");

  // Clearing filters resets checkboxes and removes the query string.
  clearBtn.dispatchEvent({ type: "click", bubbles: false });
  assert.equal(marmBox.checked, false);
  assert.equal(win.location.search, "");

  // Browser back/forward (popstate) restores URL filters.
  win.dispatchPopState("?q=SMYD2&sort=title");
  assert.equal(ctrl.getState().query, "SMYD2");
  assert.equal(ctrl.getState().sort, "title");
});

test("search.js, rp search --json, and MCP search_papers return identical DOIs on the tagged repository", () => {
  const cases = [
    {
      js: { species: ["marmoset"] },
      cli: ["--species", "marmoset"],
      mcp: { species: ["marmoset"] },
    },
    {
      js: { species: ["marmoset"], data_type: ["patch-seq"] },
      cli: ["--species", "marmoset", "--data-type", "patch-seq"],
      mcp: { species: ["marmoset"], data_type: ["patch-seq"] },
    },
    {
      js: { disease: ["alzheimers-disease"] },
      cli: ["--disease", "alzheimers-disease"],
      mcp: { disease: ["Alzheimer's disease"] },
    },
    {
      js: { query: "Callithrix", tissue_cell: ["putamen"] },
      cli: ["Callithrix", "--tissue-cell", "putamen"],
      mcp: { query: "Callithrix", tissue_cell: ["putamen"] },
    },
  ];

  const env = { ...process.env, RUNPAPERS_HOME: ROOT, PYTHONPATH: path.join(ROOT, "src") };
  for (const c of cases) {
    const jsDois = SearchUI.filterSearchIndex(searchData, c.js).entries.map((e) => e.doi);
    const cliOut = execFileSync(PYTHON, ["-m", "runpapers.cli", "search", ...c.cli, "--limit", "100", "--json"], {
      cwd: ROOT,
      env,
      encoding: "utf8",
    });
    const cliDois = JSON.parse(cliOut).map((r) => r.doi);
    assert.deepEqual(jsDois, cliDois, JSON.stringify(c.js));

    const mcpPy = `
import json
from runpapers import catalog, mcp_server
from runpapers.registry import Registry
cat = catalog.LocalCatalog(Registry(${JSON.stringify(ROOT)}))
res = mcp_server.handle_tool_call(cat, "search_papers", ${JSON.stringify({ ...c.mcp, limit: 100 })})
print(json.dumps([m["doi"] for m in res["structuredContent"]["matches"]]))
`;
    const mcpOut = execFileSync(PYTHON, ["-c", mcpPy], { cwd: ROOT, env, encoding: "utf8" });
    assert.deepEqual(jsDois, JSON.parse(mcpOut), JSON.stringify(c.mcp));
  }
});
