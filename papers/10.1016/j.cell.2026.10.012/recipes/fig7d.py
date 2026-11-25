# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "pyBigWig>=0.3.22", "matplotlib>=3.8"]
# ///
"""Figure 7D: CACNA1I locus (chr22:39,570,753-39,689,735, 118,983 bp) gene model, consensus cCREs,
and GPe MEIS2-SOX6 GABA human ATAC-seq track highlighting schizophrenia GWAS variant rs1883123
(chr22:39,600,877) directly on the tallest intronic open-chromatin peak."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyBigWig

from bg_epig import data_dir, draw_refseq_genes, out_dir, write_metrics

d = data_dir()
out = out_dir()

CHROM, START, END = "chr22", 39570753, 39689735
SNP_POS = 39600877
NBINS = 600
xs = np.linspace(START / 1e6, END / 1e6, NBINS)

bw = pyBigWig.open(str(d / "GPe_MEIS2-SOX6_GABA.bw"))
vals = np.nan_to_num(bw.stats(CHROM, START, END, nBins=NBINS, type="max"), nan=0.0).astype(float)
snp_max = float(np.nan_to_num(bw.stats(CHROM, SNP_POS - 250, SNP_POS + 250, type="max")[0], nan=0.0))
bw.close()

bed = pd.read_csv(
    d / "atac_human_consensus_peaks.bed", sep="\t", header=None, usecols=[0, 1, 2], names=["chr", "start", "end"]
)
loc_peaks = bed[(bed["chr"] == CHROM) & (bed["end"] >= START) & (bed["start"] <= END)].copy()
snp_hit = loc_peaks[(loc_peaks["start"] <= SNP_POS) & (loc_peaks["end"] >= SNP_POS)]

pd.DataFrame({"pos_mb": xs, "gpe_meis2_sox6_atac_max": vals}).to_csv(out / "fig7d_cacna1i_track.csv", index=False)

locus_max = float(vals.max())
on_tallest = abs(snp_max - locus_max) < 1e-4

fig = plt.figure(figsize=(9.5, 3.8), dpi=180)
gs = fig.add_gridspec(3, 1, height_ratios=[0.95, 0.35, 1.8], hspace=0.14)

ax_g = fig.add_subplot(gs[0, 0])
draw_refseq_genes(ax_g, CHROM, START, END, highlight_genes={"CACNA1I"})
ax_g.axvline(SNP_POS / 1e6, color="#d62728", ls="--", lw=1.1, zorder=5)
ax_g.text(SNP_POS / 1e6 + 0.0012, -0.55, "rs1883123 (chr22:39,600,877)", color="#d62728", fontsize=8, fontweight="bold")
ax_g.set_ylim(-0.95, 0.95)
ax_g.set_title("CACNA1I locus (chr22:39,570,753-39,689,735; 118,983 bp)", fontsize=10, loc="left")

ax_p = fig.add_subplot(gs[1, 0], sharex=ax_g)
for _, r in loc_peaks.iterrows():
    col = "#d62728" if (r["start"] <= SNP_POS <= r["end"]) else "#555555"
    ax_p.plot([r["start"] / 1e6, r["end"] / 1e6], [0.5, 0.5], color=col, lw=3.5, solid_capstyle="butt")
ax_p.set_ylim(0, 1)
ax_p.set_yticks([])
ax_p.set_ylabel("cCREs", fontsize=7.5, rotation=0, labelpad=24, va="center")
for sp in ("top", "right", "left", "bottom"):
    ax_p.spines[sp].set_visible(False)
ax_p.tick_params(axis="x", bottom=False, labelbottom=False)

ax_bw = fig.add_subplot(gs[2, 0], sharex=ax_g)
ax_bw.fill_between(xs, 0, vals, color="#d95f02", alpha=0.88, lw=0)
ax_bw.axvline(SNP_POS / 1e6, color="#d62728", ls="--", lw=1.1)
ax_bw.set_ylabel("GPe MEIS2-SOX6\nGABA ATAC", fontsize=8)
ax_bw.set_xlabel("chr22 position (Mb)", fontsize=8.5)
ax_bw.text(
    0.99, 0.85, f"Peak at rs1883123 = {snp_max:.2f} (locus max = {locus_max:.2f})",
    transform=ax_bw.transAxes, ha="right", va="top", fontsize=8, color="#333333",
)
ax_bw.spines["top"].set_visible(False)
ax_bw.spines["right"].set_visible(False)

fig.subplots_adjust(left=0.12, right=0.97, top=0.90, bottom=0.14)
fig.savefig(out / "fig7d.png", dpi=180)
plt.close(fig)

metrics = {
    "locus_max_atac": round(locus_max, 4),
    "rs1883123_500bp_max_atac": round(snp_max, 4),
    "n_consensus_ccres_in_locus": int(len(loc_peaks)),
    "rs1883123_on_tallest_locus_peak": bool(on_tallest),
    "rs1883123_overlaps_consensus_ccre": bool(len(snp_hit) > 0),
    "rs1883123_ccre_coord": (
        f"{snp_hit.iloc[0]['chr']}:{int(snp_hit.iloc[0]['start'])}-{int(snp_hit.iloc[0]['end'])}"
        if len(snp_hit) else ""
    ),
}
write_metrics(metrics)
print(metrics)
