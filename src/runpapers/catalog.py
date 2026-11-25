"""Unified read/request layer over either a local RunPapers Registry or a published static site.

Used by `rp search`, `rp mcp`, and `rp meeting` so every feature works both inside a contributor's git
checkout and standalone via `uvx runpapers` against `index.json` + SHA-256-verified `pack.json` files."""
import hashlib
import json
import os
import re
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

from . import DEFAULT_BASE, data, ids, newpack, requests_log, verify, vocab, workspace
from .registry import Registry, find_root, read_json, recipe_needs_from_meta, sha256_file, write_json

INDEX_TTL_SECONDS = 3600


def _config_dir():
    return Path(os.environ.get("RUNPAPERS_CONFIG", "~/.config/runpapers")).expanduser()


def _safe_shipped_relpath(relpath):
    """Validate a pack-relative path; blocks traversal, absolute paths, verify/, and held-out evals/."""
    s = str(relpath or "").strip()
    if not s or s.startswith(("/", "\\")) or "\\" in s:
        raise PermissionError(f"disallowed pack path: {relpath!r}")
    parts = Path(s).parts
    if not parts or ".." in parts or "." in parts:
        raise PermissionError(f"unsafe path traversal: {relpath!r}")
    norm = "/".join(parts)
    if not workspace.shipped(norm) or norm.startswith("verify/"):
        raise PermissionError(f"path {norm!r} is held out and never exposed to agents or workspaces")
    return norm


def parse_skill_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text or "", re.S)
    out = {"name": "", "description": ""}
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            if k in out:
                out[k] = v.strip().strip("\"'")
    return out


def extract_markdown_section(text, heading_query):
    """Extract one `## Heading` section (case-insensitive substring match) from SKILL.md."""
    q = (heading_query or "").strip().lstrip("#").strip().lower()
    if not q:
        return text
    lines = (text or "").splitlines()
    sections = []
    cur_title, cur_lines = None, []
    for ln in lines:
        if ln.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, "\n".join(cur_lines).strip() + "\n"))
            cur_title, cur_lines = ln[3:].strip(), [ln]
        elif cur_title is not None:
            cur_lines.append(ln)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_lines).strip() + "\n"))
    for title, body in sections:
        if q in title.lower():
            return body
    avail = ", ".join(t for t, _ in sections) or "none"
    raise KeyError(f"section {heading_query!r} not found in SKILL.md (available: {avail})")


def _verification_warning(stage, badges, status=None):
    if status == "available" and not badges and not stage:
        return None
    runs_state = (badges or {}).get("runs", "none")
    if runs_state == "pass":
        return None
    if runs_state == "stale":
        return "Pack content changed since its last L1 run (`runs` badge is stale); re-verify before relying on outputs."
    return f"Pack is at stage {stage!r} (`runs` badge: {runs_state}); it has not passed automatic L1 target checks yet."


def _published_at(pack):
    from .release import current
    h = pack.content_hash()
    rel_entry = current(pack)
    if rel_entry:
        pub = rel_entry.get("published") or {}
        pub_times = sorted(
            info["at"] for tgt, info in pub.items()
            if tgt in verify.PUBLIC_TARGETS and isinstance(info, dict) and info.get("at")
        )
        if pub_times:
            return pub_times[0]
        if rel_entry.get("built"):
            return rel_entry["built"]
    l1 = verify.record(pack, "l1") or {}
    if l1.get("pack_hash") == h and l1.get("at"):
        return l1["at"]
    return None


def _planned_entry(doi, p, votes=0, repo="runpapers/runpapers", issue_url=None):
    cols = p.get("collections") or ([p["collection"]] if p.get("collection") else [])
    pub_status = p.get("status") if p.get("status") in ("requested", "in_progress", "not_possible") else "requested"
    return {
        "doi": doi,
        "pmid": p.get("pmid"),
        "pmcid": p.get("pmcid"),
        "preprint_doi": p.get("preprint_doi"),
        "other_dois": list(p.get("other_dois") or []),
        "title": p.get("title") or doi,
        "first_author": p.get("first_author") or "",
        "senior_author": p.get("senior_author") or "",
        "journal": p.get("journal") or "",
        "year": p.get("year"),
        "slug": ids.doi_slug(doi),
        "collections": cols,
        "version": None,
        "pack_hash": None,
        "summary": p.get("summary") or "",
        "tags": vocab.normalize_tags(p.get("tags")),
        "profile": {},
        "recipes": [],
        "data_bytes": 0,
        "questions": [],
        "stage": "planned",
        "status": pub_status,
        "status_reason": p.get("status_reason") if pub_status == "not_possible" else None,
        "badges": {},
        "data_terms": [],
        "packed": False,
        "votes": int(votes or 0),
        "issue_url": issue_url or p.get("issue_url") or requests_log.issue_url(repo, doi),
        "published_at": None,
        "usage": None,
    }


def _standalone_request(doi, note="", by="local:mcp", title=None, github_repo="runpapers/runpapers", existing_issue=None):
    log_file = _config_dir() / "requests.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    evs = [json.loads(ln) for ln in log_file.read_text().splitlines() if ln.strip()] if log_file.is_file() else []
    already_voter = any(e.get("doi") == doi and e.get("by") == by for e in evs)
    has_req = any(e.get("doi") == doi and e.get("type") == "request" for e in evs)
    if already_voter:
        new = False
    else:
        ev = {"type": "vote" if has_req else "request", "doi": doi, "by": by, "at": verify.now()}
        if not has_req:
            ev["note"] = note
            if title:
                ev["title"] = title
        with open(log_file, "a") as f:
            f.write(json.dumps(ev, sort_keys=True) + "\n")
        evs.append(ev)
        new = True
    votes = len({e.get("by") for e in evs if e.get("doi") == doi})
    return {
        "doi": doi,
        "new": new,
        "votes": votes,
        "mode": "standalone",
        "log_path": str(log_file),
        "issue_url": existing_issue or requests_log.issue_url(github_repo, doi, note),
        "existing_issue": bool(existing_issue),
    }


class _BaseCatalog:
    source_str = ""
    github_repo = "runpapers/runpapers"

    def vocab(self):
        return vocab.load()

    def resolve_known(self, ident):
        kind, val = ids.parse_id(ident)
        for e in self.entries(include_planned=True):
            aliases = {("doi", e["doi"])}
            if e.get("pmid"):
                aliases.add(("pmid", str(e["pmid"])))
            if e.get("pmcid"):
                aliases.add(("pmcid", str(e["pmcid"]).upper()))
            for d in [e.get("preprint_doi"), *(e.get("other_dois") or [])]:
                if d:
                    try:
                        aliases.add(("doi", ids.normalize_doi(d)))
                    except ids.IdError:
                        pass
            if (kind, val) in aliases:
                return e["doi"]
        return None

    def get_skill(self, ident, section=None, reference=None):
        det = self.paper_detail(ident)
        if not det.get("packed"):
            raise ValueError(f"{det['doi']} is planned and has no pack or SKILL.md yet")
        doi = det["doi"]
        skill_raw = self.read_pack_file(doi, "SKILL.md")
        fm = parse_skill_frontmatter(skill_raw)
        ref_rel = None
        if reference:
            raw_ref = str(reference).strip()
            if not raw_ref or raw_ref.startswith(("/", "\\")) or "\\" in raw_ref or ".." in Path(raw_ref).parts:
                raise PermissionError(f"unsafe reference path: {reference!r}")
            if not raw_ref.startswith("references/"):
                if "/" in raw_ref:
                    raise PermissionError(f"reference must live inside references/: {reference!r}")
                raw_ref = f"references/{raw_ref}"
            ref_rel = _safe_shipped_relpath(raw_ref)
            if not ref_rel.startswith("references/"):
                raise PermissionError(f"reference must live inside references/: {reference!r}")
            content = self.read_pack_file(doi, ref_rel)
        elif section:
            content = extract_markdown_section(skill_raw, section)
        else:
            content = skill_raw
        return {
            "doi": doi,
            "slug": det["slug"],
            "title": det["title"],
            "skill_name": fm["name"] or f"runpapers-{det['slug']}",
            "description": fm["description"] or det.get("summary", ""),
            "version": det["version"],
            "pack_hash": det["pack_hash"],
            "stage": det["stage"],
            "badges": det["badges"],
            "verification_warning": det["verification_warning"],
            "data_terms": det["data_terms"],
            "section": section,
            "reference": ref_rel,
            "content_markdown": content,
            "available_references": det["available_references"],
            "workspace_command": det["workspace_command"],
        }


class LocalCatalog(_BaseCatalog):
    def __init__(self, reg):
        self.reg = reg
        self.source_str = str(reg.root)
        self.github_repo = reg.config.get("publish", {}).get("github_repo", "runpapers/runpapers")

    def vocab(self):
        return vocab.load(root=self.reg.root)

    def entries(self, include_planned=True):
        req_rows = requests_log.summary(self.reg)
        reqs = {r["doi"]: r["votes"] for r in req_rows}
        req_issues = {r["doi"]: r.get("issue") for r in req_rows if r.get("issue")}
        out = []
        seen_dois = set()
        for pk in self.reg.packs():
            st = verify.status(pk)
            terms = sorted({d.get("license", "").strip() for d in pk.data if d.get("license", "").strip()})
            seen_dois.add(pk.doi)
            out.append({
                **pk.card(),
                "other_dois": list(pk.paper.get("other_dois") or []),
                "pack_hash": pk.content_hash()[:12],
                "stage": st["stage"],
                "status": "available",
                "status_reason": None,
                "badges": st["badges"],
                "data_terms": terms,
                "packed": True,
                "votes": reqs.get(pk.doi, 0),
                "issue_url": req_issues.get(pk.doi),
                "published_at": _published_at(pk),
                "usage": None,
            })
        if include_planned:
            for d, p in self.reg.planned().items():
                if d not in seen_dois:
                    seen_dois.add(d)
                    out.append(_planned_entry(d, p, votes=reqs.get(d, 0), repo=self.github_repo, issue_url=req_issues.get(d)))
            for r in req_rows:
                d = r["doi"]
                if d not in seen_dois:
                    seen_dois.add(d)
                    out.append(_planned_entry(d, {"title": r.get("title") or d}, votes=r.get("votes", 0),
                                              repo=self.github_repo, issue_url=r.get("issue")))
        return out

    def paper_detail(self, ident):
        doi = self.resolve_known(ident)
        if not doi:
            raise KeyError(f"unknown paper {ident!r}: not in packs or planned collections")
        req_rows = requests_log.summary(self.reg)
        reqs = {r["doi"]: r["votes"] for r in req_rows}
        req_by_doi = {r["doi"]: r for r in req_rows}
        pdir = self.reg.pack_dir(doi)
        if not (pdir / "pack.toml").is_file():
            planned_map = self.reg.planned()
            req_row = req_by_doi.get(doi) or {}
            p = planned_map.get(doi) or {"title": req_row.get("title") or doi}
            e = _planned_entry(doi, p, votes=reqs.get(doi, 0), repo=self.github_repo, issue_url=req_row.get("issue"))
            return {**e, "verification_warning": "Not packed yet (planned).",
                    "request_hint": f"Use request_paper(id={doi!r}) or `rp request {doi}` to vote for this paper."}
        pk = self.reg.pack(doi)
        st = verify.status(pk)
        terms = sorted({d.get("license", "").strip() for d in pk.data if d.get("license", "").strip()})
        refs = [f for f in pk.files() if f.startswith("references/") and workspace.shipped(f)]
        return {
            **pk.card(),
            "pack_hash": pk.content_hash()[:12],
            "stage": st["stage"],
            "status": "available",
            "status_reason": None,
            "next": st["next"],
            "badges": st["badges"],
            "verification_warning": _verification_warning(st["stage"], st["badges"]),
            "data": pk.data,
            "data_terms": terms,
            "available_references": refs,
            "workspace_command": f"uvx runpapers get {doi}",
            "packed": True,
            "votes": reqs.get(doi, 0),
            "issue_url": (req_by_doi.get(doi) or {}).get("issue"),
            "published_at": _published_at(pk),
            "usage": None,
        }

    def list_recipes(self, ident, max_memory_gb=None, gpu=None, include_targets=True):
        det = self.paper_detail(ident)
        if not det.get("packed"):
            raise ValueError(f"{det['doi']} is planned and has no recipes yet")
        pk = self.reg.pack(det["doi"])
        st = verify.status(pk)
        l1_rec = (st.get("l1") or {}).get("recipes") or {}
        rows = []
        for r in pk.recipes:
            nd = pk.recipe_needs(r)
            if max_memory_gb is not None and nd["memory_gb"] > float(max_memory_gb):
                continue
            if gpu is not None and nd["gpu"] != bool(gpu):
                continue
            rid = r["id"]
            item = {
                "id": rid,
                "panel": r.get("panel", ""),
                "title": r.get("title", ""),
                "script": r.get("script", ""),
                "data": nd["data"],
                "data_bytes": nd["data_bytes"],
                "memory_gb": nd["memory_gb"],
                "gpu": nd["gpu"],
                "minutes": nd["minutes"],
                "needs": {"memory_gb": nd["memory_gb"], "gpu": nd["gpu"], "minutes": nd["minutes"]},
                "l1_pass": (l1_rec.get(rid) or {}).get("pass"),
                "run_command": f"rp run {pk.doi} {rid}",
            }
            if include_targets:
                item["targets"] = pk.targets_for(rid)
            rows.append(item)
        return {"doi": pk.doi, "slug": pk.slug, "stage": st["stage"], "badges": st["badges"], "recipes": rows}

    def read_pack_file(self, ident, relpath):
        norm = _safe_shipped_relpath(relpath)
        doi = self.resolve_known(ident) or ids.normalize_doi(ident)
        pk = self.reg.pack(doi)
        if norm not in pk.files():
            raise FileNotFoundError(f"{norm!r} not found in pack {pk.doi}")
        return (pk.dir / norm).read_text(encoding="utf-8")

    def request_paper(self, ident, note="", by="local:mcp", resolve_online=False):
        doi = self.resolve_known(ident)
        title = None
        if not doi:
            kind, val = ids.parse_id(ident)
            if kind == "doi":
                doi = val
            elif resolve_online:
                meta = newpack.resolve_online(ident)
                doi, title = meta.get("doi"), meta.get("title")
                if not doi:
                    raise ValueError(f"could not resolve {ident!r} online to a DOI")
            else:
                raise ValueError(f"{ident!r} is not in the local catalog; pass a DOI or set resolve_online=true")
        res = requests_log.request(self.reg, doi, note=note, by=by, title=title)
        votes = next((r["votes"] for r in requests_log.summary(self.reg) if r["doi"] == doi), 1)
        issue = next((r.get("issue") for r in requests_log.summary(self.reg) if r["doi"] == doi and r.get("issue")), None)
        return {
            **res,
            "votes": votes,
            "mode": "registry",
            "log_path": str(requests_log.log_path(self.reg)),
            "issue_url": issue or requests_log.issue_url(self.github_repo, doi, note),
            "existing_issue": bool(issue),
        }


class RemoteCatalog(_BaseCatalog):
    def __init__(self, base_url, cache_dir=None, ttl=INDEX_TTL_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.source_str = self.base_url
        key = hashlib.sha256(self.base_url.encode()).hexdigest()[:12]
        self.cache_dir = Path(cache_dir or (data.cache_root() / "catalog" / key))
        self.ttl = ttl
        self._index = None

    def _fetch_bytes(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": data.UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    def vocab(self):
        return vocab.from_dict(self.index().get("vocab"))

    def index(self, refresh=False):
        if self._index is not None and not refresh:
            return self._index
        idx_file = self.cache_dir / "index.json"
        if not refresh and idx_file.is_file() and (time.time() - idx_file.stat().st_mtime) < self.ttl:
            self._index = json.loads(idx_file.read_text())
            self.github_repo = self._index.get("github_repo", "runpapers/runpapers")
            return self._index
        try:
            raw = self._fetch_bytes(f"{self.base_url}/index.json")
            obj = json.loads(raw)
            write_json(idx_file, obj)
            self._index = obj
            self.github_repo = obj.get("github_repo", "runpapers/runpapers")
            return obj
        except OSError:
            if idx_file.is_file():
                self._index = json.loads(idx_file.read_text())
                self.github_repo = self._index.get("github_repo", "runpapers/runpapers")
                return self._index
            raise

    def entries(self, include_planned=True):
        idx = self.index()
        req_rows = idx.get("requests") or []
        reqs = {r["doi"]: r.get("votes", 0) for r in req_rows}
        req_issues = {r["doi"]: r.get("issue") for r in req_rows if r.get("issue")}
        out = []
        seen_dois = set()
        for c in idx.get("papers") or []:
            seen_dois.add(c["doi"])
            pub_st = c.get("status", "available")
            inferred_stage = c.get("stage") or ("released" if c.get("release") else "runs")
            inferred_badges = dict(c.get("badges") or ({"runs": "pass"} if pub_st == "available" else {}))
            out.append({
                **c,
                "tags": vocab.normalize_tags(c.get("tags")),
                "other_dois": list(c.get("other_dois") or []),
                "pack_hash": c.get("pack_hash"),
                "status": pub_st,
                "status_reason": None,
                "stage": inferred_stage,
                "badges": inferred_badges,
                "data_terms": list(c.get("data_terms") or []),
                "packed": True,
                "votes": int(c.get("votes", reqs.get(c["doi"], 0)) or 0),
                "issue_url": c.get("issue_url") or req_issues.get(c["doi"]),
                "published_at": c.get("published_at"),
                "usage": c.get("usage"),
            })
        if include_planned:
            for p in idx.get("planned") or []:
                d = p["doi"]
                if d not in seen_dois:
                    seen_dois.add(d)
                    out.append(_planned_entry(d, p, votes=p.get("votes", reqs.get(d, 0)),
                                              repo=self.github_repo, issue_url=p.get("issue_url") or req_issues.get(d)))
            for r in req_rows:
                d = r["doi"]
                if d not in seen_dois:
                    seen_dois.add(d)
                    out.append(_planned_entry(d, {"title": r.get("title") or d}, votes=r.get("votes", 0),
                                              repo=self.github_repo, issue_url=r.get("issue")))
        return out

    def _pack_listing(self, doi):
        raw = self._fetch_bytes(f"{self.base_url}/{ids.page_path(doi)}/pack.json")
        return json.loads(raw)

    def read_pack_file(self, ident, relpath):
        norm = _safe_shipped_relpath(relpath)
        doi = self.resolve_known(ident) or ids.normalize_doi(ident)
        listing = self._pack_listing(doi)
        hit = next((f for f in listing.get("files") or [] if f.get("path") == norm), None)
        if not hit:
            raise FileNotFoundError(f"{norm!r} not found in remote pack {doi}")
        want_sha = hit["sha256"]
        p_hash = listing.get("pack_hash", "unknown")[:16]
        cached = self.cache_dir / "packs" / ids.doi_relpath(doi) / p_hash / norm
        if cached.is_file() and sha256_file(cached) == want_sha:
            return cached.read_text(encoding="utf-8")
        raw = self._fetch_bytes(f"{self.base_url}/{ids.page_path(doi)}/pack/{norm}")
        if hashlib.sha256(raw).hexdigest() != want_sha:
            raise ValueError(f"{norm}: SHA-256 checksum mismatch against pack.json (corrupted or tampered file)")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw)
        return raw.decode("utf-8")

    def paper_detail(self, ident):
        doi = self.resolve_known(ident)
        if not doi:
            raise KeyError(f"unknown paper {ident!r} at {self.base_url}")
        entry = next(e for e in self.entries(include_planned=True) if e["doi"] == doi)
        if not entry.get("packed"):
            return {**entry, "verification_warning": "Not packed yet (planned).",
                    "request_hint": f"Use request_paper(id={doi!r}) or `rp request {doi}` to vote for this paper."}
        listing = self._pack_listing(doi)
        pack_toml = tomllib.loads(self.read_pack_file(doi, "pack.toml"))
        data_list = pack_toml.get("data", [])
        terms = sorted({d.get("license", "").strip() for d in data_list if d.get("license", "").strip()})
        refs = [f["path"] for f in listing.get("files", [])
                if f.get("path", "").startswith("references/") and workspace.shipped(f["path"])]
        src_arg = f" --source {self.base_url}" if self.base_url != DEFAULT_BASE else ""
        return {
            **entry,
            "pack_hash": listing.get("pack_hash", "")[:12],
            "verification_warning": _verification_warning(entry.get("stage"), entry.get("badges"), status=entry.get("status")),
            "data": data_list,
            "data_terms": terms or entry.get("data_terms", []),
            "available_references": sorted(refs),
            "workspace_command": f"uvx runpapers get {doi}{src_arg}",
        }

    def list_recipes(self, ident, max_memory_gb=None, gpu=None, include_targets=True):
        det = self.paper_detail(ident)
        if not det.get("packed"):
            raise ValueError(f"{det['doi']} is planned and has no recipes yet")
        doi = det["doi"]
        pack_toml = tomllib.loads(self.read_pack_file(doi, "pack.toml"))
        targets_all = tomllib.loads(self.read_pack_file(doi, "targets.toml")).get("target", []) if include_targets else []
        data_list = pack_toml.get("data", [])
        recipes_raw = pack_toml.get("recipes") or pack_toml.get("recipe", [])
        rows = []
        det_badges = det.get("badges") or {}
        l1_ok = True if (det.get("status") == "available" or det_badges.get("runs") == "pass") else None
        for r in recipes_raw:
            nd = recipe_needs_from_meta(r, data_list)
            if max_memory_gb is not None and nd["memory_gb"] > float(max_memory_gb):
                continue
            if gpu is not None and nd["gpu"] != bool(gpu):
                continue
            rid = r["id"]
            item = {
                "id": rid,
                "panel": r.get("panel", ""),
                "title": r.get("title", ""),
                "script": r.get("script", ""),
                "data": nd["data"],
                "data_bytes": nd["data_bytes"],
                "memory_gb": nd["memory_gb"],
                "gpu": nd["gpu"],
                "minutes": nd["minutes"],
                "needs": {"memory_gb": nd["memory_gb"], "gpu": nd["gpu"], "minutes": nd["minutes"]},
                "l1_pass": l1_ok,
                "run_command": f"rp run {doi} {rid}",
            }
            if include_targets:
                item["targets"] = [t for t in targets_all if t.get("recipe") == rid]
            rows.append(item)
        return {"doi": doi, "slug": det["slug"], "status": det.get("status", "available"),
                "stage": det.get("stage", "released"), "badges": det_badges, "recipes": rows}

    def request_paper(self, ident, note="", by="local:mcp", resolve_online=False):
        doi = self.resolve_known(ident)
        title = None
        if not doi:
            kind, val = ids.parse_id(ident)
            if kind == "doi":
                doi = val
            elif resolve_online:
                meta = newpack.resolve_online(ident)
                doi, title = meta.get("doi"), meta.get("title")
                if not doi:
                    raise ValueError(f"could not resolve {ident!r} online to a DOI")
            else:
                raise ValueError(f"{ident!r} is not in the catalog; pass a DOI or set resolve_online=true")
        else:
            title = next((e.get("title") for e in self.entries(include_planned=True) if e["doi"] == doi), None)
        issue = next((r.get("issue") for r in (self.index().get("requests") or []) if r.get("doi") == doi and r.get("issue")), None)
        return _standalone_request(doi, note=note, by=by, title=title, github_repo=self.github_repo, existing_issue=issue)


def open_catalog(source=None):
    """Open LocalCatalog when inside a registry (or given a local path), else RemoteCatalog."""
    if source:
        s = str(source)
        if s.startswith(("http://", "https://")):
            return RemoteCatalog(s)
        return LocalCatalog(Registry(s))
    root = find_root()
    if root is not None:
        return LocalCatalog(Registry(root))
    return RemoteCatalog(os.environ.get("RUNPAPERS_BASE", DEFAULT_BASE))
