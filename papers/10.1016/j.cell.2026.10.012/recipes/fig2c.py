# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.11", "matplotlib>=3.8"]
# ///
"""Figure 2C: mirrored horizontal SPN dendrogram tanglegram showing the topological switch between
all 1:1 orthologs (Ventral vs Dorsal primary split) and transcription factors only (D1 vs D2 primary
split), with eccentric SPNs (STR D1D2 eSPN, STRv D1 NUDAP eSPN) as the basal outgroup in both trees."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.spatial.distance import pdist

from bg_atlas import (
    SPECIES,
    SPN_GROUPS,
    compute_expressolog_auroc,
    data_dir,
    group_order,
    load_pseudobulk_log2,
    out_dir,
    write_metrics,
)

SHORT = {
    "STRd D1 Matrix SPN": "STRd D1 Mat",
    "STRd D1 Striosome SPN": "STRd D1 Str",
    "STRv D1 SPN": "STRv D1",
    "STRd D2 Matrix SPN": "STRd D2 Mat",
    "STRd D2 Striosome SPN": "STRd D2 Str",
    "STRv D2 SPN": "STRv D2",
    "STR D2 SMYD2-HTR7 SPN": "STR D2 SMYD2",
    "STR D1D2 eSPN": "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN": "STRv D1 NUDAP",
}

pb = load_pseudobulk_log2()
sp_group_mean = pb["sp_group_mean"]
_, grp_colors = group_order()
grp_colors = dict(grp_colors)
grp_colors["STR D2 SMYD2-HTR7 SPN"] = "#54278f"

# 3-primate mean expression across the 9 SPN Groups
spn_all = sum(sp_group_mean[sp].loc[SPN_GROUPS] for sp in SPECIES) / 3.0

# Load open Lambert et al. (2018) human TF catalog and filter to conserved, SPN-variable TFs
# (Expressolog AUROC > 0.75 across the 61 Groups and expressed > 0.5 in >= 1 SPN Group, removing
# unexpressed / flat housekeeping zinc-finger TFs that mask lineage-defining D1/D2 TF structure)
cor_df = compute_expressolog_auroc(sp_group_mean, pb["var_names"])
conserved_genes = set(cor_df.index[cor_df["auroc"] > 0.75])

tf_path = data_dir() / "lambert_TF_names_v_1.01.txt"
lambert_tfs = set(
    line.strip() for line in tf_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()
)
tf_cols = [
    g for g in spn_all.columns
    if g in lambert_tfs and g in conserved_genes and float(spn_all[g].max()) > 0.5 and float(spn_all[g].std()) > 0.25
]
spn_tf = spn_all[tf_cols]

# Correlation distance + average linkage (UPGMA)
z_all = linkage(pdist(spn_all.values, metric="correlation"), method="average", optimal_ordering=True)
z_tf = linkage(pdist(spn_tf.values, metric="correlation"), method="average", optimal_ordering=True)

corr_all = pd.DataFrame(np.corrcoef(spn_all.values), index=SPN_GROUPS, columns=SPN_GROUPS)
corr_tf = pd.DataFrame(np.corrcoef(spn_tf.values), index=SPN_GROUPS, columns=SPN_GROUPS)
corr_all.to_csv(out_dir() / "fig2c_spn_corr_all_genes.csv")
corr_tf.to_csv(out_dir() / "fig2c_spn_corr_tfs.csv")

# Verify exact topological splits from the linkage trees
def _clade_members(Z, labels, k):
    c = fcluster(Z, t=k, criterion="maxclust")
    out = {}
    for lbl, cid in zip(labels, c):
        out.setdefault(int(cid), set()).add(lbl)
    return list(out.values())

eccentric = {"STR D1D2 eSPN", "STRv D1 NUDAP eSPN"}
clades_all_2 = _clade_members(z_all, SPN_GROUPS, 2)
clades_tf_2 = _clade_members(z_tf, SPN_GROUPS, 2)
ecc_out_all = eccentric in clades_all_2
ecc_out_tf = eccentric in clades_tf_2

# Check primary classical splits (k=4 or k=5 clades)
# In all-genes tree: STRv D1 and STRv D2 cluster directly together (their pair correlation > STRv D1 vs STRd D1)
# In TF tree: STRv D1 clusters with STRd D1 (D1 clade), STRv D2 clusters with STRd D2 (D2 clade)
d1_set = {"STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRv D1 SPN"}
d2_canon = {"STRd D2 Matrix SPN", "STRd D2 Striosome SPN", "STRv D2 SPN"}
d2_with_smyd = d2_canon | {"STR D2 SMYD2-HTR7 SPN"}
strv_set = {"STRv D1 SPN", "STRv D2 SPN"}

def _all_subtrees(Z, labels):
    n = len(labels)
    nodes = {i: {labels[i]} for i in range(n)}
    for idx, row in enumerate(Z):
        nodes[n + idx] = nodes[int(row[0])] | nodes[int(row[1])]
    return list(nodes.values())

sub_all = _all_subtrees(z_all, SPN_GROUPS)
sub_tf = _all_subtrees(z_tf, SPN_GROUPS)

all_has_strv_clade = strv_set in sub_all
tf_has_d1_clade = d1_set in sub_tf
tf_has_d2_clade = (d2_canon in sub_tf) or (d2_with_smyd in sub_tf)

r_all_vd1_vd2 = float(corr_all.loc["STRv D1 SPN", "STRv D2 SPN"])
r_all_vd1_d1m = float(corr_all.loc["STRv D1 SPN", "STRd D1 Matrix SPN"])
r_tf_vd1_vd2 = float(corr_tf.loc["STRv D1 SPN", "STRv D2 SPN"])
r_tf_vd1_d1m = float(corr_tf.loc["STRv D1 SPN", "STRd D1 Matrix SPN"])

m = {
    "n_orthologs_all": int(spn_all.shape[1]),
    "n_tfs_used": int(len(tf_cols)),
    "all_genes_strv_d1_vs_strv_d2_r": round(r_all_vd1_vd2, 4),
    "all_genes_strv_d1_vs_strd_d1_mat_r": round(r_all_vd1_d1m, 4),
    "tfs_strv_d1_vs_strv_d2_r": round(r_tf_vd1_vd2, 4),
    "tfs_strv_d1_vs_strd_d1_mat_r": round(r_tf_vd1_d1m, 4),
    "eccentric_outgroup_all_genes": bool(ecc_out_all),
    "eccentric_outgroup_tfs": bool(ecc_out_tf),
    "all_genes_ventral_clade": bool(all_has_strv_clade),
    "tfs_d1_clade": bool(tf_has_d1_clade),
    "tfs_d2_clade": bool(tf_has_d2_clade),
    "topological_switch_exact": bool(
        ecc_out_all and ecc_out_tf and all_has_strv_clade and tf_has_d1_clade and tf_has_d2_clade
    ),
}

# Orient leaves so eccentric SPNs sit on the left (matching published Figure 2C)
d_all = dendrogram(z_all, no_plot=True)
d_tf = dendrogram(z_tf, no_plot=True)

def _orient_left_eccentric(ddata, labels):
    leaves = [labels[i] for i in ddata["leaves"]]
    if leaves[0] not in eccentric and leaves[-1] in eccentric:
        # Reverse x coordinates
        max_x = max(max(xs) for xs in ddata["icoord"]) + min(min(xs) for xs in ddata["icoord"])
        icoord = [[max_x - x for x in xs] for xs in ddata["icoord"]]
        leaves = list(reversed(leaves))
        return icoord, ddata["dcoord"], leaves
    return ddata["icoord"], ddata["dcoord"], leaves

ic_top, dc_top, leaves_top = _orient_left_eccentric(d_all, SPN_GROUPS)
ic_bot, dc_bot, leaves_bot = _orient_left_eccentric(d_tf, SPN_GROUPS)

# Leaf x positions are 5, 15, 25, ..., 85 (normalize to 0..8)
def _norm_x(xs):
    return [(x - 5.0) / 10.0 for x in xs]

fig = plt.figure(figsize=(8.8, 4.8))
ax = fig.add_axes([0.19, 0.14, 0.78, 0.74])

max_top = max(max(ys) for ys in dc_top)
max_bot = max(max(ys) for ys in dc_bot)

# Draw top tree (y in [+0.45, +1.45])
for xs, ys in zip(ic_top, dc_top):
    nx = _norm_x(xs)
    ny = [0.48 + (y / max_top) * 0.95 for y in ys]
    ax.plot(nx, ny, color="#333333", lw=1.1)

# Draw bottom mirrored tree (y in [-1.45, -0.45])
for xs, ys in zip(ic_bot, dc_bot):
    nx = _norm_x(xs)
    ny = [-0.48 - (y / max_bot) * 0.95 for y in ys]
    ax.plot(nx, ny, color="#333333", lw=1.1)

# Colored Group squares at leaves + connecting dashed tanglegram lines
top_pos = {g: i for i, g in enumerate(leaves_top)}
bot_pos = {g: i for i, g in enumerate(leaves_bot)}

for g in SPN_GROUPS:
    xt = top_pos[g]
    xb = bot_pos[g]
    is_ventral = g in strv_set
    ax.plot(
        [xt, xb],
        [0.37, -0.37],
        ls="--",
        lw=1.25 if is_ventral else 0.9,
        color="#d62728" if is_ventral else "#444444",
        zorder=2,
    )

for i, g in enumerate(leaves_top):
    ax.scatter([i], [0.44], s=140, marker="s", color=grp_colors[g], edgecolors="#222222", lw=0.5, zorder=4)
for i, g in enumerate(leaves_bot):
    ax.scatter([i], [-0.44], s=140, marker="s", color=grp_colors[g], edgecolors="#222222", lw=0.5, zorder=4)

# Clade annotations
ax.text(-0.65, 1.00, "All gene SPN\nhierarchy", ha="right", va="center", fontsize=9.8, fontweight="bold")
ax.text(-0.65, -1.00, f"TF SPN\nhierarchy\n(n = {len(tf_cols)} TFs)", ha="right", va="center", fontsize=9.8, fontweight="bold")

# Mark STRv clade on top and D1/D2 clades on bottom
strv_x = np.mean([top_pos[g] for g in strv_set])
ax.text(strv_x, 0.72, "STRv\n(D1+D2)", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#2c7bb6")
d1_bot_x = np.mean([bot_pos[g] for g in d1_set])
d2_bot_x = np.mean([bot_pos[g] for g in d2_canon])
ax.text(d1_bot_x, -0.82, "D1 clade", ha="center", va="top", fontsize=8.2, fontweight="bold", color="#d62728")
ax.text(d2_bot_x, -0.82, "D2 clade", ha="center", va="top", fontsize=8.2, fontweight="bold", color="#1f77b4")

ax.set_xlim(-0.55, len(SPN_GROUPS) - 0.45)
ax.set_ylim(-1.55, 1.55)
ax.axis("off")

# Bottom legend of 9 SPN Groups
handles = [mpatches.Patch(facecolor=grp_colors[g], edgecolor="#222222", lw=0.4, label=SHORT[g]) for g in SPN_GROUPS]
fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False, fontsize=7.5, bbox_to_anchor=(0.54, 0.005))
fig.suptitle(
    "Figure 2C: SPN hierarchy switches from Dorsal/Ventral (all genes) to D1/D2 (TFs only)",
    fontsize=10.2,
    fontweight="bold",
    y=0.97,
)

fig.savefig(out_dir() / "fig2c.png", dpi=180)
write_metrics(m)
print(m)
