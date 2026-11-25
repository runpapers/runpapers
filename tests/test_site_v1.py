"""Offline tests for public website routing, markdown twins, legacy redirects, available-only filtering,
and zero public stage, badge, or tier tokens."""
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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpapers import catalog, cli, ids, mcp_server, ops, release, requests_log, site, usertest, verify  # noqa: E402
from runpapers.registry import Registry, write_json  # noqa: E402

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

TARGETS = """\
[[target]]
recipe = "fig1"
metric = "n_total"
expected = 80
tolerance = { exact = true }
source = "Table S1"
"""

QUESTIONS = "".join(
    f'[[question]]\nid = "q{i}"\nask = "Question {i}?"\nanswer = {i}\ntolerance = {{ exact = true }}\nsource = "Table S1"\n'
    for i in range(1, 4)
)


class SiteV1Tests(unittest.TestCase):
    DOI_RELEASED = "10.9999/released.pack.2026"
    DOI_UNRELEASED = "10.9999/unreleased.pack.2026"
    DOI_PLANNED = "10.9999/planned.only.2026"

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("RUNPAPERS_HOME", "RUNPAPERS_CACHE", "RUNPAPERS_NO_CAP", "RUNPAPERS_BASE")}
        self.tmp = Path(tempfile.mkdtemp(prefix="rp-site-v1-"))
        self.root = self.tmp / "reg"
        (self.root / "papers").mkdir(parents=True)
        (self.root / "collections").mkdir()
        (self.root / "runpapers.toml").write_text('name = "RunPapers"\n[publish]\ngithub_repo = "runpapers/runpapers"\n')
        shutil.copytree(ROOT / "vocab", self.root / "vocab")
        (self.root / "collections" / "bican-2026.toml").write_text(
            f'[[paper]]\ndoi = "{self.DOI_PLANNED}"\npmid = "77777777"\n'
            f'title = "Planned striatal atlas"\nfirst_author = "Pat Planner"\njournal = "Cell"\nyear = 2026\n'
            f'[paper.tags]\nspecies = ["Human"]\ntissue_cell = ["Putamen"]\ndata_type = ["Patch-seq"]\n'
        )
        os.environ["RUNPAPERS_HOME"] = str(self.root)
        os.environ["RUNPAPERS_CACHE"] = str(self.tmp / "cache")
        os.environ["RUNPAPERS_NO_CAP"] = "1"
        self.reg = Registry(self.root)

        self._create_pack(
            self.DOI_RELEASED,
            pmid="11111111",
            title="Released primate putamen multiomic atlas",
            first_author="Ada Released",
            publish=True,
        )
        self._create_pack(
            self.DOI_UNRELEASED,
            pmid="22222222",
            title="Unreleased draft caudate study",
            first_author="Ben Draft",
            publish=False,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _create_pack(self, doi, *, pmid, title, first_author, publish):
        d = self.reg.pack_dir(doi)
        (d / "recipes").mkdir(parents=True, exist_ok=True)
        (d / "evals").mkdir(exist_ok=True)
        (d / "pack.toml").write_text(
            f'spec = "runpapers/0.2"\n'
            f'[paper]\n'
            f'doi = "{doi}"\n'
            f'pmid = "{pmid}"\n'
            f'title = {json.dumps(title)}\n'
            f'first_author = {json.dumps(first_author)}\n'
            f'journal = "Cell"\n'
            f'year = 2026\n'
            f'license = "CC-BY-4.0"\n'
            f'collections = ["bican-2026"]\n'
            f'[pack]\n'
            f'version = "0.1.0"\n'
            f'summary = {json.dumps("Summary for " + title)}\n'
            f'license = "CC-BY-4.0"\n'
            f'maintainers = [{{ name = "RunPapers" }}]\n'
            f'[profile]\n'
            f'key_genes = ["SMYD2"]\n'
            f'cell_types = ["D2 SPN"]\n'
            f'[[data]]\n'
            f'id = "counts"\n'
            f'title = "Donor counts"\n'
            f'url = "https://example.org/counts.csv"\n'
            f'size = {len(CSV)}\n'
            f'md5 = "{hashlib.md5(CSV).hexdigest()}"\n'
            f'source = "Public Archive"\n'
            f'license = "CC0"\n'
            f'[[recipes]]\n'
            f'id = "fig1"\n'
            f'title = "Donor counts panel"\n'
            f'panel = "Figure 1B"\n'
            f'script = "recipes/fig1.py"\n'
            f'data = ["counts"]\n'
            f'needs = {{ memory_gb = 4, gpu = false, minutes = 2 }}\n'
        )
        (d / "targets.toml").write_text(TARGETS)
        (d / "SKILL.md").write_text(
            f"---\nname: {ids.skill_name(doi)}\ndescription: Instructions for {title}\n---\n"
            f"# {title}\n"
            f"## What this paper did and found\nProfiled human putamen donors.\n"
            f"## Data\ncounts.csv holds donor counts.\n"
            f"## Recipes\nfig1 reproduces Figure 1B.\n"
            f"## Guardrails\nDonors, not cells, are the replicates.\n"
            f"## Answering new questions\nAggregate per donor.\n"
        )
        (d / "evals" / "questions.toml").write_text(QUESTIONS)
        (d / "recipes" / "fig1.py").write_text(RECIPE)
        (d / "tags.toml").write_text(
            'species = ["Human", "Marmoset"]\n'
            'tissue_cell = ["Putamen"]\n'
            'data_type = ["Single-nucleus multiome"]\n'
            'disease = ["None (healthy donors)"]\n'
            'collection = ["BICAN basal ganglia 2026"]\n'
        )
        cache = Path(os.environ["RUNPAPERS_CACHE"]) / "data" / ids.doi_relpath(doi)
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "counts.csv").write_bytes(CSV)

        pk = self.reg.pack(doi)
        l1_dir = ops.l1_out(self.reg, pk)
        self.assertTrue(verify.run_l1(pk, ci=False, quiet=True, keep_out=l1_dir)["pass"])
        verify.record_review(pk, "pass", "reviewer")
        verify.record_signoff(pk, "approve", "RunPapers")
        h = pk.content_hash()
        write_json(d / "verify" / "usertest.json", {
            "runs": [
                {"agent": "claude", "family": "anthropic", "pass": True, "pack_hash": h, "at": "2026-11-25T10:00:00Z"},
                {"agent": "agy", "family": "google", "pass": True, "pack_hash": h, "at": "2026-11-25T10:05:00Z"},
            ]
        })
        release.build(self.reg, pk)
        if publish:
            rel_rec = json.loads((d / "verify" / "release.json").read_text())
            rel_rec["releases"][-1]["published"] = {
                "zenodo": {
                    "at": "2026-11-25T12:00:00Z",
                    "doi": "10.5281/zenodo.9999999",
                    "concept_doi": "10.5281/zenodo.9999998",
                    "url": "https://zenodo.org/records/9999999",
                },
                "github": {
                    "at": "2026-11-25T12:01:00Z",
                    "tag": f"pack/{pk.slug}/v0.1.0",
                    "url": f"https://github.com/runpapers/runpapers/releases/tag/pack/{pk.slug}/v0.1.0",
                },
            }
            write_json(d / "verify" / "release.json", rel_rec)
        else:
            # Draft-only preview must still count as unreleased on the public site.
            rel_rec = json.loads((d / "verify" / "release.json").read_text())
            rel_rec["releases"][-1]["published"] = {
                "zenodo-draft": {"at": "2026-11-25T12:00:00Z", "draft": True},
            }
            write_json(d / "verify" / "release.json", rel_rec)
        return pk

    # Canonical routes each write index.html + index.md; legacy addresses redirect; /news, /blog, /events stay free.
    def test_all_routes_twins_and_legacy_redirects(self):
        sdir = self.tmp / "built-site"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["site", "build", "--out", str(sdir), "--base-url", "https://runpapers.com"])

        rel_slug = ids.doi_slug(self.DOI_RELEASED)
        canonical_dirs = [
            sdir,
            sdir / "papers",
            sdir / "papers" / rel_slug,
            sdir / "requests",
            sdir / "guide",
            sdir / "about",
        ]
        for d in canonical_dirs:
            self.assertTrue((d / "index.html").is_file(), d)
            self.assertTrue((d / "index.md").is_file(), d)
            html_txt = (d / "index.html").read_text()
            self.assertIn('<link rel="alternate" type="text/markdown" href="index.md">', html_txt, d)

        # Legacy redirects point to canonical directory URLs.
        redirects = [
            (sdir / "doi" / ids.doi_relpath(self.DOI_RELEASED) / "index.html", f"https://runpapers.com/papers/{rel_slug}/"),
            (sdir / "guide.html", "https://runpapers.com/guide/"),
            (sdir / "requests.html", "https://runpapers.com/requests/"),
            (sdir / "about.html", "https://runpapers.com/about/"),
        ]
        for rpath, target in redirects:
            self.assertTrue(rpath.is_file(), rpath)
            rtxt = rpath.read_text()
            self.assertIn(f'url={target}', rtxt)
            self.assertIn(f'<link rel="canonical" href="{target}">', rtxt)

        # Reserved routes remain unoccupied.
        for reserved in ("news", "blog", "events"):
            self.assertFalse((sdir / reserved).exists(), reserved)

    # Zero stage, badge, or tier words anywhere in the built site; index.json has no stage or badges keys;
    # standalone RemoteCatalog, CLI, and MCP work cleanly against the v1 index.json.
    def test_no_stage_badge_or_tier_words_anywhere_in_built_site(self):
        # Log requests on released, unreleased, and planned papers so requests.json and /requests/ are exercised too.
        requests_log.vote(self.reg, self.DOI_RELEASED, by="u1")
        requests_log.vote(self.reg, self.DOI_UNRELEASED, by="u1")
        requests_log.vote(self.reg, self.DOI_PLANNED, by="u1")

        sdir, n = site.build(self.reg, out=self.tmp / "site-no-badges", base_url="https://runpapers.com")
        self.assertEqual(n, 1)

        forbidden = re.compile(r"agent-tested|reproduces:|badge|\bstage\b|\blite\b|full[- ]tier|\btier\b", re.I)
        checked_files = 0
        for p in sorted(sdir.rglob("*")):
            if p.is_file() and p.suffix not in (".png", ".woff2", ".ico"):
                txt = p.read_text(errors="ignore")
                m = forbidden.search(txt)
                self.assertIsNone(
                    m,
                    f"forbidden token {m.group(0)!r} in {p.relative_to(sdir)}" if m else "",
                )
                checked_files += 1
        self.assertGreaterEqual(checked_files, 18)

        idx = json.loads((sdir / "index.json").read_text())
        self.assertEqual(len(idx["papers"]), 1)
        paper_entry = idx["papers"][0]
        self.assertEqual(paper_entry["doi"], self.DOI_RELEASED)
        self.assertEqual(paper_entry["status"], "available")
        self.assertNotIn("stage", paper_entry)
        self.assertNotIn("badges", paper_entry)

        # Serve the built site over HTTP and verify RemoteCatalog, CLI, and MCP work without stage/badges in index.json.
        httpd = site.serve(sdir, port=0, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}"
            # Re-build with local base URL so AGENT.md and URLs match httpd.
            site.build(self.reg, out=sdir, base_url=url)
            rcat = catalog.RemoteCatalog(url, cache_dir=self.tmp / "rcache")
            saved_home = os.environ.pop("RUNPAPERS_HOME", None)
            old_cwd = os.getcwd()
            try:
                os.chdir(self.tmp)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    cli.main(["search", "SMYD2", "--source", url, "--json"])
                cli_rows = json.loads(buf.getvalue())
                self.assertEqual([r["doi"] for r in cli_rows], [self.DOI_RELEASED])

                mcp_srch = mcp_server.handle_tool_call(rcat, "search_papers", {"species": ["marmoset"]})
                self.assertFalse(mcp_srch["isError"])
                self.assertEqual(mcp_srch["structuredContent"]["matches"][0]["doi"], self.DOI_RELEASED)

                mcp_det = mcp_server.handle_tool_call(rcat, "get_paper", {"id": "11111111"})
                self.assertFalse(mcp_det["isError"])
                self.assertIsNone(mcp_det["structuredContent"]["verification_warning"])

                mcp_sk = mcp_server.handle_tool_call(rcat, "get_skill", {"id": self.DOI_RELEASED})
                self.assertFalse(mcp_sk["isError"])
                self.assertIn("Donors, not cells", mcp_sk["structuredContent"]["content_markdown"])

                mcp_recs = mcp_server.handle_tool_call(rcat, "list_recipes", {"id": self.DOI_RELEASED})
                self.assertFalse(mcp_recs["isError"])
                self.assertTrue(mcp_recs["structuredContent"]["recipes"][0]["l1_pass"])
            finally:
                os.chdir(old_cwd)
                if saved_home is not None:
                    os.environ["RUNPAPERS_HOME"] = saved_home
        finally:
            httpd.shutdown()
            httpd.server_close()

    # With one released and one unreleased pack, only the released one appears publicly;
    # zero-available-packs state and pre-release usertest preview (`include_unreleased=True`) both work cleanly.
    def test_only_released_packs_appear_publicly(self):
        sdir, n = site.build(self.reg, out=self.tmp / "site-public", base_url="https://runpapers.com")
        self.assertEqual(n, 1)

        rel_slug = ids.doi_slug(self.DOI_RELEASED)
        unrel_slug = ids.doi_slug(self.DOI_UNRELEASED)

        self.assertTrue((sdir / "papers" / rel_slug / "index.html").is_file())
        self.assertFalse((sdir / "papers" / unrel_slug).exists())
        self.assertFalse((sdir / "doi" / ids.doi_relpath(self.DOI_UNRELEASED)).exists())

        home_html = (sdir / "index.html").read_text()
        self.assertIn("Released primate putamen multiomic atlas", home_html)
        self.assertNotIn(f"papers/{unrel_slug}/", home_html)

        llms_txt = (sdir / "llms.txt").read_text()
        self.assertIn(self.DOI_RELEASED, llms_txt)
        self.assertNotIn(self.DOI_UNRELEASED, llms_txt)

        idx = json.loads((sdir / "index.json").read_text())
        self.assertEqual([p["doi"] for p in idx["papers"]], [self.DOI_RELEASED])

        # In /papers/search.json, the released pack is "available" and the unreleased pack is "in_progress" with url=None.
        sjson = json.loads((sdir / "papers" / "search.json").read_text())
        by_doi = {e["doi"]: e for e in sjson["entries"]}
        self.assertEqual(by_doi[self.DOI_RELEASED]["status"], "available")
        self.assertEqual(by_doi[self.DOI_RELEASED]["url"], f"/papers/{rel_slug}/")
        self.assertEqual(by_doi[self.DOI_UNRELEASED]["status"], "in_progress")
        self.assertIsNone(by_doi[self.DOI_UNRELEASED]["url"])
        self.assertEqual(sjson["entries"][0]["doi"], self.DOI_RELEASED)

        # Pre-release usertest builds with include_unreleased=True so an unreleased pack's AGENT.md is served locally.
        preview_dir, n_prev = site.build(self.reg, out=self.tmp / "site-preview", base_url="http://127.0.0.1", include_unreleased=True)
        self.assertEqual(n_prev, 2)
        self.assertTrue((preview_dir / "papers" / unrel_slug / "AGENT.md").is_file())
        unrel_pk = self.reg.pack(self.DOI_UNRELEASED)
        prompt = usertest.harness_prompt(unrel_pk.card(), "http://127.0.0.1", unrel_pk.evals)
        self.assertIn(f"http://127.0.0.1/papers/{unrel_slug}/AGENT.md", prompt)

        # Zero-released-packs state (remove published release from DOI_RELEASED) builds cleanly with 0 available papers.
        (self.reg.pack_dir(self.DOI_RELEASED) / "verify" / "release.json").unlink()
        empty_dir, n_empty = site.build(self.reg, out=self.tmp / "site-empty", base_url="https://runpapers.com")
        self.assertEqual(n_empty, 0)
        self.assertEqual(json.loads((empty_dir / "index.json").read_text())["papers"], [])
        self.assertIn("No packs available yet", (empty_dir / "llms.txt").read_text())
        self.assertTrue((empty_dir / "papers" / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
