"""`rp get`: turn a published pack into a working folder for the user's own agent (Claude Code, Codex,
Antigravity, Gemini CLI, Cursor...). The folder carries the instructions in every form agents look for
(AGENTS.md, CLAUDE.md, GEMINI.md, .claude/skills, .agents/skills), the recipes, and a link to the cached data."""
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

from . import DEFAULT_BASE as _SITE, data, ids
from .registry import PACK_FILE, Pack, Registry, find_root, read_json, write_json

WS_FILE = ".runpapers.json"
DEFAULT_BASE = os.environ.get("RUNPAPERS_BASE", _SITE)
# The test questions are the held-out exam for naive-user tests: never copied into a user's workspace.
NOT_SHIPPED = ("evals/",)


def shipped(rel):
    return not rel.startswith(NOT_SHIPPED)


def find_workspace(start=None):
    p = Path(start or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / WS_FILE).is_file():
            return d
    return None


def load_workspace(start=None):
    ws = find_workspace(start)
    if not ws:
        return None, None, None
    meta = read_json(ws / WS_FILE)
    return ws, Pack(ws), meta


def _fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": data.UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _copy_from_registry(pack, dest):
    for rel in pack.files():
        if shipped(rel):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pack.dir / rel, dest / rel)


def _copy_from_site(base, doi, dest):
    root = f"{base.rstrip('/')}/doi/{ids.doi_relpath(doi)}"
    listing = json.loads(_fetch_bytes(f"{root}/pack.json"))
    for f in listing["files"]:
        rel = f["path"]
        if ".." in Path(rel).parts or rel.startswith("/"):
            raise SystemExit(f"refusing unsafe path in pack listing: {rel}")
        b = _fetch_bytes(f"{root}/pack/{rel}")
        if hashlib.sha256(b).hexdigest() != f["sha256"]:
            raise SystemExit(f"{rel}: checksum mismatch; the download was corrupted or tampered with")
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(b)
    return listing


AGENTS_MD = """# RunPapers workspace: {title}

This folder lets you (an AI agent) reproduce figures from, and answer new questions with the data of:
**{title}**, {first_author} et al., *{journal}* {year}. DOI {doi}{pmid_line}.

1. Read `SKILL.md` in full before you do anything else, and follow its guardrails.
2. Reproduce a published panel: `{rp} run <recipe>` (list them: `{rp} recipes`). Each run writes `out/<recipe>/`
   with the figure, `metrics.json`, and `result.json` (the paper's numbers next to ours). Show the user the figure
   and say plainly which numbers matched and which did not.
3. New questions: write scripts in `analyses/`, reading files from `data/` (see `SKILL.md` -> Data). Say what you
   computed and how sure you are; keep observation and interpretation apart.
4. Cite the paper (DOI {doi}) and the pack (RunPapers {doi} v{version}).

Data files live in the shared cache: {data_dir}
"""


def get(ident, dest=None, tier="lite", source=None, fetch_data=True, rp_cmd="rp", quiet=False):
    """Create the workspace. source: a registry folder, a site base URL, or None (local registry if any, else the site)."""
    src = source or (str(find_root()) if find_root() else DEFAULT_BASE)
    tmp_dest = None
    if src.startswith(("http://", "https://")):
        kind, val = ids.parse_id(ident)
        if kind != "doi":
            idx = json.loads(_fetch_bytes(f"{src.rstrip('/')}/index.json"))
            hit = [p for p in idx["papers"] if str(p.get(kind)).upper() == val.upper()]
            if not hit:
                raise SystemExit(f"{ident}: not found at {src}")
            val = hit[0]["doi"]
        doi = val
        tmp_dest = Path(dest) if dest else None
        stage = Path(dest or ".").resolve() / ".rp-incoming"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        _copy_from_site(src, doi, stage)
        pack = Pack(stage)
        target = Path(dest).resolve() if dest else Path.cwd() / pack.slug
        if target.exists() and any(p.name != ".rp-incoming" for p in target.iterdir()) and target != stage:
            if not (target / WS_FILE).is_file():
                shutil.rmtree(stage)
                raise SystemExit(f"{target} exists and is not a RunPapers workspace")
        target.mkdir(parents=True, exist_ok=True)
        for item in stage.iterdir():
            dst = target / item.name
            if dst.is_dir():
                shutil.rmtree(dst)
            shutil.move(str(item), dst)
        shutil.rmtree(stage)
    else:
        reg = Registry(src)
        pk = reg.pack(ident)
        target = Path(dest).resolve() if dest else Path.cwd() / pk.slug
        target.mkdir(parents=True, exist_ok=True)
        _copy_from_registry(pk, target)
    pack = Pack(target)
    dd = data.data_dir(pack.doi)
    notes = []
    if fetch_data:
        _, notes = data.fetch(pack, tier, quiet=quiet)
    link = target / "data"
    if link.is_symlink() or link.exists():
        if link.is_symlink() or link.is_file():
            link.unlink()
    try:
        if not link.exists():
            link.symlink_to(dd, target_is_directory=True)
    except OSError:  # e.g. Windows without symlink rights: the path is in .runpapers.json and AGENTS.md
        pass
    p = pack.paper
    text = AGENTS_MD.format(title=pack.title, first_author=p.get("first_author", ""), journal=p.get("journal", ""),
                            year=p.get("year", ""), doi=pack.doi, version=pack.version, rp=rp_cmd, data_dir=dd,
                            pmid_line=f", PMID {p['pmid']}" if p.get("pmid") else "")
    (target / "AGENTS.md").write_text(text)
    (target / "CLAUDE.md").write_text("@AGENTS.md\n@SKILL.md\n")
    (target / "GEMINI.md").write_text(text)
    skill = (target / "SKILL.md").read_text()
    for d in (".claude/skills", ".agents/skills", ".gemini/skills"):
        sd = target / d / f"runpapers-{pack.slug}"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "SKILL.md").write_text(skill)
    (target / "analyses").mkdir(exist_ok=True)
    write_json(target / WS_FILE, {"doi": pack.doi, "version": pack.version, "pack_hash": pack.content_hash(),
                                  "source": src, "tier": tier, "data_dir": str(dd)})
    if not quiet:
        print(f"workspace ready: {target}", file=sys.stderr)
        for n in notes:
            print(f"note: {n}", file=sys.stderr)
    return target, notes
