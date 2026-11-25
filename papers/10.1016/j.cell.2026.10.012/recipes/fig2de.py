# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.11", "scikit-learn>=1.5", "umap-learn>=0.5.6", "torch>=2.3", "matplotlib>=3.8"]
# ///
"""Figure 2D-E: cross-species integrated SPN UMAP across all 9 spiny projection neuron (SPN) Groups
(841,005 nuclei) alongside the 30-gene stacked violin marker plot and top Expressolog conservation bar.

Panel 2D computes a deterministic cross-species SPN embedding from scratch on HMBA-10xMultiome-BG-
Cross-Species-log2.h5ad (top 2,000 SPN HVGs -> 30-PC SVD -> PyTorch Harmony across species & donor ->
UMAP on 90,000 stratified SPN nuclei keeping 100% of STR D2 SMYD2-HTR7 SPN).
Panel 2E renders the exact 30 published markers across the 9 SPN Groups as stacked horizontal violins
colored by median expression, topped by each gene's Expressolog conservation AUROC ribbon."""
import os

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch
import umap
from sklearn.decomposition import TruncatedSVD
from sklearn.neighbors import NearestNeighbors

from bg_atlas import (
    SPECIES,
    SPN_GROUPS,
    compute_expressolog_auroc,
    data_dir,
    group_order,
    load_cells,
    load_pseudobulk_log2,
    out_dir,
    write_metrics,
)

# Exact 30 genes left-to-right from published Figure 2E (Cell 2026)
FIG2E_GENES = [
    "COCH", "DRD1", "TAC1", "CNTNAP4", "EBF1",
    "DRD2", "ADORA2A", "PENK",
    "KCNT2", "TRHDE", "GRIK1", "SMYD2", "PTN",
    "TACR1", "CASZ1", "NFIB", "VWC2L", "NTN1", "ISL1", "CUX2",
    "RXFP1", "EYA2", "KCNJ3", "TSHZ1",
    "SCN4B", "RASD2", "KCNIP1", "STXBP6", "GRIA4", "ARHGAP6",
]


def pytorch_harmony(Z_np, batch_codes, n_clusters=40, theta=2.0, sigma=0.1, n_iter=10, seed=0):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(seed)
    N, D = Z_np.shape
    B = int(batch_codes.max()) + 1
    Z_orig = torch.as_tensor(Z_np, dtype=torch.float32, device=device)
    Z_cos = torch.nn.functional.normalize(Z_orig, dim=1)
    Phi = torch.zeros((N, B), dtype=torch.float32, device=device)
    Phi[torch.arange(N, device=device), torch.as_tensor(batch_codes, dtype=torch.long, device=device)] = 1.0
    Pr_b = Phi.mean(dim=0)
    Y = Z_cos[torch.randperm(N, device=device)[:n_clusters]].clone()
    Z_corr = Z_orig.clone()
    eye_B1 = torch.eye(B + 1, dtype=torch.float32, device=device)
    eye_B1[0, 0] = 0.0
    for _ in range(n_iter):
        Z_norm = torch.nn.functional.normalize(Z_corr, dim=1)
        dist = 2.0 - 2.0 * (Z_norm @ Y.T)
        R = torch.softmax(-dist / sigma, dim=1)
        for _inner in range(3):
            O = Phi.T @ R
            E = Pr_b[:, None] * R.sum(dim=0, keepdim=True)
            penalty = ((E + 1.0) / (O + 1.0)) ** theta
            R = R * penalty[batch_codes]
            R = R / R.sum(dim=1, keepdim=True).clamp(min=1e-12)
        Y = torch.nn.functional.normalize(R.T @ Z_norm, dim=1)
        Z_new = torch.zeros_like(Z_orig)
        Phi_aug = torch.cat([torch.ones((N, 1), dtype=torch.float32, device=device), Phi], dim=1)
        for k in range(n_clusters):
            rk = R[:, k]
            if rk.sum() < 1.0:
                continue
            wPhi = Phi_aug * rk[:, None]
            W = torch.linalg.solve(Phi_aug.T @ wPhi + eye_B1, wPhi.T @ Z_orig)
            Z_new += rk[:, None] * (Z_orig - (Phi @ W[1:]))
        Z_corr = Z_new
    return Z_corr.cpu().numpy()


seed = int(os.environ.get("RP_SEED", "0"))
rng = np.random.default_rng(seed)

# 1. Load pseudobulk for Expressolog conservation bar & per-species marker verification
pb = load_pseudobulk_log2()
var_names_pb = pb["var_names"]
sp_group_mean = pb["sp_group_mean"]
cor_df = compute_expressolog_auroc(sp_group_mean, var_names_pb)

cells, _ = load_cells()
_, grp_colors = group_order()
grp_colors = dict(grp_colors)
grp_colors["STR D2 SMYD2-HTR7 SPN"] = "#54278f"

adata = ad.read_h5ad(data_dir() / "HMBA-10xMultiome-BG-Cross-Species-log2.h5ad", backed="r")
var_names = (
    adata.var["gene_symbol"].astype(str).values
    if "gene_symbol" in adata.var.columns
    else adata.var_names.astype(str).values
)
meta_idx = cells.set_index("cell_label").reindex(adata.obs_names)
sp_arr = meta_idx["species_genus"].astype(str).values
grp_arr = meta_idx["Group"].astype(str).values
sub_arr = meta_idx["Subclass"].astype(str).values
dn_arr = meta_idx["donor_label"].astype(str).values

spn_mask = np.isin(grp_arr, SPN_GROUPS)
spn_all_idx = np.where(spn_mask)[0]
n_spn_total = int(len(spn_all_idx))

# Stratified 90,000-cell SPN subsample (keep 100% of STR D2 SMYD2-HTR7 SPN, balanced across all 9 Groups)
sel_parts = []
for g in SPN_GROUPS:
    gi = np.where(grp_arr == g)[0]
    cap = len(gi) if g == "STR D2 SMYD2-HTR7 SPN" else min(len(gi), 10000)
    sel_parts.append(rng.choice(gi, size=cap, replace=False) if cap < len(gi) else gi)
sub_idx = np.sort(np.concatenate(sel_parts))

# Load sub_idx expression via fast contiguous streaming (avoids slow HDF5 fancy indexing)
print("[fig2de] Streaming 90k SPN nuclei contiguously from Cross-Species-log2.h5ad...", flush=True)
g2i = {g: i for i, g in enumerate(var_names)}
marker_idx = [g2i[g] for g in FIG2E_GENES]

sub_mask_all = np.zeros(adata.shape[0], dtype=bool)
sub_mask_all[sub_idx] = True
blocks = []
for s0 in range(0, adata.shape[0], 60000):
    s1 = min(s0 + 60000, adata.shape[0])
    loc_m = sub_mask_all[s0:s1]
    if not loc_m.any():
        continue
    Xs = adata.X[s0:s1]
    Xs = Xs.tocsr() if sp.issparse(Xs) else sp.csr_matrix(Xs)
    blocks.append(Xs[loc_m].astype(np.float32))
adata.file.close()
X_spn = sp.vstack(blocks, format="csr").astype(np.float32)
del blocks

# HVG selection within SPNs
g_mean = np.asarray(X_spn.mean(axis=0)).ravel()
X_sq = X_spn.copy()
X_sq.data = X_sq.data ** 2
g_var = np.maximum(np.asarray(X_sq.mean(axis=0)).ravel() - g_mean ** 2, 0.0)
disp = np.where(g_mean > 0.05, g_var / (g_mean + 0.05), 0.0)
hvg_idx = np.sort(np.argsort(disp)[-2000:])

# 2. Panel 2D: Per-species z-scaling -> GPU 30-PC SVD -> GPU PyTorch Harmony -> UMAP
print("[fig2de] Running per-species z-scaling + GPU 30-PC SVD + GPU Harmony + UMAP...", flush=True)
X_hvg_d = X_spn[:, hvg_idx].toarray().astype(np.float32)
sp_sub = sp_arr[sub_idx]
for sp_name in SPECIES:
    sm = sp_sub == sp_name
    mu_s = X_hvg_d[sm].mean(axis=0, keepdims=True)
    sd_s = X_hvg_d[sm].std(axis=0, keepdims=True) + 1e-4
    X_hvg_d[sm] = np.clip((X_hvg_d[sm] - mu_s) / sd_s, -10.0, 10.0)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.manual_seed(seed)
Xt = torch.as_tensor(X_hvg_d, dtype=torch.float32, device=device)
U_s, S_s, _ = torch.pca_lowrank(Xt, q=30, center=True, niter=4)
Z_pca = (U_s * S_s).cpu().numpy().astype(np.float32)
del Xt, U_s, S_s, X_hvg_d

sp_batch, _ = pd.factorize(sp_sub)
Z_harm = pytorch_harmony(Z_pca, sp_batch, n_clusters=40, theta=3.0, sigma=0.1, n_iter=12, seed=seed)
dn_batch, _ = pd.factorize(pd.Series(sp_sub) + "::" + pd.Series(dn_arr[sub_idx]))
Z_harm = pytorch_harmony(Z_harm, dn_batch, n_clusters=40, theta=2.0, sigma=0.1, n_iter=10, seed=seed)

# Evaluate SPN subclass separation (STR D1 SPN / STR D2 SPN / STR Eccentric SPN) on GPU
Z_t = torch.nn.functional.normalize(torch.as_tensor(Z_harm, dtype=torch.float32, device=device), dim=1)
nbr15 = np.empty((len(sub_idx), 16), dtype=np.int32)
for b0 in range(0, len(sub_idx), 4096):
    b1 = min(b0 + 4096, len(sub_idx))
    _, idx_t = torch.topk(Z_t[b0:b1] @ Z_t.T, k=16, dim=1, largest=True, sorted=True)
    nbr15[b0:b1] = idx_t.cpu().numpy().astype(np.int32)
sub_codes, _ = pd.factorize(sub_arr[sub_idx])
spn_subclass_purity = float((sub_codes[nbr15[:, 1:]] == sub_codes[:, None]).mean())
print(f"[fig2de] SPN subclass kNN purity={spn_subclass_purity:.4f}. Running UMAP...", flush=True)

reducer = umap.UMAP(n_neighbors=30, min_dist=0.30, metric="cosine", random_state=seed, low_memory=True)
coords = reducer.fit_transform(Z_harm).astype(np.float32)

# 3. Panel 2E: per-cell distributions for the 30 markers + per-species conservation table
X_mk = X_spn[:, marker_idx].toarray()
grp_sub = grp_arr[sub_idx]

sp_rows = []
for g in FIG2E_GENES:
    au = float(cor_df.loc[g, "auroc"]) if g in cor_df.index else np.nan
    for grp in SPN_GROUPS:
        row = {"gene": g, "Group": grp, "expressolog_auroc": round(au, 4)}
        for sp_name in SPECIES:
            row[f"{sp_name}_mean_log2"] = round(float(sp_group_mean[sp_name].loc[grp, g]), 4)
        sp_rows.append(row)
pd.DataFrame(sp_rows).to_csv(out_dir() / "fig2e_spn_markers_by_species.csv", index=False)

# Conservation checks across all 3 primates
d1_grps = ["STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRv D1 SPN"]
d2_grps = ["STRd D2 Matrix SPN", "STRd D2 Striosome SPN", "STRv D2 SPN"]
espn_grps = ["STR D1D2 eSPN", "STRv D1 NUDAP eSPN"]
smyd_grp = "STR D2 SMYD2-HTR7 SPN"

drd1_d1_all3 = all(
    sp_group_mean[s].loc[d1_grps, "DRD1"].mean() > sp_group_mean[s].loc[d2_grps, "DRD1"].mean()
    for s in SPECIES
)
drd2_d2_all3 = all(
    sp_group_mean[s].loc[d2_grps, "DRD2"].mean() > sp_group_mean[s].loc[d1_grps, "DRD2"].mean()
    for s in SPECIES
)
smyd2_enriched_all3 = all(
    sp_group_mean[s].loc[smyd_grp, "SMYD2"] > sp_group_mean[s].loc[d2_grps, "SMYD2"].mean()
    and sp_group_mean[s].loc[smyd_grp, "KCNT2"] > sp_group_mean[s].loc[d2_grps, "KCNT2"].mean()
    for s in SPECIES
)
rxfp1_espn_all3 = all(
    sp_group_mean[s].loc[espn_grps, "RXFP1"].mean() > 3.0 * sp_group_mean[s].loc[d1_grps + d2_grps + [smyd_grp], "RXFP1"].mean()
    for s in SPECIES
)

m = {
    "n_spn_nuclei_total": n_spn_total,
    "n_spn_groups": int(len(SPN_GROUPS)),
    "n_spn_plotted_umap": int(len(sub_idx)),
    "n_markers_fig2e": int(len(FIG2E_GENES)),
    "spn_subclass_knn15_purity": round(spn_subclass_purity, 4),
    "drd1_enriched_in_d1_all_species": bool(drd1_d1_all3),
    "drd2_enriched_in_d2_all_species": bool(drd2_d2_all3),
    "smyd2_kcnt2_enriched_in_smyd2_all_species": bool(smyd2_enriched_all3),
    "rxfp1_restricted_to_espn_all_species": bool(rxfp1_espn_all3),
    "mean_auroc_30_markers": round(float(cor_df.loc[FIG2E_GENES, "auroc"].mean()), 4),
}

# 4. Combined Figure 2D (left) + Figure 2E (right) matching main-06.png
fig = plt.figure(figsize=(15.0, 5.2))
gs = gridspec.GridSpec(1, 2, width_ratios=[0.85, 2.25], wspace=0.28, left=0.02, right=0.93, top=0.88, bottom=0.22)

# Left: 2D SPN UMAP
ax_u = fig.add_subplot(gs[0, 0])
perm_p = rng.permutation(len(sub_idx))
c_spn = [grp_colors[g] for g in grp_sub[perm_p]]
ax_u.scatter(coords[perm_p, 0], coords[perm_p, 1], c=c_spn, s=0.4, alpha=0.65, edgecolors="none", rasterized=True)
for sc_name in ["STR D1 SPN", "STR D2 SPN", "STR Eccentric SPN"]:
    sm = sub_arr[sub_idx] == sc_name
    if sm.sum() > 0:
        cx, cy = float(np.median(coords[sm, 0])), float(np.median(coords[sm, 1]))
        ax_u.text(cx, cy, sc_name, fontsize=8.2, fontweight="bold", ha="center", va="center",
                  bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="#444444", lw=0.5, alpha=0.82))
ax_u.set_title(f"D   Cross-species SPN UMAP ({n_spn_total:,} nuclei)", fontsize=9.8, fontweight="bold", loc="left", pad=8)
ax_u.set_xlabel("UMAP-1", fontsize=8.2)
ax_u.set_ylabel("UMAP-2", fontsize=8.2)
ax_u.set_xticks([]); ax_u.set_yticks([])
for s in ("top", "right"):
    ax_u.spines[s].set_visible(False)

# Right: 2E Top conservation ribbon + 9x30 stacked violin grid
gs_e = gridspec.GridSpecFromSubplotSpec(
    2, 1, subplot_spec=gs[0, 1], height_ratios=[0.11, 1.0], hspace=0.06
)
ax_con = fig.add_subplot(gs_e[0, 0])
ax_vio = fig.add_subplot(gs_e[1, 0])

# Top conservation bar (Expressolog AUROC 0..1, Reds)
au_vals = np.array([float(cor_df.loc[g, "auroc"]) for g in FIG2E_GENES])[None, :]
im_con = ax_con.imshow(au_vals, aspect="auto", cmap="Reds", vmin=0.0, vmax=1.0, interpolation="nearest")
ax_con.set_xticks([]); ax_con.set_yticks([])
ax_con.set_title("E   Conserved SPN Group markers across Human, Macaque & Marmoset", fontsize=9.8, fontweight="bold", loc="left", pad=6)

# Stacked violins inside ax_vio: 9 rows (y=0..8) x 30 cols (x=0..29)
n_r, n_c = len(SPN_GROUPS), len(FIG2E_GENES)
cmap_vio = cm.get_cmap("Blues")
norm_vio = mcolors.Normalize(0.0, 8.0)

for ci, gene in enumerate(FIG2E_GENES):
    # Global max for gene to normalize vertical violin shape cleanly across the 9 Groups
    col_vals = X_mk[:, ci]
    g_p99 = max(float(np.percentile(col_vals, 99.5)), 1.0)
    for ri, grp in enumerate(SPN_GROUPS):
        vals = col_vals[grp_sub == grp]
        # Draw baseline
        ax_vio.plot([ci - 0.38, ci + 0.38], [ri, ri], color="#777777", lw=0.4, zorder=1)
        med = float(np.median(vals))
        mean_v = float(np.mean(vals))
        # Histogram-based symmetric violin polygon (fast, crisp, deterministic!)
        bins = np.linspace(0.0, g_p99, 14)
        hist, edges = np.histogram(np.clip(vals, 0.0, g_p99), bins=bins)
        if hist.max() > 0:
            # Emphasize non-zero density when expressed, keep zero-spike compact
            h_norm = hist / hist.max()
            # Vertical coordinate within row ri: [ri + 0.40 (low) .. ri - 0.40 (high)] (y inverted)
            centers = 0.5 * (edges[:-1] + edges[1:])
            y_coords = ri + 0.38 - 0.76 * (centers / g_p99)
            w_half = 0.38 * h_norm
            fill_col = cmap_vio(norm_vio(med if med > 0 else 0.5 * mean_v))
            ax_vio.fill_betweenx(
                y_coords,
                ci - w_half,
                ci + w_half,
                facecolor=fill_col,
                edgecolor="#333333",
                linewidth=0.35,
                zorder=2,
            )

# Left Group color squares inside left margin of ax_vio
for ri, grp in enumerate(SPN_GROUPS):
    ax_vio.add_patch(
        mpatches.Rectangle((-1.15, ri - 0.34), 0.58, 0.68, facecolor=grp_colors[grp],
                           edgecolor="#222222", lw=0.45, clip_on=False, zorder=4)
    )

# Red dashed module boxes matching published Figure 2E
for x0, x1, y0, y1 in [
    (0.55, 4.45, -0.45, 2.45),    # D1 markers
    (4.55, 7.45, 2.55, 5.45),     # D2 markers
    (10.55, 12.45, 5.55, 6.45),   # SMYD2 / PTN
    (12.55, 14.45, 6.55, 7.45),   # TACR1 / CASZ1
    (14.55, 16.45, 7.55, 8.45),   # NFIB / VWC2L
]:
    ax_vio.add_patch(
        mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="#d62728", ls="--", lw=0.95, zorder=5)
    )

ax_vio.set_xlim(-0.5, n_c - 0.5)
ax_vio.set_ylim(n_r - 0.5, -0.5)
ax_vio.set_xticks(range(n_c))
ax_vio.set_xticklabels(FIG2E_GENES, rotation=90, fontsize=7.6)
ax_vio.set_yticks(range(n_r))
ax_vio.set_yticklabels(SPN_GROUPS, fontsize=8.0)
ax_vio.tick_params(axis="y", pad=16, length=0)

# Colorbars on far right
cax_con = fig.add_axes([0.942, 0.64, 0.013, 0.22])
cb_con = fig.colorbar(im_con, cax=cax_con)
cb_con.set_ticks([0.0, 1.0])
cb_con.set_label("Conservation\n(AUROC)", fontsize=7.5, rotation=270, labelpad=16)
cb_con.ax.tick_params(labelsize=7)

cax_med = fig.add_axes([0.942, 0.24, 0.013, 0.30])
sm_vio = cm.ScalarMappable(norm=norm_vio, cmap=cmap_vio)
cb_med = fig.colorbar(sm_vio, cax=cax_med)
cb_med.set_ticks([0.0, 4.0, 8.0])
cb_med.set_label("Gene expr.\n(median log2)", fontsize=7.5, rotation=270, labelpad=16)
cb_med.ax.tick_params(labelsize=7)

fig.savefig(out_dir() / "fig2de.png", dpi=180)
write_metrics(m)
print(m)
