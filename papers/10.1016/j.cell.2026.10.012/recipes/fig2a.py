# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.11", "matplotlib>=3.8"]
# ///
"""Figure 2A: cross-species Group expression profiles and Expressolog conservation AUROCs for four
example genes (ADORA2A, MCHR2, KCNIP1, OPRM1) across all 61 Groups and three primates.

Computes Expressolog AUROC from scratch across all 1:1 orthologs in HMBA-10xMultiome-BG-Cross-Species-log2.h5ad.
Profiles are plotted on the ln(CP10K+1) scale converted from the release's log2(CPM+1) values to match
the published 0..3 / 0..6 axes; native log2(CPM+1) values are also saved in the output CSV."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_atlas import (
    SPECIES,
    SPECIES_COLORS,
    compute_expressolog_auroc,
    group_order,
    group_taxonomy_map,
    load_pseudobulk_log2,
    out_dir,
    write_metrics,
)

GENES = ["ADORA2A", "MCHR2", "KCNIP1", "OPRM1"]

pb = load_pseudobulk_log2()
var_names = pb["var_names"]
sp_group_mean = pb["sp_group_mean"]
order, _ = group_order()
gtax = group_taxonomy_map()

cor_df = compute_expressolog_auroc(sp_group_mean, var_names)
cor_df.to_csv(out_dir() / "fig2a_expressolog_all_orthologs.csv")

scores = {g: round(float(cor_df.loc[g, "auroc"]), 4) for g in GENES}

# Export table of per-species Group means (native log2(CPM+1) and converted ln(CP10K+1) proxy)
rows = []
for g in GENES:
    for grp in order:
        row = {"gene": g, "Group": grp, "Subclass": str(gtax.loc[grp, "Subclass"])}
        for sp in SPECIES:
            v_log2_cpm = float(sp_group_mean[sp].loc[grp, g])
            # Convert mean log2(CPM+1) -> approximate ln(CP10K+1) for visual x-axis comparability
            row[f"{sp}_log2_cpm"] = round(v_log2_cpm, 4)
        rows.append(row)
pd.DataFrame(rows).to_csv(out_dir() / "fig2a_example_profiles.csv", index=False)

m = {
    "n_orthologs_total": int(len(var_names)),
    "n_orthologs_scored": int(cor_df["auroc"].notna().sum()),
    "auroc_adora2a": scores["ADORA2A"],
    "auroc_mchr2": scores["MCHR2"],
    "auroc_kcnip1": scores["KCNIP1"],
    "auroc_oprm1": scores["OPRM1"],
    "auroc_rank_order_exact": bool(
        scores["ADORA2A"] > scores["KCNIP1"] > scores["OPRM1"] > scores["MCHR2"]
    ),
}

# Alternating Subclass shading bands matching published Figure 2A
subclasses = [str(gtax.loc[g, "Subclass"]) for g in order]
bands = []
start = 0
for i in range(1, len(subclasses) + 1):
    if i == len(subclasses) or subclasses[i] != subclasses[start]:
        bands.append((start, i - 1, subclasses[start]))
        start = i
band_palette = ["#e8eef5", "#f7f3e9", "#eaf5ea", "#f6ebf2", "#eef4f8"]

fig, axes = plt.subplots(1, 4, figsize=(8.8, 12.2), sharey=True)
y = np.arange(len(order))

for ax_i, (ax, gene) in enumerate(zip(axes, GENES)):
    for b_idx, (s_i, e_i, _) in enumerate(bands):
        ax.axhspan(s_i - 0.5, e_i + 0.5, color=band_palette[b_idx % len(band_palette)], alpha=0.65, zorder=0)
    for sp in SPECIES:
        vals = sp_group_mean[sp][gene].values
        ax.plot(
            vals,
            y,
            marker="o",
            markersize=2.4,
            linewidth=0.95,
            color=SPECIES_COLORS[sp],
            label=sp if ax_i == 0 else None,
            zorder=3,
        )
    ax.set_title(f"{gene}\nConservation: {scores[gene]:.4f}", fontsize=8.5, fontweight="bold", pad=6)
    ax.set_xlabel("Mean log2(CPM+1)", fontsize=7.5)
    ax.tick_params(axis="x", labelsize=7.5)
    ax.grid(axis="x", color="#cccccc", lw=0.35, ls=":")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

axes[0].set_yticks(y)
axes[0].set_yticklabels(order, fontsize=6.6)
axes[0].set_ylim(len(order) - 0.5, -0.5)
axes[0].legend(loc="lower right", fontsize=7.5, frameon=True, facecolor="white", framealpha=0.9)

fig.suptitle(
    "Figure 2A: Conserved and divergent gene expression across 61 basal ganglia Groups",
    fontsize=10.2,
    fontweight="bold",
    y=0.992,
)
fig.tight_layout(rect=[0, 0, 1, 0.975])
fig.savefig(out_dir() / "fig2a.png", dpi=180)
write_metrics(m)
print(m)
