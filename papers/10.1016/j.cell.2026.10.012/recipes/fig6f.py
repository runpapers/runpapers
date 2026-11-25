# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8"]
# ///
"""Figure 6F (Macaque): Patch-seq intrinsic electrophysiology across six striatal SPN Groups.

Reproduces the macaque Rheobase (pA) and 3 dB cutoff frequency (Hz) boxplots from published Figure 6F
using the open Allen Brain Cell Atlas HMBA-Macaque-PatchSeq (20260228) feature tables. Preprint Group
labels in mmc_results.csv are joined by stable CS20250428_GROUP_* accession IDs to the Cell 2026
nomenclature in cluster_annotation_term.csv. Mouse Patch-seq recordings shown alongside macaque in
published Figure 6F are hosted in companion study Budzillo et al. and are not in this release."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from bg_atlas import data_dir, group_id_to_name, group_order, out_dir, write_metrics

SPN6 = [
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
    "STRd D2 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D1 Matrix SPN",
]
SHORT_LABELS = {
    "STR D2 SMYD2-HTR7 SPN": "STR D2 SMYD2",
    "STR D1D2 eSPN": "STR D1D2 eSPN",
    "STRd D2 Striosome SPN": "STRd D2 Striosome",
    "STRd D2 Matrix SPN": "STRd D2 Matrix",
    "STRd D1 Striosome SPN": "STRd D1 Striosome",
    "STRd D1 Matrix SPN": "STRd D1 Matrix",
}
CANONICAL = [
    "STRd D2 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D1 Matrix SPN",
]

d = data_dir()
pm = pd.read_csv(d / "macaque_patchseq_cell_metadata.csv")
mmc = pd.read_csv(d / "macaque_patchseq_mmc_results.csv")
lsq = pd.read_csv(d / "macaque_patchseq_cross_sweep_long_square_features.csv")
chp = pd.read_csv(d / "macaque_patchseq_chrip_features.csv")

id2name = group_id_to_name()
_, grp_colors = group_order()
# Use a darker violet for STR D2 SMYD2-HTR7 SPN to distinguish it cleanly from STR D1D2 eSPN as in published Fig 6F
grp_colors = dict(grp_colors)
grp_colors["STR D2 SMYD2-HTR7 SPN"] = "#54278f"

df = pm.merge(mmc[["cell_label", "Group_label", "Group_name"]], on="cell_label", how="left", validate="one_to_one")
df["Group"] = df["Group_label"].map(id2name)
if df["Group"].isna().any():
    raise ValueError(f"Unmapped Group_label values in macaque Patch-seq: {df.loc[df['Group'].isna(), 'Group_label'].unique()}")
df = df.merge(lsq[["cell_label", "rheobase_i", "input_resistance_ss"]], on="cell_label", how="left", validate="one_to_one")
df = df.merge(chp[["cell_label", "3db_freq_chirp"]], on="cell_label", how="left", validate="one_to_one")

sub = df[df["Group"].isin(SPN6)].copy()
sub[["cell_label", "donor_label", "Group_label", "Group", "rheobase_i", "3db_freq_chirp", "input_resistance_ss"]].to_csv(
    out_dir() / "fig6f_macaque_patchseq.csv", index=False
)

summary_rows = []
for g in SPN6:
    sg = sub[sub["Group"] == g]
    rv = sg["rheobase_i"].dropna()
    cv = sg["3db_freq_chirp"].dropna()
    summary_rows.append({
        "Group": g,
        "n_mapped": int(len(sg)),
        "n_donors": int(sg["donor_label"].nunique()),
        "n_rheobase": int(len(rv)),
        "median_rheobase_pA": round(float(rv.median()), 2),
        "n_3db": int(len(cv)),
        "median_3db_Hz": round(float(cv.median()), 3),
    })
summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv(out_dir() / "fig6f_summary.csv", index=False)

smyd = sub[sub["Group"] == "STR D2 SMYD2-HTR7 SPN"]
canon = sub[sub["Group"].isin(CANONICAL)]
_, p_rheo = stats.mannwhitneyu(smyd["rheobase_i"].dropna(), canon["rheobase_i"].dropna(), alternative="less")
_, p_3db = stats.mannwhitneyu(smyd["3db_freq_chirp"].dropna(), canon["3db_freq_chirp"].dropna(), alternative="less")

med_rheo = dict(zip(summary_df["Group"], summary_df["median_rheobase_pA"]))
med_3db = dict(zip(summary_df["Group"], summary_df["median_3db_Hz"]))

m = {
    "n_smyd2_mapped": int(len(smyd)),
    "n_smyd2_donors": int(smyd["donor_label"].nunique()),
    "n_smyd2_rheobase": int(smyd["rheobase_i"].notna().sum()),
    "n_smyd2_3db": int(smyd["3db_freq_chirp"].notna().sum()),
    "median_rheobase_smyd2_pa": float(med_rheo["STR D2 SMYD2-HTR7 SPN"]),
    "median_rheobase_espn_pa": float(med_rheo["STR D1D2 eSPN"]),
    "median_rheobase_canonical_min_pa": float(min(med_rheo[g] for g in CANONICAL)),
    "median_3db_smyd2_hz": float(med_3db["STR D2 SMYD2-HTR7 SPN"]),
    "median_3db_espn_hz": float(med_3db["STR D1D2 eSPN"]),
    "median_3db_canonical_min_hz": float(min(med_3db[g] for g in CANONICAL)),
    "smyd2_lowest_rheobase": bool(min(med_rheo, key=med_rheo.get) == "STR D2 SMYD2-HTR7 SPN"),
    "smyd2_lowest_3db": bool(min(med_3db, key=med_3db.get) == "STR D2 SMYD2-HTR7 SPN"),
    "mw_p_rheobase_smyd2_vs_canonical": float(p_rheo),
    "mw_p_3db_smyd2_vs_canonical": float(p_3db),
    "rheobase_sig_lt_005": bool(p_rheo < 0.05),
    "cutoff_3db_sig_lt_005": bool(p_3db < 0.05),
}

# Plot matching published Figure 6F macaque columns
rng = np.random.default_rng(0)
fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.3), sharey=True)
y_pos = np.arange(len(SPN6))

for ax_idx, (col, xlabel, is_log, p_val) in enumerate([
    ("rheobase_i", "Rheobase (pA)", False, p_rheo),
    ("3db_freq_chirp", "3 dB Cutoff (Hz)", True, p_3db),
]):
    ax = axes[ax_idx]
    ax.set_facecolor("#f7f7f7")
    for i, g in enumerate(SPN6):
        vals = sub.loc[sub["Group"] == g, col].dropna().values
        color = grp_colors[g]
        bp = ax.boxplot(
            vals,
            positions=[i],
            vert=False,
            widths=0.58,
            showfliers=False,
            patch_artist=True,
            boxprops=dict(facecolor="white", edgecolor=color, linewidth=1.3),
            medianprops=dict(color=color, linewidth=1.6),
            whiskerprops=dict(color=color, linewidth=1.1),
            capprops=dict(color=color, linewidth=1.1),
        )
        jitter = rng.uniform(-0.18, 0.18, size=len(vals))
        ax.scatter(vals, np.full(len(vals), i) + jitter, s=11, color="#333333", alpha=0.55, edgecolors="none", zorder=3)
    if is_log:
        from matplotlib.ticker import NullFormatter
        ax.set_xscale("log")
        ax.set_xlim(3.5, 45.0)
        ax.set_xticks([5, 10, 20, 40])
        ax.set_xticklabels(["5", "10", "20", "40"])
        ax.xaxis.set_minor_formatter(NullFormatter())
    else:
        ax.set_xlim(-20, 640)
    ax.set_title(f"{xlabel}\nMacaque (SMYD2 vs canonical MW p = {p_val:.2e})", fontsize=9.2, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=8.5)

axes[0].set_yticks(y_pos)
axes[0].set_yticklabels([SHORT_LABELS[g] for g in SPN6], fontsize=8.8)
axes[0].invert_yaxis()
# Highlight STR D2 SMYD2 and STRd D2 Matrix y-tick labels as in published Fig 6F
for tick, g in zip(axes[0].get_yticklabels(), SPN6):
    if g == "STR D2 SMYD2-HTR7 SPN":
        tick.set_color("#54278f")
        tick.set_fontweight("bold")
    elif g == "STRd D2 Matrix SPN":
        tick.set_color("#5b8fc9")
        tick.set_fontweight("bold")

n_gt640 = int((sub["rheobase_i"] > 640).sum())
clip_note = f"\nNote: {n_gt640} STRd D1 Matrix outlier at 1020 pA lies above the 640 pA display limit." if n_gt640 > 0 else ""
fig.suptitle("Figure 6F (Macaque Patch-seq): STR D2 SMYD2-HTR7 SPN intrinsic excitability", fontsize=10.2, fontweight="bold", y=0.98)
fig.text(
    0.5, 0.008,
    f"Macaque recordings from ABC Atlas HMBA-Macaque-PatchSeq (20260228); mouse Patch-seq is in companion Budzillo et al.{clip_note}",
    ha="center", va="bottom", fontsize=7.0, color="#444444",
)
fig.tight_layout(rect=[0, 0.055, 1, 0.94])
fig.savefig(out_dir() / "fig6f.png", dpi=180)
write_metrics(m)
print(m)
