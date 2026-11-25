# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8"]
# ///
"""Figure 3E: Four-species spatial localization of OB Dopa-GABA and OB FRMD7 GABA Groups
across Human MERSCOPE, Macaque MERSCOPE, Marmoset Xenium, and Mouse MERFISH (striatal
section plus Mouse Olfactory Bulb inset).

Demonstrates conserved peri-striatal distribution across the three primates contrasted with
extreme rarity in mouse peri-striatal regions and strong enrichment in the mouse olfactory bulb.
"""
import gc

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from bg_spatial import data_dir, load_primate_spatial, out_dir, write_metrics

OB_PRIMATE_COLORS = {
    "OB FRMD7 GABA": "#3b73b9",
    "OB Dopa-GABA": "#b84094",
}

OB_MOUSE_SUBCLASSES = [
    ("044 OB Dopa-Gaba", "OB Dopa-GABA", "#b84094"),
    ("042 OB-out Frmd7 Gaba", "OB-out FRMD7 GABA", "#2c3e99"),
    ("041 OB-in Frmd7 Gaba", "OB-in FRMD7 GABA", "#4b86c5"),
    ("043 OB-mi Frmd7 Gaba", "OB-mi FRMD7 GABA", "#9ecae1"),
]

summary_rows = []
primate_panels = {}

for sp_name, prefix in [
    ("Human", "human_merscope"),
    ("Macaque", "macaque_merscope"),
    ("Marmoset", "marmoset_xenium"),
]:
    df = load_primate_spatial(prefix)
    ob = df[df["Group"].isin(["OB Dopa-GABA", "OB FRMD7 GABA"])].copy()
    n_tot = int(len(df))
    n_dopa = int((ob["Group"] == "OB Dopa-GABA").sum())
    n_frmd7 = int((ob["Group"] == "OB FRMD7 GABA").sum())
    n_str = int((ob["parcellation_term_symbol"] == "STR").sum())
    n_adj = int((ob["parcellation_term_symbol"] == "Basal ganglia and adjacent").sum())

    # Pick coronal slab plane with richest representation of both OB Groups and major striatal coverage
    tab = ob.groupby(["slab_plane_label", "Group"]).size().unstack(fill_value=0)
    for col in ("OB Dopa-GABA", "OB FRMD7 GABA"):
        if col not in tab.columns:
            tab[col] = 0
    tab["tot"] = tab["OB Dopa-GABA"] + tab["OB FRMD7 GABA"]
    str_per_slab = df[df["STR"] == True].groupby("slab_plane_label").size()
    tab["str_cells"] = tab.index.map(str_per_slab).fillna(0)
    # Prefer full striatal coronal planes (top half of striatal area) containing both OB Groups
    both_ok = tab[(tab["OB Dopa-GABA"] >= 5) & (tab["OB FRMD7 GABA"] >= 5)]
    str_ok = both_ok[both_ok["str_cells"] >= both_ok["str_cells"].median()] if len(both_ok) else both_ok
    cand = str_ok if len(str_ok) else (both_ok if len(both_ok) else tab)
    best_slab = str(cand.sort_values("tot", ascending=False).index[0])

    sec = df[(df["slab_plane_label"] == best_slab) & df["x_slab_mm"].notna() & df["y_slab_mm"].notna()].copy()
    # Downsample background cells deterministically to keep PNG rendering crisp and fast
    rng = np.random.default_rng(0)
    if len(sec) > 120000:
        bg_idx = rng.choice(len(sec), size=120000, replace=False)
        bg = sec.iloc[bg_idx][["x_slab_mm", "y_slab_mm", "STR"]].copy()
    else:
        bg = sec[["x_slab_mm", "y_slab_mm", "STR"]].copy()
    sec_ob = sec[sec["Group"].isin(["OB Dopa-GABA", "OB FRMD7 GABA"])][["x_slab_mm", "y_slab_mm", "Group"]].copy()

    primate_panels[sp_name] = {"slab": best_slab, "bg": bg, "ob": sec_ob}
    summary_rows.append(
        {
            "species": sp_name,
            "total_cells": n_tot,
            "ob_dopa_gaba": n_dopa,
            "ob_frmd7_gaba": n_frmd7,
            "ob_total": n_dopa + n_frmd7,
            "ob_pct_of_total": round(100.0 * (n_dopa + n_frmd7) / max(n_tot, 1), 4),
            "ob_in_str_or_adjacent_pct": round(100.0 * (n_str + n_adj) / max(n_dopa + n_frmd7, 1), 2),
            "plotted_section": best_slab,
        }
    )
    del df, ob, sec
    gc.collect()

# Mouse MERFISH
m_df = pd.read_csv(
    data_dir() / "mouse_merfish_cell_metadata.csv",
    usecols=["brain_section_label", "x", "y", "subclass"],
    low_memory=False,
)
mouse_ob_keys = [k for k, _, _ in OB_MOUSE_SUBCLASSES]
m_ob = m_df[m_df["subclass"].isin(mouse_ob_keys)].copy()

# Identify striatal sections (>= 2,000 STR D1/D2 SPNs) vs olfactory bulb sections (>= 2,000 OB homologous cells)
spn_per_sec = m_df[m_df["subclass"].isin(["061 STR D1 Gaba", "062 STR D2 Gaba"])].groupby("brain_section_label").size()
str_secs = set(spn_per_sec[spn_per_sec >= 2000].index)
ob_per_sec = m_ob.groupby("brain_section_label").size()
ob_secs = set(ob_per_sec[ob_per_sec >= 2000].index)

m_ob_in_str = m_ob[m_ob["brain_section_label"].isin(str_secs)]
m_ob_in_ob = m_ob[m_ob["brain_section_label"].isin(ob_secs)]
n_mouse_ob_total = int(len(m_ob))
n_mouse_ob_str = int(len(m_ob_in_str))
n_mouse_ob_bulb = int(len(m_ob_in_ob))
mouse_ob_pct_str = 100.0 * n_mouse_ob_str / max(n_mouse_ob_total, 1)

# Density fold enrichment: mean OB-homologous fraction in OB sections vs STR sections
tot_in_str_secs = int(m_df["brain_section_label"].isin(str_secs).sum())
tot_in_ob_secs = int(m_df["brain_section_label"].isin(ob_secs).sum())
frac_in_str = n_mouse_ob_str / max(tot_in_str_secs, 1)
frac_in_ob = n_mouse_ob_bulb / max(tot_in_ob_secs, 1)
mouse_ob_vs_str_fc = frac_in_ob / max(frac_in_str, 1e-12)

# Choose anterior striatal section (with >= 5000 SPNs and sparse peri-striatal OB cells) and peak OB section
str_rich_secs = spn_per_sec[spn_per_sec >= 5000].index
str_ob_counts = m_ob_in_str[m_ob_in_str["brain_section_label"].isin(str_rich_secs)].groupby("brain_section_label").size()
best_mouse_str_sec = str(str_ob_counts.sort_values(ascending=False).index[0])
best_mouse_ob_sec = str(ob_per_sec.sort_values(ascending=False).index[0])

summary_rows.append(
    {
        "species": "Mouse",
        "total_cells": int(len(m_df)),
        "ob_dopa_gaba": int((m_ob["subclass"] == "044 OB Dopa-Gaba").sum()),
        "ob_frmd7_gaba": int(m_ob["subclass"].isin(["041 OB-in Frmd7 Gaba", "042 OB-out Frmd7 Gaba", "043 OB-mi Frmd7 Gaba"]).sum()),
        "ob_total": n_mouse_ob_total,
        "ob_pct_of_total": round(100.0 * n_mouse_ob_total / max(len(m_df), 1), 4),
        "ob_in_str_or_adjacent_pct": round(mouse_ob_pct_str, 2),
        "plotted_section": f"{best_mouse_str_sec} (STR) + {best_mouse_ob_sec} (OB inset)",
    }
)
pd.DataFrame(summary_rows).to_csv(out_dir() / "fig3e_4species_ob_summary.csv", index=False)

# ---- Render 2x2 four-species Figure 3E matching Cell VoR layout ----
fig, axes = plt.subplots(2, 2, figsize=(11.8, 11.2), dpi=200)
panel_order = [("Human", axes[0, 0]), ("Macaque", axes[0, 1]), ("Marmoset", axes[1, 0])]

for sp_name, ax in panel_order:
    p = primate_panels[sp_name]
    bg = p["bg"]
    ob_pts = p["ob"]
    ax.scatter(bg["x_slab_mm"], -bg["y_slab_mm"], s=0.14, c="#ebebeb", alpha=0.65, linewidths=0, rasterized=True)
    bg_str = bg[bg["STR"] == True]
    ax.scatter(bg_str["x_slab_mm"], -bg_str["y_slab_mm"], s=0.18, c="#dfe6ee", alpha=0.55, linewidths=0, rasterized=True)
    for grp, col in [("OB FRMD7 GABA", OB_PRIMATE_COLORS["OB FRMD7 GABA"]), ("OB Dopa-GABA", OB_PRIMATE_COLORS["OB Dopa-GABA"])]:
        sub = ob_pts[ob_pts["Group"] == grp]
        ax.scatter(
            sub["x_slab_mm"],
            -sub["y_slab_mm"],
            s=4.5 if sp_name != "Marmoset" else 7.5,
            c=col,
            alpha=0.92,
            linewidths=0,
            label=f"{grp} (n={len(sub):,})",
            zorder=4,
        )
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"{sp_name} ({p['slab']})", fontsize=10, fontweight="bold", pad=4)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=2, frameon=False, fontsize=7.8, markerscale=1.8)

# Bottom-right: Mouse MERFISH striatal hemisphere + OB inset
ax_m = axes[1, 1]
msec_all = m_df[m_df["brain_section_label"] == best_mouse_str_sec]
x_mid = float(msec_all["x"].median())
mh_all = msec_all[msec_all["x"] >= x_mid]
mh_str = mh_all[mh_all["subclass"].isin(["061 STR D1 Gaba", "062 STR D2 Gaba"])]
mh_ob = mh_all[mh_all["subclass"].isin(mouse_ob_keys)]

ax_m.scatter(mh_all["x"], -mh_all["y"], s=0.22, c="#ececec", linewidths=0, rasterized=True)
ax_m.scatter(mh_str["x"], -mh_str["y"], s=0.30, c="#e0e0d4", linewidths=0, rasterized=True)
for sc_key, sc_lbl, col in OB_MOUSE_SUBCLASSES:
    sub = mh_ob[mh_ob["subclass"] == sc_key]
    ax_m.scatter(sub["x"], -sub["y"], s=9.0, c=col, alpha=0.95, linewidths=0, label=sc_lbl, zorder=4)

# Expand x-axis on right to accommodate Mouse OB inset cleanly
xr = float(mh_all["x"].max() - mh_all["x"].min())
ax_m.set_xlim(float(mh_all["x"].min()) - 0.3, float(mh_all["x"].max()) + 0.65 * xr)
ax_m.set_aspect("equal")
ax_m.axis("off")
ax_m.set_title(
    f"Mouse STR ({best_mouse_str_sec}) & OB inset ({best_mouse_ob_sec})\n"
    f"STR sections: {mouse_ob_pct_str:.2f}% of OB cells ({mouse_ob_vs_str_fc:.0f}x enriched in OB)",
    fontsize=9.2,
    fontweight="bold",
    pad=4,
)
ax_m.legend(loc="lower right", frameon=False, fontsize=7.5, markerscale=1.6)

# Mouse Olfactory Bulb inset (right bulb hemisphere)
ins = ax_m.inset_axes([0.62, 0.24, 0.36, 0.42])
mob_sec = m_df[m_df["brain_section_label"] == best_mouse_ob_sec]
mob_xmid = float(mob_sec["x"].median())
mob_hemi = mob_sec[mob_sec["x"] >= mob_xmid]
ins.scatter(mob_hemi["x"], -mob_hemi["y"], s=0.15, c="#f0f0f0", linewidths=0, rasterized=True)
for sc_key, _, col in [
    ("041 OB-in Frmd7 Gaba", "", "#4b86c5"),
    ("043 OB-mi Frmd7 Gaba", "", "#9ecae1"),
    ("042 OB-out Frmd7 Gaba", "", "#2c3e99"),
    ("044 OB Dopa-Gaba", "", "#b84094"),
]:
    sub = mob_hemi[mob_hemi["subclass"] == sc_key]
    ins.scatter(sub["x"], -sub["y"], s=0.45, c=col, alpha=0.88, linewidths=0, rasterized=True)
ins.set_aspect("equal")
ins.axis("off")
ins.set_title("Mouse OB inset", fontsize=8, pad=2)

fig.suptitle("Peri-striatal distribution of OB Groups across primates vs. mouse olfactory bulb (Figure 3E)", fontsize=11, y=0.98)
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(out_dir() / "fig3e.png", dpi=200)
plt.close(fig)

row_by_sp = {r["species"]: r for r in summary_rows}
metrics = {
    "n_species_plotted": 4,
    "human_ob_dopa": int(row_by_sp["Human"]["ob_dopa_gaba"]),
    "human_ob_frmd7": int(row_by_sp["Human"]["ob_frmd7_gaba"]),
    "macaque_ob_dopa": int(row_by_sp["Macaque"]["ob_dopa_gaba"]),
    "macaque_ob_frmd7": int(row_by_sp["Macaque"]["ob_frmd7_gaba"]),
    "marmoset_ob_dopa": int(row_by_sp["Marmoset"]["ob_dopa_gaba"]),
    "marmoset_ob_frmd7": int(row_by_sp["Marmoset"]["ob_frmd7_gaba"]),
    "ob_groups_present_in_all_three_primates": bool(
        all(row_by_sp[s]["ob_dopa_gaba"] > 0 and row_by_sp[s]["ob_frmd7_gaba"] > 0 for s in ("Human", "Macaque", "Marmoset"))
    ),
    "mouse_ob_total_cells": n_mouse_ob_total,
    "mouse_ob_cells_in_striatal_sections": n_mouse_ob_str,
    "mouse_ob_pct_in_striatal_sections": round(mouse_ob_pct_str, 4),
    "mouse_ob_pct_in_striatal_sections_lt_5": bool(mouse_ob_pct_str < 5.0),
    "mouse_ob_vs_str_density_fold_enrichment": round(mouse_ob_vs_str_fc, 2),
    "mouse_ob_strongly_enriched_in_ob_over_striatum": bool(mouse_ob_vs_str_fc > 10.0),
}
write_metrics(metrics)
print(metrics)
