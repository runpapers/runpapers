# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.2", "numpy>=1.26", "matplotlib>=3.8"]
# ///
"""Figure 2F: for each donor, the share of its classical D2 spiny projection neurons (SPNs) in each of the four
D2 Groups, by species. The STR D2 SMYD2-HTR7 SPN Group (preprint name: StrioMat hybrid) is the rarest everywhere.

As in the published panel: every donor with at least one D2 SPN nucleus is plotted (one human donor, H19.30.004,
was dissected from the subthalamic nucleus only and contributes a single STRv D2 SPN nucleus: the dot at 1.0)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from bg_atlas import SPECIES, SPECIES_COLORS, load_cells, out_dir, write_metrics

D2 = ["STRv D2 SPN", "STRd D2 Striosome SPN", "STRd D2 Matrix SPN", "STR D2 SMYD2-HTR7 SPN"]
SLUG = {"STRv D2 SPN": "strv", "STRd D2 Striosome SPN": "striosome", "STRd D2 Matrix SPN": "matrix", "STR D2 SMYD2-HTR7 SPN": "smyd2"}
SPN = D2 + ["STRd D1 Matrix SPN", "STRd D1 Striosome SPN", "STRv D1 SPN", "STR D1D2 eSPN", "STRv D1 NUDAP eSPN"]

cells, _ = load_cells()
d2 = cells[cells["Group"].isin(D2)]
spn = cells[cells["Group"].isin(SPN)]
smyd = "STR D2 SMYD2-HTR7 SPN"

m = {"smyd2_pct_of_d2_pooled": round(100 * (d2["Group"] == smyd).sum() / len(d2), 4),
     "smyd2_pct_of_spn_pooled": round(100 * (spn["Group"] == smyd).sum() / len(spn), 4)}
for sp in SPECIES:
    k = sp.lower()
    s = d2[d2["species_genus"] == sp]
    m[f"n_smyd2_{k}"] = int((s["Group"] == smyd).sum())
    m[f"smyd2_pct_of_d2_pooled_{k}"] = round(100 * (s["Group"] == smyd).sum() / len(s), 4)

# Per-donor proportions (donors with >= 1 D2 SPN nucleus)
tab = d2.groupby(["donor_label", "Group"], observed=True).size().unstack(fill_value=0).reindex(columns=D2, fill_value=0)
sp_of = cells.drop_duplicates("donor_label").set_index("donor_label")["species_genus"].astype(str)
tab = tab[tab.sum(axis=1) > 0]
prop = tab.div(tab.sum(axis=1), axis=0)
prop["species"] = sp_of.reindex(prop.index).values
prop.to_csv(out_dir() / "donor_d2_proportions.csv")
m["n_donors_plotted"] = int(len(prop))
lowest, highest = [], []
for sp in SPECIES:
    ps = prop[prop["species"] == sp]
    m[f"n_donors_plotted_{sp.lower()}"] = int(len(ps))
    med = {g: float(np.median(ps[g])) for g in D2}
    for g in D2:
        m[f"median_pct_{SLUG[g]}_{sp.lower()}"] = round(100 * med[g], 2)
    lowest.append(min(med, key=med.get) == smyd)
    highest.append(max(med, key=med.get) == "STRd D2 Matrix SPN")
m["smyd2_lowest_median_in_all_species"] = all(lowest)
m["matrix_highest_median_in_all_species"] = all(highest)

# Plot: boxes of donor proportions, dots per donor, grouped by D2 Group and species
fig, ax = plt.subplots(figsize=(8, 4.2))
rng = np.random.default_rng(0)
width = 0.25
for i, g in enumerate(D2):
    for j, sp in enumerate(SPECIES):
        vals = prop.loc[prop["species"] == sp, g].values
        x = i + (j - 1) * width
        ax.boxplot(vals, positions=[x], widths=width * 0.8, showfliers=False, patch_artist=True,
                   boxprops=dict(facecolor="white", edgecolor=SPECIES_COLORS[sp]), medianprops=dict(color=SPECIES_COLORS[sp]),
                   whiskerprops=dict(color=SPECIES_COLORS[sp]), capprops=dict(color=SPECIES_COLORS[sp]))
        ax.scatter(x + rng.uniform(-width * 0.25, width * 0.25, len(vals)), vals, s=9, color=SPECIES_COLORS[sp], zorder=3,
                   label=sp if i == 0 else None)
ax.set_xticks(range(len(D2)))
ax.set_xticklabels([g.replace(" SPN", "\nSPN") for g in D2], fontsize=8)
ax.set_ylabel("Proportion of donor's classical D2 SPNs")
ax.set_ylim(-0.02, 1.02)
ax.set_title(f"STR D2 SMYD2-HTR7 SPN: {m['smyd2_pct_of_d2_pooled']:.2f}% of classical D2 SPNs (pooled)", fontsize=9)
ax.legend(fontsize=8, frameon=False)
fig.tight_layout()
fig.savefig(out_dir() / "fig2f.png", dpi=150)
write_metrics(m)
print(m)
