"""Shared helpers for spatial transcriptomics and primate-mouse homology recipes
(Figures 1E, 3A, 3B, 3C, 3E, and 6D of Johansen et al., Cell 2026).

All data files are read from $RP_DATA_DIR and all outputs are written to $RP_OUT_DIR.
"""
import gc
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

# Exact 44 neuronal Groups in published Figure 1B / Table S2 order (bottom-to-top in Figure 3A).
NEURONAL_GROUP_ORDER = [
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
]

ALL_GROUP_ORDER = NEURONAL_GROUP_ORDER + [
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

# Exact 7 classical SPN Groups highlighted in Figure 3B (bottom-to-top).
CLASSICAL_SPN_GROUPS = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STRv D1 SPN",
    "STRv D2 SPN",
    "STR D2 SMYD2-HTR7 SPN",
]

ALL_9_SPN_GROUPS = CLASSICAL_SPN_GROUPS + [
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
]

# Exact 14 mouse SPN supertypes on the x-axis of published Figure 3B (left-to-right).
FIG3B_MOUSE_SPN_SUPERTYPES = [
    "0267 STR D1 Gaba_3",
    "0268 STR D1 Gaba_4",
    "0277 STR D2 Gaba_4",
    "0272 STR D1 Gaba_8",
    "0270 STR D1 Gaba_6",
    "0265 STR D1 Gaba_1",
    "0271 STR D1 Gaba_7",
    "0269 STR D1 Gaba_5",
    "0273 STR D1 Gaba_9",
    "0274 STR D2 Gaba_1",
    "0275 STR D2 Gaba_2",
    "0278 STR D2 Gaba_5",
    "0279 STR D2 Gaba_6",
    "0276 STR D2 Gaba_3",
]

# Exact 57 conserved Group marker genes on the x-axis of published Figure 3A (left-to-right).
FIG3A_MARKER_GENES = [
    "DRD1", "EBF1", "DRD2", "ADORA2A", "BACH2", "GRIK3", "FOXP2", "CASZ1", "TSHZ1", "DRD3",
    "MEIS2", "SOX6", "ZFHX3", "PCDH11X", "ARHGAP6", "SEMA5A", "EBF2", "FRMD7", "SCGN", "SP8",
    "ETV1", "MEIS1", "LUZP2", "PVALB", "GATA3", "CPNE4", "PAX6", "ISL1", "ZFHX4", "TCF7L2",
    "PAX5", "GBX1", "CNTN5", "VIP", "LAMP5", "CHODL", "LHX6", "RSPO2", "ADARB2", "CRABP1",
    "PTHLH", "TAC3", "LHX8", "CHAT", "SPHKAP", "MEGF10", "TRPC3", "TH", "DDC", "SLC18A2",
    "GAD2", "NTNG1", "PITX3", "CALB1", "SKOR1", "SLC17A6", "PITX2",
]

# Published Group colors for SPN panels (Figures 1E, 3B, 6D).
SPN_GROUP_COLORS = {
    "STRd D1 Matrix SPN": "#1f77b4",
    "STRd D2 Matrix SPN": "#9ecae1",
    "STRd D1 Striosome SPN": "#d62728",
    "STRd D2 Striosome SPN": "#f29b9b",
    "STRv D1 SPN": "#318a43",
    "STRv D2 SPN": "#9bd496",
    "STR D2 SMYD2-HTR7 SPN": "#5e3c99",
    "STR D1D2 eSPN": "#9e9ac8",
    "STRv D1 NUDAP eSPN": "#c5b0d5",
}

# Curated primate Group -> mouse WMB homology from Table S12 (Johansen et al., Cell 2026):
# (curated_ABC_WMB_subclass_tokens, curated_ABC_WMB_supertype_tokens) for concordance checking.
TABLE_S12_CURATED_MOUSE = {
    "STRd D1 Matrix SPN": (["STR D1 Gaba"], ["0267 STR D1 Gaba_3"]),
    "STRd D1 Striosome SPN": (["STR D1 Gaba"], ["0268 STR D1 Gaba_4"]),
    "STRd D2 Matrix SPN": (["STR D2 Gaba"], ["0277 STR D2 Gaba_4"]),
    "STRd D2 Striosome SPN": (["STR D2 Gaba"], ["0277 STR D2 Gaba_4"]),
    "STRv D1 SPN": (["STR D1 Gaba"], ["0271 STR D1 Gaba_7", "0272 STR D1 Gaba_8"]),
    "STRv D2 SPN": (["STR D2 Gaba"], ["0274 STR D2 Gaba_1", "0275 STR D2 Gaba_2"]),
    "STR D2 SMYD2-HTR7 SPN": (["STR D2 Gaba"], ["0279 STR D2 Gaba_6", "0276 STR D2 Gaba_3"]),
    "STR D1D2 eSPN": (["STR D1 Sema5a Gaba"], ["0281 STR D1 Sema5a Gaba_1", "0282 STR D1 Sema5a Gaba_2", "0283 STR D1 Sema5a Gaba_3", "0284 STR D1 Sema5a Gaba_4"]),
    "STRv D1 NUDAP eSPN": (["STR-PAL Chst9 Gaba", "STR D1 Sema5a Gaba"], ["0285 STR-PAL Chst9 Gaba_1", "0286 STR-PAL Chst9 Gaba_2", "0287 STR-PAL Chst9 Gaba_3", "0288 STR-PAL Chst9 Gaba_4"]),
    "OT ICj Granule": (["OT D3 Folh1 Gaba"], ["0262 OT D3 Folh1 Gaba_1", "0263 OT D3 Folh1 Gaba_2", "0264 OT D3 Folh1 Gaba_3"]),
    "GPe MEIS2-SOX6 GABA": (["GPe-SI Sox6 Cyp26b1 Gaba"], ["0257 GPe-SI Sox6 Cyp26b1 Gaba_1"]),
    "AMY-SLEA-BNST GABA": (["CEA-BST Ebf1 Pdyn Gaba"], ["0384 CEA-BST Ebf1 Pdyn Gaba_1"]),
    "AMY-SLEA-BNST D1 GABA": (["ACB-BST-FS D1 Gaba"], ["0382 ACB-BST-FS D1 Gaba_2", "0383 ACB-BST-FS D1 Gaba_3"]),
    "OB FRMD7 GABA": (["OB-in Frmd7 Gaba"], ["0151 OB-in Frmd7 Gaba_2", "0154 OB-in Frmd7 Gaba_5"]),
    "OB Dopa-GABA": (["OB Dopa-Gaba"], ["0163 OB Dopa-Gaba_2"]),
    "GPi Core GABA": (["ZI Pax6 Gaba"], ["0461 ZI Pax6 Gaba_3"]),
    "SN GATA3-PVALB GABA": (["SNr Six3 Gaba"], ["0806 SNr Six3 Gaba_1"]),
    "GPe SOX6-CTXND1 GABA": (["NDB-SI-MA-STRv Lhx8 Gaba"], ["0247 NDB-SI-MA-STRv Lhx8 Gaba_4"]),
    "ZI-HTH GABA": (["MB GABA EBF3", "CEA-BST Ebf1 Pdyn Gaba"], []),
    "SN-VTR-HTH GATA3-TCF7L2 GABA": (["PRT Tcf7l2 Gaba"], ["0829 PRT Tcf7l2 Gaba_1"]),
    "SN GATA3-PAX8 GABA": (["SNr-VTA Pax5 Npas1 Gaba"], ["0800 SNr-VTA Pax5 Npas1 Gaba_1", "0801 SNr-VTA Pax5 Npas1 Gaba_2"]),
    "GPe-NDB-SI LHX6-LHX8-GBX1 GABA": (["NDB-SI-MA-STRv Lhx8 Gaba"], ["0247 NDB-SI-MA-STRv Lhx8 Gaba_4", "0247 NDB-SI-MA-STRv Lhx8 Gaba_8"]),
    "VIP GABA": (["Vip Gaba"], ["0175 Vip Gaba_3", "0177 Vip Gaba_5"]),
    "LAMP5-CXCL14 GABA": (["Lamp5 Gaba"], ["0199 Lamp5 Gaba_1", "0200 Lamp5 Gaba_2"]),
    "STR SST-CHODL GABA": (["Sst Chodl Gaba"], ["0238 Sst Chodl Gaba_1", "0239 Sst Chodl Gaba_2"]),
    "STR SST-RSPO2 GABA": (["Sst Gaba"], ["0228 Sst Gaba_15"]),
    "STR LYPD6-RSPO2 GABA": (["Pvalb Gaba"], ["0212 Pvalb Gaba_8"]),
    "STR SST-ADARB2 GABA": (["Sst Gaba", "NDB-SI-MA-STRv Lhx8 Gaba", "PAL-STR Gaba-Chol"], ["0248 NDB-SI-MA-STRv Lhx8 Gaba_5", "0261 PAL-STR Gaba-Chol_3"]),
    "LAMP5-LHX6 GABA": (["Lamp5 Lhx6 Gaba"], ["0203 Lamp5 Lhx6 Gaba_1"]),
    "STR FS PTHLH-PVALB GABA": (["STR Prox1 Lhx6 Gaba"], ["0234 STR Prox1 Lhx6 Gaba_2"]),
    "STR TAC3-PLPP4 GABA": (["STR Lhx8 Gaba"], ["0236 STR Lhx8 Gaba_1"]),
    "STR-BF TAC3-PLPP4-LHX8 GABA": (["STR Lhx8 Gaba"], ["0236 STR Lhx8 Gaba_1"]),
    "GPin-BF Cholinergic GABA": (["PAL-STR Gaba-Chol"], ["0259 PAL-STR Gaba-Chol_1"]),
    "STR Cholinergic GABA": (["PAL-STR Gaba-Chol"], ["0260 PAL-STR Gaba-Chol_2"]),
    "STRd Cholinergic GABA": (["PAL-STR Gaba-Chol"], ["0260 PAL-STR Gaba-Chol_2"]),
    "SN-VTR GAD2 Dopa": (["SNc-VTA-RAmb Foxa1 Dopa"], ["0880 SNc-VTA-RAmb Foxa1 Dopa_1", "0887 SNc-VTA-RAmb Foxa1 Dopa_8"]),
    "SN SOX6 Dopa": (["SNc-VTA-RAmb Foxa1 Dopa"], ["0883 SNc-VTA-RAmb Foxa1 Dopa_4", "0884 SNc-VTA-RAmb Foxa1 Dopa_5"]),
    "SN-VTR CALB1 Dopa": (["SNc-VTA-RAmb Foxa1 Dopa"], ["0882 SNc-VTA-RAmb Foxa1 Dopa_3"]),
    "BF SKOR1 Glut": (["SI-MA-LPO-LHA Skor1 Glut"], ["0530 SI-MA-LPO-LHA Skor1 Glut_1", "0533 SI-MA-LPO-LHA Skor1 Glut_4", "0534 SI-MA-LPO-LHA Skor1 Glut_5"]),
    "VTR-HTH Glut": (["STN-PSTN Pitx2 Glut", "PGRN-PARN-MDRN Hoxb5 Glut"], ["0611 PH Pitx2 Glut_2", "0974 PGRN-PARN-MDRN Hoxb5 Glut_2"]),
    "STH PVALB-PITX2 Glut": (["STN-PSTN Pitx2 Glut"], ["0602 STN-PSTN Pitx2 Glut_5"]),
    "OPC": (["OPC NN"], ["1179 OPC NN_1"]),
    "COP": (["Oligo NN"], ["1181 COP NN_1"]),
    "ImOligo": (["Oligo NN"], ["1184 MOL NN_4"]),
    "Oligo PLEKHG1": (["Oligo NN"], ["1184 MOL NN_4"]),
    "Oligo OPALIN": (["Oligo NN"], ["1184 MOL NN_4"]),
    "ImAstro": (["Astro-NT NN", "Astro-TE NN"], []),
    "Astrocyte": (["Astro-NT NN", "Astro-TE NN"], []),
    "Ependymal": (["Ependymal NN"], ["1175 Ependymal NN_1", "1176 Ependymal NN_2"]),
    "Microglia": (["Microglia NN"], ["1194 Microglia NN_1"]),
    "BAM": (["BAM NN"], ["1195 BAM NN_1"]),
    "Monocyte": (["Monocytes NN"], ["1196 Monocytes NN_1"]),
    "B cell": (["Lymphoid NN"], ["1198 B cells NN_1"]),
    "T cell": (["Lymphoid NN"], ["1201 T cells NN_4"]),
    "VLMC": (["VLMC NN"], ["1188 VLMC NN_2"]),
    "SMC": (["SMC NN"], ["1192 SMC NN_1"]),
    "Pericyte": (["Peri NN"], ["1191 Peri NN_1"]),
    "Endo": (["Endo NN"], ["1193 Endo NN_1"]),
}


def data_dir() -> Path:
    return Path(os.environ.get("RP_DATA_DIR", "data"))


def out_dir() -> Path:
    p = Path(os.environ.get("RP_OUT_DIR", "out"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_metrics(metrics: dict) -> None:
    clean = {}
    for k, v in metrics.items():
        if hasattr(v, "item"):
            v = v.item()
        clean[k] = v
    (out_dir() / "metrics.json").write_text(json.dumps(clean, indent=1, sort_keys=True) + "\n")


def canon_group(label: str) -> str:
    """Normalize preprint/release Group labels to the Cell 2026 canonical nomenclature."""
    s = str(label).replace("_", " ").replace("MSN", "SPN").strip()
    s = s.replace("STRd D2 StrioMat Hybrid SPN", "STR D2 SMYD2-HTR7 SPN")
    s = s.replace("STR D1D2 Hybrid SPN", "STR D1D2 eSPN")
    s = s.replace("STRv D1 NUDAP SPN", "STRv D1 NUDAP eSPN")
    return s


def load_group_colors() -> dict[str, str]:
    """Load official ABC hex colors for all 61 Groups from cluster_annotation_term.csv."""
    p = data_dir() / "cluster_annotation_term.csv"
    if not p.exists():
        return dict(SPN_GROUP_COLORS)
    t = pd.read_csv(p)
    g = t[t["cluster_annotation_term_set_name"] == "Group"]
    return dict(zip(g["name"], g["color_hex_triplet"]))


def load_primate_spatial(prefix: str, need_section: bool = False) -> pd.DataFrame:
    """Load merged primate spatial table (cell_label, Group, x_slab_mm, y_slab_mm, slab_plane_label, STR, parcellation)."""
    d = data_dir()
    mm = pd.read_csv(d / f"{prefix}_mmc_results.csv", usecols=["cell_label", "Group"], low_memory=False)
    mm["Group"] = mm["Group"].map(canon_group)
    sl = pd.read_csv(
        d / f"{prefix}_slab_plane_coordinates.csv",
        usecols=["cell_label", "x_slab_mm", "y_slab_mm", "slab_plane_label"],
        low_memory=False,
    )
    an = pd.read_csv(
        d / f"{prefix}_cell_anatomical_annotations.csv",
        usecols=["cell_label", "STR", "parcellation_term_symbol"],
        low_memory=False,
    )
    df = mm.merge(sl, on="cell_label", how="left").merge(an, on="cell_label", how="left")
    if need_section:
        cm = pd.read_csv(
            d / f"{prefix}_cell_metadata.csv",
            usecols=["cell_label", "brain_section_label"],
            low_memory=False,
        )
        df = df.merge(cm, on="cell_label", how="left")
    return df


def compute_primate_mouse_homology(chunk_size: int = 50000):
    """Stream primate Cross-Species-log2.h5ad and Mouse WMB-10Xv3 {STR,PAL,MB,OLF}-log2.h5ad to compute:
      - sim_df: 61 Primate Groups x Mouse WMB supertypes (>=50 cells) z-scored 2,000-HVG Pearson similarity
      - primate_cnt: Series of total primate nuclei per Group
      - mouse_cnt: Series of total mouse WMB BG cells per supertype
      - macaque_marker_mean / macaque_marker_pct: DataFrames (44 neuronal Groups x 57 marker genes)
      - mouse_marker_mean / mouse_marker_pct: DataFrames (Mouse supertypes x 57 marker genes)
      - mouse_st_to_subclass: dict[supertype -> subclass]
    """
    import anndata as ad
    import scipy.sparse as sp

    d = data_dir()

    # 1. Primate cell -> (Group, species_genus)
    c2c = pd.read_csv(
        d / "cell_to_cluster_membership.csv",
        usecols=["cell_label", "cluster_alias"],
        dtype={"cell_label": "string", "cluster_alias": "string"},
    )
    mem = pd.read_csv(d / "cluster_to_cluster_annotation_membership.csv")
    c2g = mem[mem["cluster_annotation_term_set_name"] == "Group"][
        ["cluster_alias", "cluster_annotation_term_name"]
    ].drop_duplicates("cluster_alias")
    c2g["cluster_alias"] = c2g["cluster_alias"].astype("string")
    cell_grp = c2c.merge(c2g, on="cluster_alias", how="inner")
    cm = pd.read_csv(
        d / "cell_metadata.csv",
        usecols=["cell_label", "donor_label"],
        dtype={"cell_label": "string", "donor_label": "string"},
    )
    donors = pd.read_csv(d / "donor.csv", usecols=["donor_label", "species_genus"])
    cm = cm.merge(donors, on="donor_label", how="left")
    cell_info = cell_grp.merge(cm[["cell_label", "species_genus"]], on="cell_label", how="left")
    cell_info = cell_info.set_index("cell_label")

    g2i = {g: i for i, g in enumerate(ALL_GROUP_ORDER)}
    n_groups = len(ALL_GROUP_ORDER)

    # Stream Cross-Species-log2.h5ad
    pad = ad.read_h5ad(d / "HMBA-10xMultiome-BG-Cross-Species-log2.h5ad", backed="r")
    p_genes = (
        pad.var["gene_symbol"].astype(str).str.upper().values
        if "gene_symbol" in pad.var.columns
        else pad.var_names.astype(str).str.upper().values
    )
    _, p_uniq_idx = np.unique(p_genes, return_index=True)
    p_uniq_idx = np.sort(p_uniq_idx)
    p_genes_uniq = p_genes[p_uniq_idx]
    p_gene_pos = {g: i for i, g in enumerate(p_genes_uniq)}

    marker_p_idx = np.array([p_gene_pos[g] for g in FIG3A_MARKER_GENES if g in p_gene_pos], dtype=np.int64)
    marker_p_names = [g for g in FIG3A_MARKER_GENES if g in p_gene_pos]

    p_sum = np.zeros((n_groups, len(p_genes_uniq)), dtype=np.float64)
    p_cnt = np.zeros(n_groups, dtype=np.int64)
    q_m_sum = np.zeros((n_groups, len(marker_p_idx)), dtype=np.float64)
    q_m_nz = np.zeros((n_groups, len(marker_p_idx)), dtype=np.int64)
    q_cnt = np.zeros(n_groups, dtype=np.int64)

    obs_grp = cell_info["cluster_annotation_term_name"].reindex(pad.obs_names).values
    obs_sp = cell_info["species_genus"].reindex(pad.obs_names).values
    obs_gidx = np.array([g2i.get(g, -1) for g in obs_grp], dtype=np.int32)
    is_mac = (obs_sp == "Macaque")

    for s0 in range(0, pad.n_obs, chunk_size):
        s1 = min(s0 + chunk_size, pad.n_obs)
        X = pad.X[s0:s1]
        X = sp.csr_matrix(X) if not sp.issparse(X) else X.tocsr()
        if len(p_uniq_idx) != pad.n_vars:
            X = X[:, p_uniq_idx]
        gi = obs_gidx[s0:s1]
        ok = gi >= 0
        if ok.any():
            g_ok = gi[ok]
            X_ok = X[ok]
            M = sp.csr_matrix(
                (np.ones(g_ok.size, dtype=np.float64), (g_ok, np.arange(g_ok.size))),
                shape=(n_groups, g_ok.size),
            )
            p_sum += (M @ X_ok).toarray()
            p_cnt += np.bincount(g_ok, minlength=n_groups)

        # Macaque marker stats (mean + pct expressing > 0)
        q_ok = ok & is_mac[s0:s1]
        if q_ok.any():
            gq = gi[q_ok]
            Xq = X[q_ok][:, marker_p_idx]
            Mq = sp.csr_matrix(
                (np.ones(gq.size, dtype=np.float64), (gq, np.arange(gq.size))),
                shape=(n_groups, gq.size),
            )
            q_m_sum += (Mq @ Xq).toarray()
            Xq_bin = Xq.copy()
            Xq_bin.data = (Xq_bin.data > 0).astype(np.float64)
            q_m_nz += (Mq @ Xq_bin).toarray().astype(np.int64)
            q_cnt += np.bincount(gq, minlength=n_groups)

    pad.file.close()
    del pad, cell_info, cell_grp, c2c, cm
    gc.collect()

    primate_mean = pd.DataFrame(
        p_sum / np.maximum(p_cnt[:, None], 1),
        index=ALL_GROUP_ORDER,
        columns=p_genes_uniq,
    )
    macaque_marker_mean = pd.DataFrame(
        q_m_sum / np.maximum(q_cnt[:, None], 1),
        index=ALL_GROUP_ORDER,
        columns=marker_p_names,
    ).reindex(columns=FIG3A_MARKER_GENES)
    macaque_marker_pct = pd.DataFrame(
        q_m_nz / np.maximum(q_cnt[:, None], 1),
        index=ALL_GROUP_ORDER,
        columns=marker_p_names,
    ).reindex(columns=FIG3A_MARKER_GENES)

    # 2. Mouse WMB metadata -> supertype & subclass
    wmb_meta = pd.read_csv(
        d / "mouse_wmb_cell_metadata.csv",
        usecols=["cell_label", "cluster_alias"],
        low_memory=False,
    )
    wmb_mem = pd.read_csv(d / "mouse_wmb_cluster_to_cluster_annotation_membership.csv", low_memory=False)
    wmb_piv = wmb_mem.pivot_table(
        index="cluster_alias",
        columns="cluster_annotation_term_set_name",
        values="cluster_annotation_term_name",
        aggfunc="first",
    ).reset_index()
    mouse_st_to_subclass = dict(
        zip(wmb_piv["supertype"].dropna(), wmb_piv.loc[wmb_piv["supertype"].notna(), "subclass"])
    )
    wmb_meta = wmb_meta.merge(wmb_piv[["cluster_alias", "supertype"]], on="cluster_alias", how="left")
    wmb_idx = wmb_meta.set_index("cell_label")["supertype"]
    del wmb_meta, wmb_mem, wmb_piv
    gc.collect()

    # Stream 4 Mouse WMB BG h5ad files (STR, PAL, MB, OLF)
    mouse_st_sum: dict[str, np.ndarray] = {}
    mouse_st_cnt: dict[str, int] = {}
    mouse_m_sum: dict[str, np.ndarray] = {}
    mouse_m_nz: dict[str, np.ndarray] = {}
    shared_ordered = None
    m_g_idx = None
    marker_m_idx = None
    marker_m_names = None

    for reg in ["STR", "PAL", "MB", "OLF"]:
        hp = d / f"mouse_wmb_{reg.lower()}.h5ad"
        if not hp.exists():
            hp = d / f"WMB-10Xv3-{reg}-log2.h5ad"
        mad = ad.read_h5ad(hp, backed="r")
        g_sym = (
            mad.var["gene_symbol"].astype(str).str.upper().values
            if "gene_symbol" in mad.var.columns
            else mad.var_names.astype(str).str.upper().values
        )
        if shared_ordered is None:
            p_set = set(primate_mean.columns)
            keep = [i for i, g in enumerate(g_sym) if g in p_set]
            ordered = g_sym[keep]
            _, upos = np.unique(ordered, return_index=True)
            upos = np.sort(upos)
            m_g_idx = np.array(keep, dtype=np.int64)[upos]
            shared_ordered = ordered[upos]
            sh_pos = {g: i for i, g in enumerate(shared_ordered)}
            marker_m_idx = np.array([sh_pos[g] for g in FIG3A_MARKER_GENES if g in sh_pos], dtype=np.int64)
            marker_m_names = [g for g in FIG3A_MARKER_GENES if g in sh_pos]

        sts = wmb_idx.reindex(mad.obs_names).astype(str).values
        for s0 in range(0, mad.n_obs, chunk_size):
            s1 = min(s0 + chunk_size, mad.n_obs)
            X = mad.X[s0:s1][:, m_g_idx]
            X = sp.csr_matrix(X) if not sp.issparse(X) else X.tocsr()
            codes, uniqs = pd.factorize(sts[s0:s1])
            ok = codes >= 0
            if not ok.any():
                continue
            X_ok = X[ok]
            c_ok = codes[ok]
            M = sp.csr_matrix(
                (np.ones(c_ok.size, dtype=np.float64), (c_ok, np.arange(c_ok.size))),
                shape=(len(uniqs), c_ok.size),
            )
            sums = (M @ X_ok).toarray()
            cnts = np.bincount(c_ok, minlength=len(uniqs))

            Xm = X_ok[:, marker_m_idx]
            msums = (M @ Xm).toarray()
            Xm_bin = Xm.copy()
            Xm_bin.data = (Xm_bin.data > 0).astype(np.float64)
            mnz = (M @ Xm_bin).toarray().astype(np.int64)

            for ui, st_name in enumerate(uniqs):
                if st_name in ("nan", "None", "<NA>"):
                    continue
                if st_name not in mouse_st_sum:
                    mouse_st_sum[st_name] = np.zeros(len(shared_ordered), dtype=np.float64)
                    mouse_st_cnt[st_name] = 0
                    mouse_m_sum[st_name] = np.zeros(len(marker_m_idx), dtype=np.float64)
                    mouse_m_nz[st_name] = np.zeros(len(marker_m_idx), dtype=np.int64)
                mouse_st_sum[st_name] += sums[ui]
                mouse_st_cnt[st_name] += int(cnts[ui])
                mouse_m_sum[st_name] += msums[ui]
                mouse_m_nz[st_name] += mnz[ui]
        mad.file.close()
        del mad
        gc.collect()

    valid_sts = sorted([st for st, c in mouse_st_cnt.items() if c >= 50])
    mouse_mean = pd.DataFrame(
        np.vstack([mouse_st_sum[st] / mouse_st_cnt[st] for st in valid_sts]),
        index=valid_sts,
        columns=shared_ordered,
    )
    mouse_marker_mean = pd.DataFrame(
        np.vstack([mouse_m_sum[st] / mouse_st_cnt[st] for st in valid_sts]),
        index=valid_sts,
        columns=marker_m_names,
    ).reindex(columns=FIG3A_MARKER_GENES)
    mouse_marker_pct = pd.DataFrame(
        np.vstack([mouse_m_nz[st] / mouse_st_cnt[st] for st in valid_sts]),
        index=valid_sts,
        columns=marker_m_names,
    ).reindex(columns=FIG3A_MARKER_GENES)

    # 3. Cross-species similarity: z-scored top 2,000 primate HVGs -> row-wise Pearson correlation
    P_mat = primate_mean[shared_ordered]
    hvg = P_mat.var(axis=0).nlargest(2000).index
    P_sub = P_mat[hvg].values
    M_sub = mouse_mean[hvg].values
    Pz = (P_sub - P_sub.mean(axis=0, keepdims=True)) / np.maximum(P_sub.std(axis=0, keepdims=True), 1e-6)
    Mz = (M_sub - M_sub.mean(axis=0, keepdims=True)) / np.maximum(M_sub.std(axis=0, keepdims=True), 1e-6)
    Pz_c = Pz - Pz.mean(axis=1, keepdims=True)
    Mz_c = Mz - Mz.mean(axis=1, keepdims=True)
    denom = np.maximum(
        np.sqrt((Pz_c ** 2).sum(axis=1, keepdims=True) * (Mz_c ** 2).sum(axis=1, keepdims=True).T),
        1e-8,
    )
    sim_df = pd.DataFrame((Pz_c @ Mz_c.T) / denom, index=ALL_GROUP_ORDER, columns=valid_sts)

    return {
        "sim_df": sim_df,
        "primate_cnt": pd.Series(p_cnt, index=ALL_GROUP_ORDER),
        "mouse_cnt": pd.Series({st: mouse_st_cnt[st] for st in valid_sts}),
        "macaque_marker_mean": macaque_marker_mean,
        "macaque_marker_pct": macaque_marker_pct,
        "mouse_marker_mean": mouse_marker_mean,
        "mouse_marker_pct": mouse_marker_pct,
        "mouse_st_to_subclass": mouse_st_to_subclass,
        "n_shared_orthologs": int(len(shared_ordered)),
    }
