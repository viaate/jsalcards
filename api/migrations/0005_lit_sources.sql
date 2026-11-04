-- Where each lit closing came from, for the admin page only (docs/live.md, Admin sources). Additive
-- and safe on the live database: new tables only. The live reader writes them over the Cloudflare
-- API (pipeline/snowlight/live/sources.py); the Worker reads them for GET /v1/admin/sources, which
-- only the admin may call. Codes, ids, links and times only: never a list's text.

-- One row per local day: the summary's sha256 (of the raw JSON), its part count, how many
-- statuses it holds, the publish it is from (published_at), when it was written (written_at),
-- the publisher's mode ('on', or 'shadow': not on the public map) and latest_at, the
-- publisher's last publish when it is later than published_at (a blank publish, or an upload
-- that failed after the closings file, does not rewrite the sources; NULL otherwise).
CREATE TABLE IF NOT EXISTS lit_sources_head (
  day TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  parts INTEGER NOT NULL,
  closings INTEGER NOT NULL,
  published_at TEXT NOT NULL,
  written_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  latest_at TEXT
);

-- The day's summary: gzip, cut into 64 KiB pieces, each base64.
CREATE TABLE IF NOT EXISTS lit_sources (
  day TEXT NOT NULL,
  n INTEGER NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (day, n)
) WITHOUT ROWID;

-- The rows the reader's writes to these tables took each UTC day (capped at 5,000).
CREATE TABLE IF NOT EXISTS lit_sources_budget (day TEXT PRIMARY KEY, rows INTEGER NOT NULL);
