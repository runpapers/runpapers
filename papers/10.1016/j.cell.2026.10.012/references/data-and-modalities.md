# Data, Modalities, Join Keys, and Discrepancies Reference

This reference supplements `SKILL.md` for **Johansen et al., *Cell* 2026** (`10.1016/j.cell.2026.10.012`). All 62 data files in `pack.toml` are open-access and downloaded on demand into `$RP_DATA_DIR` with unique collision-free filenames.

---

## 1. Data Modalities & Join Keys

### 1.1 Primate 10x Multiome Core Metadata (9 CSVs, 560.2 MB)
- **Source:** Allen Brain Cell (ABC) Atlas public S3 (`release 20261130`, dataset `20261031`, taxonomy `HMBA-BG-taxonomy-CCN20250428`).
- **Helper:** `recipes/bg_atlas.py` (`load_cells()`, `group_order()`, `group_id_to_name()`).
- **Files & joins:**
  - `cell_metadata.csv` (1,896,133 rows): `cell_label`, `donor_label`, `library_label`, `doublet_score`, `umi_count` (`doublet_score` and `umi_count` are `NaN` for all 313,033 marmoset nuclei).
  - `cell_to_cluster_membership.csv`: `cell_label` → `cluster_alias` (1,435 species-specific clusters: 453 human, 388 macaque, 594 marmoset).
  - `cluster_to_cluster_annotation_membership.csv`: `cluster_alias` → `cluster_annotation_term_name` across `Neighborhood` (4), `Class` (12), `Subclass` (36), and `Group` (61).
  - `cluster_annotation_term.csv`: term labels (`CS20250428_GROUP_xxxx`), `color_hex_triplet`, and ABC internal `term_order` (note: published Figure 1B / Table S2 order is supplied by `bg_atlas.group_order()`).
  - `donor.csv` (22 donors: 10 Human, 8 Macaque = 6 *M. mulatta* + 2 *M. nemestrina*, 4 Marmoset `CJ23.56.002`–`CJ24.56.004`).
  - `library.csv`: `library_label` → `region_of_interest_label`, `region_of_interest_name`, `enrichment_population`. In the 20261031 release, `GPeR`/`GPeC` are pooled into `GPe`, `SN-VTA` is labeled `VTA`, and all marmoset slabs are `Br`.
  - `cluster.csv`, `cluster_annotation_term_set.csv`, `value_sets.csv` (release color palette; note `VTA` is `#00bfa0` teal vs brown in published Figures 1A–B).

### 1.2 Primate snRNA-seq Expression Matrices & Human TF Catalog (3 files, 46.87 GB)
- `HMBA-10xMultiome-BG-Cross-Species-log2.h5ad` (15.83 GB): `1,896,133 × 16,630` 1:1 orthologs (`log2(CPM+1)`). Does **not** contain precomputed scVI `X_umap` embeddings (`fig1cd` and `fig2de` compute cross-species Harmony integration from scratch).
- `HMBA-10xMultiome-BG-Cross-Species-raw.h5ad` (15.39 GB): raw UMI counts (`1,896,133 × 16,630`), required for `PyDESeq2` pseudobulk and method-of-moments shot-noise-adjusted `CNR1` correlation in `fig2g`.
- `HMBA-10xMultiome-BG-Human-log2.h5ad` (15.65 GB, release `20250630`): full human gene space (`log2(CPM+1)`) used by `fig7b` to build 453-cluster expression specificity matrices for MAGMA v1.10.
- `lambert_TF_names_v_1.01.txt` (11.8 KB): Lambert et al. (*Cell* 2018) HumanTFs v1.01 (1,639 HGNC symbols).
- **Memory pattern:** Open `.h5ad` files with `anndata.read_h5ad(path, backed="r")` and stream contiguous blocks of 50,000–60,000 rows to avoid random HDF5 row seeks.

### 1.3 Macaque Patch-seq Electrophysiology (5 CSVs, 0.52 MB)
- **Source:** ABC Atlas `HMBA-Macaque-PatchSeq/20260228/` (717 mapped neurons across 70 macaque donors).
- **Prefixed filenames:** `macaque_patchseq_cell_metadata.csv`, `macaque_patchseq_donor.csv`, `macaque_patchseq_mmc_results.csv`, `macaque_patchseq_cross_sweep_long_square_features.csv` (`rheobase_i`, `input_resistance`, `input_resistance_ss`), `macaque_patchseq_chrip_features.csv` (`3db_freq_chirp`; upstream spelling is `chrip`).
- **Join & nomenclature:** Join all tables on `cell_label`. Never match on `Group_name` in `macaque_patchseq_mmc_results.csv` (it still uses preprint labels such as `STRd D2 StrioMat Hybrid MSN` and `STR D1D2 Hybrid MSN`); instead join `Group_label` (`CS20250428_GROUP_xxxx`) to `cluster_annotation_term.csv` via `bg_atlas.group_id_to_name()`.
- **QC note:** 20 neurons map to `STR D2 SMYD2-HTR7 SPN` (17 donors; 17 with `rheobase_i`, 6 with `3db_freq_chirp`). Check `input_resistance` for rare negative IPFX artifacts and cross-check `input_resistance_ss`.

### 1.4 Spatial Transcriptomics (13 CSVs, 7.00 GB) & Mouse WMB Reference (6 files, 33.83 GB)
- **Helper:** `recipes/bg_spatial.py`.
- **Primate spatial (`HMBA-BG-*-20261101`, joined by `cell_label`):**
  - Human MERSCOPE (4 CSVs, 3.19 GB, 5.43M cells): `human_merscope_{cell_metadata,mmc_results,cell_anatomical_annotations,slab_plane_coordinates}.csv`.
  - Macaque MERSCOPE (4 CSVs, 1.95 GB, 3.26M cells): `macaque_merscope_{cell_metadata,mmc_results,cell_anatomical_annotations,slab_plane_coordinates}.csv`. Striatal mask: `STR == True` in `cell_anatomical_annotations.csv` (for `fig6d`, restrict the kNN permutation null strictly to striatal SPNs rather than all `STR == True` cells, which contain ~40% white-matter oligodendrocytes).
  - Marmoset Xenium (4 CSVs, 0.84 GB, 1.36M cells): `marmoset_xenium_{cell_metadata,mmc_results,cell_anatomical_annotations,slab_plane_coordinates}.csv`.
  - **Coordinate & orientation notes:** `slab_plane_coordinates.csv` provides `x`, `y`, `slab`, `plane`, and `brain_section_label`. For anterior macaque coronal views (`fig1e`), orient dorsal-up (`y` increasing upward).
- **Mouse MERFISH (1 CSV, 1.02 GB):** `mouse_merfish_cell_metadata.csv` (`MERFISH-C57BL6J-638850/20241115/views/cell_metadata_with_cluster_annotation.csv`). Includes `x`, `y` (CCF dorsal-ventral, where larger `y` = more ventral), `z`, `brain_section_label`, `subclass`, `supertype`.
- **Mouse WMB-10Xv3 RNA (6 files, 33.83 GB):** `mouse_wmb_cell_metadata.csv`, `mouse_wmb_cluster_to_cluster_annotation_membership.csv`, `mouse_wmb_cluster_annotation_term.csv`, and regional `log2` matrices `mouse_wmb_{str,pal,mb,olf}.h5ad` (`STR`, `PAL`, `MB`, `OLF`). Primate-mouse ortholog alignment joins uppercase symbols across ~15,063 shared 1:1 orthologs (56/57 Figure 3A markers match; `TAC3` is macaque-only as in published Figure 3A).

### 1.5 Primate snATAC-seq, `DeepHumanBG`, Enhancers, Genomes & GWAS (25 files, 10.67 GB)
- **Helper:** `recipes/bg_epig.py` (`canon_group()`, `calibrate_deephumanbg_channels()`, `draw_refseq_genes()`, `calc_gini_2d()`).
- **snATAC-seq peaks & UMAP (1.60 GB):**
  - Human: `atac_human_Group_by_peaks.csv` (1,360,548 cCREs × 60 Groups), `atac_human_consensus_peaks.bed` (hg38), `atac_human_concatenated_peakmat_UMAP_harmony.csv` (863,439 nuclei).
  - Macaque: `atac_macaque_Group_by_peaks.bed` (1,377,753 cCREs × 58 Groups), `atac_macaque_consensus_peaks.bed` (rheMac10).
  - Marmoset: `atac_marmoset_Group_by_peaks.bed` (1,226,781 cCREs × 56 Groups), `atac_marmoset_consensus_peaks.bed` (calJac4).
  - Group-name normalization: ATAC column headers replace spaces/slashes with underscores and retain preprint names (`Hybrid`, `MSN`); always pass through `bg_epig.canon_group()`.
- **Human snATAC-seq Group bigWigs (6.07 GB, requires `pyBigWig`):** `STR_D2_SMYD2-HTR7_SPN.bw` (0.96 GB), `STRd_D2_Striosome_SPN.bw` (1.33 GB), `STRd_D2_Matrix_SPN.bw` (1.67 GB), `STR_D1D2_eSPN.bw` (1.30 GB), and `GPe_MEIS2-SOX6_GABA.bw` (0.81 GB).
- **DeepHumanBG & genomic references (2.11 GB):**
  - `human_BG_20260204_finetune_epoch_12.keras` (76.3 MB, Keras 3 / PyTorch backend): 2,114 bp input window → 59-head accessibility predictions (`SN GATA3-PVALB GABA` omitted due to only 7 peaks). Always calibrate head indices empirically via `bg_epig.calibrate_deephumanbg_channels()` (e.g., `GPe MEIS2-SOX6 GABA` maps to channel `10`, distinct from `GPe SOX6-CTXND1 GABA` at channel `11`).
  - `hg38.fa.gz` (984 MB), `mm10.fa.gz` (952 MB), `haqer.hg38.bed` (1,581 HAQERs, Mangan et al. *Cell* 2022), `JASPAR2024_CORE_vertebrates_non-redundant_pfms_meme.txt`, `ncbiRefSeqCurated.txt.gz` (UCSC hg38 RefSeq), and `allen_gta_v2_snapshot.zip` (`SpecimenMetadata.csv` with hg38/mm10 coordinates for all 48 Hunker et al. 2025 striatal AAV enhancers and core concatemers).
- **MAGMA v1.10 & open GWAS summary statistics (0.89 GB):** `magma_v1.10_static.zip` (Linux static binary), `g1000_eur.zip` (1000G EUR LD panel), `NCBI38.3.gene.loc.extendedMHCexcluded`, `NCBI37.3.gene.loc.extendedMHCexcluded`, `GCST90027158_buildGRCh38.tsv.gz` (Bellenguez et al. 2022 AD, 21.07M SNPs), and `PGC3_SCZ_wave3.european.autosome.public.v3.vcf.tsv.gz` (Trubetskoy et al. 2022 SCZ EUR, 7.66M SNPs).

---

## 2. Per-Recipe Resource Summary

| Recipe | Panel | Data Size | RAM | GPU | Est. Time | Notes |
|---|---|---:|---:|:---:|---:|---|
| `fig1a` | Figure 1A | 0.56 GB | 4 GB | No | 2 min | Top 3D brain/FACS schematic excluded |
| `fig1b` | Figure 1B | 0.56 GB | 4 GB | No | 2 min | Dendrogram omitted; writes `composition.csv` |
| `fig1cd` | Figure 1C–D | 16.4 GB | 64 GB | Yes | 15 min | From-scratch Harmony + UMAP |
| `fig1e` | Figure 1E (top) | 2.0 GB | 12 GB | No | 2 min | Macaque MERSCOPE; wet-lab traces excluded |
| `fig2a` | Figure 2A | 16.4 GB | 24 GB | No | 5 min | 4 Expressolog example profiles |
| `fig2b` | Figure 2B | 16.4 GB | 24 GB | No | 5 min | Expressolog AUROC vs Tau (`xspecies_min > 0`) |
| `fig2c` | Figure 2C | 16.4 GB | 24 GB | No | 5 min | SPN dendrogram tanglegram |
| `fig2de` | Figure 2D–E | 16.4 GB | 48 GB | Yes | 10 min | SPN UMAP + 30-gene violin |
| `fig2f` | Figure 2F | 0.56 GB | 4 GB | No | 2 min | Per-donor classical D2 SPN proportions |
| `fig2g` | Figure 2G | 31.8 GB | 64 GB | No | 15 min | `PyDESeq2` + shot-noise-corrected `CNR1` |
| `fig3a` | Figure 3A | 50.2 GB | 32 GB | No | 15 min | 44-Group homology + 57-gene dot-pie |
| `fig3b` | Figure 3B | 50.2 GB | 32 GB | No | 15 min | 7 SPN × 14 mouse supertype heatmap |
| `fig3c` | Figure 3C | 1.0 GB | 8 GB | No | 2 min | Mouse MERFISH coronal comparison |
| `fig3d` | Figure 3D | 16.4 GB | 24 GB | No | 5 min | 13-gene OB marker 3-species pie-dot |
| `fig3e` | Figure 3E | 7.0 GB | 24 GB | No | 5 min | 4-species OB spatial + mouse OB inset |
| `fig4d` | Figure 4D (part) | 1.5 GB | 4 GB | No | 5 min | Promoter fraction vs Gini (no 447-sp HAL) |
| `fig4e` | Figure 4E | 1.6 GB | 6 GB | No | 5 min | 3-species cCRE heatmaps + SPN Jaccard |
| `fig4f` | Figure 4F | 0.56 GB | 4 GB | No | 3 min | Human ATAC SPN UMAP + Jaccard tree |
| `fig4g` | Figure 4G | 0.51 GB | 4 GB | No | 3 min | HAQER × human BG cCRE heatmap |
| `fig5b` | Figure 5B | 1.6 GB | 16 GB | Yes | 10 min | `DeepHumanBG` 512-d latent UMAP + 5 IG tracks |
| `fig5c` | Figure 5C | 18.0 GB | 24 GB | Yes | 15 min | 59×45 TF motif importance × expression |
| `fig5d` | Figure 5D | 2.4 GB | 16 GB | Yes | 5 min | 48 Hunker AAV enhancer predictions |
| `fig5e` | Figure 5E (part) | 2.4 GB | 16 GB | Yes | 5 min | `AiE0779m` IG track (no 447-sp HAL) |
| `fig6a` | Figure 6A | 16.4 GB | 24 GB | No | 5 min | 28-gene `STR D2 SMYD2-HTR7 SPN` dot plot |
| `fig6b` | Figure 6B (part) | 5.3 GB | 4 GB | No | 3 min | `SMYD2` human bigWigs (`pyBigWig`) |
| `fig6d` | Figure 6D (right) | 2.0 GB | 12 GB | No | 3 min | Macaque striosome enrichment z-scores |
| `fig6f` | Figure 6F (Mac.) | 0.72 MB | 2 GB | No | 1 min | Macaque Patch-seq rheobase & 3 dB cutoff |
| `fig7b` | Figure 7B (part) | 17.3 GB | 16 GB | No | 45 min | From-scratch MAGMA v1.10 AD & SCZ |
| `fig7c` | Figure 7C | 1.6 GB | 16 GB | Yes | 5 min | 8 SCZ SNPs × 18 Groups (`DeepHumanBG`) |
| `fig7d` | Figure 7D | 0.85 GB | 4 GB | No | 3 min | `CACNA1I` ATAC track (`pyBigWig`) |
| `fig7e` | Figure 7E | 1.6 GB | 16 GB | Yes | 5 min | `rs1883123` `ATGCTAAT` motif IG disruption |

---

## 3. Documented Discrepancies (`required = false` Targets)

1. **Atlas & SPN rounding (`fig1b`, `fig2f`):** Total released nuclei = 1,896,133 (~1.9M vs "1.8 million" in text). `STR D2 SMYD2-HTR7 SPN` is 3.49% of classical D2 SPNs (truncated to "3.4%") and 1.59%–1.60% of all SPNs pooled (vs "1%" in text, matching the marmoset donor mean 1.03%).
2. **Figure 2B quadrant counts (`fig2b`):** Table S8 has 16,620 orthologs (`Cross-Species-log2.h5ad` has 16,630), while the published plot shows 11,432 genes (`941 / 2,719 / 834 / 6,938`) due to an unstated `xspecies_min > 0` filter; from-scratch 10× random donor subsampling adds small boundary variance (~10%) while preserving exact quadrant rank order (`Q4 > Q2 > Q1 > Q3`) and TF enrichment.
3. **Figure 2G DEG thresholds & `memento` (`fig2g`):** Text/Figure 2G report 656 D1–D2 and 459 Striosome–Matrix DEGs (legend cites `LFC > 1.5`), STAR Methods specifies `|log2FC| > 1`, and Table S10 lists 495 D1–D2 and 738 Striosome–Matrix genes. Method-of-moments Poisson shot-noise correction on raw UMI counts reproduces the conserved Dorsal–Ventral axis; raw single-cell Pearson correlation reverses it.
4. **Figure 3B secondary homolog rank (`fig3b`):** In the paper's scVI cross-species latent space, `STR D2 SMYD2-HTR7 SPN` pairs with two mouse D2 supertypes (primary broad + secondary ventral); in z-scored ortholog correlation without scVI, the primary homolog remains #1 while canonical D2 supertypes can score slightly ahead of the secondary ventral supertype.
5. **Figure 7C sign inversion & checkpoint (`fig7c`):** Author code computes `original_pred - mutated_pred` (`Ref - Alt`) while labeling `Alt - Ref`, and Table S20 used unbundled pretrain checkpoint `99.keras` (`+45.31` for `rs1883123` in `GPe MEIS2-SOX6 GABA`) rather than the publicly distributed `finetune_epoch_12.keras` (`+29.54` `Ref - Alt`, `-29.54` `Alt - Ref`; strong cross-Group and cross-SNP profile concordance). Both sign conventions are exported in `fig7c` CSVs.
6. **Figure 7B MAGMA AD cluster counts & restricted cohorts (`fig7b`):** STAR Methods p.33 cites Table S17 instead of Table S18; main text p.15 notes 13 Microglia + 1 T cell whereas Table S19 lists 22 AD clusters (`P < 1e-4`). From-scratch MAGMA v1.10 on the public `20250630` `log2(CPM+1)` matrix yields 15 Microglia + 3 BAM with 0 neuronal false positives (13 Microglia at `P <= 4.45e-5` plus 2 borderline clusters at `P = 7.16e-5` and `7.34e-5`). Restricted 23andMe MDD/BD/Alcohol meta-analyses are omitted.
7. **Unbundled 447-mammal Cactus HAL & non-direct PMC supplements (`fig4d`, `fig4g`, `fig5e`):** The >1 TB Zoonomia 447-way Cactus HAL is not bundled, and PMC `/bin/` endpoints return HTML interstitials under `urllib.request`. Recipes `fig4d`, `fig4g`, and `fig5e` run cleanly on open public assets and automatically evaluate optional Table S14–S17 checks if supplied locally.

---

## 4. Excluded Panels

- **Pure conceptual schematics:** Figure 1A top artwork (3D brain/FACS), Figure 4A (Cactus workflow), Figure 5A (CREsted CNN architecture), Figure 7A (GWAS workflow).
- **Unbundled >1 TB 447-way Zoonomia Cactus HAL:** Figures 4B and 4C (and the Cactus evolutionary-distance axes of Figures 4D and 5E).
- **Companion wet-lab microscopy, morphologies & raw electrophysiology traces:** Figure 1E bottom, Figure 6D left (DAPI microscopy), Figure 6E (morphologies and voltage traces), and Mouse Patch-seq in Figure 6F (Budzillo et al.).
- **Unbundled companion enhancer:** Figure 6C (`AiE3022q` from Wirthlin et al. 2026; absent from GTA 2.0, Addgene, S3, and Zenodo `22821534`).
