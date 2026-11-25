"""Maintainer operations: the pipeline board (one JSON the Lab panel and agents both read), the sign-off
gallery (published vs reproduced, side by side) and the nightly run."""
import html
import json
import os
import subprocess
from pathlib import Path

from . import __version__, ids, spec
from .recipes import check_tolerance, format_expected
from .registry import read_json, write_json
from .requests_log import summary as requests_summary
from .verify import STAGES, fits_ci, now, record, run_l1, status


def board(reg):
    packs = {p.doi: p for p in reg.packs()}
    planned = reg.planned()
    reqs = {r["doi"]: r for r in requests_summary(reg)}
    rows = []
    for doi, pk in packs.items():
        st = status(pk)
        st["collections"] = pk.paper.get("collections", [])
        st["pmid"] = pk.paper.get("pmid")
        st["votes"] = reqs.get(doi, {}).get("votes", 0)
        st["short"] = planned.get(doi, {}).get("short") or pk.slug
        rows.append(st)
    for doi, p in planned.items():
        if doi in packs:
            continue
        rows.append({"doi": doi, "title": p.get("title"), "pmid": p.get("pmid"), "short": p.get("short"),
                     "collections": [p["collection"]], "stage": "planned", "next": "scaffold the pack (`rp new " + doi + "`)",
                     "badges": {}, "votes": reqs.get(doi, {}).get("votes", 0)})
    order = {s: i for i, s in enumerate(STAGES)}
    rows.sort(key=lambda r: (-order.get(r["stage"], 0), -r.get("votes", 0), r.get("short") or ""))
    counts = {s: sum(1 for r in rows if r["stage"] == s) for s in STAGES}
    signoff = [r for r in rows if r["stage"] == "checked"]
    site_dir = reg.root / "build" / "site"
    nightly = read_json(reg.root / "build" / "nightly.json")
    git = _git(reg.root)
    return {"generated": now(), "rp_version": __version__, "repo": str(reg.root), "counts": counts, "papers": rows,
            "signoff_queue": [{"doi": r["doi"], "title": r["title"], "review": r.get("review")} for r in signoff],
            "requests": [r for r in reqs.values() if r["doi"] not in packs][:30],
            "site": {"built": site_dir.is_dir(), "built_at": _mtime(site_dir / "index.json")},
            "nightly": nightly, "git": git}


def _mtime(p):
    try:
        import datetime as dt
        return dt.datetime.fromtimestamp(Path(p).stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except FileNotFoundError:
        return None


def _git(root):
    try:
        head = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h %cI %s"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        remote = subprocess.run(["git", "-C", str(root), "remote"], capture_output=True, text=True).stdout.split()
        return {"head": head, "dirty_files": len(dirty.splitlines()) if dirty else 0, "remotes": remote}
    except OSError:
        return None


def l1_out(reg, pack):
    return reg.root / "build" / "l1" / ids.doi_relpath(pack.doi)


def gallery(reg, pack, refs_dir=None):
    """build/gallery/<doi>/index.html: each panel's published image (private, if available) next to ours, with the
    target table. This is what the critic and the PI look at before signing off."""
    refs = Path(refs_dir or os.environ.get("RUNPAPERS_REFS", reg.root / "refs")) / ids.doi_relpath(pack.doi)
    out = reg.root / "build" / "gallery" / ids.doi_relpath(pack.doi)
    out.mkdir(parents=True, exist_ok=True)
    l1 = record(pack, "l1") or {}
    e = lambda x: html.escape(str(x))
    items, panels = [], []
    l1_cur = l1 if l1.get("pack_hash") == pack.content_hash() else {}
    for r in pack.recipes:
        rid = r["id"]
        nd = pack.recipe_needs(r)
        hpc = not fits_ci(pack, r)
        rdir = l1_out(reg, pack) / rid
        res = read_json(rdir / "result.json") or ((l1_cur.get("recipes") or {}).get(rid) or {})
        ours = ([rdir / f for f in res["figures"] if (rdir / f).is_file()] if res.get("figures") and rdir.is_dir()
                else (sorted(rdir.glob("*.png")) if res and rdir.is_dir() else []))
        theirs = sorted(refs.glob(f"{rid}*.*")) if refs.is_dir() else []
        targets = pack.targets_for(rid)
        if res.get("checks"):
            checks = "".join(
                f"<tr><td>{e(c['metric'])}</td><td>{e(format_expected(c.get('expected'), check_tolerance(c, targets)))}</td><td>{e(c['observed'])}</td>"
                f"<td style='color:{'#1f8a4c' if c['ok'] else ('#b07d0b' if not c.get('required', True) else '#b3261e')}'>{'match' if c['ok'] else ('known discrepancy' if not c.get('required', True) else 'MISMATCH')}</td>"
                f"<td>{e(c['detail'])}</td><td>{e(c['source'])}</td></tr>"
                for c in res["checks"]
            )
        else:
            checks = "".join(
                f"<tr><td>{e(t['metric'])}</td><td>{e(format_expected(t.get('expected'), t.get('tolerance')))}</td><td class='mut'>—</td>"
                f"<td class='mut'>not run yet</td><td class='mut'>{'run on HPC and record with rp verify --record' if hpc else 'run recipe to compare'}</td>"
                f"<td>{e(t.get('source', ''))}</td></tr>"
                for t in targets
            )
        where = res.get("where") or ((l1_cur.get("recipes") or {}).get(rid) or {}).get("where")
        needs_pill = (f"<span class='pill{' hpc' if (hpc or where == 'hpc') else ''}'>"
                      f"{nd['memory_gb']:g} GB · {'GPU' if nd['gpu'] else 'CPU'} · {nd['minutes']:g}m"
                      + (f" · {e(where)}" if where == "hpc" else (" · HPC" if hpc else "")) + "</span>")
        run_state = ("PASS" if res.get("pass") else ("not run yet (HPC)" if not res and hpc
                     else ("not run yet" if not res else "not passing")))
        none_repro = "not run yet (HPC recipe)" if not res and hpc else "none"
        imgs = lambda ps, lab: "".join(f"<figure><figcaption>{lab}: {e(p.name)}</figcaption><img src='file://{e(str(p))}' alt='{e(lab)}: {e(p.name)}'></figure>" for p in ps) \
            or f"<figure><figcaption>{lab}</figcaption><p class='mut'>{'none (published images are kept privately in refs/ until the paper license allows showing them)' if lab == 'Published' else none_repro}</p></figure>"
        items.append(f"<section><h2>{e(r.get('panel', ''))} · <code>{e(rid)}</code> {needs_pill} · {run_state}</h2>"
                     f"<p>{e(r.get('title', ''))}</p><div class='pair'>{imgs(theirs, 'Published')}{imgs(ours, 'Reproduced')}</div>"
                     f"<table><tr><th>Metric</th><th>Paper</th><th>Ours</th><th></th><th>Detail</th><th>Source</th></tr>{checks}</table></section>")
        panels.append({"recipe": rid, "panel": r.get("panel"), "needs": nd, "where": where, "pass": res.get("pass"),
                       "ours": [str(p) for p in ours], "published": [str(p) for p in theirs], "checks": res.get("checks", [])})
    page = f"""<!doctype html><meta charset=utf-8><title>Sign-off: {e(pack.title)}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:1200px;margin:20px auto;padding:0 16px;color:#1d2230}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}figure{{margin:0;border:1px solid #e3e7ef;border-radius:8px;padding:8px}}
img{{width:100%}}table{{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 24px}}td,th{{border-bottom:1px solid #e3e7ef;padding:5px;text-align:left}}
.pill{{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:12px;background:#f3f4f6;color:#374151;vertical-align:middle}}
.pill.hpc{{background:#eef2ff;color:#1e3a8a;border:1px solid #c7d2fe}}
.mut{{color:#5b6475}}section{{border-top:2px solid #1d2230;margin-top:20px}}</style>
<h1>{e(pack.title)}</h1><p>DOI {e(pack.doi)} · pack v{e(pack.version)} · hash {pack.content_hash()[:12]} · L1 at {e(l1.get('at', 'never'))}</p>
{''.join(items)}"""
    (out / "index.html").write_text(page)
    write_json(out / "gallery.json", {"doi": pack.doi, "title": pack.title, "version": pack.version,
                                      "pack_hash": pack.content_hash(), "panels": panels})
    return out


def nightly(reg, run_l1_stale=True, quiet=True):
    """Lint every pack; re-run CI-eligible recipes where L1 is missing or stale; rebuild
    the site; write build/nightly.json. Never touches sign-offs or reviews."""
    from . import site
    rep = {"at": now(), "packs": {}, "site": None}
    for pk in reg.packs():
        f = spec.lint(pk)
        st = status(pk)
        entry = {"lint_errors": len(spec.errors(f)), "stage_before": st["stage"]}
        if run_l1_stale and not spec.errors(f) and st["badges"].get("runs") in ("none", "stale"):
            rec = run_l1(pk, ci=True, quiet=quiet, keep_out=l1_out(reg, pk))
            entry["l1"] = "pass" if rec["pass"] else "fail"
        entry["stage_after"] = status(pk)["stage"]
        rep["packs"][pk.doi] = entry
    out, n = site.build(reg)
    rep["site"] = {"dir": str(out), "papers": n}
    write_json(reg.root / "build" / "nightly.json", rep)
    return rep
