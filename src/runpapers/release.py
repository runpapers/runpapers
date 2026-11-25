"""Releases and publishing. A release is one pack version, frozen: a zip with the pack, the reproduced outputs and
every verification record, plus metadata for archives. Publishing sends it to GitHub (repository, tag, release),
Zenodo (a citable DOI) and Hugging Face (the agent-ready dataset). Credentials are read from the environment or
~/.config/runpapers/<name>_token and never written anywhere else.

Nothing here runs without a passing sign-off and passing naive-user tests on the exact content being released."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import DEFAULT_BASE, __version__, ids
from .registry import read_json, sha256_file, write_json
from .verify import PUBLIC_TARGETS, now, record, status, vdir
from .workspace import shipped

CONFIG = Path(os.environ.get("RUNPAPERS_CONFIG", "~/.config/runpapers")).expanduser()
ZENODO = {"zenodo": "https://zenodo.org", "sandbox": "https://sandbox.zenodo.org"}


# --------------------------------------------------------------------------- credentials (presence only, never printed)
def token(name):
    v = os.environ.get(f"RUNPAPERS_{name.upper()}_TOKEN")
    if v:
        return v.strip()
    p = CONFIG / f"{name}_token"
    return p.read_text().strip() if p.is_file() else None


def targets(reg):
    """Which publishing targets are configured (without revealing any secret)."""
    pub = reg.config.get("publish", {})
    remote = subprocess.run(["git", "-C", str(reg.root), "remote", "get-url", "origin"], capture_output=True, text=True)
    gh = shutil.which("gh") is not None and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0
    return {
        "github": {"ready": remote.returncode == 0 and gh, "remote": remote.stdout.strip() or None, "gh_auth": gh,
                   "repo": pub.get("github_repo")},
        "zenodo": {"ready": bool(token("zenodo")), "sandbox_ready": bool(token("zenodo_sandbox")), "community": pub.get("zenodo_community")},
        "huggingface": {"ready": bool(token("hf")), "org": pub.get("hf_org")},
        "site": {"base_url": reg.config.get("site", {}).get("base_url"), "install_cmd": reg.config.get("site", {}).get("install_cmd")},
    }


# --------------------------------------------------------------------------- pre-publication privacy scan
_NON_EMAIL_SUFFIXES = (
    "noreply@anthropic.com", ".md", ".py", ".txt", ".json", ".toml", ".csv", ".yml", ".yaml", ".html", ".png", ".svg",
)


def _is_private_email(addr):
    return not addr.endswith(_NON_EMAIL_SUFFIXES)


def prepublish_scan(reg, extra_words=()):
    """Look for anything private in tracked files and in git history: home paths, the local user name, lab-internal
    identifiers, e-mail addresses other than the project's, tokens, private keys, tracked reference images."""
    home = os.path.expanduser("~")
    user = os.path.basename(home)
    # Keep internal marker literals split in source so release.py (and its git diff) never self-matches this scan.
    internal_markers = ("@" + "lab.local", "LAB_" + "AGENT")
    ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    words = [home, f"/home/{user}", *([user] if len(user) > 3 and not ci else []), *internal_markers, *extra_words]
    rx = re.compile("|".join(re.escape(w) for w in words if w) +
                    r"|\b(hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----")
    email_rx = re.compile(r"\b[A-Za-z0-9._%+-]+@(?!runpapers\.(?:org|com)\b|anthropic\.com\b|example\.org\b|users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[a-z]{2,}\b")
    found = []
    files = subprocess.run(["git", "-C", str(reg.root), "ls-files"], capture_output=True, text=True).stdout.split("\n")
    for f in filter(None, files):
        if f.startswith("refs/"):
            found.append(("error", f, "published figure images must never be tracked"))
            continue
        p = reg.root / f
        try:
            text = p.read_text(errors="ignore")
        except (IsADirectoryError, FileNotFoundError):
            continue
        for m in rx.finditer(text):
            found.append(("error", f, f"private text: {m.group(0)[:40]!r}"))
            break
        for m in email_rx.finditer(text):
            if _is_private_email(m.group(0)):
                found.append(("warn", f, f"e-mail address: {m.group(0)}"))
                break
    hist = subprocess.run(["git", "-C", str(reg.root), "log", "--exclude=refs/heads/pre-public-*", "--all", "-p",
                           "--format=%an <%ae> %cn <%ce>"], capture_output=True, text=True).stdout
    if rx.search(hist):
        found.append(("error", "git history", "earlier commits contain private text; publish a fresh history (`rp ops fresh-history`)"))
    for m in email_rx.finditer(hist):
        if _is_private_email(m.group(0)):
            found.append(("error", "git history", f"commit identity or content has e-mail {m.group(0)}; publish a fresh history"))
            break
    return found


def fresh_history(reg, message="RunPapers: first public version"):
    """Replace main with a single commit of the current tree. The old history stays in a local branch
    (pre-public-<date>) that is never pushed."""
    root = str(reg.root)
    if subprocess.run(["git", "-C", root, "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
        raise SystemExit("commit or stash your changes first")
    backup = "pre-public-" + now()[:10]
    subprocess.run(["git", "-C", root, "branch", "-f", backup, "main"], check=True)
    subprocess.run(["git", "-C", root, "checkout", "-q", "--orphan", "rp-fresh"], check=True)
    subprocess.run(["git", "-C", root, "commit", "-q", "-m", message], check=True)
    subprocess.run(["git", "-C", root, "branch", "-f", "main", "rp-fresh"], check=True)
    subprocess.run(["git", "-C", root, "checkout", "-q", "main"], check=True)
    subprocess.run(["git", "-C", root, "branch", "-q", "-D", "rp-fresh"], check=True)
    return backup


# --------------------------------------------------------------------------- building a release
def readiness(reg, pack):
    st = status(pack)
    b = st["badges"]
    checks = {
        "lint clean": st["lint"]["errors"] == 0,
        "runs (L1) on this content": b["runs"] == "pass",
        "critic review on this content": b["checked"] == "pass",
        "sign-off on this content": b["reproduces"] == "pass",
        "naive-user tests (>= 2 companies) on this content": b["agent-tested"] == "pass",
    }
    return {"ready": all(checks.values()), "checks": checks, "status": st}


def release_dir(reg, pack, version):
    return reg.root / "build" / "release" / ids.doi_relpath(pack.doi) / version


def _install(reg):
    return reg.config.get("site", {}).get("install_cmd") or "uvx runpapers"


def _terms_link(pack):
    for d in pack.data:
        m = re.search(r"https?://[^\s)]+", d.get("license", ""))
        if m:
            return m.group(0).rstrip(".,;")
    return None


def readme(pack, version, st, install="uvx runpapers"):
    p = pack.paper
    terms = sorted({d.get("license", "") for d in pack.data})
    return f"""# RunPapers pack: {pack.title}

{p.get('first_author', '')} et al., *{p.get('journal', '')}* {p.get('year', '')}. DOI [{pack.doi}](https://doi.org/{pack.doi})
{f"· PMID {p['pmid']}" if p.get('pmid') else ''}

Pack version {version}. Verified: {", ".join(k for k, v in st["badges"].items() if v == "pass")}.

{pack.meta.get('pack', {}).get('summary', '')}

## Use it with your AI agent
Ask your agent (Claude Code, Codex, Antigravity, ...): "Use RunPapers to work with the data of DOI {pack.doi}:
reproduce a figure, then answer my question." Or run `{install} get {pack.doi}` yourself.

## Contents
- `pack/`: the pack (instructions for agents in SKILL.md, recipes, the paper's numbers in targets.toml)
- `reproduced/`: the figures and tables our recipes produced from the original data, with `result.json`
  (the paper's numbers next to ours)
- `verification/`: the records behind every badge (automatic runs, review, sign-off, naive-user tests)

## Data terms
The data are not included; recipes download them from the original repositories. Terms: {"; ".join(terms)}.

## Cite
Cite the paper (https://doi.org/{pack.doi}) and this pack.
"""


def build(reg, pack, version=None, force=False):
    """Freeze the current pack as a release: zip + metadata + verify/release.json. Returns the release record."""
    version = version or pack.version
    r = readiness(reg, pack)
    if not r["ready"] and not force:
        missing = [k for k, ok in r["checks"].items() if not ok]
        raise SystemExit("not ready to release: " + "; ".join(missing))
    h = pack.content_hash()
    rel = record(pack, "release") or {"releases": []}
    for x in rel.get("releases", []):
        if x["version"] == version and x["pack_hash"] != h and set(x.get("published") or {}) & PUBLIC_TARGETS:
            raise SystemExit(f"version {version} was already released with other content; bump [pack] version")
    d = release_dir(reg, pack, version)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    name = f"runpapers-{pack.slug}-v{version}"
    zpath = d / f"{name}.zip"
    l1 = reg.root / "build" / "l1" / ids.doi_relpath(pack.doi)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{name}/README.md", readme(pack, version, r["status"], _install(reg)))
        for f in pack.files():
            if shipped(f):
                z.write(pack.dir / f, f"{name}/pack/{f}")
        for rec in sorted(vdir(pack).glob("*.json")):
            if rec.name != "release.json":
                z.write(rec, f"{name}/verification/{rec.name}")
        for f in sorted(l1.glob("*/*")):
            if f.suffix in (".png", ".csv", ".json") and not f.name.startswith("."):
                z.write(f, f"{name}/reproduced/{f.parent.name}/{f.name}")
    entry = {"version": version, "pack_hash": h, "built": now(), "rp_version": __version__, "zip": zpath.name,
             "zip_sha256": sha256_file(zpath), "zip_bytes": zpath.stat().st_size, "published": {}}
    rel["releases"] = [x for x in rel.get("releases", []) if x["version"] != version] + [entry]
    rel["pack_hash"] = h   # status() treats the pack as released when this matches and a target is published
    write_json(vdir(pack) / "release.json", rel)
    write_json(d / "zenodo.json", zenodo_metadata(reg, pack, version))
    return entry


def current(pack):
    rel = record(pack, "release") or {}
    return next((x for x in reversed(rel.get("releases", [])) if x["pack_hash"] == pack.content_hash()), None)


def published(pack):
    """{version, doi, concept_doi, zenodo, huggingface, github} for the release of the current content, or None."""
    e = current(pack)
    pub = (e or {}).get("published") or {}
    if not (set(pub) & PUBLIC_TARGETS):
        return None
    z, h, g = pub.get("zenodo") or {}, pub.get("huggingface") or {}, pub.get("github") or {}
    return {"version": e["version"], "doi": z.get("doi"), "concept_doi": z.get("concept_doi"), "zenodo": z.get("url"),
            "huggingface": h.get("url"), "github": g.get("url")}


def _mark(pack, version, target, info):
    rel = record(pack, "release")
    for x in rel["releases"]:
        if x["version"] == version:
            x.setdefault("published", {})[target] = {"at": now(), **info}
    write_json(vdir(pack) / "release.json", rel)


# --------------------------------------------------------------------------- Zenodo
_NC_RX = re.compile(r"non-?commercial|\bNC\b|cc-by-nc", re.I)


def html_escape(s):
    import html
    return html.escape(s, quote=False)


def license_for(pack):
    """The archive's license: CC BY 4.0, unless a data source allows only noncommercial use. The release contains
    tables derived from the data, so it can't be more open than its most restrictive source."""
    return "cc-by-nc-4.0" if any(_NC_RX.search(d.get("license", "")) for d in pack.data) else "cc-by-4.0"


def zenodo_metadata(reg, pack, version):
    p = pack.paper
    pub = reg.config.get("publish", {})
    base = reg.config.get("site", {}).get("base_url", DEFAULT_BASE).rstrip("/")
    rel_ids = [{"relation": "isSupplementTo", "identifier": pack.doi, "scheme": "doi", "resource_type": "publication-article"},
               {"relation": "isDocumentedBy", "identifier": f"{base}/doi/{ids.doi_relpath(pack.doi)}/", "scheme": "url"}]
    if p.get("preprint_doi"):
        rel_ids.append({"relation": "isSupplementTo", "identifier": p["preprint_doi"], "scheme": "doi", "resource_type": "publication-preprint"})
    for src in sorted({d["url"].split("/metadata/")[0] if "/metadata/" in d["url"] else d["url"] for d in pack.data})[:5]:
        rel_ids.append({"relation": "isDerivedFrom", "identifier": src, "scheme": "url"})
    gh = pub.get("github_repo") or "runpapers/runpapers"
    terms = sorted({d.get("license", "").strip() for d in pack.data if d.get("license", "").strip()}) or ["see pack/pack.toml"]
    if gh:
        rel_ids.append({"relation": "isSupplementTo", "identifier": f"https://github.com/{gh}", "scheme": "url"})
    meta = {
        "upload_type": "software",
        "title": f"RunPapers pack {pack.doi}: {pack.title} ({p.get('first_author', '').split()[-1] if p.get('first_author') else ''} et al., {p.get('journal', '')} {p.get('year', '')})",
        "creators": [{"name": pub.get("creator", "RunPapers")}],
        "description": (f"<p>A verified, agent-ready pack for <a href='https://doi.org/{pack.doi}'>{pack.title}</a>. "
                        f"{pack.meta.get('pack', {}).get('summary', '')}</p><p>Any AI agent can use it to reproduce the "
                        f"paper's figures from the original data and answer new questions. The original data are not "
                        f"included: recipes download them from the original repositories. The reproduced tables and "
                        f"figures in <code>reproduced/</code> are derived from those data and stay under the source's "
                        f"terms: {html_escape('; '.join(terms))}. RunPapers' own instructions and recipes are also "
                        f"available under the MIT license at <a href='https://github.com/{gh}'>github.com/{gh}</a>.</p>"),
        "version": version,
        "license": license_for(pack),
        "keywords": ["RunPapers", pack.doi, "reproducibility", "AI agents", "agent skills", *pack.meta.get("profile", {}).get("assays", [])[:3],
                     *pack.meta.get("profile", {}).get("tissues", [])[:2]],
        "related_identifiers": rel_ids,
        "notes": "Data terms: " + "; ".join(sorted({d.get("license", "") for d in pack.data})),
    }
    if pub.get("zenodo_community"):
        meta["communities"] = [{"identifier": pub["zenodo_community"]}]
    return meta


def _http(method, url, tok, data=None, ctype="application/json", raw=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": ctype, "User-Agent": f"runpapers/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            txt = r.read()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url.split('?')[0]}: HTTP {e.code} {e.read()[:400]!r}")


def publish_zenodo(reg, pack, sandbox=False, publish=True, api=None):
    """Create (or add a new version to) the pack's Zenodo record, upload the zip, publish. Returns {doi, url}."""
    entry = current(pack)
    if not entry:
        raise SystemExit("build the release first (`rp release build`)")
    kind = "sandbox" if sandbox else "zenodo"
    tok = token("zenodo_sandbox" if sandbox else "zenodo")
    if not tok:
        raise SystemExit(f"no {kind} token (~/.config/runpapers/{'zenodo_sandbox' if sandbox else 'zenodo'}_token)")
    api = (api or ZENODO[kind]).rstrip("/")
    rel = record(pack, "release")
    z = (rel.get("zenodo") or {}).get(kind, {})
    dep = None
    if z.get("draft_id"):   # the private draft made by a preview: publish that one (its DOI is already reserved)
        dep = _http("GET", f"{api}/api/deposit/depositions/{z['draft_id']}", tok)
        if dep.get("submitted"):   # published by hand on zenodo.org meanwhile
            return _zenodo_done(pack, entry, kind, dep, sandbox)
    elif z.get("deposition_id"):   # already published once: a new version of the same record (same concept DOI)
        dep = _http("POST", f"{api}/api/deposit/depositions/{z['deposition_id']}/actions/newversion", tok)
        dep = _http("GET", dep["links"]["latest_draft"], tok)
    else:
        dep = _http("POST", f"{api}/api/deposit/depositions", tok, {})
    for f in dep.get("files", []):
        _http("DELETE", f"{api}/api/deposit/depositions/{dep['id']}/files/{f['id']}", tok)
    d = release_dir(reg, pack, entry["version"])
    zpath = d / entry["zip"]
    _http("PUT", f"{dep['links']['bucket']}/{zpath.name}", tok, raw=zpath.read_bytes(), ctype="application/octet-stream")
    meta = json.loads((d / "zenodo.json").read_text())
    dep = _http("PUT", f"{api}/api/deposit/depositions/{dep['id']}", tok, {"metadata": meta}) or dep
    if not publish:
        reserved = ((dep.get("metadata") or {}).get("prereserve_doi") or {}).get("doi")
        out = {"draft_id": dep["id"], "reserved_doi": reserved, "url": (dep.get("links") or {}).get("html"), "draft": True}
        rel = record(pack, "release")
        rel.setdefault("zenodo", {}).setdefault(kind, {}).update({"draft_id": dep["id"], "reserved_doi": reserved})
        write_json(vdir(pack) / "release.json", rel)
        _mark(pack, entry["version"], ("zenodo-sandbox" if sandbox else "zenodo") + "-draft", out)
        return out
    res = _http("POST", f"{api}/api/deposit/depositions/{dep['id']}/actions/publish", tok)
    return _zenodo_done(pack, entry, kind, res, sandbox)


def _zenodo_done(pack, entry, kind, res, sandbox):
    out = {"deposition_id": res["id"], "doi": res.get("doi"), "concept_doi": res.get("conceptdoi"),
           "url": (res.get("links") or {}).get("record_html") or (res.get("links") or {}).get("html"), "draft": False}
    rel = record(pack, "release")
    rel.setdefault("zenodo", {})[kind] = {"deposition_id": out["deposition_id"], "concept_doi": out.get("concept_doi")}
    write_json(vdir(pack) / "release.json", rel)
    _mark(pack, entry["version"], "zenodo-sandbox" if sandbox else "zenodo", out)
    return out


# --------------------------------------------------------------------------- Hugging Face
def hf_card(reg, pack, version, repo_id):
    p = pack.paper
    l1 = reg.root / "build" / "l1" / ids.doi_relpath(pack.doi)
    tables = sorted({(f.parent.name, f.name) for f in l1.glob("*/*.csv")})
    configs = "\n".join(f"- config_name: {Path(t).stem}\n  data_files: \"reproduced/{r}/{t}\"" for r, t in tables)
    terms = sorted({d.get("license", "").strip() for d in pack.data if d.get("license", "").strip()})
    link = _terms_link(pack)
    lic = (f"license: other\nlicense_name: source-data-terms\nlicense_link: {link}" if link else "license: other")
    prof = pack.meta.get("profile", {})
    tags = ["runpapers", "agent-ready", "reproducibility", "biology",
            *[str(x).lower().replace(" ", "-") for x in (prof.get("tissues", []) + prof.get("assays", []))[:4]]]
    table_lines = "\n".join(f"- `reproduced/{r}/{t}`" for r, t in tables)
    return f"""---
{lic}
pretty_name: "RunPapers: {pack.title}"
tags: [{", ".join(dict.fromkeys(tags))}]
configs:
{configs}
---

# RunPapers pack: {pack.title}

{p.get('first_author', '')} et al., *{p.get('journal', '')}* {p.get('year', '')}, DOI [{pack.doi}](https://doi.org/{pack.doi}).
Pack version {version}.

This dataset is the agent-ready layer of a [RunPapers](https://github.com/{reg.config.get('publish', {}).get('github_repo', 'runpapers/runpapers')})
pack: the instructions any AI agent can follow (`pack/SKILL.md`), the recipes that reproduce published panels from the
original data, and the tables and figures those recipes produced (`reproduced/`), with the paper's numbers next to ours
(`reproduced/*/result.json`).

Tables (`pack/SKILL.md` explains each one):
{table_lines or "- none"}

The raw files are not re-hosted; `pack/pack.toml` lists their original locations and checksums.

**Use it from an agent:** "Use RunPapers to work with the data of DOI {pack.doi}" or `{_install(reg)} get {pack.doi}`.
Website: {reg.config.get("site", {}).get("base_url", DEFAULT_BASE).rstrip("/")}/doi/{ids.doi_relpath(pack.doi)}/

**Terms:** the reproduced tables are derived from the original data, which stay under their source terms:
{"; ".join(terms) or "see pack/pack.toml"}. Cite the paper and the data source as those terms require.
RunPapers' own instructions and recipes are CC BY 4.0 / MIT.
"""


def publish_hf(reg, pack, repo_id=None, private=False):
    entry = current(pack)
    if not entry:
        raise SystemExit("build the release first (`rp release build`)")
    tok = token("hf")
    if not tok:
        raise SystemExit("no Hugging Face token (~/.config/runpapers/hf_token)")
    org = reg.config.get("publish", {}).get("hf_org", "runpapers")
    repo_id = repo_id or f"{org}/{pack.slug}"
    stage = release_dir(reg, pack, entry["version"]) / "hf"
    if stage.exists():
        shutil.rmtree(stage)
    with zipfile.ZipFile(release_dir(reg, pack, entry["version"]) / entry["zip"]) as z:
        z.extractall(stage)
    root = next(stage.iterdir())
    (root / "README.md").write_text(hf_card(reg, pack, entry["version"], repo_id))
    script = (
        "import sys\nfrom huggingface_hub import HfApi\napi=HfApi(token=open(sys.argv[3]).read().strip())\n"
        "rid, folder, ver, private = sys.argv[1], sys.argv[2], sys.argv[4], sys.argv[5] == '1'\n"
        "if private and api.repo_exists(rid, repo_type='dataset') and not api.dataset_info(rid).private:\n"
        "    print('SKIP already public; a preview would change the public dataset'); sys.exit(0)\n"
        "api.create_repo(rid, repo_type='dataset', exist_ok=True, private=private)\n"
        "c=api.upload_folder(repo_id=rid, repo_type='dataset', folder_path=folder, "
        "commit_message='RunPapers pack v'+ver, delete_patterns=['*'])\n"
        "if not private:\n"
        "    api.update_repo_settings(rid, private=False, repo_type='dataset')\n"
        "    api.create_tag(rid, tag='v'+ver, repo_type='dataset', exist_ok=True)\n"
        "print(c.commit_url)\n")
    tf = stage / ".tok"
    tf.write_text(tok)
    os.chmod(tf, 0o600)
    try:
        r = subprocess.run(["uv", "run", "--quiet", "--no-project", "--with", "huggingface_hub>=0.30", "python", "-c", script,
                            repo_id, str(root), str(tf), entry["version"], "1" if private else "0"],
                           capture_output=True, text=True, timeout=900)
    finally:
        tf.unlink(missing_ok=True)
    if r.returncode != 0:
        raise SystemExit(f"Hugging Face upload failed: {(r.stderr or r.stdout)[-600:]}")
    last = (r.stdout.strip().splitlines() or [""])[-1]
    out = {"repo": repo_id, "url": f"https://huggingface.co/datasets/{repo_id}", "private": private}
    if last.startswith("SKIP"):
        return {**out, "skipped": last[5:]}
    out["commit"] = last
    _mark(pack, entry["version"], "huggingface-preview" if private else "huggingface", out)
    return out


# --------------------------------------------------------------------------- GitHub (repository, tag, release)
def publish_github(reg, pack):
    entry = current(pack)
    if not entry:
        raise SystemExit("build the release first (`rp release build`)")
    root = str(reg.root)
    if subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True).returncode != 0:
        raise SystemExit("no git remote 'origin' (set up with `rp ops github-setup`)")
    bad = [f for f in prepublish_scan(reg) if f[0] == "error"]
    if bad:
        raise SystemExit("pre-publication scan failed: " + "; ".join(f"{a}: {c}" for _, a, c in bad[:5]))
    tag = f"pack/{pack.slug}/v{entry['version']}"
    subprocess.run(["git", "-C", root, "add", "-A", "papers"], check=True)
    subprocess.run(["git", "-C", root, "commit", "-q", "-m", f"{pack.doi}: release v{entry['version']}"], capture_output=True)
    subprocess.run(["git", "-C", root, "tag", "-f", tag], check=True, capture_output=True)
    p = subprocess.run(["git", "-C", root, "push", "-q", "origin", "main", tag], capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"git push failed: {p.stderr[-400:]}")
    zpath = release_dir(reg, pack, entry["version"]) / entry["zip"]
    notes = f"RunPapers pack for {pack.title} (DOI {pack.doi}), version {entry['version']}."
    r = subprocess.run(["gh", "release", "create", tag, str(zpath), "--title", f"{pack.doi} v{entry['version']}: {pack.title}"[:250], "--notes", notes],
                       cwd=root, capture_output=True, text=True)
    if r.returncode != 0 and "already exists" not in r.stderr:
        raise SystemExit(f"gh release failed: {r.stderr[-400:]}")
    out = {"tag": tag, "url": (r.stdout.strip() or None)}
    _mark(pack, entry["version"], "github", out)
    return out


def github_setup(reg, repo):
    """Create the public repository (repo = 'org/name'), add it as origin, push main, turn on Pages (Actions)."""
    root = str(reg.root)
    bad = [f for f in prepublish_scan(reg) if f[0] == "error"]
    if bad:
        raise SystemExit("pre-publication scan failed; fix first: " + "; ".join(f"{a}: {c}" for _, a, c in bad[:5]))
    if subprocess.run(["gh", "repo", "view", repo], capture_output=True).returncode != 0:
        r = subprocess.run(["gh", "repo", "create", repo, "--public", "--description",
                            "Verified, agent-ready packs: reproduce published papers' figures and ask new questions with your own AI agent."],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"gh repo create failed: {r.stderr[-400:]}")
    url = f"https://github.com/{repo}.git"
    if subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True).returncode == 0:
        subprocess.run(["git", "-C", root, "remote", "set-url", "origin", url], check=True)
    else:
        subprocess.run(["git", "-C", root, "remote", "add", "origin", url], check=True)
    subprocess.run(["gh", "auth", "setup-git"], capture_output=True)
    p = subprocess.run(["git", "-C", root, "push", "-u", "origin", "main"], capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"git push failed: {p.stderr[-400:]}")
    subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/pages", "-f", "build_type=workflow"], capture_output=True)
    return {"repo": repo, "remote": url, "pages": f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/"}
