"""The registry: papers/<doi-prefix>/<doi-suffix>/ pack folders plus collections/*.toml (planned papers)."""
import hashlib
import json
import os
import tomllib
from pathlib import Path

from . import ids

SPEC = "runpapers/0.1"
PACK_FILE = "pack.toml"
SKIP_DIRS = {"verify", "out", "__pycache__", ".cache", "data", "analyses", ".git"}
SKIP_FILES = {".DS_Store"}


def find_root(start=None):
    """The registry root: $RUNPAPERS_HOME, else the nearest parent holding runpapers.toml."""
    env = os.environ.get("RUNPAPERS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    p = Path(start or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / "runpapers.toml").is_file():
            return d
    return None


def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


class Pack:
    """One paper's pack: pack.toml (+ targets.toml, evals/questions.toml, SKILL.md, recipes/)."""

    def __init__(self, path):
        self.dir = Path(path)
        self.meta = load_toml(self.dir / PACK_FILE)
        tp = self.dir / "targets.toml"
        self.targets = load_toml(tp).get("target", []) if tp.is_file() else []
        ep = self.dir / "evals" / "questions.toml"
        self.evals = load_toml(ep).get("question", []) if ep.is_file() else []

    # -- identity
    @property
    def paper(self):
        return self.meta.get("paper", {})

    @property
    def doi(self):
        return ids.normalize_doi(self.paper.get("doi", ""))

    @property
    def title(self):
        return self.paper.get("title", "")

    @property
    def version(self):
        return self.meta.get("pack", {}).get("version", "0.0.0")

    @property
    def slug(self):
        """The DOI as a name (workspace folder, Hugging Face dataset, git tag, skill name): ids.doi_slug."""
        return ids.doi_slug(self.doi)

    def aliases(self):
        p = self.paper
        out = {("doi", self.doi)}
        if p.get("pmid"):
            out.add(("pmid", str(p["pmid"])))
        if p.get("pmcid"):
            out.add(("pmcid", str(p["pmcid"]).upper()))
        for d in [p.get("preprint_doi")] + list(p.get("other_dois", [])):
            if d:
                out.add(("doi", ids.normalize_doi(d)))
        return out

    # -- content
    @property
    def data(self):
        return self.meta.get("data", [])

    @property
    def recipes(self):
        return self.meta.get("recipes", [])

    def recipe(self, rid):
        for r in self.recipes:
            if r.get("id") == rid:
                return r
        raise KeyError(f"no recipe {rid!r} in {self.doi} (have: {', '.join(r.get('id', '?') for r in self.recipes)})")

    def data_entry(self, did):
        for d in self.data:
            if d.get("id") == did:
                return d
        raise KeyError(f"no data entry {did!r}")

    def targets_for(self, rid):
        return [t for t in self.targets if t.get("recipe") == rid]

    def files(self):
        """Pack content files (relative, sorted): what the pack hash covers and what `rp get` copies."""
        out = []
        for root, dirs, files in os.walk(self.dir):
            rel_root = Path(root).relative_to(self.dir)
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(files):
                if f in SKIP_FILES or f.endswith((".pyc", ".part")):
                    continue
                out.append(str(rel_root / f) if str(rel_root) != "." else f)
        return sorted(out)

    def content_hash(self):
        """sha256 over (path, file sha256) of the pack's content. Every badge is bound to this hash, so any change
        to recipes, targets, data, instructions or questions invalidates the badges until they are re-earned."""
        h = hashlib.sha256()
        for rel in self.files():
            h.update(rel.encode() + b"\0" + sha256_file(self.dir / rel).encode() + b"\n")
        return h.hexdigest()

    def lite_bytes(self):
        return sum(int(d.get("size", 0)) for d in self.data if d.get("tier", "lite") == "lite")

    def card(self):
        """Compact machine-readable profile (index.json, MCP search, meeting organizers)."""
        p = self.paper
        return {
            "doi": self.doi, "pmid": p.get("pmid"), "pmcid": p.get("pmcid"), "preprint_doi": p.get("preprint_doi"),
            "title": self.title, "first_author": p.get("first_author"), "senior_author": p.get("senior_author"),
            "journal": p.get("journal"), "year": p.get("year"), "slug": self.slug,
            "collections": p.get("collections", []), "version": self.version,
            "summary": self.meta.get("pack", {}).get("summary", ""),
            "profile": self.meta.get("profile", {}),
            "recipes": [{"id": r["id"], "title": r.get("title", ""), "panel": r.get("panel", ""), "tier": r.get("tier", "lite")}
                        for r in self.recipes],
            "lite_bytes": self.lite_bytes(),
            "questions": [q.get("ask") for q in self.evals if q.get("public", True)][:8],
        }


class Registry:
    def __init__(self, root=None):
        r = Path(root) if root else find_root()
        if r is None:
            raise SystemExit("no RunPapers registry here (no runpapers.toml in this folder or its parents; "
                             "set RUNPAPERS_HOME, or use `rp get` to work with a published pack)")
        self.root = r.resolve()
        self.papers = self.root / "papers"
        self.config = load_toml(self.root / "runpapers.toml") if (self.root / "runpapers.toml").is_file() else {}

    def packs(self):
        out = []
        if self.papers.is_dir():
            for pf in sorted(self.papers.glob(f"*/*/{PACK_FILE}")):
                out.append(Pack(pf.parent))
        return out

    def pack_dir(self, doi):
        return self.papers / ids.doi_relpath(doi)

    def collections(self):
        out = {}
        cd = self.root / "collections"
        for f in sorted(cd.glob("*.toml")) if cd.is_dir() else []:
            c = load_toml(f)
            c["slug"] = f.stem
            out[f.stem] = c
        return out

    def planned(self):
        """Papers listed in a collection, keyed by DOI, with their collection slug."""
        out = {}
        for slug, c in self.collections().items():
            for p in c.get("paper", []):
                d = ids.normalize_doi(p["doi"])
                out[d] = {**p, "doi": d, "collection": slug}
        return out

    def resolve(self, ident):
        """Any id (DOI, PMID, PMCID, URL, preprint DOI) -> canonical DOI, using packs then collections. None if unknown."""
        kind, val = ids.parse_id(ident)
        for pk in self.packs():
            if (kind, val) in pk.aliases():
                return pk.doi
        for d, p in self.planned().items():
            al = {("doi", d)}
            if p.get("pmid"):
                al.add(("pmid", str(p["pmid"])))
            if p.get("pmcid"):
                al.add(("pmcid", str(p["pmcid"]).upper()))
            if p.get("preprint_doi"):
                al.add(("doi", ids.normalize_doi(p["preprint_doi"])))
            if (kind, val) in al:
                return d
        return val if kind == "doi" else None

    def pack(self, ident):
        doi = self.resolve(ident)
        if not doi:
            raise SystemExit(f"unknown paper {ident!r}: no pack or collection entry has this id (try `rp resolve {ident}`)")
        d = self.pack_dir(doi)
        if not (d / PACK_FILE).is_file():
            raise SystemExit(f"{doi}: no pack yet" + (" (planned in a collection; scaffold it with `rp new " + doi + "`)"
                                                       if doi in self.planned() else ""))
        return Pack(d)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=False) + "\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default
