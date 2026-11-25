"""The static website, generated from the registry. Every page has a machine twin (`index.md`), plus `llms.txt`,
`index.json` and a per-paper `AGENT.md` that a user's agent follows. No server code: any static host works."""
import html
import http.server
import json
import re
import shutil
from functools import partial
from pathlib import Path

from . import DEFAULT_BASE, __version__, ids, papers_page, search, vocab
from .recipes import check_tolerance, format_expected
from .registry import read_json, sha256_file
from .requests_log import issue_url as requests_issue_url
from .requests_log import summary as requests_summary
from .verify import now, record, resources, status
from .workspace import shipped

_REPO_BRAND_DIR = Path(__file__).resolve().parents[2] / "brand"

ONE_SENTENCE = (
    "RunPapers turns published papers into packs your own AI agent can run: "
    "it reproduces the figures from the original data, then answers your questions."
)

FALLBACK_TOKENS_CSS = """/* RunPapers colour and type tokens. */
:root {
  --rp-hematoxylin: #2A2C6B;
  --rp-eosin: #D9466F;
  --rp-eosin-ink: #C2335E;
  --rp-eosin-bright: #FF6B93;
  --rp-eosin-wash: #FCEEF2;
  --rp-slide: #F7F7FB;
  --rp-coverslip: #E3E2EE;
  --rp-counterstain: #5D5A85;
  --rp-font-sans: "IBM Plex Sans", -apple-system, "Segoe UI", Roboto, sans-serif;
  --rp-font-serif: "Source Serif 4", Georgia, serif;
  --rp-font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --rp-hematoxylin: #ECEBF7;
    --rp-slide: #14152E;
    --rp-coverslip: #34366A;
    --rp-counterstain: #A9A6CF;
    --rp-eosin-ink: #FF7FA3;
    --rp-eosin-wash: #2A1F3F;
    --rp-eosin: #FF6B93;
  }
}
"""

_LATIN1_RANGE = (
    "U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+02C6,U+02DA,U+02DC,"
    "U+2013-2014,U+2018-201A,U+201C-201E,U+2020-2022,U+2026,U+2030,"
    "U+2039-203A,U+2044,U+20AC,U+2122,U+2212,U+FB01-FB02"
)
_SERIF_EXT_RANGE = (
    "U+0100-0130,U+0132-0151,U+0154-024F,U+0370-03FF,U+2000-2012,"
    "U+2015-2017,U+201B,U+201F,U+2023-2025,U+2027-202F,U+2031-2038,"
    "U+203B-2043,U+2045-206F,U+2190,U+2192,U+2206,U+221E,U+2248,U+2264-2265,U+2713"
)

FONT_FACES_CSS = f"""
@font-face{{font-family:"IBM Plex Sans";src:url("assets/fonts/IBMPlexSans-Var-Roman-Latin1.woff2") format("woff2");font-weight:100 700;font-style:normal;font-display:swap;unicode-range:{_LATIN1_RANGE}}}
@font-face{{font-family:"IBM Plex Sans";src:url("assets/fonts/IBMPlexSans-Var-Roman-Greek.woff2") format("woff2");font-weight:100 700;font-style:normal;font-display:swap;unicode-range:U+0370-03FF}}
@font-face{{font-family:"IBM Plex Sans";src:url("assets/fonts/IBMPlexSans-Var-Italic-Latin1.woff2") format("woff2");font-weight:100 700;font-style:italic;font-display:swap;unicode-range:{_LATIN1_RANGE}}}
@font-face{{font-family:"Source Serif 4";src:url("assets/fonts/SourceSerif4-Var-Roman-Latin1.woff2") format("woff2");font-weight:400 600;font-style:normal;font-display:swap;unicode-range:{_LATIN1_RANGE}}}
@font-face{{font-family:"Source Serif 4";src:url("assets/fonts/SourceSerif4-Var-Roman-LatinExt.woff2") format("woff2");font-weight:400 600;font-style:normal;font-display:swap;unicode-range:{_SERIF_EXT_RANGE}}}
"""

CSS = """
:root{
  --rp-surface:#FFFFFF;
  --rp-btn-bg:var(--rp-eosin-ink);
  --rp-btn-fg:#FFFFFF;
  --rp-tab-bg:var(--rp-hematoxylin);
  --rp-tab-fg:#FFFFFF;
}
@media (prefers-color-scheme: dark){
  :root{
    --rp-surface:#1B1D3C;
    --rp-btn-bg:var(--rp-eosin-ink);
    --rp-btn-fg:#14152E;
    --rp-tab-bg:var(--rp-hematoxylin);
    --rp-tab-fg:#14152E;
  }
}
*{box-sizing:border-box}
html{max-width:100%}
body{margin:0;max-width:100%;background:var(--rp-slide);color:var(--rp-hematoxylin);font:400 17px/1.6 var(--rp-font-sans);overflow-wrap:break-word}
a{color:var(--rp-eosin-ink);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--rp-eosin);outline-offset:2px}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
header.site-header{background:var(--rp-surface);border-bottom:1px solid var(--rp-coverslip)}
header.site-header .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 20px;min-height:64px;padding-top:10px;padding-bottom:10px}
.brand-link{display:inline-flex;align-items:center;padding:4px 0;text-decoration:none}
.brand-link:hover{text-decoration:none}
.brand-pic{display:inline-flex;align-items:center}
.brand-logo{display:block;height:30px;width:auto}
nav.site-nav{display:flex;flex-wrap:wrap;align-items:center;gap:6px 18px}
nav.site-nav a{color:var(--rp-counterstain);font-size:15.5px;font-weight:500;padding:4px 0}
nav.site-nav a:hover,nav.site-nav a[aria-current="page"]{color:var(--rp-hematoxylin);text-decoration:none}
nav.site-nav a[aria-current="page"]{font-weight:700;border-bottom:2px solid var(--rp-eosin)}
main.wrap{padding-top:28px;padding-bottom:44px}
h1{font:700 2.15rem/1.18 var(--rp-font-sans);letter-spacing:-.015em;margin:8px 0 12px;color:var(--rp-hematoxylin)}
h1.paper-h1{font:600 2.05rem/1.24 var(--rp-font-serif);font-optical-sizing:auto;letter-spacing:-.005em}
h2{font:700 1.32rem/1.3 var(--rp-font-sans);margin:34px 0 10px;padding-top:16px;border-top:1px solid var(--rp-coverslip);color:var(--rp-hematoxylin)}
h2.no-rule{border-top:0;padding-top:0}
h3{font:700 1.08rem/1.35 var(--rp-font-sans);margin:20px 0 6px;color:var(--rp-hematoxylin)}
p,ul,ol{max-width:72ch}
p{margin:0 0 14px}
ul,ol{margin:0 0 16px;padding-left:22px}
li{margin:0 0 6px}
.mut{color:var(--rp-counterstain)}
.small{font-size:.88rem;line-height:1.5}
.hero{padding:14px 0 8px}
.hero h1{font-size:clamp(1.85rem,4.2vw,2.65rem);line-height:1.14;margin:0 0 12px;max-width:24ch}
.hero-lead{font-size:1.08rem;line-height:1.55;color:var(--rp-counterstain);max-width:64ch;margin:0 0 20px}
.home-search{display:flex;flex-wrap:wrap;gap:10px;max-width:720px;margin:0 0 26px}
.home-search input{flex:1 1 240px;min-width:0;padding:12px 14px;border:1px solid var(--rp-coverslip);border-radius:10px;background:var(--rp-surface);color:var(--rp-hematoxylin);font:400 16px/1.35 var(--rp-font-sans)}
.btn-primary{display:inline-flex;align-items:center;justify-content:center;background:var(--rp-btn-bg);color:var(--rp-btn-fg);border:0;border-radius:9px;padding:10px 16px;font:700 15px/1.3 var(--rp-font-sans);cursor:pointer;text-decoration:none}
.btn-primary:hover{text-decoration:none;opacity:.92;color:var(--rp-btn-fg)}
.btn-secondary{display:inline-flex;align-items:center;justify-content:center;background:var(--rp-surface);color:var(--rp-eosin-ink);border:1px solid var(--rp-coverslip);border-radius:9px;padding:9px 15px;font:600 14.5px/1.3 var(--rp-font-sans);text-decoration:none}
.btn-secondary:hover{text-decoration:none;border-color:var(--rp-eosin-ink)}
ol.steps{list-style:none;padding:0;margin:18px 0 12px;max-width:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
ol.steps li{margin:0;background:var(--rp-surface);border:1px solid var(--rp-coverslip);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:6px}
.step-num{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;background:var(--rp-eosin-wash);color:var(--rp-hematoxylin);font:700 13.5px/1 var(--rp-font-sans)}
.step-body{font-size:15.5px;line-height:1.48;color:var(--rp-hematoxylin)}
.cards-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0;max-width:none}
.info-card{background:var(--rp-surface);border:1px solid var(--rp-coverslip);border-radius:12px;padding:16px 18px;font-size:15px;line-height:1.5}
.info-card b{display:block;margin-bottom:4px;color:var(--rp-hematoxylin)}
.callout{background:var(--rp-eosin-wash);border:1px solid var(--rp-coverslip);border-radius:12px;padding:18px 20px;margin:28px 0 8px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 20px}
.callout p{margin:0;color:var(--rp-hematoxylin);font-size:15.5px;max-width:56ch}
.callout-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.empty-panel{background:var(--rp-surface);border:1px solid var(--rp-coverslip);border-radius:12px;padding:20px 22px;margin:12px 0;max-width:760px}
.empty-panel p{margin:0 0 8px}
.empty-panel p:last-child{margin-bottom:0}
.note{background:var(--rp-eosin-wash);border-left:3px solid var(--rp-eosin);border-radius:8px;padding:12px 15px;margin:12px 0;font-size:15px;max-width:76ch}
.prompt-wrap{background:var(--rp-eosin-wash);border:1px solid var(--rp-coverslip);border-radius:12px;padding:16px 18px;margin:12px 0;max-width:820px}
.prompt-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 12px;margin:0 0 10px}
.tabs{display:flex;flex-wrap:wrap;gap:6px}
.tabs button{border:1px solid var(--rp-coverslip);background:var(--rp-surface);color:var(--rp-hematoxylin);border-radius:8px;padding:5px 11px;font:600 13.5px/1.3 var(--rp-font-sans);cursor:pointer}
.tabs button.on{background:var(--rp-tab-bg);color:var(--rp-tab-fg);border-color:var(--rp-tab-bg)}
.copy{background:var(--rp-btn-bg);color:var(--rp-btn-fg);border:0;border-radius:8px;padding:7px 14px;font:700 13.5px/1.3 var(--rp-font-sans);cursor:pointer}
.prompt-how{font-size:13.5px;color:var(--rp-counterstain);margin:0 0 10px;max-width:none}
.prompt{margin:0;background:var(--rp-surface);color:var(--rp-hematoxylin);border:1px solid var(--rp-coverslip);border-radius:9px;padding:14px 16px;font:400 15px/1.55 var(--rp-font-sans);white-space:pre-wrap;overflow-wrap:anywhere}
.tscroll{overflow-x:auto;max-width:100%;margin:10px 0;background:var(--rp-surface);border:1px solid var(--rp-coverslip);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14.5px}
td,th{border-bottom:1px solid var(--rp-coverslip);padding:9px 11px;text-align:left;vertical-align:top}
tr:last-child td{border-bottom:0}
th{font-weight:700;color:var(--rp-hematoxylin);background:var(--rp-slide);font-size:13.5px}
.figs{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:14px;margin:12px 0}
.figs img{width:100%;height:auto;border:1px solid var(--rp-coverslip);border-radius:8px;background:#FFFFFF}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--rp-slide);color:var(--rp-hematoxylin);border:1px solid var(--rp-coverslip);white-space:nowrap}
.pill.hpc{background:var(--rp-eosin-wash)}
details.targets{background:var(--rp-surface);border:1px solid var(--rp-coverslip);border-radius:10px;padding:9px 13px;margin:8px 0}
details.targets summary{cursor:pointer;font-size:14.5px}
code{font:500 .88em/1.4 var(--rp-font-mono);background:var(--rp-surface);border:1px solid var(--rp-coverslip);padding:1px 5px;border-radius:5px;overflow-wrap:anywhere;word-break:break-word}
.status-legend{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 18px;max-width:none;padding:0;list-style:none}
.status-legend li{margin:0;font-size:13px;padding:3px 10px;border-radius:999px;background:var(--rp-surface);border:1px solid var(--rp-coverslip);color:var(--rp-counterstain)}
.req-list{display:flex;flex-direction:column;gap:10px;margin:14px 0}
footer.site-footer{margin-top:44px;border-top:1px solid var(--rp-coverslip);background:var(--rp-surface);color:var(--rp-counterstain);font-size:13.5px;line-height:1.55}
footer.site-footer .wrap{padding-top:22px;padding-bottom:28px;display:flex;flex-direction:column;gap:6px}
footer.site-footer p{margin:0;max-width:none}
.footer-links{display:flex;flex-wrap:wrap;gap:4px 14px}
@media(max-width:760px){
  ol.steps,.cards-grid{grid-template-columns:1fr}
  .wrap{padding:0 16px}
  main.wrap{padding-top:20px;padding-bottom:32px}
  h1{font-size:1.75rem}
  h1.paper-h1{font-size:1.65rem}
}
"""

SITE_JS = """/* Minimal progressive enhancement for prompt copying and agent-tab instructions. */
function cp(id, b) {
  var el = document.getElementById(id);
  if (!el || !navigator.clipboard) return;
  navigator.clipboard.writeText(el.innerText || el.textContent || "");
  var orig = b.getAttribute("data-label") || "Copy prompt";
  b.textContent = "Copied";
  setTimeout(function () { b.textContent = orig; }, 1600);
}
function tab(btn) {
  document.querySelectorAll(".tabs button").forEach(function (x) {
    x.classList.remove("on");
    x.setAttribute("aria-selected", "false");
  });
  btn.classList.add("on");
  btn.setAttribute("aria-selected", "true");
  var how = document.getElementById("how");
  if (how) how.textContent = btn.dataset.how || "";
}
"""

HOW = {
    "Claude Code": "Open an empty folder in a terminal, start claude, and paste the prompt below.",
    "Codex": "Open an empty folder in a terminal, start codex, and paste the prompt below.",
    "Antigravity": "Open an empty folder in Antigravity and paste the prompt into the agent panel.",
    "Other": "Use any AI agent that can read a web page and run commands on your computer (Gemini CLI, Cursor, Windsurf, goose, OpenCode).",
}

REQUEST_STATUS_LABELS = {
    "requested": "Requested",
    "planned": "Requested",
    "checking_data": "Checking the data",
    "in_progress": "Being built",
    "building": "Being built",
    "checking": "Being checked",
    "available": "Available",
    "not_possible": "Not possible",
}

GUIDE = r'''# How to use RunPapers

RunPapers turns published papers into packs your own AI agent can run. You do not need to write code: pick a paper, copy
one prompt into your AI agent in an empty folder, and watch it reproduce a figure from the original data with the
paper's numbers next to its own. Then ask it your own questions about the same data.

## What you need {#need}

- **An AI agent that can run commands on your computer**: Claude Code, Codex, Antigravity, Gemini CLI, Cursor or
  another agent that works in a folder. A chat-only website cannot download data or run figure scripts.
- **A computer or computing cluster** (macOS, Linux or Windows) with an internet connection and free disk space. Every
  paper page states how much data its figures download before you start.
- **A few minutes.** Nothing needs to be set up beforehand: if `uv` (a small, open-source Python tool manager) is not on
  your computer yet, your agent asks permission and installs it from the official installer.

## Use a paper in three steps {#steps}

1. **Find a paper.** Search on the [Papers](../papers/) page by title, DOI, PMID, gene, cell type or species, or narrow
   the list with the five tag filters (Species, Tissue/cell, Data type, Disease, Collection).
2. **Copy its prompt into your AI agent, in an empty folder.** Create a new empty folder on your computer, open your AI
   agent in that folder, and paste the copied prompt. There is nothing to fill in first: your agent asks you in one
   short message whether to run on your computer or on a computing cluster, and what question you want to explore.
3. **See the figure and the paper's numbers next to your agent's. Then ask your own question.** Your agent downloads
   only the files needed for that figure from the original public archive, checks each file's checksum, runs the figure
   script, and shows you the figure alongside a comparison table. After that, ask follow-up questions in plain English.

What your agent creates inside your folder:

- `SKILL.md`: plain-language notes on what the paper measured, how the data tables fit together, and the biological
  guardrails (such as using donors rather than individual cells as replicates).
- `data/`: links to the original files downloaded from the public archive, cached once so files are never downloaded twice.
- `recipes/`: the scripts that reproduce the paper's figures.
- `out/`: the reproduced figures and `result.json`, showing the paper's printed numbers next to your agent's numbers.
- `analyses/`: where your agent saves the scripts it writes for your own questions so you can inspect, re-run or share them.

## Ask good biological questions {#questions}

Each paper page lists questions its data can answer and questions its data cannot answer. Helpful habits when working
with your agent:

- Ask for numbers per donor or per animal, not only pooled cell counts. Donors, not cells, are the biological replicates.
- Ask your agent to save every script it writes in `analyses/` and tell you which file and column it read.
- Ask "What can't this dataset answer?" before planning follow-up experiments.
- When a paper's text and supplementary table disagree slightly with each other, the pack documents that openly so your
  agent can point it out.
- To continue another day, open your agent in the same folder; it reads `AGENTS.md` and picks up where you left off.

## Data terms, privacy and citing {#cite}

- **Original sources, original terms:** RunPapers never re-hosts scientific data. Your agent downloads files straight
  from the original public repository under that repository's terms (for example, the Allen Brain Cell Atlas is for
  noncommercial research with citation required). Every paper page states the source and links to the full terms.
- **Privacy:** RunPapers runs no model and has no server that sees your questions. Your conversation stays between you
  and your own AI agent provider.
- **How to cite:** If you publish work that uses a pack, cite the original paper first, the data repository as its terms
  require, and the permanent archived version of the RunPapers pack shown on the paper page.

## Request a paper or report a problem {#request}

- **Request or vote:** On the [Requests](../requests/) page, press **Request a paper** to ask for a paper by DOI or
  PMID, or click **Vote on GitHub** on an existing request. Each thumbs-up on [GitHub](https://github.com/{repo}/issues?q=label%3Arequest)
  is a vote, and papers with the most votes are built first.
- **Report a problem:** If a figure fails to run, a number disagrees with the paper, or a pack misled your agent, open
  the [Report a problem](https://github.com/{repo}/issues/new?template=pack-problem.yml) form on GitHub with the DOI
  and your agent's last few messages.

## Optional: terminal commands and MCP {#power}

You never need to type commands yourself, because your agent runs them for you. If you prefer working in a terminal or
connecting an MCP client directly:

- **Download a pack:** `{install} get <DOI>` creates the paper's folder without downloading raw data up front.
- **Check data and memory needs:** `{install} needs` lists each figure recipe's download size, memory and runtime.
- **Run one figure:** `{install} run <recipe>` downloads that figure's files, checks checksums and compares numbers.
- **Connect via Model Context Protocol (MCP):** `{install} mcp` (for example, `claude mcp add runpapers -- {install} mcp`).
- **Compare several papers on one topic:** `{install} meeting "<topic>"` builds one workspace with every matching pack.
- **Plain-text files for agents:** every page has an `index.md` twin alongside [llms.txt](../llms.txt) and [index.json](../index.json).
'''

_ANCHOR_RX = re.compile(r"\s*\{#([a-z0-9-]+)\}\s*$")


def _md_link(m):
    label, url = m.group(1), m.group(2)
    rel = ' rel="noopener"' if url.startswith(("http://", "https://")) else ""
    return f'<a href="{html.escape(url)}"{rel}>{label}</a>'


def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _md_link, s)


def md_html(md):
    """Enough Markdown for the guide: headings with {#anchors}, paragraphs, '-' and '1.' lists, inline code/bold/links."""
    out, para, items, kind = [], [], [], None

    def flush():
        nonlocal para, items, kind
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(' '.join(i))}</li>" for i in items) + f"</{kind}>")
        para, items, kind = [], [], None

    for line in md.splitlines():
        s = line.strip()
        m = re.match(r"(#{1,3}) (.*)", s)
        if not s:
            flush()
        elif m:
            flush()
            a = _ANCHOR_RX.search(m.group(2))
            title = _ANCHOR_RX.sub("", m.group(2))
            lvl = len(m.group(1))
            out.append(f'<h{lvl}{f" id={chr(34)}{a.group(1)}{chr(34)}" if a else ""}>{_inline(title)}</h{lvl}>')
        elif re.match(r"(- |\d+\. )", s):
            k = "ul" if s.startswith("- ") else "ol"
            if para or (kind and kind != k):
                flush()
            kind = k
            items.append([re.sub(r"^(- |\d+\. )", "", s)])
        elif items and line.startswith(" "):
            items[-1].append(s)
        else:
            para.append(s)
    flush()
    return "\n".join(out)


def guide_text(install, repo):
    return GUIDE.replace("{install}", install).replace("{repo}", repo)


def guide_md(install, repo):
    return "\n".join(_ANCHOR_RX.sub("", line) for line in guide_text(install, repo).splitlines()) + "\n"


_URL_RX = re.compile(r"https?://[^\s<>()]+")


def e(s):
    return html.escape(str(s if s is not None else ""))


def fmt_bytes(n):
    n = int(n or 0)
    if n <= 0:
        return "—"
    if n >= 1_000_000_000:
        return f"{n / 1e9:.1f} GB"
    if n >= 10_000_000:
        return f"{n / 1e6:,.0f} MB"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f} MB"
    if n >= 1_000:
        return f"{n / 1e3:,.0f} KB"
    return f"{n} B"


def linkify(text):
    """Escape plain text while turning bare https:// URLs into clickable links."""
    s = str(text or "")
    out, pos = [], 0
    for m in _URL_RX.finditer(s):
        url = m.group(0).rstrip(".,;:)")
        end = m.start() + len(url)
        out.append(e(s[pos:m.start()]))
        out.append(f'<a href="{e(url)}" rel="noopener">{e(url)}</a>')
        pos = end
    out.append(e(s[pos:]))
    return "".join(out)


def _copy_brand_assets(out, reg_root):
    brand_dir = (Path(reg_root) / "brand") if (Path(reg_root) / "brand").is_dir() else _REPO_BRAND_DIR
    tokens_css = FALLBACK_TOKENS_CSS
    if brand_dir.is_dir():
        tok_path = brand_dir / "color" / "tokens.css"
        if tok_path.is_file():
            tokens_css = tok_path.read_text()
        asset_map = {
            "fonts": (
                "IBMPlexSans-Var-Roman-Latin1.woff2",
                "IBMPlexSans-Var-Roman-Greek.woff2",
                "IBMPlexSans-Var-Italic-Latin1.woff2",
                "SourceSerif4-Var-Roman-Latin1.woff2",
                "SourceSerif4-Var-Roman-LatinExt.woff2",
            ),
            "logo": (
                "runpapers-logo.svg",
                "runpapers-logo-reverse.svg",
                "runpapers-mark.svg",
                "runpapers-mark-reverse.svg",
            ),
            "icons": (
                "favicon.svg",
                "favicon-32.png",
                "apple-touch-icon.png",
                "icon-192.png",
                "icon-512.png",
            ),
            "social": (
                "og-card.png",
            ),
        }
        for sub, names in asset_map.items():
            dst_dir = out / "assets" / sub
            dst_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                src_file = brand_dir / sub / name
                if src_file.is_file():
                    shutil.copy2(src_file, dst_dir / name)
    return tokens_css


def page(title, body, depth=0, desc="", md_twin="index.md", extra_scripts=(), active="", base=DEFAULT_BASE, repo="runpapers/runpapers"):
    up = "../" * depth
    home_href = up if up else "./"
    use_desc = desc or ONE_SENTENCE
    alt = f'<link rel="alternate" type="text/markdown" href="{e(md_twin)}">' if md_twin else ""
    twin_link = f'<a href="{e(md_twin)}">This page in plain text ({e(md_twin)})</a> · ' if md_twin else ""
    nav_items = [
        ("papers", f"{up}papers/", "Papers"),
        ("requests", f"{up}requests/", "Requests"),
        ("guide", f"{up}guide/", "Guide"),
        ("about", f"{up}about/", "About"),
    ]
    nav_html = "".join(
        f'<a href="{href}"{" aria-current=\"page\"" if key == active else ""}>{label}</a>'
        for key, href, label in nav_items
    )
    scripts = (f"{up}site.js", *extra_scripts)
    scripts_html = "".join(f'<script src="{e(src)}" defer></script>' for src in scripts)
    og_img = f"{base.rstrip('/')}/assets/social/og-card.png"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(use_desc)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(use_desc)}">
<meta property="og:type" content="website">
<meta property="og:image" content="{e(og_img)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{up}assets/icons/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{up}assets/icons/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="{up}assets/icons/apple-touch-icon.png">
{alt}
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="site-header"><div class="wrap">
<a class="brand-link" href="{home_href}">
<picture class="brand-pic">
<source srcset="{up}assets/logo/runpapers-logo-reverse.svg" media="(prefers-color-scheme: dark)">
<img class="brand-logo" src="{up}assets/logo/runpapers-logo.svg" width="148" height="30" alt="RunPapers">
</picture>
</a>
<nav class="site-nav" aria-label="Primary">{nav_html}</nav>
</div></header>
<main class="wrap">{body}</main>
<footer class="site-footer"><div class="wrap">
<p>RunPapers is free, open source and non-profit. We never see your questions and never run a model for you.</p>
<div class="footer-links">
<a href="{up}papers/">Papers</a>
<a href="{up}requests/">Requests</a>
<a href="{up}guide/">Guide</a>
<a href="{up}about/">About</a>
<a href="{up}about/#how-we-count">How we count</a>
<a href="https://github.com/{e(repo)}" rel="noopener">GitHub</a>
</div>
<p class="small">For AI agents: {twin_link}<a href="{up}llms.txt">llms.txt</a> · <a href="{up}index.json">index.json</a> · <a href="{up}papers/search.json">papers/search.json</a></p>
</div></footer>
{scripts_html}</body></html>
"""


def fmt_minutes(m):
    m = float(m or 0)
    if m <= 0:
        return "—"
    if m < 1:
        return "< 1 min"
    return f"~{round(m)} min" if m >= 2 else f"~{m:g} min"


def _recipe_res(card, r):
    mr = ((card.get("resources") or {}).get("recipes") or {}).get(r["id"]) or {}
    return {**r, **{k: mr[k] for k in ("data_bytes", "memory_gb", "gpu", "minutes", "measured", "where") if mr.get(k) is not None}}


def fmt_needs(r):
    data_txt = f"{fmt_bytes(r['data_bytes'])} data" if r.get("data_bytes") else "no external data"
    return f"{data_txt}, {r.get('memory_gb', 8):g} GB RAM, {'GPU' if r.get('gpu') else 'CPU'}, {fmt_minutes(r.get('minutes', 20))}"


def copy_prompt(card, base):
    doi = card["doi"]
    first = next((r for r in card["recipes"] if not r.get("gpu") and (r.get("memory_gb") or 8) <= 14),
                 (card["recipes"] or [{}])[0])
    panel = first.get("panel") or "a main figure"
    return (f"I want to work with the data from this paper using RunPapers:\n"
            f"  \"{card['title']}\" ({card.get('first_author', '').split()[-1] if card.get('first_author') else ''} et al., "
            f"{card.get('journal', '')} {card.get('year', '')}), DOI {doi}" + (f", PMID {card['pmid']}" if card.get("pmid") else "") + "\n"
            f"Setup for you, the AI agent: fetch {base}/{ids.page_path(doi)}/AGENT.md (or `curl -sL` it) and follow it exactly.\n"
            f"Ask me everything you need in one message first. Then reproduce {panel} and show it to me with a table of\n"
            f"the paper's numbers next to yours, and then help me explore the data with my own questions.")


def _data_terms(card):
    return sorted({d.get("license", "").strip() for d in card.get("data", []) if d.get("license", "").strip()})


def cost_text(res):
    """One plain sentence about disk, memory, GPU and time across the pack."""
    if not res:
        return ""
    mem_txt = f", up to {res['memory_gb']:g} GB of memory" if res.get("memory_gb") else ""
    gpu_txt = ", GPU needed for at least one panel" if res.get("gpu") else ""
    parts = [f"About {fmt_bytes(res['disk_bytes'])} of disk if running every panel ({fmt_bytes(res['data_bytes'])} of unique source data, "
             f"the rest Python packages and results){mem_txt}{gpu_txt}"]
    if res.get("agent_minutes"):
        a, b = res["agent_minutes"]
        parts.append(f"in our tests a fresh AI agent took {a} to {b} minutes from the pasted prompt to the reproduced figure"
                     if a != b else f"in our tests a fresh AI agent took about {a} minutes from the pasted prompt to the reproduced figure")
    if res.get("recipe_minutes") is not None:
        mins = max(1, round(res["recipe_minutes"])) if res["recipe_minutes"] >= 1 else 1
        parts.append(f"all recipes together run in about {mins} minute{'s' if mins > 1 else ''}")
    text = "; ".join(parts) + "."
    if res.get("hpc_recipes"):
        text += f" Panels {', '.join(res['hpc_recipes'])} need an HPC cluster or workstation; each recipe downloads only the files it uses."
    else:
        text += " Every panel runs on a laptop, and each recipe downloads only the files it uses."
    return text


def ask_once_md(card, install):
    """The single question an agent asks before starting (one round, cluster preferred)."""
    res = card.get("resources") or {}
    return f"""0. **Ask the user once, then work without further questions.** Unless the user's prompt already says where to run,
   send ONE message, then wait for the answer:
   - What it costs: {cost_text(res)}
   - Where to run: on this computer (in the current folder), or on their HPC cluster if they have one, which is
     preferred (ask for how they connect, for example the `ssh` name).
   - Which folder to use (default: the current folder here, or a new folder on the cluster).
   - What they want to explore with this paper's data (their question; they can also say "just reproduce it first").
   Make the message short, numbered and easy to answer in one reply; offer the recommended answer for each item.
   After the answer, don't ask again unless something fails or they asked to be consulted.
   On a cluster: check `ssh <name> true` works without a password prompt, then run every step below there
   (`ssh <name> 'cd <folder> && ...'`); use an interactive or batch job (e.g. `srun`/`sbatch`) for any recipe that
   needs a cluster or more memory than a login node allows; copy the figure and tables back to show them.
"""


def agent_md(card, base, install):
    doi = card["doi"]
    pmid_txt = f", PMID {card['pmid']}" if card.get("pmid") else ""
    src_arg = f" --source {base}" if base != DEFAULT_BASE else ""
    terms = "; ".join(_data_terms(card)) or "see the paper page and original repository"
    res = card.get("resources") or {}
    rec_lines = "\n".join(
        f"   - `{r['id']}`: {r['panel']}: {r['title']} ({fmt_needs(_recipe_res(card, r))})"
        for r in card["recipes"]
    )
    tot_line = (f"   Totals across all panels (`{install} run --all`): {fmt_bytes(res.get('data_bytes', card.get('data_bytes', 0)))} unique data, "
                f"{res.get('memory_gb', 0):g} GB peak RAM, {'GPU required' if res.get('gpu') else 'CPU only'}, "
                f"{fmt_minutes(res.get('recipe_minutes', 0))}.")
    return f"""# RunPapers: agent setup for "{card['title']}"

You are helping a scientist use the RunPapers pack for this paper (DOI {doi}{pmid_txt}, version {card['version']}).
Follow these steps in order. Ask the user before anything not listed here.

{ask_once_md(card, install)}
1. Check that `uv` is installed: `uv --version`. If it is missing, install it with the official installer:
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Get the pack (instructions, recipes and target numbers; no data files are downloaded yet):
   `{install} get {doi}{src_arg} --rp-cmd "{install}"`
   This creates the folder `./{card['slug']}/`. Work inside it from now on (`cd {card['slug']}`). Run `{install} needs` anytime to inspect per-recipe resource needs.
3. Read `SKILL.md` in that folder completely. It explains the data, the recipes and the guardrails. Follow the guardrails.
4. Reproduce a published panel: `{install} run <recipe>` (downloads only that recipe's data files from the original repositories, verifies checksums, and runs it). Recipes:
{rec_lines}
{tot_line}
   Each run writes `out/<recipe>/` with the figure, `metrics.json` and `result.json` (the paper's numbers next to yours).
   Show the user the figure and report plainly which numbers matched.
5. For the user's own questions, write scripts in `analyses/` that read `data/`, as SKILL.md describes. State what you
   computed, the replicate unit, and how confident you are. Never present a guess as a result.
6. Cite the paper (https://doi.org/{doi}) and the pack ({_pack_cite(card, base)}).
7. Data terms: {terms}. Tell the user before they publish or use the data commercially.
"""


def paper_md(card, base, install="uvx runpapers", results=None):
    doi = card["doi"]
    src_arg = f" --source {base}" if base != DEFAULT_BASE else ""
    terms = "; ".join(_data_terms(card)) or "see the original repository"
    res = card.get("resources") or {}
    lines = [
        f"# {card['title']}", "",
        f"{card.get('first_author', '')} et al., {card.get('journal', '')} {card.get('year', '')}. DOI {doi}"
        + (f" · PMID {card['pmid']}" if card.get("pmid") else ""), "",
        f"RunPapers pack v{card['version']}"
        + (f" · archived: https://doi.org/{card['release']['doi']}" if (card.get("release") or {}).get("doi") else ""), "",
        f"Size and time: {cost_text(res)}", "",
        card.get("summary", ""), "",
        "## Copy this into your AI agent", "",
        "```", copy_prompt(card, base), "```", "",
        f"Agent setup: {base}/{ids.page_path(doi)}/AGENT.md",
        f"Terminal setup: `{install} get {doi}{src_arg}`", "",
        "## Figures it reproduces", "",
    ]
    for r in card["recipes"]:
        rr = _recipe_res(card, r)
        pr = (results or {}).get(r["id"])
        req = [c for c in (pr or {}).get("checks", []) if c.get("required", True)]
        match_txt = f" — {sum(1 for c in req if c.get('ok'))}/{len(req)} paper targets matched" if pr and pr.get("pass") and req else ""
        lines.append(f"- `{r['id']}`: {r['panel']}: {r['title']} ({fmt_needs(rr)}){match_txt}")
    if card["recipes"]:
        lines.append(f"- **Totals across all panels:** {fmt_bytes(res.get('data_bytes', card.get('data_bytes', 0)))} unique data, "
                     f"{res.get('memory_gb', 0):g} GB peak RAM, {'GPU' if res.get('gpu') else 'CPU'}, {fmt_minutes(res.get('recipe_minutes', 0))}")
    if card.get("questions"):
        lines += ["", "## Questions this data can answer", ""] + [f"- {q}" for q in card["questions"]]
    if card.get("data"):
        lines += ["", "## Data and terms", "", f"Source data terms: {terms}", ""]
        for d in card["data"]:
            sz = "controlled access" if d.get("access") == "controlled" else fmt_bytes(d.get("size", 0))
            lines.append(f"- **{d.get('title') or d['id']}** (`{d['id']}`, {sz}) — {d.get('source', '')}")
    lines += ["", "## Cite", "",
              f"Cite the paper (https://doi.org/{doi}) and the pack: {_pack_cite(card, base)}"]
    return "\n".join(lines) + "\n"


def _redirect_file(path, url, title):
    """Write an HTML redirect file (`<link rel="canonical">` + `<meta http-equiv="refresh">`)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>'
        f'<link rel="canonical" href="{e(url)}"><meta http-equiv="refresh" content="0; url={e(url)}">'
        f'<meta name="robots" content="noindex"></head><body><p>Moved to <a href="{e(url)}">{e(url)}</a>.</p></body></html>\n'
    )


def _redirect(d, url, title):
    """Legacy directory redirect (e.g. `/doi/<prefix>/<encoded-suffix>/index.html` -> `/papers/<slug>/`)."""
    _redirect_file(Path(d) / "index.html", url, title)


def _compute_pill(rr):
    hpc = rr.get("where") == "hpc" or rr.get("gpu") or float(rr.get("memory_gb", 8)) > 14 or float(rr.get("minutes", 20)) >= 60
    if rr.get("gpu"):
        return '<span class="pill hpc" title="Requires a GPU (computing cluster or workstation)">GPU · Cluster</span>'
    if hpc:
        return '<span class="pill hpc" title="Runs on a computing cluster or large-memory workstation">CPU · Cluster</span>'
    return '<span class="pill">Laptop</span>'


def paper_html(card, base, install, figs, results=None, repo="runpapers/runpapers"):
    doi = card["doi"]
    depth = len(ids.page_path(doi).split("/"))
    up = "../" * depth
    pid = "p0"
    src_arg = f" --source {base}" if base != DEFAULT_BASE else ""
    res = card.get("resources") or {}
    tabs = "".join(
        f'<button type="button" role="tab" aria-selected="{"true" if i == 0 else "false"}" '
        f'class="{"on" if i == 0 else ""}" data-how="{e(v)}" onclick="tab(this)">{e(k)}</button>'
        for i, (k, v) in enumerate(HOW.items())
    )
    rec_by_id = {r["id"]: _recipe_res(card, r) for r in card["recipes"]}
    rec_rows_list = []
    for r in card["recipes"]:
        rr = rec_by_id[r["id"]]
        mem_cell = f"{rr.get('memory_gb', 8):g} GB"
        rec_rows_list.append(
            f"<tr><td><code>{e(r['id'])}</code></td><td>{e(r['panel'])}</td><td>{e(r['title'])}</td>"
            f"<td>{e(fmt_bytes(rr.get('data_bytes', 0)))}</td>"
            f"<td>{e(mem_cell)}</td>"
            f"<td>{_compute_pill(rr)}</td>"
            f"<td>{e(fmt_minutes(rr.get('minutes', 20)))}</td></tr>"
        )
    rec_rows = "".join(rec_rows_list)
    tot_compute = '<span class="pill hpc">GPU · Cluster</span>' if res.get("gpu") else '<span class="pill">Laptop / CPU</span>'
    tot_mem = f"{res.get('memory_gb', 0):g} GB peak"
    tot_row = (
        f'<tr style="font-weight:700"><td>Total</td><td colspan="2">{len(card["recipes"])} panel(s) (shared files counted once)</td>'
        f'<td>{e(fmt_bytes(res.get("data_bytes", card.get("data_bytes", 0))))}</td>'
        f'<td>{e(tot_mem)}</td>'
        f'<td>{tot_compute}</td>'
        f'<td>{e(fmt_minutes(res.get("recipe_minutes", 0)))}</td></tr>'
        if card["recipes"] else ""
    )
    target_blocks = []
    for r in card["recipes"]:
        pr = (results or {}).get(r["id"])
        if not pr or not pr.get("pass") or not pr.get("checks"):
            continue
        rr = rec_by_id[r["id"]]
        req_checks = [c for c in pr["checks"] if c.get("required", True)]
        n_ok = sum(1 for c in req_checks if c.get("ok"))
        trows = "".join(
            f"<tr><td><code>{e(c['metric'])}</code></td><td>{e(c.get('paper_display', c.get('expected')))}</td>"
            f"<td>{e(c.get('observed'))}</td>"
            f"<td>{'match' if c.get('ok') else ('known paper discrepancy' if not c.get('required', True) else 'mismatch')}</td>"
            f"<td>{e(c.get('source', ''))}</td></tr>"
            for c in pr["checks"]
        )
        target_blocks.append(
            f'<details class="targets"><summary><b>{e(r.get("panel") or r["id"])}</b> '
            f'(<code>{e(r["id"])}</code>) {_compute_pill(rr)} · '
            f'{n_ok}/{len(req_checks)} paper numbers matched</summary>'
            f'<div class="tscroll"><table><tr><th>Number</th><th>Paper</th><th>Ours</th><th>Check</th><th>Where in paper</th></tr>'
            f'{trows}</table></div></details>'
        )
    targets_html = "".join(target_blocks)
    fig_items = []
    for fname, rid in figs:
        rr = rec_by_id.get(rid, {})
        cap = f"{rr.get('panel', rid)}: {rr.get('title', fname)}" if rr else fname
        hpc_tag = f' {_compute_pill(rr)}' if rr and (rr.get("where") == "hpc" or rr.get("gpu") or float(rr.get("memory_gb", 8)) > 14) else ""
        fig_items.append(
            f'<figure style="margin:0"><img src="figures/{e(fname)}" alt="{e(cap)}" loading="lazy">'
            f'<figcaption class="small mut">{e(cap)}{hpc_tag}</figcaption></figure>'
        )
    fig_html = "".join(fig_items)
    qs = "".join(f"<li>{e(q)}</li>" for q in card.get("questions") or [])
    ids_line = f'DOI <a href="{ids.doi_url(doi)}" rel="noopener">{e(doi)}</a>' + (
        f' · PMID <a href="{ids.pubmed_url(card["pmid"])}" rel="noopener">{e(card["pmid"])}</a>' if card.get("pmid") else "")
    cite_bits = [x for x in (
        f"{e(card['first_author'])} et al." if card.get("first_author") else "",
        f"{e(card['journal'])}" + (f" {e(card['year'])}" if card.get("year") else "") if card.get("journal") else (e(card["year"]) if card.get("year") else ""),
    ) if x]
    cite_prefix = (", ".join(cite_bits) + " · ") if cite_bits else ""
    tags_html = papers_page._tags_html(card.get("tags"))
    data_rows = "".join(
        f"<tr><td>{e(d.get('title') or d['id'])}</td>"
        f"<td>{e('controlled' if d.get('access') == 'controlled' else fmt_bytes(d.get('size', 0)))}</td>"
        f"<td>{e(d.get('source', ''))}</td><td>{linkify(d.get('license', 'not recorded'))}</td></tr>"
        for d in card.get("data", [])
    )
    terms = _data_terms(card)
    terms_note = (
        f'<div class="note"><b>Data and terms:</b> RunPapers never re-hosts scientific data. Your agent downloads each file '
        f'straight from its original public repository and checks its checksum. Source terms: '
        f'{"; ".join(linkify(t) for t in terms)}. Check these terms before commercial use or publication.</div>'
        if terms else ""
    )
    problem_url = f"https://github.com/{repo}/issues/new?template=pack-problem.yml&doi={html.escape(doi)}"
    body = f"""
<h1 class="paper-h1">{e(card['title'])}</h1>
<p class="mut">{cite_prefix}{ids_line}</p>
<p class="small mut">Pack v{e(card['version'])} · <a href="{up}about/">how packs are checked</a></p>
{_release_html(card)}
{tags_html}
<p>{e(card.get('summary', ''))}</p>
<h2>Copy this into your AI agent</h2>
<div class="prompt-wrap">
<div class="prompt-bar">
<div class="tabs" role="tablist" aria-label="AI agent">{tabs}</div>
<button type="button" class="copy" data-label="Copy prompt" onclick="cp('{pid}',this)">Copy prompt</button>
</div>
<p class="prompt-how" id="how">{e(next(iter(HOW.values())))}</p>
<pre class="prompt" id="{pid}">{e(copy_prompt(card, base))}</pre>
</div>
<p class="small mut">Run it in an empty folder. {e(cost_text(res))} Data come straight from the paper's original repositories; nothing is sent to RunPapers. Terminal command: <code>{e(install)} get {e(doi)}{e(src_arg)}</code></p>
<h2>Figures it reproduces</h2><div class="tscroll"><table><tr><th>Recipe</th><th>Panel</th><th>What it shows</th><th>Data</th><th>Memory</th><th>Runs on</th><th>Time</th></tr>{rec_rows}{tot_row}</table></div>
{targets_html}
{('<div class="figs">' + fig_html + '</div>') if fig_items else ''}
{('<h2>Questions this data can answer</h2><ul>' + qs + '</ul>') if qs else ''}
<h2>Data and terms</h2>{terms_note}<div class="tscroll"><table><tr><th>File</th><th>Size</th><th>Source</th><th>Terms</th></tr>{data_rows}</table></div>
<h2>Cite</h2><p class="small">1. Paper: {cite_prefix}{ids_line}<br>2. Pack: {_pack_cite_html(card, base)}</p>
<p class="small mut">Something wrong? <a href="{problem_url}" rel="noopener">Report a problem</a> · For AI agents: <a href="index.md">index.md</a> · <a href="AGENT.md">AGENT.md</a> · <a href="pack.json">pack.json</a></p>
"""
    return page(f"{card['title']} · RunPapers", body, depth=depth, desc=card.get("summary", ""), md_twin="index.md", active="papers", base=base, repo=repo)


def _pack_cite(card, base):
    r = card.get("release") or {}
    where = f"https://doi.org/{r['doi']}" if r.get("doi") else f"{base}/{ids.page_path(card['doi'])}/"
    return f"RunPapers pack for {card['doi']}, version {r.get('version') or card['version']}, {where}"


def _pack_cite_html(card, base):
    return linkify(_pack_cite(card, base))


def _release_html(card):
    r = card.get("release")
    if not r:
        return ""
    links = [f'archived on Zenodo: <a href="https://doi.org/{e(r["doi"])}" rel="noopener">doi:{e(r["doi"])}</a>' if r.get("doi") else "",
             f'<a href="{e(r["huggingface"])}" rel="noopener">Hugging Face dataset</a>' if r.get("huggingface") else "",
             f'<a href="{e(r["github"])}" rel="noopener">GitHub release</a>' if r.get("github") else ""]
    return f'<p class="small">Released v{e(r["version"])}: {" · ".join(x for x in links if x)}</p>'


def _home_sort_key(c):
    return (c.get("published_at") or "", c.get("year") or 0, c["title"])


def home_html(cards, new_req):
    sorted_cards = sorted(cards, key=_home_sort_key, reverse=True)[:10]
    if sorted_cards:
        rows = []
        for c in sorted_cards:
            entry = {
                "doi": c["doi"],
                "pmid": c.get("pmid"),
                "slug": c["slug"],
                "title": c["title"],
                "first_author": c.get("first_author"),
                "journal": c.get("journal"),
                "year": c.get("year"),
                "summary": c.get("summary"),
                "tags": c.get("tags"),
                "panels": [r.get("panel") for r in c.get("recipes", []) if r.get("panel")],
                "published_at": c.get("published_at"),
                "usage": c.get("usage"),
            }
            rows.append(papers_page._available_row_html(entry, href_prefix="papers/", about_prefix="about/"))
        papers_block = "".join(rows)
        if len(cards) > len(sorted_cards):
            papers_block += f'<p class="small"><a href="papers/">Browse all {len(cards)} available papers</a></p>'
    else:
        papers_block = (
            '<div class="empty-panel">'
            '<p><b>No packs are available yet.</b> The first packs are in final checks against their published figures.</p>'
            '<p class="small mut">See what is being built on <a href="papers/">Papers</a> or vote for what comes next on <a href="requests/">Requests</a>.</p>'
            '</div>'
        )
    return f"""<section class="hero">
<h1>Reproduce the paper. Then ask your own question.</h1>
<p class="hero-lead">Pick a paper, copy one prompt into your AI agent, and watch it reproduce a figure from the original data. Then ask it anything the data can answer.</p>
<form class="home-search" action="papers/" method="get">
<input type="search" name="q" placeholder="Search by title, DOI, PMID, gene, cell type or species" aria-label="Search papers">
<button type="submit" class="btn-primary">Search</button>
</form>
</section>
<ol class="steps">
<li><span class="step-num">1</span><span class="step-body">Find a paper.</span></li>
<li><span class="step-num">2</span><span class="step-body">Copy its prompt into your AI agent, in an empty folder.</span></li>
<li><span class="step-num">3</span><span class="step-body">See the figure and the paper's numbers next to your agent's. Then ask your own question.</span></li>
</ol>
<p class="small mut">New to AI agents? Read the <a href="guide/">step-by-step guide</a> or see <a href="about/">how every pack is checked</a>.</p>
<h2>Newest available papers</h2>
{papers_block}
<div class="callout">
<p><b>Can't find your paper?</b> Request it. Papers with the most votes are built first.</p>
<div class="callout-actions">
<a class="btn-primary" href="{e(new_req)}" rel="noopener">Request a paper</a>
<a class="btn-secondary" href="requests/">See requested papers</a>
</div>
</div>"""


def index_md(cards, base, install, repo="runpapers/runpapers"):
    lines = [
        "# RunPapers", "",
        "Reproduce the paper. Then ask your own question.", "",
        "Pick a paper, copy one prompt into your AI agent, and watch it reproduce a figure from the original data. "
        "Then ask it anything the data can answer.", "",
        "1. Find a paper.",
        "2. Copy its prompt into your AI agent, in an empty folder.",
        "3. See the figure and the paper's numbers next to your agent's. Then ask your own question.", "",
        f"Search and filter all papers: {base}/papers/index.md (`{base}/papers/search.json`).", "",
        "## Newest available papers", "",
    ]
    if cards:
        for c in sorted(cards, key=_home_sort_key, reverse=True):
            lines.append(f"- [{c['title']}]({base}/{ids.page_path(c['doi'])}/index.md) — "
                         f"{c.get('first_author', '')} et al., {c.get('journal', '')} {c.get('year', '')} · "
                         f"DOI {c['doi']}" + (f" · PMID {c['pmid']}" if c.get("pmid") else ""))
    else:
        lines.append("- No packs available yet.")
    lines += [
        "",
        "## Request a paper",
        "",
        f"Can't find your paper? Request it: {requests_issue_url(repo)} (or see {base}/requests/index.md; `{install} request <DOI or PMID>`). "
        "Papers with the most votes are built first.",
    ]
    return "\n".join(lines) + "\n"


def about_html(install, repo="runpapers/runpapers"):
    return f"""<h1>About RunPapers</h1>
<p>RunPapers makes published papers usable by any scientist, programmer or not. For each paper we build a pack: the
paper's numbers, the original data's location, and tested instructions for AI agents. You copy one prompt into your own
agent (Claude Code, Codex, Antigravity or another one that can run commands), and in a few minutes it reproduces a
figure from the original data and shows the paper's numbers next to its own. Then it is your analyst: ask it new
questions about the same data. We check every pack against the paper before it is listed. RunPapers is free, open source
and non-profit; we never see your questions and never run a model for you.</p>
<div class="cards-grid">
<div class="info-card"><b>Your own AI agent</b>You use the agent already on your computer. RunPapers runs no model, requires no account, and never sees your prompts or results.</div>
<div class="info-card"><b>Every figure open data support</b>Each pack covers all main-figure panels supported by open data. Copying a pack downloads no raw data up front; each figure downloads only the files it needs.</div>
<div class="info-card"><b>Biological guardrails</b>Every pack spells out the biological replicate unit (donors or animals, never individual cells), batch or dissection confounders, and questions the data cannot answer.</div>
</div>
<h2 id="verification">How we check every pack before listing</h2>
<p>Only checked and archived packs appear on RunPapers:</p>
<ul>
<li>Every figure script re-runs from the original public data and matches the numbers printed in the paper.</li>
<li>A second reviewer who did not build the pack compares every reproduced panel side by side with the published figure and audits the target numbers and guardrails.</li>
<li>Fresh AI agents from multiple providers, given only the copied prompt in an empty folder, reproduce a figure and answer held-out test questions before a permanent archive record is published.</li>
<li>When a published paper's text and table disagree slightly with each other, the pack states that openly rather than hiding it.</li>
</ul>
<h2 id="data-terms">Original data and terms</h2>
<p>RunPapers never re-hosts scientific data and never redistributes copyrighted figure images unless the paper's license permits it. Each pack points to the original public archive (such as the Allen Brain Cell Atlas, NCBI Gene Expression Omnibus, CELLxGENE, NeMO, Zenodo or Figshare) with exact byte sizes and checksums.</p>
<p>Every dataset keeps its original repository's terms of use rather than being assumed to be unrestricted. For example, datasets from the <b>Allen Brain Cell Atlas</b> are governed by the <a href="https://alleninstitute.org/terms-of-use/" rel="noopener">Allen Institute Terms of Use</a> (noncommercial research use, citing both the paper and the Atlas). Controlled-access human datasets are never downloaded automatically; packs explain how to apply for access instead.</p>
<h2 id="how-we-count">How we count</h2>
<p>Views by people are counted with a cookie-free counter that stores no personal data. Views by AI agents are fetches of a paper's agent instructions, which every copied prompt makes; search-engine and AI-training crawlers are not counted. Downloads are pack downloads plus the archive's downloads on Zenodo and Hugging Face. Numbers are updated every night.</p>
<h2 id="cite">Open source and citing</h2>
<p>All code and packs live openly on <a href="https://github.com/{e(repo)}" rel="noopener">GitHub</a>, with permanent pack releases archived on <a href="https://zenodo.org/communities/runpapers" rel="noopener">Zenodo</a> and <a href="https://huggingface.co/RunPapers" rel="noopener">Hugging Face</a>. Ask for a paper on <a href="../requests/">Requests</a> or read the <a href="../guide/">Guide</a> to get started. When publishing work made with a pack, cite the original paper first, the data repository as its terms require, and the pack's archive DOI.</p>"""


def about_md(install, repo="runpapers/runpapers"):
    lines = [
        "# About RunPapers", "",
        "RunPapers makes published papers usable by any scientist, programmer or not. For each paper we build a pack: the "
        "paper's numbers, the original data's location, and tested instructions for AI agents. You copy one prompt into your "
        "own agent (Claude Code, Codex, Antigravity or another one that can run commands), and in a few minutes it reproduces "
        "a figure from the original data and shows the paper's numbers next to its own. Then it is your analyst: ask it new "
        "questions about the same data. We check every pack against the paper before it is listed. RunPapers is free, open "
        "source and non-profit; we never see your questions and never run a model for you.", "",
        "## How we check every pack before listing", "",
        "- Every figure script re-runs from the original public data and matches the numbers printed in the paper.",
        "- A second reviewer who did not build the pack compares every reproduced panel side by side with the published figure.",
        "- Fresh AI agents from multiple providers reproduce a figure and answer held-out test questions from the copied prompt alone before release.",
        "- Discrepancies inside a published paper are documented openly rather than hidden.", "",
        "## Original data and terms", "",
        "RunPapers never re-hosts raw data. Your agent downloads files straight from their original public repositories with size "
        "and checksum verification, and each dataset keeps its source terms (for example, the Allen Brain Cell Atlas is under the "
        "Allen Institute Terms of Use: noncommercial research use with citation required, https://alleninstitute.org/terms-of-use/). "
        "Controlled-access datasets are never downloaded automatically.", "",
        "## How we count", "",
        "Views by people are counted with a cookie-free counter that stores no personal data. Views by AI agents are fetches of a "
        "paper's agent instructions, which every copied prompt makes; search-engine and AI-training crawlers are not counted. "
        "Downloads are pack downloads plus the archive's downloads on Zenodo and Hugging Face. Numbers are updated every night.", "",
        "## Open source and citing", "",
        f"Code and packs: https://github.com/{repo} · Zenodo: https://zenodo.org/communities/runpapers · Hugging Face: https://huggingface.co/RunPapers. "
        f"Request or vote for a paper on the Requests page or with `{install} request <DOI or PMID>`. "
        "Cite the original paper first, the data repository per its terms, and the pack's archive DOI.",
    ]
    return "\n".join(lines) + "\n"


def _human_request_status(status_key, reason=None):
    label = REQUEST_STATUS_LABELS.get(status_key or "requested", "Requested")
    if status_key == "not_possible" and reason:
        return f"{label}: {reason}"
    return label


def requests_html(reqs, planned, install, repo="runpapers/runpapers"):
    new_req = requests_issue_url(repo)
    items = []
    seen = set()
    for r in reqs:
        d = r["doi"]
        seen.add(d)
        p = planned.get(d) or {}
        items.append({
            "doi": d,
            "pmid": p.get("pmid"),
            "title": r.get("title") or p.get("title") or d,
            "first_author": p.get("first_author"),
            "journal": p.get("journal"),
            "year": p.get("year"),
            "votes": int(r.get("votes") or 0),
            "status": r.get("status") or "requested",
            "status_reason": p.get("status_reason"),
            "issue_url": r.get("issue") or requests_issue_url(repo, d),
            "tags": p.get("tags"),
        })
    for d, p in planned.items():
        if d in seen:
            continue
        items.append({
            "doi": d,
            "pmid": p.get("pmid"),
            "title": p.get("title") or d,
            "first_author": p.get("first_author"),
            "journal": p.get("journal"),
            "year": p.get("year"),
            "votes": 0,
            "status": p.get("status") or "requested",
            "status_reason": p.get("status_reason"),
            "issue_url": requests_issue_url(repo, d),
            "tags": p.get("tags"),
        })
    items.sort(key=lambda x: (-x["votes"], -(int(x["year"] or 0)), str(x["title"]).lower(), x["doi"]))

    if items:
        cards_out = []
        for item in items:
            st = item["status"]
            votes = item["votes"]
            vote_word = "1 vote" if votes == 1 else f"{votes} votes"
            status_lbl = _human_request_status(st, item.get("status_reason"))
            pill_txt = f"{status_lbl}, {vote_word}" if st not in ("available", "not_possible") and votes > 0 else (
                f"Requested, {vote_word}" if st == "requested" else status_lbl
            )
            action_txt = "Details on GitHub" if st == "not_possible" else (
                "View pack" if st == "available" else "Vote on GitHub"
            )
            action_href = f"../{ids.page_path(item['doi'])}/" if st == "available" else item["issue_url"]
            action_rel = "" if st == "available" else ' rel="noopener"'
            cards_out.append(
                f'<article class="paper-row paper-row-requested" data-doi="{e(item["doi"])}">'
                f'<div class="paper-title-line"><span class="paper-title">{e(item["title"])}</span></div>'
                f'{papers_page._citation_html(item)}'
                f'<div class="paper-req-line"><span class="req-status">{e(pill_txt)}</span>'
                f'<a class="vote-link" href="{e(action_href)}"{action_rel}>{e(action_txt)}</a></div>'
                f'{papers_page._tags_html(item.get("tags"))}'
                f'</article>'
            )
        list_html = f'<div class="req-list">{"".join(cards_out)}</div>'
    else:
        list_html = '<div class="empty-panel"><p>No paper requests yet. Press <b>Request a paper</b> above to suggest the first one.</p></div>'

    return f"""<h1>Requested papers</h1>
<p class="mut">Ask for a paper you want to use with your agent. Each thumbs-up on GitHub is a vote, and papers with the
most votes are built first. We check every request for open data and data terms before building.</p>
<p><a class="btn-primary" href="{e(new_req)}" rel="noopener">Request a paper</a></p>
<ul class="status-legend" aria-label="Request statuses">
<li>Requested</li><li>Checking the data</li><li>Being built</li><li>Being checked</li><li>Available</li><li>Not possible</li>
</ul>
<p class="small mut">You can also filter requested papers by species, tissue or cell, data type and disease on <a href="../papers/">Papers</a>, or print a request link from your agent with <code>{e(install)} request &lt;DOI or PMID&gt;</code>.</p>
{list_html}"""


def requests_md(reqs, planned, install, repo="runpapers/runpapers"):
    lines = [
        "# Requested papers", "",
        "Ask for a paper you want to use with your agent. Each thumbs-up on GitHub is a vote, and papers with the "
        "most votes are built first. We check every request for open data and data terms before building.", "",
        f"Request a paper: {requests_issue_url(repo)} (or `{install} request <DOI or PMID>`).", "",
    ]
    seen = set()
    rows = []
    for r in reqs:
        seen.add(r["doi"])
        p = planned.get(r["doi"]) or {}
        rows.append((int(r.get("votes") or 0), _human_request_status(r.get("status"), p.get("status_reason")),
                     r["doi"], r.get("title") or p.get("title") or r["doi"], r.get("issue") or requests_issue_url(repo, r["doi"])))
    for d, p in planned.items():
        if d not in seen:
            rows.append((0, _human_request_status(p.get("status"), p.get("status_reason")),
                         d, p.get("title") or d, requests_issue_url(repo, d)))
    if not rows:
        lines.append("No paper requests yet.")
    else:
        for votes, st_lbl, doi, title, issue in rows:
            vote_word = "1 vote" if votes == 1 else f"{votes} votes"
            lines.append(f"- **{title}** — DOI {doi} · {st_lbl} ({vote_word}) · Vote: {issue}")
    return "\n".join(lines) + "\n"


def _public_request_rows(raw_reqs, avail_dois, in_progress_dois, planned_map):
    out = []
    for r in raw_reqs:
        d = r["doi"]
        if d in avail_dois:
            pub_st = "available"
        elif d in in_progress_dois:
            pub_st = "in_progress"
        else:
            p_st = (planned_map.get(d) or {}).get("status")
            pub_st = p_st if p_st in ("checking_data", "in_progress", "checking", "not_possible", "requested") else "requested"
        out.append({**r, "status": pub_st})
    return out


def build(reg, out=None, base_url=None, install_cmd=None, l1_dir=None, include_unreleased=False):
    cfg = reg.config.get("site", {})
    base = (base_url or cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
    install = install_cmd or cfg.get("install_cmd") or "uvx runpapers"
    repo = reg.config.get("publish", {}).get("github_repo", "runpapers/runpapers")
    from .catalog import _planned_entry, _published_at
    from .release import published
    voc = vocab.load(root=reg.root)
    raw_reqs = requests_summary(reg)
    req_votes = {r["doi"]: r["votes"] for r in raw_reqs}
    req_issues = {r["doi"]: r.get("issue") for r in raw_reqs if r.get("issue")}
    out = Path(out or reg.root / "build" / "site")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "papers").mkdir(parents=True, exist_ok=True)
    tokens_css = _copy_brand_assets(out, reg.root)
    (out / "style.css").write_text(tokens_css + FONT_FACES_CSS + CSS + papers_page.PAPERS_CSS)
    (out / "site.js").write_text(SITE_JS)
    (out / "search.js").write_text(papers_page.SEARCH_JS)
    l1_dir = Path(l1_dir or reg.root / "build" / "l1")

    planned_all = reg.planned()
    cards = []
    unreleased_packs = {}
    for pk in reg.packs():
        rel = published(pk)
        if rel is None and not include_unreleased:
            unreleased_packs[pk.doi] = pk
            continue
        st = status(pk)
        card = {
            **pk.card(),
            "status": "available",
            "votes": req_votes.get(pk.doi, 0),
            "issue_url": req_issues.get(pk.doi),
            "published_at": _published_at(pk),
            "usage": None,
            "data": pk.data,
            "release": rel,
            "resources": resources(pk, l1_dir),
        }
        cards.append(card)
        pdir = out / ids.page_path(pk.doi)
        (pdir / "pack").mkdir(parents=True)
        files = []
        for rel_file in pk.files():
            if not shipped(rel_file):
                continue
            (pdir / "pack" / rel_file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pk.dir / rel_file, pdir / "pack" / rel_file)
            files.append({"path": rel_file, "sha256": sha256_file(pk.dir / rel_file), "size": (pk.dir / rel_file).stat().st_size})
        (pdir / "pack.json").write_text(json.dumps({"doi": pk.doi, "version": pk.version, "pack_hash": pk.content_hash(),
                                                    "files": files}, indent=1))
        figs, panel_results = [], {}
        src = l1_dir / ids.doi_relpath(pk.doi)
        if st["badges"]["runs"] == "pass":
            l1 = record(pk, "l1") or {}
            l1_recs = (l1.get("recipes") or {}) if l1.get("pack_hash") == pk.content_hash() else {}
            for r in pk.recipes:
                rid = r["id"]
                res = (read_json(src / rid / "result.json") if src.is_dir() else None) or l1_recs.get(rid)
                if res and res.get("checks"):
                    targets = pk.targets_for(rid)
                    panel_results[rid] = {
                        "pass": bool(res.get("pass")),
                        "checks": [
                            {**c, "paper_display": format_expected(c.get("expected"), check_tolerance(c, targets))}
                            for c in res["checks"]
                        ],
                    }
            if src.is_dir():
                known_rids = {r["id"]: i for i, r in enumerate(pk.recipes)}
                pngs = []
                for f in sorted(src.glob("*/*.png")):
                    rid = f.parent.name
                    if rid not in known_rids:
                        continue
                    res = read_json(f.parent / "result.json") or l1_recs.get(rid)
                    if res is not None and not res.get("pass", False):
                        continue
                    pngs.append((known_rids[rid], rid, f))
                pngs.sort(key=lambda x: (x[0], x[1], x[2].name))
                if pngs:
                    (pdir / "figures").mkdir()
                    for _, rid, f in pngs:
                        name = f"{rid}-{f.name}"
                        shutil.copy2(f, pdir / "figures" / name)
                        figs.append((name, rid))
        (pdir / "index.html").write_text(paper_html(card, base, install, figs, panel_results, repo=repo))
        (pdir / "index.md").write_text(paper_md(card, base, install, panel_results))
        (pdir / "AGENT.md").write_text(agent_md(card, base, install))
        _redirect(out / "doi" / ids.doi_relpath(pk.doi), f"{base}/{ids.page_path(pk.doi)}/", card["title"])

    card_dois = {c["doi"] for c in cards}
    planned = {}
    for d, p in planned_all.items():
        if d in card_dois:
            continue
        if d in unreleased_packs:
            upk = unreleased_packs[d]
            merged_tags = upk.tags if any(upk.tags.values()) else p.get("tags")
            planned[d] = {**p, "tags": vocab.normalize_tags(merged_tags), "status": "in_progress"}
        else:
            planned[d] = dict(p)
    for d, upk in unreleased_packs.items():
        if d not in card_dois and d not in planned:
            planned[d] = {
                "doi": d,
                "pmid": upk.paper.get("pmid"),
                "pmcid": upk.paper.get("pmcid"),
                "preprint_doi": upk.paper.get("preprint_doi"),
                "title": upk.title,
                "first_author": upk.paper.get("first_author"),
                "senior_author": upk.paper.get("senior_author"),
                "journal": upk.paper.get("journal"),
                "year": upk.paper.get("year"),
                "collections": upk.paper.get("collections", []),
                "tags": upk.tags,
                "status": "in_progress",
            }

    reqs = _public_request_rows(raw_reqs, card_dois, set(unreleased_packs), planned)
    new_req = requests_issue_url(repo)

    search_sources = list(cards)
    seen_search = set(card_dois)
    for d, p in planned.items():
        seen_search.add(d)
        search_sources.append(_planned_entry(d, p, votes=req_votes.get(d, 0), repo=repo, issue_url=req_issues.get(d)))
    for r in reqs:
        d = r["doi"]
        if d not in seen_search:
            seen_search.add(d)
            search_sources.append(_planned_entry(d, {"title": r.get("title") or d, "status": r.get("status")},
                                                 votes=r.get("votes", 0), repo=repo, issue_url=r.get("issue")))

    search_index = search.build_search_index(search_sources, voc=voc, repo=repo)
    (out / "papers" / "search.json").write_text(json.dumps(search_index, indent=1))
    (out / "papers" / "index.html").write_text(
        page(
            "Papers · RunPapers",
            papers_page.papers_body_html(search_index, repo=repo),
            depth=1,
            desc=ONE_SENTENCE,
            md_twin="index.md",
            extra_scripts=("../search.js",),
            active="papers",
            base=base,
            repo=repo,
        )
    )
    (out / "papers" / "index.md").write_text(papers_page.papers_md(search_index, base, install=install, repo=repo))

    # Home (/)
    (out / "index.html").write_text(
        page(
            "RunPapers · Reproduce the paper. Then ask your own question.",
            home_html(cards, new_req),
            depth=0,
            desc=ONE_SENTENCE,
            md_twin="index.md",
            base=base,
            repo=repo,
        )
    )
    (out / "index.md").write_text(index_md(cards, base, install, repo))

    # /requests/
    (out / "requests").mkdir(parents=True, exist_ok=True)
    (out / "requests" / "index.html").write_text(
        page(
            "Requested papers · RunPapers",
            requests_html(reqs, planned, install, repo=repo),
            depth=1,
            desc="Ask for a paper you want to use with your AI agent or vote on requested papers.",
            md_twin="index.md",
            active="requests",
            base=base,
            repo=repo,
        )
    )
    (out / "requests" / "index.md").write_text(requests_md(reqs, planned, install, repo))

    # /guide/
    (out / "guide").mkdir(parents=True, exist_ok=True)
    (out / "guide" / "index.html").write_text(
        page(
            "Guide · RunPapers",
            md_html(guide_text(install, repo)),
            depth=1,
            desc="How to reproduce a paper's figures and ask your own questions with your AI agent.",
            md_twin="index.md",
            active="guide",
            base=base,
            repo=repo,
        )
    )
    (out / "guide" / "index.md").write_text(guide_md(install, repo))

    # /about/
    (out / "about").mkdir(parents=True, exist_ok=True)
    (out / "about" / "index.html").write_text(
        page(
            "About RunPapers",
            about_html(install, repo=repo),
            depth=1,
            desc=ONE_SENTENCE,
            md_twin="index.md",
            active="about",
            base=base,
            repo=repo,
        )
    )
    (out / "about" / "index.md").write_text(about_md(install, repo=repo))

    # Legacy top-level HTML redirects -> canonical directory routes
    _redirect_file(out / "guide.html", f"{base}/guide/", "Guide · RunPapers")
    _redirect_file(out / "requests.html", f"{base}/requests/", "Requested papers · RunPapers")
    _redirect_file(out / "about.html", f"{base}/about/", "About RunPapers")

    # Machine-readable index.json (available packs only; zero internal stage or badges keys)
    index = {
        "generated": now(),
        "rp_version": __version__,
        "base_url": base,
        "install": install,
        "github_repo": repo,
        "vocab": voc.to_dict(),
        "papers": [
            {k: c[k] for k in (
                "doi", "pmid", "pmcid", "preprint_doi", "title", "first_author", "senior_author", "journal",
                "year", "slug", "collections", "version", "summary", "tags", "profile", "recipes", "data_bytes",
                "resources", "questions", "status", "votes", "published_at",
            )}
            | {
                "data_terms": _data_terms(c),
                "release": c.get("release"),
                "url": f"{base}/{ids.page_path(c['doi'])}/",
                "agent": f"{base}/{ids.page_path(c['doi'])}/AGENT.md",
            }
            for c in cards
        ],
        "planned": [
            {
                "doi": d,
                **{k: p.get(k) for k in ("title", "pmid", "first_author", "senior_author", "journal", "year",
                                         "collection", "tags", "status", "status_reason")},
                "votes": req_votes.get(d, 0),
                "issue_url": req_issues.get(d) or requests_issue_url(repo, d),
            }
            for d, p in planned.items()
        ],
        "requests": reqs,
    }
    (out / "index.json").write_text(json.dumps(index, indent=1))
    (out / "requests.json").write_text(json.dumps(reqs, indent=1))
    (out / "llms.txt").write_text("\n".join([
        "# RunPapers", "",
        "> Published papers your own AI agent can run: original data, figure-reproducing recipes, paper target numbers and agent guardrails.",
        "",
        f"To use a paper: fetch `{base}/papers/<DOI as a name>/AGENT.md` (exact `agent` URL in `{base}/index.json`) and follow it.",
        f"CLI: `{install}` · Local MCP server (stdio, zero extra deps): `{install} mcp` · Multi-paper workspace: `{install} meeting \"<topic>\"`.",
        f"Search & browse: {base}/papers/index.md (`{base}/papers/search.json`) · Catalog: {base}/index.json · Guide: {base}/guide/index.md · About: {base}/about/index.md · Requests: {base}/requests/index.md",
        "", "## Available papers", "",
    ] + ([
        f"- [{c['title']}]({base}/{ids.page_path(c['doi'])}/index.md): DOI {c['doi']}" + (f", PMID {c['pmid']}" if c.get("pmid") else "")
        for c in cards
    ] or ["- No packs available yet."])) + "\n")
    (out / "AGENT.md").write_text(
        f"# RunPapers for AI agents\n\n"
        f"1. Search `{base}/index.json` or `{base}/papers/search.json` (or run `{install} search \"<query>\" --json` / connect `{install} mcp`) by DOI, PMID, PMCID, title, author, species, tissue, data type, disease, cell type or gene.\n"
        f"2. Fetch the paper's `agent` URL (`{base}/papers/<DOI as a name>/AGENT.md`) and follow its steps in order (or compare several papers with `{install} meeting \"<topic>\"`).\n"
        f"3. Respect every guardrail in the pack's `SKILL.md` (replicate unit, confounders, unsupported questions) and inform the user of the source's `data_terms` before commercial use or publication.\n"
        f"4. Request or vote for a missing paper: `{install} request <DOI|PMID>` prints the GitHub link that files the request or adds the user's vote.\n"
    )
    return out, len(cards)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def guess_type(self, path):
        if str(path).endswith((".md", "llms.txt")):
            return "text/markdown; charset=utf-8"
        return super().guess_type(path)


def serve(directory, host="127.0.0.1", port=8765, quiet=False):
    handler = partial(_Quiet if quiet else http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    return httpd
