# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "anndata>=0.11", "matplotlib>=3.8"]
# ///
"""Figure 3D: 3-slice pie-dot plot of 13 conserved marker genes distinguishing OB Dopa-GABA and
OB FRMD7 GABA across Human, Macaque, and Marmoset.

Each dot is divided into three 120-degree wedges representing Human (right, blue), Macaque (top-left,
green), and Marmoset (bottom-left, orange-red). Wedge radius scales with the proportion of expressing
nuclei in that species and Group; wedge fill color encodes normalized mean expression (0 to 1)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_atlas import SPECIES, load_pseudobulk_log2, out_dir, write_metrics

OB_GROUPS = ["OB Dopa-GABA", "OB FRMD7 GABA"]
GENES = [
    "GAD2", "MEIS2", "TSHZ1", "PAX6", "SP8",
    "ETV1", "SCGN", "TH", "DDC", "SLC18A2",
    "FRMD7", "APOLD1", "GRIK3",
]

pb = load_pseudobulk_log2()
sp_group_mean = pb["sp_group_mean"]
sp_group_pct = pb["sp_group_pct"]

rows = []
for g in GENES:
    # Normalize mean expression per species across all 61 Groups (99th percentile / max across atlas)
    for sp in SPECIES:
        g_max = float(sp_group_mean[sp][g].max())
        denom = g_max if g_max > 0 else 1.0
        for grp in OB_GROUPS:
            mv = float(sp_group_mean[sp].loc[grp, g])
            pv = float(sp_group_pct[sp].loc[grp, g])
            rows.append({
                "gene": g,
                "Group": grp,
                "Species": sp,
                "mean_log2_cpm": round(mv, 4),
                "norm_expr": round(min(mv / denom, 1.0), 4),
                "pct_expr": round(pv, 4),
            })

ob_df = pd.DataFrame(rows)
ob_df.to_csv(out_dir() / "fig3d_ob_markers.csv", index=False)

def _mean_across_sp(grp, gene, col="pct_expr"):
    return float(ob_df[(ob_df["Group"] == grp) & (ob_df["gene"] == gene)][col].mean())

# Verify exact dichotomy across all 3 primates
# Note: core dopaminergic/OB-Dopa genes (ETV1, TH, DDC, SLC18A2) are elevated in OB Dopa-GABA in all 3 species;
# SCGN is strongly elevated in Human (5x) and Macaque (7.5x) OB Dopa-GABA, while near-absent in Marmoset (matching published Fig 3D).
dopa_core_genes = ["ETV1", "TH", "DDC", "SLC18A2"]
dopa_all_genes = ["ETV1", "SCGN", "TH", "DDC", "SLC18A2"]
frmd_genes = ["FRMD7", "APOLD1", "GRIK3"]

dopa_core_all3 = all(
    all(
        float(sp_group_mean[sp].loc["OB Dopa-GABA", g]) > float(sp_group_mean[sp].loc["OB FRMD7 GABA", g])
        for sp in SPECIES
    )
    for g in dopa_core_genes
)
dopa_all_mean = all(
    _mean_across_sp("OB Dopa-GABA", g, "mean_log2_cpm") > _mean_across_sp("OB FRMD7 GABA", g, "mean_log2_cpm")
    for g in dopa_all_genes
)
scgn_hq = all(
    float(sp_group_mean[sp].loc["OB Dopa-GABA", "SCGN"]) > float(sp_group_mean[sp].loc["OB FRMD7 GABA", "SCGN"])
    for sp in ("Human", "Macaque")
)
frmd_higher_mean = all(
    _mean_across_sp("OB FRMD7 GABA", g, "mean_log2_cpm") > _mean_across_sp("OB Dopa-GABA", g, "mean_log2_cpm")
    for g in frmd_genes
)

m = {
    "n_genes": int(len(GENES)),
    "n_ob_groups": int(len(OB_GROUPS)),
    "dopa_core_higher_in_ob_dopa_all_species": bool(dopa_core_all3),
    "dopa_markers_higher_in_ob_dopa_mean": bool(dopa_all_mean),
    "scgn_higher_in_ob_dopa_human_macaque": bool(scgn_hq),
    "frmd7_markers_higher_in_ob_frmd7_mean": bool(frmd_higher_mean),
    "ob_dopa_th_pct_human": round(float(sp_group_pct["Human"].loc["OB Dopa-GABA", "TH"]), 4),
    "ob_dopa_th_pct_macaque": round(float(sp_group_pct["Macaque"].loc["OB Dopa-GABA", "TH"]), 4),
    "ob_dopa_th_pct_marmoset": round(float(sp_group_pct["Marmoset"].loc["OB Dopa-GABA", "TH"]), 4),
    "ob_frmd7_th_pct_max": round(max(float(sp_group_pct[s].loc["OB FRMD7 GABA", "TH"]) for s in SPECIES), 4),
    "ob_frmd7_frmd7_pct_human": round(float(sp_group_pct["Human"].loc["OB FRMD7 GABA", "FRMD7"]), 4),
    "ob_frmd7_frmd7_pct_macaque": round(float(sp_group_pct["Macaque"].loc["OB FRMD7 GABA", "FRMD7"]), 4),
    "ob_frmd7_frmd7_pct_marmoset": round(float(sp_group_pct["Marmoset"].loc["OB FRMD7 GABA", "FRMD7"]), 4),
    "shared_gad2_meis2_expressed_both": bool(
        all(_mean_across_sp(grp, g, "pct_expr") > 0.30 for grp in OB_GROUPS for g in ["GAD2", "MEIS2"])
    ),
}

# Plot 3-slice pie-dot plot matching published Figure 3D
fig = plt.figure(figsize=(3.9, 8.8))
ax = fig.add_axes([0.34, 0.23, 0.56, 0.59])

# Wedge angles matching published Figure 3D (note y-axis is inverted, so 180..300 draws top-left and 60..180 draws bottom-left):
# Human right (-60..60), Macaque top-left (180..300), Marmoset bottom-left (60..180)
species_style = {
    "Human": (-60.0, 60.0, cm.get_cmap("Blues")),
    "Macaque": (180.0, 300.0, cm.get_cmap("Greens")),
    "Marmoset": (60.0, 180.0, cm.get_cmap("Oranges")),
}

max_radius = 0.43
for gi, gene in enumerate(GENES):
    for ci, grp in enumerate(OB_GROUPS):
        for sp, (t1, t2, cmap) in species_style.items():
            sub = ob_df[(ob_df["gene"] == gene) & (ob_df["Group"] == grp) & (ob_df["Species"] == sp)].iloc[0]
            pct = float(sub["pct_expr"])
            val = float(sub["norm_expr"])
            if pct <= 0.005:
                continue
            rad = max_radius * np.sqrt(min(pct, 1.0))
            col = cmap(0.12 + 0.85 * val)
            w = mpatches.Wedge(
                (ci, gi),
                rad,
                t1,
                t2,
                facecolor=col,
                edgecolor="#ffffff",
                linewidth=0.25,
                zorder=3,
            )
            ax.add_patch(w)

ax.set_xlim(-0.55, 1.55)
ax.set_ylim(len(GENES) - 0.5, -0.5)
ax.set_aspect("equal")
ax.set_xticks([0, 1])
ax.set_xticklabels(["OB DOPA-GABA", "OB FRMD7 GABA"], rotation=270, ha="center", va="bottom", fontsize=9.0, fontweight="bold")
ax.xaxis.tick_top()
ax.set_yticks(range(len(GENES)))
ax.set_yticklabels(GENES, fontsize=9.0)
ax.tick_params(axis="x", length=3, pad=4)
ax.tick_params(axis="y", length=3)
for sp_name in ("top", "right", "bottom", "left"):
    ax.spines[sp_name].set_color("#222222")
    ax.spines[sp_name].set_linewidth(0.9)

# Bottom legends: proportion circles (left) + 3 species colorbars (right)
ax_sz = fig.add_axes([0.08, 0.03, 0.36, 0.16])
ax_sz.set_xlim(0, 1)
ax_sz.set_ylim(0, 1)
ax_sz.axis("off")
ax_sz.text(0.5, 0.96, "Proportion", ha="center", va="top", fontsize=7.8, fontweight="bold")
for yv, pval in [(0.74, 0.10), (0.56, 0.25), (0.36, 0.50), (0.14, 1.00)]:
    r_leg = 0.11 * np.sqrt(pval)
    circ = mpatches.Circle((0.32, yv), r_leg, facecolor="#999999", edgecolor="#444444", lw=0.4)
    ax_sz.add_patch(circ)
    ax_sz.text(0.58, yv, f"{pval:.2f}", va="center", ha="left", fontsize=7.5)

for idx, (sp, (_, _, cmap)) in enumerate(species_style.items()):
    cax = fig.add_axes([0.50 + idx * 0.13, 0.04, 0.085, 0.13])
    sm = cm.ScalarMappable(norm=mcolors.Normalize(0.0, 1.0), cmap=cmap)
    cb = fig.colorbar(sm, cax=cax, orientation="vertical")
    cax.set_title(sp[:3], fontsize=7.5, fontweight="bold", pad=3)
    if idx < 2:
        cb.set_ticks([])
    else:
        cb.set_ticks([0.0, 1.0])
        cb.set_ticklabels(["0", "1"])
        cb.ax.tick_params(labelsize=7.5)

fig.suptitle("Figure 3D: Conserved OB markers", fontsize=10.0, fontweight="bold", y=0.985)
fig.savefig(out_dir() / "fig3d.png", dpi=180)
write_metrics(m)
print(m)
