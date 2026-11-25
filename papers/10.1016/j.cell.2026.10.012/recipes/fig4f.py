# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8"]
# ///
"""Figure 4F: Human snATAC-seq spiny projection neuron (SPN) Harmony UMAP and cCRE Jaccard dendrogram.

Reads only the 9 SPN columns from the human Group-by-peaks matrix and the Harmony UMAP coordinates
so it runs cleanly on a standard desktop (< 1.5 GB RAM, < 30 seconds on CPU)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.spatial.distance import squareform

from bg_epig import (
    SPN_GROUPS,
    canon_group,
    data_dir,
    load_group_metadata,
    out_dir,
    rp_seed,
    write_metrics,
)

d = data_dir()
out = out_dir()
group_colors, _, _, _ = load_group_metadata()

# 1. Load only the 9 SPN columns from atac_human_Group_by_peaks.csv
hdr = pd.read_csv(d / "atac_human_Group_by_peaks.csv", nrows=0).columns.tolist()
spn_set = set(SPN_GROUPS)
spn_raw_cols = [c for c in hdr[1:] if canon_group(c) in spn_set]
peaks = pd.read_csv(d / "atac_human_Group_by_peaks.csv", usecols=spn_raw_cols)
peaks.columns = [canon_group(c) for c in peaks.columns]
spn_avail = [g for g in SPN_GROUPS if g in peaks.columns]

B = peaks[spn_avail].values.astype(bool)
jacc = pd.DataFrame(index=spn_avail, columns=spn_avail, dtype=float)
for i, gi in enumerate(spn_avail):
    for j, gj in enumerate(spn_avail):
        both = int(np.logical_and(B[:, i], B[:, j]).sum())
        either = int(np.logical_or(B[:, i], B[:, j]).sum())
        jacc.loc[gi, gj] = both / either if either > 0 else np.nan
jacc.to_csv(out / "fig4f_spn_jaccard.csv")

# 2. Compute UPGMA dendrogram on Jaccard distance (1 - Jaccard)
dist_mat = np.clip(1.0 - jacc.values, 0.0, 1.0)
np.fill_diagonal(dist_mat, 0.0)
Z = linkage(squareform(dist_mat), method="average")

# Verify exact within-compartment pairing in dendrogram merges (first 3 merges should pair D1/D2 within each compartment)
n_spn = len(spn_avail)
name_of = {i: g for i, g in enumerate(spn_avail)}
first_pairs = set()
for step_i in range(len(Z)):
    c1, c2 = int(Z[step_i, 0]), int(Z[step_i, 1])
    if c1 < n_spn and c2 < n_spn:
        first_pairs.add(frozenset([name_of[c1], name_of[c2]]))

expected_pairs = {
    frozenset(["STRd D1 Matrix SPN", "STRd D2 Matrix SPN"]),
    frozenset(["STRd D1 Striosome SPN", "STRd D2 Striosome SPN"]),
    frozenset(["STRv D1 SPN", "STRv D2 SPN"]),
}
d1_d2_pair_within = expected_pairs.issubset(first_pairs)
j_smyd2_strio = float(jacc.loc["STR D2 SMYD2-HTR7 SPN", "STRd D2 Striosome SPN"])
j_smyd2_mat = float(jacc.loc["STR D2 SMYD2-HTR7 SPN", "STRd D2 Matrix SPN"])
j_smyd2_espn = float(jacc.loc["STR D2 SMYD2-HTR7 SPN", "STR D1D2 eSPN"])
smyd2_bridges = (j_smyd2_strio > j_smyd2_mat) and (j_smyd2_espn > 0.50)

# 3. Load Human snATAC-seq Harmony UMAP
umap_df = pd.read_csv(d / "atac_human_concatenated_peakmat_UMAP_harmony.csv")
grp_col = [c for c in umap_df.columns if "group" in c.lower()][0]
u1_col = [c for c in umap_df.columns if "umap" in c.lower() and ("1" in c or "_0" in c)][0]
u2_col = [c for c in umap_df.columns if "umap" in c.lower() and ("2" in c or "_1" in c)][0]
umap_df["Group_canon"] = umap_df[grp_col].astype(str).map(canon_group)
spn_u_full = umap_df[umap_df["Group_canon"].isin(spn_set)].copy()
n_total_atac = int(len(umap_df))
n_spn_atac = int(len(spn_u_full))

# Trim extreme 0.2% outlier coordinates for clean framing matching Figure 4F
x_lo, x_hi = np.percentile(spn_u_full[u1_col], [0.2, 99.8])
y_lo, y_hi = np.percentile(spn_u_full[u2_col], [0.2, 99.8])
spn_u = spn_u_full[
    spn_u_full[u1_col].between(x_lo, x_hi) & spn_u_full[u2_col].between(y_lo, y_hi)
]
if len(spn_u) > 90000:
    spn_u = spn_u.sample(90000, random_state=rp_seed())

# 4. Plot side-by-side UMAP + Dendrogram matching Figure 4F
fig, (ax_u, ax_d) = plt.subplots(
    1, 2, figsize=(10.5, 4.6), gridspec_kw={"width_ratios": [1.25, 1.0]}, dpi=180
)
for g in spn_avail:
    sub = spn_u[spn_u["Group_canon"] == g]
    col = group_colors.get(g, "#888888")
    ax_u.scatter(
        sub[u1_col], sub[u2_col], s=0.45, alpha=0.55, color=col,
        label=g, edgecolors="none", rasterized=True,
    )
ax_u.set_xlabel("UMAP-1", fontsize=8.5)
ax_u.set_ylabel("UMAP-2", fontsize=8.5)
ax_u.set_xticks([])
ax_u.set_yticks([])
for sp in ("top", "right"):
    ax_u.spines[sp].set_visible(False)
ax_u.set_title(f"Human snATAC-seq SPN Harmony UMAP (n = {n_spn_atac:,})", fontsize=9.5)

dend = dendrogram(
    Z, labels=spn_avail, orientation="right", ax=ax_d,
    color_threshold=0.0, above_threshold_color="#333333", leaf_font_size=8.5,
)
# Draw matching ABC color square next to each leaf label
leaf_labels = [lbl.get_text() for lbl in ax_d.get_yticklabels()]
yticks = ax_d.get_yticks()
xlim = ax_d.get_xlim()
ax_d.set_xlim(-0.045 * xlim[1], xlim[1] * 1.05)
for yt, g in zip(yticks, leaf_labels):
    ax_d.scatter(
        [-0.02 * xlim[1]], [yt], s=55, marker="s",
        color=group_colors.get(g, "#888888"), edgecolors="#333333", lw=0.4, zorder=5,
    )
ax_d.set_xlabel("Jaccard distance (1 - Jaccard)", fontsize=8.5)
ax_d.set_title("Human SPN cCRE Jaccard Dendrogram", fontsize=9.5)
for sp in ("top", "right"):
    ax_d.spines[sp].set_visible(False)

fig.tight_layout()
fig.savefig(out / "fig4f.png", dpi=180)
plt.close(fig)

metrics = {
    "n_spn_groups": len(spn_avail),
    "n_human_peaks": int(len(peaks)),
    "n_total_atac_nuclei": n_total_atac,
    "n_spn_atac_nuclei": n_spn_atac,
    "jaccard_d1mat_d2mat": round(float(jacc.loc["STRd D1 Matrix SPN", "STRd D2 Matrix SPN"]), 4),
    "jaccard_d1strio_d2strio": round(float(jacc.loc["STRd D1 Striosome SPN", "STRd D2 Striosome SPN"]), 4),
    "jaccard_strvd1_strvd2": round(float(jacc.loc["STRv D1 SPN", "STRv D2 SPN"]), 4),
    "jaccard_d1mat_d1strio": round(float(jacc.loc["STRd D1 Matrix SPN", "STRd D1 Striosome SPN"]), 4),
    "jaccard_smyd2_d2strio": round(j_smyd2_strio, 4),
    "jaccard_smyd2_d2mat": round(j_smyd2_mat, 4),
    "jaccard_smyd2_espn": round(j_smyd2_espn, 4),
    "d1_d2_pair_within_compartments_in_dendrogram": bool(d1_d2_pair_within),
    "smyd2_bridges_striosome_and_espn": bool(smyd2_bridges),
}
write_metrics(metrics)
print(metrics)
