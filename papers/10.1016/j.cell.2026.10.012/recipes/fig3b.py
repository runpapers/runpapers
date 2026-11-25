# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.10", "matplotlib>=3.8"]
# ///
"""Figure 3B: Zoomed similarity matrix between the 7 classical primate SPN Groups and
the 14 mouse STR D1/D2 Gaba supertypes, highlighting STR D2 SMYD2-HTR7 SPN homology to
0279 STR D2 Gaba_6 and 0276 STR D2 Gaba_3.

Exports the full 9 SPN Groups (including eccentric SPNs) x 15 mouse SPN supertypes (0265-0279)
table to fig3b_spn_similarity.csv and plots the exact 7 x 14 layout of published Figure 3B.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

from bg_spatial import (
    ALL_9_SPN_GROUPS,
    CLASSICAL_SPN_GROUPS,
    FIG3B_MOUSE_SPN_SUPERTYPES,
    SPN_GROUP_COLORS,
    compute_primate_mouse_homology,
    out_dir,
    write_metrics,
)

res = compute_primate_mouse_homology()
sim_df = res["sim_df"]

# Full 9 SPN Groups x all 15 mouse SPN supertypes (0265..0279) saved to CSV
all_15_cols = [c for c in sim_df.columns if any(c.startswith(f"{n:04d} ") for n in range(265, 280))]
full_spn_df = sim_df.loc[ALL_9_SPN_GROUPS, all_15_cols]
full_spn_df.to_csv(out_dir() / "fig3b_spn_similarity.csv")

# Exact 7 classical SPN Groups (bottom-to-top) x 14 mouse SPN supertypes (left-to-right) matching published Figure 3B
sub_7x14 = sim_df.loc[CLASSICAL_SPN_GROUPS, FIG3B_MOUSE_SPN_SUPERTYPES]

# Key homology checks
smyd2_series = sim_df.loc["STR D2 SMYD2-HTR7 SPN", FIG3B_MOUSE_SPN_SUPERTYPES].sort_values(ascending=False)
smyd2_top1 = str(smyd2_series.index[0])
smyd2_top2 = list(smyd2_series.index[:2])
d1_mat_top1 = str(sim_df.loc["STRd D1 Matrix SPN", FIG3B_MOUSE_SPN_SUPERTYPES].idxmax())
d2_mat_top1 = str(sim_df.loc["STRd D2 Matrix SPN", FIG3B_MOUSE_SPN_SUPERTYPES].idxmax())
d1_strio_top1 = str(sim_df.loc["STRd D1 Striosome SPN", FIG3B_MOUSE_SPN_SUPERTYPES].idxmax())
d2_strio_top1 = str(sim_df.loc["STRd D2 Striosome SPN", FIG3B_MOUSE_SPN_SUPERTYPES].idxmax())

# Plot Figure 3B matching Cell VoR layout (7 rows bottom-to-top with Group color swatches + orange homology boxes)
fig, ax = plt.subplots(figsize=(8.6, 5.6), dpi=200)
vals = sub_7x14.values
vmin = max(0.0, float(np.percentile(vals, 5)) - 0.05)
vmax = min(1.0, float(np.max(vals)) + 0.02)

im = ax.imshow(vals, origin="lower", aspect="equal", cmap="Greys", vmin=vmin, vmax=vmax, interpolation="nearest")

# Draw Group color swatches to the left of each row
for r_idx, g in enumerate(CLASSICAL_SPN_GROUPS):
    swatch = patches.Rectangle(
        (-1.35, r_idx - 0.48),
        0.75,
        0.96,
        facecolor=SPN_GROUP_COLORS[g],
        edgecolor="black",
        linewidth=0.7,
        clip_on=False,
    )
    ax.add_patch(swatch)

# Draw published orange homology boxes matching Figure 3B
orange_boxes = [
    (0, 0, 1, 1),   # STRd D1 Matrix -> 0267
    (1, 1, 1, 1),   # STRd D1 Striosome -> 0268
    (2, 2, 1, 2),   # STRd D2 Matrix & Striosome -> 0277
    (3, 4, 6, 1),   # STRv D1 SPN -> 0272..0273
    (9, 5, 3, 1),   # STRv D2 SPN -> 0274..0278
    (12, 6, 2, 1),  # STR D2 SMYD2-HTR7 -> 0279 & 0276
]
for x0, y0, w, h in orange_boxes:
    box = patches.Rectangle(
        (x0 - 0.5, y0 - 0.5),
        w,
        h,
        linewidth=1.8,
        edgecolor="#e67e22",
        facecolor="none",
    )
    ax.add_patch(box)

ax.set_yticks(range(len(CLASSICAL_SPN_GROUPS)))
ax.set_yticklabels(CLASSICAL_SPN_GROUPS, fontsize=8.5)
ax.tick_params(axis="y", pad=28, length=0)
ax.set_xticks(range(len(FIG3B_MOUSE_SPN_SUPERTYPES)))
ax.set_xticklabels(FIG3B_MOUSE_SPN_SUPERTYPES, rotation=90, fontsize=8)
ax.set_xlim(-0.5, len(FIG3B_MOUSE_SPN_SUPERTYPES) - 0.5)
ax.set_ylim(-0.5, len(CLASSICAL_SPN_GROUPS) - 0.5)

cb = fig.colorbar(im, ax=ax, fraction=0.032, pad=0.03)
cb.set_label("Ortholog similarity (Pearson r)", fontsize=8.5)
cb.ax.tick_params(labelsize=7.5)
ax.set_title("Classical SPN Groups vs. Mouse SPN Supertypes (Figure 3B)", fontsize=10, pad=10)

fig.tight_layout()
fig.savefig(out_dir() / "fig3b.png", dpi=200)
plt.close(fig)

metrics = {
    "n_classical_spn_groups_plotted": int(len(CLASSICAL_SPN_GROUPS)),
    "n_mouse_spn_supertypes_plotted": int(len(FIG3B_MOUSE_SPN_SUPERTYPES)),
    "n_all_spn_groups_exported": int(len(ALL_9_SPN_GROUPS)),
    "n_all_mouse_spn_supertypes_exported": int(len(all_15_cols)),
    "smyd2_top1_mouse_supertype": smyd2_top1,
    "smyd2_r_0279": round(float(sub_7x14.loc["STR D2 SMYD2-HTR7 SPN", "0279 STR D2 Gaba_6"]), 4),
    "smyd2_r_0276": round(float(sub_7x14.loc["STR D2 SMYD2-HTR7 SPN", "0276 STR D2 Gaba_3"]), 4),
    "smyd2_top1_mouse_supertype_is_0279": bool(smyd2_top1 == "0279 STR D2 Gaba_6"),
    "smyd2_top2_includes_0276": bool("0276 STR D2 Gaba_3" in smyd2_top2),
    "d1_matrix_top1": d1_mat_top1,
    "d1_matrix_top1_is_0267": bool(d1_mat_top1 == "0267 STR D1 Gaba_3"),
    "d2_matrix_top1": d2_mat_top1,
    "d2_matrix_top1_is_0277": bool(d2_mat_top1 == "0277 STR D2 Gaba_4"),
    "d1_striosome_top1": d1_strio_top1,
    "d2_striosome_top1": d2_strio_top1,
}
write_metrics(metrics)
print(metrics)
