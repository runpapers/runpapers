# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "anndata>=0.11", "matplotlib>=3.8"]
# ///
"""Figure 6A: dot plot of 28 marker genes, ion channels, and neurotransmitter receptors across four
striatal SPN Groups (STR D2 SMYD2-HTR7 SPN, STRd D2 Striosome SPN, STRd D2 Matrix SPN, STR D1D2 eSPN)
averaged across Human, Macaque, and Marmoset.

Dot area encodes relative expression across the four Groups (normalized to the per-gene maximum,
matching the 'Max / 50% / 25%' legend of published Figure 6A); dot color encodes row-wise gene
expression Z-score (-2 to +2, RdBu_r). Left-hand category and receptor-family bars match Figure 6A."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_atlas import SPECIES, group_order, load_pseudobulk_log2, out_dir, write_metrics

GROUPS = [
    "STR D2 SMYD2-HTR7 SPN",
    "STRd D2 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STR D1D2 eSPN",
]
GROUP_SHORT = [
    "STR D2\nSMYD2",
    "STRd D2\nStriosome",
    "STRd D2\nMatrix",
    "STR D1D2\neSPN",
]

# Exact 28 rows and category annotations from published Figure 6A
GENE_SPEC = [
    ("SMYD2", "Markers", "", "#2c3e50"),
    ("PTN", "Markers", "", "#2c3e50"),
    ("TTN", "Markers", "", "#2c3e50"),
    ("STXBP6", "Markers", "", "#2c3e50"),
    ("KCNIP1", "Markers", "", "#2c3e50"),
    ("GRIK1", "Markers", "", "#2c3e50"),
    ("KCNJ3", "Ion Channels", "Kir", "#3b75af"),
    ("KCNJ6", "Ion Channels", "Kir", "#3b75af"),
    ("CACNA2D2", "Ion Channels", "Ca²⁺", "#1a9850"),
    ("CACNA1G", "Ion Channels", "Ca²⁺", "#1a9850"),
    ("KCNA6", "Ion Channels", "Kv", "#756bb1"),
    ("HCN1", "Ion Channels", "HCN", "#a6761d"),
    ("SCN9A", "Ion Channels", "Na⁺", "#d73027"),
    ("DRD2", "Neurotransmitter receptors", "Dopamine", "#e67e22"),
    ("DRD1", "Neurotransmitter receptors", "Dopamine", "#e67e22"),
    ("DRD3", "Neurotransmitter receptors", "Dopamine", "#e67e22"),
    ("HTR7", "Neurotransmitter receptors", "Serotonin", "#c0392b"),
    ("HTR2A", "Neurotransmitter receptors", "Serotonin", "#c0392b"),
    ("HTR4", "Neurotransmitter receptors", "Serotonin", "#c0392b"),
    ("HTR6", "Neurotransmitter receptors", "Serotonin", "#c0392b"),
    ("CHRM2", "Neurotransmitter receptors", "Acetylcholine", "#8e44ad"),
    ("CHRM5", "Neurotransmitter receptors", "Acetylcholine", "#8e44ad"),
    ("CHRM3", "Neurotransmitter receptors", "Acetylcholine", "#8e44ad"),
    ("CHRM4", "Neurotransmitter receptors", "Acetylcholine", "#8e44ad"),
    ("OPRK1", "Neurotransmitter receptors", "Opioid", "#e7298a"),
    ("OPRM1", "Neurotransmitter receptors", "Opioid", "#e7298a"),
    ("OPRD1", "Neurotransmitter receptors", "Opioid", "#e7298a"),
    ("ADORA2A", "Neurotransmitter receptors", "Adenosine", "#636e72"),
]
GENES = [g[0] for g in GENE_SPEC]
EXTRA_CHECK_GENES = ["KCNT2", "RXFP1"]

pb = load_pseudobulk_log2()
sp_group_mean = pb["sp_group_mean"]
sp_group_pct = pb["sp_group_pct"]
_, grp_colors = group_order()
grp_colors = dict(grp_colors)
grp_colors["STR D2 SMYD2-HTR7 SPN"] = "#54278f"

all_q = GENES + EXTRA_CHECK_GENES
mean_3sp = sum(sp_group_mean[sp].loc[GROUPS, all_q] for sp in SPECIES) / 3.0
pct_3sp = sum(sp_group_pct[sp].loc[GROUPS, all_q] for sp in SPECIES) / 3.0

# Z-score across the 4 Groups per gene (population std ddof=0 to span [-1.73, +1.73] cleanly, matching -2..+2)
mu = mean_3sp.mean(axis=0)
sd = mean_3sp.std(axis=0, ddof=0).replace(0, 1.0)
z_df = (mean_3sp - mu) / sd
rel_df = mean_3sp.div(mean_3sp.max(axis=0).replace(0, 1.0), axis=1)

mean_3sp.to_csv(out_dir() / "fig6a_mean_expr.csv")
pct_3sp.to_csv(out_dir() / "fig6a_pct_expr.csv")
z_df.to_csv(out_dir() / "fig6a_zscore.csv")

enriched_10 = ["SMYD2", "PTN", "TTN", "HTR7", "GRIK1", "KCNT2", "CACNA2D2", "CACNA1G", "HCN1", "CHRM2"]
canon_d2 = ["STRd D2 Striosome SPN", "STRd D2 Matrix SPN"]
n_enriched_pos = sum(
    float(mean_3sp.loc["STR D2 SMYD2-HTR7 SPN", g]) > float(mean_3sp.loc[canon_d2, g].mean())
    for g in enriched_10
)

m = {
    "n_genes_plotted": int(len(GENES)),
    "n_groups_plotted": int(len(GROUPS)),
    "smyd2_top_group": str(mean_3sp["SMYD2"].idxmax()),
    "htr7_top_group": str(mean_3sp["HTR7"].idxmax()),
    "rxfp1_top_group": str(mean_3sp["RXFP1"].idxmax()),
    "smyd2_z_in_smyd2_group": round(float(z_df.loc["STR D2 SMYD2-HTR7 SPN", "SMYD2"]), 4),
    "htr7_z_in_smyd2_group": round(float(z_df.loc["STR D2 SMYD2-HTR7 SPN", "HTR7"]), 4),
    "rxfp1_mean_smyd2": round(float(mean_3sp.loc["STR D2 SMYD2-HTR7 SPN", "RXFP1"]), 4),
    "rxfp1_mean_espn": round(float(mean_3sp.loc["STR D1D2 eSPN", "RXFP1"]), 4),
    "rxfp1_depleted_vs_espn": bool(
        float(mean_3sp.loc["STR D2 SMYD2-HTR7 SPN", "RXFP1"]) < 0.25 * float(mean_3sp.loc["STR D1D2 eSPN", "RXFP1"])
    ),
    "n_of_10_markers_enriched_vs_canon_d2": int(n_enriched_pos),
}

# Plot matching published Figure 6A
fig = plt.figure(figsize=(6.4, 10.6))
ax_cat = fig.add_axes([0.04, 0.11, 0.25, 0.81])
ax = fig.add_axes([0.39, 0.11, 0.36, 0.81])
ax_gcol = fig.add_axes([0.39, 0.095, 0.36, 0.015])

n_g = len(GENES)
# Subtle lavender background on column 0 (STR D2 SMYD2-HTR7 SPN)
ax.axvspan(-0.5, 0.5, color="#ede7f6", alpha=0.75, zorder=0)

# Horizontal grid & category separator lines
for y in range(n_g):
    ax.axhline(y, color="#e6e6e6", lw=0.45, zorder=1)
for x in range(len(GROUPS)):
    ax.axvline(x, color="#e6e6e6", lw=0.45, zorder=1)
# Major dividers after Markers (5.5) and Ion Channels (12.5)
for sep_y in [5.5, 12.5]:
    ax.axhline(sep_y, color="#444444", lw=0.85, zorder=2)
# Sub-category light dividers
for sep_y in [7.5, 9.5, 10.5, 11.5, 15.5, 19.5, 23.5, 26.5]:
    ax.axhline(sep_y, color="#999999", lw=0.45, zorder=2)

# Plot dots (size = relative expression; color = Z-score)
for gi, gene in enumerate(GENES):
    for ci, grp in enumerate(GROUPS):
        rel = float(rel_df.loc[grp, gene])
        zv = float(z_df.loc[grp, gene])
        size = np.clip(rel * 165.0, 12.0, 180.0)
        ax.scatter(
            [ci],
            [gi],
            s=size,
            c=[zv],
            cmap="RdBu_r",
            vmin=-2.0,
            vmax=2.0,
            edgecolors="#333333",
            linewidths=0.45,
            zorder=4,
        )

ax.set_xlim(-0.5, len(GROUPS) - 0.5)
ax.set_ylim(n_g - 0.5, -0.5)
ax.set_yticks(range(n_g))
ax.set_yticklabels(GENES, fontsize=8.3)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, pad=5)
for sp_name in ("top", "right", "bottom", "left"):
    ax.spines[sp_name].set_color("#222222")
    ax.spines[sp_name].set_linewidth(0.9)

# Bottom Group color bar + rotated Group labels
for ci, grp in enumerate(GROUPS):
    ax_gcol.add_patch(mpatches.Rectangle((ci - 0.5, 0), 1.0, 1.0, facecolor=grp_colors[grp], edgecolor="none"))
ax_gcol.set_xlim(-0.5, len(GROUPS) - 0.5)
ax_gcol.set_ylim(0, 1)
ax_gcol.set_xticks(range(len(GROUPS)))
ax_gcol.set_xticklabels(GROUP_SHORT, rotation=42, ha="right", fontsize=8.5)
ax_gcol.set_yticks([])
for sp_name in ("top", "right", "bottom", "left"):
    ax_gcol.spines[sp_name].set_visible(False)
ax_gcol.tick_params(axis="x", length=0, pad=3)

# Left-hand category and subcategory bars
ax_cat.set_xlim(0, 1)
ax_cat.set_ylim(n_g - 0.5, -0.5)
ax_cat.axis("off")

# Major category labels on far left
for y0, y1, lbl in [(0, 5, "Markers"), (6, 12, "Ion Channels"), (13, 27, "Neurotransmitter receptors")]:
    ax_cat.text(0.18, (y0 + y1) / 2.0, lbl, rotation=90, ha="center", va="center", fontsize=10.0, fontweight="bold", color="#111111")

# Subcategory vertical bars and colored labels
sub_runs = []
s_i = 0
for i in range(1, n_g + 1):
    if i == n_g or (GENE_SPEC[i][1], GENE_SPEC[i][2]) != (GENE_SPEC[s_i][1], GENE_SPEC[s_i][2]):
        sub_runs.append((s_i, i - 1, GENE_SPEC[s_i][2], GENE_SPEC[s_i][3]))
        s_i = i

for y0, y1, sub_lbl, col in sub_runs:
    ax_cat.plot([0.46, 0.46], [y0 - 0.35, y1 + 0.35], color=col, lw=3.0, solid_capstyle="butt")
    if sub_lbl:
        rot = 90 if (y1 - y0) >= 2 else 0
        ax_cat.text(0.55, (y0 + y1) / 2.0, sub_lbl, rotation=rot, ha="left", va="center", fontsize=8.2, color=col, fontweight="bold")

# Right-hand colorbar (Z-score) and relative-expression size legend
cax = fig.add_axes([0.79, 0.56, 0.035, 0.25])
sm = cm.ScalarMappable(norm=mcolors.Normalize(-2.0, 2.0), cmap="RdBu_r")
cb = fig.colorbar(sm, cax=cax)
cb.set_ticks([-2, -1, 0, 1, 2])
cb.set_label("Gene expression\nZ-score", fontsize=8.2, rotation=270, labelpad=20)
cb.ax.tick_params(labelsize=7.5)

ax_sz = fig.add_axes([0.77, 0.28, 0.21, 0.22])
ax_sz.set_xlim(0, 1)
ax_sz.set_ylim(0, 1)
ax_sz.axis("off")
ax_sz.text(0.05, 0.95, "Relative\nexpression:", ha="left", va="top", fontsize=8.2, fontweight="bold")
for yv, frac, lbl in [(0.56, 1.0, "Max"), (0.34, 0.5, "50%"), (0.14, 0.25, "25%")]:
    ax_sz.scatter([0.22], [yv], s=np.clip(frac * 165.0, 12.0, 180.0), color="#b0b0b0", edgecolors="#333333", lw=0.5)
    ax_sz.text(0.45, yv, lbl, va="center", ha="left", fontsize=8.0)

fig.suptitle("Figure 6A: STR D2 SMYD2-HTR7 SPN markers, channels & receptors", fontsize=9.8, fontweight="bold", y=0.97)
fig.savefig(out_dir() / "fig6a.png", dpi=180)
write_metrics(m)
print(m)
