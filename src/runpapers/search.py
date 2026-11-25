"""Five-group tag search, vocabulary synonym expansion, and request-aware ranking.

Shared across `rp search`, MCP `search_papers`, `rp meeting`, and `papers/search.json` so CLI, MCP, and
the website return identical matching DOIs and rank available packs ahead of requested papers."""
import functools
import re

from . import ids, requests_log, vocab
from .verify import STAGES

STAGE_RANK = {s: i for i, s in enumerate(STAGES)}
PUBLIC_STATUSES = ("available", "requested", "in_progress", "not_possible")

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "across", "about", "between", "by", "compare", "data",
    "do", "does", "for", "from", "how", "in", "into", "is", "of", "on", "or", "paper", "papers",
    "show", "study", "studies", "that", "the", "their", "to", "using", "what", "which", "with",
})

_ID_PREFIX_RX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|https?://pubmed\.ncbi\.nlm\.nih\.gov/|doi:|pmid:)", re.I)


def _default_vocab(voc=None):
    return voc if isinstance(voc, vocab.Vocab) else vocab.load()


def expand_term(term, voc=None):
    v = _default_vocab(voc)
    return v.expand(term)


def tokenize(text):
    raw = re.findall(r"[a-z0-9][a-z0-9._-]*", (text or "").lower())
    filtered = [t for t in raw if t not in _STOPWORDS]
    return filtered if filtered else raw


def query_tokens(query):
    """Whitespace tokens normalized for `search_text` matching (preserving DOI slashes and gene/assay hyphens)."""
    out = []
    for raw in (query or "").strip().split():
        tok = _ID_PREFIX_RX.sub("", raw.strip()).strip(",;()[]{}\"'").lower()
        if tok:
            out.append(tok)
    return out


def public_status(entry):
    st = entry.get("status")
    if st in PUBLIC_STATUSES:
        return st
    if entry.get("packed", False):
        return "available"
    raw_stage = entry.get("stage", "planned")
    if raw_stage and raw_stage != "planned":
        return "available"
    return "requested"


def entry_year(entry):
    try:
        return int(entry.get("year") or 0)
    except (TypeError, ValueError):
        return 0


def _as_list(val):
    if val is None:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    return [s] if s else []


def entry_tag_slugs(entry, voc=None):
    """Return `{group: [slug, ...]}` for `entry`, falling back to `[profile]` only when `tags` is completely empty."""
    v = _default_vocab(voc)
    if isinstance(entry.get("tag_slugs"), dict) and set(entry["tag_slugs"]) >= set(vocab.GROUPS):
        return {g: list(entry["tag_slugs"].get(g) or []) for g in vocab.GROUPS}
    tags = vocab.normalize_tags(entry.get("tags"))
    slugs = v.tag_slugs(tags)
    has_explicit_tags = any(tags[g] for g in vocab.GROUPS)
    if not has_explicit_tags:
        prof = entry.get("profile") or {}
        for g, pkey in (("species", "species"), ("tissue_cell", "tissues"), ("data_type", "assays")):
            extra = []
            for raw in prof.get(pkey) or []:
                extra.extend(sorted(v.matching_slugs(g, str(raw))))
            if extra:
                slugs[g] = list(dict.fromkeys([*slugs[g], *extra]))
    # Collection slugs from `collections = ["bican-2026"]` or `collection = "bican-2026"` also resolve cleanly.
    col_extra = []
    for raw_col in [*(entry.get("collections") or []), *([entry["collection"]] if isinstance(entry.get("collection"), str) else [])]:
        matched = v.matching_slugs("collection", str(raw_col))
        if matched:
            col_extra.extend(sorted(matched))
        elif str(raw_col).strip():
            col_extra.append(str(raw_col).strip().lower())
    if col_extra:
        slugs["collection"] = list(dict.fromkeys([*slugs["collection"], *col_extra]))
    return slugs


def build_search_text(entry, voc=None):
    """Pre-lowercased searchable text covering metadata, IDs, `[profile]` genes/cell types, and `vocab` synonyms."""
    v = _default_vocab(voc)
    tags = vocab.normalize_tags(entry.get("tags"))
    prof = entry.get("profile") or {}
    parts = [
        entry.get("title"),
        entry.get("first_author"),
        entry.get("senior_author"),
        entry.get("journal"),
        entry.get("year"),
        entry.get("doi"),
        entry.get("pmid"),
        entry.get("pmcid"),
        entry.get("preprint_doi"),
        *(entry.get("other_dois") or []),
        entry.get("slug"),
        entry.get("summary"),
        *(entry.get("collections") or []),
        *([entry["collection"]] if isinstance(entry.get("collection"), str) else []),
        *(prof.get("key_genes") or []),
        *(prof.get("cell_types") or []),
    ]
    for r in entry.get("recipes") or []:
        if isinstance(r, dict):
            parts.extend([r.get("id"), r.get("panel"), r.get("title")])
    for panel in entry.get("panels") or []:
        parts.append(panel)
    for g in vocab.GROUPS:
        for label in tags[g]:
            parts.extend(v.term_texts(g, label))
    for g, pkey in (("species", "species"), ("tissue_cell", "tissues"), ("data_type", "assays")):
        for raw in prof.get(pkey) or []:
            parts.extend(v.term_texts(g, str(raw)))
    seen = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip().lower()
        if s:
            seen.append(s)
    return " ".join(dict.fromkeys(seen))


@functools.lru_cache(maxsize=2048)
def _term_rx(v):
    # Short words/acronyms (<= 4 chars), pure numbers, and DOIs require whole-token boundaries on both sides;
    # longer terms/phrases (>= 5 chars) require a left word boundary and allow word suffixes (plurals/possessives).
    if len(v) <= 4 or v.isdigit() or "/" in v:
        return re.compile(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])")
    return re.compile(rf"(?<![a-z0-9]){re.escape(v)}")


def _term_in_text(v, text):
    if not v or not text:
        return False
    return bool(_term_rx(v).search(text))


def _value_matches(variants, haystacks, exact_only=False):
    for h in haystacks:
        hl = str(h or "").lower()
        if not hl:
            continue
        if exact_only:
            if hl in variants:
                return True
            tokens = set(re.findall(r"[a-z0-9][a-z0-9._-]*", hl))
            if tokens & variants:
                return True
        else:
            for v in variants:
                if _term_in_text(v, hl):
                    return True
    return False


def _profile_facet_ok(wanted_list, entry_vals, voc=None, exact_only=False):
    wanted = _as_list(wanted_list)
    if not wanted:
        return True
    vals = [str(v) for v in (entry_vals or []) if v]
    if not vals:
        return False
    return any(_value_matches(expand_term(w, voc=voc), vals, exact_only=exact_only) for w in wanted)


def _group_filter_ok(group, wanted_list, tag_slugs_map, voc):
    """OR within `group`: true if `wanted_list` is empty or any wanted value's slug is in `tag_slugs_map[group]`."""
    wanted = _as_list(wanted_list)
    if not wanted:
        return True
    have = set(tag_slugs_map.get(group) or [])
    if not have:
        return False
    target_slugs = set()
    for w in wanted:
        matched = voc.matching_slugs(group, w)
        if matched:
            target_slugs.update(matched)
        elif group == "collection":
            target_slugs.add(w.strip().lower())
        else:
            target_slugs.add(f"__unknown__:{w.strip().lower()}")
    return bool(have & target_slugs)


def _id_match(entry, query):
    q = (query or "").strip()
    if not q:
        return False
    try:
        kind, val = ids.parse_id(q)
    except ids.IdError:
        return False
    if kind == "doi":
        dois = {entry.get("doi", "")}
        if entry.get("preprint_doi"):
            try:
                dois.add(ids.normalize_doi(entry["preprint_doi"]))
            except ids.IdError:
                pass
        for d in entry.get("other_dois") or []:
            try:
                dois.add(ids.normalize_doi(d))
            except ids.IdError:
                pass
        return val in dois
    if kind == "pmid":
        return str(entry.get("pmid") or "") == val
    if kind == "pmcid":
        return str(entry.get("pmcid") or "").upper() == val.upper()
    return False


def _token_in_search_text(tok, search_text, voc):
    if _term_in_text(tok, search_text):
        return True
    if tok.endswith("s") and len(tok) >= 4 and _term_in_text(tok[:-1], search_text):
        return True
    for variant in voc.expand(tok):
        if _term_in_text(variant, search_text):
            return True
    return False


def score_entry(entry, query="", voc=None, match_all_tokens=True):
    v = _default_vocab(voc)
    avail = public_status(entry) == "available"
    stage_bonus = (STAGE_RANK.get(entry.get("stage", "runs" if avail else "planned"), 0) * 0.08) if avail else 0.0
    q = (query or "").strip()
    if not q:
        return 1.0 + stage_bonus
    if _id_match(entry, q):
        return 1000.0 + stage_bonus

    stext = entry.get("search_text") or build_search_text(entry, voc=v)
    if match_all_tokens:
        q_toks = query_tokens(q)
        if not q_toks:
            return 0.0
        if not all(_token_in_search_text(t, stext, v) for t in q_toks):
            return 0.0

    prof = entry.get("profile") or {}
    tags = vocab.normalize_tags(entry.get("tags"))
    genes = [str(x).lower() for x in (prof.get("key_genes") or [])]
    tag_and_prof = [
        *(x for g in vocab.GROUPS for x in tags[g]),
        *(prof.get("species") or []),
        *(prof.get("tissues") or []),
        *(prof.get("assays") or []),
        *(prof.get("cell_types") or []),
    ]
    title = [entry.get("title") or ""]
    authors = [entry.get("first_author") or "", entry.get("senior_author") or "", entry.get("slug") or ""]
    summary = [entry.get("summary") or "", *(entry.get("collections") or []), entry.get("journal") or ""]
    rec_texts = [f"{r.get('id', '')} {r.get('panel', '')} {r.get('title', '')}" for r in (entry.get("recipes") or []) if isinstance(r, dict)]
    rec_texts.extend(str(p) for p in (entry.get("panels") or []))
    id_texts = [entry.get("doi") or "", str(entry.get("pmid") or ""), str(entry.get("pmcid") or "")]

    tokens = tokenize(q) if not match_all_tokens else (tokenize(q) or query_tokens(q))
    if not tokens:
        return 0.0
    total = 0.0
    matched = 0
    for tok in tokens:
        variants = expand_term(tok, voc=v)
        tok_score = 0.0
        if tok in genes or (variants & set(genes)):
            tok_score += 8.0
        if _value_matches(variants, id_texts):
            tok_score += 6.0
        if _value_matches(variants, tag_and_prof):
            tok_score += 5.0
        if _value_matches(variants, title):
            tok_score += 4.0
        if _value_matches(variants, authors):
            tok_score += 3.0
        if _value_matches(variants, summary):
            tok_score += 2.0
        if _value_matches(variants, rec_texts):
            tok_score += 1.5
        if tok_score == 0.0 and _token_in_search_text(tok, stext, v):
            tok_score += 2.0
        if tok_score > 0:
            matched += 1
            total += tok_score
    if matched == 0:
        return 0.0
    if match_all_tokens and matched < len(tokens) and not all(_token_in_search_text(t, stext, v) for t in query_tokens(q)):
        return 0.0
    coverage = matched / len(tokens)
    return round(total * (0.5 + 0.5 * coverage) + stage_bonus, 4)


class _DescStr:
    """Wrapper to sort ISO-8601 strings descending while keeping plain tuple keys."""
    __slots__ = ("s",)

    def __init__(self, s):
        self.s = s

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == other.s


def _usage_total(entry):
    u = entry.get("usage")
    if not isinstance(u, dict):
        return None
    for key in ("score_30d", "total_30d", "total"):
        if isinstance(u.get(key), (int, float)):
            return float(u[key])
    nums = [float(u[k]) for k in ("human_views", "agent_views", "downloads") if isinstance(u.get(k), (int, float))]
    return sum(nums) if nums else None


def _newest_key(e):
    pub = str(e.get("published_at") or "").strip()
    return (0 if pub else 1, _DescStr(pub), -entry_year(e), (e.get("title") or "").lower(), e.get("doi", ""))


def _sort_key(score, entry, has_query=False, sort="most_used"):
    avail = public_status(entry) == "available"
    bucket = 0 if avail else 1
    if not avail:
        votes = int(entry.get("votes") or 0)
        return (bucket, -votes, -entry_year(entry), (entry.get("title") or "").lower(), entry.get("doi", ""))
    if has_query:
        return (bucket, -score, -entry_year(entry), (entry.get("title") or "").lower(), entry.get("doi", ""))
    if sort == "title":
        return (bucket, (entry.get("title") or "").lower(), entry.get("doi", ""))
    if sort == "most_used":
        ut = _usage_total(entry)
        if ut is not None:
            return (bucket, 0, -ut, *_newest_key(entry))
    return (bucket, 1, *_newest_key(entry))


def search_entries(
    entries,
    query="",
    species=(),
    tissue_cell=(),
    data_type=(),
    disease=(),
    tissues=(),
    assays=(),
    cell_types=(),
    genes=(),
    collection=None,
    min_stage=None,
    include_planned=True,
    sort="most_used",
    match_all_tokens=True,
    voc=None,
    limit=20,
):
    """Filter and rank catalog entries. Returns a list of `(score, entry)` pairs."""
    if min_stage and min_stage not in STAGE_RANK:
        raise ValueError(f"unknown stage {min_stage!r}; choose from {', '.join(STAGES)}")
    min_rank = STAGE_RANK[min_stage] if min_stage else 0
    v = _default_vocab(voc)

    want_species = _as_list(species)
    want_tissue_cell = [*_as_list(tissue_cell), *_as_list(tissues)]
    want_data_type = [*_as_list(data_type), *_as_list(assays)]
    want_disease = _as_list(disease)
    want_collection = _as_list(collection)
    has_query = bool((query or "").strip())

    scored = []
    for e in entries:
        status_val = public_status(e)
        st = e.get("stage", "runs" if status_val == "available" else "planned")
        if not include_planned and status_val != "available":
            continue
        if min_stage and (status_val != "available" or STAGE_RANK.get(st, 0) < min_rank):
            continue
        tslugs = entry_tag_slugs(e, voc=v)
        if not _group_filter_ok("species", want_species, tslugs, v):
            continue
        if not _group_filter_ok("tissue_cell", want_tissue_cell, tslugs, v):
            continue
        if not _group_filter_ok("data_type", want_data_type, tslugs, v):
            continue
        if not _group_filter_ok("disease", want_disease, tslugs, v):
            continue
        if not _group_filter_ok("collection", want_collection, tslugs, v):
            continue
        prof = e.get("profile") or {}
        if not _profile_facet_ok(cell_types, prof.get("cell_types"), voc=v):
            continue
        if not _profile_facet_ok(genes, prof.get("key_genes"), voc=v, exact_only=True):
            continue
        s = score_entry(e, query, voc=v, match_all_tokens=match_all_tokens)
        if s > 0:
            scored.append((s, e))

    scored.sort(key=lambda pair: _sort_key(pair[0], pair[1], has_query=has_query, sort=sort))
    if limit is None:
        return scored
    return scored[: max(1, int(limit))]


def build_search_entry(entry, voc=None, repo="runpapers/runpapers"):
    """Build one public `papers/search.json` entry (zero internal stage, badge, or tier fields)."""
    v = _default_vocab(voc)
    doi = entry["doi"]
    slug = entry.get("slug") or ids.doi_slug(doi)
    st = public_status(entry)
    tags = vocab.normalize_tags(entry.get("tags"))
    tslugs = entry_tag_slugs(entry, voc=v)
    panels = list(dict.fromkeys(
        str(p).strip()
        for p in (entry.get("panels") or [r.get("panel") for r in (entry.get("recipes") or []) if isinstance(r, dict)])
        if p and str(p).strip()
    ))
    issue = entry.get("issue_url") or (None if st == "available" else requests_log.issue_url(repo, doi))
    return {
        "doi": doi,
        "pmid": str(entry["pmid"]) if entry.get("pmid") else None,
        "slug": slug,
        "url": f"/{ids.page_path(doi)}/" if st == "available" else None,
        "title": entry.get("title") or doi,
        "first_author": entry.get("first_author") or "",
        "senior_author": entry.get("senior_author") or "",
        "journal": entry.get("journal") or "",
        "year": entry_year(entry) or None,
        "summary": entry.get("summary") or "",
        "panels": panels,
        "status": st,
        "status_reason": entry.get("status_reason") if st == "not_possible" else None,
        "votes": int(entry.get("votes") or 0),
        "issue_url": issue,
        "tags": tags,
        "tag_slugs": tslugs,
        "search_text": build_search_text(entry, voc=v),
        "published_at": entry.get("published_at"),
        "usage": entry.get("usage") if isinstance(entry.get("usage"), dict) else None,
    }


def build_search_index(entries, voc=None, repo="runpapers/runpapers"):
    """Build the full `papers/search.json` payload (`{"vocab": ..., "entries": ...}`), ordered available-first."""
    v = _default_vocab(voc)
    built = [build_search_entry(e, voc=v, repo=repo) for e in entries]
    ordered = [e for _, e in search_entries(built, voc=v, sort="most_used", limit=None)]
    return {"vocab": v.to_dict(), "entries": ordered}


def filter_search_index(
    search_index,
    query="",
    species=(),
    tissue_cell=(),
    data_type=(),
    disease=(),
    collection=(),
    sort="most_used",
    limit=None,
):
    """Reference filter + facet-count function over `papers/search.json` (`entries` + `counts`)."""
    v = vocab.from_dict(search_index.get("vocab"))
    hits = search_entries(
        search_index.get("entries") or [],
        query=query,
        species=species,
        tissue_cell=tissue_cell,
        data_type=data_type,
        disease=disease,
        collection=collection,
        sort=sort,
        match_all_tokens=True,
        voc=v,
        limit=limit,
    )
    visible = [e for _, e in hits]
    counts = {g: {t["slug"]: 0 for t in v.groups[g]} for g in vocab.GROUPS}
    for e in visible:
        ts = e.get("tag_slugs") or {}
        for g in vocab.GROUPS:
            for slug in ts.get(g) or []:
                if slug in counts[g]:
                    counts[g][slug] += 1
    return {"entries": visible, "counts": counts}
