---
name: runpapers
description: Use published papers' data through RunPapers packs - find a paper's pack by DOI, PMID or topic, reproduce its figures, and answer new questions with its data. Use when the user wants to explore, reproduce or reanalyse a published paper's data.
---

# RunPapers

`RP` below means `uvx --from git+https://github.com/runpapers/runpapers runpapers` (once the tool is on PyPI,
`uvx runpapers` also works). It needs `uv` (https://docs.astral.sh/uv/).

1. Find the paper: `RP search "<topic, gene, cell type or title>"` or `RP resolve <PMID|DOI|URL>`; or read
   `https://runpapers.com/index.json` (title, DOI, PMID, species, tissues, assays, cell types, recipes, badges). Each
   paper there has an `agent` URL: fetch that AGENT.md and follow it. If there is no pack yet: `RP request <id>`
   gives the user a link to request it (votes decide what is packed next).
2. Set it up: `RP get <DOI>` creates a folder with the pack and its laptop-size data. `cd` into it.
3. Read the folder's `SKILL.md` fully and follow its guardrails.
4. Reproduce first: `RP run <recipe>` (`RP recipes` lists them). Show the figure and the paper-vs-ours table in
   `out/<recipe>/result.json`.
5. Then the user's questions: scripts in `analyses/` reading `data/`. State the replicate unit, what you computed,
   and how sure you are. Cite the paper's DOI and the pack version (its archive DOI is on the paper's page).

Badges on a pack tell you how much it has been checked (runs, checked, reproduces, agent-tested, endorsed). Tell the
user if a pack has none. Tell the user the data terms (on the paper's page and in AGENT.md) before they publish or
use the data commercially.
