# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8"]
# ///
"""Figure 1A: single-nucleus multiome dissection coverage across anatomical regions and three primates.

Reproduces the quantitative dot plot of published Figure 1A in anterior-to-posterior anatomical order
(Ca through SN/VTA for Human and Macaque; tiled whole-slab dissections labeled 'Br' for Marmoset).
Dot area scales with log10 nuclei sampled and fill color reflects the number of donors.
The top 3D brain surface rendering and FACS sorting cartoon in published Figure 1A are non-data
illustrations and are omitted here. In the public ABC Atlas 20261031 release, GPeR/GPeC are combined
under GPe and SN-VTA is labeled VTA (colored with the release palette from value_sets.csv)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

from bg_atlas import (
    PUBLISHED_REGION_ORDER,
    SPECIES,
    load_cells,
    out_dir,
    region_palette,
    write_metrics,
)

cells, donors = load_cells()
_, reg_colors = region_palette(exclude=())

cov = (
    cells.groupby(["species_genus", "region_of_interest_label"], observed=True)
    .agg(n_nuclei=("cell_label", "count"), n_donors=("donor_label", "nunique"))
    .reset_index()
)
cov = cov.rename(columns={"species_genus": "species", "region_of_interest_label": "region"})
cov.to_csv(out_dir() / "fig1a_region_coverage.csv", index=False)

# Verify every dissected human/macaque region appears in PUBLISHED_REGION_ORDER
obs_dissected = set(cov.loc[cov["species"] != "Marmoset", "region"].astype(str))
if obs_dissected != set(PUBLISHED_REGION_ORDER):
    extra = sorted(obs_dissected - set(PUBLISHED_REGION_ORDER))
    missing = sorted(set(PUBLISHED_REGION_ORDER) - obs_dissected)
    raise ValueError(f"Dissected regions mismatch: extra={extra}, missing={missing}")

hm_cov = cov[cov["species"].isin(["Human", "Macaque"])].copy()
marm_cov = cov[cov["species"] == "Marmoset"].copy()

m = {
    "n_nuclei_total": int(len(cells)),
    "n_donors_total": int(cells["donor_label"].nunique()),
    "n_donors_human": int(cells.loc[cells["species_genus"] == "Human", "donor_label"].nunique()),
    "n_donors_macaque": int(cells.loc[cells["species_genus"] == "Macaque", "donor_label"].nunique()),
    "n_donors_marmoset": int(cells.loc[cells["species_genus"] == "Marmoset", "donor_label"].nunique()),
    "n_regions_human": int(cov.loc[cov["species"] == "Human", "region"].nunique()),
    "n_regions_macaque": int(cov.loc[cov["species"] == "Macaque", "region"].nunique()),
    "n_regions_marmoset": int(cov.loc[cov["species"] == "Marmoset", "region"].nunique()),
    "n_regions_dissected_union": int(len(PUBLISHED_REGION_ORDER)),
    "marmoset_region_label": str(marm_cov["region"].iloc[0]),
    "n_nuclei_marmoset_br": int(marm_cov["n_nuclei"].sum()),
    "max_donors_per_region_human": int(hm_cov.loc[hm_cov["species"] == "Human", "n_donors"].max()),
    "max_donors_per_region_macaque": int(hm_cov.loc[hm_cov["species"] == "Macaque", "n_donors"].max()),
}

# Plot closely matching published Figure 1A bottom matrix
fig = plt.figure(figsize=(10.2, 4.0))
ax = fig.add_axes([0.11, 0.30, 0.72, 0.50])

x_map = {r: i for i, r in enumerate(PUBLISHED_REGION_ORDER)}
y_map = {"Human": 2.0, "Macaque": 1.0}

# Dot size scaling: linear in log10(nuclei), covering ~4,000 (3.6) to ~156,000 (5.19)
def _dot_size(n_arr):
    lv = np.log10(np.maximum(n_arr, 1.0))
    return np.clip((lv - 2.7) * 140.0, 28.0, 420.0)

sc = ax.scatter(
    hm_cov["region"].astype(str).map(x_map),
    hm_cov["species"].astype(str).map(y_map),
    s=_dot_size(hm_cov["n_nuclei"].values),
    c=hm_cov["n_donors"].values,
    cmap="Blues",
    vmin=1,
    vmax=9,
    edgecolors="#222222",
    linewidths=0.65,
    zorder=3,
)

# Marmoset tiled dissections bar across bottom row (y = 0)
bar_patch = mpatches.FancyBboxPatch(
    (-0.42, -0.26),
    len(PUBLISHED_REGION_ORDER) - 0.16,
    0.52,
    boxstyle="round,pad=0.04,rounding_size=0.14",
    facecolor="#d9d9d9",
    edgecolor="#333333",
    linewidth=0.8,
    zorder=2,
)
ax.add_patch(bar_patch)
ax.text(
    (len(PUBLISHED_REGION_ORDER) - 1) / 2.0,
    0.0,
    f"Tiled Dissections ('Br': {m['n_donors_marmoset']} donors, {m['n_nuclei_marmoset_br']:,} nuclei)",
    ha="center",
    va="center",
    fontsize=8.5,
    color="#111111",
    zorder=3,
)

ax.set_xlim(-0.75, len(PUBLISHED_REGION_ORDER) - 0.25)
ax.set_ylim(-0.55, 2.55)
ax.set_yticks([0.0, 1.0, 2.0])
ax.set_yticklabels(["Marmoset\n(4 donors)", "Macaque\n(8 donors)", "Human\n(10 donors)"], fontsize=8.5, fontweight="bold")
ax.set_xticks(range(len(PUBLISHED_REGION_ORDER)))
ax.set_xticklabels([])
ax.tick_params(axis="x", length=0)
ax.set_title("Anatomical region (anterior-to-posterior order)", fontsize=10, fontweight="bold", loc="left", pad=6)

# Colored region swatches and anatomical labels below x-axis (release palette from value_sets.csv)
ax_sw = fig.add_axes([0.11, 0.05, 0.72, 0.24])
ax_sw.set_xlim(-0.75, len(PUBLISHED_REGION_ORDER) - 0.25)
ax_sw.set_ylim(0, 1)
ax_sw.axis("off")

# Hierarchical parent-region grouping bars matching published Fig 1A
for x0, x1, col in [
    (0, 3, reg_colors["Ca"]),
    (4, 7, reg_colors["Pu"]),
    (8, 10, reg_colors["NAC"]),
    (11, 13, reg_colors["GP"]),
]:
    ax_sw.plot([x0, x1], [0.90, 0.90], color=col, lw=2.2, solid_capstyle="butt")
    for xi in range(x0, x1 + 1):
        ax_sw.plot([xi, xi], [0.80, 0.90], color=col, lw=1.0)

for i, reg in enumerate(PUBLISHED_REGION_ORDER):
    rect = mpatches.Rectangle((i - 0.34, 0.60), 0.68, 0.20, facecolor=reg_colors[reg], edgecolor="#444444", lw=0.35)
    ax_sw.add_patch(rect)
    ax_sw.text(i, 0.54, reg, ha="center", va="top", rotation=90, fontsize=8.2, color="#111111")

# Colorbar for donor count
cax = fig.add_axes([0.85, 0.34, 0.02, 0.42])
cb = fig.colorbar(sc, cax=cax)
cb.set_ticks([1, 3, 5, 7, 9])
cb.set_label("Donors", fontsize=8.5)
cb.ax.tick_params(labelsize=8)

# Size legend for log10 nuclei
ax_sz = fig.add_axes([0.885, 0.30, 0.11, 0.50])
ax_sz.axis("off")
ax_sz.set_xlim(0, 1)
ax_sz.set_ylim(0, 1)
ax_sz.text(0.5, 0.92, "Nuclei", ha="center", va="top", fontsize=8.2, fontweight="bold")
for yv, val, lbl in [(0.70, 1e4, "10k"), (0.48, 5e4, "50k"), (0.24, 1.5e5, "150k")]:
    ax_sz.scatter([0.32], [yv], s=_dot_size(np.array([val])), color="#6baed6", edgecolors="#222222", lw=0.6)
    ax_sz.text(0.62, yv, lbl, va="center", ha="left", fontsize=7.6)

fig.suptitle(
    f"Figure 1A: Dissection coverage across primates ({m['n_nuclei_total']:,} nuclei, {m['n_donors_total']} donors)",
    fontsize=10.5,
    fontweight="bold",
    y=0.97,
)
fig.text(
    0.5,
    0.905,
    "Top 3D brain/FACS schematics in published Fig 1A are non-data illustrations (omitted). Release palette from value_sets.csv (GPe pools GPeR/GPeC; VTA corresponds to SN-VTA).",
    ha="center",
    va="top",
    fontsize=7.3,
    color="#444444",
)

fig.savefig(out_dir() / "fig1a.png", dpi=180)
write_metrics(m)
print(m)
