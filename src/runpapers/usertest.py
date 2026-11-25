"""L3 naive-user tests: a fresh agent session, in an empty folder, gets only the paper page's copy-prompt plus
the held-out questions. It must reproduce the first laptop-runnable panel and answer; we grade its answers.json and
the recipe's own target check. Runs the user's real CLIs headless (claude -p, agy -p, codex exec)."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import ids, site
from .data import cache_root
from .recipes import compare
from .registry import read_json, write_json
from .verify import family, fits_ci, now, vdir

AGENTS = {
    "claude": lambda prompt, model: ["claude", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "json"]
    + (["--model", model] if model else []),
    "agy": lambda prompt, model: ["agy", "-p", prompt, "--dangerously-skip-permissions", "--output-format", "json"]
    + (["--model", model] if model else []),
    "codex": lambda prompt, model: ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                                    "-o", "last_message.txt"] + (["-m", model] if model else []) + [prompt],
}
KEEP_RUNS = 40


def harness_prompt(card, base, questions):
    qs = "\n".join(f"- {q['id']}: {q['ask']}" for q in questions)
    return (site.copy_prompt(card, base) +
            "\n\n(Test run, so here are my answers in advance: run it here on this computer, in the current folder; "
            "my questions are below. Don't ask me anything; I'm not available.)\n"
            "After reproducing the panel, answer these questions with the paper's data. Write your answers to the file "
            "answers.json in the current folder as a JSON object {\"<question id>\": <answer>}, numbers as plain numbers "
            "(no units, no % sign):\n" + qs + "\n")


def grade(questions, answers):
    out = {}
    for q in questions:
        a = answers.get(q["id"])
        if q.get("kind", "number") == "number":
            try:
                a = float(str(a).replace(",", "").replace("%", "").strip()) if a is not None else None
            except ValueError:
                a = None
            ok, detail = compare(q["answer"], a, q.get("tolerance", {"rel": 0.02}))
        else:
            want = [w.lower() for w in (q.get("contains_any") or [str(q["answer"])])]
            ok = a is not None and any(w in str(a).lower() for w in want)
            detail = "contains expected text" if ok else f"{a!r} lacks {want}"
        out[q["id"]] = {"ok": ok, "answer": a, "detail": detail}
    return out


def _find_result(root, rid):
    hits = sorted(Path(root).rglob(f"out/{rid}/result.json"), key=lambda p: p.stat().st_mtime)
    return read_json(hits[-1]) if hits else None


def run(reg, pack, agents, models=None, timeout_min=45, record=True, quiet=False, keep=True):
    """Run each agent once; returns the list of run records (also appended to verify/usertest.json)."""
    from .verify import status
    models = models or {}
    questions = pack.evals
    if not pack.recipes:
        raise SystemExit("no recipe to test")
    ci_recs = [r for r in pack.recipes if fits_ci(pack, r)]
    rid = (ci_recs or pack.recipes)[0]["id"]
    # Serve a fresh site build on a free local port, with the install command pointing at this source tree.
    tmp = Path(tempfile.mkdtemp(prefix="rp-site-"))
    httpd = site.serve(tmp, port=0, quiet=True)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    install = f"uvx --from {reg.root} runpapers"
    site.build(reg, out=tmp, base_url=base, install_cmd=install)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    st = status(pack)
    card = {**pack.card(), **{k: st[k] for k in ("stage", "badges")}}
    prompt = harness_prompt(card, base, questions)
    results = []
    try:
        for agent in agents:
            if agent not in AGENTS:
                raise SystemExit(f"unknown agent {agent} (have {', '.join(AGENTS)})")
            if not shutil.which(agent):
                results.append({"agent": agent, "pass": False, "error": f"{agent} not installed", "at": now()})
                continue
            box = cache_root() / "usertest" / ids.doi_relpath(pack.doi).replace("/", "_") / f"{agent}-{time.strftime('%Y%m%d-%H%M%S')}"
            box.mkdir(parents=True)
            (box / "PROMPT.txt").write_text(prompt)
            if not quiet:
                print(f"[usertest] {agent}: running in {box} (timeout {timeout_min} min)")
            t0 = time.time()
            env = {k: v for k, v in os.environ.items() if not k.startswith(("LAB_", "RUNPAPERS_HOME"))}
            err = None
            with open(box / "transcript.txt", "w") as tf:
                try:
                    p = subprocess.run(AGENTS[agent](prompt, models.get(agent)), cwd=box, env=env, stdout=tf,
                                       stderr=subprocess.STDOUT, timeout=60 * timeout_min, stdin=subprocess.DEVNULL)
                    if p.returncode != 0:
                        err = f"exit {p.returncode}"
                except subprocess.TimeoutExpired:
                    err = "timeout"
            secs = round(time.time() - t0)
            ans_files = sorted(box.rglob("answers.json"), key=lambda p: p.stat().st_mtime)
            try:
                answers = json.loads(ans_files[-1].read_text()) if ans_files else {}
            except json.JSONDecodeError:
                answers, err = {}, (err or "answers.json is not valid JSON")
            graded = grade(questions, answers)
            res = _find_result(box, rid)
            n_ok = sum(1 for g in graded.values() if g["ok"])
            need = max(1, int(round(0.8 * len(questions))))
            rec = {"agent": agent, "family": family(agent), "model": models.get(agent) or "default", "at": now(),
                   "pack_hash": pack.content_hash(), "version": pack.version, "recipe": rid,
                   "recipe_pass": bool(res and res.get("pass")), "answers": graded, "score": f"{n_ok}/{len(questions)}",
                   "pass": bool(res and res.get("pass")) and n_ok >= need, "seconds": secs, "error": err,
                   "run_id": str(box.relative_to(cache_root()))}   # transcript: $RUNPAPERS_CACHE/<run_id>/ (local only)
            results.append(rec)
            if not quiet:
                print(f"[usertest] {agent}: {'PASS' if rec['pass'] else 'FAIL'} recipe={'ok' if rec['recipe_pass'] else 'no'} "
                      f"answers {rec['score']} in {secs}s" + (f" ({err})" if err else ""))
            if not keep and rec["pass"]:
                shutil.rmtree(box, ignore_errors=True)
    finally:
        httpd.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    if record:
        path = vdir(pack) / "usertest.json"
        cur = read_json(path, {"runs": []})
        cur["runs"] = (cur.get("runs") or []) + [r for r in results if "pack_hash" in r]
        cur["runs"] = cur["runs"][-KEEP_RUNS:]
        write_json(path, cur)
    return results
