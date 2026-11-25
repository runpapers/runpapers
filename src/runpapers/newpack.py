"""Online id resolution (NCBI ID converter, Crossref) and `rp new`: scaffold a pack folder for a paper.
Network requests carry only the identifier being looked up and a generic user agent."""
import json
import urllib.parse
import urllib.request

from . import ids
from .data import UA
from .registry import PACK_FILE, SPEC


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def idconv(value):
    """PMID/PMCID/DOI -> {'doi','pmid','pmcid'} via NCBI's ID converter (PubMed Central records only)."""
    url = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?" + urllib.parse.urlencode({"ids": value, "format": "json"})
    try:
        recs = _get_json(url).get("records", [])
    except OSError:
        return {}
    r = recs[0] if recs else {}
    return {k: r.get(k) for k in ("doi", "pmid", "pmcid") if r.get(k)}


def pubmed_doi(pmid):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "json"})
    try:
        res = _get_json(url)["result"][str(pmid)]
    except (OSError, KeyError):
        return None
    for a in res.get("articleids", []):
        if a.get("idtype") == "doi":
            return a["value"]
    return None


def crossref(doi):
    try:
        m = _get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi))["message"]
    except (OSError, KeyError):
        return {}
    authors = m.get("author", [])
    name = lambda a: " ".join(x for x in (a.get("given"), a.get("family")) if x)
    return {"title": (m.get("title") or [""])[0], "journal": (m.get("container-title") or [""])[0],
            "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
            "first_author": name(authors[0]) if authors else "", "senior_author": name(authors[-1]) if authors else "",
            "orcids": [a["ORCID"].rsplit("/", 1)[-1] for a in authors if a.get("ORCID")],
            "license": (m.get("license") or [{}])[0].get("URL", "")}


def resolve_online(ident):
    kind, val = ids.parse_id(ident)
    out = {kind: val}
    if kind == "pmid":
        out.update(idconv(val))
        if not out.get("doi"):
            d = pubmed_doi(val)
            if d:
                out["doi"] = d
    elif kind == "pmcid":
        out.update(idconv(val))
    else:
        out.update({k: v for k, v in idconv(val).items() if k != "doi"})
    if out.get("doi"):
        out["doi"] = ids.normalize_doi(out["doi"])
        out.update({k: v for k, v in crossref(out["doi"]).items() if v})
    return out


def _q(s):
    return json.dumps(str(s or ""))


SKILL_TEMPLATE = """---
name: {skill_name}
description: Reproduce figures from and answer new questions with the data of "{title}" ({journal} {year}, DOI {doi}). Use when the user asks about this paper, its cell types, genes or data.
---

# {title}

## What this paper did and found
TODO: 4-8 plain sentences: the question, the samples (species, tissue, donors), the assays, the main findings.
State which claims the recipes in this pack reproduce.

## Data
TODO: for every file in pack.toml [[data]]: what one row/cell is, the key columns and their meaning, units,
how files join (keys), and known quirks (renamed labels, excluded samples). Files are in `data/` ($RP_DATA_DIR).

## Recipes
TODO: one line per recipe: which panel it reproduces, what it needs (data files, memory, GPU, runtime), and how to run it (`rp run <id>`).

## Guardrails
- Donors (or animals), not cells, are the replicates for any statistical claim.
- Report numbers with their unit and denominator; say when you are guessing.
- TODO: paper-specific pitfalls (batch/donor confounding, label versions, ortholog mapping...).

## Answering new questions
TODO: the analyses this data supports well, the ones it cannot support, and a worked example.
"""


def scaffold(reg, ident, meta=None, collection=None):
    """Create papers/<doi>/ with a valid skeleton. meta: dict with paper fields (from a collection or resolve_online)."""
    doi = reg.resolve(ident) or (meta or {}).get("doi")
    if not doi:
        raise SystemExit(f"{ident}: unknown offline; try `rp new {ident} --online`")
    doi = ids.normalize_doi(doi)
    m = {**reg.planned().get(doi, {}), **(meta or {})}
    d = reg.pack_dir(doi)
    if (d / PACK_FILE).exists():
        raise SystemExit(f"{doi}: pack already exists at {d}")
    (d / "recipes").mkdir(parents=True)
    (d / "evals").mkdir()
    cols = [collection or m.get("collection")] if (collection or m.get("collection")) else []
    pack = f"""spec = "{SPEC}"

[paper]
doi = "{doi}"
pmid = {_q(m.get('pmid'))}
pmcid = {_q(m.get('pmcid'))}
preprint_doi = {_q(m.get('preprint_doi'))}
title = {_q(m.get('title'))}
first_author = {_q(m.get('first_author'))}
senior_author = {_q(m.get('senior_author'))}
journal = {_q(m.get('journal'))}
year = {int(m.get('year') or 0)}
license = ""            # the paper's license (e.g. CC-BY-4.0): decides whether published figure images may be shown
collections = {json.dumps(cols)}

[pack]
version = "0.1.0"
summary = ""            # one or two plain sentences for the paper's page
license = "CC-BY-4.0"   # pack content; recipe code is MIT
code_license = "MIT"
maintainers = []        # [{{ name = "...", orcid = "0000-..." }}]

[profile]               # structured description used for search and agent meetings (use ontology terms)
species = []
tissues = []
assays = []
cell_types = []
key_genes = []

# [[data]]
# id = "cells"  title = ""  url = "https://..."  size = 0  md5 = ""  source = ""  license = ""  access = "open"

# [[recipes]]
# id = "fig1b"  title = ""  panel = "Figure 1B"  script = "recipes/fig1b.py"  data = ["cells"]  needs = {{ memory_gb = 8, gpu = false, minutes = 20 }}
"""
    (d / PACK_FILE).write_text(pack)
    (d / "targets.toml").write_text("# Numbers from the paper each recipe must reproduce.\n"
                                    "# [[target]]\n# recipe = \"fig1b\"\n# metric = \"n_nuclei_total\"\n# expected = 0\n"
                                    "# tolerance = { exact = true }   # or { abs = 0.1 } { rel = 0.02 } { range = [lo, hi] } { set = true }\n"
                                    "# source = \"main text p.5; Table S1\"\n# kind = \"tally\"   # tally | figure\n")
    (d / "evals" / "questions.toml").write_text("# Held-out test questions with verified answers (never copied to users' workspaces).\n"
                                                "# [[question]]\n# id = \"q1\"\n# ask = \"\"\n# answer = 0\n# tolerance = { abs = 0.1 }\n"
                                                "# kind = \"number\"   # number | text\n# source = \"recipe fig1b metric ...\"\n# public = true   # may appear as an example on the paper's page\n")
    (d / "SKILL.md").write_text(SKILL_TEMPLATE.format(skill_name=ids.skill_name(doi), title=m.get("title", ""), journal=m.get("journal", ""),
                                                      year=m.get("year", ""), doi=doi))
    return d
