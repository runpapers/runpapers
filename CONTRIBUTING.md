# Contributing to RunPapers

Scientists, students, and AI agents can contribute in three ways, from quickest to deepest:

## 1. Request or vote for a paper

Each request is a public GitHub issue (label `request`) and a vote is a 👍 on it; the most-voted papers are packed
first. Use the [Request a paper](https://github.com/runpapers/runpapers/issues/new?template=request-paper.yml) form
(one request per paper), or add a 👍 to an [existing request](https://github.com/runpapers/runpapers/issues?q=label%3Arequest).
From an agent or terminal, `rp request <DOI or PMID>` prints the right link. The website's
[Requests](https://runpapers.com/requests.html) page shows the queue (refreshed daily and whenever an issue changes).

Found a problem in a pack? Use [Report a problem with a pack](https://github.com/runpapers/runpapers/issues/new?template=pack-problem.yml).
Security problems (unsafe recipes, prompt injection): see [SECURITY.md](SECURITY.md).

## 2. Build a pack (with your own AI agent or by hand)

Give your agent a checkout of this repository and prompt:

> Read `spec/pack-spec.md` and use `skills/runpapers-builder/SKILL.md` to build and verify a RunPapers pack for DOI `<DOI>`.

Every pack must follow these scientific and technical rules before you open a pull request:

- **Laptop-first (`lite`) tier:** Include at least one main-figure recipe that runs from open data on a standard laptop
  (aiming under 2 GB of downloads, max 8 GB, fitting within 4 CPUs and 14 GB RAM). Put 15-30 GB expression or chromatin
  matrices in an optional `full` tier instead.
- **Verify source-specific data terms — never assume CC BY:** Point `[[data]]` URLs to the original public repository
  with exact byte size and MD5 or SHA-256 checksum, and record the repository's actual license or terms of use. For
  example, data from the **Allen Brain Cell Atlas** are under the **Allen Institute Terms of Use** (noncommercial
  research use, with citation required per the Allen Institute Citation Policy), not CC BY. Mark restricted human data
  (dbGaP, EGA, restricted NeMO) as `access = "controlled"` with an `access_note`; never download or bundle them.
- **Lock targets from the paper first:** Record the paper's printed numbers and exact page/figure/table sources in
  `targets.toml` *before* running your code. Never replace a target with your script's output or widen a tolerance just
  to force a pass. When a paper has an internal discrepancy (for example, main text vs supplementary table), keep the
  paper's value, set `required = false`, and document it in `note` and `SKILL.md`.
- **Write biologist-grade guardrails in `SKILL.md`:** State the true replicate unit (donors or animals, never cells),
  sampling or batch confounders, label changes between preprint and publication, and what questions the pack's data
  cannot support, plus a runnable worked example.
- **Verify held-out test questions twice:** Add at least 3 questions (aim for 6) in `evals/questions.toml`, computing
  every answer both with the pack's recipes and with independent code. (`evals/` is held out for naive-user testing and
  is never copied into end-user workspaces.)
- **Run local checks before submitting:**
  ```bash
  rp lint <DOI>
  rp verify <DOI>
  rp ops prepublish
  ```

## 3. Independently review a pack

Someone other than the pack's builder compares every reproduced figure side by side against the published paper
(`rp gallery <DOI>`), checks targets, data licenses, and independent question answers, and records `pass` or `revise`
(`rp review <DOI> --verdict pass|revise --by "<name>"`).

## How a submitted pack earns its badges

1. **Runs** (`rp verify`): automatic Level-0 lint/security scan + Level-1 clean-room recipe execution under CI limits.
2. **Checked** (`rp review`): independent panel-by-panel human or critic review (never by the builder).
3. **Reproduces** (`rp signoff`): sign-off by a named scientist after a passing review.
4. **Agent-tested** (`rp usertest`): fresh agents from at least two model families (Claude Code, Antigravity, Codex),
   given only the public copy-prompt in an empty folder, reproduce the figure and pass the held-out questions.
5. **Author-endorsed** (`rp endorse`): optional approval by an ORCID-matched author of the paper.

Every badge is tied to the pack's SHA-256 content hash; any later edit marks badges `stale` until re-earned.
Contributors are credited in `pack.toml` (`maintainers`, with ORCID) and in the archived Zenodo/GitHub release.

## What never goes into a pull request

Do **not** commit raw or processed data files, copyrighted published figure images (`refs/` is git-ignored),
controlled-access files, API tokens or credentials, local machine paths or usernames, hand-edited files in `verify/`,
or instructions asking an agent to bypass user approval or hide actions. `rp lint` and `rp ops prepublish` reject them.
