# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8",
#   "pyfaidx>=0.8", "torch>=2.3", "keras>=3.5",
# ]
# ///
"""Figure 7C: DeepHumanBG predicted chromatin accessibility effects of the 8 genome-wide significant
schizophrenia (SCZ) GWAS SNPs across the 18 MAGMA-enriched basal ganglia neuronal Groups.

Important sign-convention note (documented paper discrepancy):
The authors' analysis notebook computes delta = original_pred - mutated_pred (Ref - Alt) while
labeling axes 'mutated - original', causing rs1883123 (CACNA1I, C>T, which DECREASES predicted
accessibility in GPe MEIS2-SOX6 GABA) to appear positive (+45.31 in Table S20, red dot in Fig 7C).
This recipe records BOTH true biological delta (Alt - Ref) and author-convention delta (Ref - Alt)
from the publicly released DeepHumanBG finetune_epoch_12.keras model."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_epig import (
    calibrate_deephumanbg_channels,
    canon_group,
    data_dir,
    load_deephumanbg,
    one_hot_seq,
    open_hg38_fasta,
    out_dir,
    rp_seed,
    write_metrics,
)

d = data_dir()
out = out_dir()
seed = rp_seed()

# Exact 8 SCZ GWAS SNPs from Figure 7C (hg38 coordinates and alleles)
FIG7C_SNPS = [
    ("rs700670", "PLCL1", "chr2", 197822560, "T", "C"),
    ("rs118134308", "TCF4", "chr18", 55623646, "A", "G"),
    ("rs13262595", "TSNARE1", "chr8", 142235609, "A", "G"),
    ("rs7587598", "PLCL1", "chr2", 197977520, "A", "G"),
    ("rs1113736", "MAD1L1", "chr7", 1953357, "T", "C"),
    ("rs2711117", "PALS2", "chr7", 24550450, "T", "A"),
    ("rs1610602", "HLA-F", "chr6", 29734284, "C", "A"),
    ("rs1883123", "CACNA1I", "chr22", 39600877, "C", "T"),
]

# Exact 18 MAGMA-enriched BG neuronal Groups on Figure 7C x-axis (canonical 20261031 names)
GROUPS_18 = [
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STRv D1 SPN",
    "STRv D2 SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STRv D1 NUDAP eSPN",
    "OT ICj Granule",
    "GPe MEIS2-SOX6 GABA",
    "AMY-SLEA-BNST GABA",
    "OB FRMD7 GABA",
    "VIP GABA",
    "LAMP5-CXCL14 GABA",
    "STR SST-RSPO2 GABA",
    "STR LYPD6-RSPO2 GABA",
    "LAMP5-LHX6 GABA",
    "STR-BF TAC3-PLPP4-LHX8 GABA",
    "STRd Cholinergic GABA",
]

model, _ = load_deephumanbg()
win = int(model.input_shape[1])
half = win // 2
fasta = open_hg38_fasta()

peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks_df.columns = [canon_group(c) for c in peaks_df.columns]
idx_to_group, group_to_idx = calibrate_deephumanbg_channels(model, fasta, peaks_df=peaks_df, seed=seed)

bed = pd.read_csv(
    d / "atac_human_consensus_peaks.bed", sep="\t", header=None, usecols=[0, 1, 2], names=["chr", "start", "end"]
)

rows_ref_minus_alt = {}
rows_alt_minus_ref = {}
snp_meta = []

for rs, gene, ch, pos, a1, a2 in FIG7C_SNPS:
    hit = bed[(bed["chr"] == ch) & (bed["start"] <= pos) & (bed["end"] >= pos)]
    ctr = int((hit.iloc[0]["start"] + hit.iloc[0]["end"]) // 2) if len(hit) else pos
    ws = ctr - half
    s_ref = str(fasta[ch][ws : ws + win]).upper()
    rel = (pos - 1) - ws
    rb = s_ref[rel]
    ab = a2 if rb == a1 else (a1 if rb == a2 else a2)
    s_alt = s_ref[:rel] + ab + s_ref[rel + 1 :]
    p_ref = np.squeeze(model.predict(one_hot_seq(s_ref)[None, :, :], verbose=0))
    p_alt = np.squeeze(model.predict(one_hot_seq(s_alt)[None, :, :], verbose=0))
    d_ra = p_ref - p_alt
    d_ar = p_alt - p_ref
    rows_ref_minus_alt[rs] = {g: float(d_ra[group_to_idx[g]]) for g in GROUPS_18}
    rows_alt_minus_ref[rs] = {g: float(d_ar[group_to_idx[g]]) for g in GROUPS_18}
    top_g = max(GROUPS_18, key=lambda g: abs(rows_ref_minus_alt[rs][g]))
    snp_meta.append({
        "rsid": rs,
        "gene": gene,
        "coord": f"{ch}:{pos}",
        "ref": rb,
        "alt": ab,
        "in_consensus_ccre": bool(len(hit) > 0),
        "top_group_18": top_g,
        "top_delta_alt_minus_ref": rows_alt_minus_ref[rs][top_g],
        "top_delta_ref_minus_alt": rows_ref_minus_alt[rs][top_g],
    })

mat_ra = pd.DataFrame.from_dict(rows_ref_minus_alt, orient="index")[GROUPS_18]
mat_ar = pd.DataFrame.from_dict(rows_alt_minus_ref, orient="index")[GROUPS_18]
mat_ar.to_csv(out / "fig7c_deephumanbg_8snps_alt_minus_ref.csv")
mat_ra.to_csv(out / "fig7c_deephumanbg_8snps_ref_minus_alt_author_conv.csv")
pd.DataFrame(snp_meta).to_csv(out / "fig7c_8snps_summary.csv", index=False)

# Row-wise z-score clipped to [-1, 1] and capped magnitude (|delta| <= 100) matching author RECAP_SNPs_code.py
z_ra = mat_ra.sub(mat_ra.mean(axis=1), axis=0).div(mat_ra.std(axis=1).replace(0, 1.0), axis=0).clip(-1.0, 1.0)
mag = mat_ra.abs().clip(upper=100.0)

fig, ax = plt.subplots(figsize=(10.6, 4.9), dpi=180)
for ri, (rs, gene, *_rest) in enumerate(FIG7C_SNPS):
    for ci, g in enumerate(GROUPS_18):
        val_z = float(z_ra.loc[rs, g])
        val_m = float(mag.loc[rs, g])
        ax.scatter(
            [ci], [ri], s=val_m * 3.2 + 8.0, c=[val_z],
            cmap="coolwarm", vmin=-1.0, vmax=1.0, edgecolors="none",
        )

# Colorbar & size legend
sm = plt.cm.ScalarMappable(cmap="coolwarm", norm=plt.Normalize(-1.0, 1.0))
cb = fig.colorbar(sm, ax=ax, shrink=0.65, pad=0.02)
cb.set_label("Scaled Ref - Alt score\n(red = Alt decreases ATAC)", fontsize=8)

for sz_val in (10, 50, 100):
    ax.scatter([], [], s=sz_val * 3.2 + 8.0, color="#666666", label=f"{sz_val}")
ax.legend(title="|Delta|", loc="upper left", bbox_to_anchor=(1.14, 0.35), frameon=False, fontsize=8, title_fontsize=8.5, labelspacing=1.2)

ax.set_xticks(range(len(GROUPS_18)))
ax.set_xticklabels(GROUPS_18, rotation=48, ha="right", fontsize=8)
ax.set_yticks(range(len(FIG7C_SNPS)))
ax.set_yticklabels([f"{rs} ({gene})" for rs, gene, *_ in FIG7C_SNPS], fontsize=8.5)
ax.invert_yaxis()
ax.set_title(
    "DeepHumanBG (finetune_epoch_12) Predicted Accessibility Effects of 8 SCZ GWAS SNPs\n"
    "(Plotted on published Ref - Alt sign convention: red = Alt decreases accessibility)",
    fontsize=9.5,
)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
fig.savefig(out / "fig7c.png", dpi=180)
plt.close(fig)

rs188_gpe_ra = float(mat_ra.loc["rs1883123", "GPe MEIS2-SOX6 GABA"])
rs188_gpe_ar = float(mat_ar.loc["rs1883123", "GPe MEIS2-SOX6 GABA"])
rs188_top_g = max(GROUPS_18, key=lambda g: abs(float(mat_ra.loc["rs1883123", g])))

metrics = {
    "n_scz_snps_scored": len(FIG7C_SNPS),
    "n_bg_groups_plotted": len(GROUPS_18),
    "rs1883123_top_group": rs188_top_g,
    "rs1883123_top_group_is_gpe_meis2_sox6": bool(rs188_top_g == "GPe MEIS2-SOX6 GABA"),
    "rs1883123_gpe_delta_alt_minus_ref": round(rs188_gpe_ar, 4),
    "rs1883123_gpe_delta_ref_minus_alt_table_s20": round(rs188_gpe_ra, 4),
    "rs1883123_alt_decreases_gpe_accessibility": bool(rs188_gpe_ar < 0.0),
    "rs1610602_ob_frmd7_delta_ref_minus_alt": round(float(mat_ra.loc["rs1610602", "OB FRMD7 GABA"]), 4),
    "rs13262595_lamp5_cxcl14_delta_ref_minus_alt": round(float(mat_ra.loc["rs13262595", "LAMP5-CXCL14 GABA"]), 4),
}
write_metrics(metrics)
print(metrics)
