# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8"]
# ///
"""Figure 1B: atlas tallies and Group composition across human, macaque and marmoset.

Reproduces the three quantitative columns of published Figure 1B in the paper's exact Group order
(Table S2, from STRd D1 Matrix SPN to Endo):
  1. log10 total nuclei sampled per Group (red heatmap, 2 to 5.5)
  2. Relative proportion of nuclei per species within each Group (gray heatmap, 0 to 1)
  3. Dissected-region distribution per Group (stacked barplot using value_sets.csv colors; excludes
     marmoset tiled slabs labeled 'Br', which carry no regional dissection code)
The taxonomic dendrogram tree on the left of published Figure 1B is omitted because branch lengths
are not included in the public metadata tables; Neighborhood/Class groupings are annotated instead."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

from bg_atlas import SPECIES, group_order, load_cells, out_dir, region_palette, write_metrics

cells, donors = load_cells()
m = {"n_nuclei_total": int(len(cells)), "n_groups_total": int(cells["Group"].nunique()),
     "n_clusters_total": int(cells["cluster_alias"].nunique()), "n_donors_total": int(cells["donor_label"].nunique())}
for sp in SPECIES:
    s = cells[cells["species_genus"] == sp]
    k = sp.lower()
    m[f"n_nuclei_{k}"] = int(len(s))
    m[f"n_donors_{k}"] = int(s["donor_label"].nunique())
    m[f"n_groups_{k}"] = int(s["Group"].nunique())
    m[f"n_clusters_{k}"] = int(s["cluster_alias"].nunique())

order, _ = group_order()
counts = cells.groupby(["Group", "species_genus"], observed=True).size().unstack(fill_value=0).reindex(order).fillna(0)
counts = counts[SPECIES].astype(int)
counts.to_csv(out_dir() / "group_nuclei_by_species.csv")
m["largest_group"] = str(counts.sum(axis=1).idxmax())

# Composition table: nuclei per species x donor x dissected region x taxonomy (agent-friendly summary)
keys = ["species_genus", "donor_label", "region_of_interest_label", "Neighborhood", "Class", "Subclass", "Group", "cluster_alias"]
comp = cells.groupby(keys, observed=True).size().rename("n_nuclei").reset_index()
comp = comp[comp["n_nuclei"] > 0].rename(columns={"species_genus": "species", "donor_label": "donor", "region_of_interest_label": "region"})
comp.to_csv(out_dir() / "composition.csv", index=False)
m["composition_total"] = int(comp["n_nuclei"].sum())

# Quantitative matrices for published Figure 1B columns
totals = counts.sum(axis=1).values
log10_tot = np.log10(np.maximum(totals, 1.0))[:, None]
sp_prop = counts.div(counts.sum(axis=1), axis=0).fillna(0.0).values

reg_order, reg_colors = region_palette(exclude=("Br",))
dissected = cells[cells["region_of_interest_label"].astype(str) != "Br"]
reg_counts = (dissected.groupby(["Group", "region_of_interest_label"], observed=True)
              .size().unstack(fill_value=0).reindex(index=order, columns=reg_order, fill_value=0))
reg_prop = reg_counts.div(reg_counts.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
reg_prop.to_csv(out_dir() / "group_region_proportions.csv")

# Major published row blocks for clean left-margin taxonomic brackets (matching Figure 1B order)
BLOCKS = [
    (0, 10, "CN LGE\nGABA"),
    (11, 24, "F M / Cx\nGABA"),
    (25, 37, "CN CGE /\nMGE GABA"),
    (38, 43, "Glut /\nDopa"),
    (44, 60, "Nonneuron"),
]

n = len(order)
fig = plt.figure(figsize=(7.6, 14.2))
gs = gridspec.GridSpec(
    2, 5,
    height_ratios=[1.0, 0.095],
    width_ratios=[0.75, 0.42, 1.15, 2.05, 3.15],
    wspace=0.05, hspace=0.05,
    left=0.02, right=0.98, top=0.895, bottom=0.03,
)

ax_blk = fig.add_subplot(gs[0, 0])
ax_log = fig.add_subplot(gs[0, 1])
ax_sp = fig.add_subplot(gs[0, 2])
ax_reg = fig.add_subplot(gs[0, 3])
ax_lbl = fig.add_subplot(gs[0, 4])

# Left taxonomic block brackets (dendrogram branch lengths are not in metadata)
ax_blk.set_xlim(0, 1)
ax_blk.set_ylim(n - 0.5, -0.5)
ax_blk.axis("off")
for start, end, label in BLOCKS:
    ax_blk.plot([0.86, 0.94, 0.94, 0.86], [start - 0.25, start - 0.25, end + 0.25, end + 0.25],
                color="#444444", lw=0.9)
    ax_blk.text(0.80, (start + end) / 2.0, label, ha="right", va="center",
                fontsize=7.2, fontweight="bold", color="#222222")

# Column 1: log10 total nuclei heatmap (red, 2 to 5.5)
im_log = ax_log.imshow(log10_tot, aspect="auto", cmap="Reds", vmin=2.0, vmax=5.5, interpolation="nearest")
ax_log.set_xticks([0])
ax_log.set_xticklabels(["log10 n"], fontsize=7.5, fontweight="bold", rotation=45, ha="left")
ax_log.xaxis.tick_top()
ax_log.set_yticks([])
ax_log.set_ylim(n - 0.5, -0.5)
for y in np.arange(-0.5, n, 1.0):
    ax_log.axhline(y, color="#dddddd", lw=0.35)
for sp_name in ("top", "right", "bottom", "left"):
    ax_log.spines[sp_name].set_color("#888888")
    ax_log.spines[sp_name].set_linewidth(0.5)

# Column 2: species proportion heatmap (gray, 0 to 1)
im_sp = ax_sp.imshow(sp_prop, aspect="auto", cmap="Greys", vmin=0.0, vmax=1.0, interpolation="nearest")
ax_sp.set_xticks(range(len(SPECIES)))
ax_sp.set_xticklabels(SPECIES, fontsize=7.5, fontweight="bold", rotation=45, ha="left")
ax_sp.xaxis.tick_top()
ax_sp.set_yticks([])
ax_sp.set_ylim(n - 0.5, -0.5)
for y in np.arange(-0.5, n, 1.0):
    ax_sp.axhline(y, color="#cccccc", lw=0.35)
for x in (0.5, 1.5):
    ax_sp.axvline(x, color="#cccccc", lw=0.4)
for sp_name in ("top", "right", "bottom", "left"):
    ax_sp.spines[sp_name].set_color("#888888")
    ax_sp.spines[sp_name].set_linewidth(0.5)

# Column 3: dissected-region stacked barplot
y_pos = np.arange(n)
left = np.zeros(n)
present_regions = []
for reg in reg_order:
    vals = reg_prop[reg].values
    if vals.sum() > 0:
        ax_reg.barh(y_pos, vals, left=left, height=0.86, color=reg_colors[reg], edgecolor="none")
        left += vals
        present_regions.append(reg)
ax_reg.set_xlim(0, 1)
ax_reg.set_ylim(n - 0.5, -0.5)
ax_reg.set_xticks([])
ax_reg.set_yticks([])
ax_reg.set_title("Region", fontsize=8.5, fontweight="bold", style="italic", pad=6)
for sp_name in ("top", "right", "bottom", "left"):
    ax_reg.spines[sp_name].set_color("#888888")
    ax_reg.spines[sp_name].set_linewidth(0.5)

# Right column: Group labels in published Figure 1B order
ax_lbl.set_xlim(0, 1)
ax_lbl.set_ylim(n - 0.5, -0.5)
ax_lbl.axis("off")
ax_lbl.set_title("Group", fontsize=8.5, fontweight="bold", style="italic", pad=6, loc="left")
for i, name in enumerate(order):
    ax_lbl.text(0.01, i, name, ha="left", va="center", fontsize=7.0, color="#111111")

# Bottom legends: colorbars for log10 nuclei & species proportion + Region swatches
ax_leg_cb = fig.add_subplot(gs[1, 0:3])
ax_leg_cb.axis("off")
cb1_ax = ax_leg_cb.inset_axes([0.06, 0.66, 0.84, 0.18])
cb1 = fig.colorbar(im_log, cax=cb1_ax, orientation="horizontal")
cb1.set_ticks([2.0, 3.5, 5.5])
cb1.set_ticklabels(["2", "3.5", "5.5"])
cb1.ax.tick_params(labelsize=6.8, pad=1, length=2)
cb1_ax.set_title(r"$\log_{10}$ # nuclei", fontsize=7.2, pad=3)

cb2_ax = ax_leg_cb.inset_axes([0.06, 0.10, 0.84, 0.18])
cb2 = fig.colorbar(im_sp, cax=cb2_ax, orientation="horizontal")
cb2.set_ticks([0.0, 0.5, 1.0])
cb2.set_ticklabels(["0", "0.5", "1"])
cb2.ax.tick_params(labelsize=6.8, pad=1, length=2)
cb2_ax.set_title("Species proportion", fontsize=7.2, pad=3)

ax_leg_reg = fig.add_subplot(gs[1, 3:5])
ax_leg_reg.axis("off")
handles = [mpatches.Patch(facecolor=reg_colors[r], edgecolor="#666666", linewidth=0.3, label=r) for r in present_regions]
ax_leg_reg.legend(handles=handles, ncol=7, loc="center left", frameon=False,
                  fontsize=6.4, handlelength=0.9, handleheight=0.8, columnspacing=0.7, handletextpad=0.35,
                  title="Dissected regions (Human + Macaque; marmoset slabs labeled 'Br' excluded)",
                  title_fontsize=6.8)

fig.suptitle(
    f"Figure 1B: Basal ganglia consensus taxonomy ({m['n_nuclei_total']:,} nuclei, {m['n_groups_total']} Groups, {m['n_donors_total']} donors)",
    fontsize=9.8, fontweight="bold", y=0.985,
)
fig.text(
    0.5, 0.962,
    "Groups in published Figure 1B / Table S2 order (dendrogram branch lengths not in public metadata; omitted).",
    ha="center", va="top", fontsize=7.4, color="#444444",
)

fig.savefig(out_dir() / "fig1b.png", dpi=180)
write_metrics(m)
print({k: v for k, v in m.items() if not k.startswith("n_clusters_")})
