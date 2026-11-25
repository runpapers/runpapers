# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8"]
# ///
"""Figure 1E (top row): Macaque MERSCOPE spatial transcriptomics of six striatal SPN Groups
across an anterior coronal striatal section:
  - Left:   STRd D1 Matrix SPN + STRd D2 Matrix SPN
  - Center: STRd D1 Striosome SPN + STRd D2 Striosome SPN
  - Right:  STR D2 SMYD2-HTR7 SPN + STR D1D2 eSPN

Note: Middle neuron morphology reconstructions and bottom Patch-seq voltage traces in published
Figure 1E are companion wet-lab assets and are excluded from this spatial transcriptomics recipe.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from bg_spatial import SPN_GROUP_COLORS, load_primate_spatial, out_dir, write_metrics

SPN6 = [
    "STRd D1 Matrix SPN",
    "STRd D2 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Striosome SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
]

df = load_primate_spatial("macaque_merscope")
df_str = df[(df["STR"] == True) & df["x_slab_mm"].notna() & df["y_slab_mm"].notna()].copy()
df_spn = df_str[df_str["Group"].isin(SPN6)].copy()

# Deterministic selection: registered coronal striatal slab plane with the largest dorsal/eccentric SPN6 count
slab_counts = df_spn.groupby("slab_plane_label").size().sort_values(ascending=False)
best_slab = str(slab_counts.index[0])

sec_all = df_str[df_str["slab_plane_label"] == best_slab].copy()
sec_spn = df_spn[df_spn["slab_plane_label"] == best_slab].copy()

# Spatial clustering verification (k=15 nearest SPN neighbors): striosome self-enrichment vs matrix self-enrichment
coords = sec_spn[["x_slab_mm", "y_slab_mm"]].values
tree = cKDTree(coords)
_, idx = tree.query(coords, k=16)
nbr_idx = idx[:, 1:]

is_strio = sec_spn["Group"].isin(["STRd D1 Striosome SPN", "STRd D2 Striosome SPN"]).values
is_mat = sec_spn["Group"].isin(["STRd D1 Matrix SPN", "STRd D2 Matrix SPN"]).values

p_strio = float(is_strio.mean())
p_mat = float(is_mat.mean())
strio_self_nbr_frac = float(is_strio[nbr_idx[is_strio]].mean())
mat_self_nbr_frac = float(is_mat[nbr_idx[is_mat]].mean())
strio_enrichment_ratio = strio_self_nbr_frac / max(p_strio, 1e-9)
mat_enrichment_ratio = mat_self_nbr_frac / max(p_mat, 1e-9)

grp_counts_sec = sec_spn["Group"].value_counts().reindex(SPN6, fill_value=0)
grp_counts_all = df_spn["Group"].value_counts().reindex(SPN6, fill_value=0)

summary_df = pd.DataFrame(
    {
        "Group": SPN6,
        "section_cells": [int(grp_counts_sec[g]) for g in SPN6],
        "section_spn6_pct": [round(100.0 * grp_counts_sec[g] / max(len(sec_spn), 1), 3) for g in SPN6],
        "all_str_cells": [int(grp_counts_all[g]) for g in SPN6],
        "slab_plane_label": best_slab,
    }
)
summary_df.to_csv(out_dir() / "fig1e_macaque_spn_counts.csv", index=False)

n_mat = int(grp_counts_sec["STRd D1 Matrix SPN"] + grp_counts_sec["STRd D2 Matrix SPN"])
n_strio = int(grp_counts_sec["STRd D1 Striosome SPN"] + grp_counts_sec["STRd D2 Striosome SPN"])
n_smyd2 = int(grp_counts_sec["STR D2 SMYD2-HTR7 SPN"])

# Plot 3 subpanels oriented dorsal-up (-y_slab_mm) with 4 mm scale bar matching Figure 1E top row
x_all = sec_all["x_slab_mm"].values
y_all = -sec_all["y_slab_mm"].values

fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.6), dpi=200)
panels = [
    (
        "Matrix SPNs",
        ["STRd D1 Matrix SPN", "STRd D2 Matrix SPN"],
        [SPN_GROUP_COLORS["STRd D1 Matrix SPN"], SPN_GROUP_COLORS["STRd D2 Matrix SPN"]],
        0.55,
    ),
    (
        "Striosome SPNs",
        ["STRd D1 Striosome SPN", "STRd D2 Striosome SPN"],
        [SPN_GROUP_COLORS["STRd D1 Striosome SPN"], SPN_GROUP_COLORS["STRd D2 Striosome SPN"]],
        0.70,
    ),
    (
        "SMYD2-HTR7 & eSPN",
        ["STR D2 SMYD2-HTR7 SPN", "STR D1D2 eSPN"],
        [SPN_GROUP_COLORS["STR D2 SMYD2-HTR7 SPN"], SPN_GROUP_COLORS["STR D1D2 eSPN"]],
        1.10,
    ),
]

x_min, x_max = float(x_all.min()), float(x_all.max())
y_min, y_max = float(y_all.min()), float(y_all.max())
pad = 0.6

for pi, (ax, (ttl, grps, cols, pt_sz)) in enumerate(zip(axes, panels)):
    ax.scatter(x_all, y_all, s=0.12, c="#ebebeb", alpha=0.7, linewidths=0, rasterized=True)
    for g, col in zip(grps, cols):
        sub = sec_spn[sec_spn["Group"] == g]
        ax.scatter(
            sub["x_slab_mm"].values,
            -sub["y_slab_mm"].values,
            s=pt_sz,
            c=col,
            alpha=0.85,
            linewidths=0,
            label=f"{g} (n={len(sub):,})",
            rasterized=True,
        )
    if pi == 0:
        # 4 mm scale bar at bottom-right matching published Figure 1E
        sb_x1 = x_max - 0.3
        sb_x0 = sb_x1 - 4.0
        sb_y = y_min + 0.5
        ax.plot([sb_x0, sb_x1], [sb_y, sb_y], color="black", lw=2.0)
        ax.text((sb_x0 + sb_x1) / 2.0, sb_y - 0.55, "4 mm", ha="center", va="top", fontsize=9)
    ax.set_xlim(x_min - pad, x_max + pad)
    ax.set_ylim(y_min - 1.2, y_max + pad)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(ttl, fontsize=10, fontweight="bold", pad=4)
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, -0.14), frameon=False, fontsize=7.5, markerscale=5.5)

fig.suptitle(
    f"Macaque MERSCOPE spatial distribution of six SPN Groups ({best_slab})",
    fontsize=11,
    y=0.98,
)
fig.text(
    0.5,
    0.01,
    "Spatial transcriptomics (top row of Figure 1E); neuron morphologies and voltage traces are companion wet-lab assets.",
    ha="center",
    fontsize=7.5,
    color="#555555",
)
fig.tight_layout(rect=(0, 0.04, 1, 0.94))
fig.savefig(out_dir() / "fig1e.png", dpi=200)
plt.close(fig)

metrics = {
    "slab_plane_label": best_slab,
    "n_str_cells_section": int(len(sec_all)),
    "n_spn6_cells_section": int(len(sec_spn)),
    "n_spn_groups_plotted": int(len(SPN6)),
    "all_six_spn_groups_present": bool((grp_counts_sec > 0).all()),
    "n_d1_matrix": int(grp_counts_sec["STRd D1 Matrix SPN"]),
    "n_d2_matrix": int(grp_counts_sec["STRd D2 Matrix SPN"]),
    "n_d1_striosome": int(grp_counts_sec["STRd D1 Striosome SPN"]),
    "n_d2_striosome": int(grp_counts_sec["STRd D2 Striosome SPN"]),
    "n_smyd2": n_smyd2,
    "n_espn": int(grp_counts_sec["STR D1D2 eSPN"]),
    "matrix_more_abundant_than_striosome_and_smyd2": bool(n_mat > n_strio and n_strio > n_smyd2),
    "striosome_self_nbr_enrichment": round(strio_enrichment_ratio, 4),
    "matrix_self_nbr_enrichment": round(mat_enrichment_ratio, 4),
    "striosome_more_clustered_than_matrix": bool(strio_enrichment_ratio > mat_enrichment_ratio),
}
write_metrics(metrics)
print(metrics)
