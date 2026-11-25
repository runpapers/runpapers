# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8"]
# ///
"""Figure 6D (right): Macaque MERSCOPE striosome neighborhood enrichment z-scores across
coronal sections for five dorsal striatal SPN Groups:
  STRd D1 Striosome SPN, STRd D2 Striosome SPN, STR D2 SMYD2-HTR7 SPN,
  STRd D1 Matrix SPN, and STRd D2 Matrix SPN.

Computes permutation-standardized spatial neighborhood enrichment z-scores (k=6 nearest
striatal neighbors, 200 deterministic permutations) across all registered coronal striatal
slab planes (and also exports tile-level brain_section_label z-scores for reference).

Note: The left-hand DAPI single-transcript microscopy inset in published Figure 6D is a
microscopy image asset and is excluded from this recipe.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from bg_spatial import SPN_GROUP_COLORS, load_primate_spatial, out_dir, write_metrics

GROUPS_5 = [
    "STRd D1 Striosome SPN",
    "STRd D2 Striosome SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STRd D1 Matrix SPN",
    "STRd D2 Matrix SPN",
]
STRIO_SET = {"STRd D1 Striosome SPN", "STRd D2 Striosome SPN"}
SHORT_LABELS = [
    "STRd D1\nStriosome",
    "STRd D2\nStriosome",
    "STR D2\nSMYD2",
    "STRd D1\nMatrix",
    "STRd D2\nMatrix",
]

seed = int(os.environ.get("RP_SEED", "0"))
rng = np.random.default_rng(seed)

df = load_primate_spatial("macaque_merscope", need_section=True)
# Restrict to striatal SPNs inside STR == True so the permutation null tests striosome vs. matrix
# compartmentalization among SPNs without confounding from white-matter oligodendrocyte fiber bundles.
SPN_ALL = {
    "STRd D1 Striosome SPN",
    "STRd D2 Striosome SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STRd D1 Matrix SPN",
    "STRd D2 Matrix SPN",
    "STRv D1 SPN",
    "STRv D2 SPN",
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
}
df_str = df[
    (df["STR"] == True)
    & df["Group"].isin(SPN_ALL)
    & df["x_slab_mm"].notna()
    & df["y_slab_mm"].notna()
].copy()


def compute_striosome_z(frame: pd.DataFrame, sec_col: str, k_nbrs: int = 6, n_perm: int = 200, min_cells: int = 1000):
    rows = []
    for sec, sdf in frame.groupby(sec_col):
        if len(sdf) < min_cells:
            continue
        is_strio = sdf["Group"].isin(STRIO_SET).values
        n_strio = int(is_strio.sum())
        if n_strio < 50 or n_strio > len(sdf) - 50:
            continue
        coords = sdf[["x_slab_mm", "y_slab_mm"]].values
        tree = cKDTree(coords)
        _, idx = tree.query(coords, k=k_nbrs + 1, workers=4)
        nbr = idx[:, 1:]

        # Map groups to compact integer codes 0..4 (other cells = 5)
        g_code = np.full(len(sdf), 5, dtype=np.int32)
        for gi, gname in enumerate(GROUPS_5):
            g_code[sdf["Group"].values == gname] = gi

        # Observed directed edges from each group to striosome cells
        strio_nbr_cnt = is_strio[nbr].sum(axis=1)
        obs = np.bincount(g_code, weights=strio_nbr_cnt, minlength=6)[:5]
        ng = np.bincount(g_code, minlength=6)[:5]

        # Vectorized permutation null over cell label permutations on the fixed kNN graph
        perm_vals = np.empty((n_perm, 5), dtype=np.float64)
        n_tot = len(sdf)
        for pi in range(n_perm):
            p_idx = rng.permutation(n_tot)
            p_strio = is_strio[p_idx]
            p_code = g_code[p_idx]
            p_nbr_cnt = p_strio[nbr].sum(axis=1)
            perm_vals[pi] = np.bincount(p_code, weights=p_nbr_cnt, minlength=6)[:5]

        mu = perm_vals.mean(axis=0)
        sd = perm_vals.std(axis=0, ddof=1)
        for gi, gname in enumerate(GROUPS_5):
            if ng[gi] < 20 or sd[gi] <= 0:
                continue
            z = float((obs[gi] - mu[gi]) / sd[gi])
            rows.append(
                {
                    "section_level": sec_col,
                    "section": str(sec),
                    "Group": gname,
                    "n_cells": int(ng[gi]),
                    "obs_strio_edges": float(obs[gi]),
                    "null_mean": round(float(mu[gi]), 3),
                    "null_sd": round(float(sd[gi]), 3),
                    "z_score": round(z, 4),
                }
            )
    return pd.DataFrame(rows)


# Primary: registered coronal striatal slab planes (matching published ~27 coronal sections)
z_slab = compute_striosome_z(df_str, "slab_plane_label", k_nbrs=6, n_perm=200, min_cells=1000)
# Secondary audit: individual MERSCOPE tissue tiles (brain_section_label)
z_tile = compute_striosome_z(df_str, "brain_section_label", k_nbrs=6, n_perm=100, min_cells=1000)

pd.concat([z_slab, z_tile], ignore_index=True).to_csv(out_dir() / "fig6d_striosome_zscores.csv", index=False)

med_slab = z_slab.groupby("Group")["z_score"].median().to_dict()
med_tile = z_tile.groupby("Group")["z_score"].median().to_dict()

# Plot matching published Figure 6D right-hand stripplot style
fig, ax = plt.subplots(figsize=(4.8, 5.4), dpi=200)
plot_rng = np.random.default_rng(seed)

for gi, gname in enumerate(GROUPS_5):
    vals = z_slab.loc[z_slab["Group"] == gname, "z_score"].values
    col = SPN_GROUP_COLORS[gname]
    jitter = plot_rng.uniform(-0.18, 0.18, size=len(vals))
    # Vertical min-max whisker + horizontal median bar + colored section dots
    ax.plot([gi, gi], [vals.min(), vals.max()], color="#888888", lw=0.9, zorder=1)
    ax.scatter(gi + jitter, vals, s=22, color=col, edgecolors="white", linewidths=0.25, alpha=0.92, zorder=3)
    med = float(np.median(vals))
    ax.plot([gi - 0.25, gi + 0.25], [med, med], color="black", lw=1.6, zorder=4)

ax.axhline(0.0, color="#666666", ls="--", lw=0.9, zorder=0)
ax.set_xticks(range(len(GROUPS_5)))
ax.set_xticklabels(SHORT_LABELS, rotation=90, fontsize=8.5)
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")
ax.set_ylabel("Striosome enrichment z-score", fontsize=9.5, labelpad=8)
ax.set_xlim(-0.6, len(GROUPS_5) - 0.4)
ax.set_title(f"Macaque Striosome Enrichment\n(n={z_slab['section'].nunique()} coronal sections)", fontsize=9.5, pad=8)
fig.text(
    0.5,
    0.01,
    "Figure 6D right (DAPI single-transcript microscopy inset excluded).",
    ha="center",
    fontsize=7,
    color="#555555",
)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(out_dir() / "fig6d.png", dpi=200)
plt.close(fig)

z_d1s = float(med_slab["STRd D1 Striosome SPN"])
z_d2s = float(med_slab["STRd D2 Striosome SPN"])
z_smy = float(med_slab["STR D2 SMYD2-HTR7 SPN"])
z_d1m = float(med_slab["STRd D1 Matrix SPN"])
z_d2m = float(med_slab["STRd D2 Matrix SPN"])

min_abs_comp = min(abs(z_d1s), abs(z_d2s), abs(z_d1m), abs(z_d2m))

metrics = {
    "n_spn_groups_plotted": 5,
    "n_coronal_slabs": int(z_slab["section"].nunique()),
    "n_merscope_tiles": int(z_tile["section"].nunique()),
    "median_z_d1_striosome": round(z_d1s, 3),
    "median_z_d2_striosome": round(z_d2s, 3),
    "median_z_smyd2": round(z_smy, 3),
    "median_z_d1_matrix": round(z_d1m, 3),
    "median_z_d2_matrix": round(z_d2m, 3),
    "tile_median_z_smyd2": round(float(med_tile["STR D2 SMYD2-HTR7 SPN"]), 3),
    "striosome_groups_positive_z": bool(z_d1s > 0 and z_d2s > 0),
    "matrix_groups_negative_z": bool(z_d1m < 0 and z_d2m < 0),
    "smyd2_near_neutral_relative_to_striosome_and_matrix": bool(abs(z_smy) < 0.25 * min_abs_comp),
    "exact_ordering_striosome_gt_smyd2_gt_matrix": bool(min(z_d1s, z_d2s) > z_smy > max(z_d1m, z_d2m)),
}
write_metrics(metrics)
print(metrics)
