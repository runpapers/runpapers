"""Offline tests for five-group `vocab/*.toml`, hash-exempt `tags.toml`, and `rp lint` validation."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpapers import cli, ids, ops, site, spec, verify, vocab, workspace  # noqa: E402
from runpapers.registry import Registry  # noqa: E402

DOI = "10.9999/bg.tags.2026"
CSV = b"donor,group,n\nd1,A,10\nd1,B,30\nd2,A,20\nd2,B,20\n"

RECIPE = textwrap.dedent("""\
    import csv, json, os
    from pathlib import Path
    rows = list(csv.DictReader(open(Path(os.environ["RP_DATA_DIR"]) / "counts.csv")))
    tot = sum(int(r["n"]) for r in rows)
    out = Path(os.environ["RP_OUT_DIR"])
    (out / "metrics.json").write_text(json.dumps({"n_total": tot}))
    (out / "figure.png").write_bytes(b"\\x89PNG fake")
""")

PACK_TOML = f'''spec = "runpapers/0.2"
[paper]
doi = "{DOI}"
pmid = "88888888"
title = "Tagged primate basal ganglia test paper"
first_author = "Ada Tester"
journal = "Cell"
year = 2026
license = "CC-BY-4.0"
collections = ["bican-2026"]
[pack]
version = "0.1.0"
summary = "Test pack for five-group tags."
license = "CC-BY-4.0"
maintainers = [{{ name = "RunPapers" }}]
[[data]]
id = "counts"
url = "https://example.org/counts.csv"
size = {len(CSV)}
md5 = "{hashlib.md5(CSV).hexdigest()}"
source = "Test Archive"
license = "CC0"
[[recipes]]
id = "fig1"
title = "Summary counts"
panel = "Figure 1B"
script = "recipes/fig1.py"
data = ["counts"]
needs = {{ memory_gb = 4, gpu = false, minutes = 2 }}
'''

TARGETS_TOML = '''[[target]]
recipe = "fig1"
metric = "n_total"
expected = 80
tolerance = { exact = true }
source = "Table S1"
'''

SKILL_MD = f"""---
name: {ids.skill_name(DOI)}
description: Test skill
---
# Tagged primate basal ganglia test paper
## What this paper did and found
Profiled primate basal ganglia nuclei.
## Data
counts.csv holds per-donor counts.
## Recipes
fig1 reproduces Figure 1B.
## Guardrails
Donors, not cells, are the replicates.
## Answering new questions
Aggregate per donor first.
"""

QUESTIONS_TOML = "".join(
    f'[[question]]\nid = "q{i}"\nask = "Q{i}?"\nanswer = {i}\ntolerance = {{ exact = true }}\nsource = "s"\n'
    for i in range(1, 4)
)

BG03_LIKE_TAGS = '''species = ["Human", "Macaque", "Marmoset"]
tissue_cell = [
  "Caudate nucleus",
  "Putamen",
  "Nucleus accumbens",
  "Globus pallidus",
  "Subthalamic nucleus",
  "Substantia nigra",
]
data_type = ["Single-nucleus multiome", "Spatial transcriptomics", "Patch-seq"]
disease = ["None (healthy donors)"]
collection = ["BICAN basal ganglia 2026"]
'''


class TagsAndVocabTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("RUNPAPERS_HOME", "RUNPAPERS_CACHE", "RUNPAPERS_NO_CAP")}
        self.tmp = Path(tempfile.mkdtemp(prefix="rp-tags-test-"))
        self.root = self.tmp / "reg"
        (self.root / "papers").mkdir(parents=True)
        (self.root / "collections").mkdir()
        (self.root / "runpapers.toml").write_text('name = "RunPapers"\n')
        shutil.copytree(ROOT / "vocab", self.root / "vocab")
        (self.root / "collections" / "bican-2026.toml").write_text(
            '[[paper]]\ndoi = "10.9999/planned.bican.1"\npmid = "77777777"\ntitle = "Planned BICAN paper"\n'
        )
        os.environ["RUNPAPERS_HOME"] = str(self.root)
        os.environ["RUNPAPERS_CACHE"] = str(self.tmp / "cache")
        os.environ["RUNPAPERS_NO_CAP"] = "1"
        self.reg = Registry(self.root)

        d = self.reg.pack_dir(DOI)
        (d / "recipes").mkdir(parents=True)
        (d / "evals").mkdir()
        (d / "pack.toml").write_text(PACK_TOML)
        (d / "targets.toml").write_text(TARGETS_TOML)
        (d / "SKILL.md").write_text(SKILL_MD)
        (d / "evals" / "questions.toml").write_text(QUESTIONS_TOML)
        (d / "recipes" / "fig1.py").write_text(RECIPE)
        cache = Path(os.environ["RUNPAPERS_CACHE"]) / "data" / ids.doi_relpath(DOI)
        cache.mkdir(parents=True)
        (cache / "counts.csv").write_bytes(CSV)
        self.dir = d

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # `rp lint` fails on a `tags.toml` label not in `vocab/` and passes when it is.
    def test_lint_rejects_unknown_vocab_label_and_accepts_known(self):
        # Missing tags.toml emits warning `tags.missing` and zero errors during migration.
        f_missing = spec.lint(self.reg.pack(DOI), self.dir)
        self.assertEqual(spec.errors(f_missing), [])
        self.assertIn("tags.missing", {c for s, c, _ in f_missing if s == "warn"})

        # Unknown label fails `rp lint` with `tags.unknown` (and suggests canonical label when a synonym matches).
        (self.dir / "tags.toml").write_text(
            'species = ["Human", "Callithrix jacchus", "Martian"]\n'
            'data_type = ["MERFISH"]\n'
        )
        f_bad = spec.lint(self.reg.pack(DOI), self.dir)
        errs_bad = [(c, m) for s, c, m in spec.errors(f_bad)]
        self.assertTrue(any(c == "tags.unknown" and "did you mean 'Marmoset'?" in m for c, m in errs_bad), errs_bad)
        self.assertTrue(any(c == "tags.unknown" and "did you mean 'Spatial transcriptomics'?" in m for c, m in errs_bad), errs_bad)
        self.assertTrue(any(c == "tags.unknown" and "'Martian'" in m for c, m in errs_bad), errs_bad)

        # CLI `rp lint <DOI>` exits non-zero on unknown label.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx_fail:
                cli.main(["lint", "--json", DOI])
        self.assertEqual(ctx_fail.exception.code, 1)

        # Unknown tag group key fails with `tags.group`.
        (self.dir / "tags.toml").write_text('species = ["Human"]\nruns_on = ["Laptop"]\n')
        codes_grp = {c for _, c, _ in spec.errors(spec.lint(self.reg.pack(DOI), self.dir))}
        self.assertIn("tags.group", codes_grp)

        # Known labels across all five groups pass `rp lint` with zero errors and zero warnings.
        (self.dir / "tags.toml").write_text(BG03_LIKE_TAGS)
        pk = self.reg.pack(DOI)
        self.assertEqual(spec.lint(pk, self.dir), [])
        self.assertEqual(pk.tags["species"], ["Human", "Macaque", "Marmoset"])
        self.assertEqual(pk.card()["tags"]["collection"], ["BICAN basal ganglia 2026"])

        buf_ok = io.StringIO()
        with contextlib.redirect_stdout(buf_ok), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx_ok:
                cli.main(["lint", "--json", DOI])
        self.assertEqual(ctx_ok.exception.code, 0)
        self.assertEqual(json.loads(buf_ok.getvalue())[DOI], [])

    # Editing `tags.toml` does not change the pack's content hash or invalidate badges.
    def test_editing_tags_toml_preserves_pack_content_hash(self):
        pk0 = self.reg.pack(DOI)
        h0 = pk0.content_hash()
        self.assertNotIn("tags.toml", pk0.files())

        # Earn runs, checked, and reproduces badges before tags.toml exists.
        l1_dir = ops.l1_out(self.reg, pk0)
        self.assertTrue(verify.run_l1(pk0, ci=False, quiet=True, keep_out=l1_dir)["pass"])
        verify.record_review(pk0, "pass", "critic")
        verify.record_signoff(pk0, "approve", "RunPapers")
        self.assertEqual(verify.status(pk0)["stage"], "reproduces")
        ws0_dir, _ = workspace.get(DOI, dest=self.tmp / "ws-before", quiet=True)
        ws0_hash = json.loads((ws0_dir / ".runpapers.json").read_text())["pack_hash"]

        # Adding tags.toml preserves content_hash and keeps every badge current ("pass", not "stale").
        (self.dir / "tags.toml").write_text(BG03_LIKE_TAGS)
        pk1 = self.reg.pack(DOI)
        self.assertNotIn("tags.toml", pk1.files())
        self.assertEqual(pk1.content_hash(), h0)
        st1 = verify.status(pk1)
        self.assertEqual(st1["stage"], "reproduces")
        self.assertEqual(st1["badges"]["runs"], "pass")
        self.assertEqual(st1["badges"]["checked"], "pass")
        self.assertEqual(st1["badges"]["reproduces"], "pass")

        # Editing tags.toml again preserves content_hash.
        (self.dir / "tags.toml").write_text('species = ["Human", "Mouse"]\ndisease = ["Parkinson\'s disease"]\n')
        pk2 = self.reg.pack(DOI)
        self.assertEqual(pk2.content_hash(), h0)
        self.assertEqual(pk2.tags["disease"], ["Parkinson's disease"])
        self.assertEqual(pk2.tags["tissue_cell"], [])

        # Site build exposes `tags` in index.json and `workspace.get` over HTTP does not need tags.toml in pack.json.
        sdir, _ = site.build(self.reg, out=self.tmp / "site", base_url="http://127.0.0.1")
        idx = json.loads((sdir / "index.json").read_text())
        self.assertEqual(idx["papers"][0]["tags"]["species"], ["Human", "Mouse"])
        pack_json = json.loads((sdir / ids.page_path(DOI) / "pack.json").read_text())
        self.assertEqual(pack_json["pack_hash"], h0)
        self.assertFalse(any(f["path"] == "tags.toml" for f in pack_json["files"]))

        httpd = site.serve(sdir, port=0, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}"
            ws_dir, _ = workspace.get(DOI, dest=self.tmp / "ws-http", source=url, quiet=True)
            self.assertTrue((ws_dir / "SKILL.md").is_file())
            self.assertFalse((ws_dir / "tags.toml").exists())
            self.assertEqual(json.loads((ws_dir / ".runpapers.json").read_text())["pack_hash"], ws0_hash)
        finally:
            httpd.shutdown()
            httpd.server_close()

        # Removing tags.toml also leaves content_hash unchanged.
        (self.dir / "tags.toml").unlink()
        self.assertEqual(self.reg.pack(DOI).content_hash(), h0)

    def test_collection_tags_and_vocab_structure_validation(self):
        (self.dir / "tags.toml").write_text(BG03_LIKE_TAGS)

        # Planned papers in bican-2026.toml inherit default collection label and normalize explicit [paper.tags].
        (self.root / "collections" / "bican-2026.toml").write_text(
            '[[paper]]\ndoi = "10.9999/planned.bican.1"\npmid = "77777777"\ntitle = "Planned 1"\n'
            '[paper.tags]\nspecies = ["Human", "Macaque"]\ndata_type = ["Patch-seq"]\n'
        )
        planned = self.reg.planned()["10.9999/planned.bican.1"]
        self.assertEqual(planned["tags"]["species"], ["Human", "Macaque"])
        self.assertEqual(planned["tags"]["data_type"], ["Patch-seq"])
        self.assertEqual(planned["tags"]["collection"], ["BICAN basal ganglia 2026"])
        self.assertEqual(spec.lint_collections(self.reg), {})

        # Invalid collection paper tags fail `rp lint --all` with `tags.unknown` and `tags.group`.
        (self.root / "collections" / "bican-2026.toml").write_text(
            '[[paper]]\ndoi = "10.9999/planned.bican.1"\ntitle = "Planned 1"\n'
            '[paper.tags]\nspecies = ["Unicorn"]\nextra_group = ["x"]\n'
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["lint", "--all", "--json"])
        self.assertEqual(ctx.exception.code, 1)
        rep = json.loads(buf.getvalue())
        col_codes = {x["code"] for x in rep["collections/bican-2026.toml:10.9999/planned.bican.1"]}
        self.assertEqual(col_codes, {"tags.unknown", "tags.group"})

        # Restore clean collection and test vocab/*.toml structural validation (duplicate slug/label, ontology key, extra file).
        (self.root / "collections" / "bican-2026.toml").write_text(
            '[[paper]]\ndoi = "10.9999/planned.bican.1"\ntitle = "Planned 1"\n'
        )
        (self.root / "vocab" / "extra_facet.toml").write_text('[[terms]]\nslug = "x"\nlabel = "X"\n')
        (self.root / "vocab" / "disease.toml").write_text(
            '[[terms]]\nslug = "none"\nlabel = "None (healthy donors)"\nid = "MONDO:0000001"\n'
            '[[terms]]\nslug = "none"\nlabel = "Duplicate slug"\n'
        )
        _, vf = vocab.validate_dir(self.root / "vocab")
        vcodes = {c for _, c, _ in vf}
        self.assertIn("vocab.group", vcodes)
        self.assertIn("vocab.keys", vcodes)
        self.assertIn("vocab.slug", vcodes)

    def test_repo_vocab_resolver_and_synonym_expansion(self):
        voc, findings = vocab.validate_dir(ROOT / "vocab")
        self.assertEqual(findings, [])
        self.assertEqual(tuple(voc.groups), vocab.GROUPS)

        self.assertEqual(voc.resolve_slug("species", "Marmoset"), "marmoset")
        self.assertEqual(voc.resolve_label("species", "Callithrix jacchus"), "Marmoset")
        self.assertEqual(voc.resolve_label("species", "Callithrix"), "Marmoset")
        self.assertEqual(voc.resolve_label("species", "Macaca nemestrina"), "Macaque")
        self.assertEqual(voc.resolve_slug("data_type", "Patch-seq"), "patch-seq")
        self.assertEqual(voc.resolve_label("data_type", "MERFISH"), "Spatial transcriptomics")

        marm = voc.expand("marmoset", group="species")
        self.assertIn("callithrix jacchus", marm)
        self.assertIn("callithrix", marm)
        self.assertIn("marmoset", voc.expand("Callithrix"))


if __name__ == "__main__":
    unittest.main()
