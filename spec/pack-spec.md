# RunPapers pack specification v0.2 (`spec = "runpapers/0.2"`)

A pack makes one published paper usable by any AI agent: it says where the paper's data are, how to reproduce every
reproducible main-figure panel from them, which of the paper's numbers each panel must hit, and how an agent should
(and should not) analyse the data. There is one pack per paper (no tiers). It never contains the data, and never
contains published figure images.

## Identity
- A paper's id is its **DOI**, lowercase (`10.1016/j.cell.2026.10.012`). PMID, PMCID and preprint DOIs are aliases.
  If only a preprint exists, its DOI is the id; when the journal version appears, the journal DOI becomes the id and
  the preprint DOI moves to `preprint_doi`.
- Folder: `papers/<doi prefix>/<doi suffix>/`; characters outside `[a-z0-9._-]` in the suffix are percent-encoded
  (`rp resolve <id>` prints the path). On the website a paper lives at `/papers/<DOI as a name>/`
  (below); the old address `/doi/<prefix>/<encoded suffix>/` redirects there.

Wherever a DOI can't be written as is (the user's workspace folder, the Hugging Face dataset, git tags, the skill
name, the Zenodo file name), the DOI itself is turned into a name: lowercase, every run of other characters becomes
one `-` (`10.1016/j.cell.2026.10.012` -> `10-1016-j-cell-2026-10-012`; `ids.doi_slug`). The skill in SKILL.md is
named `runpapers-<that name>`. `rp lint` refuses two papers with the same name.

## Files
```
pack.toml              metadata, data, recipes (required)
targets.toml           the paper's numbers each recipe must reproduce (required)
SKILL.md               instructions for agents, Agent Skills format (required)
evals/questions.toml   held-out test questions with verified answers (required, >= 3; never shipped to users)
recipes/*.py           one script per panel (+ shared helpers)
references/            optional longer docs the SKILL.md links to (loaded on demand)
verify/*.json          verification records, written by tools only (l1, review, signoff, usertest, endorsement, release)
```

## pack.toml
```toml
spec = "runpapers/0.2"

[paper]
doi = "10.1016/j.cell.2026.10.012"      # canonical, lowercase
pmid = "43020019"                       # optional aliases: pmcid, preprint_doi, other_dois = [...]
title = "..."
first_author = "..."
senior_author = "..."
journal = "Cell"
year = 2026
license = "CC-BY-NC-ND-4.0"             # the paper's license (decides whether published images may be shown)
collections = ["bican-2026"]

[pack]
version = "0.1.0"                       # semver; bump on every change that users would notice
summary = "One or two plain sentences."
license = "CC-BY-4.0"                   # pack content; code_license = "MIT"
maintainers = [{ name = "...", orcid = "0000-..." }]

[profile]                               # for search and agent meetings; use ontology terms (CL, UBERON, HGNC)
species = [...]; tissues = [...]; assays = [...]; cell_types = [...]; key_genes = [...]

[[data]]                                # one per file (no tier field)
id = "cells"
title = "..."
url = "https://..."                     # the ORIGINAL repository; https only
size = 448741495                        # bytes
md5 = "..."                             # or sha256
source = "repository, release, version"
license = "..."
access = "open"                         # controlled: never downloaded by RunPapers; give access_note instead

[[recipes]]                             # one per reproducible main-figure panel
id = "fig2f"                            # [a-z0-9_-]
title = "..."
panel = "Figure 2F"
script = "recipes/fig2f.py"
data = ["cells"]                        # exact [[data]] ids this recipe reads
needs = { memory_gb = 6, gpu = false, minutes = 20 }   # builder estimate; measured values replace estimates after a run
```

## Getting, needs and running
- `rp get <DOI>` downloads only the pack files (instructions, recipes, targets) into `./<DOI as a name>/` — no data
  files are downloaded up front.
- `rp needs [<DOI>] [--json]` prints each recipe's `data_bytes`, `memory_gb`, `gpu`, and `minutes`, plus the pack
  totals (unique data bytes across recipes, peak `memory_gb`, whether any recipe needs a GPU, total `minutes`). Once
  a recipe has been run, measured `peak_rss_mb` and `seconds` replace the builder's estimates.
- `rp run [<DOI>] <recipe>` downloads and checksum-verifies only `<recipe>`'s `data` files into the shared cache, then
  runs `<recipe>`. `rp run --all` runs every recipe in the pack.

## Recipes
- Python with PEP 723 inline dependencies (`# /// script` block); run by `uv run --script` in a throwaway env.
- Read inputs from `$RP_DATA_DIR`; write into `$RP_OUT_DIR`: `metrics.json` (`{metric: value}`), the figure (PNG),
  and any tables. `$RP_SEED` is 0; be deterministic.
- No network access, no writes outside `$RP_OUT_DIR`, no credentials, nothing hidden. Everything in the pack is
  security-scanned; a hit is an error that review cannot waive.

## targets.toml
```toml
[[target]]
recipe = "fig2f"
metric = "smyd2_pct_of_d2_pooled"
expected = 3.4                          # the PAPER's value, never ours
tolerance = { abs = 0.34 }              # exact = true | abs | rel | range = [lo, hi] | set = true
source = "main text p.7: '... 3.4% of classical STR D2 SPNs (Figure 2F)'"
kind = "figure"                         # tally | figure | discrepancy
required = true                         # false: a known discrepancy inside the paper; shown, can't fail the run
note = ""
```
Tolerance guide: counts exact; numbers printed in the text: half of the last printed digit (or 10% of the value);
values read off a figure: the reading precision (state it in `source`).

## evals/questions.toml
```toml
[[question]]
id = "q1"
ask = "..."                              # what a scientist would ask
answer = 3.49                            # verified twice: by a recipe and by independent code
tolerance = { abs = 0.05 }               # numbers; text answers use contains_any = ["..."]
kind = "number"                          # number | text
level = "reproduce"                      # reproduce | new (needs analysis beyond the recipes)
source = "how the answer was verified"
public = true                            # may be shown as an example on the paper's page
```

## SKILL.md
Agent Skills frontmatter (`name: runpapers-<DOI as a name>`, `description`) and these sections, in plain language:
`## What this paper did and found`, `## Data` (every file: what a row is, key columns, joins, quirks),
`## Recipes`, `## Guardrails` (replicate unit, confounders, renamed labels, known discrepancies, what the data can't
answer), `## Answering new questions` (supported vs unsupported, a worked example that runs).

## Verification (badges)
Every record in `verify/` carries the pack's content hash (sha256 over all files except `verify/`); a record whose
hash differs from the current content is **stale**, and the badge must be earned again.

| Badge | Earned by | Tool |
|---|---|---|
| runs | lint clean, and **every recipe** in the pack meets all required targets on the current content hash (recipes fitting 4 CPUs, <= 14 GB RAM, `gpu = false`, `< 60` min run in `rp verify`; heavier or GPU recipes run on HPC and are recorded with `rp verify <DOI> --record <out_dir> [--where hpc]`) | `rp verify` |
| checked | an independent reviewer (never the builder) compared every reproduced panel with the published one | `rp gallery`, `rp review` |
| reproduces | a named human signed off, after a passing review | `rp signoff` |
| agent-tested | passing naive-user runs from >= 2 agent families on this exact content | `rp usertest` |
| endorsed | an author of the paper (ORCID-matched) approved | `rp endorse` |

Stages: planned -> building -> ready -> runs -> checked -> reproduces -> agent-tested -> released.

## Migration from v0.1 (`spec = "runpapers/0.1"`)
Packs written in `runpapers/0.1` still load, get and run (`rp lint` emits a `tier.ignored` warning). To migrate a
pack to `runpapers/0.2`:
1. Set `spec = "runpapers/0.2"` at the top of `pack.toml`.
2. Remove `tier` from every `[[data]]` and `[[recipes]]` entry.
3. Ensure every `[[recipes]]` entry lists its explicit `data = ["<id>", ...]` and `needs = { memory_gb = ..., gpu = false, minutes = ... }` (replacing `max_mem_gb` and `max_minutes`).
4. Run `rp lint <DOI>` and `rp verify <DOI>` (plus `rp verify <DOI> --record <out_dir>` for any HPC recipes).
