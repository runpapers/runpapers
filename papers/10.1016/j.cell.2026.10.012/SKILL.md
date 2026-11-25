---
name: runpapers-10-1016-j-cell-2026-10-012
description: Reproduce figures from and answer new questions with the data of "Cross-species multiomic atlas of the primate basal ganglia" (Johansen et al., Cell 2026, DOI 10.1016/j.cell.2026.10.012). Use when the user asks about basal ganglia cell types, spiny projection neurons (SPNs), the STR D2 SMYD2-HTR7 SPN, cell-type composition by species, donor or region in this atlas.
---

# Cross-species multiomic atlas of the primate basal ganglia (Johansen et al., Cell 2026)

## What this paper did and found
The authors profiled 1,896,133 single nuclei (~1.9 million, referred to as "1.8 million" in the paper's text) from the
basal ganglia (caudate, putamen, nucleus accumbens, globus pallidus, subthalamic nucleus, substantia nigra and
neighbours) of 10 human, 8 macaque and 4 marmoset donors with 10x Multiome (RNA and chromatin from the same nucleus),
and built one consensus cell-type taxonomy across the three primates: 4 Neighborhoods, 12 Classes, 36 Subclasses and
61 Groups. They compared it with mouse, mapped it in tissue with spatial transcriptomics, linked cell types to
brain-disease genetics, and described a rare D2 spiny projection neuron type, **STR D2 SMYD2-HTR7 SPN** (called
"StrioMat hybrid" in the preprint), that sits between striosome and matrix and makes up 3.49% of classical D2 SPNs
(written as "3.4%" in the paper's text).

This pack covers what can be done on a laptop from the public cell metadata: **who the nuclei are** (Group, Class,
species, donor, dissected region). It reproduces the atlas tallies and Group composition (Figure 1B, minus the
dendrogram branch lengths) and the D2 SPN composition per donor (Figure 2F). Gene expression and chromatin are not in
this version (they are 15-30 GB matrices; a "full" tier is planned).

## Data
All files are in `data/` (the folder `$RP_DATA_DIR`), downloaded unchanged from the Allen Brain Cell Atlas public
bucket (release 20261130, dataset version 20261031). `recipes/bg_atlas.py` has `load_cells()`, which joins them into
one table with a row per nucleus; use it rather than re-joining by hand.

- `cell_metadata.csv` (1,896,133 rows, one per nucleus): `cell_label` (unique id), `donor_label`, `library_label`,
  `doublet_score` (0-1, higher = more likely two nuclei), `umi_count` (RNA molecules detected). **Important caveat:**
  `doublet_score` and `umi_count` are complete for human (1,034,819 nuclei) and macaque (548,281 nuclei) but are
  **missing (`NaN`) for all 313,033 marmoset nuclei** in this public ABC Atlas release, even though Table S1 reports
  species-level marmoset means.
- `cell_to_cluster_membership.csv`: `cell_label` -> `cluster_alias` (text such as `Human-451`; clusters are species-specific).
- `cluster_to_cluster_annotation_membership.csv`: `cluster_alias` -> taxonomy term at each level
  (`cluster_annotation_term_set_name` is Neighborhood / Class / Subclass / Group; the term is `cluster_annotation_term_name`).
- `cluster_annotation_term.csv`: every taxonomy term with `term_order` (the ABC release's internal ordering, not the
  published Figure 1B order; `recipes/bg_atlas.py` `group_order()` provides the published Figure 1B / Table S2 order)
  and `color_hex_triplet`.
- `donor.csv` (22 rows): `donor_label`, `species_genus` (Human / Macaque / Marmoset), `species_scientific_name`,
  `donor_sex`, `donor_age_value`. Note two naming quirks: (1) Table S4 lists the four marmoset donors by colony name
  (`cjCroissant`, `cjJellybean`, `cjNutmeg`, `cjRambo`) whereas `donor.csv` uses `CJ23.56.002`, `CJ23.56.003`,
  `CJ24.56.001`, and `CJ24.56.004` with no public mapping between the two; and (2) `species_genus == "Macaque"`
  combines two species—6 *Macaca mulatta* and 2 *Macaca nemestrina* (distinguished in `species_scientific_name`).
- `library.csv`: `library_label` -> `region_of_interest_label` (dissected region, e.g. `CaB` caudate body, `PuR`
  rostral putamen, `NAC` nucleus accumbens, `GPe`, `STH` subthalamic nucleus, `SN` substantia nigra; full names in
  `region_of_interest_name`), plus `enrichment_population` and slab ids. Region codes are hierarchical and overlapping
  (`Ca`/`CaB`/`CaH`/`CaT`, `Pu`/`PuR`/`PuC`/`PuPV`, `NAC`/`NACc`/`NACs`, `GP`/`GPe`/`GPi`), and all marmoset tiled
  dissections are labeled `Br` without regional sub-labels.
- `cluster.csv`, `cluster_annotation_term_set.csv`, `value_sets.csv`: cluster list, taxonomy levels, vocabularies and
  published region/species colors.

Shortcut: `rp run fig1b` also writes `out/fig1b/composition.csv`, the number of nuclei for every combination of
species, donor, dissected region and taxonomy level (Neighborhood, Class, Subclass, Group, cluster). Most composition
questions can be answered from this small table alone; use `load_cells(extra_cols=("doublet_score", "umi_count"))`
only when you need per-nucleus QC values (human and macaque only).

Joins: nucleus -> cluster by `cell_label`; cluster -> Group by `cluster_alias`; nucleus -> species by `donor_label`;
nucleus -> region by `library_label`. In this release every nucleus belongs to the consensus taxonomy.

## Recipes
- `fig1b` (Figure 1B): atlas tallies and the three quantitative columns of published Figure 1B in Table S2 Group order
  (log10 total nuclei heatmap, per-species proportion heatmap, and human+macaque dissected-region stacked barplot; the
  dendrogram tree is omitted because branch lengths are not in the public metadata). `rp run fig1b`
- `fig2f` (Figure 2F): per-donor shares of the four classical D2 SPN Groups; the STR D2 SMYD2-HTR7 SPN. `rp run fig2f`

Each run writes `out/<recipe>/`: the figure, `metrics.json`, tables (CSV), and `result.json`, which lists the
paper's numbers next to ours with the source of each. Show the user the figure and the comparison.

## Guardrails
- **Donors, not nuclei, are the replicates.** With 10 / 8 / 4 donors (and 6 *M. mulatta* + 2 *M. nemestrina* combined
  under `"Macaque"`), say so whenever you compare species or regions, and show per-donor values (as Figure 2F does)
  rather than only pooled percentages. Do not treat Table S4's marmoset colony names (`cjCroissant`, `cjJellybean`,
  `cjNutmeg`, `cjRambo`) as missing from `donor.csv`—the public release simply uses `CJ23.56.002`–`CJ24.56.004`
  without a published crosswalk.
- **Composition depends on dissection, and slab labels are not exact cytoarchitectonic boundaries.** Donors were
  sampled from different regions, and `region_of_interest_label` mixes coarse and fine hierarchical codes
  (`Ca`/`CaB`/`CaH`/`CaT`, `Pu`/`PuR`/`PuC`/`PuPV`, `NAC`/`NACc`/`NACs`, `GP`/`GPe`/`GPi`; all marmoset slabs are
  `Br`). Because dissections are physical slabs, nuclei of a striatal cell type appearing in a `GPe` library reflect
  adjacent striatum caught in the slab, not pallidal SPNs. Compare within matching regions when you can. Example:
  human donor H19.30.004 was dissected from the subthalamic nucleus only and has a single D2 SPN nucleus (the dot at
  1.0 in Figure 2F); macaque donor QM21.26.001 has no D2 SPNs at all.
- **Names changed between preprint and paper.** "StrioMat hybrid" (preprint) = STR D2 SMYD2-HTR7 SPN (paper);
  "hybrid" SPNs were renamed "eccentric" (eSPN). Use the paper's names and mention the old one if the user does.
- **Known discrepancies and text rounding.**
  - Total nuclei: the released atlas and Table S1 contain 1,896,133 nuclei (~1.9 million), whereas the main text
    writes "1.8 million"; do not "correct" the data count down or the text quote up.
  - SMYD2-HTR7 share of classical D2 SPNs: pooled data give 3.49%, which main text p.7 truncates to "3.4%".
  - SMYD2-HTR7 share of all SPNs: main text p.7 says "1% of all SPNs", whereas Table S9's cell-level sheet totals
    848,201 SPNs including `OT ICj Granule` (13,483 / 848,201 = 1.59%) and the 9 classical + eccentric SPN Groups
    total 841,005 nuclei (1.60%). Table S9's donor-level means are 1.49% (human), 1.66% (macaque), and 1.03%
    (marmoset)—making the marmoset donor mean a plausible source of the text's "1%". Report both if asked; do not
    silently pick one.
- **Doublets (human and macaque only — missing in marmoset).** Rare Groups are the most sensitive to doublet
  filtering, but `doublet_score` and `umi_count` are `NaN` for every marmoset nucleus in this public release. Be
  careful of the `NaN` filter trap: `doublet_score < 0.2` silently drops all 313,033 marmoset nuclei, whereas
  `~(doublet_score >= 0.2)` keeps all marmoset nuclei unfiltered. Therefore, run doublet-sensitivity re-checks
  (`doublet_score < 0.2` among non-null nuclei) **only in human and macaque**, and explicitly tell the user that
  marmoset cannot be doublet-filtered from this release. For example, excluding `doublet_score >= 0.2` drops the
  human `STR D2 SMYD2-HTR7 SPN` share of classical D2 SPNs from 3.67% to 2.97% (23% of its human nuclei have
  `doublet_score >= 0.2`), while macaque changes slightly from 3.69% to 3.59%.
- **Terms of use.** The data come from the Allen Brain Cell Atlas under the Allen Institute Terms of Use:
  noncommercial research use, and anything you publish must cite the paper (DOI 10.1016/j.cell.2026.10.012) and the
  Allen Brain Cell Atlas following the Allen Institute Citation Policy. Tell the user this when they plan to publish
  or to use the data commercially.
- This pack has no expression or chromatin data. Don't answer gene-expression questions from memory or from the
  Group names; say the full tier is needed.

## Answering new questions
Well supported: how many nuclei of a Group, Class or Subclass per species, donor, sex or dissected region;
compositional comparisons across species with per-donor variation; which dissected regions (human and macaque) a cell
type comes from; per-nucleus quality metrics (`umi_count`, `doublet_score`) by Group **in human and macaque only**
(not available in marmoset).

Not supported here: per-nucleus `doublet_score` or `umi_count` in marmoset (missing from this public release),
expression of any gene, chromatin accessibility, spatial position, mouse comparisons, disease genetics. Say so and
point to the paper's figures or tables instead.

Worked example: "Which macaque dissected regions contribute `STRd D1 Striosome SPN` nuclei?"

```python
import sys; sys.path.insert(0, "recipes")
from bg_atlas import load_cells
cells, donors = load_cells()
m = cells[(cells.species_genus == "Macaque") & (cells.Group == "STRd D1 Striosome SPN")]
print(m.region_of_interest_label.value_counts())              # nuclei per region
print(m.groupby("region_of_interest_label", observed=True).donor_label.nunique())  # donors per region
```

Then report counts with the number of donors behind each, note hierarchical region codes (`Ca` vs `CaH`/`CaB`/`CaT`,
`Pu` vs `PuR`/`PuC`/`PuPV`) and slab boundaries (striatal SPNs in `GPe` libraries reflect adjacent striatum in the
dissection slab), and compare against each region's total SPN count before calling a region "enriched".
