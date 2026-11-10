-- The status checker's store (docs/status.md). Times are Unix seconds; a state is one of the
-- four words 'ok', 'late', 'down', 'unknown'. One row a sample, kept 90 days.

CREATE TABLE samples (t INTEGER PRIMARY KEY,               -- the tick, a multiple of 300
  site TEXT NOT NULL, closings TEXT NOT NULL, chances TEXT NOT NULL, accounts TEXT NOT NULL,
  site_code INTEGER NOT NULL, closings_code INTEGER NOT NULL, chances_code INTEGER NOT NULL,
  accounts_code INTEGER NOT NULL,                          -- HTTP status of the try that stands; 0: no answer
  site_ms INTEGER, accounts_ms INTEGER,                    -- NULL: no answer
  closings_made INTEGER, chances_made INTEGER, closings_allow INTEGER NOT NULL, chances_allow INTEGER NOT NULL,
  closings_bytes INTEGER);                                 -- the closings body's length; NULL: no body

CREATE TABLE days (day TEXT NOT NULL, part TEXT NOT NULL,   -- 'YYYY-MM-DD', UTC
  ok INTEGER NOT NULL, late INTEGER NOT NULL, down INTEGER NOT NULL, PRIMARY KEY (day, part)) WITHOUT ROWID;

CREATE TABLE incidents (id INTEGER PRIMARY KEY, part TEXT NOT NULL,
  kind TEXT NOT NULL,                                      -- 'late' | 'down': the worst state in it
  start INTEGER NOT NULL, last INTEGER NOT NULL,           -- ticks of its first and latest not-ok sample
  ended INTEGER, gap INTEGER NOT NULL DEFAULT 0);          -- ended NULL: open. gap 1: the readings stopped

CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID;
-- k: 'first', 'processed' (ticks), 'summary' (the document the page reads)
