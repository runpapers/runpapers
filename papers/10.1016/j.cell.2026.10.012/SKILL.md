---
name: runpapers-10-1016-j-cell-2026-10-012
description: Reproduce figures from and answer new questions with the data of "Cross-species multiomic atlas of the primate basal ganglia" (Johansen et al., Cell 2026, DOI 10.1016/j.cell.2026.10.012). Use when the user asks about basal ganglia cell types, spiny projection neurons (SPNs), STR D2 SMYD2-HTR7 SPN, cross-species gene conservation, primate-mouse homology, basal ganglia spatial transcriptomics, macaque Patch-seq electrophysiology, snATAC-seq enhancers, DeepHumanBG motif grammar, or AD/SCZ disease genetics in this atlas.
---

# Cross-species multiomic atlas of the primate basal ganglia (Johansen et al., Cell 2026)

## What this paper did and found
Johansen et al. profiled 1,896,133 single nuclei (~1.9 million, referred to as "1.8 million" in the main text) from the basal ganglia (caudate, putamen, nucleus accumbens, globus pallidus, subthalamic nucleus, substantia nigra, and neighboring structures) of 10 human, 8 macaque, and 4 marmoset donors using 10x Multiome (paired snRNA-seq and snATAC-seq), establishing one consensus primate taxonomy of 4 Neighborhoods, 12 Classes, 36 Subclasses, and 61 Groups (1,435 species-specific clusters). They combined this multiomic atlas with:

- **Cross-species transcriptomics and primate-mouse homology:** Expressolog AUROC and Tau specificity across 16,630 1:1 primate orthologs show that transcription factors (TFs) are conserved Group markers that organize classical spiny projection neurons (SPNs) by D1/D2 pathway identity rather than dorsal/ventral anatomy, while dorsal-ventral identity is more evolutionarily conserved than pathway or striosome-matrix axes. Mapping the 44 neuronal primate Groups onto the Mouse Whole-Brain (WMB) atlas confirms broad homology alongside primate-expanded peri-striatal olfactory bulb-like populations (`OB Dopa-GABA` and `OB FRMD7 GABA`).
- **Spatial transcriptomics and Patch-seq:** MERSCOPE (human, macaque), Xenium (marmoset), and MERFISH (mouse) resolve striosome-matrix architecture and peri-striatal OB-like distributions, while macaque Patch-seq links molecular identity to intrinsic physiology, characterizing the rare **STR D2 SMYD2-HTR7 SPN** (called "StrioMat hybrid" in the preprint; 3.49% of classical D2 SPNs, written as "3.4%" in the main text) as a low-rheobase, low-3 dB-cutoff SPN distributed neutrally across striosome and matrix compartments.
- **Chromatin evolution, deep sequence modeling, and disease genetics:** Primate snATAC-seq identifies 1.36M (human), 1.37M (macaque), and 1.22M (marmoset) accessible cCREs, including human BG cCREs overlapping Human Ancestor Quickly Evolved Regions (HAQERs). The pretrained `DeepHumanBG` CREsted sequence-to-accessibility CNN captures cell-type TF motif grammars (e.g., `LHX8`/`GBX2`/`ZIC3` in cholinergic interneurons, `MEIS2`/`EGR1`/`RARB` in `AiE0779m`), predicts activity of striatal AAV enhancers from Hunker et al. (2025), and scores non-coding schizophrenia (SCZ) risk variants identified via MAGMA enrichment across 453 human clusters—highlighting `rs1883123` (`CACNA1I`, `chr22:39,600,877 C>T`), which disrupts an `ATGCTAAT` motif selectively in `GPe MEIS2-SOX6 GABA` neurons while Alzheimer's disease (AD) GWAS enrichment localizes exclusively to non-neuronal immune/glial clusters.

This unified pack reproduces **31 main-figure panels** (Figures 1A–E, 2A–G, 3A–E, 4D–G, 5B–E, 6A–B, 6D, 6F, and 7B–E) strictly from open public datasets.

## Data
All 62 open data files are downloaded unchanged into `$RP_DATA_DIR` on demand when running a recipe (`rp run <recipe>` fetches only that recipe's declared `data` files). Total size across all 62 files is ~99.4 GB, but individual recipes range from 0.7 MB to 48.7 GB. See `references/data-and-modalities.md` for complete schemas, join keys, and per-file sizes.

- **Primate 10x Multiome core metadata (560 MB, 9 CSVs):** `cell_metadata.csv` (1,896,133 nuclei), `donor.csv` (22 donors), `library.csv`, `value_sets.csv`, `cell_to_cluster_membership.csv`, `cluster.csv`, `cluster_annotation_term.csv`, `cluster_annotation_term_set.csv`, `cluster_to_cluster_annotation_membership.csv` (ABC Atlas release `20261130`, version `20261031`, taxonomy `HMBA-BG-taxonomy-CCN20250428`). Use `recipes/bg_atlas.py` `load_cells()` rather than re-joining by hand.
- **Primate snRNA-seq matrices & TF catalog (46.9 GB):** `HMBA-10xMultiome-BG-Cross-Species-log2.h5ad` (15.8 GB, 1,896,133 × 16,630 orthologs), `HMBA-10xMultiome-BG-Cross-Species-raw.h5ad` (15.4 GB), `HMBA-10xMultiome-BG-Human-log2.h5ad` (15.6 GB, full human gene set for 453-cluster MAGMA), and `lambert_TF_names_v_1.01.txt` (1,639 human TFs). Always open `.h5ad` files with `anndata.read_h5ad(..., backed="r")` and stream contiguous row chunks.
- **Macaque Patch-seq (0.52 MB, 5 prefixed CSVs):** `macaque_patchseq_{cell_metadata,donor,mmc_results,cross_sweep_long_square_features,chrip_features}.csv` (note upstream spelling `chrip_features.csv`). Join on `cell_label`, and map `Group_label` (`CS20250428_GROUP_xxxx`) via `bg_atlas.group_id_to_name()` because `mmc_results.csv` still shows preprint Group strings.
- **Spatial transcriptomics across 4 species (7.0 GB, 13 prefixed CSVs) & Mouse WMB RNA (33.8 GB, 6 files):** Human MERSCOPE, Macaque MERSCOPE, Marmoset Xenium (`HMBA-BG-*-20261101`, joined by `cell_label`), Mouse MERFISH (`MERFISH-C57BL6J-638850`), and Mouse WMB-10Xv3 (`STR`, `PAL`, `MB`, `OLF` `.h5ad` + metadata). Use `recipes/bg_spatial.py` helpers.
- **Primate snATAC-seq, `DeepHumanBG`, enhancers, genomes & GWAS (10.7 GB):** Human/macaque/marmoset `Group_by_peaks` and `consensus_peaks.bed`, Human Harmony UMAP (`52 MB`), 5 Human Group bigWigs (`0.81–1.67 GB` each), `haqer.hg38.bed` (1,581 HAQERs), `JASPAR2024` MEME motifs, UCSC `ncbiRefSeqCurated.txt.gz`, `allen_gta_v2_snapshot.zip` (all 48 Hunker et al. 2025 enhancers), `human_BG_20260204_finetune_epoch_12.keras` (`DeepHumanBG`), `hg38.fa.gz`, `mm10.fa.gz`, MAGMA v1.10 Linux binary + 1000G EUR reference + GRCh38/GRCh37 gene locations + Bellenguez et al. (2022) AD and PGC3 SCZ EUR summary statistics. Use `recipes/bg_epig.py` helpers.

Shortcut: `rp run fig1b` writes `out/fig1b/composition.csv` (nuclei counts by species, donor, dissected region, Neighborhood, Class, Subclass, Group, cluster), which answers most composition queries without loading the full 1.9M-row `cell_metadata.csv`.

## Recipes
Run `rp needs 10.1016/j.cell.2026.10.012` to inspect exact per-recipe download sizes, RAM, GPU, and runtime requirements. Each recipe writes `out/<recipe>/` (`<recipe>.png`, CSV tables, `metrics.json`, `result.json`).

**Desktop-friendly recipes (CPU, 0.7 MB–1.4 GB data, 2–6 GB RAM, 1–5 min):**
- `fig1a` (Figure 1A; 0.56 GB, 4 GB RAM): Dissection coverage dot plot across 19 Human/Macaque regions + Marmoset `Br`.
- `fig1b` (Figure 1B; 0.56 GB, 4 GB RAM): Atlas tallies and 61-Group composition in Table S2 order (dendrogram omitted).
- `fig2f` (Figure 2F; 0.56 GB, 4 GB RAM): Per-donor proportions of the four classical D2 SPN Groups across 21 donors.
- `fig6f` (Figure 6F, Macaque; 0.72 MB, 2 GB RAM): Macaque Patch-seq rheobase (`pA`) and 3 dB cutoff (`Hz`) across 6 SPN Groups.
- `fig4f` (Figure 4F; 0.59 GB, 4 GB RAM): Human snATAC-seq SPN Harmony UMAP and 9-SPN cCRE Jaccard UPGMA dendrogram.
- `fig4g` (Figure 4G; 0.51 GB, 4 GB RAM): HAQER intersection with human BG cCREs (binary 60-Group cascade, coverage, Gini).
- `fig7d` (Figure 7D; 0.85 GB, 4 GB RAM, requires `pyBigWig`): `CACNA1I` locus ATAC track in `GPe MEIS2-SOX6 GABA` highlighting `rs1883123`.
- `fig4d` (Figure 4D, partial; 1.48 GB, 4 GB RAM): JASPAR2024 TF motif promoter fraction vs cell-type Gini specificity (447-mammal Cactus axis requires unbundled >1 TB HAL).
- `fig4e` (Figure 4E; 1.55 GB, 6 GB RAM): 3-species cCRE counts, Group-specific heatmaps, and human 60×60 / 9×9 SPN Jaccard heatmaps.

**Spatial & mouse homology recipes (CPU, 1.0–50.2 GB data, 8–32 GB RAM, 2–15 min):**
- `fig1e` (Figure 1E, top row; 2.0 GB, 12 GB RAM): Macaque anterior striatal MERSCOPE map of 6 SPN Groups (wet-lab morphologies/traces excluded).
- `fig3c` (Figure 3C; 1.0 GB, 8 GB RAM): Mouse MERFISH coronal comparison of the two homologous striatal D2 SPN supertypes.
- `fig3e` (Figure 3E; 7.0 GB, 24 GB RAM): Four-species peri-striatal spatial localization of `OB Dopa-GABA` and `OB FRMD7 GABA` + mouse OB inset.
- `fig6d` (Figure 6D, right; 2.0 GB, 12 GB RAM): Macaque MERSCOPE permutation-standardized striosome neighborhood enrichment z-scores (DAPI microscopy excluded).
- `fig3a` (Figure 3A; 50.2 GB, 32 GB RAM): Primate vs mouse sampling depth, 44-Group homology heatmap, and 57-gene conserved marker dot-pie.
- `fig3b` (Figure 3B; 50.2 GB, 32 GB RAM): Zoomed 7 classical SPN Groups × 14 mouse SPN supertypes homology heatmap.

**Primate expression, bigWig, MAGMA & GPU deep-learning recipes (CPU 4–64 GB RAM or 1 GPU, 1.6–31.8 GB data):**
- `fig1cd` (Figure 1C–D; 16.4 GB, 64 GB RAM, GPU): From-scratch cross-species Harmony integration and UMAP across 1.90M nuclei (scVI `X_umap` not in ABC `.h5ad`).
- `fig2a`, `fig2b`, `fig2c`, `fig3d`, `fig6a` (16.4 GB, 24 GB RAM, CPU, ~5 min each): Expressolog examples (`ADORA2A`/`MCHR2`/`KCNIP1`/`OPRM1`), Expressolog AUROC vs Tau & conserved TF heatmap, SPN Dorsal/Ventral-to-D1/D2 dendrogram tanglegram, 13-gene OB marker pie-dot plot, and 28-gene `STR D2 SMYD2-HTR7 SPN` profile.
- `fig2de` (Figure 2D–E; 16.4 GB, 48 GB RAM, GPU): Integrated SPN UMAP (`841,005` nuclei) and 30-gene conserved marker stacked violin plot.
- `fig2g` (Figure 2G; 31.8 GB, 64 GB RAM, CPU): SPN evolutionary axes (`PyDESeq2` + LOWESS-residual `|log2FC|`, shot-noise-corrected `CNR1` correlation).
- `fig6b` (Figure 6B, partial; 5.3 GB, 4 GB RAM, CPU, requires `pyBigWig`): `SMYD2` locus human ATAC bigWigs across 4 SPN Groups (companion mouse tracks excluded).
- `fig7b` (Figure 7B, partial; 17.3 GB, 16 GB RAM, CPU, ~45 min): From-scratch MAGMA v1.10 AD (Bellenguez 2022) and SCZ (PGC3 EUR) enrichment across 453 human clusters (restricted 23andMe MDD/BD/Alcohol cohorts excluded).
- `fig5b`, `fig5c`, `fig5d`, `fig5e`, `fig7c`, `fig7e` (`DeepHumanBG`, 1.6–18.0 GB data, 16–24 GB RAM, 1 GPU, 5–15 min): Latent UMAP + 5 IG tracks (`fig5b`), 59×45 TF grammar × expression clustermap (`fig5c`, uses `rna-cross-species-log2`), 48 Hunker AAV enhancer predictions (`fig5d`), `AiE0779m` D1-SPN IG logo (`fig5e`, 447-mammal Cactus scatter requires unbundled HAL), 8 SCZ SNPs × 18 MAGMA Groups (`fig7c`), and `rs1883123` `ATGCTAAT` motif disruption IG tracks (`fig7e`).

## Guardrails
- **Donors, not nuclei, are the replicates.** With 10 human, 8 macaque (6 *M. mulatta* + 2 *M. nemestrina* combined under `"Macaque"` in `species_genus`), and 4 marmoset donors, report per-donor variation alongside pooled counts. Do not treat Table S4's marmoset colony names (`cjCroissant`, `cjJellybean`, `cjNutmeg`, `cjRambo`) as missing from `donor.csv`—the public release uses `CJ23.56.002`–`CJ24.56.004` without a published crosswalk.
- **Dissection slabs and hierarchical region codes.** `region_of_interest_label` mixes coarse and fine codes (`Ca`/`CaB`/`CaH`/`CaT`, `Pu`/`PuR`/`PuC`/`PuPV`, `NAC`/`NACc`/`NACs`, `GP`/`GPe`/`GPi`; all marmoset slabs are `Br`; `GPeR`/`GPeC` are pooled as `GPe` and `SN-VTA` is labeled `VTA` in the 20261031 release). Physical slabs catch adjacent tissue (e.g., striatal SPNs in `GPe` libraries reflect neighboring striatum, not pallidal SPNs; human donor `H19.30.004` was dissected from `STH` only; macaque `QM21.26.001` has zero D2 SPNs).
- **Missing marmoset QC metrics (`NaN` filter trap).** `doublet_score` and `umi_count` are complete in human and macaque but **`NaN` for all 313,033 marmoset nuclei** in this public release. Never write `doublet_score < 0.2` across all species (it silently drops every marmoset nucleus); run doublet checks only in human and macaque and state explicitly that marmoset QC metrics are unavailable.
- **Preprint vs Cell 2026 nomenclature.** "StrioMat hybrid" (preprint) = `STR D2 SMYD2-HTR7 SPN`; "hybrid" SPN = `STR D1D2 eSPN` (eccentric SPN). Several public files (`macaque_patchseq_mmc_results.csv`, ATAC Harmony UMAP, ATAC column headers) retain preprint strings or underscores—always map via `CS20250428_GROUP_xxxx` (`bg_atlas.group_id_to_name()`) or `bg_epig.canon_group()`.
- **Documented paper & release discrepancies (never "fix" silently; see `references/data-and-modalities.md` for details):**
  - *Atlas tallies & rounding:* Released data contain 1,896,133 nuclei (~1.9M, written as "1.8 million"); `STR D2 SMYD2-HTR7 SPN` is 3.49% of classical D2 SPNs (truncated to "3.4%") and 1.59%–1.60% of all SPNs pooled (written as "1%", matching the marmoset donor mean 1.03%).
  - *Release palette (`value_sets.csv`):* `VTA` is teal (`#00bfa0`) in the release palette vs brown `SN-VTA` in published Figures 1A–B; describe it as the release palette.
  - *Figure 2B (`11,432` vs `16,620` genes):* Plotting filters strictly to `xspecies_min > 0` (minimum Tau across all three primates) and uses the Lambert et al. (2018) 1,639-TF catalog.
  - *Figure 2G (`memento` sensitivity & DEG count discrepancy):* Text/legend/Table S10 differ on DEG thresholds (`656`/`459` vs `495`/`738`), and the Dorsal–Ventral conservation result requires shot-noise-corrected correlation on raw UMIs (naive single-cell Pearson correlation with `CNR1` reverses the conclusion).
  - *Figure 3B & 6D methodology:* Linear ortholog correlation without scVI recovers the #1 mouse homolog for `STR D2 SMYD2-HTR7 SPN` while ranking canonical D2 supertypes slightly ahead of the secondary ventral homolog (`fig3b`); striosome enrichment permutation nulls (`fig6d`) must restrict to striatal SPNs (including white-matter oligodendrocytes introduces a strong gray-matter colocalization bias).
  - *`DeepHumanBG` 59-channel mapping & Figure 7C sign inversion:* `SN GATA3-PVALB GABA` (7 peaks) was omitted from the 59-head model—always calibrate channels via `bg_epig.calibrate_deephumanbg_channels()`. Author code for Figure 7C/Table S20 computes `Ref - Alt` while labeling `Alt - Ref` and used unbundled checkpoint `99.keras` instead of public `finetune_epoch_12.keras`.
  - *Figure 7B MAGMA AD counts & restricted GWAS:* Text mentions 13 Microglia + 1 T cell whereas Table S19 lists 22 AD clusters (`P < 1e-4`), and from-scratch MAGMA on the 20250630 `log2(CPM+1)` matrix recovers 15 Microglia + 3 BAM with 0 neuronal false positives. Published MDD/BD/Alcohol meta-analyses include restricted 23andMe cohorts and are excluded.
  - *Patch-seq artifacts:* Screen `input_resistance` for rare negative IPFX values (cross-check `input_resistance_ss`); mouse Patch-seq data in Figure 6F belong to companion study Budzillo et al.
- **Excluded panels:** Pure schematics (1A top artwork, 4A, 5A, 7A), >1 TB unbundled 447-way Zoonomia Cactus HAL panels (4B, 4C, and the Cactus axes of 4D/5E), companion wet-lab microscopy/morphologies/traces (1E bottom, 6D DAPI, 6E), and unbundled companion enhancer `AiE3022q` (6C).
- **Terms of use:** ABC Atlas and Allen S3 datasets are governed by the Allen Institute Terms of Use (noncommercial research use; cite Johansen et al. `10.1016/j.cell.2026.10.012` and the Allen Brain Cell Atlas). External references carry CC-BY-4.0 or open academic licenses (see `pack.toml`).

## Answering new questions
Well supported directly from the pack data (load only the files needed for the question):
- **Cell composition & QC:** Counts and per-donor proportions by species, sex, age, dissected region, and taxonomy level (`bg_atlas.load_cells()` or `out/fig1b/composition.csv`); per-nucleus `umi_count` and `doublet_score` in human and macaque only.
- **Cross-species gene expression & primate-mouse homology:** Expression, specificity (`Tau`), Expressolog AUROC, differential expression, and primate-mouse ortholog comparisons across all 61 primate Groups and Mouse WMB supertypes (stream `.h5ad` backed).
- **Spatial transcriptomics & Patch-seq:** Anatomical distribution, striosome-matrix neighborhood enrichment, and peri-striatal mapping across 4 species (`bg_spatial.py`); macaque Patch-seq electrophysiology (`rheobase_i`, `3db_freq_chirp`, `input_resistance_ss`) mapped to Cell 2026 Groups.
- **Chromatin, regulatory grammar & variant scoring:** Human/macaque/marmoset cCRE accessibility across Groups, HAQER overlaps, ATAC locus tracks (`pyBigWig`), `DeepHumanBG` accessibility/motif predictions and in-silico mutagenesis for any hg38/mm10 sequence or variant (GPU recommended), and 453-cluster MAGMA GWAS enrichment.

Not supported from this pack: marmoset `doublet_score`/`umi_count` (all `NaN`), 447-mammal Zoonomia Cactus HAL conservation scores, companion mouse Patch-seq/morphologies/voltage traces, `AiE3022q` enhancer sequences, or restricted 23andMe GWAS summary statistics.

Worked example: "Which macaque dissected regions contribute `STRd D1 Striosome SPN` nuclei, and how many donors back each region?"

```python
import sys; sys.path.insert(0, "recipes")
from bg_atlas import load_cells
cells, donors = load_cells()
m = cells[(cells.species_genus == "Macaque") & (cells.Group == "STRd D1 Striosome SPN")]
summary = m.groupby("region_of_interest_label", observed=True).agg(
    nuclei=("cell_label", "size"),
    donors=("donor_label", "nunique"),
).sort_values("nuclei", ascending=False)
print(summary.head(10))
```

Report both nucleus and donor counts per region, note hierarchical dissection codes (`Ca`/`CaH`/`CaB`/`CaT`, `Pu`/`PuR`/`PuC`/`PuPV`) and slab boundaries, and normalize against each region's total SPN count before claiming enrichment.
