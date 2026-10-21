-- Usernames, join numbers, the admin's moderation terms, and login keys for a username.
-- Additive and safe on the live database: new columns and tables only, plus
-- filling them in for the accounts that exist, and the deletion scrub of the
-- admin log (no email stays in it).
--
-- Login keys: an account has two. One for logging in by email (salt,
-- key_hash as before), whose client salt is SHA-256 of "snowlight-v1|" + email
-- as in v1 (email_salt records it; NULL marks an account with no username key
-- yet), and one for logging in by username (name_salt, its random client salt
-- that POST /v1/login/salt hands back, name_key_salt, name_key_hash). Two keys
-- with unrelated salts keep an email and a username unlinkable from outside.

ALTER TABLE users ADD COLUMN username TEXT;
ALTER TABLE users ADD COLUMN join_number INTEGER;
ALTER TABLE users ADD COLUMN rename_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN email_salt TEXT;
ALTER TABLE users ADD COLUMN name_salt TEXT;
ALTER TABLE users ADD COLUMN name_key_salt TEXT;
ALTER TABLE users ADD COLUMN name_key_hash TEXT;
-- 1 once the new Worker has numbered the account (or found no number left).
-- A row the old Worker makes after this migration keeps the default 0 and
-- gets its number at its next login.
ALTER TABLE users ADD COLUMN numbered INTEGER NOT NULL DEFAULT 0;

-- The admin is always #0001 and its username is its login (ADMIN_USERNAME, lowercased).
UPDATE users SET username = login
 WHERE id = (SELECT id FROM users WHERE role = 'admin' ORDER BY created_at, id LIMIT 1);
UPDATE users SET join_number = 1
 WHERE id = (SELECT id FROM users WHERE role = 'admin' ORDER BY created_at, id LIMIT 1);

-- Accounts that exist get numbers in sign-up order after #0001, up to #9999.
UPDATE users SET join_number = 1 + (
  SELECT COUNT(*) FROM users AS u
   WHERE u.role = 'user'
     AND (u.created_at < users.created_at OR (u.created_at = users.created_at AND u.id <= users.id))
) WHERE role = 'user';
UPDATE users SET join_number = NULL WHERE join_number > 9999;
UPDATE users SET numbered = 1;

CREATE UNIQUE INDEX users_username ON users (username);
CREATE UNIQUE INDEX users_join_number ON users (join_number);

-- The last join number handed out, which only ever goes up (to 9999), and the
-- account it last went up for (holder: the Worker gives that account the
-- number in the same transaction). Numbers are never reused: a deleted
-- account's stays retired.
CREATE TABLE counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL,
  holder TEXT
);
INSERT INTO counters (name, value) VALUES ('join', MIN(9999, 1 + (SELECT COUNT(*) FROM users WHERE role = 'user')));

-- Sign-ups per network (an IPv4 /24 or IPv6 /64, never a whole address) per
-- UTC day, kept 14 days, so the admin overview can list a network that made
-- 5 or more accounts in a day.
CREATE TABLE signup_networks (
  network TEXT NOT NULL,
  day TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (network, day)
);

-- The admin's own blocklist terms, allowlist words and number codes, applied on top of api/src/usernames/blocklist.ts.
CREATE TABLE moderation_terms (
  term TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('substring', 'token', 'allow', 'raw')),
  added_at INTEGER NOT NULL,
  PRIMARY KEY (term, kind)
);

-- The admin log names accounts by id (with the username and join number at the
-- time in its detail), never by email. A v1 entry that named an email now
-- names that account's id, or "deleted user" when the account is gone.
UPDATE audit SET target = COALESCE((SELECT u.id FROM users AS u WHERE u.email = audit.target), 'deleted user')
 WHERE target LIKE '%@%';

-- Usernames held back, in every spelling: kept only as hashes of the name's
-- skeletons (usernameSkeletons in api/src/usernames/check.ts), never the name.
-- A name an admin rename took away is held for good (until NULL) by its leet
-- skeleton and its letters alone, so that neither that account nor anyone
-- else picks it again with digits added or dropped; a deleted account's is
-- held for 30 days (until, in ms) by its leet skeleton, so that nobody can
-- take it at once and pass for that person.
CREATE TABLE held_usernames (
  skeleton_hash TEXT PRIMARY KEY,
  until INTEGER
);

-- Values the Worker keeps for itself. salt_secret makes the steady made-up salt
-- POST /v1/login/salt gives a username that has no account: random, made here
-- once, and unrelated to the admin's password.
CREATE TABLE settings (
  name TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings (name, value) VALUES ('salt_secret', lower(hex(randomblob(32))));
