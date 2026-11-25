"""Offline unit tests for Spec 004-T1: user-agent classification (24+ real strings & Worker parity),
CLI/usertest usage headers (X-RunPapers-Action, X-RunPapers-Internal, X-RunPapers-NoCount),
and deploy/cloudflare/selftest.py helpers."""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runpapers import data, registry, usertest, workspace

REPO_ROOT = Path(__file__).resolve().parents[1]

REAL_USER_AGENTS = [
    # User-triggered AI agents & RunPapers CLI (8)
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)", "agent"),
    ("Claude-User (claude-code/2.1; +https://support.anthropic.com/)", "agent"),
    ("Claude-Code/1.0.24 (+https://anthropic.com)", "agent"),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot", "agent"),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)", "agent"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Google-Agent", "agent"),
    ("Mozilla/5.0 (compatible; MistralAI-User/1.0; +https://docs.mistral.ai/robots)", "agent"),
    ("runpapers/0.2 (+https://runpapers.com)", "agent"),
    # Training & search crawlers (10)
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)", "crawler"),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", "crawler"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot", "crawler"),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +searchbot@anthropic.com)", "crawler"),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)", "crawler"),
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "crawler"),
    ("Mozilla/5.0 (compatible; Google-Extended)", "crawler"),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GoogleOther)", "crawler"),
    ("CCBot/2.0 (https://commoncrawl.org/faq/)", "crawler"),
    ("Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36 (compatible; Bytespider; https://zhanzhang.toutiao.com/)", "crawler"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/600.2.5 (KHTML, like Gecko) Version/8.0.2 Safari/600.2.5 (Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)", "crawler"),
    # Command-line & library HTTP clients (6)
    ("curl/8.5.0", "script"),
    ("Wget/1.21.4 (linux-gnu)", "script"),
    ("python-requests/2.32.3", "script"),
    ("python-httpx/0.27.2", "script"),
    ("Python-urllib/3.12", "script"),
    ("", "script"),
    # Interactive browsers (5)
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "person"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", "person"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15", "person"),
    ("Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0", "person"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0", "person"),
]


def _load_selftest():
    path = REPO_ROOT / "deploy" / "cloudflare" / "selftest.py"
    spec = importlib.util.spec_from_file_location("rp_cf_selftest", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeHTTPResponse(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class UsageCounterAndHeadersTests(unittest.TestCase):
    def test_user_agent_classification_24_real_strings(self):
        self.assertGreaterEqual(len(REAL_USER_AGENTS), 24)
        for ua, expected in REAL_USER_AGENTS:
            with self.subTest(ua=ua):
                self.assertEqual(data.classify_ua(ua), expected)

        if shutil.which("node"):
            worker_url = (REPO_ROOT / "deploy" / "cloudflare" / "worker.js").as_uri()
            script = (
                f"import {{ kindOf }} from {json.dumps(worker_url)};"
                "const uas = JSON.parse(process.env.RP_TEST_UAS);"
                "console.log(JSON.stringify(uas.map((u) => kindOf(u))));"
            )
            env = {**os.environ, "RP_TEST_UAS": json.dumps([ua for ua, _ in REAL_USER_AGENTS])}
            proc = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, env=env, check=True)
            worker_kinds = json.loads(proc.stdout)
            self.assertEqual(worker_kinds, [expected for _, expected in REAL_USER_AGENTS])

    def test_request_headers_env_flags(self):
        h_clean = data.request_headers(env={})
        self.assertEqual(h_clean, {"User-Agent": data.UA})

        h_get = data.request_headers(action="get", env={"CI": "0", "RUNPAPERS_INTERNAL": "false", "DO_NOT_TRACK": "0"})
        self.assertEqual(h_get, {"User-Agent": data.UA, "X-RunPapers-Action": "get"})

        h_ci = data.request_headers(env={"CI": "true"})
        self.assertEqual(h_ci["X-RunPapers-Internal"], "1")
        self.assertNotIn("X-RunPapers-NoCount", h_ci)

        h_internal = data.request_headers(env={"RUNPAPERS_INTERNAL": "1"})
        self.assertEqual(h_internal["X-RunPapers-Internal"], "1")

        h_dnt = data.request_headers(action="get", extra={"Range": "bytes=10-"}, env={"DO_NOT_TRACK": "1"})
        self.assertEqual(h_dnt["X-RunPapers-Action"], "get")
        self.assertEqual(h_dnt["X-RunPapers-NoCount"], "1")
        self.assertEqual(h_dnt["Range"], "bytes=10-")
        self.assertNotIn("X-RunPapers-Internal", h_dnt)

    def test_workspace_get_sends_action_and_privacy_headers(self):
        doi = "10.1234/test.2026.01"
        slug = "10-1234-test-2026-01"
        pack_files = {
            "pack.toml": (
                'spec = "runpapers/0.2"\n'
                f'[paper]\ndoi = "{doi}"\npmid = "99999999"\ntitle = "Test Paper"\n'
                'first_author = "Ada"\nsenior_author = "Grace"\njournal = "Cell"\nyear = 2026\nlicense = "CC-BY-4.0"\n'
                '[pack]\nversion = "0.1.0"\nsummary = "Test"\nlicense = "CC-BY-4.0"\n'
            ).encode(),
            "targets.toml": b"",
            "SKILL.md": b"---\nname: runpapers-10-1234-test-2026-01\ndescription: test\n---\n# Skill\n",
        }
        listing = {
            "doi": doi,
            "version": "0.1.0",
            "pack_hash": "abc",
            "files": [
                {"path": rel, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
                for rel, raw in pack_files.items()
            ],
        }
        routes = {
            "https://example.org/index.json": json.dumps({"papers": [{"doi": doi, "pmid": "99999999"}]}).encode(),
            f"https://example.org/papers/{slug}/pack.json": json.dumps(listing).encode(),
            **{f"https://example.org/papers/{slug}/pack/{rel}": raw for rel, raw in pack_files.items()},
        }
        seen = []

        def fake_urlopen(req, timeout=60):
            hdrs = {k.lower(): v for k, v in req.header_items()}
            seen.append((req.full_url, hdrs))
            return _FakeHTTPResponse(routes[req.full_url], status=200)

        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with mock.patch.dict(os.environ, {"RUNPAPERS_CACHE": str(cache_dir), "CI": "", "RUNPAPERS_INTERNAL": "", "DO_NOT_TRACK": ""}, clear=False):
                    ws_dir, _ = workspace.get("PMID:99999999", dest=Path(td) / "ws1", source="https://example.org", quiet=True)
                    self.assertTrue((ws_dir / ".runpapers.json").is_file())

                by_url = dict(seen)
                self.assertNotIn("x-runpapers-action", by_url["https://example.org/index.json"])
                self.assertEqual(by_url[f"https://example.org/papers/{slug}/pack.json"].get("x-runpapers-action"), "get")
                self.assertNotIn("x-runpapers-internal", by_url[f"https://example.org/papers/{slug}/pack.json"])
                self.assertNotIn("x-runpapers-nocount", by_url[f"https://example.org/papers/{slug}/pack.json"])
                self.assertNotIn("x-runpapers-action", by_url[f"https://example.org/papers/{slug}/pack/SKILL.md"])

                seen.clear()
                with mock.patch.dict(os.environ, {"RUNPAPERS_CACHE": str(cache_dir), "RUNPAPERS_INTERNAL": "1", "DO_NOT_TRACK": "1"}, clear=False):
                    workspace.get(doi, dest=Path(td) / "ws2", source="https://example.org", quiet=True)
                pack_hdrs = dict(seen)[f"https://example.org/papers/{slug}/pack.json"]
                self.assertEqual(pack_hdrs.get("x-runpapers-action"), "get")
                self.assertEqual(pack_hdrs.get("x-runpapers-internal"), "1")
                self.assertEqual(pack_hdrs.get("x-runpapers-nocount"), "1")

    def test_data_download_sends_internal_and_nocount_headers(self):
        seen = []

        def fake_urlopen(req, timeout=60):
            seen.append({k.lower(): v for k, v in req.header_items()})
            return _FakeHTTPResponse(b"hello", status=200)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sample.bin"
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with mock.patch.dict(os.environ, {"CI": "true", "DO_NOT_TRACK": "1"}, clear=False):
                    data._download("https://example.org/sample.bin", dest, 5, quiet=True)
            self.assertEqual(dest.read_bytes(), b"hello")
            self.assertFalse(data.verified(dest, {"size": 5}))
            self.assertEqual(seen[0].get("x-runpapers-internal"), "1")
            self.assertEqual(seen[0].get("x-runpapers-nocount"), "1")
            self.assertTrue(seen[0].get("user-agent", "").startswith("runpapers/"))

    def test_usertest_sets_runpapers_internal_in_child_env(self):
        lab_key = "LAB_" + "CUSTOM"
        env = usertest.agent_env({"PATH": "/usr/bin", lab_key: "strip-me", "RUNPAPERS_HOME": "/tmp/rp"})
        self.assertEqual(env.get("RUNPAPERS_INTERNAL"), "1")
        self.assertEqual(env.get("PATH"), "/usr/bin")
        self.assertNotIn(lab_key, env)
        self.assertNotIn("RUNPAPERS_HOME", env)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdir = root / "papers" / "10.1234" / "ut.1"
            (pdir / "recipes").mkdir(parents=True)
            (pdir / "evals").mkdir(parents=True)
            (pdir / "pack.toml").write_text(
                'spec = "runpapers/0.2"\n'
                '[paper]\ndoi = "10.1234/ut.1"\ntitle = "UT"\nfirst_author = "A"\nsenior_author = "B"\n'
                'journal = "J"\nyear = 2026\nlicense = "CC-BY-4.0"\n'
                '[pack]\nversion = "0.1.0"\nsummary = "S"\nlicense = "CC-BY-4.0"\n'
                '[[recipes]]\nid = "fig1"\ntitle = "F1"\npanel = "Figure 1"\nscript = "recipes/fig1.py"\n'
                'data = []\nneeds = { memory_gb = 1, gpu = false, minutes = 1 }\n'
            )
            (pdir / "targets.toml").write_text("")
            (pdir / "SKILL.md").write_text("---\nname: runpapers-10-1234-ut-1\ndescription: d\n---\n")
            (pdir / "recipes" / "fig1.py").write_text("print('ok')\n")
            (pdir / "evals" / "questions.toml").write_text(
                '[[question]]\nid = "q1"\nask = "How many?"\nanswer = 4\nkind = "number"\nlevel = "reproduce"\nsource = "s"\n'
            )
            (root / "runpapers.toml").write_text('[site]\nbase_url = "https://example.org"\n')
            reg = registry.Registry(root)
            pk = reg.pack("10.1234/ut.1")

            captured_envs = []

            def fake_run(cmd, cwd=None, env=None, stdout=None, stderr=None, timeout=None, stdin=None):
                captured_envs.append(dict(env or {}))
                (Path(cwd) / "answers.json").write_text(json.dumps({"q1": 4}))
                out_dir = Path(cwd) / "out" / "fig1"
                out_dir.mkdir(parents=True)
                (out_dir / "result.json").write_text(json.dumps({"pass": True}))
                return subprocess.CompletedProcess(cmd, 0)

            fake_httpd = mock.MagicMock()
            fake_httpd.server_address = ("127.0.0.1", 54321)
            with mock.patch.dict(os.environ, {"RUNPAPERS_CACHE": str(root / "cache"), lab_key: "hidden"}, clear=False), \
                 mock.patch("runpapers.site.serve", return_value=fake_httpd), \
                 mock.patch("runpapers.site.build", return_value=(root / "site", 1)), \
                 mock.patch("shutil.which", return_value="/usr/bin/claude"), \
                 mock.patch("subprocess.run", side_effect=fake_run):
                recs = usertest.run(reg, pk, ["claude"], record=False, quiet=True, keep=False)

            self.assertEqual(len(recs), 1)
            self.assertTrue(recs[0]["pass"])
            self.assertEqual(captured_envs[0].get("RUNPAPERS_INTERNAL"), "1")
            self.assertNotIn(lab_key, captured_envs[0])

    def test_selftest_helpers_and_workflow_offline(self):
        selftest = _load_selftest()

        # 1. selftest.get sends X-RunPapers-Action: st-<hex> WITHOUT X-RunPapers-Internal even inside CI
        seen_headers = []

        def fake_open(req, timeout=30):
            seen_headers.append({k.lower(): v for k, v in req.header_items()})
            if req.full_url.startswith("https://www."):
                return _FakeHTTPResponse(b"", status=301, headers={"Location": "https://runpapers.com/", "CF-Ray": "abc"})
            status = 404 if "no-such-page" in req.full_url else 200
            return _FakeHTTPResponse(b"ok", status=status, headers={"CF-Ray": "8899aabb-IAD"})

        with mock.patch.object(selftest.OPENER, "open", side_effect=fake_open), \
             mock.patch.dict(os.environ, {"CI": "true", "DO_NOT_TRACK": "1"}, clear=False), \
             contextlib.redirect_stdout(io.StringIO()):
            selftest.results.clear()
            selftest.send_requests("st-deadbeef", sleep_seconds=0, site="https://runpapers.com", host="runpapers.com")

        self.assertTrue(all(ok for ok, _, _ in selftest.results), selftest.results)
        self.assertEqual(seen_headers[0].get("x-runpapers-action"), "st-deadbeef")
        self.assertNotIn("x-runpapers-internal", seen_headers[0])
        self.assertNotIn("x-runpapers-nocount", seen_headers[0])

        # 2. cert_days parses peer certificate expiry and issuer deterministically
        fake_cert = {
            "notAfter": "Mar 15 23:59:59 2027 GMT",
            "issuer": ((("countryName", "US"),), (("organizationName", "Let's Encrypt"),), (("commonName", "E5"),)),
        }
        fake_tls = mock.MagicMock()
        fake_tls.__enter__.return_value = fake_tls
        fake_tls.getpeercert.return_value = fake_cert
        fake_ctx = mock.MagicMock()
        fake_ctx.wrap_socket.return_value = fake_tls
        fake_sock = mock.MagicMock()
        fake_sock.__enter__.return_value = fake_sock

        with mock.patch.object(selftest.socket, "create_connection", return_value=fake_sock), \
             mock.patch.object(selftest.ssl, "create_default_context", return_value=fake_ctx):
            days_ok, end_iso, issuer = selftest.cert_days(
                "185.199.108.153", "runpapers.com", now=dt.datetime(2027, 2, 20, tzinfo=dt.timezone.utc)
            )
            days_warn, _, _ = selftest.cert_days(
                "185.199.108.153", "runpapers.com", now=dt.datetime(2027, 3, 2, tzinfo=dt.timezone.utc)
            )
        self.assertEqual((days_ok, end_iso, issuer), (23, "2027-03-15", "Let's Encrypt"))
        self.assertGreater(days_ok, 14)
        self.assertEqual(days_warn, 13)
        self.assertLessEqual(days_warn, 14)

        # 3. read_back rejects malformed action strings and parses WAE JSON rows offline
        with self.assertRaises(ValueError):
            selftest.read_back("bad'; DROP TABLE", {})

        want = {("person", "html", "", "/"): 1}
        payload = json.dumps({"data": [{"kind": "person", "type": "html", "paper": "", "path": "/", "n": "1"}]})
        with mock.patch.object(selftest, "cf_api", return_value=(200, payload)), \
             contextlib.redirect_stdout(io.StringIO()):
            selftest.results.clear()
            rows = selftest.read_back("st-0123abcd", want, poll_seconds=0, settle_seconds=0, timeout_seconds=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "person")
        self.assertTrue(all(ok for ok, _, _ in selftest.results))

        # 4. usage-selftest workflow does not run on routine pushes to main
        wf = (REPO_ROOT / ".github" / "workflows" / "usage-selftest.yml").read_text()
        self.assertIn("workflow_dispatch:", wf)
        self.assertIn("ops/usage-selftest", wf)
        self.assertNotIn("branches: [main]", wf)


if __name__ == "__main__":
    unittest.main()
