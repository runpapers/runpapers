# RunPapers: notes for agents working on this repository

This is the public RunPapers repository: the `rp` tool (`src/runpapers/`), the pack registry (`papers/`), planned
papers (`collections/`), requests (`requests/`), the spec (`spec/pack-spec.md`) and skills (`skills/`).

## Map
- `src/runpapers/`: ids (DOI identity), registry (packs, content hash), spec (lint + security scan), data (fetch +
  checksums), recipes (run + compare with targets), verify (badges, stages, records), workspace (`rp get`),
  site (static site + agent pages), usertest (naive-user tests with claude/agy/codex), ops (board, gallery, nightly),
  requests_log, newpack (scaffold, online resolve), cli.
- `papers/<doi prefix>/<doi suffix>/`: one pack per paper. Build packs with `skills/runpapers-builder/SKILL.md`.
- `build/` (git-ignored): site, L1 outputs, galleries, nightly report. `refs/` (git-ignored, private): published
  figure images used only for review; never commit them.

## Rules
- Papers are identified by DOI (lowercase). Accept PMID/PMCID everywhere through `Registry.resolve`.
- The core package uses only the Python standard library (it must start fast under `uvx`). Recipes declare their
  own dependencies (PEP 723).
- Never commit data, credentials, published figure images, or anything from a private lab system.
- Verification records in `verify/` are written by `rp` only. Never edit them by hand, and never loosen a target or
  tolerance to make a run pass.
- Every change to `src/` keeps `python -m unittest discover -s tests` green; add a test with each behaviour change.
  Changing the pack format means a new `spec` version and a note in `spec/pack-spec.md`.
- Network calls carry only the identifier being looked up and the generic user agent (`runpapers/<version>`).

## Commands
`rp list`, `rp status --all`, `rp lint --all`, `rp verify <DOI>`, `rp ops board --json`, `rp ops nightly`,
`rp site build && rp site serve`, `python -m unittest discover -s tests`.
