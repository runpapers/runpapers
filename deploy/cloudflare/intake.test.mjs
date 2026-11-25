// node --test deploy/cloudflare/intake.test.mjs
// Offline test suite for Spec 006-T1 (Acceptance checks 1, 2, 3, 4, 5 + st-* isolation + deploy config).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

import worker from "./worker.js";
import {
  cleanupExpiredHashes,
  containsEmail,
  doiSlug,
  networkPrefix,
  normalizeDoi,
  parsePaperQuery,
} from "./intake.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MIGRATION_SQL = fs.readFileSync(path.join(HERE, "migrations", "0001_intake.sql"), "utf8");

// Real in-memory SQLite adapter matching Cloudflare D1's binding API (including rejecting `undefined` binds).
function createTestD1() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(MIGRATION_SQL);

  function makeStmt(sql, bound = []) {
    return {
      bind(...vals) {
        if (vals.some((v) => v === undefined)) {
          throw new TypeError(`D1 bind rejects undefined values in SQL: ${sql}`);
        }
        return makeStmt(sql, vals);
      },
      async run() {
        const res = sqlite.prepare(sql).run(...bound);
        return {
          success: true,
          meta: { changes: Number(res.changes || 0), last_row_id: Number(res.lastInsertRowid || 0) },
        };
      },
      async first(col) {
        const row = sqlite.prepare(sql).get(...bound) ?? null;
        if (!row) return null;
        return col ? row[col] : { ...row };
      },
      async all() {
        const rows = sqlite.prepare(sql).all(...bound).map((r) => ({ ...r }));
        return { success: true, results: rows };
      },
    };
  }

  return {
    sqlite,
    prepare(sql) {
      return makeStmt(sql);
    },
    async batch(stmts) {
      const out = [];
      for (const s of stmts) out.push(await s.run());
      return out;
    },
  };
}

function makeTestEnv(overrides = {}) {
  const db = createTestD1();
  const waits = [];
  const ctx = { waitUntil: (p) => waits.push(p) };
  const env = {
    SALT: "unit-test-salt-secret",
    TURNSTILE_SECRET: "ts-secret-key",
    RP_INTAKE_SECRET: "admin-shared-secret-token",
    DB: db,
    HITS: { writeDataPoint: () => {} },
    _NOW_MS: Date.UTC(2026, 10, 25, 14, 0, 0),   // 2026-11-25T14:00:00Z
    ...overrides,
  };
  return { env, db, ctx, flush: () => Promise.all(waits.splice(0)) };
}

function mockNetwork({ validTokens = new Set(["valid-ts-token"]), crossrefWorks = {}, pubmedSummaries = {}, idconvRecords = {}, catalog = { papers: [], requests: [] } } = {}) {
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (url === "https://challenges.cloudflare.com/turnstile/v0/siteverify") {
      const payload = JSON.parse(init.body || "{}");
      assert.equal(payload.remoteip, undefined, "Turnstile payload must not transmit visitor IP");
      const ok = validTokens.has(payload.response);
      return new Response(JSON.stringify({ success: ok }), { status: 200 });
    }
    if (url.endsWith("/index.json")) {
      return new Response(JSON.stringify(catalog), { status: 200 });
    }
    if (url.startsWith("https://api.crossref.org/works/")) {
      const doi = decodeURIComponent(url.slice("https://api.crossref.org/works/".length)).toLowerCase();
      if (crossrefWorks[doi]) {
        return new Response(JSON.stringify({ status: "ok", message: crossrefWorks[doi] }), { status: 200 });
      }
      return new Response("Not found", { status: 404 });
    }
    if (url.startsWith("https://api.crossref.org/works?query.bibliographic=")) {
      const items = Object.values(crossrefWorks);
      return new Response(JSON.stringify({ status: "ok", message: { items } }), { status: 200 });
    }
    if (url.startsWith("https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/")) {
      const u = new URL(url);
      const id = u.searchParams.get("ids") || "";
      const rec = idconvRecords[id.toLowerCase()] || idconvRecords[id];
      return new Response(JSON.stringify({ records: rec ? [rec] : [] }), { status: 200 });
    }
    if (url.startsWith("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi")) {
      const u = new URL(url);
      const pmid = u.searchParams.get("id") || "";
      const rec = pubmedSummaries[pmid];
      if (!rec) return new Response(JSON.stringify({ result: {} }), { status: 200 });
      return new Response(JSON.stringify({ result: { [pmid]: rec } }), { status: 200 });
    }
    throw new Error(`Unexpected outbound fetch in offline test: ${url}`);
  };
}

function postJson(pathUrl, body, { ip = "203.0.113.9", ua = "Mozilla/5.0 Chrome/131.0", origin = "https://runpapers.com", headers = {} } = {}) {
  return new Request(`https://runpapers.com${pathUrl}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "CF-Connecting-IP": ip,
      "User-Agent": ua,
      ...(origin ? { Origin: origin } : {}),
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

test("test_vote_dedup_same_day_and_turnstile_required (AC 1)", async () => {
  mockNetwork();
  const { env, ctx, flush } = makeTestEnv();
  const doi = "10.1016/j.cell.2026.10.012";

  // 1. Vote without a Turnstile token is refused (403)
  const rMissing = await worker.fetch(postJson("/_rp/api/vote", { doi }), env, ctx);
  assert.equal(rMissing.status, 403);
  assert.equal((await rMissing.json()).ok, false);

  // 2. Vote with an invalid Turnstile token is refused (403)
  const rBad = await worker.fetch(postJson("/_rp/api/vote", { doi, turnstile_token: "forged-token" }), env, ctx);
  assert.equal(rBad.status, 403);

  // 3. First valid vote from browser+network counts once
  const r1 = await worker.fetch(postJson("/_rp/api/vote", { doi: `https://doi.org/${doi.toUpperCase()}`, turnstile_token: "valid-ts-token" }), env, ctx);
  assert.equal(r1.status, 200);
  const j1 = await r1.json();
  assert.deepEqual(j1, { ok: true, doi, counted: true, already_voted: false, website_votes: 1 });

  // 4. Voting a second time from the same browser+network on the same UTC day does NOT increment
  const r2 = await worker.fetch(postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }), env, ctx);
  assert.equal(r2.status, 200);
  const j2 = await r2.json();
  assert.deepEqual(j2, { ok: true, doi, counted: false, already_voted: true, website_votes: 1 });

  // 5. Different visitor on the same day increments to 2; same original visitor on the next UTC day increments to 3
  const rOther = await worker.fetch(postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }, { ip: "198.51.100.42" }), env, ctx);
  assert.equal((await rOther.json()).website_votes, 2);

  env._NOW_MS += 24 * 3600 * 1000;
  const rNextDay = await worker.fetch(postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }), env, ctx);
  assert.equal((await rNextDay.json()).website_votes, 3);
  await flush();

  // Public counts endpoint reflects exact website votes and sets no cookies
  const rPub = await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), env, ctx);
  assert.equal(rPub.status, 200);
  assert.equal(rPub.headers.get("set-cookie"), null);
  assert.deepEqual(await rPub.json(), { votes: { [doi]: 3 }, approved_comments: {} });
});

test("test_request_unresolvable_refused_and_existing_becomes_vote (AC 2)", async () => {
  const newDoi = "10.1038/s41586-026-09999-1";
  const ghReqDoi = "10.1126/science.adz1234";
  const availDoi = "10.1016/j.cell.2026.10.012";

  const raceDoi = "10.1038/s41593-026-08888-2";
  mockNetwork({
    crossrefWorks: {
      [newDoi]: {
        DOI: newDoi,
        title: ["Conserved interneuron programs across primate striatum"],
        author: [{ given: "Mei", family: "Lin" }],
        "container-title": ["Nature"],
        issued: { "date-parts": [[2026, 9, 1]] },
      },
      [raceDoi]: {
        DOI: raceDoi,
        title: ["Concurrent cortical projection atlas"],
        author: [{ given: "Kai", family: "Chen" }],
        "container-title": ["Nature Neuroscience"],
        issued: { "date-parts": [[2026, 8, 15]] },
      },
      [ghReqDoi]: {
        DOI: ghReqDoi,
        title: ["Human spinal nociceptor atlas"],
        author: [{ given: "Sam", family: "Patel" }],
        "container-title": ["Science"],
        issued: { "date-parts": [[2025, 11, 10]] },
      },
      [availDoi]: {
        DOI: availDoi,
        title: ["Primate basal ganglia atlas"],
        author: [{ given: "A.", family: "Author" }],
        "container-title": ["Cell"],
        issued: { "date-parts": [[2026, 10, 12]] },
      },
    },
    idconvRecords: {
      [newDoi]: { doi: newDoi, pmid: "39990001" },
    },
    pubmedSummaries: {
      "39990001": {
        title: "Conserved interneuron programs across primate striatum.",
        articleids: [{ idtype: "doi", value: newDoi }],
        authors: [{ name: "Lin M" }],
        fulljournalname: "Nature",
        pubdate: "2026 Sep",
      },
    },
    catalog: {
      papers: [{ doi: availDoi, pmid: "43020019", title: "Primate basal ganglia atlas" }],
      requests: [{ doi: ghReqDoi, title: "Human spinal nociceptor atlas", votes: 4 }],
    },
  });

  const { env, ctx, flush } = makeTestEnv();

  // 1. Unresolvable DOI is refused cleanly with HTTP 422 and plain message
  const rUnres = await worker.fetch(
    postJson("/_rp/api/request", { query: "10.9999/does-not-exist-2026", turnstile_token: "valid-ts-token" }),
    env,
    ctx,
  );
  assert.equal(rUnres.status, 422);
  const jUnres = await rUnres.json();
  assert.equal(jUnres.ok, false);
  assert.match(jUnres.error, /Could not find a published paper/i);

  // 2. Already-available pack returns mode='already_available' and canonical URL without queuing
  const rAvail = await worker.fetch(
    postJson("/_rp/api/request", { query: availDoi, turnstile_token: "valid-ts-token" }),
    env,
    ctx,
  );
  assert.equal(rAvail.status, 200);
  assert.deepEqual(await rAvail.json(), {
    ok: true,
    mode: "already_available",
    doi: availDoi,
    title: "Primate basal ganglia atlas",
    url: "/papers/10-1016-j-cell-2026-10-012/",
  });

  // 3. New valid paper (submitted by PMID) resolves to canonical DOI, queues once ('pending_issue'), and records 1 vote
  const rNew = await worker.fetch(
    postJson("/_rp/api/request", {
      query: "PMID: 39990001",
      why: "Needed to compare macaque interneuron markers.",
      turnstile_token: "valid-ts-token",
    }),
    env,
    ctx,
  );
  assert.equal(rNew.status, 200);
  const jNew = await rNew.json();
  assert.equal(jNew.mode, "created");
  assert.equal(jNew.status, "pending_issue");
  assert.equal(jNew.doi, newDoi);
  assert.equal(jNew.pmid, "39990001");
  assert.equal(jNew.website_votes, 1);

  // 4. Requesting that same paper again (by exact title from a second visitor) becomes a vote instead of a duplicate row
  const rDup = await worker.fetch(
    postJson(
      "/_rp/api/request",
      { query: "Conserved interneuron programs across primate striatum", turnstile_token: "valid-ts-token" },
      { ip: "198.51.100.77" },
    ),
    env,
    ctx,
  );
  assert.equal(rDup.status, 200);
  const jDup = await rDup.json();
  assert.equal(jDup.mode, "voted_existing");
  assert.equal(jDup.counted, true);
  assert.equal(jDup.website_votes, 2);

  // 5. Paper already requested on GitHub (in index.json.requests) also becomes a vote instead of queuing a second issue
  const rGhExisting = await worker.fetch(
    postJson("/_rp/api/request", { query: ghReqDoi, turnstile_token: "valid-ts-token" }),
    env,
    ctx,
  );
  assert.equal((await rGhExisting.json()).mode, "voted_existing");
  // 6. Concurrent requests for a brand-new paper never 503 on PRIMARY KEY collision: one creates, the other votes
  const [rRaceA, rRaceB] = await Promise.all([
    worker.fetch(
      postJson("/_rp/api/request", { query: raceDoi, turnstile_token: "valid-ts-token" }, { ip: "198.51.100.81" }),
      env,
      ctx,
    ),
    worker.fetch(
      postJson("/_rp/api/request", { query: raceDoi, turnstile_token: "valid-ts-token" }, { ip: "198.51.100.82" }),
      env,
      ctx,
    ),
  ]);
  assert.equal(rRaceA.status, 200);
  assert.equal(rRaceB.status, 200);
  const modes = [(await rRaceA.json()).mode, (await rRaceB.json()).mode].sort();
  assert.deepEqual(modes, ["created", "voted_existing"]);
  await flush();

  // Admin queue has ONLY the two new pending requests (`newDoi` and `raceDoi`), and `raceDoi` has 2 votes
  const rQueue = await worker.fetch(
    new Request("https://runpapers.com/_rp/api/admin/queue", {
      headers: { Authorization: "Bearer admin-shared-secret-token" },
    }),
    env,
    ctx,
  );
  assert.equal(rQueue.status, 200);
  const q = await rQueue.json();
  assert.deepEqual(q.pending_requests.map((r) => r.doi).sort(), [newDoi, raceDoi].sort());
  const pubSnap = await (await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), env, ctx)).json();
  assert.equal(pubSnap.votes[raceDoi], 2);
});

test("test_network_rate_limit_20_per_hour (AC 3)", async () => {
  mockNetwork();
  const { env, ctx, flush } = makeTestEnv();
  const doi = "10.1016/j.cell.2026.10.012";

  // 20 submissions across hosts in the same IPv4 /24 succeed
  for (let i = 1; i <= 20; i++) {
    const r = await worker.fetch(
      postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }, { ip: `203.0.113.${i}`, ua: `Browser/${i}` }),
      env,
      ctx,
    );
    assert.equal(r.status, 200, `submission ${i} should pass`);
  }

  // 21st submission from the same /24 in the same hour is refused with 429
  const r21 = await worker.fetch(
    postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }, { ip: "203.0.113.250", ua: "Browser/21" }),
    env,
    ctx,
  );
  assert.equal(r21.status, 429);
  assert.match((await r21.json()).error, /More than 20 submissions this hour/i);

  // Different network (/48 IPv6) is unaffected, and advancing 1 hour resets the window
  assert.equal(networkPrefix("2001:db8:abcd:0001::1"), "2001:0db8:abcd::/48");
  assert.equal(networkPrefix("2001:0db8:abcd:9999::2"), "2001:0db8:abcd::/48");
  const rOtherNet = await worker.fetch(
    postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }, { ip: "2001:db8:abcd::1" }),
    env,
    ctx,
  );
  assert.equal(rOtherNet.status, 200);

  env._NOW_MS += 3600 * 1000;
  const rNextHour = await worker.fetch(
    postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }, { ip: "203.0.113.250" }),
    env,
    ctx,
  );
  assert.equal(rNextHour.status, 200);
  await flush();
});

test("test_unapproved_comments_never_exposed_publicly (AC 4)", async () => {
  mockNetwork();
  const { env, ctx, flush } = makeTestEnv();
  const doi = "10.1016/j.cell.2026.10.012";

  // Submit two comments (one with optional name, one anonymous) and one problem report
  const c1 = await (await worker.fetch(
    postJson("/_rp/api/comment", {
      doi,
      kind: "comment",
      name: "Dr. Rivera",
      body: "Figure 2F donor-level proportions match our independent macaque cohort.",
      turnstile_token: "valid-ts-token",
    }),
    env,
    ctx,
  )).json();
  const c2 = await (await worker.fetch(
    postJson("/_rp/api/comment", {
      doi,
      kind: "comment",
      body: "Anonymous unapproved comment that must stay hidden.",
      turnstile_token: "valid-ts-token",
    }),
    env,
    ctx,
  )).json();
  const prob = await (await worker.fetch(
    postJson("/_rp/api/comment", {
      doi,
      kind: "problem",
      body: "Download link in data entry 2 timed out.",
      turnstile_token: "valid-ts-token",
    }),
    env,
    ctx,
  )).json();
  assert.equal(c1.status, "pending");
  assert.equal(c2.status, "pending");
  assert.equal(prob.status, "pending");
  await flush();

  // 1. Before approval: public-counts exposes ZERO comments
  const snapBefore = await (await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), env, ctx)).json();
  assert.deepEqual(snapBefore.approved_comments, {});

  // 2. Unauthorized admin calls are rejected (401)
  const rUnauth = await worker.fetch(new Request("https://runpapers.com/_rp/api/admin/queue"), env, ctx);
  assert.equal(rUnauth.status, 401);

  // 3. Operator screens c1 -> still NOT exposed publicly while in 'screened' state
  const authHdr = { Authorization: "Bearer admin-shared-secret-token" };
  await worker.fetch(
    postJson("/_rp/api/admin/moderate", { id: c1.id, verdict: "screen", screen_note: "Clean scientific note" }, { headers: authHdr }),
    env,
    ctx,
  );
  const snapScreened = await (await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), env, ctx)).json();
  assert.deepEqual(snapScreened.approved_comments, {});

  // 4. Maintainer approves c1 -> ONLY c1 appears publicly, carrying strictly {id, name, created_date, body} (no screen_note, no exact timestamp)
  await worker.fetch(
    postJson("/_rp/api/admin/moderate", { id: c1.id, verdict: "approve" }, { headers: authHdr }),
    env,
    ctx,
  );
  const snapApproved = await (await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), env, ctx)).json();
  assert.deepEqual(snapApproved.approved_comments, {
    [doi]: [
      {
        id: c1.id,
        name: "Dr. Rivera",
        created_date: "2026-11-25",
        body: "Figure 2F donor-level proportions match our independent macaque cohort.",
      },
    ],
  });
});

test("test_zero_ip_or_email_stored_and_48h_hash_cleanup_and_selftest_isolation (AC 5)", async () => {
  const doi = "10.1016/j.cell.2026.10.012";
  mockNetwork({
    crossrefWorks: {
      [doi]: {
        DOI: doi,
        title: ["Primate basal ganglia atlas"],
        author: [{ given: "A.", family: "Author" }],
        "container-title": ["Cell"],
        issued: { "date-parts": [[2026, 10, 12]] },
      },
    },
  });
  const { env, db, ctx, flush } = makeTestEnv();
  const sampleEmail = "researcher@example.org";
  const clientIp4 = "203.0.113.55";
  const clientIp6 = "2001:db8:cafe:1234::99";

  // 1. Schema inspection: zero IP or email columns in any D1 table
  const tables = db.sqlite.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").all().map((r) => r.name);
  assert.deepEqual(tables, ["comments", "dedup_hashes", "paper_requests", "paper_votes", "rate_windows"]);
  for (const tbl of tables) {
    const cols = db.sqlite.prepare(`PRAGMA table_info(${tbl})`).all().map((c) => c.name.toLowerCase());
    for (const col of cols) {
      assert.ok(!col.includes("ip") && !col.includes("email"), `forbidden PII column ${tbl}.${col}`);
    }
  }

  // 2. Email addresses in comment name, comment body, or request why are rejected with 400 and never stored
  assert.equal(containsEmail(sampleEmail), true);
  const rEmailName = await worker.fetch(
    postJson("/_rp/api/comment", { doi, name: sampleEmail, body: "Nice pack", turnstile_token: "valid-ts-token" }, { ip: clientIp4 }),
    env,
    ctx,
  );
  assert.equal(rEmailName.status, 400);
  const rEmailBody = await worker.fetch(
    postJson("/_rp/api/comment", { doi, body: `Contact me at ${sampleEmail}`, turnstile_token: "valid-ts-token" }, { ip: clientIp4 }),
    env,
    ctx,
  );
  assert.equal(rEmailBody.status, 400);
  const rEmailWhy = await worker.fetch(
    postJson("/_rp/api/request", { query: doi, why: `Send updates to ${sampleEmail}`, turnstile_token: "valid-ts-token" }, { ip: clientIp6 }),
    env,
    ctx,
  );
  assert.equal(rEmailWhy.status, 400);

  // 3. Valid vote + comment, then reject comment -> rejected comment row is permanently DELETEd from D1
  await worker.fetch(postJson("/_rp/api/vote", { doi, turnstile_token: "valid-ts-token" }, { ip: clientIp4 }), env, ctx);
  const spamRes = await (await worker.fetch(
    postJson("/_rp/api/comment", { doi, body: "Spam text to purge", turnstile_token: "valid-ts-token" }, { ip: clientIp6 }),
    env,
    ctx,
  )).json();
  await flush();

  const authHdr = { Authorization: "Bearer admin-shared-secret-token" };
  const rReject = await worker.fetch(
    postJson("/_rp/api/admin/moderate", { id: spamRes.id, verdict: "reject" }, { headers: authHdr }),
    env,
    ctx,
  );
  assert.equal((await rReject.json()).deleted, true);
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM comments WHERE id = ?").get(spamRes.id).n, 0);

  // 4. Dump entire SQLite database contents: zero raw IPv4, IPv6, /24, /48, or email strings anywhere
  const fullDump = {};
  for (const tbl of tables) fullDump[tbl] = db.sqlite.prepare(`SELECT * FROM ${tbl}`).all();
  const serialized = JSON.stringify(fullDump);
  for (const forbidden of [clientIp4, "203.0.113", clientIp6, "2001:db8", "2001:0db8", sampleEmail]) {
    assert.ok(!serialized.includes(forbidden), `database must never contain ${forbidden}`);
  }
  assert.equal(fullDump.dedup_hashes.length, 1);
  assert.ok(fullDump.rate_windows.length >= 1);

  // 5. 48-hour hash cleanup: preserved at 47h59m59s, deleted at 48h00m00s via scheduled() (and cleanupExpiredHashes)
  const t0 = fullDump.dedup_hashes[0].created_at;
  await cleanupExpiredHashes(db, t0 + 48 * 3600 - 1);
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM dedup_hashes").get().n, 1);

  env._NOW_MS = (t0 + 48 * 3600) * 1000;
  await worker.scheduled({}, env, null);
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM dedup_hashes").get().n, 0);
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM rate_windows").get().n, 0);

  // 6. Self-test (`st-...`) isolation: unauthenticated `st-...` still requires Turnstile; authenticated `st-...` never leaks publicly
  const rUnauthSt = await worker.fetch(postJson("/_rp/api/vote", { doi, test_action: "st-deadbeef" }), env, ctx);
  assert.equal(rUnauthSt.status, 403);

  const rStVote = await worker.fetch(
    postJson("/_rp/api/vote", { doi, test_action: "st-deadbeef" }, { headers: authHdr }),
    env,
    ctx,
  );
  assert.equal(rStVote.status, 200);
  assert.equal((await rStVote.json()).isolated_test, true);

  const rStReq = await worker.fetch(
    postJson("/_rp/api/request", { query: doi, test_action: "st-deadbeef" }, { headers: authHdr }),
    env,
    ctx,
  );
  assert.equal((await rStReq.json()).isolated_test, true);

  const rStCom = await worker.fetch(
    postJson("/_rp/api/comment", { doi, body: "Selftest comment", test_action: "st-deadbeef" }, { headers: authHdr }),
    env,
    ctx,
  );
  const jStCom = await rStCom.json();
  await worker.fetch(postJson("/_rp/api/admin/moderate", { id: jStCom.id, verdict: "approve" }, { headers: authHdr }), env, ctx);

  // Public counts and default admin queue exclude all `st-deadbeef` items
  const pubAfterSt = await (await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), env, ctx)).json();
  assert.equal(pubAfterSt.votes[doi], 1);   // only the 1 real vote, not the st-deadbeef vote
  assert.deepEqual(pubAfterSt.approved_comments, {});

  const qDefault = await (await worker.fetch(new Request("https://runpapers.com/_rp/api/admin/queue", { headers: authHdr }), env, ctx)).json();
  assert.equal(qDefault.pending_requests.length, 0);

  // Cleanup removes all `st-deadbeef` rows cleanly
  await worker.fetch(
    postJson("/_rp/api/admin/moderate", { verdict: "cleanup_selftest", test_action: "st-deadbeef" }, { headers: authHdr }),
    env,
    ctx,
  );
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM paper_votes WHERE doi LIKE 'st-%'").get().n, 0);
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM paper_requests WHERE test_action != ''").get().n, 0);
  assert.equal(db.sqlite.prepare("SELECT COUNT(*) AS n FROM comments WHERE test_action != ''").get().n, 0);
});

test("ID helpers and deploy configuration stay single-file and zero-dependency", async () => {
  assert.equal(normalizeDoi("HTTPS://doi.org/10.1016/J.CELL.2026.10.012"), "10.1016/j.cell.2026.10.012");
  assert.equal(await doiSlug("10.1016/j.cell.2026.10.012"), "10-1016-j-cell-2026-10-012");
  const longDoi = "10.1016/j.very-long-journal-identifier-for-testing-truncation.2026.100999";
  const slug = await doiSlug(longDoi);
  assert.ok(slug.length <= 54);
  assert.deepEqual(parsePaperQuery("https://pubmed.ncbi.nlm.nih.gov/43020019/"), { kind: "pmid", value: "43020019" });
  assert.deepEqual(parsePaperQuery("pmc1234567"), { kind: "pmcid", value: "PMC1234567" });

  // worker.js has zero import statements so deploy.py can upload it directly without external bundlers
  const workerSrc = fs.readFileSync(path.join(HERE, "worker.js"), "utf8");
  assert.ok(!/^\s*import\s+/m.test(workerSrc), "worker.js must remain self-contained with zero imports");

  const wranglerToml = fs.readFileSync(path.join(HERE, "wrangler.toml"), "utf8");
  assert.match(wranglerToml, /name\s*=\s*"runpapers-counter"/);
  assert.match(wranglerToml, /dataset\s*=\s*"runpapers_hits"/);
  assert.match(wranglerToml, /database_name\s*=\s*"runpapers_intake"/);
  assert.match(wranglerToml, /crons\s*=\s*\["17 \* \* \* \*"\]/);

  // Broken or missing D1 binding on `/_rp/api/*` returns clean JSON 503 rather than an unhandled Worker exception
  const rNoDb = await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), {}, null);
  assert.equal(rNoDb.status, 503);
  const brokenDbEnv = { DB: { prepare: () => { throw new Error("D1 unavailable"); } } };
  const rBrokenDb = await worker.fetch(new Request("https://runpapers.com/_rp/api/public-counts"), brokenDbEnv, null);
  assert.equal(rBrokenDb.status, 503);
  assert.equal((await rBrokenDb.json()).ok, false);
});
