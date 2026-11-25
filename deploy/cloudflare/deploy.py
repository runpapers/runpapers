#!/usr/bin/env python3
"""Automated Cloudflare deployment for RunPapers (`runpapers-counter`, Spec 004 & Spec 006).

Invoked automatically from the repository root (`python3 deploy/cloudflare/deploy.py`) with `CLOUDFLARE_API_TOKEN`
in `os.environ` whenever `deploy/cloudflare/` changes on `main`. Standard library only.

Idempotently ensures:
1. Account ID discovery via `GET /accounts` (or `CLOUDFLARE_ACCOUNT_ID` when set).
2. D1 database `runpapers_intake` exists and all `deploy/cloudflare/migrations/*.sql` files are applied.
3. Turnstile widget `RunPapers` (`runpapers.com`, `www.runpapers.com`, managed, bot_fight_mode=false) exists.
4. `deploy/cloudflare/worker.js` (and any relative ES modules) is uploaded to `runpapers-counter` via Cloudflare's
   multipart Workers Script API with `keep_bindings: ["secret_text"]` so existing secrets (`SALT`, `RP_INTAKE_SECRET`)
   and bindings (`HITS` -> `runpapers_hits`) stay intact while binding `DB` -> `runpapers_intake` and `TURNSTILE_SITE_KEY`.
5. `TURNSTILE_SECRET` (and `RP_INTAKE_SECRET` if present in `os.environ`) is upserted via the per-secret endpoint
   without touching `SALT`, hourly cron `17 * * * *` is set, and `runpapers.com/*` + `www.runpapers.com/*` routes exist.
"""
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.cloudflare.com/client/v4"
WORKER_NAME = "runpapers-counter"
WAE_BINDING = "HITS"
WAE_DATASET = "runpapers_hits"
D1_BINDING = "DB"
D1_NAME = "runpapers_intake"
TURNSTILE_NAME = "RunPapers"
ZONE_NAME = "runpapers.com"
TURNSTILE_DOMAINS = ["runpapers.com", "www.runpapers.com"]
ROUTES = ("runpapers.com/*", "www.runpapers.com/*")
CRON_EXPRESSION = "17 * * * *"
COMPATIBILITY_DATE = "2025-01-01"


class DeployError(RuntimeError):
    pass


def _clean_env(env, key):
    return "".join(str((env or {}).get(key, "")).split())


def _default_requester(method, url, body_bytes=None, headers=None):
    req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except OSError as e:
        raise DeployError(f"network error calling {method} {url}: {e}") from e


class CloudflareClient:
    def __init__(self, token, requester=None):
        self.token = token
        self._requester = requester or _default_requester

    def call(self, method, path, payload=None, raw_body=None, content_type="application/json", allow_statuses=()):
        url = API_BASE + path
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "runpapers-deploy/0.2",
        }
        body_bytes = None
        if raw_body is not None:
            body_bytes = raw_body
            headers["Content-Type"] = content_type
        elif payload is not None:
            body_bytes = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = content_type

        status, text = self._requester(method, url, body_bytes, headers)
        try:
            data = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            data = {"success": False, "errors": [{"message": text[:200]}]}

        if status in allow_statuses:
            return status, data
        if status < 200 or status >= 300 or not data.get("success", False):
            errs = data.get("errors") or []
            msg = "; ".join(str(e.get("message") or e) for e in errs) if errs else text[:200]
            raise DeployError(f"Cloudflare API {method} {path} failed (HTTP {status}): {msg}")
        return status, data


def discover_account_id(cf, env):
    explicit = _clean_env(env, "CLOUDFLARE_ACCOUNT_ID").lower()
    if explicit:
        if not re.fullmatch(r"[0-9a-f]{32}", explicit):
            raise DeployError(f"CLOUDFLARE_ACCOUNT_ID must be 32 lowercase hex characters (got length {len(explicit)})")
        return explicit

    # Prefer discovering from the runpapers.com zone if accessible, otherwise GET /accounts.
    z_status, z_data = cf.call(
        "GET",
        "/zones?" + urllib.parse.urlencode({"name": ZONE_NAME}),
        allow_statuses=(401, 403),
    )
    if z_status == 200 and z_data.get("success"):
        zones = z_data.get("result") or []
        if zones and isinstance(zones[0].get("account"), dict) and zones[0]["account"].get("id"):
            return str(zones[0]["account"]["id"]).lower()

    _, data = cf.call("GET", "/accounts")
    accounts = data.get("result") or []
    if not accounts:
        raise DeployError("Cloudflare token has access to zero accounts; check Account permissions.")
    acct_id = str(accounts[0].get("id") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", acct_id):
        raise DeployError("Cloudflare /accounts returned an unexpected account id.")
    return acct_id


def ensure_d1_and_migrate(cf, account_id, migrations_dir):
    _, data = cf.call("GET", f"/accounts/{account_id}/d1/database")
    dbs = data.get("result") or []
    existing = next((d for d in dbs if d.get("name") == D1_NAME), None)
    created = False
    if existing:
        db_id = existing.get("uuid") or existing.get("id")
    else:
        _, c_data = cf.call("POST", f"/accounts/{account_id}/d1/database", payload={"name": D1_NAME})
        res = c_data.get("result") or {}
        db_id = res.get("uuid") or res.get("id")
        created = True
    if not db_id:
        raise DeployError(f"Could not determine UUID for D1 database {D1_NAME!r}")

    sql_files = sorted(Path(migrations_dir).glob("*.sql"))
    applied = []
    for sql_file in sql_files:
        sql_text = sql_file.read_text(encoding="utf-8").strip()
        if not sql_text:
            continue
        _, q_data = cf.call(
            "POST",
            f"/accounts/{account_id}/d1/database/{db_id}/query",
            payload={"sql": sql_text},
        )
        for stmt_res in q_data.get("result") or []:
            if isinstance(stmt_res, dict) and stmt_res.get("success") is False:
                raise DeployError(f"D1 migration {sql_file.name} failed: {stmt_res.get('error', 'unknown SQL error')}")
        applied.append(sql_file.name)
    return {"uuid": db_id, "created": created, "migrations": applied}


def ensure_turnstile_widget(cf, account_id):
    _, data = cf.call("GET", f"/accounts/{account_id}/challenges/widgets")
    widgets = data.get("result") or []
    match = next(
        (
            w for w in widgets
            if ZONE_NAME in (w.get("domains") or []) or w.get("name") == TURNSTILE_NAME
        ),
        None,
    )
    created = False
    if match:
        sitekey = match.get("sitekey")
        secret = match.get("secret")
        if sitekey and not secret:
            _, detail = cf.call("GET", f"/accounts/{account_id}/challenges/widgets/{sitekey}")
            secret = (detail.get("result") or {}).get("secret")
    else:
        _, c_data = cf.call(
            "POST",
            f"/accounts/{account_id}/challenges/widgets",
            payload={
                "name": TURNSTILE_NAME,
                "domains": TURNSTILE_DOMAINS,
                "mode": "managed",
                "bot_fight_mode": False,
            },
        )
        res = c_data.get("result") or {}
        sitekey = res.get("sitekey")
        secret = res.get("secret")
        created = True
    if not sitekey:
        raise DeployError("Cloudflare Turnstile API did not return a sitekey.")
    return {"sitekey": sitekey, "secret": secret, "created": created}


def _collect_worker_modules(cf_dir):
    main_path = Path(cf_dir) / "worker.js"
    if not main_path.is_file():
        raise DeployError(f"Missing Worker entrypoint: {main_path}")
    main_src = main_path.read_text(encoding="utf-8")
    modules = [("worker.js", main_src)]
    # Attach any local relative ES modules referenced by worker.js (e.g. `./intake.js`) if ever imported.
    seen = {"worker.js"}
    for m in re.finditer(r"""^\s*(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]\./([A-Za-z0-9_.-]+\.m?js)['"]""", main_src, re.MULTILINE):
        rel = m.group(1)
        if rel not in seen:
            mod_path = Path(cf_dir) / rel
            if not mod_path.is_file():
                raise DeployError(f"worker.js imports missing local module: {rel}")
            modules.append((rel, mod_path.read_text(encoding="utf-8")))
            seen.add(rel)
    return modules


def _encode_multipart(parts):
    """Encode `(name, filename_or_none, content_type, data_bytes)` tuples as RFC 7578 multipart/form-data."""
    boundary = "----RunPapersWorkerBoundary" + secrets.token_hex(12)
    chunks = []
    for name, filename, ctype, payload in parts:
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        chunks.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\nContent-Type: {ctype}\r\n\r\n".encode("utf-8"))
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_worker(cf, account_id, cf_dir, db_uuid, turnstile_sitekey):
    modules = _collect_worker_modules(cf_dir)
    bindings = [
        {"type": "analytics_engine", "name": WAE_BINDING, "dataset": WAE_DATASET},
        {"type": "d1", "name": D1_BINDING, "id": db_uuid},
    ]
    if turnstile_sitekey:
        bindings.append({"type": "plain_text", "name": "TURNSTILE_SITE_KEY", "text": turnstile_sitekey})

    # `keep_bindings: ["secret_text"]` instructs Cloudflare to retain existing secrets (`SALT`, `RP_INTAKE_SECRET`,
    # `TURNSTILE_SECRET`) on `runpapers-counter` while updating code and explicit bindings (`HITS`, `DB`).
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": COMPATIBILITY_DATE,
        "keep_bindings": ["secret_text"],
        "bindings": bindings,
    }
    parts = [("metadata", None, "application/json", json.dumps(metadata).encode("utf-8"))]
    for mod_name, mod_src in modules:
        parts.append((mod_name, mod_name, "application/javascript+module", mod_src.encode("utf-8")))
    raw_body, content_type = _encode_multipart(parts)

    cf.call(
        "PUT",
        f"/accounts/{account_id}/workers/scripts/{WORKER_NAME}",
        raw_body=raw_body,
        content_type=content_type,
    )
    sha12 = hashlib.sha256(modules[0][1].encode("utf-8")).hexdigest()[:12]
    return {"modules": [m[0] for m in modules], "sha256_12": sha12}


def upsert_worker_secret(cf, account_id, secret_name, secret_value):
    cf.call(
        "PUT",
        f"/accounts/{account_id}/workers/scripts/{WORKER_NAME}/secrets",
        payload={"name": secret_name, "text": secret_value, "type": "secret_text"},
    )


def ensure_cron_schedule(cf, account_id):
    cf.call(
        "PUT",
        f"/accounts/{account_id}/workers/scripts/{WORKER_NAME}/schedules",
        payload=[{"cron": CRON_EXPRESSION}],
    )
    return CRON_EXPRESSION


def ensure_zone_routes(cf, expected_routes=ROUTES):
    status, z_data = cf.call(
        "GET",
        "/zones?" + urllib.parse.urlencode({"name": ZONE_NAME}),
        allow_statuses=(401, 403),
    )
    if status in (401, 403) or not z_data.get("result"):
        return {"checked": False, "created": [], "existing": []}
    zone_id = z_data["result"][0]["id"]
    r_status, r_data = cf.call("GET", f"/zones/{zone_id}/workers/routes", allow_statuses=(401, 403))
    if r_status in (401, 403):
        return {"checked": False, "created": [], "existing": []}
    by_pattern = {r.get("pattern"): r for r in (r_data.get("result") or [])}
    created, existing = [], []
    for pat in expected_routes:
        cur = by_pattern.get(pat)
        if cur and cur.get("script") == WORKER_NAME:
            existing.append(pat)
        elif cur and cur.get("id"):
            cf.call(
                "PUT",
                f"/zones/{zone_id}/workers/routes/{cur['id']}",
                payload={"pattern": pat, "script": WORKER_NAME},
            )
            created.append(pat)
        else:
            cf.call(
                "POST",
                f"/zones/{zone_id}/workers/routes",
                payload={"pattern": pat, "script": WORKER_NAME},
            )
            created.append(pat)
    return {"checked": True, "created": created, "existing": existing}


def deploy(env=None, repo_root=None, requester=None, out=None):
    env = os.environ if env is None else env
    out = sys.stdout if out is None else out
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    cf_dir = root / "deploy" / "cloudflare"

    token = _clean_env(env, "CLOUDFLARE_API_TOKEN")
    if not token:
        raise DeployError("CLOUDFLARE_API_TOKEN is not set in environment.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise DeployError(f"CLOUDFLARE_API_TOKEN contains unexpected characters (length {len(token)}).")

    cf = CloudflareClient(token, requester=requester)
    account_id = discover_account_id(cf, env)
    print("Cloudflare account: verified", file=out, flush=True)

    d1_info = ensure_d1_and_migrate(cf, account_id, cf_dir / "migrations")
    print(
        f"D1 database {D1_NAME}: {'created' if d1_info['created'] else 'present'} "
        f"(migrations applied: {', '.join(d1_info['migrations']) or 'none'})",
        file=out,
        flush=True,
    )

    ts_info = ensure_turnstile_widget(cf, account_id)
    print(
        f"Turnstile widget {TURNSTILE_NAME}: {'created' if ts_info['created'] else 'present'} "
        f"(sitekey: {ts_info['sitekey']})",
        file=out,
        flush=True,
    )

    wk_info = upload_worker(cf, account_id, cf_dir, d1_info["uuid"], ts_info["sitekey"])
    print(
        f"Worker {WORKER_NAME}: uploaded ({', '.join(wk_info['modules'])}, sha256={wk_info['sha256_12']}; "
        f"{WAE_BINDING}={WAE_DATASET}, {D1_BINDING}={D1_NAME}, existing secrets preserved)",
        file=out,
        flush=True,
    )

    upserted_secrets = []
    if ts_info.get("secret"):
        upsert_worker_secret(cf, account_id, "TURNSTILE_SECRET", ts_info["secret"])
        upserted_secrets.append("TURNSTILE_SECRET")
    intake_secret = _clean_env(env, "RP_INTAKE_SECRET")
    if intake_secret:
        upsert_worker_secret(cf, account_id, "RP_INTAKE_SECRET", intake_secret)
        upserted_secrets.append("RP_INTAKE_SECRET")
    if upserted_secrets:
        print(f"Worker secrets synced (SALT untouched): {', '.join(upserted_secrets)}", file=out, flush=True)

    cron = ensure_cron_schedule(cf, account_id)
    print(f"Cron trigger: {cron}", file=out, flush=True)

    routes_info = ensure_zone_routes(cf)
    if routes_info["checked"]:
        print(
            f"Routes verified on {ZONE_NAME}: existing={routes_info['existing']}, updated/created={routes_info['created']}",
            file=out,
            flush=True,
        )
    else:
        print(f"Routes on {ZONE_NAME}: unchanged (zone route scope not granted on token)", file=out, flush=True)

    return {
        "ok": True,
        "worker": WORKER_NAME,
        "d1": d1_info,
        "turnstile_sitekey": ts_info["sitekey"],
        "worker_sha256_12": wk_info["sha256_12"],
        "cron": cron,
        "routes": routes_info,
    }


def main(argv=None, env=None, repo_root=None, requester=None, out=None, err=None):
    _ = argv
    err = sys.stderr if err is None else err
    try:
        deploy(env=env, repo_root=repo_root, requester=requester, out=out)
        return 0
    except DeployError as e:
        print(f"deploy error: {e}", file=err, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
