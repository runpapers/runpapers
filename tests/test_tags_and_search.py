"""Offline tests for five-group `vocab/*.toml`, hash-exempt `tags.toml`, `rp lint`, and unified 5-group search."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import threading
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpapers import catalog, cli, ids, mcp_server, ops, requests_log, search, site, spec, verify, vocab, workspace  # noqa: E402
from runpapers.registry import Pack, Registry  # noqa: E402

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
        self.assertNotIn("nhp", marm)
        self.assertNotIn("nonhuman primate", marm)
        self.assertIn("marmoset", voc.expand("Callithrix"))
        self.assertNotIn("nhp", voc.expand("Callithrix"))
        # Shared umbrella synonyms expand to all member terms only when queried directly.
        nhp = voc.expand("NHP", group="species")
        self.assertIn("macaque", nhp)
        self.assertIn("marmoset", nhp)
        self.assertNotIn("strd", voc.expand("putamen", group="tissue_cell"))
        self.assertTrue({"caudate nucleus", "putamen"} <= voc.expand("STRd", group="tissue_cell"))

        # Deduplicate repeated labels in normalize_tags and allow Pack(".") lint from inside a pack directory.
        dedup = vocab.normalize_tags({"species": ["Human", "Marmoset", "Human"], "disease": ["None (healthy donors)", "None (healthy donors)"]})
        self.assertEqual(dedup["species"], ["Human", "Marmoset"])
        self.assertEqual(dedup["disease"], ["None (healthy donors)"])

        (self.dir / "tags.toml").write_text(BG03_LIKE_TAGS)
        old_cwd = os.getcwd()
        try:
            os.chdir(self.dir)
            self.assertEqual(spec.lint(Pack(".")), [])
        finally:
            os.chdir(old_cwd)

        # Wheel packaging bundles vocab/*.toml into runpapers/_vocab for standalone installs.
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"], {"vocab": "runpapers/_vocab"})

    def _add_pack(self, doi, *, pmid, title, first_author, year=2026, preprint_doi=None, key_genes=(), cell_types=(), tags_toml=""):
        d = self.reg.pack_dir(doi)
        (d / "recipes").mkdir(parents=True, exist_ok=True)
        (d / "evals").mkdir(exist_ok=True)
        pre_line = f'preprint_doi = "{preprint_doi}"\n' if preprint_doi else ""
        (d / "pack.toml").write_text(
            f'spec = "runpapers/0.2"\n'
            f'[paper]\n'
            f'doi = "{doi}"\n'
            f'pmid = "{pmid}"\n'
            f'{pre_line}'
            f'title = {json.dumps(title)}\n'
            f'first_author = {json.dumps(first_author)}\n'
            f'journal = "Cell"\n'
            f'year = {year}\n'
            f'license = "CC-BY-4.0"\n'
            f'collections = ["bican-2026"]\n'
            f'[pack]\n'
            f'version = "0.1.0"\n'
            f'summary = {json.dumps("Verified summary for " + title)}\n'
            f'license = "CC-BY-4.0"\n'
            f'maintainers = [{{ name = "RunPapers" }}]\n'
            f'[profile]\n'
            f'key_genes = {json.dumps(list(key_genes))}\n'
            f'cell_types = {json.dumps(list(cell_types))}\n'
            f'[[data]]\n'
            f'id = "counts"\n'
            f'url = "https://example.org/counts.csv"\n'
            f'size = {len(CSV)}\n'
            f'md5 = "{hashlib.md5(CSV).hexdigest()}"\n'
            f'source = "Test Archive"\n'
            f'license = "CC0"\n'
            f'[[recipes]]\n'
            f'id = "fig1"\n'
            f'title = "Summary counts"\n'
            f'panel = "Figure 1B"\n'
            f'script = "recipes/fig1.py"\n'
            f'data = ["counts"]\n'
            f'needs = {{ memory_gb = 4, gpu = false, minutes = 2 }}\n'
        )
        (d / "targets.toml").write_text(TARGETS_TOML)
        (d / "SKILL.md").write_text(SKILL_MD.replace(ids.skill_name(DOI), ids.skill_name(doi)))
        (d / "evals" / "questions.toml").write_text(QUESTIONS_TOML)
        (d / "recipes" / "fig1.py").write_text(RECIPE)
        if tags_toml:
            (d / "tags.toml").write_text(tags_toml)
        cache = Path(os.environ["RUNPAPERS_CACHE"]) / "data" / ids.doi_relpath(doi)
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "counts.csv").write_bytes(CSV)
        return self.reg.pack(doi)

    def _cli_search_dois(self, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["search", *args, "--json"])
        return [r["doi"] for r in json.loads(buf.getvalue())]

    # Searching "marmoset", "Callithrix", the DOI, the PMID or "SMYD2" finds the primate basal ganglia pack
    # without cross-species/umbrella false positives or mid-word acronym false positives;
    # papers/search.json contains zero tier, stage, or badge strings.
    def test_search_finds_bg03_by_common_scientific_doi_pmid_and_gene(self):
        bg03_doi = "10.1016/j.cell.2026.10.012"
        macaque_only_doi = "10.9999/macaque.only.2026"
        caudate_only_doi = "10.9999/caudate.only.2026"
        self._add_pack(
            bg03_doi,
            pmid="43020019",
            preprint_doi="10.64898/2025.12.15.694496",
            title="Cross-species multiomic atlas of the primate basal ganglia",
            first_author="Nelson J. Johansen",
            key_genes=["SMYD2", "HTR7", "DRD2"],
            cell_types=["D2 SPN", "astrocyte"],
            tags_toml=BG03_LIKE_TAGS,
        )
        # Macaque-only cortex pack (shares umbrella synonym "NHP" with Marmoset, but has zero Marmoset).
        self._add_pack(
            macaque_only_doi,
            pmid="43020091",
            title="Rhesus macaque cortical Patch-seq map",
            first_author="Mina Macaque",
            tags_toml=(
                'species = ["Macaque"]\n'
                'tissue_cell = ["Cerebral cortex"]\n'
                'data_type = ["Patch-seq"]\n'
                'disease = ["None (healthy donors)"]\n'
            ),
        )
        # Caudate-only human pack (shares umbrella synonym "STRd" with Putamen, but has zero Putamen).
        self._add_pack(
            caudate_only_doi,
            pmid="43020092",
            title="Integrated caudate atlas across human individuals and mammals",
            first_author="Ada Tester",
            tags_toml=(
                'species = ["Human"]\n'
                'tissue_cell = ["Caudate nucleus"]\n'
                'data_type = ["Single-nucleus RNA-seq"]\n'
                'disease = ["None (healthy donors)"]\n'
            ),
        )
        # Healthy adult mouse snRNA-seq pack containing words with mid-word substrings ("Adult", "broad", "Ada", "snrna-seq").
        (self.dir / "pack.toml").write_text(
            PACK_TOML.replace(
                'title = "Tagged primate basal ganglia test paper"',
                'title = "Adult mouse cortex broad transcriptomic map"',
            )
        )
        (self.dir / "tags.toml").write_text(
            'species = ["Mouse"]\n'
            'tissue_cell = ["Cerebral cortex"]\n'
            'data_type = ["Single-nucleus RNA-seq"]\n'
            'disease = ["None (healthy donors)"]\n'
        )
        sdir, _ = site.build(self.reg, out=self.tmp / "site-ac3", base_url="http://127.0.0.1")
        search_json_path = sdir / "papers" / "search.json"
        self.assertTrue(search_json_path.is_file())
        raw_search_json = search_json_path.read_text()
        self.assertIsNone(
            re.search(r"\b(lite|full|tier|tiers|tiered|stage|badges|badge)\b", raw_search_json, re.I),
            raw_search_json[:400],
        )
        sidx = json.loads(raw_search_json)
        self.assertEqual(tuple(sidx["vocab"]), vocab.GROUPS)
        lcat = catalog.LocalCatalog(self.reg)

        # 1. Exact BG-03 lookups: "marmoset" and "Callithrix" MUST NOT match macaque_only_doi via "NHP".
        for q in (
            "marmoset",
            "Callithrix",
            "Callithrix jacchus",
            bg03_doi,
            "43020019",
            "PMID: 43020019",
            "10.64898/2025.12.15.694496",
            "SMYD2",
            "MERFISH",
            "SN",
        ):
            res_page = search.filter_search_index(sidx, query=q)
            self.assertEqual([e["doi"] for e in res_page["entries"]], [bg03_doi], q)
            self.assertEqual(self._cli_search_dois([q]), [bg03_doi], q)
            mcp_hits = mcp_server.handle_tool_call(lcat, "search_papers", {"query": q})
            self.assertEqual([m["doi"] for m in mcp_hits["structuredContent"]["matches"]], [bg03_doi], q)

        # 2. "putamen" matches BG-03 only (NOT caudate_only_doi via shared "STRd");
        #    umbrella queries "NHP" and "STRd" match both respective packs.
        self.assertEqual([e["doi"] for e in search.filter_search_index(sidx, query="putamen")["entries"]], [bg03_doi])
        self.assertEqual(
            set(e["doi"] for e in search.filter_search_index(sidx, query="NHP")["entries"]),
            {bg03_doi, macaque_only_doi},
        )
        self.assertEqual(
            set(e["doi"] for e in search.filter_search_index(sidx, query="STRd")["entries"]),
            {bg03_doi, caudate_only_doi},
        )

        # 3. Short acronyms and disease/species terms do NOT match mid-word substrings
        #    ("Alzheimer"/"ad" vs "Adult"/"broad"/"Ada", "rat" vs "Integrated", "ALS" vs "individuals"/"mammals").
        for absent_q in ("Alzheimer", "ALS", "rat"):
            self.assertEqual(search.filter_search_index(sidx, query=absent_q)["entries"], [], absent_q)
            self.assertEqual(self._cli_search_dois([absent_q]), [], absent_q)
            mcp_none = mcp_server.handle_tool_call(lcat, "search_papers", {"query": absent_q})
            self.assertEqual(mcp_none["structuredContent"]["matches"], [], absent_q)

    # A requested paper (GitHub issue with votes) appears after all available papers with its vote count.
    def test_requested_papers_rank_after_available_with_votes(self):
        (self.dir / "tags.toml").write_text(BG03_LIKE_TAGS)
        second_avail = "10.9999/avail.striatum.2025"
        self._add_pack(
            second_avail,
            pmid="55555555",
            title="Available human striatum multiomic study",
            first_author="Bea Builder",
            year=2025,
            tags_toml='species = ["Human"]\ntissue_cell = ["Striatum"]\ndata_type = ["Single-nucleus multiome"]\ndisease = ["None (healthy donors)"]\n',
        )
        (self.root / "collections" / "bican-2026.toml").write_text(
            '[[paper]]\ndoi = "10.9999/planned.bican.1"\npmid = "77777777"\n'
            'title = "Planned basal ganglia striatum study"\nyear = 2026\n'
            '[paper.tags]\nspecies = ["Human"]\ntissue_cell = ["Striatum"]\n'
            '[[paper]]\ndoi = "10.9999/inprog.bican.2"\npmid = "77777778"\n'
            'title = "In-progress basal ganglia study"\nyear = 2026\nstatus = "in_progress"\n'
            '[[paper]]\ndoi = "10.9999/notposs.bican.3"\npmid = "77777779"\n'
            'title = "Closed basal ganglia study"\nyear = 2026\nstatus = "not_possible"\n'
            'status_reason = "No open source data deposited"\n'
        )
        issues = [
            {
                "number": 10,
                "html_url": "https://github.com/runpapers/runpapers/issues/10",
                "title": "Paper request: 10.1234/requested.ganglia.2026",
                "body": "### DOI or PMID\n\n10.1234/requested.ganglia.2026\n",
                "state": "open",
                "created_at": "2026-11-10T00:00:00Z",
                "reactions": {"+1": 11},  # 1 + 11 = 12 votes
            },
            {
                "number": 11,
                "html_url": "https://github.com/runpapers/runpapers/issues/11",
                "title": "Paper request: 10.9999/planned.bican.1",
                "body": "### DOI or PMID\n\n10.9999/planned.bican.1\n",
                "state": "open",
                "created_at": "2026-11-11T00:00:00Z",
                "reactions": {"+1": 4},  # 1 + 4 = 5 votes
            },
        ]
        requests_log.sync_github(
            self.reg,
            "runpapers/runpapers",
            fetch=lambda u, tok: issues if "page=1" in u else [],
            resolve_online=False,
        )

        sdir, _ = site.build(self.reg, out=self.tmp / "site-ac5", base_url="http://127.0.0.1")
        sidx = json.loads((sdir / "papers" / "search.json").read_text())
        entries = sidx["entries"]

        # All available packs rank strictly ahead of all non-available papers, even when requests have more votes.
        statuses = [e["status"] for e in entries]
        last_avail = max(i for i, st in enumerate(statuses) if st == "available")
        first_non_avail = min(i for i, st in enumerate(statuses) if st != "available")
        self.assertLess(last_avail, first_non_avail, statuses)
        self.assertEqual({e["doi"] for e in entries[:first_non_avail]}, {DOI, second_avail})

        non_avail = entries[first_non_avail:]
        self.assertEqual(non_avail[0]["doi"], "10.1234/requested.ganglia.2026")
        self.assertEqual(non_avail[0]["status"], "requested")
        self.assertEqual(non_avail[0]["votes"], 12)
        self.assertEqual(non_avail[0]["issue_url"], "https://github.com/runpapers/runpapers/issues/10")
        self.assertIsNone(non_avail[0]["url"])

        self.assertEqual(non_avail[1]["doi"], "10.9999/planned.bican.1")
        self.assertEqual(non_avail[1]["votes"], 5)
        self.assertEqual(non_avail[1]["issue_url"], "https://github.com/runpapers/runpapers/issues/11")

        by_doi = {e["doi"]: e for e in non_avail}
        self.assertEqual(by_doi["10.9999/inprog.bican.2"]["status"], "in_progress")
        self.assertEqual(by_doi["10.9999/notposs.bican.3"]["status"], "not_possible")
        self.assertEqual(by_doi["10.9999/notposs.bican.3"]["status_reason"], "No open source data deposited")

        # Even on a text query matching both available and high-vote requested papers ("ganglia"), available comes first.
        q_page = [e["doi"] for e in search.filter_search_index(sidx, query="ganglia")["entries"]]
        self.assertEqual(q_page[0], DOI)
        self.assertEqual(q_page[1], "10.1234/requested.ganglia.2026")
        self.assertEqual(self._cli_search_dois(["ganglia"]), q_page)
        mcp_q = mcp_server.handle_tool_call(catalog.LocalCatalog(self.reg), "search_papers", {"query": "ganglia"})
        self.assertEqual([m["doi"] for m in mcp_q["structuredContent"]["matches"]], q_page)

    # `rp search --species marmoset --json` and MCP `search_papers` return the exact same DOIs as `search.json` filtering
    # (both locally and via standalone `RemoteCatalog` over HTTP).
    def test_cli_mcp_and_search_json_return_identical_dois(self):
        (self.dir / "tags.toml").write_text(BG03_LIKE_TAGS)
        doi_marm_rna = "10.9999/marmoset.rna.2025"
        self._add_pack(
            doi_marm_rna,
            pmid="66666661",
            title="Marmoset cortex single-nucleus RNA atlas",
            first_author="Cara Cortex",
            year=2025,
            tags_toml=(
                'species = ["Marmoset"]\n'
                'tissue_cell = ["Cerebral cortex"]\n'
                'data_type = ["Single-nucleus RNA-seq"]\n'
                'disease = ["None (healthy donors)"]\n'
            ),
        )
        doi_mouse_pd = "10.9999/mouse.pd.2026"
        self._add_pack(
            doi_mouse_pd,
            pmid="66666662",
            title="Mouse substantia nigra Parkinson model",
            first_author="Dan Dopamine",
            year=2026,
            tags_toml=(
                'species = ["Mouse"]\n'
                'tissue_cell = ["Substantia nigra"]\n'
                'data_type = ["Patch-seq"]\n'
                'disease = ["Parkinson\'s disease"]\n'
            ),
        )
        (self.root / "collections" / "bican-2026.toml").write_text(
            '[[paper]]\ndoi = "10.9999/planned.marmoset.patch"\npmid = "77777771"\n'
            'title = "Planned marmoset striatal Patch-seq study"\nyear = 2026\n'
            '[paper.tags]\nspecies = ["Marmoset", "Human"]\ntissue_cell = ["Putamen"]\ndata_type = ["Patch-seq"]\n'
        )
        requests_log.vote(self.reg, "10.9999/planned.marmoset.patch", by="scientist1")

        # Add a custom term in the registry's vocab/ to confirm RemoteCatalog hydrates `vocab` from `index.json`.
        with open(self.root / "vocab" / "species.toml", "a") as fh:
            fh.write('\n[[terms]]\nslug = "zebra-finch"\nlabel = "Zebra finch"\nscientific_name = "Taeniopygia guttata"\nsynonyms = ["songbird"]\n')
        doi_finch = "10.9999/finch.2026"
        self._add_pack(
            doi_finch,
            pmid="66666663",
            title="Songbird basal ganglia nucleus X",
            first_author="Eve Finch",
            year=2026,
            tags_toml='species = ["Zebra finch"]\ntissue_cell = ["Basal ganglia"]\ndata_type = ["Patch-seq"]\ndisease = ["None (healthy donors)"]\n',
        )

        sdir, _ = site.build(self.reg, out=self.tmp / "site-ac7", base_url="http://127.0.0.1")
        sidx = json.loads((sdir / "papers" / "search.json").read_text())
        lcat = catalog.LocalCatalog(self.reg)

        cases = [
            # 1. Single species filter (slug)
            (
                {"species": ["marmoset"]},
                ["--species", "marmoset"],
                {"species": ["marmoset"]},
                [DOI, doi_marm_rna, "10.9999/planned.marmoset.patch"],
            ),
            # 2. Cross-group AND: Species = Marmoset AND Data type = Patch-seq (available first, then planned)
            (
                {"species": ["Marmoset"], "data_type": ["Patch-seq"]},
                ["--species", "marmoset", "--data-type", "patch-seq"],
                {"species": ["marmoset"], "data_type": ["patch-seq"]},
                [DOI, "10.9999/planned.marmoset.patch"],
            ),
            # 3. Within-group OR + cross-group AND: Species in (Marmoset OR Mouse) AND Data type = Patch-seq
            #    ("Mouse..." sorts before "Tagged..." on equal year=2026 by title asc, both ahead of planned)
            (
                {"species": ["marmoset", "mouse"], "data_type": ["patch-seq"]},
                ["--species", "marmoset", "--species", "mouse", "--data-type", "patch-seq"],
                {"species": ["marmoset", "mouse"], "data_type": ["patch-seq"]},
                [doi_mouse_pd, DOI, "10.9999/planned.marmoset.patch"],
            ),
            # 4. All five groups + CLI/MCP legacy tissue/assay aliases
            (
                {"species": ["human"], "tissue_cell": ["putamen"], "data_type": ["single-nucleus-multiome"],
                 "disease": ["none"], "collection": ["bican-2026"]},
                ["--species", "human", "--tissue", "putamen", "--assay", "Single-nucleus multiome",
                 "--disease", "None (healthy donors)", "--collection", "bican-2026"],
                {"species": ["Human"], "tissues": ["Putamen"], "assays": ["Single-nucleus multiome"],
                 "disease": ["none"], "collection": ["BICAN basal ganglia 2026"]},
                [DOI],
            ),
            # 5. Custom registry vocab synonym ("Taeniopygia guttata") resolved via index.json on RemoteCatalog
            (
                {"query": "Taeniopygia"},
                ["Taeniopygia"],
                {"query": "Taeniopygia"},
                [doi_finch],
            ),
        ]

        httpd = site.serve(sdir, port=0, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}"
            rcat = catalog.RemoteCatalog(url, cache_dir=self.tmp / "rcache-ac7")
            for page_kw, cli_args, mcp_args, expected_dois in cases:
                res_page = search.filter_search_index(sidx, **page_kw)
                page_dois = [e["doi"] for e in res_page["entries"]]
                self.assertEqual(page_dois, expected_dois, page_kw)

                # Facet counts in filter_search_index match visible results.
                for g in vocab.GROUPS:
                    for term in sidx["vocab"][g]:
                        slug = term["slug"]
                        want_n = sum(1 for e in res_page["entries"] if slug in e["tag_slugs"][g])
                        self.assertEqual(res_page["counts"][g][slug], want_n, (g, slug, page_kw))

                # Local CLI & Local MCP match page filter.
                self.assertEqual(self._cli_search_dois(cli_args), page_dois, cli_args)
                mcp_local = mcp_server.handle_tool_call(lcat, "search_papers", mcp_args)
                self.assertEqual([m["doi"] for m in mcp_local["structuredContent"]["matches"]], page_dois, mcp_args)

                # Standalone RemoteCatalog CLI & MCP (with RUNPAPERS_HOME unset) match page filter identically.
                saved_home = os.environ.pop("RUNPAPERS_HOME", None)
                old_cwd = os.getcwd()
                try:
                    os.chdir(self.tmp)
                    self.assertEqual(self._cli_search_dois([*cli_args, "--source", url]), page_dois, cli_args)
                    mcp_remote = mcp_server.handle_tool_call(rcat, "search_papers", mcp_args)
                    self.assertEqual([m["doi"] for m in mcp_remote["structuredContent"]["matches"]], page_dois, mcp_args)
                finally:
                    os.chdir(old_cwd)
                    if saved_home is not None:
                        os.environ["RUNPAPERS_HOME"] = saved_home
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
