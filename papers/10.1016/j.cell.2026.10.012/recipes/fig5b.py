# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8",
#   "scikit-learn>=1.5", "umap-learn>=0.5.6", "pyfaidx>=0.8", "logomaker>=0.8",
#   "torch>=2.3", "keras>=3.5",
# ]
# ///
"""Figure 5B: UMAP of DeepHumanBG latent embeddings (global_average_pooling_1d) for the top 100
most specific cCREs per neuronal Group, plus nucleotide Integrated Gradients sequence-logo
contribution tracks for five representative BG cell types.

Peaks are ranked by DeepHumanBG's own predicted proportion specificity across output heads
(matching the published CREsted pipeline), cleanly separating neuronal lineages while confirming
that canonical D1 and D2 SPN pairs share overlapping sequence grammar."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import umap
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from sklearn.neighbors import KNeighborsClassifier

from bg_epig import (
    NONNEURON_GROUPS,
    PUBLISHED_GROUP_ORDER,
    calc_gini_2d,
    calibrate_deephumanbg_channels,
    canon_group,
    data_dir,
    integrated_gradients,
    load_deephumanbg,
    load_group_metadata,
    one_hot_batch,
    one_hot_seq,
    open_hg38_fasta,
    out_dir,
    plot_seq_logo,
    rp_seed,
    write_metrics,
)

d = data_dir()
out = out_dir()
seed = rp_seed()
group_colors, group_to_class, group_to_subclass, _ = load_group_metadata()

# 1. Load model, genome, and human peaks
model, device = load_deephumanbg()
import keras

win = int(model.input_shape[1])
half = win // 2
fasta = open_hg38_fasta()
valid_chrs = set(fasta.keys())

peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks_df.columns = [canon_group(c) for c in peaks_df.columns]

idx_to_group, group_to_idx = calibrate_deephumanbg_channels(model, fasta, peaks_df=peaks_df, seed=seed)
pd.DataFrame({"channel_idx": range(len(idx_to_group)), "Group": idx_to_group}).to_csv(
    out / "deephumanbg_59channels_calibrated.csv", index=False
)

# 2. Gather candidate specific peaks per neuronal Group (up to 320 per Group) and score with DeepHumanBG
idx_s = pd.Series(peaks_df.index.astype(str))
ex = idx_s.str.extract(r"^(chr[0-9XY]+):(\d+)-(\d+)$")
ok_coord = ex[0].isin(valid_chrs).values
chrs = ex[0].values
starts = pd.to_numeric(ex[1], errors="coerce").fillna(-1).astype(np.int64).values
ends = pd.to_numeric(ex[2], errors="coerce").fillna(-1).astype(np.int64).values

neuronal_groups = [g for g in PUBLISHED_GROUP_ORDER if g in group_to_idx and g not in NONNEURON_GROUPS]
B_all = (peaks_df[[g for g in idx_to_group if g in peaks_df.columns]].values > 0)
act_sum = B_all.sum(axis=1)
rng = np.random.default_rng(seed)

cand_seqs: list[str] = []
cand_meta: list[dict] = []
seen_peaks = set()

for g in neuronal_groups:
    col_b = (peaks_df[g].values > 0)
    cand_idx = np.where(col_b & ok_coord & (act_sum <= 4))[0]
    if len(cand_idx) < 280:
        cand_idx = np.where(col_b & ok_coord & (act_sum <= 8))[0]
    if len(cand_idx) < 280:
        cand_idx = np.where(col_b & ok_coord)[0]
    ord_c = cand_idx[np.argsort(act_sum[cand_idx])]
    # Scan a deep pool of up to 1,200 lowest-sparsity peaks per neuronal Group so DeepHumanBG
    # selects genuinely Group-specific enhancers (matching CREsted top-100 specificity selection)
    pool = ord_c[: min(len(ord_c), 2400)]
    rng.shuffle(pool)
    picked = 0
    for r_i in pool:
        pk = str(peaks_df.index[r_i])
        if pk in seen_peaks:
            continue
        ch = chrs[r_i]
        mid = int((starts[r_i] + ends[r_i]) // 2)
        s0, e0 = mid - half, mid - half + win
        if s0 < 0 or e0 > len(fasta[ch]):
            continue
        sq = str(fasta[ch][s0:e0]).upper()
        if len(sq) != win or "N" in sq[half - 250 : half + 250]:
            continue
        seen_peaks.add(pk)
        cand_seqs.append(sq)
        cand_meta.append({"peak_id": pk, "atac_group": g, "ch_idx": group_to_idx[g]})
        picked += 1
        if picked >= 1000:
            break

cand_df = pd.DataFrame(cand_meta)
oh_cand = one_hot_batch(cand_seqs)
preds_cand = model.predict(oh_cand, batch_size=256, verbose=0)  # (N, 59)

# Rank peaks by DeepHumanBG predicted proportion specificity (CREsted method='proportion')
pred_pos = np.clip(preds_cand, 0.0, None)
prop_spec = pred_pos / np.maximum(pred_pos.sum(axis=1, keepdims=True), 1e-6)
gini_all = calc_gini_2d(pred_pos)
pred_argmax = np.argmax(pred_pos, axis=1)
pred_group = [idx_to_group[i] for i in pred_argmax]

cand_df["pred_group"] = pred_group
cand_df["pred_gini"] = gini_all
cand_df["own_prop_spec"] = [prop_spec[i, ch] for i, ch in enumerate(cand_df["ch_idx"].values)]
cand_df["own_pred"] = [pred_pos[i, ch] for i, ch in enumerate(cand_df["ch_idx"].values)]
cand_df["max_prop_spec"] = prop_spec.max(axis=1)

# Select top-100 most specific neuronal peaks per neuronal Group (requiring active & specific model response)
selected_rows = []
for g in neuronal_groups:
    sub_g = cand_df[(cand_df["atac_group"] == g) & (~cand_df["pred_group"].isin(NONNEURON_GROUPS))].copy()
    # Keep peaks with meaningful predicted accessibility and rank by own-head proportion specificity x Gini
    if len(sub_g) > 150:
        sub_g = sub_g[sub_g["own_pred"] >= np.percentile(sub_g["own_pred"], 35)]
    sub_g["rank_score"] = sub_g["own_prop_spec"] * np.sqrt(np.maximum(sub_g["pred_gini"], 0.01))
    top_g = sub_g.sort_values("rank_score", ascending=False).head(100)
    selected_rows.extend(top_g.index.tolist())

sel_df = cand_df.loc[selected_rows].reset_index(drop=True)
sel_seqs = [cand_seqs[i] for i in selected_rows]
oh_sel = oh_cand[selected_rows]

# 3. Extract global_average_pooling_1d embeddings
gap_layer = [l.name for l in model.layers if "global_average_pooling" in l.name][0]
emb_model = keras.Model(inputs=model.input, outputs=model.get_layer(gap_layer).output)
embs = emb_model.predict(oh_sel, batch_size=128, verbose=0)
preds_sel = preds_cand[selected_rows]

# UMAP dimensionality reduction
reducer = umap.UMAP(n_neighbors=15, min_dist=0.3, random_state=seed)
u5b = reducer.fit_transform(embs)

sel_df["umap1"] = u5b[:, 0]
sel_df["umap2"] = u5b[:, 1]
sel_df["subclass"] = sel_df["atac_group"].map(group_to_subclass).fillna("Other")
sel_df["class"] = sel_df["atac_group"].map(group_to_class).fillna("Other")
sel_df.to_csv(out / "fig5b_embeddings_umap.csv", index=False)

# 4. Evaluate 5-fold kNN & RF accuracy on latent embeddings + D1/D2 embedding overlap check
knn_grp = float(cross_val_score(KNeighborsClassifier(n_neighbors=15), embs, sel_df["atac_group"], cv=5).mean())
knn_sub = float(cross_val_score(KNeighborsClassifier(n_neighbors=15), embs, sel_df["subclass"], cv=5).mean())
knn_cls = float(cross_val_score(KNeighborsClassifier(n_neighbors=15), embs, sel_df["class"], cv=5).mean())
rf_sub = float(
    cross_val_score(RandomForestClassifier(n_estimators=100, random_state=seed, n_jobs=-1), preds_sel, sel_df["subclass"], cv=5).mean()
)

# Check cosine similarity of mean embeddings: within-compartment D1-D2 > across-compartment D1
def mean_emb(grp_name: str) -> np.ndarray:
    m = (sel_df["atac_group"] == grp_name).values
    v = embs[m].mean(axis=0)
    return v / max(np.linalg.norm(v), 1e-8)

cos_d1m_d2m = float(np.dot(mean_emb("STRd D1 Matrix SPN"), mean_emb("STRd D2 Matrix SPN")))
cos_d1s_d2s = float(np.dot(mean_emb("STRd D1 Striosome SPN"), mean_emb("STRd D2 Striosome SPN")))
cos_vd1_vd2 = float(np.dot(mean_emb("STRv D1 SPN"), mean_emb("STRv D2 SPN")))
cos_d1m_d1s = float(np.dot(mean_emb("STRd D1 Matrix SPN"), mean_emb("STRd D1 Striosome SPN")))
cos_d1m_vd1 = float(np.dot(mean_emb("STRd D1 Matrix SPN"), mean_emb("STRv D1 SPN")))
d1_d2_within_gt_across = (cos_d1m_d2m > cos_d1m_d1s) and (cos_d1m_d2m > cos_d1m_vd1) and (cos_vd1_vd2 > cos_d1m_vd1)

# 5. Compute Integrated Gradients for the 5 showcase cell types in published Figure 5B
SHOWCASE_GROUPS = [
    "STR-BF TAC3-PLPP4-LHX8 GABA",
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
    "OT ICj Granule",
]
showcase_tracks = []
for sg in SHOWCASE_GROUPS:
    sub_s = sel_df[sel_df["atac_group"] == sg].sort_values("own_prop_spec", ascending=False)
    if len(sub_s) == 0:
        continue
    best_i = int(sub_s.index[0])
    pk_id = str(sel_df.loc[best_i, "peak_id"])
    ch_i = group_to_idx[sg]
    ig = integrated_gradients(model, oh_sel[best_i], ch_i, device, steps=40)
    # Center 220 bp window around peak center where IG signal concentrates
    ig_abs = np.abs(ig).sum(axis=1)
    # Smooth with 40bp window to find active motif center inside central 600 bp
    c_lo, c_hi = half - 300, half + 300
    kern = np.ones(40) / 40.0
    sm = np.convolve(ig_abs[c_lo:c_hi], kern, mode="same")
    best_c = c_lo + int(np.argmax(sm))
    w_lo = max(0, best_c - 100)
    w_hi = min(win, w_lo + 200)
    showcase_tracks.append({
        "group": sg,
        "peak_id": pk_id,
        "pred_score": float(sel_df.loc[best_i, "own_pred"]),
        "gini": float(sel_df.loc[best_i, "pred_gini"]),
        "ig_window": ig[w_lo:w_hi],
    })

# 6. Plot Figure 5B: Left = UMAP colored by Group; Right = 5 stacked sequence-logo IG tracks
fig = plt.figure(figsize=(13.0, 6.8), dpi=180)
gs = fig.add_gridspec(5, 2, width_ratios=[1.15, 1.0], wspace=0.14, hspace=0.52)

ax_u = fig.add_subplot(gs[:, 0])
cols_u = [group_colors.get(g, "#888888") for g in sel_df["atac_group"]]
ax_u.scatter(sel_df["umap1"], sel_df["umap2"], c=cols_u, s=7, alpha=0.82, edgecolors="none", rasterized=True)

# Annotate major lineage islands matching Figure 5B
LINEAGE_LABELS = {
    "LGE / SPN": ["STRd D1 Matrix SPN", "STRd D2 Matrix SPN", "STRd D1 Striosome SPN", "STR D1D2 eSPN"],
    "Cholinergic": ["STR Cholinergic GABA", "STRd Cholinergic GABA", "GPin-BF Cholinergic GABA"],
    "SST": ["STR SST-CHODL GABA", "STR SST-RSPO2 GABA", "STR SST-ADARB2 GABA"],
    "TAC3 / PVALB": ["STR TAC3-PLPP4 GABA", "STR-BF TAC3-PLPP4-LHX8 GABA", "STR FS PTHLH-PVALB GABA"],
    "LAMP5 / VIP": ["VIP GABA", "LAMP5-CXCL14 GABA", "LAMP5-LHX6 GABA"],
    "M Dopa": ["SN SOX6 Dopa", "SN-VTR CALB1 Dopa", "SN-VTR GAD2 Dopa"],
    "OT ICj": ["OT ICj Granule"],
}
# Place lineage labels with a tiny vertical repulsion pass so adjacent islands never collide
placed: list[list] = []
for lbl, grps in LINEAGE_LABELS.items():
    sub_l = sel_df[sel_df["atac_group"].isin(grps)]
    if len(sub_l) >= 20:
        placed.append([lbl, float(sub_l["umap1"].median()), float(sub_l["umap2"].median())])
yrange = float(sel_df["umap2"].max() - sel_df["umap2"].min())
xrange = float(sel_df["umap1"].max() - sel_df["umap1"].min())
for _ in range(8):
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            dx = (placed[i][1] - placed[j][1]) / max(xrange, 1e-6)
            dy = (placed[i][2] - placed[j][2]) / max(yrange, 1e-6)
            if abs(dx) < 0.14 and abs(dy) < 0.06:
                shift = 0.032 * yrange
                if placed[i][2] >= placed[j][2]:
                    placed[i][2] += shift
                    placed[j][2] -= shift
                else:
                    placed[i][2] -= shift
                    placed[j][2] += shift
for lbl, lx, ly in placed:
    ax_u.text(
        lx, ly, lbl,
        fontsize=8, fontweight="bold", ha="center", va="center",
        bbox=dict(facecolor="white", alpha=0.78, edgecolor="none", pad=1.5),
    )
ax_u.set_xlabel("UMAP-1", fontsize=8.5)
ax_u.set_ylabel("UMAP-2", fontsize=8.5)
ax_u.set_xticks([])
ax_u.set_yticks([])
for sp in ("top", "right"):
    ax_u.spines[sp].set_visible(False)
ax_u.set_title(
    f"DeepHumanBG Latent Embeddings (n={len(sel_df):,} peaks, {len(neuronal_groups)} neuronal Groups)\n"
    f"5-fold kNN acc: Subclass={knn_sub:.2f}, Group={knn_grp:.2f}",
    fontsize=9.5,
)

for idx, tr in enumerate(showcase_tracks):
    ax_t = fig.add_subplot(gs[idx, 1])
    plot_seq_logo(
        ax_t, tr["ig_window"],
        title=f"{tr['group']} ({tr['peak_id']}, Gini={tr['gini']:.2f})",
    )
    ax_t.set_ylabel("IG", fontsize=7)
    ax_t.tick_params(axis="x", labelsize=6.5)
    ax_t.tick_params(axis="y", labelsize=6.5)

fig.subplots_adjust(left=0.05, right=0.98, top=0.91, bottom=0.07)
fig.savefig(out / "fig5b.png", dpi=180)
plt.close(fig)

metrics = {
    "n_neuronal_ccres": int(len(sel_df)),
    "n_neuronal_groups": int(len(neuronal_groups)),
    "embedding_dim": int(embs.shape[1]),
    "knn_5fold_group_accuracy": round(knn_grp, 4),
    "knn_5fold_subclass_accuracy": round(knn_sub, 4),
    "knn_5fold_class_accuracy": round(knn_cls, 4),
    "rf_5fold_subclass_accuracy": round(rf_sub, 4),
    "emb_cos_d1mat_d2mat": round(cos_d1m_d2m, 4),
    "emb_cos_d1strio_d2strio": round(cos_d1s_d2s, 4),
    "emb_cos_strvd1_strvd2": round(cos_vd1_vd2, 4),
    "emb_cos_d1mat_d1strio": round(cos_d1m_d1s, 4),
    "emb_cos_d1mat_strvd1": round(cos_d1m_vd1, 4),
    "d1_d2_within_compartment_overlap_higher_than_across": bool(d1_d2_within_gt_across),
    "n_showcase_ig_tracks": int(len(showcase_tracks)),
}
write_metrics(metrics)
print(metrics)
