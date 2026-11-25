"""Offline tests for `rp search`, `rp mcp` (Skills over MCP), `RemoteCatalog`, and `rp meeting`."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runpapers import catalog, ids, mcp_server, meeting, release, search, site, verify  # noqa: E402
from runpapers.registry import Registry  # noqa: E402

CSV_BYTES = b"donor,group,n\nd1,A,10\nd1,B,30\nd2,A,20\nd2,B,20\n"
CSV_MD5 = hashlib.md5(CSV_BYTES).hexdigest()
SECRET_EVAL = "TOP_SECRET_EVAL_ANSWER_98765"

RECIPE_SRC = textwrap.dedent("""\
    import csv, json, os
    from pathlib import Path
    rows = list(csv.DictReader(open(Path(os.environ["RP_DATA_DIR"]) / "counts.csv")))
    tot = sum(int(r["n"]) for r in rows)
    out = Path(os.environ["RP_OUT_DIR"])
    (out / "metrics.json").write_text(json.dumps({"n_total": tot}))
    (out / "figure.png").write_bytes(b"\\x89PNG fake")
""")

TARGETS_SRC = """\
[[target]]
recipe = "fig1"
metric = "n_total"
expected = 80
tolerance = { exact = true }
source = "main text p.2"

[[target]]
recipe = "fig1"
metric = "n_total"
expected = 75
tolerance = { exact = true }
source = "main text p.4"
required = false
note = "known discrepancy between text and table"
"""


def _make_pack(reg, cache_dir, *, doi, pmid, citekey, title, first_author, profile, data_license, run_l1=True, extra_ref=False):
    d = reg.pack_dir(doi)
    (d / "recipes").mkdir(parents=True)
    (d / "evals").mkdir()
    prof_lines = "\n".join(f"{k} = {json.dumps(v)}" for k, v in profile.items())
    (d / "pack.toml").write_text(
        f'spec = "runpapers/0.2"\n'
        f'[paper]\n'
        f'doi = "{doi}"\n'
        f'pmid = "{pmid}"\n'
        f'title = {json.dumps(title)}\n'
        f'first_author = {json.dumps(first_author)}\n'
        f'senior_author = "Senior Researcher"\n'
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
        f'{prof_lines}\n'
        f'[[data]]\n'
        f'id = "counts"\n'
        f'title = "Counts table"\n'
        f'url = "https://example.org/counts.csv"\n'
        f'size = {len(CSV_BYTES)}\n'
        f'md5 = "{CSV_MD5}"\n'
        f'source = "Test Archive v1"\n'
        f'license = {json.dumps(data_license)}\n'
        f'[[recipes]]\n'
        f'id = "fig1"\n'
        f'title = "Summary counts"\n'
        f'panel = "Figure 1B"\n'
        f'script = "recipes/fig1.py"\n'
        f'data = ["counts"]\n'
        f'needs = {{ memory_gb = 4, gpu = false, minutes = 2 }}\n'
    )
    (d / "targets.toml").write_text(TARGETS_SRC)
    (d / "SKILL.md").write_text(
        f"---\nname: {ids.skill_name(doi)}\ndescription: Skill for {title}\n---\n"
        f"# {title}\n\n"
        f"## What this paper did and found\nProfiled nuclei.\n\n"
        f"## Data\ncounts.csv has donor and group counts.\n\n"
        f"## Recipes\nfig1 reproduces Figure 1B.\n\n"
        f"## Guardrails\nDonors, not cells, are the replicates ({citekey}).\n\n"
        f"## Answering new questions\nGroup by donor first.\n"
    )
    (d / "evals" / "questions.toml").write_text(
        f'[[question]]\nid = "q1"\nask = "Secret?"\nanswer = "{SECRET_EVAL}"\nkind = "text"\nsource = "s"\n'
        f'[[question]]\nid = "q2"\nask = "Total?"\nanswer = 80\ntolerance = {{ exact = true }}\nsource = "s"\n'
        f'[[question]]\nid = "q3"\nask = "Donors?"\nanswer = 2\ntolerance = {{ exact = true }}\nsource = "s"\n'
    )
    (d / "recipes" / "fig1.py").write_text(RECIPE_SRC)
    if extra_ref:
        (d / "references").mkdir()
        (d / "references" / "notes.md").write_text("# Detailed taxonomy notes\n\nReference content for progressive disclosure.\n")
    cdir = cache_dir / "data" / ids.doi_relpath(doi)
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "counts.csv").write_bytes(CSV_BYTES)
    pk = reg.pack(doi)
    if run_l1:
        rec = verify.run_l1(pk, ci=False, quiet=True, keep_out=reg.root / "build" / "l1" / ids.doi_relpath(doi))
        assert rec["pass"], rec
    return pk


class McpAndMeetingTests(unittest.TestCase):
    DOI_A = "10.9999/bg.spn.2026"
    DOI_B = "10.9999/bg.patch.2026"
    DOI_C = "10.9999/mouse.unverified.2026"
    DOI_PLANNED = "10.9999/planned.astro.2026"

    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in ("RUNPAPERS_HOME", "RUNPAPERS_CACHE", "RUNPAPERS_CONFIG", "RUNPAPERS_NO_CAP", "RUNPAPERS_BASE")}
        self.tmp = Path(tempfile.mkdtemp(prefix="rp-mcp-test-"))
        self.root = self.tmp / "reg"
        self.cache = self.tmp / "cache"
        self.cfg = self.tmp / "config"
        (self.root / "papers").mkdir(parents=True)
        (self.root / "collections").mkdir()
        (self.root / "runpapers.toml").write_text('name = "RunPapers"\n[publish]\ngithub_repo = "runpapers/runpapers"\n')
        (self.root / "collections" / "bican-2026.toml").write_text(
            f'[[paper]]\ndoi = "{self.DOI_PLANNED}"\npmid = "44444444"\n'
            f'title = "Striatal D2 SPN and astrocyte circuit interactions in primates"\n'
            f'first_author = "Dana Planner"\njournal = "Cell"\nyear = 2026\n'
        )
        os.environ["RUNPAPERS_HOME"] = str(self.root)
        os.environ["RUNPAPERS_CACHE"] = str(self.cache)
        os.environ["RUNPAPERS_CONFIG"] = str(self.cfg)
        os.environ["RUNPAPERS_NO_CAP"] = "1"
        self.reg = Registry(self.root)

        allen_terms = "Allen Institute Terms of Use: noncommercial research use, cite per the Allen Citation Policy (https://alleninstitute.org/terms-of-use/)"
        _make_pack(
            self.reg, self.cache,
            doi=self.DOI_A, pmid="11111111", citekey="spn2026",
            title="Primate striatal spiny projection neuron atlas",
            first_author="Alice Atlas",
            profile={
                "species": ["Homo sapiens", "Macaca mulatta", "Callithrix jacchus"],
                "tissues": ["caudate nucleus", "putamen"],
                "assays": ["10x Multiome snRNA-seq", "MERSCOPE"],
                "cell_types": ["spiny projection neuron", "D2 SPN"],
                "key_genes": ["SMYD2", "HTR7", "DRD2"],
            },
            data_license=allen_terms,
            run_l1=True,
            extra_ref=True,
        )
        _make_pack(
            self.reg, self.cache,
            doi=self.DOI_B, pmid="22222222", citekey="patch2026",
            title="Morphoelectric specialization of putamen D2 SPNs and astrocytes",
            first_author="Bob Patch",
            profile={
                "species": ["Homo sapiens", "Macaca nemestrina"],
                "tissues": ["putamen", "globus pallidus"],
                "assays": ["Patch-seq", "10x Multiome snRNA-seq"],
                "cell_types": ["D2 SPN", "astrocyte"],
                "key_genes": ["DRD2", "KCNC1"],
            },
            data_license="CC-BY-4.0",
            run_l1=True,
            extra_ref=False,
        )
        _make_pack(
            self.reg, self.cache,
            doi=self.DOI_C, pmid="33333333", citekey="mouse2026",
            title="Unverified murine spinal cord draft",
            first_author="Carol Draft",
            profile={
                "species": ["Mus musculus"],
                "tissues": ["spinal cord"],
                "assays": ["10x Multiome snRNA-seq"],
                "cell_types": ["motor neuron"],
                "key_genes": ["CHAT"],
            },
            data_license="CC0",
            run_l1=False,
            extra_ref=False,
        )
        self.cat = catalog.LocalCatalog(self.reg)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # 1. Profile ranking, biological synonyms, multi-facet AND filtering, min_stage, and CLI search
    def test_search_profile_ranking_and_facets(self):
        entries = self.cat.entries(include_planned=True)
        hits_gene = search.search_entries(entries, query="HTR7")
        self.assertEqual(hits_gene[0][1]["doi"], self.DOI_A)

        # Colloquial 'marmoset' matches ontology 'Callithrix jacchus'
        hits_marm = search.search_entries(entries, species=["marmoset"])
        self.assertEqual([e["doi"] for _, e in hits_marm], [self.DOI_A])

        # Multi-facet AND filtering narrows to the exact intersection
        hits_and = search.search_entries(entries, species=["human"], tissues=["putamen"], assays=["Patch-seq"])
        self.assertEqual([e["doi"] for _, e in hits_and], [self.DOI_B])

        # min_stage='runs' excludes unverified 'ready' pack C and 'planned' paper D
        hits_verified = search.search_entries(entries, min_stage="runs")
        self.assertEqual({e["doi"] for _, e in hits_verified}, {self.DOI_A, self.DOI_B})

        # Exact PMID fast-path
        hits_pmid = search.search_entries(entries, query="PMID: 22222222")
        self.assertGreaterEqual(hits_pmid[0][0], 1000.0)
        self.assertEqual(hits_pmid[0][1]["doi"], self.DOI_B)

        # CLI `rp search --json`
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        r = subprocess.run([sys.executable, "-m", "runpapers.cli", "search", "HTR7", "--gene", "SMYD2", "--json"],
                           env=env, capture_output=True, text=True, check=True)
        rows = json.loads(r.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doi"], self.DOI_A)

    # 2. Subprocess stdio JSON-RPC 2.0 handshake, notifications, discovery, and zero stray stdout bytes
    def test_mcp_stdio_handshake_and_discovery(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        proc = subprocess.Popen(
            [sys.executable, "-m", "runpapers.cli", "mcp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )
        try:
            reqs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
                {"jsonrpc": "2.0", "id": 5, "method": "resources/templates/list"},
                {"jsonrpc": "2.0", "id": 6, "method": "prompts/list"},
                {"jsonrpc": "2.0", "id": 7, "method": "prompts/get",
                 "params": {"name": "use_paper", "arguments": {"id": "11111111", "question": "How many donors?"}}},
            ]
            stdout_data, stderr_data = proc.communicate("\n".join(json.dumps(x) for x in reqs) + "\n", timeout=15)
        finally:
            proc.kill()
            proc.wait()

        self.assertEqual(proc.returncode, 0, stderr_data)
        lines = [ln for ln in stdout_data.splitlines() if ln.strip()]
        # 7 requests + 1 notification -> exactly 7 JSON-RPC response lines and zero stray bytes
        self.assertEqual(len(lines), 7, stdout_data)
        by_id = {obj["id"]: obj for obj in (json.loads(ln) for ln in lines)}

        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "runpapers")
        self.assertEqual(by_id[2]["result"], {})

        tool_names = [t["name"] for t in by_id[3]["result"]["tools"]]
        self.assertEqual(tool_names, ["search_papers", "get_paper", "get_skill", "list_recipes", "request_paper"])

        res_uris = {r["uri"] for r in by_id[4]["result"]["resources"]}
        self.assertIn(f"skill://runpapers/{self.DOI_A}/SKILL.md", res_uris)
        spn_res = next(r for r in by_id[4]["result"]["resources"] if self.DOI_A in r["uri"])
        self.assertIn("Allen Institute Terms of Use", spn_res["description"])

        tpl_uris = {t["uriTemplate"] for t in by_id[5]["result"]["resourceTemplates"]}
        self.assertIn("skill://runpapers/{doi_prefix}/{doi_suffix}/SKILL.md", tpl_uris)
        self.assertIn("skill://runpapers/{doi_prefix}/{doi_suffix}/references/{path}", tpl_uris)

        self.assertEqual(by_id[6]["result"]["prompts"][0]["name"], "use_paper")
        prompt_msg = by_id[7]["result"]["messages"][0]["content"]["text"]
        self.assertIn("How many donors?", prompt_msg)
        self.assertIn("Donors, not cells, are the replicates", prompt_msg)

    # 3. get_paper (PMID alias, data_terms, verification warnings, planned paper) & list_recipes (targets + tiers)
    def test_mcp_get_paper_and_list_recipes(self):
        r_a = mcp_server.handle_tool_call(self.cat, "get_paper", {"id": "11111111"})
        self.assertFalse(r_a["isError"])
        sc_a = r_a["structuredContent"]
        self.assertEqual(sc_a["doi"], self.DOI_A)
        self.assertEqual(sc_a["badges"]["runs"], "pass")
        self.assertIsNone(sc_a["verification_warning"])
        self.assertTrue(any("Allen Institute Terms of Use" in t for t in sc_a["data_terms"]))

        # Unverified pack C surfaces a clear verification_warning
        r_c = mcp_server.handle_tool_call(self.cat, "get_paper", {"id": "33333333"})
        self.assertFalse(r_c["isError"])
        self.assertIn("not passed", r_c["structuredContent"]["verification_warning"])

        # Planned paper D returns stage='planned' and request_hint
        r_plan = mcp_server.handle_tool_call(self.cat, "get_paper", {"id": self.DOI_PLANNED})
        self.assertFalse(r_plan["isError"])
        self.assertFalse(r_plan["structuredContent"]["packed"])
        self.assertEqual(r_plan["structuredContent"]["stage"], "planned")

        # list_recipes includes locked targets (and optional discrepancy target) and filters by resource needs
        recs = mcp_server.handle_tool_call(self.cat, "list_recipes", {"id": "11111111", "max_memory_gb": 8, "gpu": False, "include_targets": True})
        self.assertFalse(recs["isError"])
        rlist = recs["structuredContent"]["recipes"]
        self.assertEqual(len(rlist), 1)
        self.assertEqual(rlist[0]["needs"], {"memory_gb": 4, "gpu": False, "minutes": 2})
        self.assertTrue(rlist[0]["l1_pass"])
        self.assertEqual(len(rlist[0]["targets"]), 2)
        self.assertTrue(any(not t.get("required", True) for t in rlist[0]["targets"]))

        recs_gpu = mcp_server.handle_tool_call(self.cat, "list_recipes", {"id": "11111111", "gpu": True})
        self.assertEqual(recs_gpu["structuredContent"]["recipes"], [])

    # 4. Skills over MCP (full SKILL.md, section filter, references/, skill:// resources) & strict evals/ blocking
    def test_mcp_skills_over_mcp_and_security(self):
        full = mcp_server.handle_tool_call(self.cat, "get_skill", {"id": self.DOI_A})
        self.assertFalse(full["isError"])
        self.assertEqual(full["structuredContent"]["available_references"], ["references/notes.md"])
        self.assertIn("## Guardrails", full["structuredContent"]["content_markdown"])

        sec = mcp_server.handle_tool_call(self.cat, "get_skill", {"id": self.DOI_A, "section": "Guardrails"})
        self.assertFalse(sec["isError"])
        self.assertTrue(sec["structuredContent"]["content_markdown"].startswith("## Guardrails"))
        self.assertNotIn("## Recipes", sec["structuredContent"]["content_markdown"])

        ref = mcp_server.handle_tool_call(self.cat, "get_skill", {"id": self.DOI_A, "reference": "notes.md"})
        self.assertFalse(ref["isError"])
        self.assertIn("Detailed taxonomy notes", ref["structuredContent"]["content_markdown"])

        res_skill = mcp_server.read_resource(self.cat, f"skill://runpapers/{self.DOI_A}/SKILL.md")
        self.assertIn("Donors, not cells", res_skill["contents"][0]["text"])
        res_ref = mcp_server.read_resource(self.cat, f"skill://runpapers/{self.DOI_A}/references/notes.md")
        self.assertIn("progressive disclosure", res_ref["contents"][0]["text"])

        # Security: every attempt to read evals/ or traverse outside references/ is blocked
        for bad_ref in ("evals/questions.toml", "../evals/questions.toml", "references/../../evals/questions.toml", "/etc/passwd"):
            denied = mcp_server.handle_tool_call(self.cat, "get_skill", {"id": self.DOI_A, "reference": bad_ref})
            self.assertTrue(denied["isError"], bad_ref)
            self.assertNotIn(SECRET_EVAL, json.dumps(denied))

        for bad_uri in (
            f"skill://runpapers/{self.DOI_A}/evals/questions.toml",
            f"skill://runpapers/{self.DOI_A}/references/../../evals/questions.toml",
            f"skill://runpapers/{self.DOI_A}/pack.toml",
        ):
            rpc_resp = mcp_server.dispatch_rpc(self.cat, {"jsonrpc": "2.0", "id": 99, "method": "resources/read", "params": {"uri": bad_uri}})
            self.assertIn("error", rpc_resp, bad_uri)
            self.assertNotIn(SECRET_EVAL, json.dumps(rpc_resp))

    # 5. request_paper in both local registry mode and standalone uvx (no local repo) mode
    def test_mcp_request_paper_local_and_standalone(self):
        r1 = mcp_server.handle_tool_call(self.cat, "request_paper", {"id": "44444444", "note": "Need astrocyte Fig 3"})
        self.assertFalse(r1["isError"])
        self.assertEqual((r1["structuredContent"]["mode"], r1["structuredContent"]["new"], r1["structuredContent"]["votes"]),
                         ("registry", True, 1))
        r2 = mcp_server.handle_tool_call(self.cat, "request_paper", {"id": self.DOI_PLANNED})
        self.assertEqual((r2["structuredContent"]["new"], r2["structuredContent"]["votes"]), (False, 1))

        # Standalone mode: no local registry, writes to RUNPAPERS_CONFIG/requests.jsonl + returns GitHub issue URL
        site_dir = self.tmp / "site-req"
        httpd = site.serve(site_dir, port=0, quiet=True)
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        site.build(self.reg, out=site_dir, base_url=url)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            rcat = catalog.RemoteCatalog(url, cache_dir=self.tmp / "rcache-req")
            s1 = mcp_server.handle_tool_call(rcat, "request_paper", {"id": "10.9999/external.2026.55", "note": "Spatial panel"})
            self.assertFalse(s1["isError"])
            sc = s1["structuredContent"]
            self.assertEqual((sc["mode"], sc["new"], sc["votes"]), ("standalone", True, 1))
            self.assertTrue((self.cfg / "requests.jsonl").is_file())
            self.assertIn("https://github.com/runpapers/runpapers/issues/new?", sc["issue_url"])

            s2 = mcp_server.handle_tool_call(rcat, "request_paper", {"id": "10.9999/external.2026.55"})
            self.assertEqual((s2["structuredContent"]["new"], s2["structuredContent"]["votes"]), (False, 1))
        finally:
            httpd.shutdown()
            httpd.server_close()

    # 6. RemoteCatalog over local HTTP site + SHA-256 tamper rejection
    def test_remote_catalog_over_local_http(self):
        site_dir = self.tmp / "site-http"
        httpd = site.serve(site_dir, port=0, quiet=True)
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        site.build(self.reg, out=site_dir, base_url=url)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        old_cwd = os.getcwd()
        try:
            os.chdir(self.tmp)
            os.environ.pop("RUNPAPERS_HOME", None)
            os.environ["RUNPAPERS_BASE"] = url
            rcat = catalog.open_catalog()
            self.assertIsInstance(rcat, catalog.RemoteCatalog)

            srch = mcp_server.handle_tool_call(rcat, "search_papers", {"query": "SMYD2"})
            self.assertEqual(srch["structuredContent"]["matches"][0]["doi"], self.DOI_A)

            srch_tags = mcp_server.handle_tool_call(
                rcat,
                "search_papers",
                {"species": ["human"], "tissue_cell": ["putamen"], "data_type": ["patch-seq"]},
            )
            self.assertEqual([m["doi"] for m in srch_tags["structuredContent"]["matches"]], [self.DOI_B])

            det = mcp_server.handle_tool_call(rcat, "get_paper", {"id": "11111111"})
            self.assertEqual(det["structuredContent"]["doi"], self.DOI_A)
            self.assertIn(f"--source {url}", det["structuredContent"]["workspace_command"])

            sk = mcp_server.handle_tool_call(rcat, "get_skill", {"id": "11111111"})
            self.assertFalse(sk["isError"])
            self.assertIn("Donors, not cells", sk["structuredContent"]["content_markdown"])

            # Tamper with remote reference file on disk -> RemoteCatalog detects SHA-256 mismatch against pack.json
            ref_on_server = site_dir / ids.page_path(self.DOI_A) / "pack" / "references" / "notes.md"
            ref_on_server.write_text("TAMPERED CONTENT\n")
            tampered = mcp_server.handle_tool_call(rcat, "get_skill", {"id": "11111111", "reference": "notes.md"})
            self.assertTrue(tampered["isError"])
            self.assertIn("SHA-256 checksum mismatch", tampered["content"][0]["text"])
        finally:
            os.chdir(old_cwd)
            httpd.shutdown()
            httpd.server_close()

    # 7. `rp meeting` multi-paper workspace, [profile] overlap matrix, guardrails, and evals/ exclusion
    def test_meeting_kit_workspace_and_overlap(self):
        mdir = self.tmp / "bg-meeting"
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        r = subprocess.run(
            [sys.executable, "-m", "runpapers.cli", "meeting", "striatal D2 SPN putamen",
             "--no-data", "--dir", str(mdir), "--json"],
            env=env, capture_output=True, text=True, check=True,
        )
        manifest = json.loads(r.stdout)
        selected_dois = [p["doi"] for p in manifest["packs"]]
        # Verified packs A and B are selected; unverified pack C ('ready') is excluded; planned D is in planned_matches
        self.assertEqual(set(selected_dois), {self.DOI_A, self.DOI_B})
        self.assertNotIn(self.DOI_C, selected_dois)
        self.assertEqual([p["doi"] for p in manifest["planned_matches"]], [self.DOI_PLANNED])

        ov = manifest["profile_overlap"]
        self.assertIn("Homo sapiens", ov["shared"]["species"])
        self.assertIn("putamen", ov["shared"]["tissues"])
        self.assertIn("10x Multiome snRNA-seq", ov["shared"]["assays"])
        self.assertIn("D2 SPN", ov["shared"]["cell_types"])
        self.assertIn("DRD2", ov["shared"]["key_genes"])
        self.assertIn("Callithrix jacchus", ov["by_paper"]["10-9999-bg-spn-2026"]["species"])
        self.assertIn("Patch-seq", ov["by_paper"]["10-9999-bg-patch-2026"]["assays"])
        self.assertTrue(any("Allen Institute Terms of Use" in t for t in manifest["data_terms"]))
        self.assertIn("CC-BY-4.0", manifest["data_terms"])

        # Check workspace layout, mirrored skills, shared-donor guardrail, and zero leaked evals/
        for rel in (
            ".runpapers-meeting.json", "MEETING.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "synthesis/README.md",
            "papers/10-9999-bg-spn-2026/SKILL.md", "papers/10-9999-bg-patch-2026/SKILL.md",
            ".agents/skills/runpapers-10-9999-bg-spn-2026/SKILL.md", ".agents/skills/runpapers-10-9999-bg-patch-2026/SKILL.md",
            ".claude/skills/runpapers-10-9999-bg-spn-2026/SKILL.md", ".gemini/skills/runpapers-10-9999-bg-patch-2026/SKILL.md",
        ):
            self.assertTrue((mdir / rel).is_file(), rel)
        self.assertIn("overlapping human or animal donors", (mdir / "MEETING.md").read_text())
        self.assertEqual(list(mdir.rglob("*evals*")), [])
        for p in mdir.rglob("*"):
            if p.is_file():
                self.assertNotIn(SECRET_EVAL, p.read_text(errors="ignore"))

    # 8. Core stdlib-only packaging invariant & zero tracked-file findings in prepublish_scan
    def test_startup_and_prepublish_clean(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(pyproject["project"]["dependencies"], [])
        self.assertIn("mcp", pyproject["project"]["optional-dependencies"])

        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        r = subprocess.run([sys.executable, "-S", "-c",
                            "import sys; sys.path.insert(0, " + repr(str(ROOT / "src")) + "); "
                            "import runpapers.cli, runpapers.mcp_server, runpapers.meeting; print('stdlib-ok')"],
                           env=env, capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout.strip(), "stdlib-ok")

        tracked_findings = [x for x in release.prepublish_scan(Registry(ROOT)) if x[1] != "git history"]
        self.assertEqual(tracked_findings, [])


if __name__ == "__main__":
    unittest.main()
