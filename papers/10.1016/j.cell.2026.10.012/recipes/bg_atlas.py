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

# Nine spiny projection neuron (SPN) Groups in published Figure 2E order.
SPN_GROUPS = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRv D1 SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STRv D2 SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
]

# Published Figure 1A anterior-to-posterior anatomical region order (Human & Macaque).
# In the ABC 20261031 release, GPeR/GPeC are pooled under GPe and SN-VTA is labeled VTA; Marmoset slabs are 'Br'.
PUBLISHED_REGION_ORDER = [
    "Ca", "CaH", "CaB", "CaT",
    "Pu", "PuR", "PuC", "PuPV",
    "NAC", "NACs", "NACc",
    "GP", "GPe", "GPi",
    "VeP", "Eca", "STH", "SN", "VTA",
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


def group_taxonomy_map():
    """Group -> dict with Neighborhood, Class, Subclass derived directly from the release taxonomy."""
    tax = taxonomy()
    g = tax[["Group", "Neighborhood", "Class", "Subclass"]].drop_duplicates("Group").set_index("Group")
    return g


def group_order():
    """The 61 Groups in published Figure 1B / Table S2 order (STRd D1 Matrix SPN to Endo), with release hex colors."""
    t = pd.read_csv(data_dir() / "cluster_annotation_term.csv")
    g = t[t["cluster_annotation_term_set_name"] == "Group"]
    colors = dict(zip(g["name"], g["color_hex_triplet"]))
    if set(PUBLISHED_GROUP_ORDER) != set(colors):
        missing = sorted(set(colors) - set(PUBLISHED_GROUP_ORDER))
        extra = sorted(set(PUBLISHED_GROUP_ORDER) - set(colors))
        raise ValueError(f"PUBLISHED_GROUP_ORDER mismatch: missing={missing}, extra={extra}")
    return list(PUBLISHED_GROUP_ORDER), colors


def group_id_to_name():
    """Map stable taxonomy accession IDs (CS20250428_GROUP_xxxx) to current Cell 2026 Group names."""
    t = pd.read_csv(data_dir() / "cluster_annotation_term.csv")
    g = t[t["cluster_annotation_term_set_name"] == "Group"]
    return dict(zip(g["label"], g["name"]))


def region_palette(exclude=("Br",)):
    """Dissected-region labels in ABC value_sets.csv order with their release-palette hex colors."""
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


def load_pseudobulk_log2(chunk_size=50000):
    """Return donor-by-Group and Species-by-Group log2(CPM+1) expression summaries across all 61 Groups
    and 16,630 1:1 primate orthologs.

    Reads HMBA-10xMultiome-BG-Cross-Species-log2.h5ad from $RP_DATA_DIR in streaming chunks (low RAM).
    If the optional read-only environment variable RP_PSEUDOBULK_CACHE points to a precomputed AnnData
    pseudobulk file (with layers 'sum' and 'n_expressing' and obs columns Species/Donor/Group/n_cells),
    it is loaded directly to avoid redundant streaming across recipes."""
    import anndata as ad
    import numpy as np
    import scipy.sparse as sp

    order, _ = group_order()
    cache_path = os.environ.get("RP_PSEUDOBULK_CACHE", "").strip()
    if cache_path and Path(cache_path).is_file():
        pb = ad.read_h5ad(cache_path)
        sdg_meta = pb.obs.reset_index(drop=True).copy()
        sdg_sum = np.asarray(pb.layers["sum"], dtype=np.float64)
        sdg_nz = np.asarray(pb.layers["n_expressing"], dtype=np.int64)
        sdg_cnt = sdg_meta["n_cells"].values.astype(np.int64)
        var_names = pb.var_names.astype(str).values
    else:
        cells, _ = load_cells()
        adata = ad.read_h5ad(data_dir() / "HMBA-10xMultiome-BG-Cross-Species-log2.h5ad", backed="r")
        var_names = (
            adata.var["gene_symbol"].astype(str).values
            if "gene_symbol" in adata.var.columns
            else adata.var_names.astype(str).values
        )
        n_cells, n_genes = adata.shape
        meta_idx = cells.set_index("cell_label").reindex(adata.obs_names)
        sp_arr = meta_idx["species_genus"].astype(str).values
        dn_arr = meta_idx["donor_label"].astype(str).values
        gp_arr = meta_idx["Group"].astype(str).values

        keys = pd.Series(sp_arr) + "||" + pd.Series(dn_arr) + "||" + pd.Series(gp_arr)
        sdg_codes, sdg_uniques = pd.factorize(keys)
        n_sdg = len(sdg_uniques)
        sdg_sum = np.zeros((n_sdg, n_genes), dtype=np.float64)
        sdg_nz = np.zeros((n_sdg, n_genes), dtype=np.int64)
        sdg_cnt = np.bincount(sdg_codes, minlength=n_sdg)

        for start in range(0, n_cells, chunk_size):
            end = min(start + chunk_size, n_cells)
            x_sub = adata.X[start:end]
            x_sub = x_sub.tocsr() if sp.issparse(x_sub) else sp.csr_matrix(x_sub)
            c_sub = sdg_codes[start:end]
            m_ind = sp.csr_matrix(
                (np.ones(end - start, dtype=np.float64), (c_sub, np.arange(end - start))),
                shape=(n_sdg, end - start),
            )
            sdg_sum += (m_ind @ x_sub).toarray()
            x_bin = x_sub.copy()
            x_bin.data = np.ones_like(x_bin.data)
            sdg_nz += (m_ind @ x_bin).toarray().astype(np.int64)
        adata.file.close()
        sdg_meta = pd.DataFrame([u.split("||") for u in sdg_uniques], columns=["Species", "Donor", "Group"])
        sdg_meta["n_cells"] = sdg_cnt

    sp_group_mean = {}
    sp_group_pct = {}
    for sp_name in SPECIES:
        mask = (sdg_meta["Species"] == sp_name).values
        sub_meta = sdg_meta.loc[mask]
        g_means = pd.DataFrame(0.0, index=order, columns=var_names, dtype=np.float64)
        g_pcts = pd.DataFrame(0.0, index=order, columns=var_names, dtype=np.float64)
        for grp, idx_df in sub_meta.groupby("Group"):
            if grp not in g_means.index:
                continue
            rows = idx_df.index.values
            tot = sdg_cnt[rows].sum()
            if tot > 0:
                g_means.loc[grp] = sdg_sum[rows].sum(axis=0) / tot
                g_pcts.loc[grp] = sdg_nz[rows].sum(axis=0) / tot
        sp_group_mean[sp_name] = g_means
        sp_group_pct[sp_name] = g_pcts

    return {
        "var_names": var_names,
        "sdg_meta": sdg_meta,
        "sdg_sum": sdg_sum,
        "sdg_nz": sdg_nz,
        "sdg_cnt": sdg_cnt,
        "sp_group_mean": sp_group_mean,
        "sp_group_pct": sp_group_pct,
    }


def compute_expressolog_auroc(sp_group_mean, var_names):
    """Compute cross-species Expressolog AUROC across all 61 Groups (missing species-Groups zero-filled)."""
    import numpy as np

    pairs = [("Human", "Macaque"), ("Human", "Marmoset"), ("Macaque", "Marmoset")]
    pair_cors = {}
    for s1, s2 in pairs:
        m1 = sp_group_mean[s1].values
        m2 = sp_group_mean[s2].values
        m1c = m1 - m1.mean(axis=0, keepdims=True)
        m2c = m2 - m2.mean(axis=0, keepdims=True)
        denom = np.sqrt((m1c ** 2).sum(axis=0) * (m2c ** 2).sum(axis=0))
        cor = np.where(denom > 0, (m1c * m2c).sum(axis=0) / np.where(denom > 0, denom, 1.0), np.nan)
        pair_cors[f"{s1}_{s2}"] = cor
    cor_df = pd.DataFrame(pair_cors, index=var_names)
    cor_df["median_cor"] = cor_df.median(axis=1, skipna=True)
    valid = cor_df["median_cor"].notna()
    ranks = cor_df.loc[valid, "median_cor"].rank(method="average")
    cor_df["auroc"] = np.nan
    cor_df.loc[valid, "auroc"] = (ranks - 1.0) / (valid.sum() - 1.0)
    return cor_df

