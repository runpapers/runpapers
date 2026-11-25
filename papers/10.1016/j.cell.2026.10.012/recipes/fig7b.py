# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.2", "numpy>=1.26", "scipy>=1.13", "matplotlib>=3.8", "anndata>=0.10",
# ]
# ///
"""Figure 7B: Human basal ganglia cell-type genetic risk enrichment via MAGMA v1.10 across all 453
human clusters (HMBA-10xMultiome-BG-Human-log2.h5ad) tested on open European-ancestry GWAS summary
statistics (Bellenguez et al. 2022 Alzheimer's disease GCST90027158; plus open PGC3 Schizophrenia
EUR when provided, and Table S19 full 6-trait cross-audit when present).

Note: Major depressive disorder (MDD), bipolar disorder (BD), and alcohol-use GWAS in the published
paper incorporate restricted 23andMe meta-analyses that cannot be redistributed; published LDSC
validation further filters psychiatric hits."""
import gzip
import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy import stats

from bg_epig import PUBLISHED_GROUP_ORDER, data_dir, out_dir, write_metrics

d = data_dir()
out = out_dir()
work = out / "_magma_work"
work.mkdir(parents=True, exist_ok=True)


def ensure_magma_binary() -> Path:
    b = d / "magma"
    if b.exists() and os.access(b, os.X_OK):
        return b
    z = d / "magma_v1.10_static.zip"
    dst = work / "magma"
    if not dst.exists():
        with zipfile.ZipFile(z) as zf:
            for nm in zf.namelist():
                if nm.endswith("/magma") or nm == "magma":
                    with zf.open(nm) as src, open(dst, "wb") as f_out:
                        shutil.copyfileobj(src, f_out)
                    break
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return dst


def ensure_g1000_eur() -> Path:
    if (d / "g1000_eur.bed").exists() and (d / "g1000_eur.bim").exists():
        return d / "g1000_eur"
    ref_dir = work / "g1000_eur_ref"
    ref_dir.mkdir(exist_ok=True)
    if not (ref_dir / "g1000_eur.bed").exists():
        with zipfile.ZipFile(d / "g1000_eur.zip") as zf:
            zf.extractall(ref_dir)
    return ref_dir / "g1000_eur"


def build_human_453_specificity(gene_loc_path: Path) -> tuple[Path, dict[str, str]]:
    """Build 453-human-cluster expression specificity matrix (Entrez genes x 453 Human clusters)."""
    mem = pd.read_csv(d / "cell_to_cluster_membership.csv", usecols=["cell_label", "cluster_alias"])
    ann = pd.read_csv(d / "cluster_to_cluster_annotation_membership.csv")
    piv = ann.pivot_table(
        index="cluster_alias",
        columns="cluster_annotation_term_set_name",
        values="cluster_annotation_term_name",
        aggfunc="first",
    ).reset_index()
    clust2grp = dict(zip(piv["Cluster"].astype(str), piv["Group"].astype(str)))

    covar_path = out / "human_453_specificity.txt"
    if covar_path.exists() and covar_path.stat().st_size > 10_000_000:
        return covar_path, clust2grp

    ann_cl = ann[ann["cluster_annotation_term_set_name"] == "Cluster"][["cluster_alias", "cluster_annotation_term_name"]]
    cm = mem.merge(ann_cl, on="cluster_alias", how="left").set_index("cell_label")["cluster_annotation_term_name"]

    had = ad.read_h5ad(d / "HMBA-10xMultiome-BG-Human-log2.h5ad", backed="r")
    h_vars = (
        had.var["gene_symbol"].astype(str).values
        if "gene_symbol" in had.var.columns
        else had.var_names.astype(str).values
    )
    h_cl = cm.reindex(had.obs_names).fillna("").astype(str).values
    uniq_cl = sorted([c for c in set(h_cl) if c.startswith("Human-")])
    cl2i = {c: i for i, c in enumerate(uniq_cl)}

    cl_sum = np.zeros((len(uniq_cl), had.n_vars), dtype=np.float64)
    cl_cnt = np.zeros(len(uniq_cl), dtype=np.int64)
    for s0 in range(0, had.n_obs, 40000):
        s1 = min(s0 + 40000, had.n_obs)
        X = had.X[s0:s1]
        X = sp.csr_matrix(X) if not sp.issparse(X) else X.tocsr()
        c_arr = np.array([cl2i.get(c, -1) for c in h_cl[s0:s1]])
        ok = c_arr >= 0
        if ok.any():
            M = sp.csr_matrix(
                (np.ones(int(ok.sum()), dtype=np.float64), (c_arr[ok], np.arange(int(ok.sum())))),
                shape=(len(uniq_cl), int(ok.sum())),
            )
            cl_sum += (M @ X[ok]).toarray()
            cl_cnt += np.bincount(c_arr[ok], minlength=len(uniq_cl))
    had.file.close()

    cl_mean = cl_sum / np.maximum(cl_cnt[:, None], 1)
    sym2entrez = {}
    with open(gene_loc_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 6:
                sym2entrez[parts[5]] = parts[0]

    keep_gi, entrez_ids, seen_e = [], [], set()
    for gi, sym in enumerate(h_vars):
        eid = sym2entrez.get(sym)
        if eid and eid not in seen_e and cl_mean[:, gi].sum() > 0:
            seen_e.add(eid)
            keep_gi.append(gi)
            entrez_ids.append(eid)

    mat_k = cl_mean[:, np.array(keep_gi)]
    spec = mat_k / np.maximum(mat_k.sum(axis=0, keepdims=True), 1e-12)
    cov_df = pd.DataFrame(spec.T, index=entrez_ids, columns=uniq_cl)
    cov_df.index.name = "GENE"
    cov_df.to_csv(covar_path, sep="\t", float_format="%.6f")
    return covar_path, clust2grp


def run_magma_trait(
    magma_bin: Path,
    ref_bed: Path,
    gene_loc: Path,
    covar_path: Path,
    sumstats_gz: Path,
    trait_slug: str,
    n_sample: int,
    rs_col: str,
    chr_col: str,
    pos_col: str,
    p_col: str,
) -> tuple[pd.DataFrame, int]:
    """Stream gzipped GWAS summary stats (tolerating EBI trailing EOF garbage), dedupe rsIDs,
    and run 3-step MAGMA v1.10 (window=35,35; direction-covar=greater)."""
    pval_p = work / f"{trait_slug}_pval.txt"
    loc_p = work / f"{trait_slug}_snploc.txt"
    pref = work / f"magma_{trait_slug}"
    gsa_out = Path(f"{pref}_celltype.gsa.out")

    if not gsa_out.exists():
        # Stream & clean autosomal SNPs (chr 1..22)
        valid_chrs = {str(i) for i in range(1, 23)}
        seen_rs = set()
        n_kept = 0
        # Use gzip/zlib stream tolerant of EBI trailing bytes after EOF
        with open(pval_p, "w") as fp, open(loc_p, "w") as fl:
            fp.write("SNP\tP\n")
            proc = subprocess.Popen(["gzip", "-dc", str(sumstats_gz)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            header = None
            idx_rs = idx_ch = idx_pos = idx_p = -1
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith("##"):
                    continue
                if header is None:
                    header = line.lstrip("#").strip().split("\t")
                    col_i = {c: i for i, c in enumerate(header)}
                    idx_rs, idx_ch, idx_pos, idx_p = col_i[rs_col], col_i[chr_col], col_i[pos_col], col_i[p_col]
                    continue
                parts = line.strip().split("\t")
                if len(parts) <= max(idx_rs, idx_ch, idx_pos, idx_p):
                    continue
                ch = parts[idx_ch].replace("chr", "")
                if ch not in valid_chrs:
                    continue
                rs = parts[idx_rs]
                if not rs or rs == "." or rs in seen_rs:
                    continue
                try:
                    pv = float(parts[idx_p])
                    pos_i = int(float(parts[idx_pos]))
                except ValueError:
                    continue
                if not (0.0 <= pv <= 1.0) or np.isnan(pv):
                    continue
                if pv == 0.0:
                    pv = 1e-300
                seen_rs.add(rs)
                fp.write(f"{rs}\t{pv}\n")
                fl.write(f"{rs}\t{ch}\t{pos_i}\n")
                n_kept += 1
            proc.wait()

        # Step 1: SNP-to-gene annotation
        res = subprocess.run(
            [str(magma_bin), "--annotate", "window=35,35", "--snp-loc", str(loc_p), "--gene-loc", str(gene_loc), "--out", str(pref)],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"MAGMA annotate failed:\n{res.stdout[-500:]}\n{res.stderr[-500:]}")

        # Step 2: Gene-level analysis (parallelized across available CPU cores via MAGMA --batch + --merge)
        n_workers = max(1, min(int(os.environ.get("RP_MAGMA_BATCHES", os.cpu_count() or 1)), 8))
        if n_workers > 1:
            procs = []
            for bi in range(1, n_workers + 1):
                cmd_b = [
                    str(magma_bin), "--bfile", str(ref_bed), "--pval", str(pval_p), f"N={n_sample}",
                    "--gene-annot", f"{pref}.genes.annot", "--batch", str(bi), str(n_workers),
                    "--out", str(pref),
                ]
                procs.append((bi, subprocess.Popen(cmd_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
            for bi, p in procs:
                so, se = p.communicate()
                if p.returncode != 0:
                    raise RuntimeError(f"MAGMA batch {bi}/{n_workers} failed:\n{so[-500:]}\n{se[-500:]}")
            res_m = subprocess.run(
                [str(magma_bin), "--merge", str(pref), "--out", str(pref)],
                capture_output=True, text=True,
            )
            if res_m.returncode != 0:
                raise RuntimeError(f"MAGMA merge failed:\n{res_m.stdout[-500:]}\n{res_m.stderr[-500:]}")
        else:
            res_g = subprocess.run(
                [str(magma_bin), "--bfile", str(ref_bed), "--pval", str(pval_p), f"N={n_sample}", "--gene-annot", f"{pref}.genes.annot", "--out", str(pref)],
                capture_output=True, text=True,
            )
            if res_g.returncode != 0:
                raise RuntimeError(f"MAGMA gene analysis failed:\n{res_g.stdout[-500:]}\n{res_g.stderr[-500:]}")

        # Step 3: Cell-type specificity gene-property regression across all 453 human clusters
        res_c = subprocess.run(
            [str(magma_bin), "--gene-results", f"{pref}.genes.raw", "--gene-covar", str(covar_path), "--model", "direction-covar=greater", "--out", f"{pref}_celltype"],
            capture_output=True, text=True,
        )
        if res_c.returncode != 0:
            raise RuntimeError(f"MAGMA cell-type analysis failed:\n{res_c.stdout[-500:]}\n{res_c.stderr[-500:]}")
    else:
        n_kept = sum(1 for _ in open(pval_p)) - 1 if pval_p.exists() else 0

    gsa = pd.read_csv(gsa_out, comment="#", sep=r"\s+")
    return gsa, n_kept


magma_bin = ensure_magma_binary()
ref_bed = ensure_g1000_eur()
gene_loc = d / "NCBI38.3.gene.loc.extendedMHCexcluded"
covar_path, clust2grp = build_human_453_specificity(gene_loc)

# 1. From-scratch MAGMA v1.10 on Bellenguez et al. (2022) AD GWAS (GCST90027158)
ad_gsa, ad_n_snps = run_magma_trait(
    magma_bin, ref_bed, gene_loc, covar_path,
    d / "GCST90027158_buildGRCh38.tsv.gz",
    trait_slug="AD", n_sample=487511,
    rs_col="variant_id", chr_col="chromosome", pos_col="base_pair_location", p_col="p_value",
)
ad_gsa["Group"] = ad_gsa["VARIABLE"].map(clust2grp)
ad_gsa.to_csv(out / "fig7b_magma_ad_from_scratch.csv", index=False)

ad_sig = ad_gsa[ad_gsa["P"] < 1e-4]
ad_vc = ad_sig["Group"].value_counts().to_dict()
nonneuron_groups = {"OPC", "COP", "ImOligo", "Oligo PLEKHG1", "Oligo OPALIN", "ImAstro", "Astrocyte", "Ependymal", "Microglia", "BAM", "Monocyte", "B cell", "T cell", "VLMC", "SMC", "Pericyte", "Endo"}
ad_neuronal_fp = int((~ad_sig["Group"].isin(nonneuron_groups)).sum())

# 2. From-scratch MAGMA v1.10 on open PGC3 SCZ EUR (GRCh37)
scz_gsa = None
scz_n_snps = 0
scz_p = d / "PGC3_SCZ_wave3.european.autosome.public.v3.vcf.tsv.gz"
gene_loc_hg37 = d / "NCBI37.3.gene.loc.extendedMHCexcluded"
if scz_p.exists() and scz_p.stat().st_size > 10_000_000 and gene_loc_hg37.exists():
    proc = subprocess.Popen(["gzip", "-dc", str(scz_p)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    hdr = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if not line.startswith("##"):
            hdr = line.lstrip("#").strip().split("\t")
            break
    proc.terminate()
    rs_c = next(c for c in ("ID", "rsid", "variant_id", "SNP") if c in hdr)
    ch_c = next(c for c in ("CHROM", "chromosome", "CHR") if c in hdr)
    po_c = next(c for c in ("POS", "base_pair_location", "BP") if c in hdr)
    pv_c = next(c for c in ("PVAL", "p_value", "P") if c in hdr)
    scz_gsa, scz_n_snps = run_magma_trait(
        magma_bin, ref_bed, gene_loc_hg37, covar_path, scz_p,
        trait_slug="SCZ", n_sample=130644, rs_col=rs_c, chr_col=ch_c, pos_col=po_c, p_col=pv_c,
    )
    scz_gsa["Group"] = scz_gsa["VARIABLE"].map(clust2grp)
    scz_gsa.to_csv(out / "fig7b_magma_scz_from_scratch.csv", index=False)

# 3. Plot Figure 7B dot matrix (from-scratch MAGMA + Table S19 full 6-trait panel if available)
COLS_7B = [
    "STRd D1 Striosome SPN", "STRd D2 Matrix SPN", "STRd D2 Striosome SPN", "STR D2 SMYD2-HTR7 SPN",
    "STRv D1 SPN", "STRv D2 SPN", "STRv D1 NUDAP eSPN", "GPe MEIS2-SOX6 GABA", "OB FRMD7 GABA",
    "VIP GABA", "LAMP5-CXCL14 GABA", "STR SST-RSPO2 GABA", "STR LYPD6-RSPO2 GABA", "LAMP5-LHX6 GABA", "STRd Cholinergic GABA",
    "ImOligo", "ImAstro", "Microglia", "BAM", "T cell", "Endo",
]

# Build trait rows from whatever traits were computed/provided
trait_rows = []
if scz_gsa is not None:
    scz_sig = scz_gsa[scz_gsa["P"] < 1e-4]
    trait_rows.append(("Schizophrenia (MAGMA)", scz_sig["Group"].value_counts().to_dict(), "#386cb0"))
trait_rows.append(("Alzheimer Disease (MAGMA)", ad_vc, "#7fc97f"))

# Also check if Table S19 CSVs are present for the full 6-trait comparison
t19_traits = [
    ("SCZ (Table S19)", "TableS19.SCZ_2022_european.csv", "#386cb0"),
    ("Depression (Table S19)", "TableS19.depression_european.csv", "#6baed6"),
    ("Bipolar (Table S19)", "TableS19.bipolar_disorder_european.csv", "#74c476"),
    ("PTSD (Table S19)", "TableS19.PTSD_european.csv", "#9e9ac8"),
    ("AD (Table S19)", "TableS19.Alzheimer_european.csv", "#a1d99b"),
    ("Ancient DNA (Table S19)", "TableS19.ancient_DNA_european.csv", "#b2df8a"),
]
t19_rows = []
for lbl, fn, col in t19_traits:
    p = d / fn
    if p.exists():
        df19 = pd.read_csv(p)
        s19 = df19[df19["P"] < 1e-4].copy()
        s19["Group"] = s19["VARIABLE"].map(clust2grp)
        t19_rows.append((lbl, s19["Group"].value_counts().to_dict(), col))

plot_rows = t19_rows + trait_rows if t19_rows else trait_rows

fig_h = max(3.6, 0.55 * len(plot_rows) + 2.4)
fig, ax = plt.subplots(figsize=(11.2, fig_h), dpi=180)
for ri, (tr_lbl, vc_map, col) in enumerate(plot_rows):
    for ci, g in enumerate(COLS_7B):
        val = int(vc_map.get(g, 0))
        if val > 0:
            ax.scatter([ci], [ri], s=val * 30 + 26, c=col, edgecolors="#222222", lw=0.6, zorder=3)
            ax.text(ci, ri, str(val), ha="center", va="center", fontsize=7, fontweight="bold",
                    color="white" if val >= 6 else "black", zorder=4)

ax.axvline(14.5, color="#888888", ls="--", lw=0.9)
ax.set_xticks(range(len(COLS_7B)))
ax.set_xticklabels(COLS_7B, rotation=48, ha="right", fontsize=8)
ax.set_yticks(range(len(plot_rows)))
ax.set_yticklabels([r[0] for r in plot_rows], fontsize=8.5)
ax.invert_yaxis()
ax.set_xlim(-0.7, len(COLS_7B) - 0.3)
ax.set_ylim(len(plot_rows) - 0.3, -0.7)
ax.set_title("Human BG Cell-Type Disease Associations (MAGMA v1.10, P < 1e-4 across 453 Human Clusters)", fontsize=10)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
fig.savefig(out / "fig7b.png", dpi=180)
plt.close(fig)

# Compute summary metrics
scz_ok = False
scz_metrics = {}
if scz_gsa is not None:
    scz_sig = scz_gsa[scz_gsa["P"] < 1e-4]
    scz_vc = scz_sig["Group"].value_counts().to_dict()
    scz_ok = (
        scz_vc.get("STRv D1 NUDAP eSPN", 0) >= 3
        and scz_vc.get("STRv D2 SPN", 0) >= 2
        and scz_vc.get("VIP GABA", 0) >= 3
    )
    scz_metrics = {
        "scz_magma_total_sig_clusters": int(len(scz_sig)),
        "scz_magma_strv_d1_nudap_sig": int(scz_vc.get("STRv D1 NUDAP eSPN", 0)),
        "scz_magma_strv_d2_sig": int(scz_vc.get("STRv D2 SPN", 0)),
        "scz_magma_vip_sig": int(scz_vc.get("VIP GABA", 0)),
        "scz_magma_gpe_meis2_sox6_sig": int(scz_vc.get("GPe MEIS2-SOX6 GABA", 0)),
        "scz_magma_smyd2_sig": int(scz_vc.get("STR D2 SMYD2-HTR7 SPN", 0)),
    }
elif t19_rows:
    scz_vc = t19_rows[0][1]
    scz_ok = (
        scz_vc.get("STRv D1 NUDAP eSPN", 0) >= 10
        and scz_vc.get("VIP GABA", 0) >= 10
    )

metrics = {
    "n_human_clusters_tested": int(len(ad_gsa)),
    "ad_magma_n_snps": int(ad_n_snps),
    "ad_magma_total_sig_clusters": int(len(ad_sig)),
    "ad_magma_microglia_sig_clusters": int(ad_vc.get("Microglia", 0)),
    "ad_magma_bam_sig_clusters": int(ad_vc.get("BAM", 0)),
    "ad_magma_tcell_sig_clusters": int(ad_vc.get("T cell", 0)),
    "ad_magma_neuronal_false_positives": ad_neuronal_fp,
    "ad_magma_zero_neuronal_false_positives": bool(ad_neuronal_fp == 0),
    "scz_magma_ventral_spn_and_vip_enriched": bool(scz_ok),
    **scz_metrics,
}
write_metrics(metrics)
print(metrics)
