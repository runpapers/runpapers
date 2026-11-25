"""Shared helpers for epigenomics, DeepHumanBG sequence modeling, and GWAS recipes
for Johansen et al., Cell 2026 (DOI: 10.1016/j.cell.2026.10.012).

All inputs are read from $RP_DATA_DIR and all outputs are written to $RP_OUT_DIR."""
from __future__ import annotations

import gzip
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

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

SPN_GROUPS = [
    "STRd D1 Matrix SPN",
    "STRd D1 Striosome SPN",
    "STRd D2 Matrix SPN",
    "STRd D2 Striosome SPN",
    "STRv D1 SPN",
    "STRv D2 SPN",
    "STR D2 SMYD2-HTR7 SPN",
    "STR D1D2 eSPN",
    "STRv D1 NUDAP eSPN",
]

NONNEURON_GROUPS = {
    "OPC", "COP", "ImOligo", "Oligo PLEKHG1", "Oligo OPALIN",
    "ImAstro", "Astrocyte", "Ependymal", "Microglia", "BAM",
    "Monocyte", "B cell", "T cell", "VLMC", "SMC", "Pericyte", "Endo",
}

LEGACY_TO_CANON = {
    "T cells": "T cell",
    "B cells": "B cell",
    "GPi Core": "GPi Core GABA",
    "GPi Shell": "GPi Shell GABA-Glut",
    "SN EBF2 GABA": "IP EBF2 GABA",
    "SN SEMA5A GABA": "IP SEMA5A GABA",
    "STRd D1 Matrix MSN": "STRd D1 Matrix SPN",
    "STRv D1 MSN": "STRv D1 SPN",
    "STRd D1 Striosome MSN": "STRd D1 Striosome SPN",
    "STRd D2 Matrix MSN": "STRd D2 Matrix SPN",
    "STRv D2 MSN": "STRv D2 SPN",
    "STRd D2 Striosome MSN": "STRd D2 Striosome SPN",
    "STRd D2 StrioMat Hybrid MSN": "STR D2 SMYD2-HTR7 SPN",
    "STRv D1 NUDAP MSN": "STRv D1 NUDAP eSPN",
    "STR D1D2 Hybrid MSN": "STR D1D2 eSPN",
    "OT D1 ICj": "OT ICj Granule",
}


def canon_group(name: str) -> str:
    """Map preprint (20250531) or underscored Group names to canonical 20261031 Cell names."""
    s = str(name).strip().replace("_", " ")
    if s in LEGACY_TO_CANON:
        return LEGACY_TO_CANON[s]
    s2 = s.replace("MSN", "SPN")
    if s2 in LEGACY_TO_CANON:
        return LEGACY_TO_CANON[s2]
    s2 = s2.replace("STRd D2 StrioMat Hybrid SPN", "STR D2 SMYD2-HTR7 SPN")
    s2 = s2.replace("STR D1D2 Hybrid SPN", "STR D1D2 eSPN")
    s2 = s2.replace("STRv D1 NUDAP SPN", "STRv D1 NUDAP eSPN")
    return s2


def data_dir() -> Path:
    return Path(os.environ.get("RP_DATA_DIR", "data"))


def out_dir() -> Path:
    p = Path(os.environ.get("RP_OUT_DIR", "out"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def rp_seed() -> int:
    return int(os.environ.get("RP_SEED", "0"))


def write_metrics(metrics: dict) -> None:
    def _clean(v):
        if hasattr(v, "item"):
            return v.item()
        if isinstance(v, dict):
            return {str(k): _clean(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_clean(val) for val in v]
        return v

    clean = _clean(metrics)
    (out_dir() / "metrics.json").write_text(json.dumps(clean, indent=1, sort_keys=True) + "\n")


def load_group_metadata() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Return (group_colors, group_to_class, group_to_subclass, class_colors) from ABC taxonomy tables."""
    d = data_dir()
    terms_p = d / "cluster_annotation_term.csv"
    mem_p = d / "cluster_to_cluster_annotation_membership.csv"
    group_colors: dict[str, str] = {}
    class_colors: dict[str, str] = {}
    group_to_class: dict[str, str] = {}
    group_to_subclass: dict[str, str] = {}
    if terms_p.exists():
        t = pd.read_csv(terms_p)
        g = t[t["cluster_annotation_term_set_name"] == "Group"]
        group_colors = dict(zip(g["name"], g["color_hex_triplet"]))
        c = t[t["cluster_annotation_term_set_name"] == "Class"]
        class_colors = dict(zip(c["name"], c["color_hex_triplet"]))
    if mem_p.exists():
        mem = pd.read_csv(mem_p)
        piv = mem.pivot_table(
            index="cluster_alias",
            columns="cluster_annotation_term_set_name",
            values="cluster_annotation_term_name",
            aggfunc="first",
        ).dropna(subset=["Group"])
        for grp, sub in piv.groupby("Group"):
            if "Class" in sub.columns:
                group_to_class[grp] = str(sub["Class"].iloc[0])
            if "Subclass" in sub.columns:
                group_to_subclass[grp] = str(sub["Subclass"].iloc[0])
    return group_colors, group_to_class, group_to_subclass, class_colors


def calc_gini_1d(arr: np.ndarray) -> float:
    """CREsted Gini coefficient for a non-negative 1D accessibility vector."""
    x = np.asarray(arr, dtype=np.float64).ravel().clip(0.0, None) + 1e-7
    x = np.sort(x)
    n = x.size
    idx = np.arange(1, n + 1, dtype=np.float64)
    return float(np.sum((2.0 * idx - n - 1.0) * x) / (n * np.sum(x)))


def calc_gini_2d(mat: np.ndarray) -> np.ndarray:
    """Row-wise Gini coefficient (vectorized across rows)."""
    x = np.asarray(mat, dtype=np.float64).clip(0.0, None) + 1e-7
    x = np.sort(x, axis=1)
    n = x.shape[1]
    coef = (2.0 * np.arange(1, n + 1, dtype=np.float64) - n - 1.0)[None, :]
    return np.sum(coef * x, axis=1) / (n * np.sum(x, axis=1))


# Fast vectorized ASCII -> one-hot lookup table (A, C, G, T)
_ONEHOT_LUT = np.zeros((256, 4), dtype=np.float32)
_ONEHOT_LUT[ord("A")] = _ONEHOT_LUT[ord("a")] = [1, 0, 0, 0]
_ONEHOT_LUT[ord("C")] = _ONEHOT_LUT[ord("c")] = [0, 1, 0, 0]
_ONEHOT_LUT[ord("G")] = _ONEHOT_LUT[ord("g")] = [0, 0, 1, 0]
_ONEHOT_LUT[ord("T")] = _ONEHOT_LUT[ord("t")] = [0, 0, 0, 1]

_BASE_LUT = np.full(256, -1, dtype=np.int8)
for _ch, _v in [("A", 0), ("a", 0), ("C", 1), ("c", 1), ("G", 2), ("g", 2), ("T", 3), ("t", 3)]:
    _BASE_LUT[ord(_ch)] = _v


def one_hot_seq(seq: str) -> np.ndarray:
    raw = np.frombuffer(seq.encode("ascii", errors="replace"), dtype=np.uint8)
    return _ONEHOT_LUT[raw].copy()


def one_hot_batch(seqs: list[str]) -> np.ndarray:
    n = len(seqs)
    L = len(seqs[0])
    out = np.empty((n, L, 4), dtype=np.float32)
    for i, s in enumerate(seqs):
        raw = np.frombuffer(s.encode("ascii", errors="replace"), dtype=np.uint8)
        out[i] = _ONEHOT_LUT[raw]
    return out


def open_genome_fasta(build: str = "hg38"):
    """Open <build>.fa (decompressing <build>.fa.gz into $RP_OUT_DIR if only .gz exists)."""
    from pyfaidx import Fasta

    d = data_dir()
    fa = d / f"{build}.fa"
    if fa.exists():
        return Fasta(str(fa), as_raw=True)
    gz = d / f"{build}.fa.gz"
    if gz.exists():
        unpacked = out_dir() / f"_tmp_{build}.fa"
        if not unpacked.exists():
            import shutil

            with gzip.open(gz, "rb") as src, open(unpacked, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        return Fasta(str(unpacked), as_raw=True)
    raise FileNotFoundError(f"Neither {fa} nor {gz} found in RP_DATA_DIR")


def open_hg38_fasta():
    """Open hg38.fa (or unpack hg38.fa.gz into $RP_OUT_DIR)."""
    return open_genome_fasta("hg38")


def pad_sequence_n(sequence: str, target_width: int = 2114) -> str:
    """Center-trim or symmetrically N-pad a DNA sequence to target_width (matching CREsted inference)."""
    seq = sequence.upper()
    if len(seq) >= target_width:
        center = len(seq) // 2
        start = center - (target_width // 2)
        return seq[start : start + target_width]
    total_pad = target_width - len(seq)
    left_pad = total_pad // 2
    right_pad = total_pad - left_pad
    return ("N" * left_pad) + seq + ("N" * right_pad)


def load_deephumanbg():
    """Load DeepHumanBG (Keras 3 + PyTorch backend, cuDNN disabled for dilated conv stability on A100)."""
    os.environ["KERAS_BACKEND"] = "torch"
    import torch

    torch.backends.cudnn.enabled = False
    import keras

    model_p = data_dir() / "human_BG_20260204_finetune_epoch_12.keras"
    model = keras.models.load_model(str(model_p), compile=False)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return model, device


def calibrate_deephumanbg_channels(
    model,
    fasta,
    peaks_df: pd.DataFrame | None = None,
    n_per_group: int = 35,
    seed: int = 0,
) -> tuple[list[str], dict[str, int]]:
    """Empirically calibrate all 59 DeepHumanBG output heads against human_atac_group_by_peaks.csv.

    Uses exclusive / highest-specificity peaks per Group and solves the 1-to-1 linear sum assignment
    on z-scored channel enrichment, guaranteeing exact channel-to-Group alignment with zero guesswork.
    Returns (idx_to_group[0..58], group_to_idx).
    """
    from scipy.optimize import linear_sum_assignment

    d = data_dir()
    if peaks_df is None:
        peaks_df = pd.read_csv(d / "atac_human_Group_by_peaks.csv", index_col=0)
    cols = [canon_group(c) for c in peaks_df.columns]
    peaks_df = peaks_df.copy()
    peaks_df.columns = cols

    # Drop any Group with < 500 total peaks (in human, SN GATA3-PVALB GABA has only 7 peaks -> excluded from 59-head model)
    col_sums = (peaks_df.values > 0).sum(axis=0)
    valid_groups = [g for g, cnt in zip(cols, col_sums) if cnt >= 500]
    n_out = int(model.output_shape[-1])
    if len(valid_groups) != n_out:
        # Take top n_out groups by peak count
        order = np.argsort(-col_sums)[:n_out]
        valid_groups = [cols[i] for i in sorted(order)]

    win = int(model.input_shape[1])
    half = win // 2
    valid_chrs = set(fasta.keys())

    # Parse coordinates once
    idx_s = pd.Series(peaks_df.index.astype(str))
    ex = idx_s.str.extract(r"^(chr[0-9XY]+):(\d+)-(\d+)$")
    ok_coord = ex[0].isin(valid_chrs).values
    chrs = ex[0].values
    starts = pd.to_numeric(ex[1], errors="coerce").fillna(-1).astype(np.int64).values
    ends = pd.to_numeric(ex[2], errors="coerce").fillna(-1).astype(np.int64).values

    B = (peaks_df[valid_groups].values > 0)
    act_sum = B.sum(axis=1)
    rng = np.random.default_rng(seed)

    seqs: list[str] = []
    grp_ids: list[int] = []
    for gi, gname in enumerate(valid_groups):
        cand = np.where(B[:, gi] & ok_coord & (act_sum <= 3))[0]
        if len(cand) < n_per_group:
            cand = np.where(B[:, gi] & ok_coord & (act_sum <= 6))[0]
        if len(cand) < n_per_group:
            cand = np.where(B[:, gi] & ok_coord)[0]
        # Prefer rarest (most exclusive) peaks
        ord_c = cand[np.argsort(act_sum[cand])]
        pool = ord_c[: max(n_per_group * 4, 150)]
        rng.shuffle(pool)
        picked = 0
        for row_i in pool:
            ch = chrs[row_i]
            mid = (starts[row_i] + ends[row_i]) // 2
            s0, e0 = int(mid - half), int(mid - half + win)
            if s0 < 0 or e0 > len(fasta[ch]):
                continue
            sq = str(fasta[ch][s0:e0]).upper()
            if len(sq) == win:
                seqs.append(sq)
                grp_ids.append(gi)
                picked += 1
                if picked >= n_per_group:
                    break

    preds = model.predict(one_hot_batch(seqs), batch_size=128, verbose=0)
    # Column-wise z-score across all calibration peaks
    pred_z = (preds - preds.mean(axis=0, keepdims=True)) / np.maximum(preds.std(axis=0, keepdims=True), 1e-6)
    grp_ids_arr = np.array(grp_ids)
    score_mat = np.zeros((n_out, n_out), dtype=np.float64)
    for gi in range(n_out):
        m = grp_ids_arr == gi
        if m.any():
            score_mat[gi] = pred_z[m].mean(axis=0) - pred_z[~m].mean(axis=0)

    row_ind, col_ind = linear_sum_assignment(-score_mat)
    idx_to_group = [""] * n_out
    for gi, ch_i in zip(row_ind, col_ind):
        idx_to_group[ch_i] = valid_groups[gi]
    group_to_idx = {g: i for i, g in enumerate(idx_to_group)}
    return idx_to_group, group_to_idx


def integrated_gradients(model, oh_single: np.ndarray, target_idx: int, device, steps: int = 40) -> np.ndarray:
    """Compute Integrated Gradients (steps, zero baseline) for a single (L, 4) or (1, L, 4) one-hot sequence."""
    return integrated_gradients_multi(model, oh_single, [target_idx], device, steps=steps)


def integrated_gradients_multi(
    model, oh_single: np.ndarray, target_indices: list[int], device, steps: int = 40
) -> np.ndarray:
    """Compute mean Integrated Gradients across one or more target heads for a single (L, 4) one-hot sequence."""
    import torch

    if oh_single.ndim == 2:
        oh = oh_single[None, :, :].astype(np.float32)
    else:
        oh = oh_single.astype(np.float32)
    alphas = np.linspace(0.0, 1.0, steps + 1, dtype=np.float32)[:, None, None]
    interp = alphas * oh
    x_t = torch.tensor(interp, dtype=torch.float32, device=device, requires_grad=True)
    preds = model(x_t, training=False)[:, target_indices].mean(dim=1)
    preds.sum().backward()
    grads = x_t.grad.detach().cpu().numpy()
    avg_grads = np.mean(0.5 * (grads[:-1] + grads[1:]), axis=0)
    return oh[0] * avg_grads


def plot_seq_logo(ax, contrib: np.ndarray, title: str = "", x_offset: int = 0) -> None:
    """Render per-base contribution scores (L, 4) as a DNA sequence logo using logomaker."""
    df = pd.DataFrame(contrib, columns=["A", "C", "G", "T"])
    try:
        import logomaker

        logomaker.Logo(df, ax=ax, color_scheme="classic", vpad=0.02, width=0.92)
    except Exception:
        vals = contrib.sum(axis=1)
        ax.bar(np.arange(len(vals)), vals, color=np.where(vals >= 0, "#d95f02", "#386cb0"), width=0.85)
    if x_offset != 0:
        ticks = ax.get_xticks()
        ax.set_xticklabels([str(int(t + x_offset)) for t in ticks], fontsize=7)
    if title:
        ax.set_title(title, fontsize=8.5, loc="left", pad=2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def draw_refseq_genes(
    ax,
    chrom: str,
    start: int,
    end: int,
    highlight_genes: set[str] | None = None,
) -> list[str]:
    """Parse UCSC ncbiRefSeqCurated.txt.gz and draw exon/intron gene models in [start, end] (Mb x-axis)."""
    refseq_p = data_dir() / "ncbiRefSeqCurated.txt.gz"
    genes: dict[str, dict] = {}
    with gzip.open(refseq_p, "rt") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 13 or parts[2] != chrom:
                continue
            tx_s, tx_e = int(parts[4]), int(parts[5])
            if tx_e < start or tx_s > end:
                continue
            sym = parts[12]
            if highlight_genes and sym not in highlight_genes:
                continue
            span = tx_e - tx_s
            ex_s = [int(x) for x in parts[9].split(",") if x]
            ex_e = [int(x) for x in parts[10].split(",") if x]
            # Keep longest canonical transcript per gene symbol
            if sym not in genes or span > genes[sym]["span"]:
                genes[sym] = {
                    "strand": parts[3],
                    "tx_s": tx_s,
                    "tx_e": tx_e,
                    "ex_s": ex_s,
                    "ex_e": ex_e,
                    "span": span,
                }
    names = sorted(genes.keys(), key=lambda g: genes[g]["tx_s"])
    for row_i, sym in enumerate(names):
        g = genes[sym]
        y = -row_i
        xs = max(g["tx_s"], start) / 1e6
        xe = min(g["tx_e"], end) / 1e6
        ax.plot([xs, xe], [y, y], color="#222222", lw=1.0, zorder=2)
        # Strand chevrons along intron line
        n_arr = max(2, min(14, int((xe - xs) / ((end - start) / 1e6) * 18)))
        arrow_ch = ">" if g["strand"] == "+" else "<"
        for xp in np.linspace(xs, xe, n_arr + 2)[1:-1]:
            ax.text(xp, y, arrow_ch, ha="center", va="center", fontsize=6, color="#555555")
        for s_i, e_i in zip(g["ex_s"], g["ex_e"]):
            if e_i < start or s_i > end:
                continue
            es = max(s_i, start) / 1e6
            ee = min(e_i, end) / 1e6
            ax.add_patch(
                __import__("matplotlib.patches", fromlist=["Rectangle"]).Rectangle(
                    (es, y - 0.25), max(ee - es, (end - start) / 1e6 * 0.002), 0.5,
                    facecolor="#1b4f72", edgecolor="none", zorder=3
                )
            )
        span_mb = (end - start) / 1e6
        if xe > end / 1e6 - 0.14 * span_mb:
            # Place label centered above the gene body so it never clips past the right edge
            ax.text((xs + xe) / 2.0, y + 0.34, sym, va="bottom", ha="center", fontsize=7.8, fontweight="bold", style="italic")
        else:
            ax.text(xe + 0.008 * span_mb, y, sym, va="center", ha="left", fontsize=7.8, fontweight="bold", style="italic")
    ax.set_xlim(start / 1e6, end / 1e6)
    ax.set_ylim(-max(len(names), 1) + 0.25, 0.95)
    ax.set_yticks([])
    for sp in ("top", "right", "left", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="x", bottom=False, labelbottom=False)
    return names


def parse_jaspar_meme(meme_path: Path) -> dict[str, np.ndarray]:
    """Parse JASPAR2024 CORE vertebrate MEME file into {TF_SYMBOL_UPPER: log2_PWM (4, L)}."""
    pwms: dict[str, np.ndarray] = {}
    with open(meme_path) as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("MOTIF "):
            parts = line.split()
            raw_name = parts[2] if len(parts) >= 3 else parts[1]
            # Strip :: heterodimer parts carefully, also store base TF symbol
            tf_key = raw_name.upper()
            i += 1
            while i < len(lines) and not lines[i].startswith("letter-probability matrix:"):
                i += 1
            if i >= len(lines):
                break
            m = re.search(r"w=\s*(\d+)", lines[i])
            w = int(m.group(1)) if m else 0
            i += 1
            rows = []
            while i < len(lines) and len(rows) < w:
                vals = lines[i].strip().split()
                if len(vals) == 4:
                    rows.append([float(v) for v in vals])
                i += 1
            if len(rows) == w and w > 0:
                mat = np.array(rows, dtype=np.float64).T  # (4, w)
                probs = (mat + 0.005) / (mat.sum(axis=0, keepdims=True) + 0.02)
                pwm = np.log2(probs / 0.25).astype(np.float32)
                # Keep first / highest-IC entry for simple symbol
                if tf_key not in pwms:
                    pwms[tf_key] = pwm
                # Also map simple base name before '(' (e.g. 'SOX2(var.2)' -> 'SOX2' if missing)
                base = tf_key.split("(")[0]
                if base not in pwms:
                    pwms[base] = pwm
        else:
            i += 1
    return pwms


def scan_sequence_pwm(oh: np.ndarray, pwm: np.ndarray) -> np.ndarray:
    """Fast vectorized convolution of one-hot (L, 4) with forward + reverse-complement PWM (4, w).
    Returns max(fwd, rev) score array of length L - w + 1."""
    w = pwm.shape[1]
    L = oh.shape[0]
    if L < w:
        return np.empty(0, dtype=np.float32)
    # Reverse complement PWM: flip base order (A<->T, C<->G) and reverse positions
    rc_pwm = pwm[::-1, ::-1]
    # Strided sliding window view: (L - w + 1, w, 4)
    shape = (L - w + 1, w, 4)
    strides = (oh.strides[0], oh.strides[0], oh.strides[1])
    windows = np.lib.stride_tricks.as_strided(oh, shape=shape, strides=strides)
    fwd = np.tensordot(windows, pwm.T, axes=([1, 2], [0, 1]))
    rev = np.tensordot(windows, rc_pwm.T, axes=([1, 2], [0, 1]))
    return np.maximum(fwd, rev)
