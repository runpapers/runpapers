# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8", "pyfaidx>=0.8"]
# ///
"""Figure 4D: Transcription factor (TF) motif cell-type specificity (mean Gini score across 60
human BG Groups) versus promoter enrichment (TSS +/- 1.5 kb from UCSC RefSeq) computed directly
from open human snATAC-seq cCREs (atac_human_Group_by_peaks.csv), hg38.fa.gz, and JASPAR2024
CORE vertebrate motifs (~879 motifs).

Verifies the core biological contrast of Figure 4D (main p.9): promoter-enriched housekeeping
motifs (HINFP, TCFL5) exhibit lower cell-type specificity (Gini) than cell-type-specific
neuronal POU/HOX homeodomain motifs (POU3F1). When optional Cell VoR Table S15 is present in
$RP_DATA_DIR, also cross-verifies 447-mammal Cactus mean evolutionary distance."""
import gzip
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_epig import (
    PUBLISHED_GROUP_ORDER,
    calc_gini_2d,
    canon_group,
    data_dir,
    one_hot_batch,
    open_hg38_fasta,
    out_dir,
    parse_jaspar_meme,
    rp_seed,
    write_metrics,
)

d = data_dir()
out = out_dir()
seed = rp_seed()
rng = np.random.default_rng(seed)

# 1. Load human Group-by-peaks matrix and compute per-cCRE Gini specificity across all 60 Groups
peaks = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks.columns = [canon_group(c) for c in peaks.columns]
cols60 = [g for g in PUBLISHED_GROUP_ORDER if g in peaks.columns]
B = (peaks[cols60].values > 0).astype(np.float32)
gini_all = calc_gini_2d(B)

idx_s = pd.Series(peaks.index.astype(str))
ex = idx_s.str.extract(r"^(chr[0-9XY]+):(\d+)-(\d+)$")
p_chr = ex[0].values
p_s = pd.to_numeric(ex[1], errors="coerce").fillna(-1).astype(np.int64).values
p_e = pd.to_numeric(ex[2], errors="coerce").fillna(-1).astype(np.int64).values
p_mid = (p_s + p_e) // 2

# 2. Annotate promoter cCREs (TSS +/- 1,500 bp from UCSC ncbiRefSeqCurated.txt.gz)
tss_by_chr: dict[str, list[int]] = defaultdict(list)
with gzip.open(d / "ncbiRefSeqCurated.txt.gz", "rt") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 6:
            continue
        ch = parts[2]
        tss = int(parts[4]) if parts[3] == "+" else int(parts[5])
        tss_by_chr[ch].append(tss)

is_prom = np.zeros(len(peaks), dtype=bool)
for ch, tss_list in tss_by_chr.items():
    mask = p_chr == ch
    if not mask.any():
        continue
    arr = np.sort(np.unique(np.array(tss_list, dtype=np.int64)))
    mids = p_mid[mask]
    idx = np.searchsorted(arr, mids)
    d_right = np.where(idx < len(arr), np.abs(arr[np.minimum(idx, len(arr) - 1)] - mids), 10**9)
    d_left = np.where(idx > 0, np.abs(mids - arr[np.maximum(idx - 1, 0)]), 10**9)
    is_prom[mask] = np.minimum(d_left, d_right) <= 1500

# 3. Deterministic stratified sample of 24,000 cCREs (8,000 promoter + 16,000 distal) for fast BLAS PWM scan
fasta = open_hg38_fasta()
valid_chrs = set(fasta.keys())
ok_mask = np.isin(p_chr, list(valid_chrs)) & (p_s >= 500)
prom_idx = np.where(ok_mask & is_prom)[0]
dist_idx = np.where(ok_mask & (~is_prom))[0]
sel_idx = np.concatenate([
    rng.choice(prom_idx, size=min(8000, len(prom_idx)), replace=False),
    rng.choice(dist_idx, size=min(16000, len(dist_idx)), replace=False),
])

WIN = 220
HALF = WIN // 2
seqs = []
keep_rows = []
for r_i in sel_idx:
    ch = p_chr[r_i]
    mid = int(p_mid[r_i])
    s0, e0 = mid - HALF, mid - HALF + WIN
    if s0 < 0 or e0 > len(fasta[ch]):
        continue
    sq = str(fasta[ch][s0:e0]).upper()
    if len(sq) == WIN and "N" not in sq:
        seqs.append(sq)
        keep_rows.append(r_i)

keep_rows = np.array(keep_rows, dtype=np.int64)
gini_s = gini_all[keep_rows]
prom_s = is_prom[keep_rows].astype(np.float64)
oh = one_hot_batch(seqs)  # (N, WIN, 4)

# 4. Parse ALL JASPAR2024 CORE vertebrate motifs (unique base names) and scan in width-batched BLAS matmuls
pwms_raw = parse_jaspar_meme(d / "JASPAR2024_CORE_vertebrates_non-redundant_pfms_meme.txt")
# Deduplicate keeping exact MEME TF names (excluding base aliases that duplicate another key)
motifs_by_w: dict[int, list[tuple[str, np.ndarray, float]]] = defaultdict(list)
for tf_nm, pwm in pwms_raw.items():
    w = int(pwm.shape[1])
    if 5 <= w <= 24:
        max_sc = float(pwm.max(axis=0).sum())
        if max_sc > 3.0:
            motifs_by_w[w].append((tf_nm, pwm, max_sc))

results = []
BATCH = 1500
N_seq = oh.shape[0]
for w, items in sorted(motifs_by_w.items()):
    M = len(items)
    # Build (4*w, 2*M) weight matrix for forward and reverse-complement PWMs
    W_mat = np.empty((w * 4, 2 * M), dtype=np.float32)
    thrs = np.empty(M, dtype=np.float32)
    for mi, (_, pwm, max_sc) in enumerate(items):
        # pwm is (4, w) -> transpose to (w, 4) -> flatten (4*w,)
        W_mat[:, mi] = pwm.T.reshape(-1)
        W_mat[:, M + mi] = pwm[::-1, ::-1].T.reshape(-1)
        thrs[mi] = 0.72 * max_sc

    hit_gini_sum = np.zeros(M, dtype=np.float64)
    hit_prom_sum = np.zeros(M, dtype=np.float64)
    hit_cnt = np.zeros(M, dtype=np.int64)

    n_pos = WIN - w + 1
    for b0 in range(0, N_seq, BATCH):
        b1 = min(b0 + BATCH, N_seq)
        B_oh = oh[b0:b1]  # (bs, WIN, 4)
        bs = b1 - b0
        # Strided view (bs, n_pos, w, 4) -> (bs * n_pos, 4 * w)
        st0, st1, st2 = B_oh.strides
        win_v = np.lib.stride_tricks.as_strided(
            B_oh, shape=(bs, n_pos, w, 4), strides=(st0, st1, st1, st2)
        ).reshape(bs * n_pos, w * 4)
        scores = win_v @ W_mat  # (bs * n_pos, 2*M)
        scores = scores.reshape(bs, n_pos, 2 * M)
        max_per_seq = np.maximum(scores[:, :, :M].max(axis=1), scores[:, :, M:].max(axis=1))  # (bs, M)
        hits = max_per_seq >= thrs[None, :]  # (bs, M)
        hit_cnt += hits.sum(axis=0)
        hit_gini_sum += (hits * gini_s[b0:b1, None]).sum(axis=0)
        hit_prom_sum += (hits * prom_s[b0:b1, None]).sum(axis=0)

    for mi, (tf_nm, _, _) in enumerate(items):
        cnt = int(hit_cnt[mi])
        if cnt >= 15:
            results.append({
                "motif_TF": tf_nm,
                "n_hit_peaks": cnt,
                "mean_gini_score": float(hit_gini_sum[mi] / cnt),
                "promoter_fraction": float(hit_prom_sum[mi] / cnt),
            })

res_df = pd.DataFrame(results).sort_values("mean_gini_score", ascending=False).reset_index(drop=True)
res_df.to_csv(out / "fig4d_tf_motifs_open.csv", index=False)

# Optional Table S15 cross-audit if supplied
t15_path = d / "TableS15_tf_motifs.csv"
t15_metrics = {}
if t15_path.exists():
    t15 = pd.read_csv(t15_path)
    for tf_k in ("POU3F1", "HINFP", "OTX2"):
        sub = t15[t15["motif_TF"] == tf_k]
        if len(sub):
            t15_metrics[f"{tf_k.lower()}_mean_evo_distance"] = round(float(sub.iloc[0]["mean_evo_distance"]), 4)

# 5. Plot Figure 4D (Open mode: Promoter enrichment vs Cell-type Gini specificity across JASPAR2024)
ANCHORS = ["POU3F1", "OTX2", "CTCF", "ZNF135", "TCFL5", "HINFP"]
rmap = res_df.set_index("motif_TF")

fig, ax = plt.subplots(figsize=(6.8, 5.4), dpi=180)
sc_p = ax.scatter(
    res_df["promoter_fraction"], res_df["mean_gini_score"],
    c=res_df["promoter_fraction"], cmap="viridis_r", s=14, alpha=0.72, edgecolors="none",
)
OFFSETS = {
    "POU3F1": (16, 10),
    "OTX2": (24, -4),
    "CTCF": (14, 6),
    "ZNF135": (-56, -18),
    "TCFL5": (-58, 12),
    "HINFP": (-58, -14),
}
for tf in ANCHORS:
    if tf not in rmap.index:
        continue
    r = rmap.loc[tf]
    xv, yv = float(r["promoter_fraction"]), float(r["mean_gini_score"])
    ax.scatter([xv], [yv], s=36, c="#d62728", edgecolors="black", lw=0.6, zorder=6)
    dx, dy = OFFSETS.get(tf, (8, 6))
    lbl = "POU/HOX (POU3F1)" if tf == "POU3F1" else tf
    ax.annotate(
        lbl, (xv, yv), xytext=(dx, dy), textcoords="offset points",
        fontsize=8.5, fontweight="bold",
        arrowprops=dict(arrowstyle="-", color="#333333", lw=0.75),
    )

cb = fig.colorbar(sc_p, ax=ax, shrink=0.7, pad=0.02)
cb.set_label("Promoter fraction (TSS +/- 1.5 kb)", fontsize=8)
ax.set_xlabel("Promoter enrichment (fraction of hit cCREs within 1.5 kb of RefSeq TSS)", fontsize=9)
ax.set_ylabel("Cell-type specificity (mean Gini score across 60 BG Groups)", fontsize=9)
ax.set_title(
    f"JASPAR2024 TF Motifs in Human BG cCREs (n = {len(res_df)} motifs; open data)\n"
    "[Note: 447-mammal Cactus evolutionary distance requires unbundled >1 TB HAL]",
    fontsize=9.2,
)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
fig.savefig(out / "fig4d.png", dpi=180)
plt.close(fig)

pou_g = float(rmap.loc["POU3F1", "mean_gini_score"]) if "POU3F1" in rmap.index else np.nan
hinfp_g = float(rmap.loc["HINFP", "mean_gini_score"]) if "HINFP" in rmap.index else np.nan
tcfl5_g = float(rmap.loc["TCFL5", "mean_gini_score"]) if "TCFL5" in rmap.index else np.nan
pou_p = float(rmap.loc["POU3F1", "promoter_fraction"]) if "POU3F1" in rmap.index else np.nan
hinfp_p = float(rmap.loc["HINFP", "promoter_fraction"]) if "HINFP" in rmap.index else np.nan

metrics = {
    "n_motifs_scored": int(len(res_df)),
    "n_ccres_sampled": int(len(keep_rows)),
    "pou3f1_mean_gini_score": round(pou_g, 4),
    "pou3f1_promoter_fraction": round(pou_p, 4),
    "hinfp_mean_gini_score": round(hinfp_g, 4),
    "hinfp_promoter_fraction": round(hinfp_p, 4),
    "tcfl5_mean_gini_score": round(tcfl5_g, 4),
    "promoter_motifs_lower_gini_than_pou_hox": bool((hinfp_g < pou_g) and (tcfl5_g < pou_g)),
    "hinfp_higher_promoter_fraction_than_pou3f1": bool(hinfp_p > pou_p),
    **t15_metrics,
}
write_metrics(metrics)
print(metrics)
