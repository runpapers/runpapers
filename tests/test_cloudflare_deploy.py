"""Offline unit tests for `deploy/cloudflare/deploy.py` and `deploy/cloudflare/selftest.py`
dynamic `/index.json` discovery and zero-published-packs fallback."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name, rel_path):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
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


class CloudflareDeployAndSelftestTests(unittest.TestCase):
    def test_deploy_provisions_d1_turnstile_worker_secrets_cron_and_routes_preserving_salt(self):
        cf_deploy = _load_module("rp_cf_deploy", "deploy/cloudflare/deploy.py")
        acct_id = "a" * 32
        zone_id = "b" * 32
        d1_uuid = "11111111-2222-3333-4444-555555555555"
        calls = []

        def fake_requester(method, url, body_bytes, headers):
            calls.append((method, url, body_bytes, dict(headers)))
            path = url.replace("https://api.cloudflare.com/client/v4", "")
            if method == "GET" and path.startswith("/zones?"):
                return 200, json.dumps({"success": True, "result": [{"id": zone_id, "account": {"id": acct_id}}]})
            if method == "GET" and path == f"/accounts/{acct_id}/d1/database":
                return 200, json.dumps({"success": True, "result": []})
            if method == "POST" and path == f"/accounts/{acct_id}/d1/database":
                return 200, json.dumps({"success": True, "result": {"uuid": d1_uuid, "name": "runpapers_intake"}})
            if method == "POST" and path == f"/accounts/{acct_id}/d1/database/{d1_uuid}/query":
                payload = json.loads(body_bytes.decode())
                self.assertIn("CREATE TABLE IF NOT EXISTS paper_votes", payload["sql"])
                self.assertIn("CREATE TABLE IF NOT EXISTS dedup_hashes", payload["sql"])
                return 200, json.dumps({"success": True, "result": [{"success": True}]})
            if method == "GET" and path == f"/accounts/{acct_id}/challenges/widgets":
                return 200, json.dumps({"success": True, "result": []})
            if method == "POST" and path == f"/accounts/{acct_id}/challenges/widgets":
                payload = json.loads(body_bytes.decode())
                self.assertEqual(payload["domains"], ["runpapers.com", "www.runpapers.com"])
                self.assertIs(payload["bot_fight_mode"], False)
                return 200, json.dumps({
                    "success": True,
                    "result": {"sitekey": "0x4AAAAAAA_sitekey", "secret": "0x4AAAAAAA_turnstile_secret_val"},
                })
            if method == "PUT" and path == f"/accounts/{acct_id}/workers/scripts/runpapers-counter":
                ctype = headers["Content-Type"]
                self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
                raw_text = body_bytes.decode("utf-8")
                self.assertIn('"main_module": "worker.js"', raw_text)
                self.assertIn('"keep_bindings": ["secret_text"]', raw_text)
                self.assertIn('"dataset": "runpapers_hits"', raw_text)
                self.assertIn(f'"id": "{d1_uuid}"', raw_text)
                self.assertIn('"name": "TURNSTILE_SITE_KEY"', raw_text)
                self.assertIn("export async function handleIntake", raw_text)
                return 200, json.dumps({"success": True, "result": {"id": "runpapers-counter"}})
            if method == "PUT" and path == f"/accounts/{acct_id}/workers/scripts/runpapers-counter/secrets":
                payload = json.loads(body_bytes.decode())
                self.assertNotEqual(payload["name"], "SALT", "deploy.py must never overwrite existing SALT secret")
                return 200, json.dumps({"success": True, "result": {"name": payload["name"]}})
            if method == "PUT" and path == f"/accounts/{acct_id}/workers/scripts/runpapers-counter/schedules":
                payload = json.loads(body_bytes.decode())
                self.assertEqual(payload, [{"cron": "17 * * * *"}])
                return 200, json.dumps({"success": True, "result": {"schedules": payload}})
            if method == "GET" and path == f"/zones/{zone_id}/workers/routes":
                return 200, json.dumps({
                    "success": True,
                    "result": [{"id": "r1", "pattern": "runpapers.com/*", "script": "runpapers-counter"}],
                })
            if method == "POST" and path == f"/zones/{zone_id}/workers/routes":
                payload = json.loads(body_bytes.decode())
                self.assertEqual(payload, {"pattern": "www.runpapers.com/*", "script": "runpapers-counter"})
                return 200, json.dumps({"success": True, "result": {"id": "r2"}})
            raise AssertionError(f"Unexpected API call: {method} {path}")

        out = io.StringIO()
        err = io.StringIO()
        env = {
            "CLOUDFLARE_API_TOKEN": "  cf_agent_tok_12345  \n",
            "RP_INTAKE_SECRET": "intake_shared_sec_999",
        }
        rc = cf_deploy.main(env=env, repo_root=REPO_ROOT, requester=fake_requester, out=out, err=err)
        self.assertEqual(rc, 0, err.getvalue())

        stdout_text = out.getvalue()
        self.assertIn("D1 database runpapers_intake: created", stdout_text)
        self.assertIn("0001_intake.sql", stdout_text)
        self.assertIn("0x4AAAAAAA_sitekey", stdout_text)
        self.assertIn("Worker runpapers-counter: uploaded", stdout_text)
        self.assertIn("Cron trigger: 17 * * * *", stdout_text)
        # Ensure zero secret values ever appear in stdout/stderr
        for secret_val in ("cf_agent_tok_12345", "0x4AAAAAAA_turnstile_secret_val", "intake_shared_sec_999"):
            self.assertNotIn(secret_val, stdout_text)
            self.assertNotIn(secret_val, err.getvalue())

        secret_puts = [
            json.loads(b.decode())["name"]
            for m, u, b, _ in calls
            if m == "PUT" and u.endswith("/workers/scripts/runpapers-counter/secrets")
        ]
        self.assertEqual(secret_puts, ["TURNSTILE_SECRET", "RP_INTAKE_SECRET"])

    def test_deploy_is_idempotent_when_resources_exist_and_fails_cleanly_on_bad_token_or_api_error(self):
        cf_deploy = _load_module("rp_cf_deploy", "deploy/cloudflare/deploy.py")
        acct_id = "c" * 32
        d1_uuid = "99999999-8888-7777-6666-555555555555"

        def existing_requester(method, url, body_bytes, headers):
            path = url.replace("https://api.cloudflare.com/client/v4", "")
            if method == "GET" and path == f"/accounts/{acct_id}/d1/database":
                return 200, json.dumps({"success": True, "result": [{"uuid": d1_uuid, "name": "runpapers_intake"}]})
            if method == "POST" and path == f"/accounts/{acct_id}/d1/database/{d1_uuid}/query":
                return 200, json.dumps({"success": True, "result": [{"success": True}]})
            if method == "GET" and path == f"/accounts/{acct_id}/challenges/widgets":
                return 200, json.dumps({"success": True, "result": [{"sitekey": "sitekey_existing", "domains": ["runpapers.com"]}]})
            if method == "GET" and path == f"/accounts/{acct_id}/challenges/widgets/sitekey_existing":
                return 200, json.dumps({"success": True, "result": {"sitekey": "sitekey_existing", "secret": "ts_sec"}})
            if method == "PUT" and path.startswith(f"/accounts/{acct_id}/workers/scripts/runpapers-counter"):
                return 200, json.dumps({"success": True, "result": {}})
            if method == "GET" and path.startswith("/zones?"):
                return 403, json.dumps({"success": False, "errors": [{"message": "zone scope omitted"}]})
            raise AssertionError(f"Unexpected API call on idempotent run: {method} {path}")

        out = io.StringIO()
        rc = cf_deploy.main(
            env={"CLOUDFLARE_API_TOKEN": "valid_tok", "CLOUDFLARE_ACCOUNT_ID": acct_id},
            repo_root=REPO_ROOT,
            requester=existing_requester,
            out=out,
            err=io.StringIO(),
        )
        self.assertEqual(rc, 0)
        self.assertIn("D1 database runpapers_intake: present", out.getvalue())
        self.assertIn("Turnstile widget RunPapers: present", out.getvalue())

        # Missing token exits 1 cleanly
        err_missing = io.StringIO()
        self.assertEqual(cf_deploy.main(env={}, repo_root=REPO_ROOT, err=err_missing), 1)
        self.assertIn("CLOUDFLARE_API_TOKEN is not set", err_missing.getvalue())

        # Upstream 500 exits 1 cleanly without leaking token
        err_500 = io.StringIO()
        rc_500 = cf_deploy.main(
            env={"CLOUDFLARE_API_TOKEN": "super_secret_token_xyz", "CLOUDFLARE_ACCOUNT_ID": acct_id},
            repo_root=REPO_ROOT,
            requester=lambda *a: (500, json.dumps({"success": False, "errors": [{"message": "internal error"}]})),
            err=err_500,
        )
        self.assertEqual(rc_500, 1)
        self.assertNotIn("super_secret_token_xyz", err_500.getvalue())

        # Confirm no legacy Worker deploy workflow exists and setup docs describe automatic deploy via deploy.py
        self.assertEqual(list((REPO_ROOT / ".github" / "workflows").glob("*deploy*worker*")), [])
        guide = (REPO_ROOT / "docs" / "setup-usage-counting.md").read_text()
        self.assertIn("deploy/cloudflare/deploy.py", guide)
        self.assertNotIn("paste it into the editor", guide)

    def test_selftest_dynamic_index_discovery_and_zero_packs_fallback_matches_worker(self):
        selftest = _load_module("rp_cf_selftest", "deploy/cloudflare/selftest.py")

        # 1. RP_PAPER env override wins without needing /index.json
        self.assertEqual(selftest.resolve_paper_slug("https://runpapers.com", env={"RP_PAPER": "override-slug"}), "override-slug")

        # 2. When RP_PAPER is unset and /index.json has an available paper, fetches with X-RunPapers-Internal: 1 and uses papers[0]
        seen_idx_headers = []

        def open_with_paper(req, timeout=30):
            seen_idx_headers.append({k.lower(): v for k, v in req.header_items()})
            body = json.dumps({"papers": [{"doi": "10.1016/j.cell.2026.10.012", "slug": "10-1016-j-cell-2026-10-012"}]}).encode()
            return _FakeHTTPResponse(body, status=200)

        with mock.patch.object(selftest.OPENER, "open", side_effect=open_with_paper):
            slug = selftest.resolve_paper_slug("https://runpapers.com", env={})
        self.assertEqual(slug, "10-1016-j-cell-2026-10-012")
        self.assertEqual(seen_idx_headers[0].get("x-runpapers-internal"), "1")
        paper_cases = selftest.build_cases(slug)
        self.assertEqual(len(paper_cases), 7)

        # 3. When /index.json has zero available papers (`papers: []`), falls back to `/` across all 4 visitor kinds
        with mock.patch.object(selftest.OPENER, "open", return_value=_FakeHTTPResponse(b'{"papers": []}', status=200)):
            empty_slug = selftest.resolve_paper_slug("https://runpapers.com", env={})
        self.assertEqual(empty_slug, "")
        zero_cases = selftest.build_cases(empty_slug)
        want = {(kind, typ, paper, path): 1 for kind, path, _, exp in zero_cases if exp for (typ, paper) in [exp]}
        self.assertEqual(
            want,
            {
                ("person", "html", "", "/"): 1,
                ("agent", "html", "", "/"): 1,
                ("crawler", "html", "", "/"): 1,
                ("script", "html", "", "/"): 1,
            },
        )

        # Verify selftest.send_requests succeeds offline with zero_cases
        def fake_site_open(req, timeout=30):
            if req.full_url.startswith("https://www."):
                return _FakeHTTPResponse(b"", status=301, headers={"Location": "https://runpapers.com/", "CF-Ray": "r1"})
            code = 404 if "no-such-page" in req.full_url else 200
            return _FakeHTTPResponse(b"ok", status=code, headers={"CF-Ray": "r1"})

        with mock.patch.object(selftest.OPENER, "open", side_effect=fake_site_open), \
             contextlib.redirect_stdout(io.StringIO()):
            selftest.results.clear()
            selftest.send_requests("st-0000cafe", sleep_seconds=0, site="https://runpapers.com", host="runpapers.com", cases=zero_cases)
        self.assertTrue(all(ok for ok, _, _ in selftest.results), selftest.results)

        # 4. Run zero_cases (2x each + www 301) through actual deploy/cloudflare/worker.js in Node and prove 1:1 count match
        if shutil.which("node"):
            worker_url = (REPO_ROOT / "deploy" / "cloudflare" / "worker.js").as_uri()
            node_sim = f"""
              import worker from {json.dumps(worker_url)};
              const cases = JSON.parse(process.env.RP_ZERO_CASES);
              const uas = JSON.parse(process.env.RP_UAS);
              const points = [], store = new Set(), waits = [];
              globalThis.caches = {{ default: {{ match: async (r) => store.has(r.url), put: async (r) => store.add(r.url) }} }};
              globalThis.fetch = async (req) => {{
                const u = new URL(req.url);
                if (u.hostname === "www.runpapers.com") return new Response("", {{ status: 301, headers: {{ Location: "https://runpapers.com/" }} }});
                if (u.pathname.includes("no-such-page")) return new Response("missing", {{ status: 404 }});
                return new Response("<html>ok</html>", {{ status: 200 }});
              }};
              const env = {{ SALT: "s", HITS: {{ writeDataPoint: (p) => points.push(p) }} }};
              const ctx = {{ waitUntil: (p) => waits.push(p) }};
              for (const [kind, path] of cases) {{
                for (const _ of [1, 2]) {{
                  await worker.fetch(new Request("https://runpapers.com" + path, {{
                    headers: {{ "User-Agent": uas[kind], "X-RunPapers-Action": "st-0000cafe", "CF-Connecting-IP": "198.51.100.10" }},
                  }}), env, ctx);
                }}
              }}
              await worker.fetch(new Request("https://www.runpapers.com/", {{
                headers: {{ "User-Agent": uas.person, "X-RunPapers-Action": "st-0000cafe", "CF-Connecting-IP": "198.51.100.10" }},
              }}), env, ctx);
              await Promise.all(waits);
              console.log(JSON.stringify(points.map((p) => p.blobs)));
            """
            proc = subprocess.run(
                ["node", "--input-type=module", "-e", node_sim],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "RP_ZERO_CASES": json.dumps([[k, p] for k, p, _, _ in zero_cases]),
                    "RP_UAS": json.dumps(selftest.UA),
                },
                check=True,
            )
            blobs = json.loads(proc.stdout)
            got = {(b[0], b[1], b[2], b[4]): 1 for b in blobs}
            self.assertEqual(len(blobs), 4)
            self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
