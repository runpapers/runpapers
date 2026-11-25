# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.11", "scanpy>=1.10", "pydeseq2>=0.4.12", "statsmodels>=0.14", "scikit-posthocs>=0.9", "matplotlib>=3.8"]
# ///
"""Figure 2G: evolutionary divergence across three striatal SPN axes (Dorsal-Ventral, Striosome-Matrix,
and D1-D2) compared against the 5,000 most highly variable genes (HVG) across the five dorsal SPN Groups.

Computes everything from scratch from the open ABC Atlas raw & log2 expression matrices:
  1. D1-D2 and Striosome-Matrix DEGs via per-species Wilcoxon rank-sum tests (Bonferroni p < 0.01,
     |LFC| > 1.0 for D1-D2 and |LFC| > 1.5 for Striosome-Matrix; also records both thresholds to audit
     the text vs Table S10 discrepancy).
  2. Dorsal-Ventral CNR1-correlated genes using method-of-moments (memento-style) Poisson shot-noise
     de-noised correlation on raw UMI counts (|r_mom| > 0.3 in any species), and also computes raw
     single-cell Pearson |r| > 0.3 to quantify sensitivity to capture-noise correction.
  3. Per-Group cross-species PyDESeq2 |log2FC| across Human, Macaque, and Marmoset donor pseudobulks
     within each of the 5 dorsal SPN Groups (STRd D1 Matrix, STRd D1 Striosome, STRd D2 Matrix,
     STRd D2 Striosome, STR D2 SMYD2-HTR7), LOWESS-adjusted for mean expression level, with Kruskal-
     Wallis and Bonferroni-adjusted Dunn's post-hoc tests."""
import gc
import os

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp
import scikit_posthocs as sp_ph
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats
from scipy import stats
from statsmodels.nonparametric.smoothers_lowess import lowess

from bg_atlas import (
    SPECIES,
    data_dir,
    group_order,
    load_cells,
    load_pseudobulk_log2,
    out_dir,
    write_metrics,
)

DORSAL_5 = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STR D2 SMYD2-HTR7 SPN",
]
CLASSICAL_DORSAL = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
]
CLASSICAL_ALL = CLASSICAL_DORSAL + ["STRv D1 SPN", "STRv D2 SPN"]
PAIRS = [("Human", "Macaque"), ("Human", "Marmoset"), ("Macaque", "Marmoset")]

seed = int(os.environ.get("RP_SEED", "0"))
rng = np.random.default_rng(seed)

pb = load_pseudobulk_log2()
var_names = pb["var_names"]
sp_group_mean = pb["sp_group_mean"]
sp_group_pct = pb["sp_group_pct"]
n_genes = len(var_names)

cells, _ = load_cells()
_, grp_colors = group_order()
grp_colors = dict(grp_colors)
grp_colors["STR D2 SMYD2-HTR7 SPN"] = "#54278f"

# 1. Identify D1-D2 and Striosome-Matrix DEGs from Cross-Species-log2.h5ad (Wilcoxon per species)
adata_log2 = ad.read_h5ad(data_dir() / "HMBA-10xMultiome-BG-Cross-Species-log2.h5ad", backed="r")
meta_idx = cells.set_index("cell_label").reindex(adata_log2.obs_names)
species_arr = meta_idx["species_genus"].astype(str).values
group_arr = meta_idx["Group"].astype(str).values
donor_arr = meta_idx["donor_label"].astype(str).values

deg_sets = {
    "D1_vs_D2_LFC1": set(),
    "D1_vs_D2_LFC1.5": set(),
    "Strio_vs_Mat_LFC1": set(),
    "Strio_vs_Mat_LFC1.5": set(),
}
dv_raw_pearson = set()
cnr1_idx = int(np.where(var_names == "CNR1")[0][0])

for sp_name in SPECIES:
    sp_cells = []
    for grp in CLASSICAL_ALL:
        idx = np.where((species_arr == sp_name) & (group_arr == grp))[0]
        if len(idx) > 10000:
            idx = rng.choice(idx, size=10000, replace=False)
        sp_cells.append(idx)
    sp_cells = np.sort(np.concatenate(sp_cells))
    X_sp = adata_log2.X[sp_cells]
    X_sp = X_sp.tocsr() if sp.issparse(X_sp) else sp.csr_matrix(X_sp)
    obs_sp = pd.DataFrame({"Group": group_arr[sp_cells]}, index=[f"c{i}" for i in range(len(sp_cells))])
    sub_ad = ad.AnnData(X=X_sp, obs=obs_sp, var=pd.DataFrame(index=var_names))

    # D1 vs D2 (dorsal + ventral classical SPNs)
    sub_ad.obs["pathway"] = np.where(sub_ad.obs["Group"].str.contains("D1"), "D1", "D2")
    sc.tl.rank_genes_groups(sub_ad, groupby="pathway", method="wilcoxon", corr_method="benjamini-hochberg")
    df_d12 = sc.get.rank_genes_groups_df(sub_ad, group="D1")
    df_d12["p_bonf"] = np.minimum(df_d12["pvals"] * n_genes, 1.0)
    deg_sets["D1_vs_D2_LFC1"].update(df_d12.loc[(df_d12["p_bonf"] < 0.01) & (df_d12["logfoldchanges"].abs() > 1.0), "names"])
    deg_sets["D1_vs_D2_LFC1.5"].update(df_d12.loc[(df_d12["p_bonf"] < 0.01) & (df_d12["logfoldchanges"].abs() > 1.5), "names"])

    # Striosome vs Matrix (dorsal classical SPNs)
    dors = sub_ad[sub_ad.obs["Group"].isin(CLASSICAL_DORSAL)].copy()
    dors.obs["comp"] = np.where(dors.obs["Group"].str.contains("Striosome"), "Striosome", "Matrix")
    sc.tl.rank_genes_groups(dors, groupby="comp", method="wilcoxon", corr_method="benjamini-hochberg")
    df_sm = sc.get.rank_genes_groups_df(dors, group="Striosome")
    df_sm["p_bonf"] = np.minimum(df_sm["pvals"] * n_genes, 1.0)
    deg_sets["Strio_vs_Mat_LFC1"].update(df_sm.loc[(df_sm["p_bonf"] < 0.01) & (df_sm["logfoldchanges"].abs() > 1.0), "names"])
    deg_sets["Strio_vs_Mat_LFC1.5"].update(df_sm.loc[(df_sm["p_bonf"] < 0.01) & (df_sm["logfoldchanges"].abs() > 1.5), "names"])

    # Raw single-cell Pearson correlation with CNR1 (unadjusted control for sensitivity check)
    Xd = X_sp.toarray().astype(np.float64)
    y_cnr1 = Xd[:, cnr1_idx]
    yc = y_cnr1 - y_cnr1.mean()
    Xc = Xd - Xd.mean(axis=0, keepdims=True)
    den = np.sqrt((yc ** 2).sum() * (Xc ** 2).sum(axis=0))
    r_raw = np.where(den > 0, (yc[:, None] * Xc).sum(axis=0) / np.where(den > 0, den, 1.0), 0.0)
    dv_raw_pearson.update(var_names[np.abs(r_raw) > 0.3])

    del sub_ad, dors, X_sp, Xd
    gc.collect()
adata_log2.file.close()

# Genes expressed in >20% of cells in at least one classical SPN Group (averaged across species)
spn_pct_avg = sum(sp_group_pct[s].loc[DORSAL_5] for s in SPECIES) / 3.0
expressed_20pct = set(var_names[(spn_pct_avg.max(axis=0) > 0.20).values])

# 5,000 most highly variable genes across dorsal SPN Groups
dors_mean_avg = sum(sp_group_mean[s].loc[DORSAL_5] for s in SPECIES) / 3.0
hvg_5000 = set(dors_mean_avg.var(axis=0).nlargest(5000).index) & expressed_20pct

# 2. Stream Cross-Species-raw.h5ad for:
#    (a) Method-of-moments (memento-style) shot-noise-corrected CNR1 correlation across classical SPNs
#    (b) Donor-by-Group raw-count pseudobulks for the 5 dorsal SPN Groups -> PyDESeq2
adata_raw = ad.read_h5ad(data_dir() / "HMBA-10xMultiome-BG-Cross-Species-raw.h5ad", backed="r")

# (a) Method-of-moments Poisson-denoised correlation with CNR1 per species (exact Kim et al. memento moments!)
dv_memento = set()
for sp_name in SPECIES:
    sp_cells = []
    for grp in CLASSICAL_ALL:
        idx = np.where((species_arr == sp_name) & (group_arr == grp))[0]
        if len(idx) > 8000:
            idx = rng.choice(idx, size=8000, replace=False)
        sp_cells.append(idx)
    sp_cells = np.sort(np.concatenate(sp_cells))
    Xr = adata_raw.X[sp_cells]
    Xr = Xr.tocsr() if sp.issparse(Xr) else sp.csr_matrix(Xr)
    lib_size = np.asarray(Xr.sum(axis=1)).ravel().astype(np.float64)
    keep_c = lib_size > 100.0
    Xr = Xr[keep_c]
    lib_size = lib_size[keep_c]
    n_c = len(lib_size)
    # Normalize each cell by its relative size factor s_i = lib_i / mean(lib)
    inv_lib = (1.0 / lib_size).astype(np.float64)
    scale = float(lib_size.mean())
    # Normalized rate x_ig = c_ig / lib_i * scale  (units = counts per average cell)
    D_inv = sp.diags(scale * inv_lib)
    Xn = D_inv @ Xr
    mean_g = np.asarray(Xn.mean(axis=0)).ravel()
    Xn_sq = Xn.copy()
    Xn_sq.data = Xn_sq.data ** 2
    var_obs = np.maximum(np.asarray(Xn_sq.mean(axis=0)).ravel() - mean_g ** 2, 0.0)
    # Poisson shot-noise variance contribution: E[c_ig / lib_i^2] * scale^2 = mean_g * mean(scale / lib_i)
    shot_factor = float(np.mean(scale * inv_lib))
    var_true = var_obs - mean_g * shot_factor
    # Covariance with CNR1 (distinct genes have zero Poisson noise covariance)
    y = Xn[:, cnr1_idx].toarray().ravel().astype(np.float64)
    cov_y = np.asarray(Xn.T @ y).ravel() / n_c - mean_g * mean_g[cnr1_idx]
    v_cnr1 = var_true[cnr1_idx]
    # Require positive denoised variance and meaningful expression (mean_g >= 0.05 counts/cell)
    valid_g = (var_true > 0.02 * var_obs) & (var_true > 1e-6) & (mean_g >= 0.05) & (v_cnr1 > 1e-6)
    r_mom = np.zeros(n_genes, dtype=np.float64)
    r_mom[valid_g] = cov_y[valid_g] / np.sqrt(var_true[valid_g] * v_cnr1)
    r_mom = np.clip(r_mom, -1.0, 1.0)
    dv_memento.update(var_names[valid_g & (np.abs(r_mom) > 0.3)])
    del Xr, Xn, Xn_sq
    gc.collect()

# (b) Raw-count donor pseudobulks for the 5 dorsal SPN Groups
dors_raw_idx = np.where(np.isin(group_arr, DORSAL_5))[0]
raw_sdg = pd.DataFrame({
    "Species": species_arr[dors_raw_idx],
    "Donor": donor_arr[dors_raw_idx],
    "Group": group_arr[dors_raw_idx],
})
rcodes, runiq = pd.factorize(raw_sdg["Species"] + "||" + raw_sdg["Donor"] + "||" + raw_sdg["Group"])
n_r = len(runiq)
raw_pb = np.zeros((n_r, n_genes), dtype=np.int64)
for s0 in range(0, len(dors_raw_idx), 40000):
    s1 = min(s0 + 40000, len(dors_raw_idx))
    Xr = adata_raw.X[dors_raw_idx[s0:s1]]
    Xr = Xr.tocsr() if sp.issparse(Xr) else sp.csr_matrix(Xr)
    c_sub = rcodes[s0:s1]
    M = sp.csr_matrix((np.ones(s1 - s0, dtype=np.float64), (c_sub, np.arange(s1 - s0))), shape=(n_r, s1 - s0))
    raw_pb += np.rint((M @ Xr).toarray()).astype(np.int64)
adata_raw.file.close()

raw_meta = pd.DataFrame([u.split("||") for u in runiq], columns=["Species", "Donor", "Group"])
raw_meta["n_cells"] = np.bincount(rcodes, minlength=n_r)
keep_pb = raw_meta["n_cells"] >= 20
raw_pb = raw_pb[keep_pb]
raw_meta = raw_meta.loc[keep_pb].reset_index(drop=True)

# 3. PyDESeq2 within each of the 5 dorsal SPN Groups across the 3 species pairs
per_group_lfc = {}
for grp in DORSAL_5:
    gm = (raw_meta["Group"] == grp).values
    cnt_df = pd.DataFrame(raw_pb[gm], columns=var_names)
    meta_g = raw_meta.loc[gm, ["Species", "Donor"]].copy()
    meta_g.index = [f"s{i}" for i in range(len(meta_g))]
    cnt_df.index = meta_g.index
    gene_keep = cnt_df.sum(axis=0) >= 10
    cnt_sub = cnt_df.loc[:, gene_keep]
    dds = DeseqDataSet(counts=cnt_sub, metadata=meta_g, design_factors="Species", n_cpus=8, quiet=True)
    dds.deseq2()
    pair_lfcs = []
    for s1, s2 in PAIRS:
        st = DeseqStats(dds, contrast=["Species", s1, s2], n_cpus=8, quiet=True)
        st.summary()
        pair_lfcs.append(st.results_df["log2FoldChange"].abs().reindex(var_names))
    per_group_lfc[grp] = pd.concat(pair_lfcs, axis=1).mean(axis=1, skipna=True)

# 4. Compute LOWESS expression-level-adjusted residual |log2FC| per dorsal SPN Group
gene_sets = {
    "5000 HVG": hvg_5000,
    "Dorsal-Ventral": dv_memento & expressed_20pct,
    "Striosome-Matrix": deg_sets["Strio_vs_Mat_LFC1.5"] & expressed_20pct,
    "D1-D2": deg_sets["D1_vs_D2_LFC1"] & expressed_20pct,
}

# Fit LOWESS per Group over the union of evaluated genes (matching Fig 2G per-Group boxplots)
rows_long = []
for grp in DORSAL_5:
    grp_expr = sum(sp_group_mean[s].loc[grp] for s in SPECIES) / 3.0
    grp_lfc = per_group_lfc[grp]
    union_g = sorted(set().union(*gene_sets.values()))
    valid_u = [g for g in union_g if pd.notna(grp_lfc.get(g, np.nan))]
    x_e = np.array([float(grp_expr[g]) for g in valid_u])
    y_l = np.array([float(grp_lfc[g]) for g in valid_u])
    lw = lowess(y_l, x_e, frac=0.3, return_sorted=False)
    resid_map = dict(zip(valid_u, y_l - lw))
    for set_name, gset in gene_sets.items():
        for g in sorted(gset):
            if g in resid_map:
                rows_long.append({
                    "Group": grp,
                    "set": set_name,
                    "gene": g,
                    "mean_expr": round(float(grp_expr[g]), 4),
                    "abs_lfc": round(float(grp_lfc[g]), 4),
                    "resid_lfc": round(float(resid_map[g]), 4),
                })

df_long = pd.DataFrame(rows_long)
df_long.to_csv(out_dir() / "fig2g_spn_axes_residuals.csv", index=False)

# Pooled gene-level median across the 5 dorsal SPN Groups for Kruskal-Wallis & Dunn's test
df_gene = df_long.groupby(["set", "gene"], as_index=False)["resid_lfc"].mean()
set_order = ["5000 HVG", "Dorsal-Ventral", "Striosome-Matrix", "D1-D2"]
kw_stat, kw_p = stats.kruskal(*[df_gene.loc[df_gene["set"] == s, "resid_lfc"].values for s in set_order])
dunn = sp_ph.posthoc_dunn(df_gene, val_col="resid_lfc", group_col="set", p_adjust="bonferroni")
# Also run KW/Dunn across all gene x Group observations (matching pooled dorsal SPN test)
kw_stat_all, kw_p_all = stats.kruskal(*[df_long.loc[df_long["set"] == s, "resid_lfc"].values for s in set_order])
dunn_all = sp_ph.posthoc_dunn(df_long, val_col="resid_lfc", group_col="set", p_adjust="bonferroni")

meds = {s: round(float(df_gene.loc[df_gene["set"] == s, "resid_lfc"].median()), 4) for s in set_order}

# Sensitivity check: raw unadjusted single-cell Pearson CNR1 genes
raw_dv_set = dv_raw_pearson & expressed_20pct
grp_expr_avg = dors_mean_avg.mean(axis=0)
lfc_avg = pd.concat(per_group_lfc.values(), axis=1).mean(axis=1, skipna=True)
u_all = sorted(set().union(*gene_sets.values(), raw_dv_set))
u_valid = [g for g in u_all if pd.notna(lfc_avg.get(g, np.nan))]
lw_avg = lowess(lfc_avg.loc[u_valid].values, grp_expr_avg.loc[u_valid].values, frac=0.3, return_sorted=False)
res_avg = dict(zip(u_valid, lfc_avg.loc[u_valid].values - lw_avg))
raw_dv_med = round(float(np.median([res_avg[g] for g in raw_dv_set if g in res_avg])), 4) if raw_dv_set else None

m = {
    "n_genes_5000_hvg": int(len(gene_sets["5000 HVG"])),
    "n_genes_dv_memento": int(len(gene_sets["Dorsal-Ventral"])),
    "n_genes_dv_raw_pearson": int(len(raw_dv_set)),
    "n_genes_strio_mat_lfc15": int(len(deg_sets["Strio_vs_Mat_LFC1.5"] & expressed_20pct)),
    "n_genes_strio_mat_lfc10": int(len(deg_sets["Strio_vs_Mat_LFC1"] & expressed_20pct)),
    "n_genes_d1_d2_lfc10": int(len(deg_sets["D1_vs_D2_LFC1"] & expressed_20pct)),
    "n_genes_d1_d2_lfc15": int(len(deg_sets["D1_vs_D2_LFC1.5"] & expressed_20pct)),
    "median_resid_hvg": meds["5000 HVG"],
    "median_resid_dv": meds["Dorsal-Ventral"],
    "median_resid_dv_raw_pearson": raw_dv_med,
    "median_resid_strio_mat": meds["Striosome-Matrix"],
    "median_resid_d1_d2": meds["D1-D2"],
    "kruskal_p_gene_level": float(kw_p),
    "kruskal_p_all_dorsal_groups": float(kw_p_all),
    "dunn_p_strio_mat_vs_hvg": float(dunn.loc["Striosome-Matrix", "5000 HVG"]),
    "dunn_p_d1_d2_vs_hvg": float(dunn.loc["D1-D2", "5000 HVG"]),
    "dunn_p_dv_vs_hvg": float(dunn.loc["Dorsal-Ventral", "5000 HVG"]),
    "strio_mat_and_d1_d2_more_diverged_than_hvg": bool(
        meds["Striosome-Matrix"] > meds["5000 HVG"]
        and meds["D1-D2"] > meds["5000 HVG"]
        and float(dunn.loc["Striosome-Matrix", "5000 HVG"]) < 0.01
        and float(dunn.loc["D1-D2", "5000 HVG"]) < 0.01
    ),
    "dv_less_diverged_than_strio_mat_and_d1_d2": bool(
        meds["Dorsal-Ventral"] < meds["Striosome-Matrix"]
        and meds["Dorsal-Ventral"] < meds["D1-D2"]
    ),
    "dv_less_diverged_than_hvg": bool(meds["Dorsal-Ventral"] < meds["5000 HVG"]),
}

# 5. Plot matching published Figure 2G: 5 dorsal SPN Group colored boxes per axis category (15th/50th/85th)
fig, ax = plt.subplots(figsize=(8.4, 4.4))
n_g = len(DORSAL_5)
box_w = 0.145
offsets = (np.arange(n_g) - (n_g - 1) / 2.0) * (box_w + 0.008)

for ci, set_name in enumerate(set_order):
    for gi, grp in enumerate(DORSAL_5):
        vals = df_long.loc[(df_long["set"] == set_name) & (df_long["Group"] == grp), "resid_lfc"].values
        if len(vals) == 0:
            continue
        q15, q25, q50, q75, q85 = np.percentile(vals, [15, 25, 50, 75, 85])
        x = ci + offsets[gi]
        # Draw box spanning 25th-75th (or 15th-85th per legend: box 25-75 / whiskers 15-85)
        ax.add_patch(
            mpatches.Rectangle((x - box_w / 2.0, q25), box_w, q75 - q25,
                               facecolor=grp_colors[grp], edgecolor="#222222", lw=0.75, zorder=3)
        )
        ax.plot([x - box_w / 2.0, x + box_w / 2.0], [q50, q50], color="#111111", lw=1.1, zorder=4)
        ax.plot([x, x], [q15, q25], color="#222222", lw=0.75, zorder=2)
        ax.plot([x, x], [q75, q85], color="#222222", lw=0.75, zorder=2)
        ax.plot([x - box_w * 0.3, x + box_w * 0.3], [q15, q15], color="#222222", lw=0.75, zorder=2)
        ax.plot([x - box_w * 0.3, x + box_w * 0.3], [q85, q85], color="#222222", lw=0.75, zorder=2)

ax.axhline(0.0, color="#222222", lw=0.8, zorder=1)

# Significance brackets matching published Figure 2G
def _stars(p):
    if p < 1e-4:
        return "**"
    if p < 0.05:
        return "*"
    return "n.s."

for yb, target_x, pval in [
    (1.25, 1, float(dunn.loc["Dorsal-Ventral", "5000 HVG"])),
    (1.42, 2, float(dunn.loc["Striosome-Matrix", "5000 HVG"])),
    (1.59, 3, float(dunn.loc["D1-D2", "5000 HVG"])),
]:
    ax.plot([0, target_x], [yb, yb], color="#222222", lw=0.85)
    ax.text((0 + target_x) / 2.0, yb + 0.015, _stars(pval), ha="center", va="bottom", fontsize=9.5, fontweight="bold")

ax.set_xticks(range(len(set_order)))
ax.set_xticklabels([
    f"5000 HVG\n(n={m['n_genes_5000_hvg']})",
    f"Dorsal-Ventral\n(n={m['n_genes_dv_memento']})",
    f"Striosome-Matrix\n(n={m['n_genes_strio_mat_lfc15']})",
    f"D1-D2\n(n={m['n_genes_d1_d2_lfc10']})",
], fontsize=8.8)
ax.set_ylabel("mean |LFC| (LOWESS residual)", fontsize=9.5)
ax.set_ylim(-1.05, 1.82)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

handles = [mpatches.Patch(facecolor=grp_colors[g], edgecolor="#222222", lw=0.5, label=g.replace(" SPN", "")) for g in DORSAL_5]
ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=3, frameon=False, fontsize=7.8)
ax.set_title(
    f"Figure 2G: SPN axis evolutionary divergence across 5 dorsal SPN Groups (KW p = {kw_p:.2e})",
    fontsize=9.8,
    fontweight="bold",
    pad=8,
)
fig.tight_layout()
fig.savefig(out_dir() / "fig2g.png", dpi=180, bbox_inches="tight")
write_metrics(m)
print(m)
