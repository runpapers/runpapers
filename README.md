# RunPapers

**Ask a published paper's data your own questions, with your own AI agent.**

A RunPapers *pack* turns one published paper into a verified workspace that any AI agent (Claude Code, Codex,
Antigravity, Gemini CLI, Cursor, ...) can run on your computer: links and checksums for the original public data,
recipes that reproduce published figure panels, the paper's own numbers locked in as targets, and plain-language
instructions (`SKILL.md`, the open Agent Skills format) that keep new biological analyses honest (true replicate units
such as donors rather than individual cells, dissection or batch confounders, label history, and questions the dataset
cannot answer).

RunPapers hosts no AI model and sees none of your prompts or analyses: everything runs locally on your machine.

Website: **[runpapers.com](https://runpapers.com)** · Step-by-step guide: [runpapers.com/guide.html](https://runpapers.com/guide.html)
· Request a paper: [Requests](https://runpapers.com/requests.html)

## For scientists

On a paper's page, click **Copy** on the prompt and paste it into your agent in an empty folder:

```text
I want to work with the data from this paper using RunPapers:
  "Cross-species multiomic atlas of the primate basal ganglia" (Johansen et al., Cell 2026), DOI 10.1016/j.cell.2026.10.012
Setup for you, the AI agent: fetch https://runpapers.com/doi/10.1016/j.cell.2026.10.012/AGENT.md (or `curl -sL` it) and follow it exactly.
Then:
1) Reproduce Figure 1B and show it to me, with a table of the paper's numbers next to yours.
2) Answer my question using the paper's data: <write your question here>
```

Your agent needs only [`uv`](https://docs.astral.sh/uv/). It downloads the laptop-size ("lite") files straight from the
paper's original public repositories, verifies every checksum, reproduces the figure first so you can see the numbers
match, and then writes transparent Python scripts in `analyses/` for your own questions.

Or run it directly from a terminal:

```bash
RP="uvx --from git+https://github.com/runpapers/runpapers runpapers"   # "uvx runpapers" once it is on PyPI
$RP get 10.1016/j.cell.2026.10.012     # or by PMID: $RP get 43020019
cd johansen2026 && $RP run fig1b
```

### Local MCP server & multi-paper meetings

Connect any MCP-capable agent directly to RunPapers over `stdio` (stdlib-only, instant startup):

```json
{
  "mcpServers": {
    "runpapers": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/runpapers/runpapers", "runpapers", "mcp"]
    }
  }
}
```

`rp mcp` exposes `search_papers`, `get_paper`, `get_skill` (Skills over MCP + `skill://runpapers/...` resources),
`list_recipes`, and `request_paper`. To compare findings across several verified packs on one topic (with automatic
shared-donor and taxonomy-alignment guardrails):

```bash
uvx --from git+https://github.com/runpapers/runpapers runpapers meeting "striatal D2 SPN subtypes across primates"
```

## Verification badges

Every badge is cryptographically bound to the SHA-256 content hash of the pack (`verify/*.json`); any change to a
recipe, target, data entry, or `SKILL.md` marks earlier badges as `stale` (`re-checking`) until re-verified.

| Badge | What was verified |
|---|---|
| **Runs** | Format, licenses, and security checks pass; lite data checksums match; every lite recipe re-ran from the original data under laptop/free-CI limits (4 CPUs, 14 GB RAM) and hit the paper's target numbers (`rp verify`). |
| **Checked** | An independent reviewer (never the pack builder) compared every reproduced panel side by side with the published figure and audited targets and guardrails (`rp gallery`, `rp review`). |
| **Reproduces** | A named scientist signed off the reproduction after a passing independent review (`rp signoff`). |
| **Agent-tested** | Fresh AI agents from at least two companies (e.g. Claude Code, Antigravity, Codex), given only the copy-prompt in an empty folder, reproduced the figure and answered held-out test questions (`rp usertest`). |
| **Author-endorsed** | An ORCID-verified author of the paper approved the pack (`rp endorse`). |

## Data and source-specific terms

RunPapers never re-hosts raw data and never redistributes copyrighted figure images unless the paper's license allows
it. Recipes fetch data directly from the original archives (Allen Brain Cell Atlas, NCBI GEO, CELLxGENE, NeMO, Zenodo,
figshare, ...) and verify sizes and MD5/SHA-256 checksums locally. Controlled-access datasets (such as dbGaP, EGA, or
restricted NeMO files) are never downloaded automatically; packs record access instructions instead.

**Always check a pack's recorded data terms before commercial use or publication — never assume public data are CC BY.**
For example, datasets from the **Allen Brain Cell Atlas** are governed by the
[Allen Institute Terms of Use](https://alleninstitute.org/terms-of-use/) (noncommercial research use, with citation of
both the paper and the Allen Brain Cell Atlas per the Allen Institute Citation Policy).

## Paper identity

Every paper is identified by its canonical lowercase **DOI** (`10.1016/j.cell.2026.10.012`); PMID, PMCID, preprint
DOIs, and `doi.org` / PubMed URLs are accepted everywhere as aliases (`rp resolve 43020019`). Packs live at
`papers/<doi-prefix>/<doi-suffix>/`.

## For contributors (people and agents)

See [CONTRIBUTING.md](CONTRIBUTING.md) and [spec/pack-spec.md](spec/pack-spec.md). In short:

```bash
rp new <DOI or PMID> --online   # scaffold papers/<doi>/ from Crossref and PubMed metadata
rp lint <DOI>                   # Level-0 checks: format, licenses, lite budget, completeness, security scan
rp verify <DOI>                 # Level-1 check: fetch lite data, run lite recipes under CI limits, check targets
rp status <DOI>                 # current stage, badges, and next step
```

The `skills/runpapers-builder` skill walks an AI agent step by step through building and checking a pack.

## Command reference (`rp` / `runpapers`)

Every command supports `--help` and `--json` for machine-readable output:

- **Scientists & workspaces:** `rp get <id>` · `rp recipes [id]` · `rp run [id] <recipe>|--all` · `rp fetch [id]` · `rp meeting "<topic>"` · `rp mcp`
- **Discovery & paper queue:** `rp search [query]` · `rp resolve <id> [--online]` · `rp list` · `rp show <id>` · `rp request <id>` · `rp vote <id>` · `rp requests`
- **Building & verification:** `rp new <id> [--online]` · `rp lint [id|--all]` · `rp verify [id|--all]` · `rp status [id|--all]` · `rp gallery <id>` · `rp review <id>` · `rp signoff <id>` · `rp endorse <id>` · `rp usertest <id>`
- **Releases, website & maintainer ops:** `rp release check|build <id>` · `rp publish github|zenodo|huggingface <id>` · `rp site build|serve` · `rp ops board|nightly|targets|prepublish|fresh-history|github-setup`

## Credits and licenses

The paper-reading and verifier-independence ideas build on [Paper2Agent](https://github.com/jmiao24/Paper2Agent)
(Miao et al., *Nature* 2026; MIT). RunPapers adds checksummed original-repository data manifests, figure-level target
verification, content-hash badges, a DOI registry, and naive-user testing across multiple agent families.

- **RunPapers tool & recipe code:** MIT (`LICENSE`).
- **Pack instructions & metadata:** CC BY 4.0 unless a pack specifies otherwise.
- **Underlying scientific data:** remain with their original repositories under their own terms of use.
