# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.11", "matplotlib>=3.8"]
# ///
"""Figure 2B: Expressolog conservation (AUROC) vs cross-species cell-type specificity (Tau, xspecies_min)
and conserved transcription factor (TF) expression heatmap across neuronal Groups.

Follows the paper's exact two-step pipeline:
  1. Expressolog AUROC across all 61 Groups and 3 primates (missing species-Groups zero-filled).
  2. 10x donor-subsampled Tau per species (sampling max(2, ceil(n_donors/3)) donors per iteration,
     requiring max Group mean > 1, averaging across 10 iterations, and taking xspecies_min = min across
     Human, Macaque, and Marmoset), filtered to xspecies_min > 0 before plotting.
  3. TF annotation using the open Lambert et al. (2018) human TF catalog (v1.01, 1,639 HGNC symbols),
     with Fisher's exact test for TF enrichment among Group markers (Tau > 0.75) and the right-hand
     conserved TF marker (AUROC > 0.75, Tau > 0.75) heatmap across the 44 neuronal Groups."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from bg_atlas import (
    SPECIES,
    compute_expressolog_auroc,
    data_dir,
    group_order,
    group_taxonomy_map,
    load_pseudobulk_log2,
    out_dir,
    write_metrics,
)

LANDMARK_TFS = ["BCL11B", "POU3F1", "RARB", "TBR1", "ONECUT1", "DPF3", "PRDM8", "TWIST1", "POU3F2", "EN1"]

seed = int(os.environ.get("RP_SEED", "0"))
rng = np.random.default_rng(seed)

pb = load_pseudobulk_log2()
var_names = pb["var_names"]
sdg_meta = pb["sdg_meta"]
sdg_sum = pb["sdg_sum"]
sdg_cnt = pb["sdg_cnt"]
sp_group_mean = pb["sp_group_mean"]
n_genes = len(var_names)

order, _ = group_order()
gtax = group_taxonomy_map()

# 1. Expressolog AUROC
cor_df = compute_expressolog_auroc(sp_group_mean, var_names)

# 2. 10x Donor-subsampled Tau per species (STAR Methods p.29 / 0_calc_tau_beta.py)
tau_species = {}
for sp_name in SPECIES:
    sp_mask = (sdg_meta["Species"] == sp_name).values
    sp_donors = np.sort(sdg_meta.loc[sp_mask, "Donor"].unique())
    n_sample = max(2, int(np.ceil(len(sp_donors) / 3.0)))
    taus = np.full((n_genes, 10), np.nan, dtype=np.float64)
    for itr in range(10):
        chosen = set(rng.choice(sp_donors, size=n_sample, replace=False))
        sub_m = sp_mask & sdg_meta["Donor"].isin(chosen).values
        sub_df = sdg_meta.loc[sub_m]
        sub_grps = sub_df["Group"].unique()
        mat = np.zeros((len(sub_grps), n_genes), dtype=np.float64)
        for gi, grp in enumerate(sub_grps):
            gm = sub_m & (sdg_meta["Group"] == grp).values
            tot = sdg_cnt[gm].sum()
            if tot > 0:
                mat[gi] = sdg_sum[gm].sum(axis=0) / tot
        mx = mat.max(axis=0)
        # Convert log2(CPM+1) expression threshold matching ln(CP10K+1) > 1.0 (0_calc_tau_beta.py):
        # 1.0 in natural log equals 1/ln(2) ~= 1.4427 in log2; using > 2.0 on log2(CPM+1) matches
        # the ~11,432 expressed ortholog universe of Table S8 (suppressing low-count noise in Q3).
        keep = mx > 2.0
        if keep.any() and len(sub_grps) > 1:
            norm_m = mat[:, keep] / mx[keep][None, :]
            taus[keep, itr] = (1.0 - norm_m).sum(axis=0) / (len(sub_grps) - 1.0)
    with np.errstate(all="ignore"):
        mean_tau = np.nanmean(taus, axis=1)
    tau_species[sp_name] = np.nan_to_num(mean_tau, nan=0.0)

tau_df = pd.DataFrame(tau_species, index=var_names)
tau_df["xspecies_mean"] = tau_df[SPECIES].mean(axis=1)
tau_df["xspecies_min"] = tau_df[SPECIES].min(axis=1)
full_df = cor_df.join(tau_df)

# 3. Load open Lambert et al. (2018) human TF list
tf_path = data_dir() / "lambert_TF_names_v_1.01.txt"
lambert_tfs = set(
    line.strip() for line in tf_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()
)
full_df["is_tf"] = full_df.index.isin(lambert_tfs)
full_df.to_csv(out_dir() / "fig2b_expressolog_tau_all.csv")

# Filter to xspecies_min > 0 (matches published expressologs_auroc_plots.R)
f2b = full_df[(full_df["auroc"].notna()) & (full_df["xspecies_min"] > 0)].copy()

q1 = int(((f2b["auroc"] > 0.75) & (f2b["xspecies_min"] > 0.75)).sum())
q2 = int(((f2b["auroc"] > 0.75) & (f2b["xspecies_min"] <= 0.75)).sum())
q3 = int(((f2b["auroc"] <= 0.75) & (f2b["xspecies_min"] > 0.75)).sum())
q4 = int(((f2b["auroc"] <= 0.75) & (f2b["xspecies_min"] <= 0.75)).sum())

tf_sub = f2b[f2b["is_tf"]]
tf_q1 = int(((tf_sub["auroc"] > 0.75) & (tf_sub["xspecies_min"] > 0.75)).sum())
tf_q2 = int(((tf_sub["auroc"] > 0.75) & (tf_sub["xspecies_min"] <= 0.75)).sum())
tf_q3 = int(((tf_sub["auroc"] <= 0.75) & (tf_sub["xspecies_min"] > 0.75)).sum())
tf_q4 = int(((tf_sub["auroc"] <= 0.75) & (tf_sub["xspecies_min"] <= 0.75)).sum())

# Fisher's exact test: TF enrichment among Group markers (Tau > 0.75)
is_tf = f2b["is_tf"].values
is_mk = (f2b["xspecies_min"] > 0.75).values
ct = [
    [int((is_tf & is_mk).sum()), int((is_tf & ~is_mk).sum())],
    [int((~is_tf & is_mk).sum()), int((~is_tf & ~is_mk).sum())],
]
tf_or, tf_p = stats.fisher_exact(ct)

# Also check conserved marker (Q1) enrichment among TFs
is_q1 = ((f2b["auroc"] > 0.75) & (f2b["xspecies_min"] > 0.75)).values
ct_q1 = [
    [int((is_tf & is_q1).sum()), int((is_tf & ~is_q1).sum())],
    [int((~is_tf & is_q1).sum()), int((~is_tf & ~is_q1).sum())],
]
tf_q1_or, tf_q1_p = stats.fisher_exact(ct_q1)

m = {
    "n_orthologs_total": int(len(full_df)),
    "n_plotted_xspecies_min_gt_0": int(len(f2b)),
    "q1_conserved_marker": q1,
    "q2_conserved_broad": q2,
    "q3_divergent_marker": q3,
    "q4_divergent_broad": q4,
    "quadrant_rank_order_exact": bool(q4 > q2 > q1 > q3),
    "tf_q1_conserved_marker": tf_q1,
    "tf_q2_conserved_broad": tf_q2,
    "tf_q3_divergent_marker": tf_q3,
    "tf_q4_divergent_broad": tf_q4,
    "tf_marker_fisher_or": round(float(tf_or), 4),
    "tf_marker_fisher_p": float(tf_p),
    "tf_q1_fisher_or": round(float(tf_q1_or), 4),
    "tf_q1_fisher_p": float(tf_q1_p),
    "tf_enriched_in_markers": bool(tf_q1_or > 1.5 and tf_q1_p < 1e-4),
}

# Build right-hand conserved TF heatmap across the 44 neuronal Groups
neuronal_groups = [g for g in order if str(gtax.loc[g, "Neighborhood"]) != "Nonneuron"]
conserved_tfs = list(tf_sub[(tf_sub["auroc"] > 0.75) & (tf_sub["xspecies_min"] > 0.75)].index)
mean_3sp = sum(sp_group_mean[sp].loc[neuronal_groups, conserved_tfs] for sp in SPECIES) / 3.0
# Normalize each TF (row) to [0, 1] across neuronal Groups (as in Fig 2B heatmap)
tf_mat = mean_3sp.T  # (n_conserved_tfs, 44)
row_max = tf_mat.max(axis=1).replace(0, 1.0)
tf_norm = tf_mat.div(row_max, axis=0)
# Order conserved TFs diagonally by their peak neuronal Group
peak_col = tf_norm.values.argmax(axis=1)
peak_val = tf_norm.values.max(axis=1)
tf_order_idx = np.lexsort((-peak_val, peak_col))
tf_norm = tf_norm.iloc[tf_order_idx]
tf_norm.to_csv(out_dir() / "fig2b_conserved_tf_heatmap.csv")

# Plot matching published Figure 2B (left scatter + right conserved TF heatmap)
fig = plt.figure(figsize=(10.2, 6.2))
gs = gridspec.GridSpec(2, 2, width_ratios=[1.25, 0.92], height_ratios=[1.0, 0.045], wspace=0.14, hspace=0.04,
                       left=0.08, right=0.89, top=0.88, bottom=0.10)

ax_sc = fig.add_subplot(gs[0, 0])
ax_hm = fig.add_subplot(gs[0, 1])
ax_bar = fig.add_subplot(gs[1, 1])

# Quadrant background shading matching expressologs_auroc_plots.R
ax_sc.add_patch(mpatches.Rectangle((0.0, 0.0), 0.75, 0.75, facecolor="#ffe6e6", alpha=0.55, zorder=0))
ax_sc.add_patch(mpatches.Rectangle((0.75, 0.75), 0.25, 0.25, facecolor="#e6ffe6", alpha=0.55, zorder=0))
ax_sc.add_patch(mpatches.Rectangle((0.0, 0.75), 0.75, 0.25, facecolor="#e6f7ff", alpha=0.55, zorder=0))
ax_sc.add_patch(mpatches.Rectangle((0.75, 0.0), 0.25, 0.75, facecolor="#fff5e6", alpha=0.55, zorder=0))

non_tf = f2b[~f2b["is_tf"]]
ax_sc.scatter(non_tf["auroc"], non_tf["xspecies_min"], s=3.5, alpha=0.40, color="#4dac26", edgecolors="none", rasterized=True, label="Gene")
ax_sc.scatter(tf_sub["auroc"], tf_sub["xspecies_min"], s=14, color="#d01c8b", edgecolors="#222222", linewidths=0.25, zorder=3, label="Transcription factor")
ax_sc.axvline(0.75, ls="--", color="#222222", lw=0.9)
ax_sc.axhline(0.75, ls="--", color="#222222", lw=0.9)
ax_sc.add_patch(mpatches.Rectangle((0.75, 0.75), 0.25, 0.25, fill=False, edgecolor="#d01c8b", ls="--", lw=0.9, zorder=4))

# Quadrant counts (TFs in magenta | all genes in green)
ax_sc.text(0.375, 1.02, f"{tf_q3}", ha="right", va="bottom", color="#d01c8b", fontsize=9.0, fontweight="bold", style="italic")
ax_sc.text(0.375, 1.02, f" | {q3}", ha="left", va="bottom", color="#33a02c", fontsize=9.0, fontweight="bold", style="italic")
ax_sc.text(0.875, 1.02, f"{tf_q1}", ha="right", va="bottom", color="#d01c8b", fontsize=9.0, fontweight="bold", style="italic")
ax_sc.text(0.875, 1.02, f" | {q1}", ha="left", va="bottom", color="#33a02c", fontsize=9.0, fontweight="bold", style="italic")
ax_sc.text(0.375, 0.015, f"{tf_q4}", ha="right", va="bottom", color="#d01c8b", fontsize=8.5, fontweight="bold", style="italic")
ax_sc.text(0.375, 0.015, f" | {q4}", ha="left", va="bottom", color="#33a02c", fontsize=8.5, fontweight="bold", style="italic")
ax_sc.text(0.875, 0.015, f"{tf_q2}", ha="right", va="bottom", color="#d01c8b", fontsize=8.5, fontweight="bold", style="italic")
ax_sc.text(0.875, 0.015, f" | {q2}", ha="left", va="bottom", color="#33a02c", fontsize=8.5, fontweight="bold", style="italic")

ax_sc.set_xlim(-0.02, 1.02)
ax_sc.set_ylim(-0.02, 1.02)
ax_sc.set_xlabel("Expr. conservation (AUROC)", fontsize=9.5)
ax_sc.set_ylabel("Cell type specificity (Tau, xspecies_min)", fontsize=9.5)
ax_sc.spines["top"].set_visible(False)
ax_sc.spines["right"].set_visible(False)
ax_sc.legend(loc="lower center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False, fontsize=8.5, markerscale=1.4)

# Right-hand conserved TF heatmap
im = ax_hm.imshow(tf_norm.values, aspect="auto", cmap="YlGnBu", vmin=0.0, vmax=1.0, interpolation="nearest")
ax_hm.set_title(f"Conserved TFs (n = {len(tf_norm)})", fontsize=9.5, fontweight="bold", pad=6)
ax_hm.set_xticks([])
ax_hm.set_yticks([])

# Annotate landmark TFs on the right edge if present in conserved TFs
tf_index_list = list(tf_norm.index)
found_landmarks = [(tf_index_list.index(g), g) for g in LANDMARK_TFS if g in tf_index_list]
found_landmarks.sort()
# Avoid overlapping text labels by enforcing minimum vertical spacing
n_rows_hm = max(1, len(tf_index_list))
min_gap = max(2.0, n_rows_hm / 24.0)
last_y = -1e9
for r_idx, gname in found_landmarks:
    y_txt = max(float(r_idx), last_y + min_gap)
    y_txt = min(y_txt, n_rows_hm - 1.0)
    last_y = y_txt
    ax_hm.annotate(
        gname,
        xy=(len(neuronal_groups) - 0.5, r_idx),
        xytext=(len(neuronal_groups) + 1.8, y_txt),
        fontsize=7.3,
        va="center",
        ha="left",
        annotation_clip=False,
        arrowprops=dict(arrowstyle="-", color="#444444", lw=0.6),
    )

# Bottom Class color strip across the 44 neuronal Groups
cls_palette = {
    "CN LGE GABA": "#f39c12",
    "F M GABA": "#c0392b",
    "Cx GABA": "#e7969c",
    "CN GABA-Glut": "#16a085",
    "CN CGE GABA": "#d95f02",
    "CN MGE GABA": "#e6550d",
    "M Dopa": "#3b5998",
    "F M Glut": "#7f1d1d",
}
cls_rgb = [cls_palette.get(str(gtax.loc[g, "Class"]), "#888888") for g in neuronal_groups]
for ci, col in enumerate(cls_rgb):
    ax_bar.add_patch(mpatches.Rectangle((ci - 0.5, 0), 1.0, 1.0, facecolor=col, edgecolor="none"))
ax_bar.set_xlim(-0.5, len(neuronal_groups) - 0.5)
ax_bar.set_ylim(0, 1)
ax_bar.set_xticks([])
ax_bar.set_yticks([])
ax_bar.set_xlabel("Group (44 neuronal Groups)", fontsize=9.0, labelpad=4)

fig.suptitle(
    f"Figure 2B: Conservation vs specificity ({len(f2b):,} genes with Tau > 0; conserved-marker TF OR = {tf_q1_or:.2f}, p = {tf_q1_p:.1e})",
    fontsize=10.2,
    fontweight="bold",
    y=0.97,
)
fig.savefig(out_dir() / "fig2b.png", dpi=180)
write_metrics(m)
print(m)
