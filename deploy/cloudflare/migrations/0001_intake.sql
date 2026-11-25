-- RunPapers sign-in-free intake schema for Cloudflare D1 (`runpapers_intake`, Spec 006).
-- Privacy invariant (AC 5): zero IP address columns and zero email columns anywhere in this schema.
-- Ephemeral salted hashes in `dedup_hashes` and `rate_windows` are deleted after 48 hours.

-- Website vote totals per canonical lowercase DOI (kept separate from GitHub thumbs-ups).
CREATE TABLE IF NOT EXISTS paper_votes (
  doi TEXT PRIMARY KEY,
  website_votes INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

-- Verified paper requests submitted on runpapers.com (resolved via Crossref / NCBI before insert; AC 2).
CREATE TABLE IF NOT EXISTS paper_requests (
  doi TEXT PRIMARY KEY,
  pmid TEXT,
  title TEXT NOT NULL,
  first_author TEXT,
  journal TEXT,
  year INTEGER,
  why TEXT,
  status TEXT NOT NULL DEFAULT 'pending_issue', -- pending_issue | issue_opened | duplicate
  github_issue_url TEXT,
  test_action TEXT NOT NULL DEFAULT '',         -- '' for real users; 'st-<hex>' for isolated self-tests
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON paper_requests(status, test_action, created_at);

-- Moderated comments and pack-problem reports (no email column, no IP column; AC 4, AC 5).
CREATE TABLE IF NOT EXISTS comments (
  id TEXT PRIMARY KEY,                          -- random hex id
  doi TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'comment',         -- comment | problem
  author_name TEXT,                             -- optional display name (<= 80 chars, no emails)
  body TEXT NOT NULL,                           -- plain text (<= 2000 chars, no emails)
  status TEXT NOT NULL DEFAULT 'pending',       -- pending | screened | approved | issue_opened
  screen_note TEXT,
  github_issue_url TEXT,
  test_action TEXT NOT NULL DEFAULT '',         -- '' for real users; 'st-<hex>' for isolated self-tests
  created_date TEXT NOT NULL,                   -- YYYY-MM-DD (UTC)
  created_at INTEGER NOT NULL                   -- epoch seconds
);
CREATE INDEX IF NOT EXISTS idx_comments_status ON comments(status, test_action, created_at);
CREATE INDEX IF NOT EXISTS idx_comments_doi_approved ON comments(doi, status, test_action);

-- Ephemeral daily-salted deduplication hashes (deleted after <= 48 hours; AC 1, AC 5).
CREATE TABLE IF NOT EXISTS dedup_hashes (
  hash TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dedup_created ON dedup_hashes(created_at);

-- Ephemeral hourly network rate-limit counters (20 submissions/hour/network; deleted after <= 48 hours; AC 3, AC 5).
CREATE TABLE IF NOT EXISTS rate_windows (
  net_hash TEXT PRIMARY KEY,
  submissions INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_created ON rate_windows(created_at);
