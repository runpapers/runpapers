#!/usr/bin/env python3
"""End-to-end check of the usage counter on runpapers.com (run by .github/workflows/usage-selftest.yml).

1. Sends marked requests through Cloudflare as a browser, an AI agent, a crawler and a script (each twice), plus a
   style sheet and a missing page, and checks every response: served, through Cloudflare, no cookie.
2. Reads them back from Workers Analytics Engine with the read-only token (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID)
   and checks each page was counted exactly once, under the right kind and page type, and that the style sheet and
   the missing page were not counted.
3. Checks both HTTPS certificates: Cloudflare's (what visitors see) and GitHub Pages' own (behind the proxy), and
   warns when either has 14 days or less left.

Test rows carry the action "st-<run id>"; the nightly stats job ignores every action that starts with "st-".
Standard library only. Exit code 0 = everything passed.
"""
import datetime as dt
import json
import os
import secrets
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

SITE = os.environ.get("RP_SITE", "https://runpapers.com")
HOST = SITE.split("://", 1)[1].strip("/")
PAPER = os.environ.get("RP_PAPER", "10-1016-j-cell-2026-10-012")
GITHUB_PAGES_IP = "185.199.108.153"
UA = {
    "person": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/142.0.0.0 Safari/537.36",
    "agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; "
             "+Claude-User@anthropic.com)",
    "crawler": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "script": "curl/8.5.0",
}
# (who asks, path, expected status, expected (type, paper) when counted, or None when it must not be counted)
CASES = [
    ("person", f"/papers/{PAPER}/", 200, ("html", PAPER)),
    ("agent", f"/papers/{PAPER}/AGENT.md", 200, ("agent", PAPER)),
    ("crawler", f"/papers/{PAPER}/index.md", 200, ("md", PAPER)),
    ("script", f"/papers/{PAPER}/pack.json", 200, ("pack", PAPER)),
    ("person", "/", 200, ("html", "")),
    ("person", "/style.css", 200, None),
    ("person", f"/papers/{PAPER}/no-such-page-selftest", 404, None),
]

results = []   # (ok, check, detail)


def check(ok, name, detail=""):
    results.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)
    return ok


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def get(url, ua, action):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "X-RunPapers-Action": action})
    try:
        with OPENER.open(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def send_requests(action):
    for kind, path, status, _ in CASES:
        for attempt in (1, 2):
            code, headers, _ = get(SITE + path, UA[kind], action)
            if attempt == 1:
                check(code == status, f"{path} as {kind}: HTTP {status}", f"got {code}")
                check("cf-ray" in headers, f"{path}: served through Cloudflare")
                check("set-cookie" not in headers, f"{path}: no cookie set")
            time.sleep(2)   # the first request's "seen" mark must be stored before the repeat arrives
    code, headers, _ = get(f"https://www.{HOST}/", UA["person"], action)
    check(code == 301 and headers.get("location", "").rstrip("/") == SITE, f"www.{HOST} redirects to {SITE}",
          f"got {code} {headers.get('location', '')}")


def cf_api(path, body=None):
    token, account = os.environ.get("CLOUDFLARE_API_TOKEN", ""), os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4" + path.format(account=account),
        data=body.encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def read_back(action, want):
    sql = ("SELECT blob1 AS kind, blob2 AS type, blob3 AS paper, blob5 AS path, SUM(_sample_interval) AS n "
           f"FROM runpapers_hits WHERE blob4 = '{action}' AND timestamp > NOW() - INTERVAL '1' HOUR "
           "GROUP BY kind, type, paper, path FORMAT JSON")
    rows, deadline = None, time.time() + 420
    while time.time() < deadline:
        code, text = cf_api("/accounts/{account}/analytics_engine/sql", sql)
        if code != 200:
            check(False, "read the counts with the token (Account Analytics: Read)", f"HTTP {code}: {text[:300]}")
            return []
        rows = json.loads(text).get("data", [])
        if len(rows) >= len(want):
            time.sleep(45)   # let any duplicate arrive before judging
            rows = json.loads(cf_api("/accounts/{account}/analytics_engine/sql", sql)[1]).get("data", [])
            break
        time.sleep(20)
    check(rows is not None, "read the counts with the token (Account Analytics: Read)")
    return rows or []


def cert_days(connect_host, sni):
    ctx = ssl.create_default_context()
    with socket.create_connection((connect_host, 443), timeout=20) as sock:
        with ctx.wrap_socket(sock, server_hostname=sni) as s:
            cert = s.getpeercert()
    end = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
    issuer = dict(x[0] for x in cert["issuer"]).get("organizationName", "?")
    return (end - dt.datetime.now(dt.timezone.utc)).days, end.date().isoformat(), issuer


def main():
    action = "st-" + secrets.token_hex(4)
    print(f"Self-test run {action} against {SITE}\n", flush=True)

    has_token = check(os.environ.get("CLOUDFLARE_API_TOKEN"), "GitHub secret CLOUDFLARE_API_TOKEN is set")
    has_account = check(os.environ.get("CLOUDFLARE_ACCOUNT_ID"), "GitHub variable CLOUDFLARE_ACCOUNT_ID is set")
    if has_token:
        code, text = cf_api("/user/tokens/verify")
        if code != 200 and has_account:
            code, text = cf_api("/accounts/{account}/tokens/verify")
        status = (json.loads(text).get("result") or {}).get("status") if text.startswith("{") else None
        check(code == 200 and status == "active", "the Cloudflare token is active", f"HTTP {code}, status {status}")

    send_requests(action)

    want = {(kind, typ, paper, path): 1 for kind, path, _, exp in CASES if exp for (typ, paper) in [exp]}
    rows = read_back(action, want) if has_token and has_account else []
    got = {(r["kind"], r["type"], r["paper"], r["path"]): int(float(r["n"])) for r in rows}
    for key, n in want.items():
        kind, typ, paper, path = key
        check(got.get(key) == n, f"counted once: {path} as {kind} ({typ})", f"counted {got.get(key, 0)}")
    for key, n in got.items():
        if key not in want:
            check(False, f"nothing else counted", f"unexpected {key} x{n}")
    if rows and all(k in want for k in got):
        check(True, "style sheets and missing pages are not counted")

    for label, connect in (("Cloudflare (what visitors see)", HOST), ("GitHub Pages, behind Cloudflare", GITHUB_PAGES_IP)):
        try:
            days, end, issuer = cert_days(connect, HOST)
            check(days > 14, f"HTTPS certificate, {label}", f"{issuer}, valid until {end} ({days} days left)")
        except Exception as e:   # noqa: BLE001
            check(False, f"HTTPS certificate, {label}", f"{type(e).__name__}: {e}")

    failed = [r for r in results if not r[0]]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## Usage counter self-test {action}: {'all passed' if not failed else f'{len(failed)} failed'}\n\n")
            f.write("| | Check | Detail |\n|---|---|---|\n")
            for ok, name, detail in results:
                f.write(f"| {'✅' if ok else '❌'} | {name} | {detail} |\n")
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
