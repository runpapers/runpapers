"""Paper identifiers. The canonical id of a paper is its DOI (lowercase); PMID, PMCID and preprint DOIs are aliases.

Why DOI rather than PMID: every journal article and preprint has one at publication (PMIDs exist only for
PubMed-indexed papers and can arrive weeks later), it resolves to the publisher, and Crossref/DataCite use it
to link datasets, code and packs back to the paper.
"""
import hashlib
import re
import urllib.parse

DOI_RX = re.compile(r"^10\.\d{4,9}/\S+$")
_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789.-_")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/",
                 "https://www.doi.org/", "doi.org/", "doi:", "doi ")


class IdError(ValueError):
    pass


def normalize_doi(s):
    """'https://doi.org/10.1016/J.CELL.2026.10.012' -> '10.1016/j.cell.2026.10.012'."""
    t = (s or "").strip()
    low = t.lower()
    for p in _DOI_PREFIXES:
        if low.startswith(p):
            t = t[len(p):]
            break
    t = urllib.parse.unquote(t).strip().lower()
    if not DOI_RX.match(t):
        raise IdError(f"not a DOI: {s!r}")
    return t


def parse_id(s):
    """Classify a user-supplied identifier. Returns (kind, value) with kind in doi|pmid|pmcid."""
    t = (s or "").strip()
    low = t.lower()
    m = re.match(r"^(?:pmid:\s*|https?://(?:www\.)?(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/)?(\d{1,9})/?$", low)
    if m:
        return "pmid", m.group(1)
    m = re.match(r"^(?:pmcid:\s*|https?://(?:www\.)?(?:ncbi\.nlm\.nih\.gov/pmc/articles|pmc\.ncbi\.nlm\.nih\.gov/articles)/)?(pmc\d+)/?$", low)
    if m:
        return "pmcid", m.group(1).upper()
    return "doi", normalize_doi(t)


def encode_suffix(suffix):
    out = []
    for ch in suffix:
        if ch in _SAFE:
            out.append(ch)
        else:
            out.extend("%{:02X}".format(b) for b in ch.encode("utf-8"))
    return "".join(out)


def doi_relpath(doi):
    """Folder of a paper inside papers/ (and the cache): '<prefix>/<encoded suffix>'. Reversible."""
    doi = normalize_doi(doi)
    prefix, suffix = doi.split("/", 1)
    return f"{prefix}/{encode_suffix(suffix)}"


def relpath_doi(rel):
    prefix, enc = rel.strip("/").split("/", 1)
    return normalize_doi(f"{prefix}/{urllib.parse.unquote(enc)}")


def doi_slug(doi):
    """The DOI as a name where a DOI can't be used as is (folders, Hugging Face datasets, git tags, skill and agent
    names): lowercase, every run of other characters -> one '-'. '10.1016/j.cell.2026.10.012' ->
    '10-1016-j-cell-2026-10-012'. The registry refuses two packs with the same slug (`rp lint`)."""
    s = re.sub(r"[^a-z0-9]+", "-", normalize_doi(doi)).strip("-")
    if len(s) > 54:   # skill names are at most 64 characters, 'runpapers-' included
        s = s[:45].rstrip("-") + "-" + hashlib.sha256(normalize_doi(doi).encode()).hexdigest()[:8]
    return s


def skill_name(doi):
    """Agent Skills name of a paper's pack: lowercase letters, digits and single hyphens, at most 64 characters."""
    return "runpapers-" + doi_slug(doi)


def doi_url(doi):
    return "https://doi.org/" + normalize_doi(doi)


def pubmed_url(pmid):
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
