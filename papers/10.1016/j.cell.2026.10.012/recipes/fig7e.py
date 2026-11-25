# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8",
#   "pyfaidx>=0.8", "logomaker>=0.8", "torch>=2.3", "keras>=3.5",
# ]
# ///
"""Figure 7E: DeepHumanBG nucleotide-resolution Integrated Gradients sequence logos for
schizophrenia GWAS variant rs1883123 (chr22:39,600,877 C>T) in GPe MEIS2-SOX6 GABA neurons.

Demonstrates that mutating Reference C to Alternate T disrupts the ATGCTAAT (TCF12-annotated)
motif and markedly reduces both predicted chromatin accessibility and local IG sequence
contribution in GPe MEIS2-SOX6 GABA."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_epig import (
    calibrate_deephumanbg_channels,
    canon_group,
    data_dir,
    integrated_gradients,
    load_deephumanbg,
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

CHROM, SNP_POS = "chr22", 39600877
TARGET_GROUP = "GPe MEIS2-SOX6 GABA"

model, device = load_deephumanbg()
win = int(model.input_shape[1])
half = win // 2
fasta = open_hg38_fasta()

peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks_df.columns = [canon_group(c) for c in peaks_df.columns]
_, group_to_idx = calibrate_deephumanbg_channels(model, fasta, peaks_df=peaks_df, seed=seed)
target_idx = group_to_idx[TARGET_GROUP]

bed = pd.read_csv(
    d / "atac_human_consensus_peaks.bed", sep="\t", header=None, usecols=[0, 1, 2], names=["chr", "start", "end"]
)
hit = bed[(bed["chr"] == CHROM) & (bed["start"] <= SNP_POS) & (bed["end"] >= SNP_POS)]
center = int((hit.iloc[0]["start"] + hit.iloc[0]["end"]) // 2) if len(hit) else SNP_POS
w_start = center - half
seq_ref = str(fasta[CHROM][w_start : w_start + win]).upper()
snp_rel = (SNP_POS - 1) - w_start  # 0-based offset inside window
ref_base = seq_ref[snp_rel]
alt_base = "T" if ref_base == "C" else "C"
seq_alt = seq_ref[:snp_rel] + alt_base + seq_ref[snp_rel + 1 :]
flank_15 = seq_ref[snp_rel - 7 : snp_rel + 8]

oh_ref = one_hot_seq(seq_ref)
oh_alt = one_hot_seq(seq_alt)
pred_ref = float(np.squeeze(model.predict(oh_ref[None, :, :], verbose=0))[target_idx])
pred_alt = float(np.squeeze(model.predict(oh_alt[None, :, :], verbose=0))[target_idx])

ig_ref = integrated_gradients(model, oh_ref, target_idx, device, steps=50)
ig_alt = integrated_gradients(model, oh_alt, target_idx, device, steps=50)

# Save per-base IG table (+/- 80 bp around rs1883123)
sl_tab = slice(snp_rel - 80, snp_rel + 81)
pd.DataFrame({
    "offset_from_snp": np.arange(-80, 81),
    "genomic_pos_1based": np.arange(SNP_POS - 80, SNP_POS + 81),
    "ref_base": list(seq_ref[sl_tab]),
    "alt_base": list(seq_alt[sl_tab]),
    "ig_ref_sum": ig_ref[sl_tab].sum(axis=1),
    "ig_alt_sum": ig_alt[sl_tab].sum(axis=1),
}).to_csv(out / "fig7e_rs1883123_ig_contrib.csv", index=False)

motif_21_ref = float(ig_ref[snp_rel - 10 : snp_rel + 11].sum())
motif_21_alt = float(ig_alt[snp_rel - 10 : snp_rel + 11].sum())

# Plot Figure 7E: Left = +/-75 bp wide sequence logo; Right = zoomed 10-bp ATGCTAAT motif logo
W_HALF = 75
sl_wide = slice(snp_rel - W_HALF, snp_rel + W_HALF + 1)
# Zoom right onto ATGCTAAT (offset -4 to +5 -> 10 bp centered on motif)
m_pos = seq_ref.find("ATGCTAAT", snp_rel - 10, snp_rel + 10)
if m_pos >= 0:
    z_lo, z_hi = m_pos - 1, m_pos + 9
else:
    z_lo, z_hi = snp_rel - 5, snp_rel + 5

y_min = float(min(ig_ref[sl_wide].min(), ig_alt[sl_wide].min())) * 1.12
y_max = float(max(ig_ref[sl_wide].max(), ig_alt[sl_wide].max())) * 1.12

fig = plt.figure(figsize=(11.5, 4.2), dpi=180)
gs = fig.add_gridspec(2, 2, width_ratios=[2.4, 1.0], wspace=0.14, hspace=0.35)

for row_i, (ig, lbl, pred_v) in enumerate([
    (ig_ref, f"Reference ({ref_base}) — pred = {pred_ref:.2f}", pred_ref),
    (ig_alt, f"Alternate ({alt_base}) — pred = {pred_alt:.2f}", pred_alt),
]):
    ax_w = fig.add_subplot(gs[row_i, 0])
    plot_seq_logo(ax_w, ig[sl_wide], title=lbl)
    ax_w.set_ylim(y_min, y_max)
    # Red rectangle highlighting zoomed motif window
    box_x = z_lo - (snp_rel - W_HALF)
    ax_w.add_patch(
        patches.Rectangle((box_x - 0.5, y_min * 0.92), (z_hi - z_lo), (y_max - y_min) * 0.92,
                          fill=False, edgecolor="#d62728", lw=1.3, zorder=6)
    )
    ax_w.set_ylabel("IG score", fontsize=8)
    if row_i == 1:
        ax_w.set_xlabel(f"Position relative to window start (rs1883123 at x={W_HALF}; {CHROM}:{SNP_POS:,} {ref_base}>{alt_base})", fontsize=8)

    ax_z = fig.add_subplot(gs[row_i, 1])
    plot_seq_logo(ax_z, ig[z_lo:z_hi], title=("TCF12 Binding Site (ATGCTAAT)" if row_i == 0 else f"Disrupted ({ref_base}->{alt_base})"))
    ax_z.set_ylim(y_min, y_max)
    snp_in_z = snp_rel - z_lo
    ax_z.axvline(snp_in_z, color="#d62728", ls="--", lw=0.9, alpha=0.7)
    ax_z.set_xticks(range(z_hi - z_lo))
    ax_z.set_xticklabels(list((seq_ref if row_i == 0 else seq_alt)[z_lo:z_hi]), fontsize=8, fontweight="bold")
    for spine in ax_z.spines.values():
        spine.set_edgecolor("#d62728")
        spine.set_linewidth(1.1)

fig.suptitle(f"DeepHumanBG Integrated Gradients — {TARGET_GROUP} at rs1883123 ({CHROM}:{SNP_POS:,} {ref_base}>{alt_base})", fontsize=10, y=0.98)
fig.subplots_adjust(left=0.06, right=0.98, top=0.86, bottom=0.13)
fig.savefig(out / "fig7e.png", dpi=180)
plt.close(fig)

metrics = {
    "target_group": TARGET_GROUP,
    "target_channel_idx": int(target_idx),
    "ref_base": ref_base,
    "alt_base": alt_base,
    "ref_base_is_C": bool(ref_base == "C"),
    "flank_15bp": flank_15,
    "contains_atgctaat_motif": bool("ATGCTAAT" in flank_15),
    "pred_ref": round(pred_ref, 4),
    "pred_alt": round(pred_alt, 4),
    "delta_alt_minus_ref": round(pred_alt - pred_ref, 4),
    "motif_21bp_ig_sum_ref": round(motif_21_ref, 4),
    "motif_21bp_ig_sum_alt": round(motif_21_alt, 4),
    "alt_reduces_pred_and_motif_ig": bool((pred_alt < pred_ref) and (motif_21_alt < motif_21_ref)),
}
write_metrics(metrics)
print(metrics)
