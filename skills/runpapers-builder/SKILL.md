---
name: runpapers-builder
description: Build a RunPapers pack for a published paper (data manifest, figure-reproducing recipes, the paper's numbers as targets, agent instructions, held-out test questions) and get it through lint and L1 verification. Use when asked to "pack", "agentify" or "make RunPapers-ready" a paper given its DOI or PMID.
---

# Building a RunPapers pack

Read `spec/pack-spec.md` once. The pack is judged on one thing: a scientist's own agent, given only the copy-prompt,
reproduces a published panel and then answers new questions correctly. Every step below serves that.

## 0. Identify and scope (before writing anything)
1. `rp resolve <DOI|PMID> --online`, then `rp new <DOI>` (scaffolds `papers/<doi>/`). The DOI is the id everywhere.
2. Read the paper: main text, figure legends, STAR Methods / Methods, **data and code availability**, supplementary
   tables. Use a local copy if you have one.
3. List every main-figure panel and classify it: reproducible from open data on a laptop (**lite**), reproducible but
   heavy (**full**), or not reproducible (schematic, microscopy, controlled-access data, missing files). Say why.
4. Pick 2-3 lite panels that carry the paper's main claims. A pack with one honest lite panel beats one with five
   panels that only run on a cluster.

## 1. Data
- Point to the **original** repository (Allen/ABC, NeMO, CELLxGENE, GEO, Zenodo, figshare...). Never re-host data.
- For each file record `url`, `size` (bytes), `md5` or `sha256` (compute after one download if the source has none),
  `source` (repository + release), `license`, `access`. Controlled-access files (dbGaP, NDA, EGA, NeMO restricted)
  are `access = "controlled"` with an `access_note`, never lite, never downloaded.
- Keep the lite tier small (aim < 2 GB). Prefer metadata and summary tables over full matrices.

## 2. Targets FIRST
Lock the paper's numbers in `targets.toml` **before running anything**, each with its exact source (page, panel,
table). Never use a value your own code produced as a target. Counts are exact; text values get half the last printed
digit; values read from a figure get the reading precision. When the paper disagrees with itself (text vs table),
keep the paper's value, set `required = false`, and explain in `note`. Don't absorb the mismatch.

## 3. Recipes
- One script per panel with a PEP 723 header; shared loaders in a helper module (`recipes/<name>.py`).
- Inputs from `$RP_DATA_DIR`, outputs to `$RP_OUT_DIR`: `metrics.json`, one PNG that resembles the published panel,
  and the tables behind it. Deterministic. No network. Lite recipes: < 30 min, < 14 GB RAM.
- Follow the paper's own definitions (which samples, which filters, which denominator). When the Methods are
  ambiguous, try the readings, report which one matches, and say so in SKILL.md.
- `rp run <DOI> <recipe>` while developing.

## 4. SKILL.md (for the user's agent)
Required sections: what the paper did and found; Data (every file: what a row is, key columns with meaning and units,
how files join, quirks); Recipes; Guardrails; Answering new questions (supported vs unsupported, a worked example that
actually runs). Write for a careful agent helping a biologist: plain sentences, the paper's names (and old names),
the replicate unit, confounders such as dissection or batch, known discrepancies, and what the data can't answer.
No TODOs, no hidden text, nothing that asks the agent to skip the user.

## 5. Test questions
At least 3 (aim for 6) in `evals/questions.toml`: some a recipe answers (`level = "reproduce"`), most needing a new
analysis (`level = "new"`). **Compute every answer twice**: once with the recipes and once with independent code
that doesn't import the pack. Record both in `source`. Mark a few `public = true` as examples for the paper's page.

## 6. Verify
`rp lint <DOI>` until clean, then `rp verify <DOI>` (L1 under CI limits). If a target fails: check your pipeline
first, then the paper's definitions; never loosen a tolerance just to pass. A failed reproduction, documented, is a
result. Then `rp status <DOI>`: the next step is an independent review.

## 7. Independent review, sign-off and user tests (other people do these)
- Reviewer (never the builder): `rp gallery <DOI>`, compare every panel with the published one, then
  `rp review <DOI> --verdict pass|revise --by <name> --note "..." --fig <recipe>="..."`.
- Sign-off by a named scientist: `rp signoff <DOI> --approve --by "<name>"` (only after a passing review).
- Naive-user tests: `rp usertest <DOI> --agents claude,agy,codex`. Failures here usually mean SKILL.md or AGENT.md
  is unclear: read the transcripts in the sandbox folder and fix the instructions, not the grader.

Credit: the reading-package and verifier-independence ideas follow Paper2Agent (Miao et al., Nature 2026; MIT).
For papers whose main product is a software method, its `paper2mcp` skill can wrap the method as MCP tools; put them
under `tools/` and describe them in SKILL.md.
