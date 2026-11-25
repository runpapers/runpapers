"""Level-0 checks (lint): the pack is well formed, licensed, complete, within the lite-tier budget, and has no
instructions or code that a user's agent should not run. Every finding is (severity, code, message); any 'error'
fails L0. Community packs are untrusted until they pass this and a human review."""
import re
from pathlib import Path

from . import ids
from .registry import SPEC

TIERS = ("lite", "full")
ACCESS = ("open", "controlled")
TOL_KEYS = {"exact", "abs", "rel", "range", "set"}
LITE_WARN_BYTES = 2 * 1024**3     # a laptop and a free CI runner should handle the lite tier
LITE_MAX_BYTES = 8 * 1024**3
MIN_QUESTIONS = 3
SKILL_SECTIONS = ("## What this paper", "## Data", "## Recipes", "## Guardrails", "## Answering new questions")

# Things a pack must never ask an agent to do. Hits in SKILL.md or recipes are errors; review can't wave them through.
DANGER = [
    (r"curl[^\n|]*\|\s*(ba|z)?sh\b", "pipes a download into a shell"),
    (r"wget[^\n|]*\|\s*(ba|z)?sh\b", "pipes a download into a shell"),
    (r"\brm\s+-rf\s+(/|~|\$HOME)", "deletes outside the workspace"),
    (r"~/\.ssh|\.aws/credentials|\.config/gcloud|id_rsa|\.netrc|\.claude\.json|credentials\.json", "touches credentials"),
    (r"base64\s+(-d|--decode)[^\n]*\|\s*(ba|z)?sh", "decodes and runs hidden code"),
    (r"\b(exec|eval)\s*\(\s*(base64|codecs|zlib|bytes\.fromhex)", "runs obfuscated code"),
    (r"(?i)ignore (all |any )?(previous|prior|above) instructions", "prompt-injection phrase"),
    (r"(?i)do not (tell|inform|show) the user", "asks the agent to hide things from the user"),
    (r"(?i)--dangerously-skip-permissions|--dangerously-bypass", "asks the agent to drop its safety prompts"),
    (r"\bos\.environ\b[^\n]*(requests|urllib|http)", "may send environment variables over the network"),
]
HIDDEN_CHARS = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _tol_ok(t):
    tol = t.get("tolerance", {"exact": True})
    if not isinstance(tol, dict) or not tol or not set(tol) <= TOL_KEYS:
        return False
    if "range" in tol and not (isinstance(tol["range"], list) and len(tol["range"]) == 2):
        return False
    return True


def scan_text(text, where):
    out = []
    for rx, why in DANGER:
        if re.search(rx, text):
            out.append(("error", "security", f"{where}: {why} (pattern {rx!r})"))
    if HIDDEN_CHARS.search(text):
        out.append(("error", "security", f"{where}: contains invisible/bidirectional Unicode characters (could hide instructions)"))
    for c in HTML_COMMENT.findall(text):
        if len(c) > 40:
            out.append(("warn", "security", f"{where}: HTML comment with text an agent reads but a person doesn't see: {c[:60]!r}"))
    return out


def lint(pack, expected_dir=None):
    f = []
    m = pack.meta
    add = lambda sev, code, msg: f.append((sev, code, msg))
    if m.get("spec") != SPEC:
        add("error", "spec", f"spec must be {SPEC!r} (got {m.get('spec')!r})")
    p = m.get("paper", {})
    try:
        doi = ids.normalize_doi(p.get("doi", ""))
        if p.get("doi") != doi:
            add("error", "paper.doi", f"write the DOI in canonical lowercase form: {doi}")
        if expected_dir is not None and Path(expected_dir).resolve() != pack.dir.resolve():
            add("error", "paper.doi", f"pack folder does not match its DOI (expected {expected_dir})")
    except ids.IdError as e:
        add("error", "paper.doi", str(e))
    for k in ("title", "first_author", "journal", "year"):
        if not p.get(k):
            add("error", f"paper.{k}", f"paper.{k} is required")
    if p.get("pmid") and not re.fullmatch(r"\d{1,9}", str(p["pmid"])):
        add("error", "paper.pmid", "pmid must be digits")
    if not p.get("license"):
        add("warn", "paper.license", "paper.license unknown: published figure images can't be shown or redistributed until it is verified")
    pk = m.get("pack", {})
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(pk.get("version", ""))):
        add("error", "pack.version", "pack.version must be MAJOR.MINOR.PATCH")
    for k in ("summary", "license", "maintainers"):
        if not pk.get(k):
            add("error", f"pack.{k}", f"pack.{k} is required")

    # data
    seen = set()
    for d in pack.data:
        did = d.get("id", "?")
        if did in seen:
            add("error", "data.id", f"duplicate data id {did}")
        seen.add(did)
        if not str(d.get("url", "")).startswith("https://"):
            add("error", "data.url", f"{did}: url must be https")
        if d.get("access", "open") not in ACCESS:
            add("error", "data.access", f"{did}: access must be one of {ACCESS}")
        if d.get("access") == "controlled":
            if d.get("tier", "lite") == "lite":
                add("error", "data.access", f"{did}: controlled-access data can't be in the lite tier")
            continue
        if not isinstance(d.get("size"), int) or d["size"] <= 0:
            add("error", "data.size", f"{did}: size (bytes, integer) is required")
        if not (d.get("md5") or d.get("sha256")):
            add("error", "data.checksum", f"{did}: md5 or sha256 is required")
        if d.get("tier", "lite") not in TIERS:
            add("error", "data.tier", f"{did}: tier must be lite or full")
        if not d.get("source"):
            add("error", "data.source", f"{did}: say where the file comes from (repository, release)")
        if not d.get("license"):
            add("warn", "data.license", f"{did}: data license not recorded")
    if not pack.data:
        add("error", "data", "no [[data]] entries")
    lb = pack.lite_bytes()
    if lb > LITE_MAX_BYTES:
        add("error", "data.lite", f"lite tier is {lb / 1e9:.1f} GB; keep it under {LITE_MAX_BYTES / 1e9:.0f} GB (move files to tier 'full')")
    elif lb > LITE_WARN_BYTES:
        add("warn", "data.lite", f"lite tier is {lb / 1e9:.1f} GB; aim for under 2 GB so it runs on a laptop")

    # recipes
    rids = set()
    for r in pack.recipes:
        rid = r.get("id", "?")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", rid):
            add("error", "recipe.id", f"recipe id {rid!r}: lowercase letters, digits, - and _")
        if rid in rids:
            add("error", "recipe.id", f"duplicate recipe {rid}")
        rids.add(rid)
        sp = pack.dir / r.get("script", "")
        if not r.get("script") or not sp.is_file():
            add("error", "recipe.script", f"{rid}: script {r.get('script')!r} not found")
        for did in r.get("data", []):
            if did not in seen:
                add("error", "recipe.data", f"{rid}: unknown data id {did}")
            elif r.get("tier", "lite") == "lite":
                d = pack.data_entry(did)
                if d.get("tier", "lite") != "lite":
                    add("error", "recipe.tier", f"{rid}: lite recipe uses full-tier data {did}")
        if not r.get("panel"):
            add("warn", "recipe.panel", f"{rid}: say which published panel it reproduces (e.g. 'Figure 2F')")
        if not pack.targets_for(rid):
            add("error", "recipe.targets", f"{rid}: no targets (numbers from the paper the output must match)")
    if not pack.recipes:
        add("error", "recipes", "no [[recipes]]")
    # every file an agent might run or read (recipes and their helpers, references) gets the security scan
    for rel in pack.files():
        if rel.endswith((".py", ".R", ".r", ".sh", ".md", ".ipynb", ".jl")) and rel != "SKILL.md":
            f.extend(scan_text((pack.dir / rel).read_text(errors="replace"), rel))

    # targets
    for t in pack.targets:
        tag = f"{t.get('recipe')}:{t.get('metric')}"
        if t.get("recipe") not in rids:
            add("error", "target.recipe", f"{tag}: unknown recipe")
        if "expected" not in t:
            add("error", "target.expected", f"{tag}: expected value missing")
        if not t.get("source"):
            add("error", "target.source", f"{tag}: cite where the expected value is in the paper (page, figure, table)")
        if not _tol_ok(t):
            add("error", "target.tolerance", f"{tag}: tolerance must be one of exact/abs/rel/range/set")

    # questions
    if len(pack.evals) < MIN_QUESTIONS:
        add("error", "evals", f"need at least {MIN_QUESTIONS} test questions in evals/questions.toml (have {len(pack.evals)})")
    qids = set()
    for q in pack.evals:
        if q.get("id") in qids:
            add("error", "evals.id", f"duplicate question {q.get('id')}")
        qids.add(q.get("id"))
        if not q.get("ask") or "answer" not in q or not q.get("source"):
            add("error", "evals.fields", f"question {q.get('id')}: needs ask, answer and source")

    # instructions
    sk = pack.dir / "SKILL.md"
    if not sk.is_file():
        add("error", "skill", "SKILL.md missing")
    else:
        text = sk.read_text(errors="replace")
        fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not fm or "name:" not in fm.group(1) or "description:" not in fm.group(1):
            add("error", "skill.frontmatter", "SKILL.md needs Agent Skills frontmatter (name, description)")
        for s in SKILL_SECTIONS:
            if s not in text:
                add("error", "skill.section", f"SKILL.md lacks section starting {s!r}")
        if re.search(r"\bTODO\b", text):
            add("error", "skill.todo", "SKILL.md still has TODO placeholders")
        f.extend(scan_text(text, "SKILL.md"))
        if len(text) > 30000:
            add("warn", "skill.size", "SKILL.md is long; move detail into references/ so agents load it on demand")
    return f


def errors(findings):
    return [x for x in findings if x[0] == "error"]
