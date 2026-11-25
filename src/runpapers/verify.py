"""Verification levels, records and the pipeline stage of each paper.

Badges (each record in papers/<doi>/verify/ is bound to the pack's content hash; a change makes it 'stale'):
  runs         L1: lint passes, lite data verified, every lite recipe meets its targets under CI limits (automatic)
  checked      an independent critic compared every reproduced panel with the published one (agent review)
  reproduces   L2: a named human signed off the paper after the critic's check (the PI, once per paper)
  agent-tested L3: fresh agents from >= 2 families, given only the copy-prompt, reproduced and answered the test questions
  endorsed     an author of the paper approved the pack (ORCID-matched)
"""
import datetime as dt
import platform
import shutil
import tempfile
from pathlib import Path

from . import __version__, data, recipes, spec
from .registry import read_json, write_json

STAGES = ["planned", "building", "ready", "runs", "checked", "reproduces", "agent-tested", "released"]
MIN_FAMILIES = 2


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def vdir(pack):
    return pack.dir / "verify"


def record(pack, name):
    return read_json(vdir(pack) / f"{name}.json")


def _current(rec, h):
    return bool(rec) and rec.get("pack_hash") == h


def run_l1(pack, ci=True, quiet=False, keep_out=None):
    """L1 on the registry copy of a pack. Writes verify/l1.json. Returns the record."""
    h = pack.content_hash()
    findings = spec.lint(pack)
    rec = {"level": "L1", "pack_hash": h, "version": pack.version, "at": now(), "rp_version": __version__,
           "platform": f"{platform.system()} {platform.machine()} py{platform.python_version()}",
           "lint": [list(x) for x in findings], "recipes": {}, "pass": False, "notes": []}
    if spec.errors(findings):
        rec["notes"].append("lint errors: recipes not run")
        write_json(vdir(pack) / "l1.json", rec)
        return rec
    paths, notes = data.fetch(pack, "lite", quiet=quiet)
    rec["notes"] += notes
    out_root = Path(keep_out) if keep_out else Path(tempfile.mkdtemp(prefix="rp-l1-"))
    lite = [r for r in pack.recipes if r.get("tier", "lite") == "lite"]
    for r in lite:
        res = recipes.run(pack, r["id"], data.data_dir(pack.doi), out_root, ci=ci, quiet=quiet)
        rec["recipes"][r["id"]] = {k: res[k] for k in ("panel", "status", "seconds", "peak_rss_mb", "pass", "checks", "figures")}
    rec["pass"] = bool(lite) and all(v["pass"] for v in rec["recipes"].values())
    if not lite:
        rec["notes"].append("no lite recipes: L1 needs at least one panel that runs on a laptop")
    write_json(vdir(pack) / "l1.json", rec)
    return rec


def record_review(pack, verdict, by, note="", figs=None):
    """The critic's independent check of every reproduced panel against the published one."""
    if verdict not in ("pass", "revise"):
        raise SystemExit("verdict must be pass or revise")
    l1 = record(pack, "l1")
    h = pack.content_hash()
    if verdict == "pass" and not (_current(l1, h) and l1.get("pass")):
        raise SystemExit("a review can pass only a pack whose current L1 passes (run `rp verify` first)")
    rec = {"pack_hash": h, "version": pack.version, "at": now(), "by": by, "verdict": verdict, "note": note,
           "figures": figs or {}}
    write_json(vdir(pack) / "review.json", rec)
    return rec


def record_signoff(pack, decision, by, note="", rejected=None):
    """The human sign-off that grants 'reproduces' (L2). Needs a current passing critic review."""
    if decision not in ("approve", "reject"):
        raise SystemExit("decision must be approve or reject")
    h = pack.content_hash()
    rv = record(pack, "review")
    if decision == "approve" and not (_current(rv, h) and rv.get("verdict") == "pass"):
        raise SystemExit("sign-off needs the critic's passing review of this exact pack version first")
    rec = {"pack_hash": h, "version": pack.version, "at": now(), "by": by, "decision": decision, "note": note,
           "rejected_figures": rejected or {}}
    write_json(vdir(pack) / "signoff.json", rec)
    return rec


def record_endorsement(pack, by, orcid, note=""):
    rec = {"pack_hash": pack.content_hash(), "version": pack.version, "at": now(), "by": by, "orcid": orcid, "note": note}
    write_json(vdir(pack) / "endorsement.json", rec)
    return rec


def family(agent):
    return {"claude": "anthropic", "agy": "google", "gemini": "google", "codex": "openai"}.get(agent, agent)


def status(pack):
    """Badges, stage, components and the next step for one pack."""
    h = pack.content_hash()
    findings = spec.lint(pack)
    errs = spec.errors(findings)
    comp = {
        "data": bool(pack.data), "recipes": bool(pack.recipes), "targets": bool(pack.targets),
        "skill": (pack.dir / "SKILL.md").is_file(), "questions": len(pack.evals) >= spec.MIN_QUESTIONS,
    }
    l1, rv, so = record(pack, "l1"), record(pack, "review"), record(pack, "signoff")
    ut, en, rel = record(pack, "usertest") or {}, record(pack, "endorsement"), record(pack, "release")

    def badge(rec, ok):
        if not rec:
            return "none"
        if not _current(rec, h):
            return "stale"
        return "pass" if ok(rec) else "fail"

    runs = [r for r in (ut.get("runs") or []) if r.get("pack_hash") == h]
    fams = sorted({family(r["agent"]) for r in runs if r.get("pass")})
    badges = {
        "runs": badge(l1, lambda r: r.get("pass")),
        "checked": badge(rv, lambda r: r.get("verdict") == "pass"),
        "reproduces": badge(so, lambda r: r.get("decision") == "approve"),
        "agent-tested": ("pass" if len(fams) >= MIN_FAMILIES else ("partial" if fams else
                         ("fail" if runs else ("stale" if ut.get("runs") else "none")))),
        "endorsed": badge(en, lambda r: True),
    }
    if errs or not all(comp.values()):
        stage = "building"
    elif badges["runs"] != "pass":
        stage = "ready"
    elif badges["checked"] != "pass":
        stage = "runs"
    elif badges["reproduces"] != "pass":
        stage = "checked"
    elif badges["agent-tested"] != "pass":
        stage = "reproduces"
    elif not any(x.get("pack_hash") == h and set(x.get("published") or {}) & {"github", "zenodo", "huggingface"}
                 for x in (rel or {}).get("releases", [])):
        stage = "agent-tested"
    else:
        stage = "released"
    nxt = {
        "building": "finish the pack: " + (", ".join(k for k, v in comp.items() if not v) or f"fix {len(errs)} lint error(s)"),
        "ready": "run L1 (`rp verify " + pack.doi + "`)" + (" - last L1 failed" if badges["runs"] == "fail" else "")
                 + (" - last L1 is stale" if badges["runs"] == "stale" else ""),
        "runs": "critic review of every reproduced panel" + (" (revise requested)" if rv and _current(rv, h) and rv.get("verdict") == "revise" else ""),
        "checked": "PI sign-off (once per paper)" + (" - last sign-off rejected" if badges["reproduces"] == "fail" else ""),
        "reproduces": f"naive-user tests: {len(fams)}/{MIN_FAMILIES} agent families passed",
        "agent-tested": "release (version, changelog, archive DOI)",
        "released": "maintain: re-verify when sources change",
    }[stage]
    return {"doi": pack.doi, "title": pack.title, "citekey": pack.citekey, "version": pack.version, "pack_hash": h[:12],
            "stage": stage, "next": nxt, "badges": badges, "components": comp,
            "lint": {"errors": len(errs), "warnings": len(findings) - len(errs)},
            "l1": {"at": l1.get("at"), "pass": l1.get("pass"),
                   "recipes": {k: {"pass": v.get("pass"), "seconds": v.get("seconds"), "peak_rss_mb": v.get("peak_rss_mb"),
                                   "panel": v.get("panel")} for k, v in (l1.get("recipes") or {}).items()}} if l1 else None,
            "review": {k: rv.get(k) for k in ("at", "by", "verdict", "note")} if rv else None,
            "signoff": {k: so.get(k) for k in ("at", "by", "decision", "note")} if so else None,
            "usertest": {"families": fams, "runs": [{k: r.get(k) for k in ("agent", "model", "at", "pass", "score", "seconds")}
                                                    for r in runs]},
            "endorsed": {k: en.get(k) for k in ("by", "orcid", "at")} if en else None,
            "releases": [{k: x.get(k) for k in ("version", "built", "published")} | {"current": x.get("pack_hash") == h}
                         for x in (rel or {}).get("releases", [])]}


def tool_available(name):
    return shutil.which(name) is not None
