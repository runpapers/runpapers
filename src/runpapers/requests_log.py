"""Paper requests and votes. The public channel is the GitHub repository: one issue per paper (the "Request a
paper" form, label `request`), and a vote is a thumbs-up on that issue. `rp requests --sync` takes a snapshot of those
issues (requests/github.json, not tracked; the website build makes a fresh one). Maintainers can also log requests
locally (requests/requests.jsonl). Both are counted together."""
import getpass
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import ids
from .registry import read_json, write_json
from .verify import now

GITHUB_FILE = "github.json"
ISSUE_FORM = "request-paper.yml"


def issue_url(repo, doi="", note=""):
    """Link to the pre-filled "Request a paper" form on GitHub."""
    q = {"template": ISSUE_FORM, "labels": "request", "title": f"Paper request: {doi}".strip()}
    if doi:
        q["doi"] = doi
    if note:
        q["why"] = note
    return f"https://github.com/{repo}/issues/new?" + urllib.parse.urlencode(q)


def _issue_ident(issue):
    """The DOI/PMID a request issue is about: the form's "DOI or PMID" field, else the title after "Paper request:"."""
    body = issue.get("body") or ""
    m = re.search(r"###\s*DOI or PMID\s*\n+\s*([^\n]+)", body)
    for cand in ((m.group(1) if m else ""), (issue.get("title") or "").split(":", 1)[-1]):
        cand = cand.strip().strip("`").strip()
        if cand and cand != "_No response_":
            return cand
    return None


def _get_json(url, token=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "runpapers"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return json.loads(r.read())


def sync_github(reg, repo=None, token=None, fetch=None, resolve_online=True):
    """Snapshot the public request issues (open and closed) with their thumbs-up counts into requests/github.json."""
    repo = repo or reg.config.get("publish", {}).get("github_repo", "runpapers/runpapers")
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    fetch = fetch or _get_json
    issues = []
    for page in range(1, 11):
        batch = fetch(f"https://api.github.com/repos/{repo}/issues?labels=request&state=all&per_page=100&page={page}", token)
        issues += [i for i in batch or [] if "pull_request" not in i]
        if not batch or len(batch) < 100:
            break
    rows = []
    for i in issues:
        ident = _issue_ident(i)
        doi = reg.resolve(ident) if ident else None
        if ident and not doi:
            kind, val = ids.parse_id(ident)
            if kind == "doi" and val.startswith("10."):
                doi = val
            elif resolve_online:
                try:
                    from .newpack import resolve_online as online
                    doi = online(ident).get("doi")
                except Exception:   # offline or unknown id: kept, shown as "needs a DOI"
                    doi = None
        rows.append({"number": i["number"], "url": i["html_url"], "ident": ident, "doi": doi, "state": i.get("state"),
                     "state_reason": i.get("state_reason"), "opened": i.get("created_at"),
                     "votes": 1 + int((i.get("reactions") or {}).get("+1", 0))})
    write_json(reg.root / "requests" / GITHUB_FILE, {"repo": repo, "synced": now(), "issues": rows})
    return rows


def log_path(reg):
    return reg.root / "requests" / "requests.jsonl"


def events(reg):
    p = log_path(reg)
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def append(reg, ev):
    p = log_path(reg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(ev, sort_keys=True) + "\n")


def who(by=None):
    return by or f"local:{getpass.getuser()}"


def request(reg, ident, note="", by=None, title=None):
    doi = reg.resolve(ident)
    if not doi:
        raise SystemExit(f"{ident}: can't turn this into a DOI offline; give the DOI (or run `rp resolve {ident} --online`)")
    by = who(by)
    if any(e["doi"] == doi and e["type"] == "request" for e in events(reg)):
        return vote(reg, doi, by)
    append(reg, {"type": "request", "doi": doi, "by": by, "at": now(), "note": note, "title": title or reg.planned().get(doi, {}).get("title")})
    return {"doi": doi, "new": True}


def vote(reg, ident, by=None):
    doi = reg.resolve(ident) or ids.normalize_doi(ident)
    by = who(by)
    if any(e["doi"] == doi and e["by"] == by for e in events(reg)):
        return {"doi": doi, "new": False, "note": "already counted"}
    append(reg, {"type": "vote", "doi": doi, "by": by, "at": now()})
    return {"doi": doi, "new": True}


def summary(reg):
    from .verify import status  # local import: verify imports nothing from here
    packs = {p.doi: p for p in reg.packs()}
    planned = reg.planned()
    agg = {}
    for e in events(reg):
        a = agg.setdefault(e["doi"], {"doi": e["doi"], "title": None, "voters": set(), "first": e["at"], "notes": []})
        a["voters"].add(e["by"])
        if e.get("title"):
            a["title"] = e["title"]
        if e.get("note"):
            a["notes"].append(e["note"])
    gh = read_json(reg.root / "requests" / GITHUB_FILE, {}) or {}
    for r in sorted(gh.get("issues", []), key=lambda r: r["number"]):
        if not r.get("doi") or r.get("state_reason") == "not_planned":
            continue
        a = agg.setdefault(r["doi"], {"doi": r["doi"], "title": None, "voters": set(), "first": r.get("opened") or now(), "notes": []})
        a["gh_votes"] = a.get("gh_votes", 0) + r["votes"]
        a.setdefault("issue", r["url"])
        a["first"] = min(a["first"], r.get("opened") or a["first"])
    out = []
    for d, a in agg.items():
        if d in packs:
            st = status(packs[d])["stage"]
            state = "live" if st in ("reproduces", "agent-tested", "released") else f"building ({st})"
        elif d in planned:
            state = "planned"
        else:
            state = "requested"
        out.append({"doi": d, "title": a["title"] or (packs[d].title if d in packs else planned.get(d, {}).get("title")),
                    "votes": len(a["voters"]) + a.get("gh_votes", 0), "first": a["first"], "status": state,
                    "notes": a["notes"][-3:], "issue": a.get("issue")})
    return sorted(out, key=lambda r: (-r["votes"], r["first"]))
