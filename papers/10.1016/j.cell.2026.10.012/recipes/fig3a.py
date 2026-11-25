# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.10", "matplotlib>=3.8"]
# ///
"""Figure 3A: Primate vs. mouse basal ganglia cell sampling, 44-Group x mouse supertype homology
heatmap, and 57-gene macaque-mouse conserved marker dot-pie chart.

Streams HMBA-10xMultiome-BG-Cross-Species-log2.h5ad (1.90M nuclei) and Mouse WMB-10Xv3
STR/PAL/MB/OLF expression matrices (4.04M cells) to compute cross-species similarity and
conserved marker expression between macaque Groups and matched mouse WMB supertypes.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.gridspec as gridspec
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_spatial import (
    ALL_GROUP_ORDER,
    CLASSICAL_SPN_GROUPS,
    FIG3A_MARKER_GENES,
    FIG3B_MOUSE_SPN_SUPERTYPES,
    NEURONAL_GROUP_ORDER,
    TABLE_S12_CURATED_MOUSE,
    compute_primate_mouse_homology,
    load_group_colors,
    out_dir,
    write_metrics,
)

res = compute_primate_mouse_homology()
sim_df = res["sim_df"]
primate_cnt = res["primate_cnt"]
mouse_cnt = res["mouse_cnt"]
mac_mean = res["macaque_marker_mean"]
mac_pct = res["macaque_marker_pct"]
mus_mean = res["mouse_marker_mean"]
mus_pct = res["mouse_marker_pct"]
st_to_sub = res["mouse_st_to_subclass"]
group_colors = load_group_colors()

# Save full 61-Group similarity matrix
sim_df.to_csv(out_dir() / "fig3a_primate_mouse_similarity.csv")

# Evaluate Table S12 concordance across all 58 curated primate Groups (full mouse BG+OLF supertype space)
top_all = sim_df.idxmax(axis=1)
n_curated = 0
n_exact_st = 0
n_concordant = 0
hom_rows = []

for g in ALL_GROUP_ORDER:
    best_st = str(top_all[g])
    best_r = float(sim_df.loc[g, best_st])
    best_sub = str(st_to_sub.get(best_st, ""))
    p_n = int(primate_cnt[g])
    m_n = int(mouse_cnt.get(best_st, 0))
    fc = float(p_n / max(m_n, 1))
    cur_subs, cur_sts = TABLE_S12_CURATED_MOUSE.get(g, ([], []))
    exact_hit = False
    sub_hit = False
    if cur_subs or cur_sts:
        n_curated += 1
        exact_hit = any(best_st == s or s in best_st for s in cur_sts)
        sub_hit = any(s.lower() in best_sub.lower() for s in cur_subs)
        if exact_hit:
            n_exact_st += 1
        if exact_hit or sub_hit:
            n_concordant += 1
    hom_rows.append(
        {
            "Group": g,
            "best_mouse_supertype": best_st,
            "best_mouse_subclass": best_sub,
            "similarity_r": round(best_r, 4),
            "primate_cells": p_n,
            "mouse_cells_top_supertype": m_n,
            "fold_change_primate_vs_mouse": round(fc, 3),
            "table_s12_exact_supertype": exact_hit,
            "table_s12_concordant": bool(exact_hit or sub_hit),
        }
    )

hom_df = pd.DataFrame(hom_rows).set_index("Group")
hom_df.to_csv(out_dir() / "fig3a_homology_and_sampling.csv")
concordance_pct = round(100.0 * n_concordant / max(n_curated, 1), 2)

# For Figure 3A panel: 44 neuronal Groups (bottom-to-top); exclude mouse OB supertypes per Figure 3E legend
non_ob_cols = [c for c in sim_df.columns if not any(tok in c for tok in (" OB-", " OB "))]
sim_bg = sim_df.loc[NEURONAL_GROUP_ORDER, non_ob_cols].copy()

# Select and order mouse BG supertypes diagonally from bottom-left (STRd D1 Matrix) to top-right (STH PVALB-PITX2)
ordered_cols = [c for c in FIG3B_MOUSE_SPN_SUPERTYPES if c in sim_bg.columns]
seen_cols = set(ordered_cols)
ob_excluded_groups = {"OB FRMD7 GABA", "OB Dopa-GABA", "IP SEMA5A GABA", "IP EBF2 GABA"}

for g in NEURONAL_GROUP_ORDER:
    if g in ob_excluded_groups:
        continue
    top_k = sim_bg.loc[g].nlargest(3).index.tolist()
    for c in top_k:
        if c not in seen_cols and sim_bg.loc[g, c] >= 0.30:
            ordered_cols.append(c)
            seen_cols.add(c)

sim_plot = sim_bg[ordered_cols].copy()
# Mask OB/IP rows with no mouse BG homolog (matching blank rows in Figure 3A & Figure 3E legend)
for g in ob_excluded_groups:
    sim_plot.loc[g, :] = np.nan

# Prepare 57-gene Macaque vs matched-Mouse dot-pie table
marker_rows = []
mac_vals_all, mus_vals_all = [], []
mac_norm_mat = np.zeros((len(NEURONAL_GROUP_ORDER), len(FIG3A_MARKER_GENES)), dtype=np.float64)
mac_pct_mat = np.zeros_like(mac_norm_mat)
mus_norm_mat = np.full_like(mac_norm_mat, np.nan)
mus_pct_mat = np.full_like(mac_norm_mat, np.nan)

# Match each neuronal Group to its top non-OB mouse supertype for marker comparison
top_bg_match = sim_bg.idxmax(axis=1)

# Normalize expression per gene to [0, 1] across the 44 neuronal Groups (matching published 0..1 colormaps)
mac_sub_mean = mac_mean.loc[NEURONAL_GROUP_ORDER, FIG3A_MARKER_GENES].fillna(0.0)
mac_sub_pct = mac_pct.loc[NEURONAL_GROUP_ORDER, FIG3A_MARKER_GENES].fillna(0.0)

matched_sts = [top_bg_match[g] for g in NEURONAL_GROUP_ORDER]
mus_matched_mean = pd.DataFrame(
    [
        mus_mean.loc[top_bg_match[g], FIG3A_MARKER_GENES].values
        if g not in ob_excluded_groups
        else np.full(len(FIG3A_MARKER_GENES), np.nan)
        for g in NEURONAL_GROUP_ORDER
    ],
    index=NEURONAL_GROUP_ORDER,
    columns=FIG3A_MARKER_GENES,
)
mus_matched_pct = pd.DataFrame(
    [
        mus_pct.loc[top_bg_match[g], FIG3A_MARKER_GENES].values
        if g not in ob_excluded_groups
        else np.full(len(FIG3A_MARKER_GENES), np.nan)
        for g in NEURONAL_GROUP_ORDER
    ],
    index=NEURONAL_GROUP_ORDER,
    columns=FIG3A_MARKER_GENES,
)

for j, gene in enumerate(FIG3A_MARKER_GENES):
    m_col = mac_sub_mean[gene].values
    m_max = max(float(np.nanmax(m_col)), 1e-6)
    mac_norm_mat[:, j] = m_col / m_max
    mac_pct_mat[:, j] = mac_sub_pct[gene].values

    u_col = mus_matched_mean[gene].values
    if np.isfinite(u_col).any() and np.nanmax(u_col) > 0:
        u_max = float(np.nanmax(u_col))
        mus_norm_mat[:, j] = u_col / u_max
        mus_pct_mat[:, j] = mus_matched_pct[gene].values
        ok = np.isfinite(mus_norm_mat[:, j])
        mac_vals_all.extend(mac_norm_mat[ok, j].tolist())
        mus_vals_all.extend(mus_norm_mat[ok, j].tolist())

    for i, g in enumerate(NEURONAL_GROUP_ORDER):
        marker_rows.append(
            {
                "Group": g,
                "gene": gene,
                "macaque_mean_log2": round(float(mac_sub_mean.iloc[i, j]), 4),
                "macaque_pct": round(float(mac_pct_mat[i, j]), 4),
                "mouse_supertype": "" if g in ob_excluded_groups else str(top_bg_match[g]),
                "mouse_mean_log2": (
                    round(float(mus_matched_mean.iloc[i, j]), 4)
                    if np.isfinite(mus_matched_mean.iloc[i, j])
                    else np.nan
                ),
                "mouse_pct": (
                    round(float(mus_pct_mat[i, j]), 4)
                    if np.isfinite(mus_pct_mat[i, j])
                    else np.nan
                ),
            }
        )

pd.DataFrame(marker_rows).to_csv(out_dir() / "fig3a_conserved_markers_macaque_mouse.csv", index=False)
marker_corr = float(np.corrcoef(mac_vals_all, mus_vals_all)[0, 1])

# ---- Render 3-column Figure 3A matching Cell VoR layout ----
fig = plt.figure(figsize=(19.5, 11.8), dpi=200)
gs = gridspec.GridSpec(
    2,
    3,
    height_ratios=[0.07, 0.93],
    width_ratios=[1.15, 3.0, 4.4],
    wspace=0.05,
    hspace=0.06,
)

ax_bar = fig.add_subplot(gs[1, 0])
ax_hm = fig.add_subplot(gs[1, 1], sharey=ax_bar)
ax_dot = fig.add_subplot(gs[1, 2], sharey=ax_bar)

n_rows = len(NEURONAL_GROUP_ORDER)
y_pos = np.arange(n_rows)

# 1. Left panel: Primate vs. mouse sampling fold change
fcs = np.clip(hom_df.loc[NEURONAL_GROUP_ORDER, "fold_change_primate_vs_mouse"].values, 0.0, 35.0)
bar_cols = [group_colors.get(g, "#666666") for g in NEURONAL_GROUP_ORDER]
ax_bar.barh(y_pos, fcs, height=0.72, color=bar_cols, edgecolor="#333333", linewidth=0.35)
ax_bar.axvline(1.0, color="#c0392b", lw=0.9, ls="-")
ax_bar.set_yticks(y_pos)
ax_bar.set_yticklabels(NEURONAL_GROUP_ORDER, fontsize=7.5)
ax_bar.set_xlim(0, 36)
ax_bar.set_xticks([0, 10, 20, 30])
ax_bar.xaxis.tick_top()
ax_bar.xaxis.set_label_position("top")
ax_bar.set_xlabel("Primate vs. mouse\nsampling (fold change)", fontsize=8.5, labelpad=6)
ax_bar.spines["right"].set_visible(False)
ax_bar.spines["bottom"].set_visible(False)
ax_bar.set_ylim(-0.6, n_rows - 0.4)

# 2. Center panel: Similarity heatmap (Greys, 0..1 clipped/scaled)
hm_vals = np.clip(sim_plot.values, 0.0, 1.0)
cmap_hm = plt.get_cmap("Greys").copy()
cmap_hm.set_bad(color="#f7f7f7")
im = ax_hm.imshow(
    hm_vals,
    aspect="auto",
    origin="lower",
    cmap=cmap_hm,
    vmin=0.0,
    vmax=0.75,
    interpolation="nearest",
)
# Orange highlight box around the 7 classical SPN Groups x 14 mouse SPN supertypes (zoomed in Figure 3B)
n_spn_cols = sum(1 for c in ordered_cols[: len(FIG3B_MOUSE_SPN_SUPERTYPES)] if c in FIG3B_MOUSE_SPN_SUPERTYPES)
rect = patches.Rectangle(
    (-0.5, -0.5),
    n_spn_cols,
    len(CLASSICAL_SPN_GROUPS),
    linewidth=1.6,
    edgecolor="#e67e22",
    facecolor="none",
)
ax_hm.add_patch(rect)
ax_hm.set_xlabel("Mouse Supertype", fontsize=9, labelpad=6)
ax_hm.set_xticks([])
plt.setp(ax_hm.get_yticklabels(), visible=False)
ax_hm.tick_params(axis="y", length=0)

# Similarity colorbar in top-center slot
ax_c1 = fig.add_subplot(gs[0, 1])
ax_c1.axis("off")
cax_sim = ax_c1.inset_axes([0.62, 0.15, 0.34, 0.32])
cb_sim = fig.colorbar(im, cax=cax_sim, orientation="horizontal")
cb_sim.set_ticks([0.0, 0.75])
cb_sim.set_ticklabels(["0", "1"])
cb_sim.ax.tick_params(labelsize=7.5)
cax_sim.set_title("Similarity", fontsize=8.5, pad=3)

# 3. Right panel: Split-semicircle dot-pie chart (Bottom = Macaque Blues, Top = Mouse Oranges)
# Keep exact vertical row alignment with ax_bar and ax_hm by using aspect='auto' with aspect-corrected wedges
cmap_mac = matplotlib.colormaps["Blues"]
cmap_mus = matplotlib.colormaps["Oranges"]
n_genes = len(FIG3A_MARKER_GENES)

# Compute data-to-display aspect ratio so split discs render circular while matching ax_bar/ax_hm height 1:1
fig.subplots_adjust(left=0.145, right=0.985, top=0.95, bottom=0.09)
bbox_dot = ax_dot.get_position()
fig_w, fig_h = fig.get_size_inches()
px_per_x = (bbox_dot.width * fig_w) / (n_genes + 0.4)
px_per_y = (bbox_dot.height * fig_h) / (n_rows + 0.2)
r_y_max = 0.42
r_x_max = r_y_max * (px_per_y / px_per_x)
angles_top = np.linspace(0.0, np.pi, 24)
angles_bot = np.linspace(np.pi, 2.0 * np.pi, 24)

for i in range(n_rows):
    for j in range(n_genes):
        p_mac = float(mac_pct_mat[i, j])
        if p_mac >= 0.05:
            scale = np.sqrt(min(p_mac, 1.0))
            rx, ry = r_x_max * scale, r_y_max * scale
            verts = np.column_stack([j + rx * np.cos(angles_bot), i + ry * np.sin(angles_bot)])
            col_mac = cmap_mac(0.15 + 0.85 * float(mac_norm_mat[i, j]))
            ax_dot.add_patch(patches.Polygon(verts, closed=True, facecolor=col_mac, edgecolor="none"))
        p_mus = float(mus_pct_mat[i, j]) if np.isfinite(mus_pct_mat[i, j]) else 0.0
        if p_mus >= 0.05 and np.isfinite(mus_norm_mat[i, j]):
            scale = np.sqrt(min(p_mus, 1.0))
            rx, ry = r_x_max * scale, r_y_max * scale
            verts = np.column_stack([j + rx * np.cos(angles_top), i + ry * np.sin(angles_top)])
            col_mus = cmap_mus(0.15 + 0.85 * float(mus_norm_mat[i, j]))
            ax_dot.add_patch(patches.Polygon(verts, closed=True, facecolor=col_mus, edgecolor="none"))

ax_dot.set_xlim(-0.7, n_genes - 0.3)
ax_dot.set_xticks(np.arange(n_genes))
ax_dot.set_xticklabels(FIG3A_MARKER_GENES, rotation=90, fontsize=6.5)
plt.setp(ax_dot.get_yticklabels(), visible=False)
ax_dot.tick_params(axis="y", length=0)
ax_dot.set_facecolor("white")

# Legends in top-right slot (explicit 0..1 axes limits so Proportion never overlaps colorbars)
ax_c2 = fig.add_subplot(gs[0, 2])
ax_c2.set_xlim(0.0, 1.0)
ax_c2.set_ylim(0.0, 1.0)
ax_c2.axis("off")
for idx_p, prop_v in enumerate([0.25, 0.5, 1.0]):
    ax_c2.scatter([0.08], [0.72 - idx_p * 0.28], s=(prop_v * 58), color="#888888")
    ax_c2.text(0.12, 0.72 - idx_p * 0.28, f"{prop_v}", va="center", fontsize=7.5)
ax_c2.text(0.10, 0.96, "Proportion", ha="center", va="bottom", fontsize=8.5)

cax_mac = ax_c2.inset_axes([0.30, 0.18, 0.26, 0.30])
sm_mac = cm.ScalarMappable(cmap=cmap_mac, norm=plt.Normalize(0, 1))
cb_mac = fig.colorbar(sm_mac, cax=cax_mac, orientation="horizontal")
cb_mac.set_ticks([0, 1])
cb_mac.ax.tick_params(labelsize=7.5)
cax_mac.set_title("Macaque (bottom half)", fontsize=8, pad=3)

cax_mus = ax_c2.inset_axes([0.66, 0.18, 0.26, 0.30])
sm_mus = cm.ScalarMappable(cmap=cmap_mus, norm=plt.Normalize(0, 1))
cb_mus = fig.colorbar(sm_mus, cax=cax_mus, orientation="horizontal")
cb_mus.set_ticks([0, 1])
cb_mus.ax.tick_params(labelsize=7.5)
cax_mus.set_title("Mouse (top half)", fontsize=8, pad=3)

fig.savefig(out_dir() / "fig3a.png", dpi=200)
plt.close(fig)

med_fc = float(hom_df["fold_change_primate_vs_mouse"].median())
med_fc_neuronal = float(hom_df.loc[NEURONAL_GROUP_ORDER, "fold_change_primate_vs_mouse"].median())

metrics = {
    "n_shared_orthologs": int(res["n_shared_orthologs"]),
    "n_mouse_supertypes_ge50": int(sim_df.shape[1]),
    "n_neuronal_groups_plotted": int(len(NEURONAL_GROUP_ORDER)),
    "n_marker_genes_plotted": int(len(FIG3A_MARKER_GENES)),
    "median_primate_vs_mouse_sampling_fc": round(med_fc, 4),
    "median_primate_vs_mouse_sampling_fc_neuronal": round(med_fc_neuronal, 4),
    "primate_exceeds_mouse_sampling_depth": bool(med_fc > 1.0 and med_fc_neuronal > 1.0),
    "n_curated_groups_table_s12": int(n_curated),
    "n_exact_supertype_matches_table_s12": int(n_exact_st),
    "n_concordant_groups_table_s12": int(n_concordant),
    "homology_concordance_pct_with_table_s12": concordance_pct,
    "conserved_marker_macaque_mouse_pearson_r": round(marker_corr, 4),
    "conserved_marker_macaque_mouse_corr_positive": bool(marker_corr > 0.5),
}
write_metrics(metrics)
print(metrics)
