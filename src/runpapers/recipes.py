"""Running a recipe (one published panel) and comparing its metrics with the paper's numbers (targets).

A recipe is a script with PEP 723 inline dependencies, run by `uv run --script` in its own throwaway
environment (plain python when uv is missing). It reads data from $RP_DATA_DIR, writes into $RP_OUT_DIR at
least metrics.json ({metric: value}) and its figure(s). Nothing else about the machine is assumed."""
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CI_LIMITS = {"cpus": 4, "mem_gb": 14, "memory_gb": 14, "gpu": False, "max_minutes": 60}
_PEAK = ("import resource,subprocess,sys;rc=subprocess.call(sys.argv[2:]);"
         "open(sys.argv[1],'w').write(str(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss));sys.exit(rc)")   # a free GitHub Actions runner; "if it runs in CI it runs on a laptop"


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def compare(expected, observed, tol):
    """-> (ok, detail). tol: {exact}|{abs: x}|{rel: x}|{range: [lo, hi]}|{set: true}."""
    if observed is None:
        return False, "metric missing from metrics.json"
    tol = tol or {"exact": True}
    try:
        if "range" in tol:
            lo, hi = tol["range"]
            ok = lo <= observed <= hi
            return ok, f"{observed} in [{lo}, {hi}]" if ok else f"{observed} outside [{lo}, {hi}]"
        if "set" in tol:
            a, b = set(map(str, expected)), set(map(str, observed))
            return a == b, "same set" if a == b else f"missing {sorted(a - b)[:5]}, extra {sorted(b - a)[:5]}"
        if "abs" in tol and _num(expected) and _num(observed):
            d = abs(observed - expected)
            return d <= tol["abs"], f"|{observed} - {expected}| = {d:.4g} (allowed {tol['abs']})"
        if "rel" in tol and _num(expected) and _num(observed):
            d = abs(observed - expected) / (abs(expected) or 1.0)
            return d <= tol["rel"], f"relative difference {d:.3%} (allowed {tol['rel']:.1%})"
        if _num(expected) and _num(observed):
            ok = math.isclose(expected, observed, rel_tol=0, abs_tol=0)
        else:
            ok = expected == observed
        return ok, "exact match" if ok else f"{observed!r} != {expected!r}"
    except TypeError as e:
        return False, f"can't compare: {e}"


def format_expected(expected, tol=None):
    """Human-readable Paper/expected target display (shows [lo, hi] for range targets)."""
    if isinstance(tol, dict) and isinstance(tol.get("range"), (list, tuple)) and len(tol["range"]) == 2:
        lo, hi = tol["range"]
        rng = f"[{lo}, {hi}]"
        if expected is None or expected == list(tol["range"]) or str(expected) == rng:
            return rng
        if _num(expected) and _num(lo) and _num(hi) and math.isclose(expected, (lo + hi) / 2, rel_tol=1e-9, abs_tol=1e-9):
            return rng
        return f"{expected} ({rng})"
    return "" if expected is None else str(expected)


def check_tolerance(check, targets=()):
    """Tolerance dict for one check row, falling back to pack targets when reading older result.json files."""
    if isinstance(check.get("tolerance"), dict):
        return check["tolerance"]
    for t in targets:
        if (t.get("metric") == check.get("metric") and t.get("expected") == check.get("expected")
                and t.get("source", "") == check.get("source", "")):
            return t.get("tolerance")
    for t in targets:
        if t.get("metric") == check.get("metric") and t.get("source", "") == check.get("source", ""):
            return t.get("tolerance")
    for t in targets:
        if t.get("metric") == check.get("metric"):
            return t.get("tolerance")
    return None


def command_for(script):
    text = Path(script).read_text(errors="replace")
    if shutil.which("uv") and "# /// script" in text:
        return ["uv", "run", "--quiet", "--script", str(script)]
    return [sys.executable, str(script)]


def capped(cmd, mem_gb, cpus):
    """Run under a memory/CPU cap like a CI runner when systemd user scopes are available."""
    if shutil.which("systemd-run") and os.environ.get("RUNPAPERS_NO_CAP") != "1":
        probe = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], capture_output=True)
        if probe.returncode == 0:
            return ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={mem_gb}G",
                    "-p", f"CPUQuota={int(cpus) * 100}%", *cmd]
    return cmd


def run(pack, rid, data_dir, out_root, ci=False, pack_dir=None, quiet=False):
    """Run recipe `rid`; returns the result dict (also written to <out>/result.json)."""
    r = pack.recipe(rid)
    base = Path(pack_dir or pack.dir)
    script = base / r["script"]
    out = Path(out_root) / rid
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    env = {**os.environ, "RP_DATA_DIR": str(data_dir), "RP_OUT_DIR": str(out), "RP_PACK_DIR": str(base),
           "RP_SEED": "0", "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg"}
    cmd = command_for(script)
    rn = pack.recipe_needs(r)
    mem = min(float(rn["memory_gb"]), CI_LIMITS["memory_gb"]) if ci else None
    if ci:
        cmd = capped(cmd, int(math.ceil(mem)), CI_LIMITS["cpus"])
    timeout = 60 * float(rn["minutes"] or 30)
    t0 = time.time()
    rss_file = out / ".peak_rss"
    cmd = [sys.executable, "-c", _PEAK, str(rss_file), *cmd]   # measures this recipe's own peak memory
    log = out / "run.log"
    status, rc = "ok", None
    with open(log, "w") as lf:
        try:
            p = subprocess.run(cmd, cwd=out, env=env, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
            rc = p.returncode
            if rc != 0:
                status = "error"
        except subprocess.TimeoutExpired:
            status = "timeout"
    secs = round(time.time() - t0, 1)
    try:
        peak_mb = round(int(rss_file.read_text()) / 1024)
        rss_file.unlink()
    except (FileNotFoundError, ValueError):
        peak_mb = None
    try:
        metrics = json.loads((out / "metrics.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        metrics = {}
        if status == "ok":
            status = "no-metrics"
    checks = []
    for t in pack.targets_for(rid):
        tol = t.get("tolerance") or {"exact": True}
        ok, detail = compare(t.get("expected"), metrics.get(t["metric"]), tol)
        checks.append({"metric": t["metric"], "expected": t.get("expected"), "observed": metrics.get(t["metric"]),
                       "tolerance": tol, "ok": ok, "detail": detail, "source": t.get("source", ""),
                       "kind": t.get("kind", "figure"), "required": t.get("required", True), "note": t.get("note", "")})
    figures = sorted(p.name for p in out.iterdir() if p.suffix.lower() in (".png", ".svg", ".pdf", ".jpg"))
    res = {"recipe": rid, "panel": r.get("panel", ""), "pack_hash": pack.content_hash(), "status": status,
           "returncode": rc, "seconds": secs, "peak_rss_mb": peak_mb, "ci": ci, "checks": checks,
           "pass": status == "ok" and any(c["required"] for c in checks) and all(c["ok"] for c in checks if c["required"]),
           "figures": figures, "log": str(log)}
    (out / "result.json").write_text(json.dumps({**res, "log": "run.log"}, indent=1) + "\n")   # no local paths in shared files
    if not quiet:
        mark = "PASS" if res["pass"] else "FAIL"
        print(f"{mark} {rid} ({r.get('panel', '')}) in {secs}s: "
              + (f"{sum(c['ok'] for c in checks if c['required'])}/{sum(c['required'] for c in checks)} required targets met"
                 + (f", {sum(not c['ok'] for c in checks if not c['required'])} known discrepancy(ies)" if any(not c['required'] for c in checks) else "")
                 if checks else status)
              + ("" if status == "ok" else f" [{status}; see {log}]"), file=sys.stderr)
    return res
