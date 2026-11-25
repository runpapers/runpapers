"""Profile-aware paper search and facet ranking shared by `rp search`, `rp mcp`, and `rp meeting`.

Operates purely in memory over standardized catalog entries so user queries never leave the machine."""
import re

from . import ids
from .verify import STAGES

STAGE_RANK = {s: i for i, s in enumerate(STAGES)}

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "across", "about", "between", "by", "compare", "data",
    "do", "does", "for", "from", "how", "in", "into", "is", "of", "on", "or", "paper", "papers",
    "show", "study", "studies", "that", "the", "their", "to", "using", "what", "which", "with",
})

# Bidirectional biological synonym groups so colloquial queries match ontology-normalized [profile] values.
_SYNONYM_GROUPS = (
    ("human", "humans", "homo sapiens"),
    ("macaque", "macaques", "rhesus", "pig-tailed macaque", "macaca mulatta", "macaca nemestrina", "macaca"),
    ("marmoset", "marmosets", "common marmoset", "callithrix jacchus", "callithrix"),
    ("mouse", "mice", "murine", "mus musculus"),
    ("rat", "rats", "rattus norvegicus"),
    ("nhp", "nonhuman primate", "primate", "macaca mulatta", "macaca nemestrina", "callithrix jacchus"),
    ("spn", "spns", "msn", "msns", "spiny projection neuron", "medium spiny neuron"),
    ("snrna", "snrna-seq", "scrna", "scrna-seq", "single-nucleus rna-seq", "10x multiome snrna-seq"),
    ("snatac", "snatac-seq", "atac", "atac-seq", "10x multiome snatac-seq"),
    ("multiome", "10x multiome", "10x multiome snrna-seq", "10x multiome snatac-seq"),
    ("striatum", "striatal", "caudate", "caudate nucleus", "putamen", "nucleus accumbens"),
)

_SYNONYMS = {}
for _grp in _SYNONYM_GROUPS:
    for _term in _grp:
        _SYNONYMS.setdefault(_term, set()).update(_grp)


def expand_term(term):
    t = (term or "").strip().lower()
    if not t:
        return set()
    out = {t}
    if t in _SYNONYMS:
        out.update(_SYNONYMS[t])
    if t.endswith("s") and len(t) > 3 and t[:-1] in _SYNONYMS:
        out.update(_SYNONYMS[t[:-1]])
    return out


def tokenize(text):
    raw = re.findall(r"[a-z0-9][a-z0-9._-]*", (text or "").lower())
    filtered = [t for t in raw if t not in _STOPWORDS]
    return filtered if filtered else raw


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
                if len(v) <= 2:
                    if v in re.findall(r"[a-z0-9][a-z0-9._-]*", hl):
                        return True
                elif v in hl or hl in v:
                    return True
    return False


def _facet_ok(wanted_list, entry_vals, exact_only=False):
    if not wanted_list:
        return True
    vals = [str(v) for v in (entry_vals or []) if v]
    if not vals:
        return False
    return any(_value_matches(expand_term(w), vals, exact_only=exact_only) for w in wanted_list if str(w).strip())


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


def score_entry(entry, query=""):
    stage_bonus = STAGE_RANK.get(entry.get("stage", "planned"), 0) * 0.08
    q = (query or "").strip()
    if not q:
        return 1.0 + stage_bonus
    if _id_match(entry, q):
        return 1000.0 + stage_bonus

    prof = entry.get("profile") or {}
    genes = [str(x).lower() for x in (prof.get("key_genes") or [])]
    prof_buckets = [
        *(prof.get("species") or []),
        *(prof.get("tissues") or []),
        *(prof.get("assays") or []),
        *(prof.get("cell_types") or []),
    ]
    title = [entry.get("title") or ""]
    authors = [entry.get("first_author") or "", entry.get("senior_author") or "", entry.get("citekey") or ""]
    summary = [entry.get("summary") or "", *(entry.get("collections") or []), entry.get("journal") or ""]
    rec_texts = [f"{r.get('id', '')} {r.get('panel', '')} {r.get('title', '')}" for r in (entry.get("recipes") or [])]
    id_texts = [entry.get("doi") or "", str(entry.get("pmid") or ""), str(entry.get("pmcid") or "")]

    tokens = tokenize(q)
    if not tokens:
        return 0.0
    total = 0.0
    matched = 0
    for tok in tokens:
        variants = expand_term(tok)
        tok_score = 0.0
        if tok in genes or (variants & set(genes)):
            tok_score += 8.0
        if _value_matches(variants, id_texts):
            tok_score += 6.0
        if _value_matches(variants, prof_buckets):
            tok_score += 5.0
        if _value_matches(variants, title):
            tok_score += 4.0
        if _value_matches(variants, authors):
            tok_score += 3.0
        if _value_matches(variants, summary):
            tok_score += 2.0
        if _value_matches(variants, rec_texts):
            tok_score += 1.5
        if tok_score > 0:
            matched += 1
            total += tok_score
    if matched == 0:
        return 0.0
    coverage = matched / len(tokens)
    return round(total * (0.5 + 0.5 * coverage) + stage_bonus, 4)


def search_entries(
    entries,
    query="",
    species=(),
    tissues=(),
    assays=(),
    cell_types=(),
    genes=(),
    collection=None,
    min_stage=None,
    include_planned=True,
    limit=20,
):
    """Filter and rank catalog entries. Returns a list of (score, entry) pairs."""
    if min_stage and min_stage not in STAGE_RANK:
        raise ValueError(f"unknown stage {min_stage!r}; choose from {', '.join(STAGES)}")
    min_rank = STAGE_RANK[min_stage] if min_stage else 0
    col_want = collection.strip().lower() if collection else None

    scored = []
    for e in entries:
        st = e.get("stage", "planned")
        if not include_planned and (st == "planned" or not e.get("packed", True)):
            continue
        if STAGE_RANK.get(st, 0) < min_rank:
            continue
        if col_want and col_want not in [str(c).lower() for c in (e.get("collections") or [])]:
            continue
        prof = e.get("profile") or {}
        if not _facet_ok(species, prof.get("species")):
            continue
        if not _facet_ok(tissues, prof.get("tissues")):
            continue
        if not _facet_ok(assays, prof.get("assays")):
            continue
        if not _facet_ok(cell_types, prof.get("cell_types")):
            continue
        if not _facet_ok(genes, prof.get("key_genes"), exact_only=True):
            continue
        s = score_entry(e, query)
        if s > 0:
            scored.append((s, e))

    scored.sort(key=lambda pair: (-pair[0], -(entry_year(pair[1])), pair[1].get("doi", "")))
    return scored[: max(1, int(limit))]


def entry_year(entry):
    try:
        return int(entry.get("year") or 0)
    except (TypeError, ValueError):
        return 0
