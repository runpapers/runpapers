"""Controlled five-group tag vocabulary (`vocab/*.toml`): loader, validator, slug/label resolver, and synonym expander.

RunPapers uses exactly five tag groups (species, tissue_cell, data_type, disease, collection) with plain biologist
labels, optional `scientific_name` on species, and optional `synonyms` for search. No ontology CURIEs or parent-region
hierarchies are required or exposed."""
import difflib
import re
import tomllib
from pathlib import Path

GROUPS = ("species", "tissue_cell", "data_type", "disease", "collection")
GROUP_TITLES = {
    "species": "Species",
    "tissue_cell": "Tissue/cell",
    "data_type": "Data type",
    "disease": "Disease",
    "collection": "Collection",
}
SLUG_RX = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED_TERM_KEYS = frozenset({"slug", "label", "scientific_name", "synonyms"})
_REPO_VOCAB_DIR = Path(__file__).resolve().parents[2] / "vocab"
_PKG_VOCAB_DIR = Path(__file__).resolve().parent / "_vocab"
DEFAULT_VOCAB_DIR = _REPO_VOCAB_DIR if _REPO_VOCAB_DIR.is_dir() else _PKG_VOCAB_DIR


def empty_tags():
    return {g: [] for g in GROUPS}


def normalize_tags(raw):
    if not isinstance(raw, dict):
        return empty_tags()
    out = {}
    for g in GROUPS:
        vals = raw.get(g)
        clean = [str(v).strip() for v in vals if isinstance(v, str) and v.strip()] if isinstance(vals, list) else []
        out[g] = list(dict.fromkeys(clean))
    return out


class Vocab:
    """In-memory view of the five controlled vocabulary files."""

    def __init__(self, groups_map=None):
        self.groups = {g: list((groups_map or {}).get(g) or []) for g in GROUPS}
        self.by_label = {g: {} for g in GROUPS}
        self.by_slug = {g: {} for g in GROUPS}
        self._lookup = {g: {} for g in GROUPS}
        self._syn_slugs = {g: {} for g in GROUPS}
        self._synonym_sets = {}
        for g, terms in self.groups.items():
            for t in terms:
                self.by_label[g][t["label"]] = t
                self.by_slug[g][t["slug"]] = t
                aliases = [t["slug"], t["label"]]
                if t.get("scientific_name"):
                    aliases.append(t["scientific_name"])
                aliases.extend(t.get("synonyms") or [])
                lower_set = {a.strip().lower() for a in aliases if a and a.strip()}
                for low in lower_set:
                    self._lookup[g].setdefault(low, t)
                    self._syn_slugs[g].setdefault(low, set()).add(t["slug"])
                    self._synonym_sets.setdefault(low, set()).update(lower_set)
            # Prefer exact label / slug / scientific_name hits over shared synonyms (e.g. "NHP" shared by Macaque & Marmoset).
            for t in terms:
                self._lookup[g][t["slug"].lower()] = t
                self._lookup[g][t["label"].lower()] = t
                if t.get("scientific_name"):
                    self._lookup[g][t["scientific_name"].lower()] = t

    def has_label(self, group, label):
        return group in self.by_label and label in self.by_label[group]

    def resolve(self, group, value):
        """Resolve a slug, case-insensitive label, scientific_name, or unique/first synonym to its term dict."""
        if group not in self._lookup or not isinstance(value, str):
            return None
        q = value.strip()
        if not q:
            return None
        if q in self.by_label[group]:
            return self.by_label[group][q]
        if q in self.by_slug[group]:
            return self.by_slug[group][q]
        low = q.lower()
        if low in self._lookup[group]:
            return self._lookup[group][low]
        if low.endswith("s") and len(low) > 3 and low[:-1] in self._lookup[group]:
            return self._lookup[group][low[:-1]]
        return None

    def resolve_slug(self, group, value):
        t = self.resolve(group, value)
        return t["slug"] if t else None

    def resolve_label(self, group, value):
        t = self.resolve(group, value)
        return t["label"] if t else None

    def matching_slugs(self, group, value):
        """Return the set of canonical slugs in `group` matching `value` (exact slug/label/scientific_name first, else synonyms)."""
        if group not in self.groups or not isinstance(value, str):
            return set()
        q = value.strip()
        if not q:
            return set()
        low = q.lower()
        for t in self.groups[group]:
            prim = {t["slug"].lower(), t["label"].lower()}
            if t.get("scientific_name"):
                prim.add(t["scientific_name"].lower())
            if low in prim:
                return {t["slug"]}
        hits = set(self._syn_slugs[group].get(low, ()))
        if not hits and low.endswith("s") and len(low) > 3:
            hits = set(self._syn_slugs[group].get(low[:-1], ()))
        return hits

    def tag_slugs(self, tags):
        """Convert normalized 5-group `tags` into `{group: [slug, ...]}` preserving order without duplicates."""
        norm = normalize_tags(tags)
        out = {}
        for g in GROUPS:
            slugs = []
            for label in norm[g]:
                s = self.resolve_slug(g, label)
                if s:
                    slugs.append(s)
            out[g] = list(dict.fromkeys(slugs))
        return out

    def term_texts(self, group, value):
        """All search strings (label, slug, scientific_name, synonyms) associated with `value` in `group`."""
        if not isinstance(value, str) or not value.strip():
            return []
        vals = [value.strip()]
        for slug in sorted(self.matching_slugs(group, value)):
            t = self.by_slug[group].get(slug)
            if t:
                vals.extend([t["label"], t["slug"]])
                if t.get("scientific_name"):
                    vals.append(t["scientific_name"])
                vals.extend(t.get("synonyms") or [])
        return vals

    def suggest(self, group, bad_value):
        """Return the closest canonical label in `group` (via synonym/slug/scientific_name or fuzzy match), or None."""
        if group not in self._lookup or not isinstance(bad_value, str):
            return None
        q = bad_value.strip()
        if not q:
            return None
        direct = self.resolve(group, q)
        if direct:
            return direct["label"]
        matches = difflib.get_close_matches(q.lower(), list(self._lookup[group].keys()), n=1, cutoff=0.6)
        if matches:
            return self._lookup[group][matches[0]]["label"]
        return None

    def expand(self, text, group=None):
        """Expand `text` to all lowercased synonyms/scientific names/labels/slugs in `group` (or across all groups)."""
        q = (text or "").strip().lower()
        if not q:
            return set()
        out = {q}
        if group in self.groups:
            for t in self.groups[group]:
                names = {t["slug"].lower(), t["label"].lower(), *(s.lower() for s in (t.get("synonyms") or []))}
                if t.get("scientific_name"):
                    names.add(t["scientific_name"].lower())
                if q in names or (q.endswith("s") and len(q) > 3 and q[:-1] in names):
                    out.update(names)
            return out
        if q in self._synonym_sets:
            out.update(self._synonym_sets[q])
        if q.endswith("s") and len(q) > 3 and q[:-1] in self._synonym_sets:
            out.update(self._synonym_sets[q[:-1]])
        return out

    def to_dict(self):
        out = {}
        for g in GROUPS:
            rows = []
            for t in self.groups[g]:
                item = {"slug": t["slug"], "label": t["label"]}
                if t.get("scientific_name"):
                    item["scientific_name"] = t["scientific_name"]
                if t.get("synonyms"):
                    item["synonyms"] = list(t["synonyms"])
                rows.append(item)
            out[g] = rows
        return out


def from_dict(raw):
    """Hydrate a `Vocab` instance from an `index.json` or `search.json` `vocab` dictionary."""
    if not isinstance(raw, dict):
        return load()
    groups_map = {}
    for g in GROUPS:
        rows = []
        for t in raw.get(g) or []:
            if isinstance(t, dict) and t.get("slug") and t.get("label"):
                item = {
                    "slug": str(t["slug"]),
                    "label": str(t["label"]),
                    "synonyms": [str(s) for s in (t.get("synonyms") or []) if isinstance(s, str) and s.strip()],
                }
                if t.get("scientific_name"):
                    item["scientific_name"] = str(t["scientific_name"])
                rows.append(item)
        groups_map[g] = rows
    return Vocab(groups_map) if any(groups_map.values()) else load()


def validate_dir(vdir):
    """Load and validate `vocab/*.toml` from `vdir`. Returns `(Vocab, findings)`."""
    vdir = Path(vdir)
    findings = []
    add = lambda sev, code, msg: findings.append((sev, code, msg))
    if not vdir.is_dir():
        add("error", "vocab.missing", f"vocabulary folder missing: {vdir}")
        return Vocab(), findings

    for extra in sorted(vdir.glob("*.toml")):
        if extra.stem not in GROUPS:
            add("error", "vocab.group",
                f"vocab/{extra.name}: unknown tag group {extra.stem!r} (allowed: {', '.join(GROUPS)})")

    groups_map = {}
    for g in GROUPS:
        p = vdir / f"{g}.toml"
        if not p.is_file():
            add("error", "vocab.missing", f"vocab/{g}.toml missing")
            groups_map[g] = []
            continue
        try:
            with open(p, "rb") as fh:
                raw = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            add("error", "vocab.format", f"vocab/{g}.toml: invalid TOML ({exc})")
            groups_map[g] = []
            continue
        extra_top = set(raw) - {"terms"}
        if extra_top:
            add("error", "vocab.format", f"vocab/{g}.toml: unexpected top-level key(s) {sorted(extra_top)}")
        terms = raw.get("terms")
        if not isinstance(terms, list) or not terms:
            add("error", "vocab.empty", f"vocab/{g}.toml: must define a non-empty [[terms]] list")
            groups_map[g] = []
            continue
        seen_slugs, seen_labels = set(), set()
        clean_terms = []
        for idx, t in enumerate(terms):
            where = f"vocab/{g}.toml term #{idx + 1}"
            if not isinstance(t, dict):
                add("error", "vocab.format", f"{where}: must be a table")
                continue
            allowed_keys = ALLOWED_TERM_KEYS if g == "species" else (ALLOWED_TERM_KEYS - {"scientific_name"})
            bad_keys = set(t) - allowed_keys
            if bad_keys:
                add("error", "vocab.keys",
                    f"{where}: unsupported key(s) {sorted(bad_keys)} (allowed: {sorted(allowed_keys)})")
            slug = t.get("slug")
            label = t.get("label")
            if not isinstance(slug, str) or not SLUG_RX.fullmatch(slug):
                add("error", "vocab.slug", f"{where}: slug {slug!r} must match [a-z0-9]+(-[a-z0-9]+)*")
                continue
            if slug in seen_slugs:
                add("error", "vocab.slug", f"vocab/{g}.toml: duplicate slug {slug!r}")
                continue
            seen_slugs.add(slug)
            if not isinstance(label, str) or not label.strip() or label != label.strip():
                add("error", "vocab.label", f"{where} ({slug}): label must be a non-empty trimmed string")
                continue
            if label.lower() in seen_labels:
                add("error", "vocab.label", f"vocab/{g}.toml: duplicate label {label!r}")
                continue
            seen_labels.add(label.lower())
            sci = t.get("scientific_name")
            if sci is not None and (not isinstance(sci, str) or not sci.strip()):
                add("error", "vocab.scientific_name", f"{where} ({slug}): scientific_name must be a non-empty string")
                sci = None
            syns = t.get("synonyms", [])
            if not isinstance(syns, list) or any(not isinstance(s, str) or not s.strip() for s in syns):
                add("error", "vocab.synonyms", f"{where} ({slug}): synonyms must be a list of non-empty strings")
                syns = []
            entry = {"slug": slug, "label": label, "synonyms": list(syns)}
            if sci:
                entry["scientific_name"] = sci.strip()
            clean_terms.append(entry)
        groups_map[g] = clean_terms
    return Vocab(groups_map), findings


def resolve_vocab_dir(root=None, vocab_dir=None):
    if vocab_dir is not None:
        return Path(vocab_dir)
    if root is not None and (Path(root) / "vocab").exists():
        return Path(root) / "vocab"
    return DEFAULT_VOCAB_DIR


def load_for_root(root=None, vocab_dir=None):
    return validate_dir(resolve_vocab_dir(root=root, vocab_dir=vocab_dir))


def load(root=None, vocab_dir=None):
    voc, _ = load_for_root(root=root, vocab_dir=vocab_dir)
    return voc
