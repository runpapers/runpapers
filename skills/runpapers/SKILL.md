---
name: runpapers
description: Use published papers' data through RunPapers packs - find a paper's pack by DOI, PMID or topic, reproduce its figures, and answer new questions with its data. Use when the user wants to explore, reproduce or reanalyse a published paper's data.
---

# RunPapers

1. Find the paper: `uvx runpapers resolve <PMID|DOI|URL>`; browse `https://runpapers.org/index.json` (title, DOI,
   PMID, species, tissues, assays, cell types, recipes, badges). If there is no pack yet: `uvx runpapers request <id>`.
2. Set it up: `uvx runpapers get <DOI>` creates a folder with the pack and its laptop-size data. `cd` into it.
3. Read the folder's `SKILL.md` fully and follow its guardrails.
4. Reproduce first: `uvx runpapers run <recipe>` (`uvx runpapers recipes` lists them). Show the figure and the
   paper-vs-ours table in `out/<recipe>/result.json`.
5. Then the user's questions: scripts in `analyses/` reading `data/`. State the replicate unit, what you computed,
   and how sure you are. Cite the paper's DOI and the pack version.

Badges on a pack tell you how much it has been checked (runs, checked, reproduces, agent-tested, endorsed). Tell the
user if a pack has none.
