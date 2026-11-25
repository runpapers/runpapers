"""Paper requests and votes. Until the project is public this is an append-only local log
(requests/requests.jsonl); after launch each request becomes a GitHub issue and votes are its reactions."""
import getpass
import json
from pathlib import Path

from . import ids
from .verify import now


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
                    "votes": len(a["voters"]), "first": a["first"], "status": state, "notes": a["notes"][-3:]})
    return sorted(out, key=lambda r: (-r["votes"], r["first"]))
