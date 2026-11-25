# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8", "seaborn>=0.13"]
# ///
"""Figure 4E: Three-species (Human, Macaque, Marmoset) Group-specific cCRE accessibility heatmaps,
consensus cCRE counts (1.36M / 1.37M / 1.22M), full 60-Group human Jaccard similarity matrix,
and zoomed 9-Group human SPN cCRE Jaccard similarity heatmap."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from bg_epig import (
    PUBLISHED_GROUP_ORDER,
    SPN_GROUPS,
    canon_group,
    data_dir,
    load_group_metadata,
    out_dir,
    write_metrics,
)

d = data_dir()
out = out_dir()
group_colors, group_to_class, _, class_colors = load_group_metadata()

# 1. Consensus cCRE counts across all 3 primates
ccre_counts = {}
for sp, fn in [
    ("human", "atac_human_consensus_peaks.bed"),
    ("macaque", "atac_macaque_consensus_peaks.bed"),
    ("marmoset", "atac_marmoset_consensus_peaks.bed"),
]:
    with open(d / fn) as f:
        ccre_counts[sp] = sum(1 for _ in f)


def load_species_group_peaks(path):
    df = pd.read_csv(path, index_col=0)
    df.columns = [canon_group(c) for c in df.columns]
    # Drop duplicate columns if any
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def build_diagonal_heatmap(df: pd.DataFrame, k_per_group: int = 25) -> tuple[np.ndarray, list[bool]]:
    """Build Group-specific peak accessibility matrix (peaks x 61 Groups) with NaN columns for missing Groups."""
    present_cols = [g for g in PUBLISHED_GROUP_ORDER if g in df.columns]
    B = df[present_cols].values.astype(np.float32)
    act_sum = B.sum(axis=1)
    # Specificity score per peak: 1 / act_sum for active groups
    selected_rows = []
    for ci, g in enumerate(present_cols):
        active = np.where((B[:, ci] > 0) & (act_sum <= 4))[0]
        if len(active) < k_per_group:
            active = np.where(B[:, ci] > 0)[0]
        if len(active) == 0:
            continue
        ord_a = active[np.argsort(act_sum[active])]
        selected_rows.extend(ord_a[:k_per_group].tolist())
    # Assemble full 61-column matrix (NaN for species-absent Groups)
    full = np.full((len(selected_rows), len(PUBLISHED_GROUP_ORDER)), np.nan, dtype=np.float32)
    col_map = {g: i for i, g in enumerate(present_cols)}
    is_present = []
    if selected_rows:
        sub_B = B[selected_rows]
        # Smooth visual intensity: peak specificity weighted (1.0 when exclusive, scaled by 1/sqrt(k))
        row_scale = 1.0 / np.sqrt(np.maximum(sub_B.sum(axis=1, keepdims=True), 1.0))
        sub_norm = sub_B * row_scale
        # Normalize each row to [0, 1]
        rmax = np.maximum(sub_norm.max(axis=1, keepdims=True), 1e-6)
        sub_norm = sub_norm / rmax
        for gi, g in enumerate(PUBLISHED_GROUP_ORDER):
            if g in col_map:
                full[:, gi] = sub_norm[:, col_map[g]]
                is_present.append(True)
            else:
                is_present.append(False)
    return full, is_present


h_df = load_species_group_peaks(d / "atac_human_Group_by_peaks.csv")
q_df = load_species_group_peaks(d / "atac_macaque_Group_by_peaks.bed")
m_df = load_species_group_peaks(d / "atac_marmoset_Group_by_peaks.bed")

h_hm, _ = build_diagonal_heatmap(h_df, k_per_group=22)
q_hm, _ = build_diagonal_heatmap(q_df, k_per_group=22)
m_hm, _ = build_diagonal_heatmap(m_df, k_per_group=22)

# 2. Full 60-Group Human Jaccard similarity matrix + 9-SPN zoom
h_groups = [g for g in PUBLISHED_GROUP_ORDER if g in h_df.columns]
Bh = (h_df[h_groups].values > 0).astype(np.float32)
inter = Bh.T @ Bh
sums = Bh.sum(axis=0)
union = sums[:, None] + sums[None, :] - inter
jacc_all = pd.DataFrame(
    np.divide(inter, np.maximum(union, 1.0)),
    index=h_groups,
    columns=h_groups,
)
jacc_all.to_csv(out / "fig4e_human_60group_jaccard.csv")

spn_avail = [g for g in SPN_GROUPS if g in jacc_all.index]
jacc_spn = jacc_all.loc[spn_avail, spn_avail]
jacc_spn.to_csv(out / "fig4e_human_spn_jaccard.csv")

j_d1m_d2m = float(jacc_spn.loc["STRd D1 Matrix SPN", "STRd D2 Matrix SPN"])
j_d1s_d2s = float(jacc_spn.loc["STRd D1 Striosome SPN", "STRd D2 Striosome SPN"])
j_vd1_vd2 = float(jacc_spn.loc["STRv D1 SPN", "STRv D2 SPN"])
j_d1m_d1s = float(jacc_spn.loc["STRd D1 Matrix SPN", "STRd D1 Striosome SPN"])
j_d2m_d2s = float(jacc_spn.loc["STRd D2 Matrix SPN", "STRd D2 Striosome SPN"])
within_gt_across = (
    j_d1m_d2m > j_d1m_d1s
    and j_d1m_d2m > j_d2m_d2s
    and j_d1s_d2s > j_d1m_d1s
    and j_vd1_vd2 > j_d1m_d1s
)

# 3. Plot Figure 4E layout: Left 3 stacked species heatmaps; Right top 60x60 Jaccard, Right bottom 9x9 SPN Jaccard
fig = plt.figure(figsize=(13.2, 11.2), dpi=180)
gs_l = fig.add_gridspec(4, 1, left=0.04, right=0.44, top=0.95, bottom=0.08, height_ratios=[1, 1, 1, 0.08], hspace=0.06)
gs_r = fig.add_gridspec(2, 1, left=0.60, right=0.96, top=0.95, bottom=0.14, height_ratios=[1.0, 1.05], hspace=0.18)

cmap_v = plt.get_cmap("viridis").copy()
cmap_v.set_bad(color="#b0b0b0")

for row_i, (sp_lbl, hm, n_c) in enumerate([
    ("Human", h_hm, ccre_counts["human"]),
    ("Macaque", q_hm, ccre_counts["macaque"]),
    ("Marmoset", m_hm, ccre_counts["marmoset"]),
]):
    ax = fig.add_subplot(gs_l[row_i, 0])
    ax.imshow(hm, aspect="auto", cmap=cmap_v, vmin=0, vmax=1, interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(
        0.02, 0.05, f"{sp_lbl} ({n_c / 1e6:.2f}M cCREs)",
        transform=ax.transAxes, color="white", fontsize=9, fontweight="bold",
        bbox=dict(facecolor="black", alpha=0.45, pad=2, edgecolor="none"),
    )
    if row_i == 0:
        ax.set_title("Group-specific cCRE accessibility (61 BG Groups)", fontsize=10)

ax_c = fig.add_subplot(gs_l[3, 0])
cls_hex = [class_colors.get(group_to_class.get(g, ""), "#999999") for g in PUBLISHED_GROUP_ORDER]
ax_c.imshow(np.array([mcolors.to_rgb(c) for c in cls_hex])[None, :, :], aspect="auto", interpolation="nearest")
ax_c.set_xticks([])
ax_c.set_yticks([])
ax_c.set_xlabel("61 Consensus BG Groups (CN LGE -> Subpallium -> Nonneuron; grey = absent in species)", fontsize=7.5)

ax_j60 = fig.add_subplot(gs_r[0, 0])
ax_j60.imshow(jacc_all.values, cmap="Blues", vmin=0, vmax=1, aspect="equal", interpolation="nearest")
# Highlight 9x9 SPN corner
import matplotlib.patches as patches
ax_j60.add_patch(patches.Rectangle((-0.5, -0.5), len(spn_avail), len(spn_avail), fill=False, edgecolor="#d62728", lw=1.6))
ax_j60.set_xticks([])
ax_j60.set_yticks([])
ax_j60.set_title("Human 60-Group cCRE Jaccard Similarity (red box = 9 SPNs)", fontsize=9.5)

ax_jspn = fig.add_subplot(gs_r[1, 0])
sns.heatmap(
    jacc_spn, cmap="Blues", vmin=0, vmax=1, annot=True, fmt=".2f",
    annot_kws={"size": 7.5}, square=True, cbar_kws={"label": "Jaccard similarity", "shrink": 0.8}, ax=ax_jspn,
)
ax_jspn.set_xticklabels(spn_avail, rotation=45, ha="right", fontsize=8)
ax_jspn.set_yticklabels(spn_avail, rotation=0, fontsize=8)
ax_jspn.set_title("Human SPN cCRE Jaccard Similarity", fontsize=9.5)

fig.savefig(out / "fig4e.png", dpi=180)
plt.close(fig)

metrics = {
    "n_ccres_human": int(ccre_counts["human"]),
    "n_ccres_macaque": int(ccre_counts["macaque"]),
    "n_ccres_marmoset": int(ccre_counts["marmoset"]),
    "n_human_groups_in_atac": int(len(h_groups)),
    "n_macaque_groups_in_atac": int(len([g for g in PUBLISHED_GROUP_ORDER if g in q_df.columns])),
    "n_marmoset_groups_in_atac": int(len([g for g in PUBLISHED_GROUP_ORDER if g in m_df.columns])),
    "jaccard_d1mat_d2mat": round(j_d1m_d2m, 4),
    "jaccard_d1strio_d2strio": round(j_d1s_d2s, 4),
    "jaccard_strvd1_strvd2": round(j_vd1_vd2, 4),
    "jaccard_d1mat_d1strio": round(j_d1m_d1s, 4),
    "jaccard_d2mat_d2strio": round(j_d2m_d2s, 4),
    "within_compartment_d1_d2_gt_across_compartment": bool(within_gt_across),
}
write_metrics(metrics)
print(metrics)
