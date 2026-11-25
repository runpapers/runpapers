# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8"]
# ///
"""Figure 3C: Mouse MERFISH coronal striatal spatial distribution of STR D2 SMYD2-HTR7 SPN
homologous mouse supertypes:
  - 0279 STR D2 Gaba_6 (broadly distributed across dorsal and ventral striatum)
  - 0276 STR D2 Gaba_3 (ventrally enriched)

Computes brain-wide cell counts and two-sided Mann-Whitney U test on CCF dorsal-ventral
coordinate y (larger y = more ventral), and renders a single-hemisphere coronal striatal
section matching published Figure 3C.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from bg_spatial import data_dir, out_dir, write_metrics

m_df = pd.read_csv(
    data_dir() / "mouse_merfish_cell_metadata.csv",
    usecols=["brain_section_label", "x", "y", "z", "supertype", "subclass"],
    low_memory=False,
)

m_279 = m_df[m_df["supertype"] == "0279 STR D2 Gaba_6"].copy()
m_276 = m_df[m_df["supertype"] == "0276 STR D2 Gaba_3"].copy()

mw_stat, mw_p = stats.mannwhitneyu(m_279["y"].values, m_276["y"].values, alternative="two-sided")
med_y_279 = float(m_279["y"].median())
med_y_276 = float(m_276["y"].median())

# Per-section tally table
sec_279 = m_279.groupby("brain_section_label").size().rename("n_0279")
sec_276 = m_276.groupby("brain_section_label").size().rename("n_0276")
sec_tab = pd.concat([sec_279, sec_276], axis=1).fillna(0).astype(int)
sec_tab["geom_mean"] = np.sqrt(sec_tab["n_0279"] * sec_tab["n_0276"])
sec_tab = sec_tab.sort_values("geom_mean", ascending=False)
sec_tab.to_csv(out_dir() / "fig3c_mouse_merfish_0279_0276.csv")

# Select coronal section with best joint representation of both 0279 and 0276
best_sec = str(sec_tab.index[0])
sec_all = m_df[m_df["brain_section_label"] == best_sec]
x_mid = float(sec_all["x"].median())

# Right hemisphere (x >= x_mid), dorsal UP (-y), matching published Figure 3C orientation
hemi_all = sec_all[sec_all["x"] >= x_mid]
hemi_str = hemi_all[hemi_all["subclass"].isin(["061 STR D1 Gaba", "062 STR D2 Gaba"])]
hemi_279 = m_279[(m_279["brain_section_label"] == best_sec) & (m_279["x"] >= x_mid)]
hemi_276 = m_276[(m_276["brain_section_label"] == best_sec) & (m_276["x"] >= x_mid)]

fig, ax = plt.subplots(figsize=(5.6, 5.8), dpi=200)
ax.scatter(hemi_all["x"], -hemi_all["y"], s=0.35, c="#ececec", linewidths=0, rasterized=True)
ax.scatter(hemi_str["x"], -hemi_str["y"], s=0.45, c="#dddddd", linewidths=0, rasterized=True)
ax.scatter(
    hemi_279["x"],
    -hemi_279["y"],
    s=18,
    c="#9c7b3e",
    edgecolors="none",
    alpha=0.92,
    label=f"0279 STR D2 Gaba_6 (all n={len(m_279):,})",
    zorder=3,
)
ax.scatter(
    hemi_276["x"],
    -hemi_276["y"],
    s=18,
    c="#4c7c3b",
    edgecolors="none",
    alpha=0.95,
    label=f"0276 STR D2 Gaba_3 (all n={len(m_276):,})",
    zorder=4,
)
ax.set_aspect("equal")
ax.axis("off")
ax.legend(loc="lower right", frameon=False, fontsize=8.5, markerscale=1.4)
ax.set_title(
    f"Mouse MERFISH ({best_sec}, right hemisphere)\n"
    f"Ventral shift (CCF y): 0276 med={med_y_276:.2f} vs 0279 med={med_y_279:.2f}, p={mw_p:.1e}",
    fontsize=8.5,
)
fig.tight_layout()
fig.savefig(out_dir() / "fig3c.png", dpi=200)
plt.close(fig)

metrics = {
    "section_plotted": best_sec,
    "n_0279_total": int(len(m_279)),
    "n_0276_total": int(len(m_276)),
    "n_0279_section_hemi": int(len(hemi_279)),
    "n_0276_section_hemi": int(len(hemi_276)),
    "median_y_0279": round(med_y_279, 4),
    "median_y_0276": round(med_y_276, 4),
    "mannwhitney_u_stat": float(mw_stat),
    "mannwhitney_y_p": float(mw_p),
    "gaba6_0279_more_abundant_than_gaba3_0276": bool(len(m_279) > len(m_276)),
    "gaba3_0276_more_ventral_than_gaba6_0279": bool(med_y_276 > med_y_279),
    "dv_mannwhitney_p_lt_1e10": bool(mw_p < 1e-10),
}
write_metrics(metrics)
print(metrics)
