-- Notifications v1 (docs/notify.md): web push subscriptions, each account's notification
-- settings, and what was sent, so that nothing is sent twice. Additive and safe on the live
-- database: new tables only. Nothing here sends anything: the sender runs in GitHub Actions
-- (pipeline/snowlight/notify) and reads these tables over the Cloudflare API.
--
-- The VAPID key pair the pushes are signed with lives in the settings table as two rows,
-- vapid_public and vapid_private, which api.yml makes once (api/scripts/vapid.mjs). The
-- Worker serves only the public one (GET /v1/push/key).

-- One row per browser that turned notifications on: its push service address, the keys
-- the browser made for it, and the sign-in it was turned on in (session_hash, the session's
-- token_hash). Up to 5 per account (the Worker drops the oldest). A browser gets
-- notifications only while that sign-in lasts: the sender joins live sessions, and ending
-- sessions (log out, a password change, an admin reset or disable) deletes their rows.
-- failures and failing_since count a push service's refusals in a row (400, 401, 403...);
-- the sender deletes a browser refused 10 times over more than a day.
CREATE TABLE push_subscriptions (
  endpoint TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  session_hash TEXT NOT NULL,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  failures INTEGER NOT NULL DEFAULT 0,
  failing_since INTEGER
);

CREATE INDEX push_subscriptions_user ON push_subscriptions (user_id, created_at);

CREATE INDEX push_subscriptions_session ON push_subscriptions (session_hash);

-- An account's choices. No row means the defaults: status and chance on at 50%, the night
-- before off at 20:00, quiet from 22:00 to 05:00 in each school's own time zone (quiet_from
-- equal to quiet_to means no quiet hours).
CREATE TABLE notify_settings (
  user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  status INTEGER NOT NULL DEFAULT 1,
  chance INTEGER NOT NULL DEFAULT 1,
  threshold INTEGER NOT NULL DEFAULT 50 CHECK (threshold IN (30, 50, 70)),
  night_before INTEGER NOT NULL DEFAULT 0,
  night_time TEXT NOT NULL DEFAULT '20:00',
  quiet_from TEXT NOT NULL DEFAULT '22:00',
  quiet_to TEXT NOT NULL DEFAULT '05:00',
  updated_at INTEGER NOT NULL
);

-- What was sent to an account for one school and one school-local day: kind status (value:
-- the status it said, or none once an open statement lifted it, then # and how many status
-- notifications that school-day had), chance and chance_rise (value: the
-- percent), night (value: the percent). The sender keeps a few days.
CREATE TABLE notify_sent (
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  school_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('status', 'chance', 'chance_rise', 'night')),
  day TEXT NOT NULL,
  value TEXT NOT NULL,
  sent_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, school_id, kind, day)
);

CREATE INDEX notify_sent_day ON notify_sent (day);
