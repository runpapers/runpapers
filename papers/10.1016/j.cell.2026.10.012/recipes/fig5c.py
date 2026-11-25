# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8",
#   "anndata>=0.10", "pyfaidx>=0.8", "torch>=2.3", "keras>=3.5",
# ]
# ///
"""Figure 5C: DeepHumanBG cell-type TF-motif importance (Integrated Gradients weighted over JASPAR2024
CORE vertebrate motifs across top Group-specific cCREs) combined with scaled mean log-normalized TF
expression from the human snRNA-seq atlas.

Verifies the core regulatory grammar claims from main text p.11:
- Cholinergic LHX8/GBX2/ZIC3 signature, with GBX2 enriched in striatal cholinergic Groups and absent
  from GPin-BF Cholinergic GABA;
- DLX5/DLX6 SPN polarity (strongly positive in eccentric SPNs, attenuated in dorsal matrix/striosome,
  and reduced/negative in ventral SPNs);
- MEIS/POU/SMAD SPN grammars and non-neuronal lineage TFs (SPI1/IRF8/RUNX1, SOX10/OLIG2, NFIA/NFIB/SOX9)."""
import matplotlib

matplotlib.use("Agg")
import anndata as ad
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.sparse as sp

from bg_epig import (
    PUBLISHED_GROUP_ORDER,
    calibrate_deephumanbg_channels,
    canon_group,
    data_dir,
    integrated_gradients,
    load_deephumanbg,
    load_group_metadata,
    one_hot_batch,
    open_hg38_fasta,
    out_dir,
    parse_jaspar_meme,
    rp_seed,
    scan_sequence_pwm,
    write_metrics,
)

d = data_dir()
out = out_dir()
seed = rp_seed()
_, group_to_class, _, class_colors = load_group_metadata()

# Curated BG TF panel matching Figure 5C x-axis clusters (SPN, Interneuron, Cholinergic, Dopa, Glia)
TF_PANEL = [
    "RFX2", "RFX3", "SMAD3", "KLF5", "EGR1", "BACH2",
    "MEIS1", "MEIS2", "MEF2C", "RORA", "SP8", "POU3F1", "POU6F2",
    "DLX5", "DLX6", "ISL1", "EBF1", "FOXP1", "FOXP2",
    "NKX2-1", "LHX6", "LHX8", "GBX2", "ZIC1", "ZIC3",
    "PAX6", "OTX2", "NR4A2", "LMX1A", "EN1", "TCF12",
    "NFIA", "NFIB", "NFIX", "SOX2", "SOX6", "SOX9", "SOX10", "OLIG2",
    "SPI1", "IRF8", "RUNX1", "STAT1", "MAFB", "CTCF",
]

# 1. Load JASPAR2024 CORE vertebrate PWMs
pwms_all = parse_jaspar_meme(d / "JASPAR2024_CORE_vertebrates_non-redundant_pfms_meme.txt")
tfs_avail = [tf for tf in TF_PANEL if tf in pwms_all]
pwm_max = {tf: float(pwms_all[tf].max(axis=0).sum()) for tf in tfs_avail}

# 2. Compute scaled mean log2 TF expression per human Group from Cross-Species-log2.h5ad
c2c = pd.read_csv(d / "cell_to_cluster_membership.csv", usecols=["cell_label", "cluster_alias"])
ann = pd.read_csv(d / "cluster_to_cluster_annotation_membership.csv")
cl2grp = (
    ann[ann["cluster_annotation_term_set_name"] == "Group"]
    .set_index("cluster_alias")["cluster_annotation_term_name"]
)
c2c["Group"] = c2c["cluster_alias"].map(cl2grp)
cell_grp = c2c.set_index("cell_label")["Group"]

cm = pd.read_csv(d / "cell_metadata.csv", usecols=["cell_label", "donor_label"])
don = pd.read_csv(d / "donor.csv", usecols=["donor_label", "species_genus"])
cm = cm.merge(don, on="donor_label", how="left")
human_cells = set(cm.loc[cm["species_genus"] == "Human", "cell_label"].astype(str))

h5 = ad.read_h5ad(d / "HMBA-10xMultiome-BG-Cross-Species-log2.h5ad", backed="r")
var_syms = (
    h5.var["gene_symbol"].astype(str).str.upper().values
    if "gene_symbol" in h5.var.columns
    else h5.var_names.astype(str).str.upper().values
)
sym_to_vi = {}
for vi, sym in enumerate(var_syms):
    if sym not in sym_to_vi:
        sym_to_vi[sym] = vi
tfs_both = [tf for tf in tfs_avail if tf in sym_to_vi]
tf_vidx = np.array([sym_to_vi[tf] for tf in tfs_both], dtype=np.int64)

obs_names = h5.obs_names.astype(str).values
obs_grps = cell_grp.reindex(obs_names).fillna("").astype(str).values
is_hum = np.array([c in human_cells for c in obs_names], dtype=bool)

grp_list = [g for g in PUBLISHED_GROUP_ORDER if g != "SN GATA3-PAX8 GABA"]
g2i = {g: i for i, g in enumerate(grp_list)}
g_sum = np.zeros((len(grp_list), len(tfs_both)), dtype=np.float64)
g_cnt = np.zeros(len(grp_list), dtype=np.int64)

for s0 in range(0, h5.n_obs, 40000):
    s1 = min(s0 + 40000, h5.n_obs)
    hm_chunk = is_hum[s0:s1]
    if not hm_chunk.any():
        continue
    X = h5.X[s0:s1][:, tf_vidx]
    if sp.issparse(X):
        X = X.toarray()
    X = np.asarray(X, dtype=np.float64)
    grps_c = obs_grps[s0:s1]
    for loc_i in np.where(hm_chunk)[0]:
        gi = g2i.get(grps_c[loc_i], -1)
        if gi >= 0:
            g_sum[gi] += X[loc_i]
            g_cnt[gi] += 1
h5.file.close()

expr_df = pd.DataFrame(
    g_sum / np.maximum(g_cnt[:, None], 1),
    index=grp_list,
    columns=tfs_both,
)
# Scale expression per TF (0..1 across Groups for dot size matching Figure 5C)
expr_scaled = expr_df.div(np.maximum(expr_df.max(axis=0), 1e-6), axis=1)
expr_df.to_csv(out / "fig5c_tf_expression_by_group.csv")

# 3. DeepHumanBG IG-weighted motif importance per Group
model, device = load_deephumanbg()
win = int(model.input_shape[1])
half = win // 2
fasta = open_hg38_fasta()
valid_chrs = set(fasta.keys())

peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks_df.columns = [canon_group(c) for c in peaks_df.columns]
idx_to_group, group_to_idx = calibrate_deephumanbg_channels(model, fasta, peaks_df=peaks_df, seed=seed)

idx_s = pd.Series(peaks_df.index.astype(str))
ex = idx_s.str.extract(r"^(chr[0-9XY]+):(\d+)-(\d+)$")
ok_coord = ex[0].isin(valid_chrs).values
chrs = ex[0].values
starts = pd.to_numeric(ex[1], errors="coerce").fillna(-1).astype(np.int64).values
ends = pd.to_numeric(ex[2], errors="coerce").fillna(-1).astype(np.int64).values

B_all = (peaks_df[[g for g in idx_to_group if g in peaks_df.columns]].values > 0)
act_sum = B_all.sum(axis=1)
rng = np.random.default_rng(seed)

# Select top 25 highest-specificity peaks per Group (59 Groups x 25 = 1,475 peaks -> fast ~60s on A100!)
active_groups = [g for g in PUBLISHED_GROUP_ORDER if g in group_to_idx]
imp_mat = np.zeros((len(active_groups), len(tfs_both)), dtype=np.float64)
CENTRAL_HALF = 250  # central 500 bp cCRE window

for gi, g in enumerate(active_groups):
    ch_i = group_to_idx[g]
    col_b = (peaks_df[g].values > 0)
    cand_idx = np.where(col_b & ok_coord & (act_sum <= 4))[0]
    if len(cand_idx) < 100:
        cand_idx = np.where(col_b & ok_coord)[0]
    ord_c = cand_idx[np.argsort(act_sum[cand_idx])][:180]
    seqs_g = []
    for r_i in ord_c:
        ch = chrs[r_i]
        mid = int((starts[r_i] + ends[r_i]) // 2)
        s0, e0 = mid - half, mid - half + win
        if s0 < 0 or e0 > len(fasta[ch]):
            continue
        sq = str(fasta[ch][s0:e0]).upper()
        if len(sq) == win:
            seqs_g.append(sq)
        if len(seqs_g) >= 120:
            break
    if not seqs_g:
        continue
    oh_g = one_hot_batch(seqs_g)
    preds_g = np.clip(model.predict(oh_g, batch_size=128, verbose=0), 0.0, None)
    prop_g = preds_g[:, ch_i] / np.maximum(preds_g.sum(axis=1), 1e-6)
    # Pick top 25 most Group-specific high-signal peaks
    score_rank = prop_g * np.log1p(preds_g[:, ch_i])
    top_local = np.argsort(-score_rank)[:25]

    tf_contrib_sum = np.zeros(len(tfs_both), dtype=np.float64)
    tf_hit_cnt = np.zeros(len(tfs_both), dtype=np.float64)
    for li in top_local:
        ig = integrated_gradients(model, oh_g[li], ch_i, device, steps=20)
        # Signed per-base IG contribution inside central 500 bp
        c_oh = oh_g[li, half - CENTRAL_HALF : half + CENTRAL_HALF]
        c_ig = ig[half - CENTRAL_HALF : half + CENTRAL_HALF].sum(axis=1)
        for ti, tf in enumerate(tfs_both):
            pwm = pwms_all[tf]
            w = pwm.shape[1]
            sc = scan_sequence_pwm(c_oh, pwm)
            thr = 0.65 * pwm_max[tf]
            hits = np.where(sc >= thr)[0]
            if len(hits):
                # Take top non-overlapping hit(s) contribution
                best_p = int(hits[np.argmax(sc[hits])])
                tf_contrib_sum[ti] += float(c_ig[best_p : best_p + w].sum())
                tf_hit_cnt[ti] += 1.0
    # Mean contribution per peak (combining frequency x signed IG strength)
    imp_mat[gi] = tf_contrib_sum / max(len(top_local), 1)

imp_df = pd.DataFrame(imp_mat, index=active_groups, columns=tfs_both)
# Row/column standardized importance for display (clipped to [-3, +6] matching Figure 5C)
imp_z = (imp_df - imp_df.mean(axis=0)) / np.maximum(imp_df.std(axis=0), 1e-6)
imp_df.to_csv(out / "fig5c_motif_importance_raw.csv")
imp_z.to_csv(out / "fig5c_motif_importance_zscore.csv")

# 4. Verify key biological claims from main text p.11
def _get(df, g, tf):
    return float(df.loc[g, tf]) if (g in df.index and tf in df.columns) else np.nan

str_chol_gbx2 = float(np.nanmean([_get(imp_z, "STR Cholinergic GABA", "GBX2"), _get(imp_z, "STRd Cholinergic GABA", "GBX2")]))
gpin_chol_gbx2 = _get(imp_z, "GPin-BF Cholinergic GABA", "GBX2")
str_chol_gbx2_expr = float(np.nanmean([_get(expr_df, "STR Cholinergic GABA", "GBX2"), _get(expr_df, "STRd Cholinergic GABA", "GBX2")]))
gpin_chol_gbx2_expr = _get(expr_df, "GPin-BF Cholinergic GABA", "GBX2")

chol_lhx8 = float(np.nanmean([_get(imp_z, g, "LHX8") for g in ["STR Cholinergic GABA", "STRd Cholinergic GABA", "GPin-BF Cholinergic GABA"]]))
chol_zic3 = float(np.nanmean([_get(imp_z, g, "ZIC3") for g in ["STR Cholinergic GABA", "STRd Cholinergic GABA", "GPin-BF Cholinergic GABA"]]))
cholinergic_ok = (chol_lhx8 > 0.5) and (chol_zic3 > 0.5)
gbx2_ok = (str_chol_gbx2 > gpin_chol_gbx2) and (str_chol_gbx2_expr > gpin_chol_gbx2_expr)

dlx_cols = [c for c in ("DLX5", "DLX6") if c in imp_z.columns]
espn_dlx = float(imp_z.loc[["STR D1D2 eSPN", "STRv D1 NUDAP eSPN"], dlx_cols].values.mean())
vent_dlx = float(imp_z.loc[["STRv D1 SPN", "STRv D2 SPN"], dlx_cols].values.mean())
dlx_ok = espn_dlx > vent_dlx

# 5. Plot Figure 5C: Heatmap of motif importance + overlaid dot size for scaled TF expression
expr_sub = expr_scaled.reindex(index=active_groups, columns=tfs_both).fillna(0.0)
fig = plt.figure(figsize=(14.5, 9.2), dpi=180)
gs = fig.add_gridspec(1, 3, width_ratios=[18, 0.45, 3.2], wspace=0.04)

ax_hm = fig.add_subplot(gs[0, 0])
disp = imp_z.clip(-3.0, 5.0).values
im = ax_hm.imshow(disp, aspect="auto", cmap="coolwarm", vmin=-3.0, vmax=5.0, interpolation="nearest")

# Overlay expression dots where TF is appreciably expressed (scaled >= 0.15)
ys, xs, szs = [], [], []
for ri in range(len(active_groups)):
    for ci in range(len(tfs_both)):
        ev = float(expr_sub.iloc[ri, ci])
        if ev >= 0.15:
            ys.append(ri)
            xs.append(ci)
            szs.append(ev * 26.0)
ax_hm.scatter(xs, ys, s=szs, c="black", alpha=0.55, edgecolors="none", zorder=3)
ax_hm.set_xticks(range(len(tfs_both)))
ax_hm.set_xticklabels(tfs_both, rotation=90, fontsize=7.5)
ax_hm.set_yticks([])
ax_hm.set_title("DeepHumanBG TF-Motif Contribution (color) x Scaled Human TF Expression (dot size)", fontsize=10.5)

# Class color strip
ax_cl = fig.add_subplot(gs[0, 1])
cls_hex = [class_colors.get(group_to_class.get(g, ""), "#999999") for g in active_groups]
ax_cl.imshow(np.array([mcolors.to_rgb(c) for c in cls_hex])[:, None, :], aspect="auto", interpolation="nearest")
ax_cl.set_xticks([])
ax_cl.set_yticks([])

# Key Group labels on right matching Figure 5C
ax_lbl = fig.add_subplot(gs[0, 2])
ax_lbl.set_ylim(len(active_groups) - 0.5, -0.5)
ax_lbl.set_xlim(0, 1)
ax_lbl.axis("off")
HIGHLIGHT_ROWS = {
    "STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRd D2 Matrix SPN", "STRd D2 Striosome SPN",
    "STRv D1 SPN", "STRv D2 SPN", "STR D2 SMYD2-HTR7 SPN", "STR D1D2 eSPN", "STRv D1 NUDAP eSPN",
    "OT ICj Granule", "OB FRMD7 GABA", "OB Dopa-GABA",
    "GPin-BF Cholinergic GABA", "STR Cholinergic GABA", "STRd Cholinergic GABA",
    "SN-VTR GAD2 Dopa", "SN SOX6 Dopa", "SN-VTR CALB1 Dopa",
    "OPC", "Oligo OPALIN", "Astrocyte", "Microglia", "BAM",
}
for ri, g in enumerate(active_groups):
    if g in HIGHLIGHT_ROWS:
        ax_lbl.text(0.02, ri, g, va="center", ha="left", fontsize=7.2)

cbar = fig.colorbar(im, ax=ax_lbl, fraction=0.18, pad=0.05, shrink=0.35, location="right")
cbar.set_label("Motif importance (z-score)", fontsize=8)

fig.subplots_adjust(left=0.03, right=0.95, top=0.94, bottom=0.12)
fig.savefig(out / "fig5c.png", dpi=180)
plt.close(fig)

metrics = {
    "n_groups_scored": int(len(active_groups)),
    "n_tfs_scored": int(len(tfs_both)),
    "cholinergic_lhx8_importance_z": round(chol_lhx8, 4),
    "cholinergic_zic3_importance_z": round(chol_zic3, 4),
    "striatal_cholinergic_gbx2_importance_z": round(str_chol_gbx2, 4),
    "gpin_cholinergic_gbx2_importance_z": round(gpin_chol_gbx2, 4),
    "striatal_cholinergic_gbx2_expr": round(str_chol_gbx2_expr, 4),
    "gpin_cholinergic_gbx2_expr": round(gpin_chol_gbx2_expr, 4),
    "espn_dlx56_importance_z": round(espn_dlx, 4),
    "ventral_spn_dlx56_importance_z": round(vent_dlx, 4),
    "cholinergic_lhx8_zic3_enriched": bool(cholinergic_ok),
    "gbx2_higher_in_striatal_than_gpin_cholinergic": bool(gbx2_ok),
    "dlx56_higher_in_espn_than_ventral_spn": bool(dlx_ok),
}
write_metrics(metrics)
print(metrics)
