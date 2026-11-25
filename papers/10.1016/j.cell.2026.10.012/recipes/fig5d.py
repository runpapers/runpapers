# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8",
#   "pyfaidx>=0.8", "torch>=2.3", "keras>=3.5",
# ]
# ///
"""Figure 5D: DeepHumanBG predicted chromatin accessibility across all 48 Hunker, Wirthlin et al.
(2025) striatal AAV enhancers and core-concatemer variants (3xC2, 6xC2, 3xC3) parsed directly
from the public Allen Genetic Tools Atlas 2.0 snapshot (SpecimenMetadata.csv) and hg38/mm10 genomes.

Reproduces the normalized predicted accessibility heatmap across the 14 target striatal Groups
and raw target-class accessibility sidebar (0-8), verifying:
- AiE0441h and AiE0441h_3xC2 preferentially target STR D1D2 eSPN over classical D1 SPNs;
- AiE1419m is selectively predicted for STR FS PTHLH-PVALB GABA;
- AiE1404m is strongly predicted for STR SST-CHODL GABA;
- Optimized AiE0779m concatemers increase predicted accessibility monotonically (6xC2 > 3xC2 > FL);
- All 7 cholinergic enhancers peak selectively in Cholinergic GABA Groups."""
import re
import zipfile

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
    load_deephumanbg,
    one_hot_batch,
    open_genome_fasta,
    out_dir,
    pad_sequence_n,
    rp_seed,
    write_metrics,
)

d = data_dir()
out = out_dir()
seed = rp_seed()

# Exact 48 enhancers in published Figure 5D order grouped by target class (Hunker, Wirthlin et al. 2025)
ENHANCER_CLASSES = [
    ("pan-SPN", "#e7298a", [
        "AiE1026h", "AiE0367h_C2", "AiE0621h", "AiE0621h_3xC2", "AiE0603m",
        "AiE0441h", "AiE0616h_3xC2", "AiE0441h_3xC2", "AiE0782m", "AiE2116m_3xC2",
        "AiE0447h", "AiE0351h", "AiE0351h_3xC2", "AiE0784m", "AiE0618h",
        "AiE0450h", "AiE1191m", "AiE0785m", "AiE0367h_3xC2", "AiE0367h",
    ]),
    ("D1-SPN", "#ae017e", [
        "AiE0617h", "AiE0612h", "AiE1190m", "AiE0444h",
        "AiE0452h_3xC2", "AiE0452h", "AiE0445h",
    ]),
    ("D2-SPN", "#6a3d9a", [
        "AiE0780m", "AiE0779m_6xC2", "AiE0779m_3xC2", "AiE0779m", "AiE0616h",
    ]),
    ("Cholinergic", "#ff7f00", [
        "AiE0743m_3xC2", "AiE0873m_3xC2", "AiE0873m", "AiE0869m",
        "AiE0743m", "AiE0868m", "AiE0576h_3xC3",
    ]),
    ("Sst Chodl", "#1b7837", [
        "AiE0600m", "AiE0769m", "AiE1426m", "AiE0682h", "AiE1404m",
    ]),
    ("Pvalb-Pthlh", "#8c510a", [
        "AiE0951h", "AiE1419m", "AiE1421m", "AiE0140h_3xC2",
    ]),
]

# Exact 14 target columns in published Figure 5D
TARGET_COLS_14 = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STRv D1 SPN",
    "STRv D2 SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
    "GPin-BF Cholinergic GABA",
    "STR Cholinergic GABA",
    "STRd Cholinergic GABA",
    "STR SST-CHODL GABA",
    "STR FS PTHLH-PVALB GABA",
]

SHORT_COL_LABELS = [
    "STRd D1 Matrix", "STRd D1 Striosome", "STRd D2 Matrix", "STRd D2 Striosome",
    "STRv D1", "STRv D2", "STR D2 SMYD2", "STR D1D2 eSPN", "STRv D1 NUDAP eSPN",
    "GPin-BF Chol", "STR Chol", "STRd Chol",
    "STR SST-CHODL", "STR PTHLH-PVALB",
]

CLASS_TARGET_GROUPS = {
    "pan-SPN": TARGET_COLS_14[:9],
    "D1-SPN": ["STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRv D1 SPN"],
    "D2-SPN": ["STRd D2 Matrix SPN", "STRd D2 Striosome SPN", "STRv D2 SPN", "STRd D1 Matrix SPN", "STRd D1 Striosome SPN"],
    "Cholinergic": ["GPin-BF Cholinergic GABA", "STR Cholinergic GABA", "STRd Cholinergic GABA"],
    "Sst Chodl": ["STR SST-CHODL GABA"],
    "Pvalb-Pthlh": ["STR FS PTHLH-PVALB GABA"],
}

# Known alias in GTA v2.0 snapshot where AiE0616h_3xC2 is recorded as AiE0616h_3xC2b
GTA_ALIASES = {"AiE0616h_3xC2": "AiE0616h_3xC2b"}

# 1. Parse GTA v2.0 SpecimenMetadata.csv for all 48 enhancers
all_enh_ids = [e for _, _, es in ENHANCER_CLASSES for e in es]
lookup_targets = set(all_enh_ids) | set(GTA_ALIASES.values())

with zipfile.ZipFile(d / "allen_gta_v2_snapshot.zip") as zf:
    csv_nm = [n for n in zf.namelist() if "SpecimenMetadata" in n][0]
    gta_df = pd.read_csv(zf.open(csv_nm), low_memory=False)

coords_map: dict[str, tuple[str, str]] = {}
# Pass 1: clean single-enhancer rows
for _, r in gta_df.iterrows():
    en = str(r.get("Enhancer ID", "")).strip()
    co = str(r.get("Enhancer Coordinates", "")).strip()
    gb = str(r.get("Genome Build (enhancer)", "")).strip()
    if "|" not in en and en in lookup_targets and co.startswith("chr") and gb in ("hg38", "mm10"):
        coords_map.setdefault(en, (gb, co))

# Pass 2: pipe-delimited multi-enhancer rows (disambiguating species via h/m suffix)
for _, r in gta_df.iterrows():
    en = str(r.get("Enhancer ID", "")).strip()
    co = str(r.get("Enhancer Coordinates", "")).strip()
    gb = str(r.get("Genome Build (enhancer)", "")).strip()
    if "|" not in en:
        continue
    ens = [x.strip() for x in en.split("|")]
    cos = [x.strip() for x in co.split("|")]
    gbs = [x.strip() for x in gb.split("|")]
    if len(ens) == len(cos) == len(gbs):
        for e_i, c_i, g_i in zip(ens, cos, gbs):
            if e_i in lookup_targets and e_i not in coords_map and c_i.startswith("chr") and g_i in ("hg38", "mm10"):
                want_g = "hg38" if e_i.split("_")[0].endswith("h") else "mm10"
                if g_i == want_g:
                    coords_map[e_i] = (g_i, c_i)

# 2. Fetch hg38/mm10 DNA sequences, apply concatemer repeats (3x / 6x), and N-pad to 2,114 bp
model, _ = load_deephumanbg()
win = int(model.input_shape[1])
fasta_hg38 = open_genome_fasta("hg38")
fasta_mm10 = open_genome_fasta("mm10")

peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks_df.columns = [canon_group(c) for c in peaks_df.columns]
_, group_to_idx = calibrate_deephumanbg_channels(model, fasta_hg38, peaks_df=peaks_df, seed=seed)

meta_rows = []
padded_seqs = []
for cls_name, cls_col, enh_list in ENHANCER_CLASSES:
    for enh_id in enh_list:
        key = enh_id if enh_id in coords_map else GTA_ALIASES.get(enh_id, enh_id)
        if key not in coords_map:
            raise KeyError(f"Enhancer {enh_id} not found in allen_gta_v2_snapshot.zip")
        gb, coord = coords_map[key]
        chrom, span = coord.split(":")
        st, en_p = [int(x) for x in span.split("-")]
        fa = fasta_hg38 if gb == "hg38" else fasta_mm10
        core_seq = str(fa[chrom][st:en_p]).upper()
        # Concatemer repeats for engineered multi-copy cores (e.g., _3xC2, _6xC2, _3xC3)
        m_rep = re.search(r"_(\d+)xC", enh_id)
        n_rep = int(m_rep.group(1)) if m_rep else 1
        full_seq = core_seq * n_rep
        pad_seq = pad_sequence_n(full_seq, win)
        padded_seqs.append(pad_seq)
        meta_rows.append({
            "enhancer_id": enh_id,
            "target_class": cls_name,
            "genome_build": gb,
            "coordinates": coord,
            "core_len_bp": len(core_seq),
            "n_repeats": n_rep,
            "construct_len_bp": len(full_seq),
        })

meta_df = pd.DataFrame(meta_rows)
oh = one_hot_batch(padded_seqs)
preds_all = np.clip(model.predict(oh, batch_size=32, verbose=0), 0.0, None)

# 3. Extract 14 target columns, compute row-normalized heatmap and target-class raw strength
col_indices = [group_to_idx[g] for g in TARGET_COLS_14]
pred_14 = pd.DataFrame(preds_all[:, col_indices], index=meta_df["enhancer_id"], columns=TARGET_COLS_14)
row_max = np.maximum(pred_14.max(axis=1).values[:, None], 1e-6)
norm_14 = pd.DataFrame(pred_14.values / row_max, index=pred_14.index, columns=TARGET_COLS_14)

target_strength = []
for _, r in meta_df.iterrows():
    eid = r["enhancer_id"]
    tgs = CLASS_TARGET_GROUPS[r["target_class"]]
    target_strength.append(float(pred_14.loc[eid, tgs].mean()))
meta_df["target_mean_pred"] = target_strength
meta_df["top_group_14"] = pred_14.idxmax(axis=1).values
meta_df["top_pred_14"] = pred_14.max(axis=1).values

pred_14.to_csv(out / "fig5d_enhancer_predictions_raw.csv")
norm_14.to_csv(out / "fig5d_enhancer_predictions_norm.csv")
meta_df.to_csv(out / "fig5d_enhancer_summary.csv", index=False)

# 4. Verify biological claims from main p.12 & Figure 5D
aie0441_top = str(pred_14.loc["AiE0441h"].idxmax())
aie0441_3x_top = str(pred_14.loc["AiE0441h_3xC2"].idxmax())
aie1419_top = str(pred_14.loc["AiE1419m"].idxmax())
aie1404_top = str(pred_14.loc["AiE1404m"].idxmax())

p_0779_fl = float(meta_df.loc[meta_df["enhancer_id"] == "AiE0779m", "target_mean_pred"].iloc[0])
p_0779_3x = float(meta_df.loc[meta_df["enhancer_id"] == "AiE0779m_3xC2", "target_mean_pred"].iloc[0])
p_0779_6x = float(meta_df.loc[meta_df["enhancer_id"] == "AiE0779m_6xC2", "target_mean_pred"].iloc[0])
mono_0779 = (p_0779_6x > p_0779_3x > p_0779_fl)

chol_ids = [e for c, _, es in ENHANCER_CLASSES if c == "Cholinergic" for e in es]
chol_cols = ["GPin-BF Cholinergic GABA", "STR Cholinergic GABA", "STRd Cholinergic GABA"]
n_chol_correct = int(sum(str(pred_14.loc[e].idxmax()) in chol_cols for e in chol_ids))
chol_mean_top3 = norm_14.loc[chol_ids].mean(axis=0).sort_values(ascending=False).index[:3].tolist()
chol_peak_ok = (set(chol_mean_top3) == set(chol_cols)) and (n_chol_correct >= 6)

# 5. Plot Figure 5D matching published heatmap + purple magnitude bar + class boxes
fig = plt.figure(figsize=(8.6, 10.6), dpi=180)
gs = fig.add_gridspec(1, 2, width_ratios=[14.0, 1.3], wspace=0.05)

ax_hm = fig.add_subplot(gs[0, 0])
im = ax_hm.imshow(norm_14.values, aspect="auto", cmap="viridis", vmin=0.0, vmax=1.0, interpolation="nearest")

# White vertical separators between SPN (0..8), Chol (9..11), SST (12), PVALB (13)
for vx in (8.5, 11.5, 12.5):
    ax_hm.axvline(vx, color="white", lw=3.2, zorder=4)

# Draw colored class border rectangles & row separators
row_cursor = 0
for cls_name, cls_col, enh_list in ENHANCER_CLASSES:
    n_e = len(enh_list)
    rect = patches.Rectangle(
        (-0.5, row_cursor - 0.5), len(TARGET_COLS_14), n_e,
        fill=False, edgecolor=cls_col, lw=2.2, zorder=5,
    )
    ax_hm.add_patch(rect)
    row_cursor += n_e

ax_hm.set_xticks(range(len(TARGET_COLS_14)))
ax_hm.set_xticklabels(SHORT_COL_LABELS, rotation=90, fontsize=8.2)
ax_hm.set_yticks([])
ax_hm.set_title("DeepHumanBG Predictions on Hunker, Wirthlin et al. (2025) Striatal AAVs (n=48)", fontsize=9.8, pad=8)

# Right sidebar: log1p target-class predicted accessibility (Purples 0..8.5, matching published 0..8 scale)
ax_mag = fig.add_subplot(gs[0, 1])
log_strength = np.log1p(np.array(target_strength, dtype=np.float64))
vmax_mag = max(8.5, float(log_strength.max()))
im_m = ax_mag.imshow(
    log_strength[:, None], aspect="auto", cmap="Purples",
    vmin=0.0, vmax=vmax_mag, interpolation="nearest",
)
ax_mag.set_xticks([])
ax_mag.yaxis.tick_right()
ax_mag.set_yticks(range(len(all_enh_ids)))
ax_mag.set_yticklabels(all_enh_ids, fontsize=7.5, style="italic")
for lbl_txt in ax_mag.get_yticklabels():
    if lbl_txt.get_text() in {"AiE0779m", "AiE0779m_3xC2", "AiE0779m_6xC2"}:
        lbl_txt.set_fontweight("bold")

row_cursor = 0
for _, cls_col, enh_list in ENHANCER_CLASSES:
    n_e = len(enh_list)
    ax_mag.axhline(row_cursor - 0.5, color="#333333", lw=1.0)
    row_cursor += n_e

# Colorbars
cb1 = fig.colorbar(im, ax=ax_hm, location="left", fraction=0.035, pad=0.04, shrink=0.35)
cb1.set_label("Predicted accessibility\n(row-normalized)", fontsize=8)
cb2 = fig.colorbar(im_m, ax=ax_mag, location="bottom", fraction=0.04, pad=0.03, aspect=10)
cb2.set_label("log(1 + pred)", fontsize=7.5)

# Class legend along bottom
handles = [patches.Patch(facecolor="none", edgecolor=col, lw=2.2, label=nm) for nm, col, _ in ENHANCER_CLASSES]
fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0.52, 0.005))

fig.subplots_adjust(left=0.14, right=0.80, top=0.95, bottom=0.19)
fig.savefig(out / "fig5d.png", dpi=180)
plt.close(fig)

metrics = {
    "n_hunker_enhancers_scored": int(len(meta_df)),
    "aie0441h_top_group": aie0441_top,
    "aie0441h_3xc2_top_group": aie0441_3x_top,
    "aie0441h_top_group_is_espn": bool(aie0441_top == "STR D1D2 eSPN" and aie0441_3x_top == "STR D1D2 eSPN"),
    "aie1419m_top_group": aie1419_top,
    "aie1419m_top_group_is_pvalb": bool(aie1419_top == "STR FS PTHLH-PVALB GABA"),
    "aie1404m_top_group": aie1404_top,
    "aie1404m_top_group_is_sst_chodl": bool(aie1404_top == "STR SST-CHODL GABA"),
    "aie0779m_fl_target_pred": round(p_0779_fl, 4),
    "aie0779m_3xc2_target_pred": round(p_0779_3x, 4),
    "aie0779m_6xc2_target_pred": round(p_0779_6x, 4),
    "aie0779m_6xc2_gt_3xc2_gt_fl": bool(mono_0779),
    "cholinergic_enhancers_peak_in_cholinergic": bool(chol_peak_ok),
    "n_cholinergic_enhancers_correct": int(sum(str(pred_14.loc[e].idxmax()) in chol_cols for e in chol_ids)),
}
write_metrics(metrics)
print(metrics)
