"""The static website, generated from the registry. Every page has a machine twin (.md), plus llms.txt,
index.json and a per-paper AGENT.md that a user's agent follows. No server code: any static host works."""
import html
import http.server
import json
import re
import shutil
from functools import partial
from pathlib import Path

from . import DEFAULT_BASE, __version__, ids
from .recipes import check_tolerance, format_expected
from .registry import read_json, sha256_file
from .requests_log import issue_url as requests_issue_url
from .requests_log import summary as requests_summary
from .verify import now, record, resources, status
from .workspace import shipped

BADGES = [
    ("runs", "Runs", "Lint passed, data checksums matched, and every recipe re-ran from the original data and met the paper's numbers (automatically in CI within CI limits, or recorded from HPC)."),
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
.pill{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:12px;background:var(--soft);color:var(--fg);white-space:nowrap}
.pill.hpc{background:#eef2ff;color:#1e3a8a;border:1px solid #c7d2fe}
details.targets{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}
details.targets summary{cursor:pointer;font-size:14px}
.tscroll{overflow-x:auto}
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

GUIDE = r'''# How to use RunPapers

RunPapers lets you reproduce a published paper's figures and then ask the paper's data your own questions, with the AI
agent you already use. You don't need to know Python: your agent sets everything up, downloads the data from the
paper's original repository and runs it on your own computer.

## What you need {#need}

- **An AI agent that can run terminal commands**: Claude Code, Codex, Antigravity, Gemini CLI, Cursor or similar. A
  chat-only assistant in a web browser can't run the recipes.
- **A computer** (macOS, Linux or Windows) with an internet connection and some free disk space. Each paper's page
  says how much it downloads.
- **A few minutes.** In our tests a fresh agent needed about 2 to 5 minutes from pasting the prompt to showing the
  reproduced figure, plus the download time on your connection. Nothing has to be installed beforehand: if `uv` (a small, widely used Python
  tool manager) is missing, your agent installs it with the official installer after asking you.

## Use a paper in five steps {#steps}

1. **Find the paper.** On the [Papers](index.html) page, type in the search box: words from the title, an author, a
   gene, a cell type, a brain region, a DOI or a PMID. Click the paper.
2. **Read the badges** at the top of its page. They say how thoroughly the pack was checked ([what they mean](#badges)).
   The page also lists the panels that can be reproduced and example questions.
3. **Copy the prompt.** Choose your agent's tab, then press **Copy**. There is nothing to fill in: your agent asks
   you what it needs (where to run it, and what you want to know) in one message.
4. **Start your agent in an empty folder and paste the prompt.** For Claude Code: open a terminal, run
   `mkdir my-paper`, then `cd my-paper`, then `claude`, and paste. For Codex, the same with `codex`. For Antigravity,
   open an empty folder and paste into the agent panel. Approve the commands your agent asks to run.
5. **Look at the result.** Your agent shows you the reproduced figure and a table with the paper's numbers next to its
   own, then answers your question.

Behind the scenes, your agent runs `{install} get <DOI>`. This makes a folder named after the paper's DOI (for example
`10-1016-j-cell-2026-10-012/`) with the pack's instructions (`SKILL.md`), recipes and target numbers. When your agent
runs a recipe (`{install} run <recipe>`), it downloads only that recipe's data files from the original repository and
checks every file against its checksum.

What you'll find in the folder:

- `SKILL.md`: what the data are, how the files join, and the guardrails for this paper. Your agent reads it first,
  and it's worth a skim for you too.
- `data/`: the original files. It links to a shared download folder, so the same data are never downloaded twice.
- `recipes/`: the scripts that reproduce the paper's panels.
- `out/<recipe>/`: the reproduced figure, its tables, and `result.json` (the paper's numbers next to ours).
- `analyses/`: where your agent saves the scripts it writes for your questions, so you can re-run or share them.
- `AGENTS.md`, `CLAUDE.md` and `GEMINI.md`: so that any agent you open in this folder later knows where things are.

## Check the reproduction {#check}

- Compare the reproduced figure with the published panel. The numbers should match; colours and layout may differ.
- `out/<recipe>/result.json` lists every number taken from the paper, ours, the tolerance allowed, and where the
  paper states it (main text, figure or supplementary table).
- When a paper disagrees with itself (for example, a number in the text that differs from its own table), the pack
  says so openly instead of hiding it, and your agent should tell you.

## Ask good questions {#questions}

Each paper's page lists example questions its data can answer. Some tips:

- Ask for values per donor (or per animal), not only pooled numbers. Donors, not cells, are the replicates.
- Ask your agent to show the code it ran and to save it in `analyses/`.
- Ask "What can't this dataset tell me?" Each pack lists the questions its data can't support, for example gene
  expression when the pack only covers cell metadata.
- If an answer surprises you, ask your agent to check it another way.
- To continue on another day, open your agent in the same folder. It reads `AGENTS.md` and carries on.

## What the badges mean {#badges}

- **Runs**: every recipe re-ran from the original data and matched the paper's numbers. Recipes within free-CI limits
  re-run automatically on every update; heavier or GPU panels are verified on HPC and recorded against the exact pack hash.
- **Checked**: an independent reviewer, never the pack's builder, compared every reproduced panel with the published
  figure and checked the numbers and instructions.
- **Reproduces**: a named scientist signed off the reproduction after the independent review.
- **Agent-tested**: fresh AI agents from at least two companies, given only the copy-prompt in an empty folder,
  reproduced the figure and correctly answered questions they had never seen.
- **Author-endorsed**: an author of the paper approved the pack.

Badges belong to one exact version of a pack. If anything in the pack changes, its badges show "re-checking" until
the checks pass again. More detail: [How it works](about.html#badges).

## Data terms and citing {#cite}

- RunPapers never re-hosts data. Your agent downloads every file from the original repository, under that
  repository's terms, which each paper's page shows. For example, data from the Allen Brain Cell Atlas are for
  noncommercial research, and you cite them as the Allen Institute Citation Policy describes.
- If you publish something made with a pack, cite three things: the paper, the data source as its terms require, and
  the pack version. Once a pack is released, its paper page shows a permanent archive DOI to cite.
- Privacy: RunPapers has no server that runs analyses and never sees your questions. Your prompts go only to your
  agent's provider, under your agreement with them.

## Request a paper or vote {#request}

- Requests and votes are public issues on [GitHub](https://github.com/{repo}/issues?q=label%3Arequest), so anyone can
  see what comes next. You need a free GitHub account.
- **Request:** on the [Requests](requests.html) page, press **Request a paper**, enter the DOI or PMID, and say what
  you'd like to do with the data. One request per paper.
- **Vote:** open the paper's request and add a thumbs-up. The papers with the most votes are packed first. Planned
  papers have a "request or vote" link too.
- **From your agent:** ask it to "request DOI ... on RunPapers". It runs `{install} request <DOI or PMID>`, which
  prints the right link.

## Report a problem {#problem}

If a recipe fails, a number disagrees with the paper, or a pack misled your agent, open an issue with the
[Report a problem with a pack](https://github.com/{repo}/issues/new?template=pack-problem.yml) form. Include the DOI,
which agent you used, and what it said (its last few messages are enough).

## For power users and agents {#power}

- **Terminal:** `{install} get <DOI>`, then `cd` into the folder and run `{install} run <recipe>`.
  `{install} --help` lists every command.
- **MCP:** connect RunPapers as an MCP server so any MCP-capable agent can search packs and read their instructions:
  `{install} mcp`. For Claude Code: `claude mcp add runpapers -- {install} mcp`. Other agents take the same command
  in their MCP settings.
- **Several papers at once:** `{install} meeting "<topic>"` builds one workspace with every matching pack.
- **Machine-readable site:** [llms.txt](llms.txt), and [index.json](index.json), which lists every paper with its
  `agent` URL. Every page also has a plain-text `.md` twin.

## Troubleshooting {#trouble}

- **"uv: command not found" right after installing it:** open a new terminal (the installer updates your PATH), or
  ask your agent to use the full path that the installer printed.
- **Windows:** use PowerShell. If Windows refuses to create the `data` link, the pack still works, because the data
  location is written in `AGENTS.md`.
- **The download stopped:** paste the same prompt again in the same folder. Downloads resume, and files that already
  passed their checksum are not downloaded again.
- **Your agent wants to install Python packages:** each recipe declares its own packages, and `uv` installs them in
  a separate environment. Your system Python is not touched.
- **Your agent ignored the pack's instructions:** tell it "Read SKILL.md and follow its guardrails", or start again
  in a new empty folder.
'''

_ANCHOR_RX = re.compile(r"\s*\{#([a-z0-9-]+)\}\s*$")


def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', s)


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
    return "\n".join(_ANCHOR_RX.sub("", l) for l in guide_text(install, repo).splitlines()) + "\n"


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
<nav><a href="{up}index.html">Papers</a><a href="{up}guide.html">Guide</a><a href="{up}requests.html">Requests</a><a href="{up}about.html">How it works</a><a href="{up}llms.txt">For agents</a></nav></div></header>
<main class="wrap">{body}</main>
<footer class="wrap">RunPapers v{__version__} · open source · every page has a plain-text twin for AI agents (<a href="{up}llms.txt">llms.txt</a>, <a href="{up}index.json">index.json</a>{twin_note}).</footer>
<script>{COPY_JS}</script></body></html>"""


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
    """The single question an agent asks before starting (2026-11-25, the PI: one round, cluster preferred)."""
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

You are helping a scientist use the verified RunPapers pack for this paper (DOI {doi}{pmid_txt}, version {card['version']}).
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

Verification of this pack: {", ".join(k for k, v in card['badges'].items() if v == 'pass') or "not yet verified"}.
"""


def paper_md(card, base, install="uvx runpapers", results=None):
    doi = card["doi"]
    src_arg = f" --source {base}" if base != DEFAULT_BASE else ""
    terms = "; ".join(_data_terms(card)) or "see the original repository"
    res = card.get("resources") or {}
    lines = [
        f"# {card['title']}", "",
        f"{card.get('first_author', '')} et al. *{card.get('journal', '')}* {card.get('year', '')}. DOI {doi}"
        + (f" · PMID {card['pmid']}" if card.get("pmid") else ""), "",
        f"RunPapers pack v{card['version']} · stage: {card['stage']} · badges: "
        + (", ".join(k for k, v in card["badges"].items() if v == "pass") or "none yet")
        + (f" · archived: https://doi.org/{card['release']['doi']}" if (card.get("release") or {}).get("doi") else ""), "",
        f"Size and time: {cost_text(res)}", "",
        card.get("summary", ""), "",
        "## Use it from your AI agent", "",
        "```", copy_prompt(card, base), "```", "",
        f"Agent setup: {base}/{ids.page_path(doi)}/AGENT.md",
        f"Terminal setup: `{install} get {doi}{src_arg}`", "",
        "## Reproducible panels", "",
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
        lines += ["", "## Example questions", ""] + [f"- {q}" for q in card["questions"]]
    if card.get("data"):
        lines += ["", "## Data and terms", "", f"Source data terms: {terms}", ""]
        for d in card["data"]:
            sz = "controlled access" if d.get("access") == "controlled" else fmt_bytes(d.get("size", 0))
            lines.append(f"- **{d.get('title') or d['id']}** (`{d['id']}`, {sz}) — {d.get('source', '')}")
    lines += ["", "## Cite", "",
              f"Cite the paper (https://doi.org/{doi}) and the pack: {_pack_cite(card, base)}"]
    return "\n".join(lines) + "\n"


def _redirect(d, url, title):
    """The old address /doi/<prefix>/<suffix>/ (also what people type after a DOI) sends visitors to the paper's page."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>'
        f'<link rel="canonical" href="{e(url)}"><meta http-equiv="refresh" content="0; url={e(url)}">'
        f'<meta name="robots" content="noindex"></head><body><p>This paper is at <a href="{e(url)}">{e(url)}</a>.</p></body></html>\n')


def _compute_pill(rr):
    hpc = rr.get("where") == "hpc" or rr.get("gpu") or float(rr.get("memory_gb", 8)) > 14 or float(rr.get("minutes", 20)) >= 60
    if rr.get("gpu"):
        return '<span class="pill hpc" title="Requires a GPU (HPC or workstation)">GPU · HPC</span>'
    if hpc:
        return '<span class="pill hpc" title="Runs on an HPC cluster or large-memory workstation">CPU · HPC</span>'
    return '<span class="pill">CPU</span>'


def paper_html(card, base, install, figs, results=None):
    doi = card["doi"]
    depth = len(ids.page_path(doi).split("/"))
    up = "../" * depth
    pid = "p0"
    src_arg = f" --source {base}" if base != DEFAULT_BASE else ""
    res = card.get("resources") or {}
    tabs = "".join(
        f'<button class="{"on" if i == 0 else ""}" data-how="{e(v)}" onclick="tab(this)">{e(k)}</button>'
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
    tot_compute = '<span class="pill hpc">GPU</span>' if res.get("gpu") else '<span class="pill">CPU</span>'
    tot_mem = f"{res.get('memory_gb', 0):g} GB peak"
    tot_row = (
        f'<tr style="font-weight:600"><td>Total</td><td colspan="2">{len(card["recipes"])} panel(s) (shared files counted once)</td>'
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
            f'{n_ok}/{len(req_checks)} paper targets matched</summary>'
            f'<div class="tscroll"><table><tr><th>Metric</th><th>Paper</th><th>Ours</th><th>Status</th><th>Source</th></tr>'
            f'{trows}</table></div></details>'
        )
    targets_html = "".join(target_blocks)
    fig_items = []
    for fname, rid in figs:
        rr = rec_by_id.get(rid, {})
        cap = f"{rr.get('panel', rid)}: {rr.get('title', fname)}" if rr else fname
        hpc_tag = f' {_compute_pill(rr)}' if rr and (rr.get("where") == "hpc" or rr.get("gpu") or float(rr.get("memory_gb", 8)) > 14) else ""
        fig_items.append(
            f'<figure style="margin:0"><img src="figures/{e(fname)}" alt="{e(cap)}">'
            f'<figcaption class="small mut">{e(cap)}{hpc_tag}</figcaption></figure>'
        )
    fig_html = "".join(fig_items)
    qs = "".join(f"<li>{e(q)}</li>" for q in card.get("questions") or [])
    ids_line = f'DOI <a href="{ids.doi_url(doi)}">{e(doi)}</a>' + (
        f' · PMID <a href="{ids.pubmed_url(card["pmid"])}">{e(card["pmid"])}</a>' if card.get("pmid") else "")
    data_rows = "".join(
        f"<tr><td>{e(d.get('title') or d['id'])}</td>"
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
<span class="small mut">pack v{e(card['version'])} · <a href="{up}guide.html#badges">what these badges mean</a></span></div>
{_release_html(card)}
<p>{e(card.get('summary', ''))}</p>
<h2>Use it from your own AI agent</h2>
<div class="tabs">{tabs}</div><p class="small mut" id="how">{e(next(iter(HOW.values())))}</p>
<div class="prompt"><button class="copy" onclick="cp('{pid}',this)">Copy</button><span id="{pid}">{e(copy_prompt(card, base))}</span></div>
<p class="small mut">{e(cost_text(res))} Your agent asks you once whether to run it on this computer or on your computing cluster (preferred when you have one). Data come from the paper's original repositories; nothing is sent to RunPapers. Or from a terminal: <code>{e(install)} get {e(doi)}{e(src_arg)}</code></p>
<h2>Reproducible panels</h2><div class="tscroll"><table><tr><th>Recipe</th><th>Panel</th><th>What it shows</th><th>Data</th><th>Memory</th><th>Compute</th><th>Time</th></tr>{rec_rows}{tot_row}</table></div>
{targets_html}
{('<h2>Reproduced figures</h2><div class="figs">' + fig_html + '</div>') if fig_items else ''}
{('<h2>Example questions</h2><ul>' + qs + '</ul>') if qs else ''}
<h2>Data</h2>{terms_note}<div class="tscroll"><table><tr><th>File</th><th>Size</th><th>Source</th><th>Terms / license</th></tr>{data_rows}</table></div>
<h2>Cite</h2><p class="small">Cite the paper ({ids_line}), the original data source per its terms above, and this pack: {_pack_cite_html(card, base)}</p>
<p class="small mut">Machine-readable: <a href="index.md">index.md</a> · <a href="AGENT.md">AGENT.md</a> · <a href="pack.json">pack.json</a></p>
"""
    return page(f"{card['title']} · RunPapers", body, depth=depth, desc=card.get("summary", ""), md_twin="index.md")


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
    links = [f'archived on Zenodo: <a href="https://doi.org/{e(r["doi"])}">doi:{e(r["doi"])}</a>' if r.get("doi") else "",
             f'<a href="{e(r["huggingface"])}">Hugging Face dataset</a>' if r.get("huggingface") else "",
             f'<a href="{e(r["github"])}">GitHub release</a>' if r.get("github") else ""]
    return f'<div class="small" style="margin:0 0 8px">Released v{e(r["version"])}: {" · ".join(x for x in links if x)}</div>'


def _search_blob(card):
    prof = card.get("profile") or {}
    prof_terms = [x for vals in prof.values() if isinstance(vals, list) for x in vals]
    parts = [
        card.get("title"), card.get("doi"), card.get("pmid"), card.get("pmcid"),
        card.get("first_author"), card.get("senior_author"), card.get("journal"),
        " ".join(card.get("collections") or []), card.get("summary"), *prof_terms,
    ]
    return " ".join(str(x).lower() for x in parts if x)


def _req_link(repo, doi, reqs):
    issue = next((r.get("issue") for r in reqs if r["doi"] == doi and r.get("issue")), None)
    return issue or requests_issue_url(repo, doi)


def index_md(cards, planned, base, install, repo="runpapers/runpapers", reqs=()):
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
            lines.append(f"- [{c['title']}]({base}/{ids.page_path(c['doi'])}/index.md) — "
                         f"{c.get('first_author', '')} et al., *{c.get('journal', '')}* {c.get('year', '')} · "
                         f"DOI {c['doi']}" + (f" · PMID {c['pmid']}" if c.get("pmid") else "") + f" · badges: {badges}")
    else:
        lines.append("- No packs published yet.")
    if planned:
        lines += ["", f"## Coming next ({len(planned)} planned)", "",
                  f"Request a paper or vote for one: {base}/requests.md (or `{install} request <DOI or PMID>`, which prints the link).", ""]
        for d, p in list(planned.items())[:40]:
            au = f"{p['first_author']} et al., " if p.get("first_author") else ""
            jn = f"*{p['journal']}* {p.get('year', '')} · " if p.get("journal") else ""
            pm = f" · PMID {p['pmid']}" if p.get("pmid") else ""
            lines.append(f"- {p.get('title', d)} — {au}{jn}DOI {d}{pm} · request or vote: {_req_link(repo, d, reqs)}")
    return "\n".join(lines) + "\n"


def about_html(install):
    badge_rows = "".join(f"<tr><td>{badge_html(k, 'pass')}</td><td>{e(t)}</td></tr>" for k, _, t in BADGES)
    return f"""<h1>How RunPapers works</h1>
<p>RunPapers is an open, non-profit collection of verified paper packs. A pack turns one published paper into a workspace
that your own AI agent (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, ...) can run on your computer to reproduce
published figures from the original data and then answer new scientific questions.</p>
<div class="steps">
<div class="step"><b>Bring your own agent</b>RunPapers hosts no model and sees none of your questions. Everything runs locally on your machine using open tools (<code>uv</code> and Python).</div>
<div class="step"><b>One pack, every panel</b>Each pack covers every main-figure panel the open data support. Getting a pack downloads no data up front; running a recipe downloads only the files that panel uses, and each panel states the data size, memory, GPU and time it needs.</div>
<div class="step"><b>Guardrails for biology</b>Each pack's <code>SKILL.md</code> spells out the biological replicate unit (donors or animals, never individual cells), dissection or batch confounders, renamed cell-type labels, and questions the dataset cannot support.</div>
</div>
<h2 id="badges">Verification badges</h2>
<p class="small mut">Every badge is cryptographically bound to the SHA-256 content hash of the pack. Any edit to a recipe, target, data entry or instruction marks earlier badges as <em>re-checking</em> until verification passes again. Tolerances are locked to the paper's own printed numbers before running code; internal discrepancies in a paper are documented openly rather than hidden by widening tolerances.</p>
<table><tr><th>Badge</th><th>What was verified</th></tr>{badge_rows}</table>
<h2>Original data and source terms</h2>
<p>Packs never contain or re-host raw data files, and never redistribute copyrighted figure images unless the paper's license permits it. Instead, each pack points to the original public repository (such as the Allen Brain Cell Atlas, NCBI GEO, CELLxGENE, NeMO, or Zenodo) with exact byte sizes and MD5/SHA-256 checksums.</p>
<p>Data remain under the original repository's license or terms of use — never assumed to be CC BY. For example, datasets from the <b>Allen Brain Cell Atlas</b> are governed by the <a href="https://alleninstitute.org/terms-of-use/">Allen Institute Terms of Use</a> (noncommercial research use, citing both the paper and the Atlas per the Allen Institute Citation Policy). Controlled-access human datasets (such as dbGaP, EGA, or restricted NeMO files) are never downloaded automatically; packs provide access instructions instead.</p>
<h2>Request, contribute or cite</h2>
<p>Ask for a paper or vote one up on the <a href="requests.html">Requests</a> page (requests are public GitHub issues; a vote is a thumbs-up), or from your agent with <code>{e(install)} request &lt;DOI or PMID&gt;</code>. Step-by-step help is in the <a href="guide.html">Guide</a>. You can also connect any MCP-capable agent directly to RunPapers via <code>{e(install)} mcp</code> (Skills over MCP) or assemble a multi-paper comparison workspace with <code>{e(install)} meeting "&lt;topic&gt;"</code>. To build or review a pack, see <code>CONTRIBUTING.md</code> and <code>skills/runpapers-builder</code> in the repository. When publishing work that uses a pack, cite the original paper, the data repository per its terms, and the archived RunPapers pack version.</p>"""


def about_md(install):
    lines = [
        "# How RunPapers works", "",
        "RunPapers is an open, non-profit collection of verified paper packs. A pack turns one published paper into a "
        "workspace that your own AI agent (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, ...) runs on your computer "
        "to reproduce published figures from the original data and answer new scientific questions.", "",
        "- **Bring your own agent:** RunPapers hosts no model and sees none of your questions; code runs locally via `uv`.",
        "- **One pack, every panel:** Each pack covers every reproducible main-figure panel in one place. Getting a pack downloads no data up front; each recipe downloads only the files it uses and states its data size, memory, GPU and runtime.",
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
        f"Request or vote for a paper on the Requests page (public GitHub issues; a vote is a thumbs-up) or with `{install} request <DOI or PMID>`. "
        "Cite the original paper, the data repository per its terms, and the RunPapers pack version.",
    ]
    return "\n".join(lines) + "\n"


def requests_md(reqs, install, repo="runpapers/runpapers"):
    lines = [
        "# Requested papers", "",
        f"Each request is a public GitHub issue and a vote is a thumbs-up on it. New request: {requests_issue_url(repo)} "
        f"(or `{install} request <DOI or PMID>`, which prints the link).", "",
    ]
    if not reqs:
        lines.append("No paper requests logged yet.")
    else:
        for r in reqs:
            lines.append(f"- **{r['votes']} vote(s)** · `{r['status']}` · DOI {r['doi']} — {r.get('title') or ''}"
                         + (f" · vote: {r['issue']}" if r.get("issue") else ""))
    return "\n".join(lines) + "\n"


def build(reg, out=None, base_url=None, install_cmd=None, l1_dir=None):
    cfg = reg.config.get("site", {})
    base = (base_url or cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
    install = install_cmd or cfg.get("install_cmd") or "uvx runpapers"
    repo = reg.config.get("publish", {}).get("github_repo", "runpapers/runpapers")
    from .release import published
    out = Path(out or reg.root / "build" / "site")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "style.css").write_text(CSS)
    l1_dir = Path(l1_dir or reg.root / "build" / "l1")
    cards = []
    for pk in reg.packs():
        st = status(pk)
        card = {**pk.card(), **{k: st[k] for k in ("stage", "badges")}, "data": pk.data, "release": published(pk),
                "resources": resources(pk, l1_dir)}
        cards.append(card)
        pdir = out / ids.page_path(pk.doi)
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
        (pdir / "index.html").write_text(paper_html(card, base, install, figs, panel_results))
        (pdir / "index.md").write_text(paper_md(card, base, install, panel_results))
        (pdir / "AGENT.md").write_text(agent_md(card, base, install))
        _redirect(out / "doi" / ids.doi_relpath(pk.doi), f"{base}/{ids.page_path(pk.doi)}/", card["title"])
    planned = {d: p for d, p in reg.planned().items() if d not in {c["doi"] for c in cards}}
    reqs = requests_summary(reg)
    new_req = requests_issue_url(repo)
    # index
    rows = []
    for c in sorted(cards, key=lambda c: (c.get("year") or 0, c["title"]), reverse=True):
        s = _search_blob(c)
        pmid_txt = f" · PMID {e(c['pmid'])}" if c.get("pmid") else ""
        rows.append(f'<div class="card" data-s="{e(s)}"><a class="t" href="{ids.page_path(c["doi"])}/">{e(c["title"])}</a>'
                    f'<div class="m">{e(c.get("first_author", ""))} et al. · <i>{e(c.get("journal", ""))}</i> {e(c.get("year", ""))} · DOI {e(c["doi"])}{pmid_txt}</div>'
                    f'<div class="small mut" style="margin:4px 0 8px">{e(c.get("summary", ""))}</div>'
                    f'{"".join(badge_html(b, c["badges"].get(b, "none")) for b, _, _ in BADGES)}</div>')
    planned_items = []
    for d, p in list(planned.items())[:40]:
        ps = " ".join(str(x).lower() for x in (p.get("title"), d, p.get("pmid"), p.get("first_author"), p.get("senior_author"), p.get("journal")) if x)
        au = f"{e(p['first_author'])} et al. · " if p.get("first_author") else ""
        jn = f"<i>{e(p['journal'])}</i> {e(p.get('year', ''))} · " if p.get("journal") else ""
        pm = f' · PMID <a href="{ids.pubmed_url(p["pmid"])}">{e(p["pmid"])}</a>' if p.get("pmid") else ""
        planned_items.append(f'<li data-s="{e(ps)}"><b>{e(p.get("title"))}</b><br><span class="mut">{au}{jn}DOI <a href="{ids.doi_url(d)}">{e(d)}</a>{pm}'
                             f' · <a href="{e(_req_link(repo, d, reqs))}">request or vote</a></span></li>')
    body = f"""<div class="hero"><h1>Ask a published paper's data your own questions, with your own AI agent.</h1>
<p>Each RunPapers pack turns one paper into something any AI agent can use on your computer: the original public data, recipes that reproduce its figures,
and scientific guardrails that keep new analyses honest. Every pack is verified before it carries a <a href="about.html#badges">badge</a>.</p></div>
<div class="steps"><div class="step"><b>1. Find the paper</b>Search by title, author, gene, cell type, tissue, DOI or PMID — or request one.</div>
<div class="step"><b>2. Copy one prompt</b>Paste it into Claude Code, Codex, Antigravity or any agent that can run commands.</div>
<div class="step"><b>3. Reproduce, then ask</b>Your agent reproduces a published panel first, then answers your questions locally.</div></div>
<p class="small mut">New here? The <a href="guide.html">Guide</a> walks through it step by step.</p>
<input class="search" placeholder="Search by title, author, gene, cell type, brain region, DOI or PMID" oninput="filt(this.value)">
{''.join(rows) or '<p class="mut">No packs published yet.</p>'}
<h2>Coming next</h2><p class="small mut">Planned papers ({len(planned)}). Vote to move one up, or <a href="{e(new_req)}">request another paper</a> (see the <a href="requests.html">requests</a>).</p>
<ul class="small" style="line-height:1.65">{''.join(planned_items)}</ul>"""
    (out / "index.html").write_text(page("RunPapers: verified, agent-ready papers", body,
                                         desc="Reproduce figures and ask new questions of published papers' data with your own AI agent.",
                                         md_twin="index.md"))
    (out / "index.md").write_text(index_md(cards, planned, base, install, repo, reqs))
    req_rows = ("".join(f"<tr><td>{e(r['title'] or '—')}</td><td><a href=\"{ids.doi_url(r['doi'])}\">{e(r['doi'])}</a></td>"
                        f"<td>{r['votes']}</td><td>{e(r['status'])}</td>"
                        f"<td><a href=\"{e(r.get('issue') or requests_issue_url(repo, r['doi']))}\">vote</a></td></tr>" for r in reqs)
                or '<tr><td colspan="5" class="mut">No requests yet. Be the first: press the button above.</td></tr>')
    (out / "requests.html").write_text(page("Requests · RunPapers", f"""<h1>Requested papers</h1>
<p class="mut">Which paper should be packed next? Each request is a public issue on GitHub, and a vote is a thumbs-up on it
(it takes a free GitHub account). The most-voted papers are packed first.</p>
<p><a class="copy" style="position:static;display:inline-block;text-decoration:none" href="{e(new_req)}">Request a paper</a></p>
<p class="small mut">From your agent or terminal: <code>{e(install)} request &lt;DOI or PMID&gt;</code> prints the link. Planned papers are listed on the <a href="index.html">Papers</a> page, each with a "request or vote" link.</p>
<table><tr><th>Paper</th><th>DOI</th><th>Votes</th><th>Status</th><th></th></tr>{req_rows}</table>""",
                                            desc="Requested papers and votes", md_twin="requests.md"))
    (out / "requests.md").write_text(requests_md(reqs, install, repo))
    (out / "guide.html").write_text(page("Guide · RunPapers", md_html(guide_text(install, repo)),
                                         desc="How to use RunPapers with your AI agent, step by step", md_twin="guide.md"))
    (out / "guide.md").write_text(guide_md(install, repo))
    (out / "about.html").write_text(page("How RunPapers works", about_html(install),
                                         desc="How RunPapers verifies packs and handles original data terms", md_twin="about.md"))
    (out / "about.md").write_text(about_md(install))
    index = {"generated": now(), "rp_version": __version__, "base_url": base, "install": install,
             "papers": [{k: c[k] for k in ("doi", "pmid", "pmcid", "preprint_doi", "title", "first_author", "senior_author", "journal",
                                            "year", "slug", "collections", "version", "summary", "tags", "profile", "recipes", "data_bytes", "resources",
                                            "questions", "stage", "badges")}
                        | {"data_terms": _data_terms(c), "release": c.get("release"), "url": f"{base}/{ids.page_path(c['doi'])}/",
                           "agent": f"{base}/{ids.page_path(c['doi'])}/AGENT.md"}
                        for c in cards],
             "planned": [{"doi": d, **{k: p.get(k) for k in ("title", "pmid", "first_author", "journal", "year", "collection", "tags")}}
                         for d, p in planned.items()],
             "requests": reqs}
    (out / "index.json").write_text(json.dumps(index, indent=1))
    (out / "requests.json").write_text(json.dumps(reqs, indent=1))
    (out / "llms.txt").write_text("\n".join([
        "# RunPapers", "",
        "> Verified, agent-ready packs for published papers: original data, figure-reproducing recipes, paper target numbers and agent guardrails.",
        "", f"To use a paper: fetch `{base}/papers/<DOI as a name>/AGENT.md` (exact `agent` URL in `{base}/index.json`) and follow it.",
        f"CLI: `{install}` · Local MCP server (stdio, zero extra deps): `{install} mcp` · Multi-paper workspace: `{install} meeting \"<topic>\"`.",
        f"Machine-readable catalog: {base}/index.json · Guide for people: {base}/guide.md · How verification & data terms work: {base}/about.md · Requests: {base}/requests.md",
        "", "## Papers", ""] +
        [f"- [{c['title']}]({base}/{ids.page_path(c['doi'])}/index.md): DOI {c['doi']}" + (f", PMID {c['pmid']}" if c.get("pmid") else "")
         + f"; badges: {', '.join(k for k, v in c['badges'].items() if v == 'pass') or 'none'}" for c in cards]) + "\n")
    (out / "AGENT.md").write_text(
        f"# RunPapers for AI agents\n\n"
        f"1. Search `{base}/index.json` (or run `{install} search \"<query>\" --json` / connect `{install} mcp`) by DOI, PMID, PMCID, title, author, species, tissue, assay, cell type or gene.\n"
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
