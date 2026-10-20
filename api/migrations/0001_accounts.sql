-- Snowlight accounts: users, sessions, rate limits, manual statuses and the admin log.
-- Times are Unix milliseconds (UTC). Passwords never reach the server: the
-- browser derives a key from the password (PBKDF2-SHA256, 600,000 iterations)
-- and the Worker keeps only SHA-256(salt || key) with a random per-user salt.
-- Push subscriptions and per-user notification settings come later in their own
-- migration (0002_...), keyed by users.id with ON DELETE CASCADE like sessions.

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  login TEXT NOT NULL UNIQUE,
  email TEXT UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  salt TEXT,
  key_hash TEXT,
  over13 INTEGER NOT NULL DEFAULT 0,
  schools TEXT NOT NULL DEFAULT '[]',
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  last_login_at INTEGER
);

CREATE INDEX users_created ON users (created_at);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  refreshed_at INTEGER NOT NULL
);

CREATE INDEX sessions_user ON sessions (user_id);
CREATE INDEX sessions_expires ON sessions (expires_at);

CREATE TABLE rate_limits (
  bucket TEXT PRIMARY KEY,
  count INTEGER NOT NULL,
  window_start INTEGER NOT NULL
);

CREATE TABLE overrides (
  key TEXT PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('district', 'school')),
  target_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('closed', 'delayed', 'early_dismissal', 'open')),
  minutes INTEGER,
  at_local_time TEXT,
  note TEXT,
  set_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  set_by TEXT
);

CREATE INDEX overrides_expires ON overrides (expires_at);

CREATE TABLE audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,
  actor_id TEXT,
  actor_name TEXT,
  action TEXT NOT NULL,
  target TEXT,
  detail TEXT
);

CREATE INDEX audit_at ON audit (at);
