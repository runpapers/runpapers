# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "pyBigWig>=0.3.22", "matplotlib>=3.8"]
# ///
"""Figure 6B (ATAC-seq tracks + gene model): Human snATAC-seq chromatin accessibility tracks at the
SMYD2 locus (chr1:214,150,000-214,400,000, hg38) across four SPN subtypes, showing selective open
chromatin in STR D2 SMYD2-HTR7 SPN (>= 2.3x peak and mean signal over classical D2 Striosome/Matrix).

Note: DNA methylation (mCG/mCH), histone marks (H3K27ac/H3K27me3), and Hi-C contact tracks shown in
the lower half of published Figure 6B originate from companion epigenomic dataset Ding et al. (2026)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyBigWig

from bg_epig import data_dir, draw_refseq_genes, out_dir, write_metrics

d = data_dir()
out = out_dir()

CHROM, START, END = "chr1", 214150000, 214400000
NBINS = 600
xs = np.linspace(START / 1e6, END / 1e6, NBINS)

TRACKS = [
    ("STR D2 SMYD2-HTR7 SPN", "STR_D2_SMYD2-HTR7_SPN.bw", "#9467bd"),
    ("STRd D2 Striosome SPN", "STRd_D2_Striosome_SPN.bw", "#d62728"),
    ("STRd D2 Matrix SPN", "STRd_D2_Matrix_SPN.bw", "#1f77b4"),
    ("STR D1D2 eSPN", "STR_D1D2_eSPN.bw", "#2ca02c"),
]

# Load consensus cCREs in locus
bed = pd.read_csv(
    d / "atac_human_consensus_peaks.bed", sep="\t", header=None, usecols=[0, 1, 2], names=["chr", "start", "end"]
)
loc_peaks = bed[(bed["chr"] == CHROM) & (bed["end"] >= START) & (bed["start"] <= END)]

stats_rows = []
signals = {}
for lbl, fn, _ in TRACKS:
    bw = pyBigWig.open(str(d / fn))
    vals = np.nan_to_num(bw.stats(CHROM, START, END, nBins=NBINS, type="max"), nan=0.0).astype(float)
    bw.close()
    signals[lbl] = vals
    stats_rows.append({
        "group": lbl,
        "max_atac": float(vals.max()),
        "mean_atac": float(vals.mean()),
        "p99_atac": float(np.percentile(vals, 99)),
    })

summary_df = pd.DataFrame(stats_rows)
summary_df.to_csv(out / "fig6b_smyd2_atac_summary.csv", index=False)

s_map = summary_df.set_index("group")
sm_max = float(s_map.loc["STR D2 SMYD2-HTR7 SPN", "max_atac"])
sm_mean = float(s_map.loc["STR D2 SMYD2-HTR7 SPN", "mean_atac"])
strio_max = float(s_map.loc["STRd D2 Striosome SPN", "max_atac"])
mat_max = float(s_map.loc["STRd D2 Matrix SPN", "max_atac"])
espn_max = float(s_map.loc["STR D1D2 eSPN", "max_atac"])
strio_mean = float(s_map.loc["STRd D2 Striosome SPN", "mean_atac"])
mat_mean = float(s_map.loc["STRd D2 Matrix SPN", "mean_atac"])
espn_mean = float(s_map.loc["STR D1D2 eSPN", "mean_atac"])

fig = plt.figure(figsize=(9.2, 5.8), dpi=180)
gs = fig.add_gridspec(6, 1, height_ratios=[1.1, 0.35, 1, 1, 1, 1], hspace=0.14)

ax_g = fig.add_subplot(gs[0, 0])
draw_refseq_genes(ax_g, CHROM, START, END, highlight_genes={"LINC02775", "SMYD2", "PTPN14"})
ax_g.set_title("SMYD2 locus (chr1:214,150-214,400 kb, hg38) — Human snATAC-seq tracks", fontsize=10, loc="left")

ax_p = fig.add_subplot(gs[1, 0], sharex=ax_g)
for _, r in loc_peaks.iterrows():
    ax_p.plot([r["start"] / 1e6, r["end"] / 1e6], [0.5, 0.5], color="#444444", lw=3.0, solid_capstyle="butt")
ax_p.set_ylim(0, 1)
ax_p.set_yticks([])
ax_p.set_ylabel("cCREs", fontsize=7.5, rotation=0, labelpad=24, va="center")
for sp in ("top", "right", "left", "bottom"):
    ax_p.spines[sp].set_visible(False)
ax_p.tick_params(axis="x", bottom=False, labelbottom=False)

ymax = sm_max * 1.08
for idx, (lbl, _, col) in enumerate(TRACKS):
    ax = fig.add_subplot(gs[2 + idx, 0], sharex=ax_g)
    vals = signals[lbl]
    # Soft highlight over SMYD2 gene body (chr1:214.28-214.33 Mb) matching Figure 6B
    ax.axvspan(214.280, 214.335, color="#f7e58b", alpha=0.28, zorder=0)
    ax.fill_between(xs, 0, vals, color=col, alpha=0.88, lw=0)
    ax.set_ylim(0, ymax)
    short_lbl = {
        "STR D2 SMYD2-HTR7 SPN": "STR D2\nSMYD2-HTR7",
        "STRd D2 Striosome SPN": "STRd D2\nStriosome",
        "STRd D2 Matrix SPN": "STRd D2\nMatrix",
        "STR D1D2 eSPN": "STR D1D2\neSPN",
    }.get(lbl, lbl)
    ax.set_ylabel(short_lbl, fontsize=7.8)
    ax.text(
        0.99, 0.78, f"max={vals.max():.2f}  mean={vals.mean():.2f}",
        transform=ax.transAxes, ha="right", va="top", fontsize=7.5, color="#333333",
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if idx < len(TRACKS) - 1:
        ax.tick_params(axis="x", labelbottom=False)
    else:
        ax.set_xlabel("chr1 position (Mb)  [Companion mCG/mCH/H3K27/Hi-C tracks hosted in Ding et al. 2026]", fontsize=8)

fig.subplots_adjust(left=0.14, right=0.97, top=0.93, bottom=0.10)
fig.savefig(out / "fig6b.png", dpi=180)
plt.close(fig)

metrics = {
    "n_consensus_ccres_in_locus": int(len(loc_peaks)),
    "smyd2_max_atac": round(sm_max, 4),
    "smyd2_mean_atac": round(sm_mean, 4),
    "d2_striosome_max_atac": round(strio_max, 4),
    "d2_matrix_max_atac": round(mat_max, 4),
    "espn_max_atac": round(espn_max, 4),
    "smyd2_peak_fold_vs_d2_striosome": round(sm_max / max(strio_max, 1e-6), 4),
    "smyd2_peak_fold_vs_d2_matrix": round(sm_max / max(mat_max, 1e-6), 4),
    "smyd2_peak_fold_vs_espn": round(sm_max / max(espn_max, 1e-6), 4),
    "smyd2_mean_fold_vs_d2_striosome": round(sm_mean / max(strio_mean, 1e-6), 4),
    "smyd2_mean_fold_vs_d2_matrix": round(sm_mean / max(mat_mean, 1e-6), 4),
    "smyd2_mean_fold_vs_espn": round(sm_mean / max(espn_mean, 1e-6), 4),
    "smyd2_highest_max_and_mean_atac": bool(
        sm_max > max(strio_max, mat_max, espn_max) and sm_mean > max(strio_mean, mat_mean, espn_mean)
    ),
}
write_metrics(metrics)
print(metrics)
