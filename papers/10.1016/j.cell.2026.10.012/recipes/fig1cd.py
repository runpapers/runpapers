# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "anndata>=0.11", "scikit-learn>=1.5", "umap-learn>=0.5.6", "torch>=2.3", "matplotlib>=3.8"]
# ///
"""Figure 1C-D: cross-species integrated basal ganglia UMAP across all 1,896,133 nuclei (61 Groups,
4 Neighborhoods, 3 primates) with species alignment entropy, dissected anatomical region, and
neurotransmitter identity overlays.

The public ABC Atlas expression matrix (HMBA-10xMultiome-BG-Cross-Species-log2.h5ad) omits the
precomputed scVI UMAP coordinates, so this recipe computes a deterministic cross-species integrated
embedding from scratch: top 2,500 HVGs across all 1.90M nuclei -> 50-PC SVD -> PyTorch Harmony
integration across species & donor (GPU-accelerated when CUDA is available) -> k=100 local species
mixing entropy -> UMAP on a 200,000-nucleus stratified representation covering all 61 Groups."""
import os

import anndata as ad
import matplotlib

matplotlib.use("Agg")
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
    data_dir,
    group_order,
    load_cells,
    out_dir,
    region_palette,
    write_metrics,
)


def pytorch_harmony(Z_np, batch_codes, n_clusters=80, theta=2.0, sigma=0.1, n_iter=10, seed=0):
    """Lightweight deterministic Harmony integration in PyTorch (runs on CUDA GPU if available)."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(seed)
    np.random.seed(seed)

    N, D = Z_np.shape
    B = int(batch_codes.max()) + 1
    Z_orig = torch.as_tensor(Z_np, dtype=torch.float32, device=device)
    # L2-normalize rows for cosine clustering
    Z_cos = torch.nn.functional.normalize(Z_orig, dim=1)

    # One-hot batch design matrix (N, B)
    Phi = torch.zeros((N, B), dtype=torch.float32, device=device)
    Phi[torch.arange(N, device=device), torch.as_tensor(batch_codes, dtype=torch.long, device=device)] = 1.0
    Pr_b = Phi.mean(dim=0)  # (B,)

    # Initialize K centroids from stratified random cells
    perm = torch.randperm(N, device=device)[:n_clusters]
    Y = Z_cos[perm].clone()  # (K, D)

    Z_corr = Z_orig.clone()
    eye_B1 = torch.eye(B + 1, dtype=torch.float32, device=device)
    eye_B1[0, 0] = 0.0  # do not penalize intercept

    for _ in range(n_iter):
        Z_norm = torch.nn.functional.normalize(Z_corr, dim=1)
        # Soft assignment R: (N, K)
        dist = 2.0 - 2.0 * (Z_norm @ Y.T)
        R = torch.softmax(-dist / sigma, dim=1)

        # Diversity penalty update (3 inner coordinate steps)
        for _inner in range(3):
            O = Phi.T @ R  # (B, K)
            E = Pr_b[:, None] * R.sum(dim=0, keepdim=True)  # (B, K)
            penalty = ((E + 1.0) / (O + 1.0)) ** theta  # (B, K)
            # Apply per-cell batch penalty
            R = R * penalty[batch_codes]
            R = R / R.sum(dim=1, keepdim=True).clamp(min=1e-12)

        # Update centroids
        Y = torch.nn.functional.normalize(R.T @ Z_norm, dim=1)

        # Linear mixture-of-experts ridge regression correction per cluster
        Z_new = torch.zeros_like(Z_orig)
        Phi_aug = torch.cat([torch.ones((N, 1), dtype=torch.float32, device=device), Phi], dim=1)  # (N, B+1)
        for k in range(n_clusters):
            rk = R[:, k]  # (N,)
            rk_sum = rk.sum()
            if rk_sum < 1.0:
                continue
            wPhi = Phi_aug * rk[:, None]
            lhs = Phi_aug.T @ wPhi + 1.0 * eye_B1
            rhs = wPhi.T @ Z_orig
            W = torch.linalg.solve(lhs, rhs)  # (B+1, D)
            # Subtract batch-specific shifts (rows 1..B), preserve intercept W[0]
            batch_shift = Phi @ W[1:]  # (N, D)
            Z_new += rk[:, None] * (Z_orig - batch_shift)
        Z_corr = Z_new

    return Z_corr.cpu().numpy()


def fast_cosine_knn(X_emb, k=100, batch_size=4096):
    """Exact cosine kNN using batched PyTorch matmul (CUDA GPU if available, else CPU)."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    Z = torch.nn.functional.normalize(torch.as_tensor(X_emb, dtype=torch.float32, device=device), dim=1)
    N = Z.shape[0]
    out = np.empty((N, k), dtype=np.int32)
    for b0 in range(0, N, batch_size):
        b1 = min(b0 + batch_size, N)
        sim = Z[b0:b1] @ Z.T
        _, idx = torch.topk(sim, k=k, dim=1, largest=True, sorted=True)
        out[b0:b1] = idx.cpu().numpy().astype(np.int32)
    return out


def local_species_entropy(X_emb, sp_codes, k=100):
    """Compute k-NN Shannon entropy of species labels in embedding space (matches UMAP_species_mixing.py)."""
    nbrs = fast_cosine_knn(X_emb, k=k)
    ent = np.zeros(len(sp_codes), dtype=np.float32)
    for c in range(3):
        p = (sp_codes[nbrs] == c).mean(axis=1)
        ent -= np.where(p > 0, p * np.log(np.where(p > 0, p, 1.0)), 0.0)
    return ent


seed = int(os.environ.get("RP_SEED", "0"))
rng = np.random.default_rng(seed)

cells, _ = load_cells()
order, grp_colors = group_order()
_, reg_colors = region_palette(exclude=())

adata = ad.read_h5ad(data_dir() / "HMBA-10xMultiome-BG-Cross-Species-log2.h5ad", backed="r")
var_names = (
    adata.var["gene_symbol"].astype(str).values
    if "gene_symbol" in adata.var.columns
    else adata.var_names.astype(str).values
)
n_cells, n_genes = adata.shape
meta_idx = cells.set_index("cell_label").reindex(adata.obs_names)

sp_arr = meta_idx["species_genus"].astype(str).values
grp_arr = meta_idx["Group"].astype(str).values
nb_arr = meta_idx["Neighborhood"].astype(str).values
cls_arr = meta_idx["Class"].astype(str).values
reg_arr = meta_idx["region_of_interest_label"].astype(str).values
dn_arr = meta_idx["donor_label"].astype(str).values

# 1. Stratified sample of ~120,000 nuclei preserving ALL 61 Groups (100% of rare Groups <= 1,000 cells)
print("[fig1cd] Selecting stratified ~120k nuclei & streaming Cross-Species-log2.h5ad contiguously...", flush=True)
target_n = 120000
sel_parts = []
large_groups = []
for g in order:
    gi = np.where(grp_arr == g)[0]
    if len(gi) <= 1000:
        sel_parts.append(gi)
    else:
        large_groups.append((g, gi))

rem = max(0, target_n - sum(len(x) for x in sel_parts))
tot_large = sum(len(gi) for _, gi in large_groups)
for g, gi in large_groups:
    k_g = max(1000, int(round(rem * len(gi) / tot_large)))
    k_g = min(k_g, len(gi))
    sel_parts.append(rng.choice(gi, size=k_g, replace=False))
sub_idx = np.sort(np.concatenate(sel_parts))
sub_mask_all = np.zeros(n_cells, dtype=bool)
sub_mask_all[sub_idx] = True

# Single contiguous streaming pass: compute per-gene mean/var, NT markers (1.90M cells), and collect stratified rows
nt_genes = ["GAD1", "GAD2", "SLC32A1", "SLC17A6", "SLC17A7", "CHAT", "SLC5A7", "TH", "DDC", "SLC6A3", "SLC18A2"]
nt_idx = [i for i, g in enumerate(var_names) if g in set(nt_genes)]
nt_names = [var_names[i] for i in nt_idx]

gene_sum = np.zeros(n_genes, dtype=np.float64)
gene_sq = np.zeros(n_genes, dtype=np.float64)
nt_expr_all = np.zeros((n_cells, len(nt_idx)), dtype=np.float32)
sub_blocks = []

chunk = 60000
for s0 in range(0, n_cells, chunk):
    s1 = min(s0 + chunk, n_cells)
    X_sub = adata.X[s0:s1]
    X_sub = X_sub.tocsr() if sp.issparse(X_sub) else sp.csr_matrix(X_sub)
    gene_sum += np.asarray(X_sub.sum(axis=0)).ravel()
    X_sq = X_sub.copy()
    X_sq.data = X_sq.data ** 2
    gene_sq += np.asarray(X_sq.sum(axis=0)).ravel()
    nt_expr_all[s0:s1] = X_sub[:, nt_idx].toarray()
    loc_m = sub_mask_all[s0:s1]
    if loc_m.any():
        sub_blocks.append(X_sub[loc_m].astype(np.float32))
adata.file.close()

gene_mean = gene_sum / n_cells
gene_var = np.maximum(gene_sq / n_cells - gene_mean ** 2, 0.0)
disp = np.where(gene_mean > 0.05, gene_var / (gene_mean + 0.05), 0.0)
hvg_idx = np.sort(np.argsort(disp)[-2500:])
X_hvg_raw = sp.vstack(sub_blocks, format="csr")[:, hvg_idx].toarray().astype(np.float32)
del sub_blocks
print(f"[fig1cd] Streamed 1.90M cells; X_hvg={X_hvg_raw.shape}. Running raw PCA, per-species scaling + GPU Harmony...", flush=True)

# 3a. Pre-integration PCA (unscaled across species, to quantify baseline species separation)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.manual_seed(seed)
Xt_raw = torch.as_tensor(X_hvg_raw, dtype=torch.float32, device=device)
U_r, S_r, _ = torch.pca_lowrank(Xt_raw, q=50, center=True, niter=3)
Z_pca_raw = (U_r * S_r).cpu().numpy().astype(np.float32)
del Xt_raw, U_r, S_r

# 3b. Per-species gene z-scoring (removes cross-species sequencing/annotation offset) -> 50-PC SVD -> GPU Harmony
X_scaled = X_hvg_raw.copy()
sp_sub = sp_arr[sub_idx]
for sp_name in SPECIES:
    sm = sp_sub == sp_name
    mu_s = X_scaled[sm].mean(axis=0, keepdims=True)
    sd_s = X_scaled[sm].std(axis=0, keepdims=True) + 1e-4
    X_scaled[sm] = np.clip((X_scaled[sm] - mu_s) / sd_s, -10.0, 10.0)
del X_hvg_raw

Xt_sc = torch.as_tensor(X_scaled, dtype=torch.float32, device=device)
U_s, S_s, _ = torch.pca_lowrank(Xt_sc, q=50, center=True, niter=4)
Z_pca_sc = (U_s * S_s).cpu().numpy().astype(np.float32)
del Xt_sc, U_s, S_s, X_scaled

# First integrate species_genus strongly, then fine-tune across species::donor
sp_batch, _ = pd.factorize(sp_sub)
Z_harm = pytorch_harmony(Z_pca_sc, sp_batch, n_clusters=80, theta=3.0, sigma=0.1, n_iter=12, seed=seed)
dn_batch, _ = pd.factorize(pd.Series(sp_sub) + "::" + pd.Series(dn_arr[sub_idx]))
Z_harm = pytorch_harmony(Z_harm, dn_batch, n_clusters=80, theta=2.0, sigma=0.1, n_iter=10, seed=seed)

# 4. Evaluate species mixing entropy (k=100) and Neighborhood purity (k=15) on GPU
print("[fig1cd] Computing k=100 species entropy & k=15 Neighborhood purity on GPU...", flush=True)
sp_codes_sub = pd.Categorical(sp_sub, categories=SPECIES).codes
ent_pre = local_species_entropy(Z_pca_raw, sp_codes_sub, k=100)
ent_post = local_species_entropy(Z_harm, sp_codes_sub, k=100)

nbr15 = fast_cosine_knn(Z_harm, k=16)
nb_codes_sub, nb_uniques = pd.factorize(nb_arr[sub_idx])
nb_purity = float((nb_codes_sub[nbr15[:, 1:]] == nb_codes_sub[:, None]).mean())

# 5. UMAP embedding
print(f"[fig1cd] Entropy {np.median(ent_pre):.3f}->{np.median(ent_post):.3f}, nb_purity={nb_purity:.4f}. Running UMAP...", flush=True)
reducer = umap.UMAP(n_neighbors=30, min_dist=0.35, metric="cosine", random_state=seed, low_memory=True)
coords = reducer.fit_transform(Z_harm).astype(np.float32)

# 6. Neurotransmitter identity per cell across all 1.90M nuclei
nt_df_all = pd.DataFrame(nt_expr_all, columns=nt_names)
gaba_s = nt_df_all[[c for c in ["GAD1", "GAD2", "SLC32A1"] if c in nt_df_all]].mean(axis=1).values
glut_s = nt_df_all[[c for c in ["SLC17A6", "SLC17A7"] if c in nt_df_all]].mean(axis=1).values
chol_s = nt_df_all[[c for c in ["CHAT", "SLC5A7"] if c in nt_df_all]].mean(axis=1).values
dopa_s = nt_df_all[[c for c in ["TH", "DDC", "SLC6A3", "SLC18A2"] if c in nt_df_all]].mean(axis=1).values

# Check canonical NT marker enrichments against taxonomy labels across all 1.90M nuclei
is_nn = nb_arr == "Nonneuron"
is_gaba_grp = (nb_arr == "Subpallium GABA")
is_glut_grp = (cls_arr == "F M Glut")
is_dopa_grp = (cls_arr == "M Dopa")
is_chol_grp = np.array(["Cholinergic" in g for g in grp_arr])

nt_sub_mat = np.vstack([gaba_s[sub_idx], glut_s[sub_idx], chol_s[sub_idx], dopa_s[sub_idx]]).T
nt_max = nt_sub_mat.max(axis=1)
nt_arg = nt_sub_mat.argmax(axis=1)
nt_lbl_sub = np.where(
    nb_arr[sub_idx] == "Nonneuron",
    "Non-NT/Glia",
    np.where(
        nb_arr[sub_idx] == "Subpallium GABA-Glut",
        "GABA-Glut",
        np.where(nt_max < 0.4, "Non-NT/Glia", np.array(["GABA", "Glut", "Chol", "Dopa"])[nt_arg]),
    ),
)

# Save compact Group centroid summary CSV
cent_rows = []
for g in order:
    gm = grp_arr[sub_idx] == g
    cent_rows.append({
        "Group": g,
        "n_plotted": int(gm.sum()),
        "umap1_median": round(float(np.median(coords[gm, 0])), 4),
        "umap2_median": round(float(np.median(coords[gm, 1])), 4),
        "median_species_entropy": round(float(np.median(ent_post[gm])), 4),
    })
pd.DataFrame(cent_rows).to_csv(out_dir() / "fig1cd_group_centroids.csv", index=False)

m = {
    "n_nuclei_total": int(n_cells),
    "n_neighborhoods": int(len(np.unique(nb_arr))),
    "n_groups_embedded": int(len(np.unique(grp_arr[sub_idx]))),
    "n_nuclei_plotted": int(len(sub_idx)),
    "median_species_entropy_pre_harmony": round(float(np.median(ent_pre)), 4),
    "median_species_entropy_post_harmony": round(float(np.median(ent_post)), 4),
    "harmony_improves_species_mixing": bool(np.median(ent_post) > np.median(ent_pre)),
    "neighborhood_knn15_purity": round(nb_purity, 4),
    "gaba_marker_enriched_in_gaba_groups": bool(gaba_s[is_gaba_grp].mean() > 3.0 * gaba_s[is_nn].mean()),
    "glut_marker_enriched_in_glut_groups": bool(glut_s[is_glut_grp].mean() > 3.0 * glut_s[is_nn].mean()),
    "dopa_marker_enriched_in_dopa_groups": bool(dopa_s[is_dopa_grp].mean() > 3.0 * dopa_s[is_nn].mean()),
    "chol_marker_enriched_in_chol_groups": bool(chol_s[is_chol_grp].mean() > 3.0 * chol_s[is_nn].mean()),
}

# Plot Figure 1C (top) + Figure 1D (bottom 3 panels) matching main-04.png layout
fig = plt.figure(figsize=(10.5, 11.4))
gs = gridspec.GridSpec(2, 3, height_ratios=[1.65, 1.0], wspace=0.06, hspace=0.14,
                       left=0.03, right=0.97, top=0.93, bottom=0.05)

ax_c = fig.add_subplot(gs[0, :])
ax_d1 = fig.add_subplot(gs[1, 0])
ax_d2 = fig.add_subplot(gs[1, 1])
ax_d3 = fig.add_subplot(gs[1, 2])

perm_plot = rng.permutation(len(sub_idx))
ux = coords[perm_plot, 0]
uy = coords[perm_plot, 1]

# 1C: 61 Groups colored by release hex colors
c_grp = [grp_colors.get(g, "#888888") for g in grp_arr[sub_idx[perm_plot]]]
ax_c.scatter(ux, uy, c=c_grp, s=0.35, alpha=0.7, edgecolors="none", rasterized=True)
ax_c.set_title(f"C   Cross-species integrated UMAP (61 consensus Groups, {len(sub_idx):,} stratified of 1.90M nuclei)",
               fontsize=10.2, fontweight="bold", loc="left", pad=6)
ax_c.set_xticks([]); ax_c.set_yticks([])
for s in ("top", "right", "bottom", "left"):
    ax_c.spines[s].set_visible(False)

# Annotate landmark Groups / Non-Neurons at cluster medians
landmarks = [
    "STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRd D2 Matrix SPN", "STRd D2 Striosome SPN",
    "STRv D1 SPN", "STRv D2 SPN", "STR D2 SMYD2-HTR7 SPN", "STR D1D2 eSPN", "STRv D1 NUDAP eSPN",
    "OT ICj Granule", "Oligo OPALIN", "Astrocyte", "Microglia", "SN SOX6 Dopa", "STH PVALB-PITX2 Glut",
]
for g in landmarks:
    gm = grp_arr[sub_idx] == g
    if gm.sum() > 0:
        cx, cy = float(np.median(coords[gm, 0])), float(np.median(coords[gm, 1]))
        ax_c.text(cx, cy, g.replace(" SPN", ""), fontsize=6.8, fontweight="bold", ha="center", va="center",
                  color="#111111", bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="none", alpha=0.72))

# 1D-left: Species alignment (k=100 entropy)
sc1 = ax_d1.scatter(ux, uy, c=ent_post[perm_plot], cmap="magma", vmin=0.0, vmax=np.log(3.0),
                    s=0.25, alpha=0.75, edgecolors="none", rasterized=True)
ax_d1.set_title("D   Species alignment (k=100 entropy)", fontsize=9.0, fontweight="bold")
cb1 = plt.colorbar(sc1, ax=ax_d1, orientation="horizontal", fraction=0.045, pad=0.03)
cb1.set_ticks([0.0, np.log(3.0)])
cb1.set_ticklabels(["Low", "High"])
cb1.ax.tick_params(labelsize=7.5)

# 1D-middle: Anatomical region (plot Marmoset 'Br' first in gray, then dissected Human/Macaque regions on top)
reg_sub = reg_arr[sub_idx[perm_plot]]
is_br = reg_sub == "Br"
ax_d2.scatter(ux[is_br], uy[is_br], c="#d9d9d9", s=0.20, alpha=0.45, edgecolors="none", rasterized=True)
ax_d2.scatter(ux[~is_br], uy[~is_br], c=[reg_colors.get(r, "#888888") for r in reg_sub[~is_br]],
              s=0.25, alpha=0.70, edgecolors="none", rasterized=True)
ax_d2.set_title("Anatomical region (release palette)", fontsize=9.0, fontweight="bold")

# 1D-right: Neurotransmitter identity
nt_palette = {
    "GABA": "#e67e22",
    "Glut": "#2980b9",
    "Chol": "#27ae60",
    "Dopa": "#8e44ad",
    "GABA-Glut": "#d01c8b",
    "Non-NT/Glia": "#d5d5d5",
}
nt_p = nt_lbl_sub[perm_plot]
is_glia = nt_p == "Non-NT/Glia"
ax_d3.scatter(ux[is_glia], uy[is_glia], c="#d5d5d5", s=0.20, alpha=0.45, edgecolors="none", rasterized=True)
ax_d3.scatter(ux[~is_glia], uy[~is_glia], c=[nt_palette[x] for x in nt_p[~is_glia]],
              s=0.25, alpha=0.75, edgecolors="none", rasterized=True)
ax_d3.set_title("Neurotransmitter identity", fontsize=9.0, fontweight="bold")
nt_handles = [mpatches.Patch(facecolor=nt_palette[k], label=k) for k in ("GABA", "Glut", "Chol", "Dopa", "GABA-Glut")]
ax_d3.legend(handles=nt_handles, loc="lower center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False, fontsize=7.2)

for ax in (ax_d1, ax_d2, ax_d3):
    ax.set_xticks([]); ax.set_yticks([])
    for s in ("top", "right", "bottom", "left"):
        ax.spines[s].set_visible(False)

fig.suptitle(
    f"Figure 1C-D: Cross-species integrated atlas ({n_cells:,} nuclei; median species entropy {m['median_species_entropy_pre_harmony']:.2f} -> {m['median_species_entropy_post_harmony']:.2f})",
    fontsize=10.5,
    fontweight="bold",
    y=0.975,
)
fig.savefig(out_dir() / "fig1cd.png", dpi=180)
write_metrics(m)
print(m)
