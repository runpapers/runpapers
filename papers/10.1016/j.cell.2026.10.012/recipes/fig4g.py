# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8"]
# ///
"""Figure 4G: Intersection of human basal ganglia cCREs with Human Ancestor Quickly Evolved Regions
(HAQERs, Mangan et al. 2022, n = 1,581 from haqer.hg38.bed).

Reproduces the exact 504 / 1,581 HAQER-cCRE overlap and plots the cell-type accessibility heatmap
across all 60 human BG Groups annotated with % cell-type coverage and Gini specificity. Runs on a
standard desktop CPU (< 1.5 GB RAM, < 30 seconds) using pure pandas/numpy/matplotlib."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_epig import (
    PUBLISHED_GROUP_ORDER,
    calc_gini_2d,
    canon_group,
    data_dir,
    load_group_metadata,
    out_dir,
    write_metrics,
)

d = data_dir()
out = out_dir()
_, group_to_class, _, class_colors = load_group_metadata()

# 1. Read all 1,581 hg38 HAQERs from haqer.hg38.bed (Mangan et al. 2022, 5-column TSV)
haqers = pd.read_csv(
    d / "haqer.hg38.bed", sep="\t", header=None, usecols=[0, 1, 2, 3],
    names=["chr", "start", "end", "HAQER_ID"],
)
haqers["start"] = haqers["start"].astype(np.int64)
haqers["end"] = haqers["end"].astype(np.int64)
n_haqers_total = int(len(haqers))

# 2. Load atac_human_Group_by_peaks.csv and parse coordinates
peaks = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks.columns = [canon_group(c) for c in peaks.columns]
ordered_cols = [g for g in PUBLISHED_GROUP_ORDER if g in peaks.columns]
peaks = peaks[ordered_cols]

idx_s = pd.Series(peaks.index.astype(str))
ex = idx_s.str.extract(r"^(chr[^:]+):(\d+)-(\d+)$")
p_chr = ex[0].values
p_s = pd.to_numeric(ex[1], errors="coerce").fillna(-1).astype(np.int64).values
p_e = pd.to_numeric(ex[2], errors="coerce").fillna(-1).astype(np.int64).values

# 3. Exact interval intersection (open/half-open overlap: p_s < h_e and p_e > h_s)
ov_records = []
ov_peak_rows = []
ov_haqer_ids = set()
for ch, sub_h in haqers.groupby("chr"):
    mask_c = p_chr == ch
    if not mask_c.any():
        continue
    row_idx = np.where(mask_c)[0]
    ps_c = p_s[row_idx]
    pe_c = p_e[row_idx]
    ord_c = np.argsort(ps_c)
    row_idx, ps_c, pe_c = row_idx[ord_c], ps_c[ord_c], pe_c[ord_c]
    max_len = int((pe_c - ps_c).max()) + 1
    for _, hr in sub_h.iterrows():
        hs, he, hid = int(hr["start"]), int(hr["end"]), str(hr["HAQER_ID"])
        hi = np.searchsorted(ps_c, he, side="left")
        lo = max(0, np.searchsorted(ps_c, hs - max_len, side="left"))
        hits = np.where((ps_c[lo:hi] < he) & (pe_c[lo:hi] > hs))[0] + lo
        if len(hits):
            ov_haqer_ids.add(hid)
            for h_i in hits:
                r_orig = int(row_idx[h_i])
                ov_peak_rows.append(r_orig)
                ov_records.append({
                    "HAQER_ID": hid,
                    "chr": ch,
                    "haqer_start": hs,
                    "haqer_end": he,
                    "peak_id": str(peaks.index[r_orig]),
                    "peak_start": int(ps_c[h_i]),
                    "peak_end": int(pe_c[h_i]),
                })

ov_df = pd.DataFrame(ov_records).drop_duplicates(subset=["peak_id"]).reset_index(drop=True)
n_haqers_overlapping = int(len(ov_haqer_ids))

# 4. Build unique overlapping cCRE x 60-Group binary accessibility matrix
mat_df = peaks.loc[ov_df["peak_id"].values].astype(np.int8)
mat_df.index = ov_df["peak_id"].values
cov_frac = mat_df.mean(axis=1).values
gini_vals = calc_gini_2d(mat_df.values.astype(np.float64))

ov_df["pct_coverage"] = cov_frac
ov_df["gini_specificity"] = gini_vals

# Optional Table S16 overlay if provided in $RP_DATA_DIR
t16_path = d / "TableS16_HAQER_ABC.csv"
n_conserved_s16 = None
hdeg_flags = np.zeros(len(ov_df), dtype=bool)
gene_labels: dict[int, str] = {}
if t16_path.exists():
    t16 = pd.read_csv(t16_path)
    n_conserved_s16 = int(t16["HAQER_ID"].nunique())
    hdeg_ids = set(t16.loc[t16["hDEG"] == True, "HAQER_ID"].astype(str))
    hdeg_flags = ov_df["HAQER_ID"].isin(hdeg_ids).values
    for gene_sym in ("CHL1", "DPP10"):
        g_ids = set(t16.loc[t16["gene_id"] == gene_sym, "HAQER_ID"].astype(str))
        hits = ov_df.index[ov_df["HAQER_ID"].isin(g_ids)].tolist()
        if hits:
            gene_labels[hits[0]] = gene_sym
ov_df["near_hDEG"] = hdeg_flags

# Sort rows like Figure 4G: highest coverage at bottom, lowest/most specific at top (or descending block diagonal)
# Match Fig 4G: descending by first active Group column (so CN LGE -> Subpallium -> Nonneuron cascades left-to-right),
# with broadly accessible cCREs at the bottom.
sort_key = pd.DataFrame({
    "broad": (cov_frac >= 0.5).astype(int),
    "first_col": np.argmax(mat_df.values > 0, axis=1),
    "cov": cov_frac,
})
order = sort_key.sort_values(["broad", "first_col", "cov"], ascending=[True, True, True]).index.values
mat_sorted = mat_df.values[order]
cov_sorted = cov_frac[order]
gini_sorted = gini_vals[order]
hdeg_sorted = hdeg_flags[order]
ov_df_sorted = ov_df.iloc[order].reset_index(drop=True)
ov_df_sorted.to_csv(out / "fig4g_haqer_ccre_overlaps.csv", index=False)

# 5. Plot Figure 4G heatmap + Class strip + % Coverage + Specificity (+ Near hDEG if Table S16 present)
n_strips = 3 if t16_path.exists() else 2
ratios = [14.0] + [0.65] * n_strips
fig = plt.figure(figsize=(8.4, 5.4), dpi=180)
gs = fig.add_gridspec(2, 1 + n_strips, height_ratios=[18, 1.0], width_ratios=ratios, wspace=0.06, hspace=0.04)

ax_hm = fig.add_subplot(gs[0, 0])
ax_hm.imshow(mat_sorted, aspect="auto", cmap="Greys", interpolation="nearest", vmin=0, vmax=1)
ax_hm.set_ylabel(f"Human cCREs overlapping HAQERs (n = {len(mat_sorted)})", fontsize=8.5)
ax_hm.set_yticks([])
ax_hm.set_xticks([])
ax_hm.set_title(f"HAQERs ({n_haqers_overlapping}/{n_haqers_total}) overlapping human BG cCREs", fontsize=10, loc="left")

# Bottom Class color bar
ax_cb = fig.add_subplot(gs[1, 0])
cls_hex = [class_colors.get(group_to_class.get(g, ""), "#999999") for g in ordered_cols]
import matplotlib.colors as mcolors
rgb_strip = np.array([mcolors.to_rgb(c) for c in cls_hex])[None, :, :]
ax_cb.imshow(rgb_strip, aspect="auto", interpolation="nearest")
ax_cb.set_yticks([])
# Label major Class spans
cls_seq = [group_to_class.get(g, "Other") for g in ordered_cols]
spans = []
s_idx = 0
for i in range(1, len(cls_seq) + 1):
    if i == len(cls_seq) or cls_seq[i] != cls_seq[s_idx]:
        spans.append((cls_seq[s_idx], s_idx, i - 1))
        s_idx = i
tick_pos = [(a + b) / 2.0 for _, a, b in spans if (b - a + 1) >= 2]
tick_lbl = [nm for nm, a, b in spans if (b - a + 1) >= 2]
ax_cb.set_xticks(tick_pos)
ax_cb.set_xticklabels(tick_lbl, rotation=35, ha="right", fontsize=7)

# Right annotation strips: % Coverage, Specificity (Gini), optional Near hDEG
ax_cov = fig.add_subplot(gs[0, 1])
ax_cov.imshow(cov_sorted[:, None], aspect="auto", cmap="coolwarm", vmin=0, vmax=1, interpolation="nearest")
ax_cov.set_xticks([0]); ax_cov.set_xticklabels(["% Coverage"], rotation=60, ha="right", fontsize=7.5)
ax_cov.set_yticks([])

ax_gin = fig.add_subplot(gs[0, 2])
ax_gin.imshow(gini_sorted[:, None], aspect="auto", cmap="coolwarm", vmin=0, vmax=1, interpolation="nearest")
ax_gin.set_xticks([0]); ax_gin.set_xticklabels(["Specificity"], rotation=60, ha="right", fontsize=7.5)
ax_gin.set_yticks([])

if t16_path.exists():
    ax_hd = fig.add_subplot(gs[0, 3])
    ax_hd.imshow(hdeg_sorted.astype(float)[:, None], aspect="auto", cmap="Greens", vmin=0, vmax=1, interpolation="nearest")
    ax_hd.set_xticks([0]); ax_hd.set_xticklabels(["Near hDEG"], rotation=60, ha="right", fontsize=7.5)
    ax_hd.set_yticks([])

fig.subplots_adjust(left=0.08, right=0.96, top=0.92, bottom=0.18)
fig.savefig(out / "fig4g.png", dpi=180)
plt.close(fig)

metrics = {
    "n_haqers_total": n_haqers_total,
    "n_haqers_overlapping_human_ccres": n_haqers_overlapping,
    "pct_haqers_overlapping_human_ccres": round(100.0 * n_haqers_overlapping / n_haqers_total, 2),
    "n_overlapping_human_ccres": int(len(mat_sorted)),
    "median_coverage_fraction": round(float(np.median(cov_sorted)), 4),
    "median_gini_specificity": round(float(np.median(gini_sorted)), 4),
}
if n_conserved_s16 is not None:
    metrics["n_conserved_haqers_table_s16"] = n_conserved_s16
write_metrics(metrics)
print(metrics)
