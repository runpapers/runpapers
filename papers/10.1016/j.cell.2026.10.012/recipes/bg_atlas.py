"""Shared loader for this pack's recipes: one table with a row per nucleus of the consensus basal ganglia
taxonomy (Johansen et al., Cell 2026), with its donor, species, dissected region and taxonomy labels.

Data files are read from $RP_DATA_DIR (the pack's `data/` folder); outputs go to $RP_OUT_DIR."""
import json
import os
from pathlib import Path

import pandas as pd

SPECIES = ["Human", "Macaque", "Marmoset"]
SPECIES_COLORS = {"Human": "#3182bd", "Macaque": "#4daf4a", "Marmoset": "#e41a1c"}

# Published Figure 1B / Table S2 (display_order_group 1..61) top-to-bottom Group order.
# Note: cluster_annotation_term.csv term_order uses a different internal ordering and is not Figure 1B's order.
PUBLISHED_GROUP_ORDER = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STRv D1 SPN",
    "STRv D2 SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
    "OT ICj Granule",
    "GPe MEIS2-SOX6 GABA",
    "AMY-SLEA-BNST GABA",
    "AMY-SLEA-BNST D1 GABA",
    "IP SEMA5A GABA",
    "IP EBF2 GABA",
    "OB FRMD7 GABA",
    "OB Dopa-GABA",
    "GPi Shell GABA-Glut",
    "GPi Core GABA",
    "SN GATA3-PVALB GABA",
    "GPe SOX6-CTXND1 GABA",
    "ZI-HTH GABA",
    "SN-VTR-HTH GATA3-TCF7L2 GABA",
    "SN GATA3-PAX8 GABA",
    "GPe-NDB-SI LHX6-LHX8-GBX1 GABA",
    "VIP GABA",
    "LAMP5-CXCL14 GABA",
    "STR SST-CHODL GABA",
    "STR SST-RSPO2 GABA",
    "STR LYPD6-RSPO2 GABA",
    "STR SST-ADARB2 GABA",
    "LAMP5-LHX6 GABA",
    "STR FS PTHLH-PVALB GABA",
    "STR TAC3-PLPP4 GABA",
    "STR-BF TAC3-PLPP4-LHX8 GABA",
    "GPin-BF Cholinergic GABA",
    "STR Cholinergic GABA",
    "STRd Cholinergic GABA",
    "SN-VTR GAD2 Dopa",
    "SN SOX6 Dopa",
    "SN-VTR CALB1 Dopa",
    "BF SKOR1 Glut",
    "VTR-HTH Glut",
    "STH PVALB-PITX2 Glut",
    "OPC",
    "COP",
    "ImOligo",
    "Oligo PLEKHG1",
    "Oligo OPALIN",
    "ImAstro",
    "Astrocyte",
    "Ependymal",
    "Microglia",
    "BAM",
    "Monocyte",
    "B cell",
    "T cell",
    "VLMC",
    "SMC",
    "Pericyte",
    "Endo",
]


def data_dir():
    return Path(os.environ.get("RP_DATA_DIR", "data"))


def out_dir():
    p = Path(os.environ.get("RP_OUT_DIR", "out"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def taxonomy():
    """cluster_alias -> Neighborhood, Class, Subclass, Group for the clusters in the consensus taxonomy."""
    mem = pd.read_csv(data_dir() / "cluster_to_cluster_annotation_membership.csv")
    piv = mem.pivot_table(index="cluster_alias", columns="cluster_annotation_term_set_name",
                          values="cluster_annotation_term_name", aggfunc="first").reset_index()
    return piv[piv["Group"].notna()][["cluster_alias", "Neighborhood", "Class", "Subclass", "Group"]]


def group_order():
    """The 61 Groups in published Figure 1B / Table S2 order (STRd D1 Matrix SPN to Endo), with ABC hex colors."""
    t = pd.read_csv(data_dir() / "cluster_annotation_term.csv")
    g = t[t["cluster_annotation_term_set_name"] == "Group"]
    colors = dict(zip(g["name"], g["color_hex_triplet"]))
    if set(PUBLISHED_GROUP_ORDER) != set(colors):
        missing = sorted(set(colors) - set(PUBLISHED_GROUP_ORDER))
        extra = sorted(set(PUBLISHED_GROUP_ORDER) - set(colors))
        raise ValueError(f"PUBLISHED_GROUP_ORDER mismatch: missing={missing}, extra={extra}")
    return list(PUBLISHED_GROUP_ORDER), colors


def region_palette(exclude=("Br",)):
    """Dissected-region labels in ABC value_sets.csv order with their published hex colors."""
    vs = pd.read_csv(data_dir() / "value_sets.csv")
    r = vs[(vs["table"] == "library") & (vs["field"] == "region_of_interest_label")].sort_values("order")
    if exclude:
        r = r[~r["label"].isin(exclude)]
    return list(r["label"]), dict(zip(r["label"], r["color_hex_triplet"]))


def load_cells(extra_cols=()):
    """One row per nucleus: cell_label, donor_label, library_label, cluster_alias, taxonomy levels, species_genus,
    region_of_interest_label. Only nuclei assigned to a consensus-taxonomy cluster are kept (all of them, in this release)."""
    d = data_dir()
    c2c = pd.read_csv(d / "cell_to_cluster_membership.csv", usecols=["cell_label", "cluster_alias"],
                      dtype={"cell_label": "string", "cluster_alias": "string"})
    cm = pd.read_csv(d / "cell_metadata.csv", usecols=["cell_label", "donor_label", "library_label", *extra_cols],
                     dtype={"cell_label": "string", "donor_label": "category", "library_label": "category"})
    cells = cm.merge(c2c, on="cell_label", how="left", validate="one_to_one")
    tax = taxonomy()
    tax["cluster_alias"] = tax["cluster_alias"].astype("string")
    cells = cells.merge(tax, on="cluster_alias", how="inner")
    donors = pd.read_csv(d / "donor.csv")
    cells = cells.merge(donors[["donor_label", "species_genus"]], on="donor_label", how="left", validate="many_to_one")
    libs = pd.read_csv(d / "library.csv")[["library_label", "region_of_interest_label"]].drop_duplicates("library_label")
    cells["library_label"] = cells["library_label"].astype(str)
    cells = cells.merge(libs, on="library_label", how="left", validate="many_to_one")
    for c in ("Group", "Subclass", "Class", "Neighborhood", "species_genus", "region_of_interest_label", "donor_label"):
        cells[c] = cells[c].astype("category")
    return cells, donors


def write_metrics(metrics):
    clean = {k: (v.item() if hasattr(v, "item") else v) for k, v in metrics.items()}
    (out_dir() / "metrics.json").write_text(json.dumps(clean, indent=1, sort_keys=True) + "\n")
