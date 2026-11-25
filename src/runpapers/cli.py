"""rp: the RunPapers command line. The same tool serves scientists' agents (get, run, request) and
maintainers' agents (new, lint, verify, review, signoff, usertest, site, ops). Add --json for machine output."""
import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, data, ids, spec
from .registry import Registry, find_root


def out(obj, as_json, text=None):
    if as_json:
        print(json.dumps(obj, indent=1, default=str))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(obj, indent=1, default=str))


def reg_():
    return Registry()


def pack_or_workspace(ident):
    """In a workspace (rp get folder) with no id: that pack. Otherwise the registry pack."""
    from .workspace import load_workspace
    if not ident:
        ws, pk, meta = load_workspace()
        if not ws:
            raise SystemExit("not inside a RunPapers workspace; give a DOI/PMID or `cd` into the folder `rp get` made")
        return pk, Path(meta["data_dir"]), ws / "out", ws
    reg = reg_()
    pk = reg.pack(ident)
    from .ops import l1_out
    return pk, data.data_dir(pk.doi), l1_out(reg, pk).parent / (l1_out(reg, pk).name + "-manual"), None


# --------------------------------------------------------------------------- user-facing
def c_get(a):
    from .workspace import get
    import shutil
    rp_cmd = os.environ.get("RUNPAPERS_RP_CMD") or ("rp" if shutil.which("rp") else "uvx runpapers")
    target, notes = get(a.id, dest=a.dir, tier=a.tier, source=a.source, fetch_data=not a.no_data, rp_cmd=a.rp_cmd or rp_cmd)
    out({"workspace": str(target), "notes": notes}, a.json, f"Ready: {target}\nNext: cd {target} and read SKILL.md")


def c_recipes(a):
    pk, *_ = pack_or_workspace(a.id)
    rows = [{"id": r["id"], "panel": r.get("panel"), "title": r.get("title"), "tier": r.get("tier", "lite")} for r in pk.recipes]
    out(rows, a.json, "\n".join(f"{r['id']:14} {r['tier']:5} {r['panel']}: {r['title']}" for r in rows))


def c_run(a):
    from . import recipes
    if len(a.args) >= 2:
        ident, rid = a.args[0], a.args[1]
    elif len(a.args) == 1:
        ident, rid = (a.args[0], None) if a.all else (None, a.args[0])
    else:
        ident, rid = None, None
    pk, dd, out_root, ws = pack_or_workspace(ident)
    todo = [r["id"] for r in pk.recipes if a.all and (r.get("tier", "lite") == "lite" or a.tier == "full")] if a.all else [rid]
    if not todo or todo == [None]:
        raise SystemExit("which recipe? `rp recipes` lists them")
    data.fetch(pk, a.tier if a.all else pk.recipe(rid).get("tier", "lite"), quiet=a.json)
    res = [recipes.run(pk, r, dd, out_root, ci=a.ci, quiet=a.json) for r in todo]
    out(res if len(res) > 1 else res[0], a.json, None if a.json else "\n".join(f"{r['recipe']}: {'PASS' if r['pass'] else 'FAIL'} -> {Path(r['log']).parent}" for r in res))
    sys.exit(0 if all(r["pass"] for r in res) else 1)


def c_fetch(a):
    pk, *_ = pack_or_workspace(a.id)
    paths, notes = data.fetch(pk, a.tier)
    out({"files": paths, "notes": notes}, a.json, "\n".join([f"{k}: {v}" for k, v in paths.items()] + notes))


def _public_request(a):
    """Outside the registry (a scientist's computer): give the GitHub link that files the request or votes on it."""
    from . import catalog
    res = catalog.open_catalog(getattr(a, "source", None)).request_paper(a.id, note=getattr(a, "note", "") or "", resolve_online=True)
    how = "add a thumbs-up to the existing request" if res.get("existing_issue") else "send the request (it takes a free GitHub account)"
    out(res, a.json, f"{res['doi']}: open this link to {how}:\n{res['issue_url']}")


def c_request(a):
    from . import requests_log
    from .registry import find_root
    if find_root() is None:
        return _public_request(a)
    reg = reg_()
    res = requests_log.request(reg, a.id, note=a.note or "", by=a.by)
    res["issue_url"] = requests_log.issue_url(reg.config.get("publish", {}).get("github_repo", "runpapers/runpapers"), res["doi"], a.note or "")
    out(res, a.json)


def c_vote(a):
    from . import requests_log
    from .registry import find_root
    if find_root() is None:
        return _public_request(a)
    out(requests_log.vote(reg_(), a.id, by=a.by), a.json)


def c_requests(a):
    from . import requests_log
    if a.sync:
        n = len(requests_log.sync_github(reg_()))
        if not a.json:
            print(f"synced {n} request issue(s) from GitHub")
    rows = requests_log.summary(reg_())
    out(rows, a.json, "\n".join(f"{r['votes']:3}  {r['status']:22} {r['doi']}  {r['title'] or ''}" for r in rows) or "no requests")


# --------------------------------------------------------------------------- identity
def c_resolve(a):
    if a.online:
        from .newpack import resolve_online
        out(resolve_online(a.id), True)
        return
    root = find_root()
    doi = Registry(root).resolve(a.id) if root else None
    if not doi:
        kind, val = ids.parse_id(a.id)
        doi = val if kind == "doi" else None
    out({"input": a.id, "doi": doi, "path": ids.doi_relpath(doi) if doi else None}, a.json,
        doi or f"{a.id}: not in this registry; try --online")


def c_list(a):
    from .ops import board
    b = board(reg_())
    out(b["papers"], a.json, "\n".join(f"{r['stage']:13} {(r.get('short') or '')[:28]:28} {r['doi']:32} {(r.get('title') or '')[:60]}" for r in b["papers"]))


def c_show(a):
    from .verify import status
    reg = reg_()
    pk = reg.pack(a.id)
    out({**pk.card(), "status": status(pk), "dir": str(pk.dir)}, True)


def c_search(a):
    from . import catalog, search
    cat = catalog.open_catalog(a.source)
    hits = search.search_entries(
        cat.entries(include_planned=not a.no_planned),
        query=" ".join(a.query or []),
        species=a.species or (),
        tissues=a.tissue or (),
        assays=a.assay or (),
        cell_types=a.cell_type or (),
        genes=a.gene or (),
        collection=a.collection,
        min_stage=a.min_stage,
        include_planned=not a.no_planned,
        limit=a.limit,
    )
    rows = [{"score": sc, **{k: e.get(k) for k in ("doi", "pmid", "title", "first_author", "journal", "year", "citekey",
                                                   "packed", "stage", "badges", "profile", "data_terms")}}
            for sc, e in hits]
    txt = "\n".join(f"{r['stage']:13} {(r.get('citekey') or ''):16} {r['doi']:32} {(r.get('title') or '')[:60]}" for r in rows) or "no matches"
    out(rows, a.json, txt)


def c_mcp(a):
    from . import catalog, mcp_server
    cat = catalog.open_catalog(a.source)
    if a.transport == "streamable-http":
        mcp_server.serve_streamable_http(cat, host=a.host, port=a.port)
    else:
        mcp_server.serve_stdio(cat)


def c_meeting(a):
    import shutil
    from . import meeting
    rp_cmd = a.rp_cmd or os.environ.get("RUNPAPERS_RP_CMD") or ("rp" if shutil.which("rp") else "uvx runpapers")
    target, manifest = meeting.build_meeting(
        a.topic,
        papers=a.papers or (),
        collection=a.collection,
        species=a.species or (),
        tissues=a.tissue or (),
        assays=a.assay or (),
        cell_types=a.cell_type or (),
        genes=a.gene or (),
        max_papers=a.max_papers,
        min_stage=a.min_stage,
        tier=a.tier,
        fetch_data=not a.no_data,
        dest=a.dir,
        source=a.source,
        rp_cmd=rp_cmd,
        quiet=a.json,
    )
    txt = (f"Ready: {target} ({len(manifest['packs'])} pack(s): {', '.join(p['citekey'] for p in manifest['packs'])})\n"
           f"Next: cd {target} and read MEETING.md")
    out(manifest, a.json, txt)


# --------------------------------------------------------------------------- building and verification
def c_new(a):
    from .newpack import resolve_online, scaffold
    reg = reg_()
    meta = resolve_online(a.id) if a.online else None
    d = scaffold(reg, a.id, meta=meta, collection=a.collection)
    out({"dir": str(d)}, a.json, f"scaffolded {d}\nnext: fill pack.toml [[data]]/[[recipes]], targets.toml, SKILL.md, evals/questions.toml; then `rp lint`")


def _targets(a):
    reg = reg_()
    return reg, (reg.packs() if a.all else [reg.pack(a.id)])


def c_lint(a):
    reg, packs = _targets(a)
    res, bad = {}, 0
    for pk in packs:
        f = spec.lint(pk, expected_dir=reg.pack_dir(pk.doi))
        res[pk.doi] = [{"severity": s, "code": c, "message": m} for s, c, m in f]
        bad += len(spec.errors(f))
    out(res, a.json, "\n".join(f"{d}: " + ("ok" if not v else "\n  " + "\n  ".join(f"{x['severity']:5} {x['code']}: {x['message']}" for x in v)) for d, v in res.items()))
    sys.exit(1 if bad else 0)


def c_verify(a):
    from .ops import l1_out
    from .verify import run_l1
    reg, packs = _targets(a)
    res = {}
    for pk in packs:
        if a.level == "L0":
            f = spec.lint(pk, expected_dir=reg.pack_dir(pk.doi))
            res[pk.doi] = {"pass": not spec.errors(f), "errors": len(spec.errors(f))}
        else:
            rec = run_l1(pk, ci=not a.no_cap, quiet=a.json, keep_out=l1_out(reg, pk))
            res[pk.doi] = {"pass": rec["pass"], "recipes": {k: v["pass"] for k, v in rec["recipes"].items()}, "notes": rec["notes"],
                           "lint_errors": len(spec.errors([tuple(x) for x in rec["lint"]]))}
    out(res, a.json, "\n".join(f"{'PASS' if v['pass'] else 'FAIL'} {a.level} {d} {v.get('recipes', '')}" for d, v in res.items()))
    sys.exit(0 if all(v["pass"] for v in res.values()) else 1)


def c_status(a):
    from .verify import status
    reg, packs = _targets(a)
    rows = [status(pk) for pk in packs]
    out(rows if a.all else rows[0], a.json, "\n".join(
        f"{r['doi']}  [{r['stage']}]  " + " ".join(f"{k}:{v}" for k, v in r["badges"].items()) + f"\n  next: {r['next']}" for r in rows))


def c_review(a):
    from .verify import record_review
    reg = reg_()
    pk = reg.pack(a.id)
    figs = dict(x.split("=", 1) for x in (a.fig or []))
    out(record_review(pk, a.verdict, a.by, a.note or "", figs), a.json, f"review recorded: {a.verdict} by {a.by}")


def c_signoff(a):
    from .verify import record_signoff
    reg = reg_()
    pk = reg.pack(a.id)
    rej = dict(x.split("=", 1) if "=" in x else (x, "") for x in (a.reject_fig or []))
    dec = "approve" if a.approve else "reject"
    out(record_signoff(pk, dec, a.by, a.note or "", rej), a.json, f"sign-off recorded: {dec} by {a.by}")


def c_endorse(a):
    from .verify import record_endorsement
    pk = reg_().pack(a.id)
    out(record_endorsement(pk, a.by, a.orcid, a.note or ""), a.json)


def c_gallery(a):
    from .ops import gallery
    reg = reg_()
    d = gallery(reg, reg.pack(a.id), a.refs)
    out({"dir": str(d), "html": str(d / "index.html")}, a.json, str(d / "index.html"))


def c_usertest(a):
    from . import usertest
    reg = reg_()
    pk = reg.pack(a.id)
    models = dict(x.split("=", 1) for x in (a.model or []))
    res = usertest.run(reg, pk, [x.strip() for x in a.agents.split(",") if x.strip()], models=models,
                       timeout_min=a.timeout, record=not a.no_record, quiet=a.json)
    out(res, a.json, None if not a.json else None)


# --------------------------------------------------------------------------- releases and publishing
def c_release(a):
    from . import release
    reg = reg_()
    pk = reg.pack(a.id)
    if a.action == "check":
        r = release.readiness(reg, pk)
        out({k: v for k, v in r.items() if k != "status"} | {"current": release.current(pk)}, a.json,
            "\n".join(f"{'ok ' if ok else 'NO '} {k}" for k, ok in r["checks"].items()) + f"\nready: {r['ready']}")
    else:
        e = release.build(reg, pk, a.version, force=a.force)
        out(e, a.json, f"built v{e['version']}: {e['zip']} ({e['zip_bytes'] / 1e6:.1f} MB)")


def c_publish(a):
    from . import release
    reg = reg_()
    pk = reg.pack(a.id)
    fn = {"zenodo": lambda: release.publish_zenodo(reg, pk, sandbox=a.sandbox, publish=not a.draft),
          "huggingface": lambda: release.publish_hf(reg, pk, private=a.private), "github": lambda: release.publish_github(reg, pk)}[a.target]
    out(fn(), a.json)


# --------------------------------------------------------------------------- site and operations
def c_site(a):
    from . import site
    reg = reg_()
    if a.action == "build":
        d, n = site.build(reg, out=a.out, base_url=a.base_url, install_cmd=a.install)
        out({"dir": str(d), "papers": n}, a.json, f"built {n} paper page(s) into {d}")
    else:
        d = Path(a.out or reg.root / "build" / "site")
        if not d.is_dir():
            site.build(reg, out=d, base_url=f"http://{a.host}:{a.port}")
        httpd = site.serve(d, a.host, a.port)
        print(f"serving {d} at http://{a.host}:{a.port}/  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def c_ops(a):
    from . import ops
    reg = reg_()
    if a.action == "board":
        b = ops.board(reg)
        out(b, a.json, "\n".join([f"RunPapers board  {b['generated']}", "  " + "  ".join(f"{k}:{v}" for k, v in b["counts"].items() if v)] +
                                 [f"  {r['stage']:13} {(r.get('short') or '')[:26]:26} {r['doi']}  -> {r.get('next', '')}" for r in b["papers"]]))
    elif a.action == "nightly":
        out(ops.nightly(reg), a.json)
    elif a.action == "targets":
        from . import release
        out(release.targets(reg), True)
    elif a.action == "prepublish":
        from . import release
        f = release.prepublish_scan(reg)
        out([{"severity": s, "where": w, "what": m} for s, w, m in f], a.json,
            "\n".join(f"{s:5} {w}: {m}" for s, w, m in f) or "clean: nothing private found in tracked files or history")
        sys.exit(1 if any(x[0] == "error" for x in f) else 0)
    elif a.action == "fresh-history":
        from . import release
        b = release.fresh_history(reg)
        out({"backup_branch": b}, a.json, f"main is now one commit; the old history is kept locally in branch {b} (never pushed)")
    elif a.action == "github-setup":
        from . import release
        out(release.github_setup(reg, a.repo or reg.config.get("publish", {}).get("github_repo", "runpapers/runpapers")), True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="rp", description="RunPapers: verified, agent-ready paper packs.")
    p.add_argument("--version", action="version", version=f"runpapers {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.set_defaults(fn=fn)
        return sp

    s = cmd("get", c_get, "Create a working folder for a paper (pack + data link + agent instructions).")
    s.add_argument("id", help="DOI, PMID, PMCID or doi.org/PubMed URL")
    s.add_argument("--dir"); s.add_argument("--tier", default="lite", choices=["lite", "full"])
    s.add_argument("--source", help="registry folder or site URL (default: local registry, else https://runpapers.com)")
    s.add_argument("--no-data", action="store_true"); s.add_argument("--rp-cmd", help="how the workspace should call rp")
    s = cmd("recipes", c_recipes, "List a pack's recipes (inside a workspace, or give an id)."); s.add_argument("id", nargs="?")
    s = cmd("run", c_run, "Run a recipe and compare with the paper's numbers: `rp run fig2f` in a workspace, or `rp run <id> <recipe>`.")
    s.add_argument("args", nargs="*"); s.add_argument("--all", action="store_true"); s.add_argument("--ci", action="store_true", help="run under CI memory/CPU limits")
    s.add_argument("--tier", default="lite", choices=["lite", "full"])
    s = cmd("fetch", c_fetch, "Download and verify a pack's data into the cache."); s.add_argument("id", nargs="?"); s.add_argument("--tier", default="lite", choices=["lite", "full"])
    s = cmd("request", c_request, "Ask for a paper to be packed (or add your vote): prints the GitHub link that does it.")
    s.add_argument("id"); s.add_argument("--note"); s.add_argument("--by"); s.add_argument("--source", help="site URL (default https://runpapers.com)")
    s = cmd("vote", c_vote, "Vote for a requested paper."); s.add_argument("id"); s.add_argument("--by"); s.add_argument("--source")
    s = cmd("requests", c_requests, "Requested papers by votes."); s.add_argument("--sync", action="store_true", help="first take a fresh snapshot of the request issues on GitHub")
    s = cmd("resolve", c_resolve, "Turn a PMID/PMCID/URL/DOI into the canonical DOI."); s.add_argument("id"); s.add_argument("--online", action="store_true")
    cmd("list", c_list, "Every paper in the registry and collections with its pipeline stage.")
    s = cmd("show", c_show, "A pack's card and status."); s.add_argument("id")
    s = cmd("search", c_search, "Search packs and planned papers by query and biological [profile] facets.")
    s.add_argument("query", nargs="*"); s.add_argument("--species", action="append"); s.add_argument("--tissue", action="append")
    s.add_argument("--assay", action="append"); s.add_argument("--cell-type", action="append"); s.add_argument("--gene", action="append")
    s.add_argument("--collection"); s.add_argument("--min-stage"); s.add_argument("--no-planned", action="store_true")
    s.add_argument("--limit", type=int, default=20); s.add_argument("--source")
    s = cmd("mcp", c_mcp, "Run the local Model Context Protocol (MCP) server (stdio by default, zero extra dependencies).")
    s.add_argument("--source", help="registry folder or site URL")
    s.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8766)
    s = cmd("meeting", c_meeting, "Assemble a multi-paper workspace for a topic using pack [profile] metadata.")
    s.add_argument("topic", help="scientific topic or cross-paper question")
    s.add_argument("--papers", action="append", help="explicit DOI/PMID (comma-separated or repeatable)")
    s.add_argument("--collection"); s.add_argument("--species", action="append"); s.add_argument("--tissue", action="append")
    s.add_argument("--assay", action="append"); s.add_argument("--cell-type", action="append"); s.add_argument("--gene", action="append")
    s.add_argument("--max-papers", type=int, default=5); s.add_argument("--min-stage", default="runs")
    s.add_argument("--tier", default="lite", choices=["lite", "full"]); s.add_argument("--no-data", action="store_true")
    s.add_argument("--dir"); s.add_argument("--source"); s.add_argument("--rp-cmd")
    s = cmd("new", c_new, "Scaffold a pack for a paper."); s.add_argument("id"); s.add_argument("--online", action="store_true"); s.add_argument("--collection")
    for name, fn, h in (("lint", c_lint, "Level-0 checks (format, licenses, completeness, security)."),
                        ("status", c_status, "Badges, stage and next step.")):
        s = cmd(name, fn, h); s.add_argument("id", nargs="?"); s.add_argument("--all", action="store_true")
    s = cmd("verify", c_verify, "Run verification (L1 by default: fetch lite data, run lite recipes under CI limits, check targets).")
    s.add_argument("id", nargs="?"); s.add_argument("--all", action="store_true"); s.add_argument("--level", default="L1", choices=["L0", "L1"])
    s.add_argument("--no-cap", action="store_true", help="don't apply CI memory/CPU limits")
    s = cmd("review", c_review, "Record the critic's independent check of every reproduced panel.")
    s.add_argument("id"); s.add_argument("--verdict", required=True, choices=["pass", "revise"]); s.add_argument("--by", required=True)
    s.add_argument("--note"); s.add_argument("--fig", action="append", help="recipe=verdict note (repeatable)")
    s = cmd("signoff", c_signoff, "Record the human sign-off that grants 'reproduces'.")
    s.add_argument("id"); g = s.add_mutually_exclusive_group(required=True); g.add_argument("--approve", action="store_true"); g.add_argument("--reject", action="store_true")
    s.add_argument("--by", required=True); s.add_argument("--note"); s.add_argument("--reject-fig", action="append", help="recipe=reason (repeatable)")
    s = cmd("endorse", c_endorse, "Record an author's endorsement."); s.add_argument("id"); s.add_argument("--by", required=True); s.add_argument("--orcid", required=True); s.add_argument("--note")
    s = cmd("gallery", c_gallery, "Build the side-by-side sign-off page (published vs reproduced)."); s.add_argument("id"); s.add_argument("--refs")
    s = cmd("usertest", c_usertest, "L3: fresh agents get only the copy-prompt; grade what they produce.")
    s.add_argument("id"); s.add_argument("--agents", default="claude,agy,codex"); s.add_argument("--model", action="append", help="agent=model")
    s.add_argument("--timeout", type=int, default=45, help="minutes per agent"); s.add_argument("--no-record", action="store_true")
    s = cmd("site", c_site, "Build or serve the static website."); s.add_argument("action", choices=["build", "serve"])
    s.add_argument("--out"); s.add_argument("--base-url"); s.add_argument("--install"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8765)
    s = cmd("release", c_release, "Freeze a verified pack version (zip + archive metadata), or check readiness.")
    s.add_argument("action", choices=["check", "build"]); s.add_argument("id"); s.add_argument("--version"); s.add_argument("--force", action="store_true")
    s = cmd("publish", c_publish, "Publish the built release: github (tag + release), zenodo (DOI), huggingface (dataset).")
    s.add_argument("target", choices=["github", "zenodo", "huggingface"]); s.add_argument("id")
    s.add_argument("--sandbox", action="store_true", help="Zenodo sandbox (test DOI)"); s.add_argument("--draft", action="store_true", help="Zenodo: a private draft (DOI reserved), not published")
    s.add_argument("--private", action="store_true", help="Hugging Face: a private dataset (preview)")
    s = cmd("ops", c_ops, "Maintainer: board, nightly, targets, prepublish (privacy scan), fresh-history, github-setup.")
    s.add_argument("action", choices=["board", "nightly", "targets", "prepublish", "fresh-history", "github-setup"]); s.add_argument("--repo")
    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (ids.IdError, KeyError) as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
