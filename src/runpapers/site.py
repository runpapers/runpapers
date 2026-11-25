"""The static website, generated from the registry. Every page has a machine twin (.md), plus llms.txt,
index.json and a per-paper AGENT.md that a user's agent follows. No server code: any static host works."""
import html
import http.server
import json
import re
import shutil
from functools import partial
from pathlib import Path

from . import __version__, ids
from .registry import sha256_file
from .requests_log import summary as requests_summary
from .verify import now, status
from .workspace import shipped

BADGES = [
    ("runs", "Runs", "Lint passed, data checksums matched, and every lite recipe re-ran from the original data under laptop/CI limits and met the paper's numbers (automatic)."),
    ("checked", "Checked", "An independent reviewer (never the pack builder) compared every reproduced panel side by side with the published figure and checked the targets and guardrails."),
    ("reproduces", "Reproduces", "A named scientist signed off the reproduction after a passing independent review."),
    ("agent-tested", "Agent-tested", "Fresh AI agents from at least two companies, given only the copy-prompt in an empty folder, reproduced the figure and answered held-out questions."),
    ("endorsed", "Author-endorsed", "An ORCID-verified author of the paper approved this pack."),
]

CSS = """
:root{--fg:#1d2230;--mut:#5b6475;--bg:#fff;--soft:#f4f6fa;--line:#e3e7ef;--acc:#2456d6;
--runs:#1f8a4c;--checked:#0f7c86;--reproduces:#2456d6;--agent-tested:#7a3fc4;--endorsed:#b07d0b}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--fg);background:var(--bg)}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--line)}.wrap{max-width:980px;margin:0 auto;padding:0 20px}
header .wrap{display:flex;align-items:center;gap:18px;height:58px}.logo{font-weight:700;font-size:20px;color:var(--fg)}
.logo span{color:var(--acc)}nav a{color:var(--mut);margin-right:14px;font-size:15px}
h1{font-size:28px;line-height:1.25;margin:28px 0 6px}h2{font-size:20px;margin:30px 0 10px}
.mut{color:var(--mut)}.small{font-size:14px}
.hero{padding:34px 0 10px}.hero p{font-size:18px;color:var(--mut);max-width:740px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}
.step{background:var(--soft);border-radius:10px;padding:14px 16px}.step b{display:block;margin-bottom:4px}
.note{background:var(--soft);border-left:3px solid var(--acc);border-radius:6px;padding:10px 14px;margin:12px 0;font-size:14px}
input.search{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;font-size:16px;margin:8px 0 14px}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}
.card .t{font-weight:600;font-size:17px}.card .m{color:var(--mut);font-size:14px;margin:2px 0 6px}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:20px;margin:2px 4px 2px 0;color:#fff}
.badge.off{background:#e9ecf2;color:#8a92a3}.badge.stale{background:#e9ecf2;color:#5b6475;border:1px dashed #9aa3b5}
.prompt{position:relative;background:#0f1424;color:#e8ecf7;border-radius:12px;padding:16px 18px;font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap}
.copy{position:absolute;top:10px;right:10px;background:var(--acc);color:#fff;border:0;border-radius:8px;padding:6px 12px;font-weight:600;cursor:pointer}
.tabs button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 10px;margin:0 6px 6px 0;cursor:pointer}
.tabs button.on{background:var(--fg);color:#fff;border-color:var(--fg)}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:7px 6px;text-align:left;vertical-align:top}
.figs{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}.figs img{width:100%;border:1px solid var(--line);border-radius:8px}
code{background:var(--soft);padding:1px 5px;border-radius:5px;font-size:90%}
footer{margin:40px 0;color:var(--mut);font-size:13px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:700px){.steps{grid-template-columns:1fr}}
"""

COPY_JS = """
function cp(id,b){navigator.clipboard.writeText(document.getElementById(id).innerText);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1500)}
function tab(btn){document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));btn.classList.add('on');document.getElementById('how').textContent=btn.dataset.how}
function filt(q){q=q.toLowerCase();document.querySelectorAll('[data-s]').forEach(c=>c.style.display=c.dataset.s.includes(q)?'':'none')}
"""

HOW = {
    "Claude Code": "Open a terminal in an empty folder, run claude, and paste the prompt below.",
    "Codex": "Open a terminal in an empty folder, run codex, and paste the prompt below.",
    "Antigravity": "Open an empty folder in Antigravity (or run agy) and paste the prompt into the agent panel.",
    "Other agents": "Any AI agent that can fetch a web page and run terminal commands works: Gemini CLI, Cursor, Windsurf, goose, OpenCode.",
}

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
        out.append(f'<a href="{e(url)}">{e(url)}</a>')
        pos = end
    out.append(e(s[pos:]))
    return "".join(out)


def badge_html(b, state):
    lab = dict((k, v) for k, v, _ in BADGES).get(b, b)
    tip = dict((k, t) for k, _, t in BADGES).get(b, "")
    if state == "pass":
        return f'<span class="badge" style="background:var(--{b})" title="{e(tip)}">{e(lab)}</span>'
    if state == "stale":
        return f'<span class="badge stale" title="Earned by an earlier version; being re-checked after a pack update">{e(lab)} (re-checking)</span>'
    if state == "partial":
        return f'<span class="badge stale" title="{e(tip)}">{e(lab)} (in progress)</span>'
    return f'<span class="badge off" title="{e(tip)}">{e(lab)}</span>'


def page(title, body, depth=0, desc="", md_twin=None):
    up = "../" * depth
    alt = f'<link rel="alternate" type="text/markdown" href="{e(md_twin)}">' if md_twin else ""
    twin_note = f' · <a href="{e(md_twin)}">{e(md_twin)}</a>' if md_twin else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">{alt}
<link rel="stylesheet" href="{up}style.css"></head><body>
<header><div class="wrap"><a class="logo" href="{up}index.html">Run<span>Papers</span></a>
<nav><a href="{up}index.html">Papers</a><a href="{up}requests.html">Requests</a><a href="{up}about.html">How it works</a><a href="{up}llms.txt">For agents</a></nav></div></header>
<main class="wrap">{body}</main>
<footer class="wrap">RunPapers v{__version__} · open source · every page has a plain-text twin for AI agents (<a href="{up}llms.txt">llms.txt</a>, <a href="{up}index.json">index.json</a>{twin_note}).</footer>
<script>{COPY_JS}</script></body></html>"""


def copy_prompt(card, base):
    doi = card["doi"]
    first = next((r for r in card["recipes"] if r.get("tier") == "lite"), (card["recipes"] or [{}])[0])
    panel = first.get("panel") or "a main figure"
    return (f"I want to work with the data from this paper using RunPapers:\n"
            f"  \"{card['title']}\" ({card.get('first_author', '').split()[-1] if card.get('first_author') else ''} et al., "
            f"{card.get('journal', '')} {card.get('year', '')}), DOI {doi}\n"
            f"Setup for you, the AI agent: fetch {base}/doi/{ids.doi_relpath(doi)}/AGENT.md (or `curl -sL` it) and follow it exactly.\n"
            f"Then:\n"
            f"1) Reproduce {panel} and show it to me, with a table of the paper's numbers next to yours.\n"
            f"2) Answer my question using the paper's data: <write your question here>")


def _data_terms(card):
    return sorted({d.get("license", "").strip() for d in card.get("data", []) if d.get("license", "").strip()})


def agent_md(card, base, install):
    doi = card["doi"]
    src_arg = f" --source {base}" if base != "https://runpapers.org" else ""
    terms = "; ".join(_data_terms(card)) or "see the paper page and original repository"
    return f"""# RunPapers: agent setup for "{card['title']}"

You are helping a scientist use the verified RunPapers pack for this paper (DOI {doi}, version {card['version']}).
Follow these steps in order. Ask the user before anything not listed here.

1. Check that `uv` is installed: `uv --version`. If it is missing, install it with the official installer:
   - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Get the pack and its laptop-size ("lite") data, about {fmt_bytes(card['lite_bytes'])}, from the paper's original repositories:
   `{install} get {doi}{src_arg} --rp-cmd "{install}"`
   This creates the folder `./{card['citekey']}/`. Work inside it from now on (`cd {card['citekey']}`).
3. Read `SKILL.md` in that folder completely. It explains the data, the recipes and the guardrails. Follow the guardrails.
4. Reproduce a published panel: `{install} run <recipe>`. Recipes:
{chr(10).join(f"   - `{r['id']}`: {r['panel']}: {r['title']}" for r in card['recipes'])}
   Each run writes `out/<recipe>/` with the figure, `metrics.json` and `result.json` (the paper's numbers next to yours).
   Show the user the figure and report plainly which numbers matched.
5. For the user's own questions, write scripts in `analyses/` that read `data/`, as SKILL.md describes. State what you
   computed, the replicate unit, and how confident you are. Never present a guess as a result.
6. Cite the paper (https://doi.org/{doi}) and the pack (RunPapers {doi} v{card['version']}, {base}/doi/{ids.doi_relpath(doi)}/).
7. Data terms: {terms}. Tell the user before they publish or use the data commercially.

Verification of this pack: {", ".join(k for k, v in card['badges'].items() if v == 'pass') or "not yet verified"}.
"""


def paper_md(card, base, install="uvx runpapers"):
    doi = card["doi"]
    src_arg = f" --source {base}" if base != "https://runpapers.org" else ""
    terms = "; ".join(_data_terms(card)) or "see the original repository"
    lines = [
        f"# {card['title']}", "",
        f"{card.get('first_author', '')} et al. *{card.get('journal', '')}* {card.get('year', '')}. DOI {doi}"
        + (f" · PMID {card['pmid']}" if card.get("pmid") else ""), "",
        f"RunPapers pack v{card['version']} · stage: {card['stage']} · badges: "
        + (", ".join(k for k, v in card["badges"].items() if v == "pass") or "none yet"), "",
        card.get("summary", ""), "",
        "## Use it from your AI agent", "",
        "```", copy_prompt(card, base), "```", "",
        f"Agent setup: {base}/doi/{ids.doi_relpath(doi)}/AGENT.md",
        f"Terminal setup: `{install} get {doi}{src_arg}`", "",
        "## Reproducible panels", "",
    ]
    lines += [f"- `{r['id']}` ({r['tier']}): {r['panel']}: {r['title']}" for r in card["recipes"]]
    if card.get("questions"):
        lines += ["", "## Example questions", ""] + [f"- {q}" for q in card["questions"]]
    if card.get("data"):
        lines += ["", "## Data and terms", "", f"Source data terms: {terms}", ""]
        for d in card["data"]:
            sz = "controlled access" if d.get("access") == "controlled" else fmt_bytes(d.get("size", 0))
            lines.append(f"- **{d.get('title') or d['id']}** (`{d.get('tier', 'lite')}`, {sz}) — {d.get('source', '')}")
    lines += ["", "## Cite", "",
              f"Cite the paper (https://doi.org/{doi}) and the pack: RunPapers pack for {doi}, version {card['version']}, {base}/doi/{ids.doi_relpath(doi)}/"]
    return "\n".join(lines) + "\n"


def paper_html(card, base, install, figs):
    doi = card["doi"]
    depth = len(ids.doi_relpath(doi).split("/")) + 1
    up = "../" * depth
    pid = "p0"
    src_arg = f" --source {base}" if base != "https://runpapers.org" else ""
    tabs = "".join(
        f'<button class="{"on" if i == 0 else ""}" data-how="{e(v)}" onclick="tab(this)">{e(k)}</button>'
        for i, (k, v) in enumerate(HOW.items())
    )
    rec_by_id = {r["id"]: r for r in card["recipes"]}
    rec_rows = "".join(
        f"<tr><td><code>{e(r['id'])}</code></td><td>{e(r['panel'])}</td><td>{e(r['title'])}</td><td>{e(r['tier'])}</td></tr>"
        for r in card["recipes"]
    )
    fig_items = []
    for fname, rid in figs:
        r = rec_by_id.get(rid, {})
        cap = f"{r.get('panel', rid)}: {r.get('title', fname)}" if r else fname
        fig_items.append(
            f'<figure style="margin:0"><img src="figures/{e(fname)}" alt="{e(cap)}">'
            f'<figcaption class="small mut">{e(cap)}</figcaption></figure>'
        )
    fig_html = "".join(fig_items)
    qs = "".join(f"<li>{e(q)}</li>" for q in card.get("questions") or [])
    ids_line = f'DOI <a href="{ids.doi_url(doi)}">{e(doi)}</a>' + (
        f' · PMID <a href="{ids.pubmed_url(card["pmid"])}">{e(card["pmid"])}</a>' if card.get("pmid") else "")
    data_rows = "".join(
        f"<tr><td>{e(d.get('title') or d['id'])}</td><td>{e(d.get('tier', 'lite'))}</td>"
        f"<td>{e('controlled' if d.get('access') == 'controlled' else fmt_bytes(d.get('size', 0)))}</td>"
        f"<td>{e(d.get('source', ''))}</td><td>{linkify(d.get('license', 'not recorded'))}</td></tr>"
        for d in card.get("data", [])
    )
    terms = _data_terms(card)
    terms_note = (
        f'<div class="note"><b>Data terms:</b> Data are never re-hosted by RunPapers; your agent downloads each file '
        f'directly from its original repository with checksum verification. Terms from the data source: '
        f'{"; ".join(linkify(t) for t in terms)}. Check these terms before commercial use or publication.</div>'
        if terms else ""
    )
    body = f"""
<h1>{e(card['title'])}</h1>
<div class="mut">{e(card.get('first_author', ''))} et al. · <i>{e(card.get('journal', ''))}</i> {e(card.get('year', ''))} · {ids_line}</div>
<div style="margin:10px 0">{''.join(badge_html(b, card['badges'].get(b, 'none')) for b, _, _ in BADGES)}
<span class="small mut">pack v{e(card['version'])} · <a href="{up}about.html#badges">what these badges mean</a></span></div>
<p>{e(card.get('summary', ''))}</p>
<h2>Use it from your own AI agent</h2>
<div class="tabs">{tabs}</div><p class="small mut" id="how">{e(next(iter(HOW.values())))}</p>
<div class="prompt"><button class="copy" onclick="cp('{pid}',this)">Copy</button><span id="{pid}">{e(copy_prompt(card, base))}</span></div>
<p class="small mut">Your agent downloads about {e(fmt_bytes(card['lite_bytes']))} from the paper's original data repositories and runs everything locally on your computer. Nothing is sent to RunPapers. Or from a terminal: <code>{e(install)} get {e(doi)}{e(src_arg)}</code></p>
<h2>Reproducible panels</h2><table><tr><th>Recipe</th><th>Panel</th><th>What it shows</th><th>Tier</th></tr>{rec_rows}</table>
{('<h2>Reproduced figures</h2><div class="figs">' + fig_html + '</div>') if fig_items else ''}
{('<h2>Example questions</h2><ul>' + qs + '</ul>') if qs else ''}
<h2>Data</h2>{terms_note}<table><tr><th>File</th><th>Tier</th><th>Size</th><th>Source</th><th>Terms / license</th></tr>{data_rows}</table>
<h2>Cite</h2><p class="small">Cite the paper ({ids_line}), the original data source per its terms above, and this pack: RunPapers pack for {e(doi)}, version {e(card['version'])}, {e(base)}/doi/{e(ids.doi_relpath(doi))}/</p>
<p class="small mut">Machine-readable: <a href="index.md">index.md</a> · <a href="AGENT.md">AGENT.md</a> · <a href="pack.json">pack.json</a></p>
"""
    return page(f"{card['title']} · RunPapers", body, depth=depth, desc=card.get("summary", ""), md_twin="index.md")


def _search_blob(card):
    prof = card.get("profile") or {}
    prof_terms = [x for vals in prof.values() if isinstance(vals, list) for x in vals]
    parts = [
        card.get("title"), card.get("doi"), card.get("pmid"), card.get("pmcid"),
        card.get("first_author"), card.get("senior_author"), card.get("journal"),
        " ".join(card.get("collections") or []), card.get("summary"), *prof_terms,
    ]
    return " ".join(str(x).lower() for x in parts if x)


def index_md(cards, planned, base, install):
    lines = [
        "# RunPapers", "",
        "Ask a published paper's data your own questions, with your own AI agent.", "",
        "Each RunPapers pack pairs a paper's original public data (verified by checksum) with figure-reproducing recipes, "
        "the paper's own numbers as targets, and instructions (`SKILL.md`) that keep new analyses honest.", "",
        "## Published and active packs", "",
    ]
    if cards:
        for c in sorted(cards, key=lambda c: (c.get("year") or 0, c["title"]), reverse=True):
            badges = ", ".join(k for k, v in c["badges"].items() if v == "pass") or "in verification"
            lines.append(f"- [{c['title']}]({base}/doi/{ids.doi_relpath(c['doi'])}/index.md) — "
                         f"{c.get('first_author', '')} et al., *{c.get('journal', '')}* {c.get('year', '')} · "
                         f"DOI {c['doi']}" + (f" · PMID {c['pmid']}" if c.get("pmid") else "") + f" · badges: {badges}")
    else:
        lines.append("- No packs published yet.")
    if planned:
        lines += ["", f"## Coming next ({len(planned)} planned)", "",
                  f"Request or vote for a paper with `{install} request <DOI or PMID>` or `{install} vote <DOI>`.", ""]
        for d, p in list(planned.items())[:40]:
            au = f"{p['first_author']} et al., " if p.get("first_author") else ""
            jn = f"*{p['journal']}* {p.get('year', '')} · " if p.get("journal") else ""
            pm = f" · PMID {p['pmid']}" if p.get("pmid") else ""
            lines.append(f"- {p.get('title', d)} — {au}{jn}DOI {d}{pm}")
    return "\n".join(lines) + "\n"


def about_html(install):
    badge_rows = "".join(f"<tr><td>{badge_html(k, 'pass')}</td><td>{e(t)}</td></tr>" for k, _, t in BADGES)
    return f"""<h1>How RunPapers works</h1>
<p>RunPapers is an open, non-profit collection of verified paper packs. A pack turns one published paper into a workspace
that your own AI agent (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, ...) can run on your computer to reproduce
published figures from the original data and then answer new scientific questions.</p>
<div class="steps">
<div class="step"><b>Bring your own agent</b>RunPapers hosts no model and sees none of your questions. Everything runs locally on your machine using open tools (<code>uv</code> and Python).</div>
<div class="step"><b>Laptop-first ("lite" tier)</b>Every pack includes at least one main-figure recipe that runs on a standard laptop (aiming under 2 GB of public metadata or tables). Heavy expression or chromatin matrices belong to an optional "full" tier.</div>
<div class="step"><b>Guardrails for biology</b>Each pack's <code>SKILL.md</code> spells out the biological replicate unit (donors or animals, never individual cells), dissection or batch confounders, renamed cell-type labels, and questions the dataset cannot support.</div>
</div>
<h2 id="badges">Verification badges</h2>
<p class="small mut">Every badge is cryptographically bound to the SHA-256 content hash of the pack. Any edit to a recipe, target, data entry or instruction marks earlier badges as <em>re-checking</em> until verification passes again. Tolerances are locked to the paper's own printed numbers before running code; internal discrepancies in a paper are documented openly rather than hidden by widening tolerances.</p>
<table><tr><th>Badge</th><th>What was verified</th></tr>{badge_rows}</table>
<h2>Original data and source terms</h2>
<p>Packs never contain or re-host raw data files, and never redistribute copyrighted figure images unless the paper's license permits it. Instead, each pack points to the original public repository (such as the Allen Brain Cell Atlas, NCBI GEO, CELLxGENE, NeMO, or Zenodo) with exact byte sizes and MD5/SHA-256 checksums.</p>
<p>Data remain under the original repository's license or terms of use — never assumed to be CC BY. For example, datasets from the <b>Allen Brain Cell Atlas</b> are governed by the <a href="https://alleninstitute.org/terms-of-use/">Allen Institute Terms of Use</a> (noncommercial research use, citing both the paper and the Atlas per the Allen Institute Citation Policy). Controlled-access human datasets (such as dbGaP, EGA, or restricted NeMO files) are never downloaded automatically; packs provide access instructions instead.</p>
<h2>Request, contribute or cite</h2>
<p>Ask for a paper or vote one up in the queue from your terminal or agent: <code>{e(install)} request &lt;DOI or PMID&gt;</code> and <code>{e(install)} vote &lt;DOI&gt;</code>. You can also connect any MCP-capable agent directly to RunPapers via <code>{e(install)} mcp</code> (Skills over MCP) or assemble a multi-paper comparison workspace with <code>{e(install)} meeting "&lt;topic&gt;"</code>. To build or review a pack, see <code>CONTRIBUTING.md</code> and <code>skills/runpapers-builder</code> in the repository. When publishing work that uses a pack, cite the original paper, the data repository per its terms, and the archived RunPapers pack version.</p>"""


def about_md(install):
    lines = [
        "# How RunPapers works", "",
        "RunPapers is an open, non-profit collection of verified paper packs. A pack turns one published paper into a "
        "workspace that your own AI agent (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, ...) runs on your computer "
        "to reproduce published figures from the original data and answer new scientific questions.", "",
        "- **Bring your own agent:** RunPapers hosts no model and sees none of your questions; code runs locally via `uv`.",
        "- **Laptop-first (`lite` tier):** Every pack has at least one main-figure recipe that runs on a laptop (aiming under 2 GB); larger matrices live in an optional `full` tier.",
        "- **Guardrails for biology:** `SKILL.md` records the true replicate unit (donors or animals, not cells), confounders, label changes, documented paper discrepancies, and unsupported questions.",
        f"- **MCP server & multi-paper meetings:** Run `{install} mcp` to expose paper search, metadata, and `SKILL.md` over MCP, or `{install} meeting \"<topic>\"` to build a multi-paper synthesis workspace.", "",
        "## Verification badges", "",
        "Every badge is bound to the SHA-256 content hash of the pack; any change resets badges to `stale` until re-verified.", "",
    ]
    lines += [f"- **{label}** (`{key}`): {desc}" for key, label, desc in BADGES]
    lines += [
        "", "## Original data and source terms", "",
        "Packs never re-host raw data. Recipes download files directly from their original repositories with size and MD5/SHA-256 checksum checks, "
        "and each dataset keeps its source terms (for example, the Allen Brain Cell Atlas is under the Allen Institute Terms of Use: noncommercial research use "
        "with citation required, https://alleninstitute.org/terms-of-use/, not CC BY). Controlled-access datasets are never downloaded automatically.", "",
        "## Request, contribute or cite", "",
        f"Request or vote for a paper: `{install} request <DOI or PMID>` / `{install} vote <DOI>`. "
        "Cite the original paper, the data repository per its terms, and the RunPapers pack version.",
    ]
    return "\n".join(lines) + "\n"


def requests_md(reqs, install):
    lines = [
        "# Requested papers", "",
        f"Ask for a paper or vote for one from your agent or terminal: `{install} request <DOI or PMID>` and `{install} vote <DOI>`.", "",
    ]
    if not reqs:
        lines.append("No paper requests logged yet.")
    else:
        for r in reqs:
            lines.append(f"- **{r['votes']} vote(s)** · `{r['status']}` · DOI {r['doi']} — {r.get('title') or ''}")
    return "\n".join(lines) + "\n"


def build(reg, out=None, base_url=None, install_cmd=None, l1_dir=None):
    cfg = reg.config.get("site", {})
    base = (base_url or cfg.get("base_url") or "https://runpapers.org").rstrip("/")
    install = install_cmd or cfg.get("install_cmd") or "uvx runpapers"
    out = Path(out or reg.root / "build" / "site")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "style.css").write_text(CSS)
    l1_dir = Path(l1_dir or reg.root / "build" / "l1")
    cards = []
    for pk in reg.packs():
        st = status(pk)
        card = {**pk.card(), **{k: st[k] for k in ("stage", "badges")}, "data": pk.data}
        cards.append(card)
        pdir = out / "doi" / ids.doi_relpath(pk.doi)
        (pdir / "pack").mkdir(parents=True)
        files = []
        for rel in pk.files():
            if not shipped(rel):
                continue
            (pdir / "pack" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pk.dir / rel, pdir / "pack" / rel)
            files.append({"path": rel, "sha256": sha256_file(pk.dir / rel), "size": (pk.dir / rel).stat().st_size})
        (pdir / "pack.json").write_text(json.dumps({"doi": pk.doi, "version": pk.version, "pack_hash": pk.content_hash(),
                                                    "files": files}, indent=1))
        figs = []
        src = l1_dir / ids.doi_relpath(pk.doi)
        if st["badges"]["runs"] == "pass" and src.is_dir():
            (pdir / "figures").mkdir()
            for f in sorted(src.glob("*/*.png")):
                name = f"{f.parent.name}-{f.name}"
                shutil.copy2(f, pdir / "figures" / name)
                figs.append((name, f.parent.name))
        (pdir / "index.html").write_text(paper_html(card, base, install, figs))
        (pdir / "index.md").write_text(paper_md(card, base, install))
        (pdir / "AGENT.md").write_text(agent_md(card, base, install))
    planned = {d: p for d, p in reg.planned().items() if d not in {c["doi"] for c in cards}}
    reqs = requests_summary(reg)
    # index
    rows = []
    for c in sorted(cards, key=lambda c: (c.get("year") or 0, c["title"]), reverse=True):
        s = _search_blob(c)
        pmid_txt = f" · PMID {e(c['pmid'])}" if c.get("pmid") else ""
        rows.append(f'<div class="card" data-s="{e(s)}"><a class="t" href="doi/{ids.doi_relpath(c["doi"])}/index.html">{e(c["title"])}</a>'
                    f'<div class="m">{e(c.get("first_author", ""))} et al. · <i>{e(c.get("journal", ""))}</i> {e(c.get("year", ""))} · DOI {e(c["doi"])}{pmid_txt}</div>'
                    f'<div class="small mut" style="margin:4px 0 8px">{e(c.get("summary", ""))}</div>'
                    f'{"".join(badge_html(b, c["badges"].get(b, "none")) for b, _, _ in BADGES)}</div>')
    planned_items = []
    for d, p in list(planned.items())[:40]:
        ps = " ".join(str(x).lower() for x in (p.get("title"), d, p.get("pmid"), p.get("first_author"), p.get("senior_author"), p.get("journal")) if x)
        au = f"{e(p['first_author'])} et al. · " if p.get("first_author") else ""
        jn = f"<i>{e(p['journal'])}</i> {e(p.get('year', ''))} · " if p.get("journal") else ""
        pm = f' · PMID <a href="{ids.pubmed_url(p["pmid"])}">{e(p["pmid"])}</a>' if p.get("pmid") else ""
        planned_items.append(f'<li data-s="{e(ps)}"><b>{e(p.get("title"))}</b><br><span class="mut">{au}{jn}DOI <a href="{ids.doi_url(d)}">{e(d)}</a>{pm}</span></li>')
    body = f"""<div class="hero"><h1>Ask a published paper's data your own questions, with your own AI agent.</h1>
<p>Each RunPapers pack turns one paper into something any AI agent can use on your computer: the original public data, recipes that reproduce its figures,
and scientific guardrails that keep new analyses honest. Every pack is verified before it carries a <a href="about.html#badges">badge</a>.</p></div>
<div class="steps"><div class="step"><b>1. Find the paper</b>Search by title, author, gene, cell type, tissue, DOI or PMID — or request one.</div>
<div class="step"><b>2. Copy one prompt</b>Paste it into Claude Code, Codex, Antigravity or any agent that can run commands.</div>
<div class="step"><b>3. Reproduce, then ask</b>Your agent reproduces a published panel first, then answers your questions locally.</div></div>
<input class="search" placeholder="Search by title, author, gene, cell type, brain region, DOI or PMID" oninput="filt(this.value)">
{''.join(rows) or '<p class="mut">No packs published yet.</p>'}
<h2>Coming next</h2><p class="small mut">Planned papers ({len(planned)}). Request a paper or vote on the <a href="requests.html">requests page</a> to move one up.</p>
<ul class="small" style="line-height:1.65">{''.join(planned_items)}</ul>"""
    (out / "index.html").write_text(page("RunPapers: verified, agent-ready papers", body,
                                         desc="Reproduce figures and ask new questions of published papers' data with your own AI agent.",
                                         md_twin="index.md"))
    (out / "index.md").write_text(index_md(cards, planned, base, install))
    req_rows = ("".join(f"<tr><td>{e(r['title'] or '—')}</td><td><a href=\"{ids.doi_url(r['doi'])}\">{e(r['doi'])}</a></td>"
                        f"<td>{r['votes']}</td><td>{e(r['status'])}</td></tr>" for r in reqs)
                or '<tr><td colspan="4" class="mut">No paper requests logged yet. Use the command above to request any published paper by DOI or PMID.</td></tr>')
    (out / "requests.html").write_text(page("Requests · RunPapers", f"""<h1>Requested papers</h1>
<p class="mut">Ask for a paper to be packed or vote for one in the queue. From your agent or terminal:
<code>{e(install)} request &lt;DOI or PMID&gt;</code> and <code>{e(install)} vote &lt;DOI&gt;</code>.</p>
<table><tr><th>Paper</th><th>DOI</th><th>Votes</th><th>Status</th></tr>{req_rows}</table>""",
                                            desc="Requested papers and votes", md_twin="requests.md"))
    (out / "requests.md").write_text(requests_md(reqs, install))
    (out / "about.html").write_text(page("How RunPapers works", about_html(install),
                                         desc="How RunPapers verifies packs and handles original data terms", md_twin="about.md"))
    (out / "about.md").write_text(about_md(install))
    index = {"generated": now(), "rp_version": __version__, "base_url": base, "install": install,
             "papers": [{k: c[k] for k in ("doi", "pmid", "pmcid", "preprint_doi", "title", "first_author", "senior_author", "journal",
                                            "year", "citekey", "collections", "version", "summary", "profile", "recipes", "lite_bytes",
                                            "questions", "stage", "badges")}
                        | {"data_terms": _data_terms(c), "url": f"{base}/doi/{ids.doi_relpath(c['doi'])}/",
                           "agent": f"{base}/doi/{ids.doi_relpath(c['doi'])}/AGENT.md"}
                        for c in cards],
             "planned": [{"doi": d, **{k: p.get(k) for k in ("title", "pmid", "first_author", "journal", "year", "collection")}}
                         for d, p in planned.items()],
             "requests": reqs}
    (out / "index.json").write_text(json.dumps(index, indent=1))
    (out / "requests.json").write_text(json.dumps(reqs, indent=1))
    (out / "llms.txt").write_text("\n".join([
        "# RunPapers", "",
        "> Verified, agent-ready packs for published papers: original data, figure-reproducing recipes, paper target numbers and agent guardrails.",
        "", f"To use a paper: fetch `{base}/doi/<doi-prefix>/<doi-suffix>/AGENT.md` (exact `agent` URL in `{base}/index.json`) and follow it.",
        f"CLI: `{install}` · Local MCP server (stdio, zero extra deps): `{install} mcp` · Multi-paper workspace: `{install} meeting \"<topic>\"`.",
        f"Machine-readable catalog: {base}/index.json · How verification & data terms work: {base}/about.md · Requests: {base}/requests.md",
        "", "## Papers", ""] +
        [f"- [{c['title']}]({base}/doi/{ids.doi_relpath(c['doi'])}/index.md): DOI {c['doi']}" + (f", PMID {c['pmid']}" if c.get("pmid") else "")
         + f"; badges: {', '.join(k for k, v in c['badges'].items() if v == 'pass') or 'none'}" for c in cards]) + "\n")
    (out / "AGENT.md").write_text(
        f"# RunPapers for AI agents\n\n"
        f"1. Search `{base}/index.json` (or run `{install} search \"<query>\" --json` / connect `{install} mcp`) by DOI, PMID, PMCID, title, author, species, tissue, assay, cell type or gene.\n"
        f"2. Fetch the paper's `agent` URL (`{base}/doi/<doi-prefix>/<doi-suffix>/AGENT.md`) and follow its steps in order (or compare several papers with `{install} meeting \"<topic>\"`).\n"
        f"3. Respect every guardrail in the pack's `SKILL.md` (replicate unit, confounders, unsupported questions) and inform the user of the source's `data_terms` before commercial use or publication.\n"
        f"4. Request or vote for a missing paper: `{install} request <DOI|PMID>` / `{install} vote <DOI>`.\n"
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
