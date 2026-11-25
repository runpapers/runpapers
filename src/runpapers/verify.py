"""Verification levels, records and the pipeline stage of each paper.

Badges (each record in papers/<doi>/verify/ is bound to the pack's content hash; a change makes it 'stale'):
  runs         L1: lint passes and every recipe meets its targets on this content (CI for recipes within CI limits;
               HPC runs recorded with `rp verify --record` for heavier or GPU recipes)
  checked      an independent critic compared every reproduced panel with the published one (agent review)
  reproduces   L2: a named human signed off the paper after the critic's check (the PI, once per paper)
  agent-tested L3: fresh agents from >= 2 families, given only the copy-prompt, reproduced and answered the test questions
  endorsed     an author of the paper approved the pack (ORCID-matched)
"""
import datetime as dt
import json
import platform
import shutil
import tempfile
from pathlib import Path

from . import __version__, data, recipes, spec
from .registry import read_json, write_json

STAGES = ["planned", "building", "ready", "runs", "checked", "reproduces", "agent-tested", "released"]
MIN_FAMILIES = 2
PUBLIC_TARGETS = {"github", "zenodo", "huggingface"}
CI_LIMITS = recipes.CI_LIMITS


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def vdir(pack):
    return pack.dir / "verify"


def record(pack, name):
    return read_json(vdir(pack) / f"{name}.json")


def _current(rec, h):
    return bool(rec) and rec.get("pack_hash") == h


def fits_ci(pack, r):
    """True when recipe `r` fits the free CI machine (4 CPUs, <= 14 GB RAM, no GPU, < 60 min)."""
    n = pack.recipe_needs(r) if not ("memory_gb" in r and "gpu" in r and "minutes" in r) else r
    return (not bool(n.get("gpu", False))
            and float(n.get("memory_gb", 8)) <= CI_LIMITS["memory_gb"]
            and float(n.get("minutes", 20)) < CI_LIMITS["max_minutes"])


def _measured_mem_gb(rss_mb):
    val = round(rss_mb / 1024, 1) if rss_mb >= 102 else max(0.01, round(rss_mb / 1024, 2))
    return int(val) if isinstance(val, float) and val.is_integer() else val


def _measured_minutes(secs):
    val = round(secs / 60, 1) if secs >= 6 else max(0.01, round(secs / 60, 2))
    return int(val) if isinstance(val, float) and val.is_integer() else val


def needs(pack, out_dirs=()):
    """Per-recipe and total resource needs for `pack`; measured values from completed runs replace estimates."""
    h = pack.content_hash()
    l1 = record(pack, "l1") or {}
    l1_recs = (l1.get("recipes") or {}) if l1.get("pack_hash") == h else {}
    rows = []
    for r in pack.recipes:
        rid = r["id"]
        decl = pack.recipe_needs(r)
        run_rec = None
        for d in out_dirs or ():
            cand = read_json(Path(d) / rid / "result.json")
            if cand and cand.get("pack_hash") in (None, h) and (cand.get("pass") or cand.get("status") == "ok"):
                run_rec = cand
                break
        if run_rec is None:
            lr = l1_recs.get(rid)
            if isinstance(lr, dict) and lr.get("pack_hash", h) == h and (lr.get("pass") or lr.get("status") == "ok"):
                run_rec = lr
        rss_mb = run_rec.get("peak_rss_mb") if run_rec else None
        secs = run_rec.get("seconds") if run_rec else None
        mem_gb = _measured_mem_gb(rss_mb) if rss_mb is not None else decl["memory_gb"]
        mins = _measured_minutes(secs) if secs is not None else decl["minutes"]
        rows.append({
            "id": rid,
            "panel": r.get("panel", ""),
            "title": r.get("title", ""),
            "data": decl["data"],
            "data_bytes": decl["data_bytes"],
            "memory_gb": mem_gb,
            "gpu": decl["gpu"],
            "minutes": mins,
            "measured": rss_mb is not None or secs is not None,
            "peak_rss_mb": rss_mb,
            "seconds": secs,
        })
    tot_min = round(sum(x["minutes"] for x in rows), 2)
    if isinstance(tot_min, float) and tot_min.is_integer():
        tot_min = int(tot_min)
    return {
        "doi": pack.doi,
        "version": pack.version,
        "recipes": rows,
        "totals": {
            "data": sorted({did for x in rows for did in x["data"]}),
            "data_bytes": pack.data_bytes(),
            "memory_gb": max((x["memory_gb"] for x in rows), default=0),
            "gpu": any(x["gpu"] for x in rows),
            "minutes": tot_min,
        },
    }


def _all_recipes_pass(pack, rec_map, h):
    return bool(pack.recipes) and all(
        isinstance(rec_map.get(r["id"]), dict)
        and rec_map[r["id"]].get("pass")
        and rec_map[r["id"]].get("pack_hash", h) == h
        for r in pack.recipes
    )


def run_l1(pack, ci=True, quiet=False, keep_out=None):
    """L1 on the registry copy of a pack. Runs recipes that fit CI limits and preserves current-hash HPC records."""
    h = pack.content_hash()
    findings = spec.lint(pack)
    prev = record(pack, "l1") or {}
    prev_recs = (prev.get("recipes") or {}) if prev.get("pack_hash") == h else {}
    rec = {"level": "L1", "pack_hash": h, "version": pack.version, "at": now(), "rp_version": __version__,
           "platform": f"{platform.system()} {platform.machine()} py{platform.python_version()}",
           "lint": [list(x) for x in findings], "recipes": {}, "pass": False, "notes": []}
    if spec.errors(findings):
        rec["notes"].append("lint errors: recipes not run")
        write_json(vdir(pack) / "l1.json", rec)
        return rec
    out_root = Path(keep_out) if keep_out else Path(tempfile.mkdtemp(prefix="rp-l1-"))
    if not pack.recipes:
        rec["notes"].append("no recipes in pack")
        write_json(vdir(pack) / "l1.json", rec)
        return rec
    where = "ci" if ci else "local"
    for r in pack.recipes:
        rid = r["id"]
        if fits_ci(pack, r):
            only = set(r["data"]) if "data" in r else None
            _, notes = data.fetch(pack, only=only, quiet=quiet)
            for n in notes:
                if n not in rec["notes"]:
                    rec["notes"].append(n)
            res = recipes.run(pack, rid, data.data_dir(pack.doi), out_root, ci=ci, quiet=quiet)
            rec["recipes"][rid] = {
                **{k: res[k] for k in ("panel", "status", "seconds", "peak_rss_mb", "pass", "checks", "figures")},
                "where": where, "pack_hash": h, "at": now(),
            }
        else:
            old = prev_recs.get(rid)
            if isinstance(old, dict) and old.get("pack_hash", h) == h:
                rec["recipes"][rid] = old
            else:
                nd = pack.recipe_needs(r)
                rec["notes"].append(
                    f"{rid}: exceeds CI limits ({nd['memory_gb']:g} GB RAM, {'GPU' if nd['gpu'] else 'CPU'}, "
                    f"{nd['minutes']:g} min); run on HPC and record with `rp verify {pack.doi} --record <out_dir>`"
                )
    rec["pass"] = _all_recipes_pass(pack, rec["recipes"], h)
    write_json(vdir(pack) / "l1.json", rec)
    return rec


def _discover_run_dirs(pack, source_path):
    p = Path(source_path)
    if p.is_file() and p.name in ("result.json", "metrics.json"):
        p = p.parent
    if not p.is_dir():
        raise SystemExit(f"record path not found: {source_path}")
    known = {r["id"] for r in pack.recipes}
    if (p / "result.json").is_file() or (p / "metrics.json").is_file():
        res = read_json(p / "result.json") or {}
        rid = res.get("recipe") or p.name
        if rid not in known:
            raise SystemExit(f"unknown recipe {rid!r} in {p} (have: {', '.join(sorted(known))})")
        return [(rid, p)]
    found = []
    for r in pack.recipes:
        sub = p / r["id"]
        if (sub / "result.json").is_file() or (sub / "metrics.json").is_file():
            found.append((r["id"], sub))
    if not found:
        raise SystemExit(f"no recipe outputs (result.json or metrics.json) found in {source_path}")
    return found


def record_run(pack, source_path, where="hpc", keep_out=None):
    """Record external/HPC recipe outputs into verify/l1.json (bound to current pack_hash) and build/l1/<doi>/."""
    h = pack.content_hash()
    findings = spec.lint(pack)
    if spec.errors(findings):
        raise SystemExit("cannot record runs while pack has lint errors; run `rp lint` first")
    pairs = _discover_run_dirs(pack, source_path)
    prev = record(pack, "l1")
    if prev and prev.get("pack_hash") == h:
        rec = prev
        rec["lint"] = [list(x) for x in findings]
        rec["at"] = now()
        rec["rp_version"] = __version__
    else:
        rec = {"level": "L1", "pack_hash": h, "version": pack.version, "at": now(), "rp_version": __version__,
               "platform": f"{platform.system()} {platform.machine()} py{platform.python_version()}",
               "lint": [list(x) for x in findings], "recipes": {}, "pass": False, "notes": []}
    for rid, rdir in pairs:
        r = pack.recipe(rid)
        res = read_json(rdir / "result.json") or {}
        if res.get("pack_hash") and res["pack_hash"] != h:
            raise SystemExit(
                f"{rid}: output was produced on pack_hash {res['pack_hash'][:12]}, "
                f"current pack is {h[:12]}; re-run on current pack"
            )
        metrics = read_json(rdir / "metrics.json")
        obs_fallback = {c.get("metric"): c.get("observed") for c in (res.get("checks") or []) if "metric" in c}
        checks = []
        for t in pack.targets_for(rid):
            tol = t.get("tolerance") or {"exact": True}
            obs = metrics.get(t["metric"]) if isinstance(metrics, dict) else obs_fallback.get(t["metric"])
            ok, detail = recipes.compare(t.get("expected"), obs, tol)
            checks.append({"metric": t["metric"], "expected": t.get("expected"), "observed": obs,
                           "tolerance": tol, "ok": ok, "detail": detail, "source": t.get("source", ""),
                           "kind": t.get("kind", "figure"), "required": t.get("required", True), "note": t.get("note", "")})
        status_val = res.get("status", "ok" if (metrics is not None or obs_fallback) else "no-metrics")
        passed = (status_val == "ok" and any(c["required"] for c in checks)
                  and all(c["ok"] for c in checks if c["required"]))
        figures = sorted(f.name for f in rdir.iterdir() if f.is_file() and f.suffix.lower() in (".png", ".svg", ".pdf", ".jpg"))
        secs = res.get("seconds")
        peak_mb = res.get("peak_rss_mb")
        if keep_out is not None:
            dst = Path(keep_out) / rid
            if dst.resolve() != rdir.resolve():
                if dst.exists():
                    shutil.rmtree(dst)
                dst.mkdir(parents=True, exist_ok=True)
                for f in sorted(rdir.iterdir()):
                    if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in (".png", ".svg", ".pdf", ".jpg", ".csv", ".json"):
                        shutil.copy2(f, dst / f.name)
            norm_res = {"recipe": rid, "panel": r.get("panel", ""), "pack_hash": h, "status": status_val,
                        "returncode": res.get("returncode", 0 if status_val == "ok" else 1), "seconds": secs,
                        "peak_rss_mb": peak_mb, "ci": False, "where": where, "checks": checks,
                        "pass": passed, "figures": figures, "log": "run.log"}
            (dst / "result.json").write_text(json.dumps(norm_res, indent=1) + "\n")
        rec["recipes"][rid] = {"panel": r.get("panel", ""), "status": status_val, "seconds": secs,
                               "peak_rss_mb": peak_mb, "pass": passed, "checks": checks, "figures": figures,
                               "where": where, "pack_hash": h, "at": now()}
    # Prune notes for recipes that have now been recorded cleanly.
    rec["notes"] = [n for n in (rec.get("notes") or [])
                    if not any(n.startswith(f"{rid}: exceeds CI limits") and rec["recipes"].get(rid, {}).get("pass")
                               for rid, _ in pairs)]
    rec["pass"] = _all_recipes_pass(pack, rec["recipes"], h)
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
    elif not any(x.get("pack_hash") == h and set(x.get("published") or {}) & PUBLIC_TARGETS
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
    return {"doi": pack.doi, "title": pack.title, "slug": pack.slug, "version": pack.version, "pack_hash": h[:12],
            "stage": stage, "next": nxt, "badges": badges, "components": comp,
            "lint": {"errors": len(errs), "warnings": len(findings) - len(errs)},
            "l1": {"at": l1.get("at"), "pass": l1.get("pass"),
                   "recipes": {k: {"pass": v.get("pass"), "seconds": v.get("seconds"), "peak_rss_mb": v.get("peak_rss_mb"),
                                   "panel": v.get("panel"), "where": v.get("where")} for k, v in (l1.get("recipes") or {}).items()}} if l1 else None,
            "review": {k: rv.get(k) for k in ("at", "by", "verdict", "note")} if rv else None,
            "signoff": {k: so.get(k) for k in ("at", "by", "decision", "note")} if so else None,
            "usertest": {"families": fams, "runs": [{k: r.get(k) for k in ("agent", "model", "at", "pass", "score", "seconds")}
                                                    for r in runs]},
            "endorsed": {k: en.get(k) for k in ("by", "orcid", "at")} if en else None,
            "releases": [{k: x.get(k) for k in ("version", "built", "published")} | {"current": x.get("pack_hash") == h}
                         for x in (rel or {}).get("releases", [])]}


def tool_available(name):
    return shutil.which(name) is not None


def resources(pack, l1_root=None):
    """What running this pack costs, combining per-recipe needs with measured L1/HPC runs and usertest timings."""
    from . import ids
    out_dirs = [Path(l1_root) / ids.doi_relpath(pack.doi)] if l1_root else []
    nd = needs(pack, out_dirs=out_dirs)
    outputs_bytes = None
    if out_dirs and out_dirs[0].is_dir():
        outputs_bytes = sum(f.stat().st_size for f in out_dirs[0].rglob("*") if f.is_file())
    l1 = record(pack, "l1") or {}
    l1_cur = l1 if l1.get("pack_hash") == pack.content_hash() else {}
    recs = {}
    for r in nd["recipes"]:
        rid = r["id"]
        lr = (l1_cur.get("recipes") or {}).get(rid) or {}
        recs[rid] = {
            "data_bytes": r["data_bytes"],
            "memory_gb": r["memory_gb"],
            "gpu": r["gpu"],
            "minutes": r["minutes"],
            "measured": r["measured"],
            "seconds": r["seconds"],
            "peak_ram_mb": r["peak_rss_mb"],
            "where": lr.get("where"),
        }
    hpc_recipes = [r["id"] for r in nd["recipes"] if not fits_ci(pack, r)]
    ut = [r for r in ((record(pack, "usertest") or {}).get("runs") or [])
          if r.get("pass") and r.get("seconds") and r.get("version") == pack.version]
    agent_min = None
    if ut:
        m = sorted(r["seconds"] for r in ut)
        agent_min = [round(m[0] / 60), round(m[-1] / 60)]
    env_bytes = 300_000_000
    data_bytes = nd["totals"]["data_bytes"]
    return {
        "data_bytes": data_bytes,
        "env_bytes": env_bytes,
        "outputs_bytes": outputs_bytes,
        "disk_bytes": data_bytes + (outputs_bytes or 0) + env_bytes,
        "memory_gb": nd["totals"]["memory_gb"],
        "gpu": nd["totals"]["gpu"],
        "recipe_minutes": nd["totals"]["minutes"],
        "peak_ram_gb": nd["totals"]["memory_gb"] if any(r["measured"] for r in nd["recipes"]) else None,
        "agent_minutes": agent_min,
        "measured_on": l1_cur.get("platform"),
        "hpc_recipes": hpc_recipes,
        "recipes": recs,
    }
