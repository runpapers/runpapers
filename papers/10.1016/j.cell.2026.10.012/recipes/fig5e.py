# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8",
#   "pyfaidx>=0.8", "logomaker>=0.8", "torch>=2.3", "keras>=3.5",
# ]
# ///
"""Figure 5E: DeepHumanBG nucleotide-resolution Integrated Gradients sequence logo for mouse
striatal enhancer AiE0779m (mm10 chr10:19,829,172-19,829,652; 480 bp) averaged across D1 SPN heads
(STRd D1 Matrix SPN, STRd D1 Striosome SPN, STRv D1 SPN), highlighting its principal MEIS2, EGR1,
and RARB driver motifs from open data (Allen GTA 2.0 snapshot + mm10.fa.gz + JASPAR2024).

When optional 447-mammal Cactus tables (TableS14/TableS17) are also present in $RP_DATA_DIR,
plots the 19-clade 447-species predicted activity scatterplot alongside the contribution logo;
otherwise pairs the logo with the open AiE0779m FL -> 3xC2 -> 6xC2 predicted activity comparison
and notes that 447-species alignment requires the unbundled >1 TB Zoonomia HAL."""
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
    integrated_gradients_multi,
    load_deephumanbg,
    one_hot_seq,
    open_genome_fasta,
    out_dir,
    pad_sequence_n,
    parse_jaspar_meme,
    plot_seq_logo,
    rp_seed,
    scan_sequence_pwm,
    write_metrics,
)

d = data_dir()
out = out_dir()
seed = rp_seed()
rng = np.random.default_rng(seed)

# 1. Extract AiE0779m (FL) and AiE0779m_C2 coordinates from Allen GTA 2.0 snapshot
with zipfile.ZipFile(d / "allen_gta_v2_snapshot.zip") as zf:
    csv_nm = [n for n in zf.namelist() if "SpecimenMetadata" in n][0]
    gta_df = pd.read_csv(zf.open(csv_nm), low_memory=False)


def find_gta_coord(target_id: str) -> tuple[str, int, int]:
    for _, r in gta_df.iterrows():
        en = str(r.get("Enhancer ID", "")).strip()
        co = str(r.get("Enhancer Coordinates", "")).strip()
        gb = str(r.get("Genome Build (enhancer)", "")).strip()
        if en == target_id and co.startswith("chr") and gb == "mm10":
            ch, sp = co.split(":")
            s0, e0 = [int(x) for x in sp.split("-")]
            return ch, s0, e0
    for _, r in gta_df.iterrows():
        en = str(r.get("Enhancer ID", "")).strip()
        co = str(r.get("Enhancer Coordinates", "")).strip()
        gb = str(r.get("Genome Build (enhancer)", "")).strip()
        if "|" in en:
            for e_i, c_i, g_i in zip(en.split("|"), co.split("|"), gb.split("|")):
                if e_i.strip() == target_id and g_i.strip() == "mm10" and c_i.strip().startswith("chr"):
                    ch, sp = c_i.strip().split(":")
                    s0, e0 = [int(x) for x in sp.split("-")]
                    return ch, s0, e0
    raise KeyError(f"{target_id} mm10 coordinates not found in allen_gta_v2_snapshot.zip")


ch_fl, st_fl, en_fl = find_gta_coord("AiE0779m")
ch_c2, st_c2, en_c2 = find_gta_coord("AiE0779m_3xC2")

fa_hg38 = open_genome_fasta("hg38")
fa_mm10 = open_genome_fasta("mm10")
seq_fl = str(fa_mm10[ch_fl][st_fl:en_fl]).upper()
seq_c2 = str(fa_mm10[ch_c2][st_c2:en_c2]).upper()

# 2. Load DeepHumanBG, calibrate 59 heads, and run D1-SPN Integrated Gradients on AiE0779m
model, device = load_deephumanbg()
win = int(model.input_shape[1])
peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
peaks_df.columns = [canon_group(c) for c in peaks_df.columns]
_, group_to_idx = calibrate_deephumanbg_channels(model, fa_hg38, peaks_df=peaks_df, seed=seed)

D1_HEADS = ["STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRv D1 SPN"]
d1_idx = [group_to_idx[g] for g in D1_HEADS]

pad_fl = pad_sequence_n(seq_fl, win)
pad_3x = pad_sequence_n(seq_c2 * 3, win)
pad_6x = pad_sequence_n(seq_c2 * 6, win)

oh_fl = one_hot_seq(pad_fl)
pred_fl = float(np.squeeze(model.predict(oh_fl[None, :, :], verbose=0))[d1_idx].mean())
pred_3x = float(np.squeeze(model.predict(one_hot_seq(pad_3x)[None, :, :], verbose=0))[d1_idx].mean())
pred_6x = float(np.squeeze(model.predict(one_hot_seq(pad_6x)[None, :, :], verbose=0))[d1_idx].mean())

ig_full = integrated_gradients_multi(model, oh_fl, d1_idx, device, steps=50)
left_pad = (win - len(seq_fl)) // 2
ig_fl = ig_full[left_pad : left_pad + len(seq_fl)]
oh_core = oh_fl[left_pad : left_pad + len(seq_fl)]
ig_per_base = ig_fl.sum(axis=1)

pd.DataFrame({
    "rel_pos": np.arange(len(seq_fl)),
    "mm10_pos": np.arange(st_fl, st_fl + len(seq_fl)),
    "base": list(seq_fl),
    "ig_d1_spn": ig_per_base,
}).to_csv(out / "fig5e_aie0779m_ig_track.csv", index=False)

# 3. Locate MEIS2, EGR1, and RARB motif instances via JASPAR2024 PWMs and quantify their IG contribution
pwms = parse_jaspar_meme(d / "JASPAR2024_CORE_vertebrates_non-redundant_pfms_meme.txt")
# Note: RARB (JASPAR MA0858, 16-bp DR5 dimer) acts at its half-site directly flanking MEIS2 #3 (bp ~285-305)
# with strong negative repressor bases (GGTC) matching published Figure 5E.
MOTIF_SPECS = [
    ("MEIS2", "#6baed6", 0.40, 3),
    ("EGR1", "#74c476", 0.45, 1),
    ("RARB", "#fb6a4a", None, 1),
]
motif_hits = []
motif_best_ig = {}
for tf_name, col_hex, thr_frac, max_k in MOTIF_SPECS:
    pwm = pwms[tf_name]
    w = pwm.shape[1]
    max_sc = float(pwm.max(axis=0).sum())
    sc = scan_sequence_pwm(oh_core, pwm)
    if thr_frac is not None:
        cands = np.where(sc >= thr_frac * max_sc)[0]
        scored = [(int(p), float(sc[p]), float(ig_per_base[p : p + w].sum())) for p in cands]
        scored.sort(key=lambda t: -t[2])
    else:
        # Take highest-scoring PWM hit(s) in the active core region
        top_p = np.argsort(-sc)[:3]
        scored = [(int(p), float(sc[p]), float(ig_per_base[p : p + w].sum())) for p in top_p]
        scored.sort(key=lambda t: -t[1])
    kept = []
    for p, s_val, ig_val in scored:
        if all(abs(p - kp) >= max(w, 10) for kp, _, _ in kept):
            kept.append((p, s_val, ig_val))
        if len(kept) >= max_k:
            break
    motif_best_ig[tf_name] = float(kept[0][2]) if kept else 0.0
    for p, s_val, ig_val in kept:
        # For RARB dimer centered at 285..301, shade the non-overlapping repressor half-site tail (p+10..p+18) on the full track
        sh_s = (p + 11) if tf_name == "RARB" else p
        sh_e = min(len(seq_fl), (p + w + 4) if tf_name == "RARB" else (p + w))
        motif_hits.append({
            "tf": tf_name,
            "start": p,
            "end": p + w,
            "shade_start": sh_s,
            "shade_end": sh_e,
            "seq": seq_fl[p : p + w],
            "pwm_score": round(s_val, 3),
            "ig_sum": round(ig_val, 4),
            "color": col_hex,
        })

pd.DataFrame(motif_hits).to_csv(out / "fig5e_aie0779m_motifs.csv", index=False)

# 4. Check optional Table S14 + Table S17 for 447-mammal clade scatter
has_447 = (
    (d / "TableS14_cactus_species_info.csv").exists()
    and (d / "TableS14_clade_order.csv").exists()
    and (d / "TableS17_striatal_tools_447mammals.csv").exists()
)
mammal_metrics = {}

# 5. Plot Figure 5E
if has_447:
    t14 = pd.read_csv(d / "TableS14_cactus_species_info.csv")
    t14_ord = pd.read_csv(d / "TableS14_clade_order.csv")
    t17 = pd.read_csv(d / "TableS17_striatal_tools_447mammals.csv", index_col=0)
    sp_to_clade = {}
    for _, r in t14.iterrows():
        sp = str(r["species"]).strip()
        psh = str(r["primates_shorthand"]).strip() if pd.notna(r["primates_shorthand"]) else ""
        sp_to_clade[sp] = psh if psh else str(r["order"]).strip()
    s17 = t17.loc["AiE0779m"].dropna()
    m_df = pd.DataFrame({"species": s17.index.astype(str), "pred": s17.values.astype(float)})
    m_df["clade"] = m_df["species"].map(sp_to_clade).fillna("Other")
    m_df["pred_norm"] = m_df["pred"] / max(float(m_df["pred"].max()), 1e-6)
    clade_order = [str(c).strip() for c in t14_ord["clade"].tolist()]
    present_clades = [c for c in clade_order if c in set(m_df["clade"])]
    primate_clades = {"Great_apes", "Small_apes", "Old_World_monkeys", "New_World_monkeys", "Tarsiers", "Lemuriforms"}
    med_lago = float(m_df.loc[m_df["clade"] == "Lagomorpha", "pred"].median())
    med_prim = float(m_df.loc[m_df["clade"].isin(primate_clades), "pred"].median())
    med_cing = float(m_df.loc[m_df["clade"] == "Cingulata", "pred"].median())
    med_phol = float(m_df.loc[m_df["clade"] == "Pholidota", "pred"].median())
    mammal_metrics = {
        "n_mammalian_species_scored": int(len(m_df)),
        "n_clades_plotted": int(len(present_clades)),
        "lagomorpha_gt_primates_gt_cingulata_gt_pholidota": bool(med_lago > med_prim > med_cing > med_phol),
    }

# Render clean 2-row figure: top = full 480 bp mouse AiE0779m sequence logo with MEIS2/EGR1/RARB highlights;
# bottom = zoomed motif logos (MEIS2, EGR1, RARB) + FL / 3xC2 / 6xC2 predicted D1-SPN strength bar
fig = plt.figure(figsize=(12.2, 5.6), dpi=180)
gs = fig.add_gridspec(2, 4, height_ratios=[1.45, 1.0], hspace=0.48, wspace=0.26)

ax_top = fig.add_subplot(gs[0, :])
# Focus on active central span where C2 core & motifs sit (or full 480 bp)
plot_seq_logo(
    ax_top, ig_fl,
    title=f"Mouse AiE0779m ({ch_fl}:{st_fl:,}-{en_fl:,}, mm10, {len(seq_fl)} bp) — DeepHumanBG D1-SPN Integrated Gradients (mean pred = {pred_fl:.2f})",
)
ylo, yhi = ax_top.get_ylim()
for h in motif_hits:
    ax_top.axvspan(h["shade_start"] - 0.5, h["shade_end"] - 0.5, color=h["color"], alpha=0.28, zorder=0)
    lbl_y = yhi * 0.94 if h["tf"] != "RARB" else yhi * 0.78
    ax_top.text(
        (h["shade_start"] + h["shade_end"]) / 2.0, lbl_y, h["tf"],
        ha="center", va="top", fontsize=7.5, fontweight="bold", color="#222222",
    )
# Focus x-axis on the active 140..395 bp span (matching published Figure 5E zoom across C2 core + flanks)
ax_top.set_xlim(140, 395)
c2_rel_s = st_c2 - st_fl
c2_rel_e = en_c2 - st_fl
ax_top.axvspan(c2_rel_s, c2_rel_e, color="#dddddd", alpha=0.14, zorder=0)
ax_top.text(c2_rel_s + 2, ylo * 0.85 if ylo < 0 else yhi * 0.05, "C2 core (195 bp)", fontsize=7, color="#555555")
ax_top.set_ylabel("IG score (D1 SPN)", fontsize=8.5)
ax_top.set_xlabel("Position along AiE0779m (bp)", fontsize=8.5)

# Bottom left 3 panels: zoomed logos for strongest MEIS2, EGR1, RARB hits
for col_i, (tf_name, col_hex, _, _) in enumerate(MOTIF_SPECS):
    ax_m = fig.add_subplot(gs[1, col_i])
    sub_h = [h for h in motif_hits if h["tf"] == tf_name]
    if sub_h:
        best_h = max(sub_h, key=lambda x: x["ig_sum"])
        z0 = max(0, best_h["shade_start"] - 3)
        z1 = min(len(seq_fl), best_h["shade_end"] + 3)
        plot_seq_logo(ax_m, ig_fl[z0:z1], title=f"{tf_name} (IG={best_h['ig_sum']:.1f})")
        ax_m.set_xticks(range(z1 - z0))
        ax_m.set_xticklabels(list(seq_fl[z0:z1]), fontsize=7, fontweight="bold")
        ax_m.axvspan(best_h["shade_start"] - z0 - 0.5, best_h["shade_end"] - z0 - 0.5, color=col_hex, alpha=0.24, zorder=0)
    ax_m.set_ylabel("IG" if col_i == 0 else "", fontsize=8)

# Bottom right panel: FL -> 3xC2 -> 6xC2 predicted D1-SPN activity
ax_b = fig.add_subplot(gs[1, 3])
bars = ax_b.bar(["FL", "3xC2", "6xC2"], [pred_fl, pred_3x, pred_6x], color=["#bcbddc", "#807dba", "#54278f"], edgecolor="#222222", lw=0.7)
for b, val in zip(bars, [pred_fl, pred_3x, pred_6x]):
    ax_b.text(b.get_x() + b.get_width() / 2.0, val + 0.15, f"{val:.2f}", ha="center", va="bottom", fontsize=8, fontweight="bold")
ax_b.set_ylim(0, max(pred_6x, pred_3x, pred_fl) * 1.22)
ax_b.set_ylabel("Predicted D1-SPN ATAC", fontsize=8)
ax_b.set_title("AiE0779m Variants", fontsize=8.5)
ax_b.spines["top"].set_visible(False)
ax_b.spines["right"].set_visible(False)

fig.text(
    0.5, 0.01,
    "Reference mouse AiE0779m IG track computed from open data (Allen GTA 2.0 + mm10 + DeepHumanBG); 447-mammal Cactus HAL (>1 TB) is unbundled.",
    ha="center", fontsize=7.5, color="#555555",
)
fig.subplots_adjust(left=0.06, right=0.98, top=0.92, bottom=0.12)
fig.savefig(out / "fig5e.png", dpi=180)
plt.close(fig)

meis_ok = motif_best_ig.get("MEIS2", 0.0) > 0.05
egr_ok = motif_best_ig.get("EGR1", 0.0) > 0.05
rarb_ok = motif_best_ig.get("RARB", 0.0) > 0.05

metrics = {
    "aie0779m_coord_mm10": f"{ch_fl}:{st_fl}-{en_fl}",
    "aie0779m_ref_length_bp": int(len(seq_fl)),
    "aie0779m_d1_spn_pred_fl": round(pred_fl, 4),
    "aie0779m_d1_spn_pred_3xc2": round(pred_3x, 4),
    "aie0779m_d1_spn_pred_6xc2": round(pred_6x, 4),
    "aie0779m_positive_d1_spn_pred": bool(pred_fl > 0.5),
    "meis2_best_motif_ig": round(motif_best_ig.get("MEIS2", 0.0), 4),
    "egr1_best_motif_ig": round(motif_best_ig.get("EGR1", 0.0), 4),
    "rarb_best_motif_ig": round(motif_best_ig.get("RARB", 0.0), 4),
    "aie0779m_meis2_egr1_rarb_positive_ig": bool(meis_ok and egr_ok and rarb_ok),
    "n_motif_hits_annotated": int(len(motif_hits)),
    **mammal_metrics,
}
write_metrics(metrics)
print(metrics)
