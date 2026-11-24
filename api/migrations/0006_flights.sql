-- Flights trips, alerts and Google (flights spec D12, D18, D19; docs/flights-trips.md). Additive
-- and safe on the live database: new tables only, nothing in the Schools tables changes. Nothing
-- here sends anything: the alerts sender runs in GitHub Actions (pipeline/snowlight/notify
-- flights) and reads these tables over the Cloudflare API, as the Schools sender does.

-- A saved flight: its airline and number, the airport it leaves from and the one it lands at,
-- the local day it leaves (the departure airport's clock) and its usual times on each end's own
-- clock (flights spec D11). The ticket type changes the advice only (D19): basic, regular,
-- premium or unsure (Not sure, also the skip). ticket_asked: the one tap was shown. need_by: an
-- optional "I need to be there by" as the arrival airport's local date and time. source: typed,
-- calendar or gmail (what the person confirmed; never any email or event text).
CREATE TABLE trips (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  carrier TEXT NOT NULL,
  number INTEGER NOT NULL CHECK (number BETWEEN 1 AND 9999),
  from_airport TEXT NOT NULL,
  to_airport TEXT NOT NULL,
  day TEXT NOT NULL,
  leaves INTEGER NOT NULL CHECK (leaves BETWEEN 0 AND 1439),
  lands INTEGER NOT NULL CHECK (lands BETWEEN 0 AND 1439),
  ticket TEXT NOT NULL DEFAULT 'unsure' CHECK (ticket IN ('basic', 'regular', 'premium', 'unsure')),
  ticket_asked INTEGER NOT NULL DEFAULT 0,
  need_by TEXT,
  source TEXT NOT NULL DEFAULT 'typed' CHECK (source IN ('typed', 'calendar', 'gmail')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (user_id, carrier, number, from_airport, day)
);

CREATE INDEX trips_user ON trips (user_id, day, leaves);

CREATE INDEX trips_day ON trips (day);

-- An account's Flights alert choices. No row means the defaults: alerts on at 30% (30, 50 or 70
-- like Schools), the evening check the night before on at 20:00 in the departure airport's own
-- time, and email on (sent only while Google is connected). Quiet hours are the account's
-- Schools ones (notify_settings), in the departure airport's time.
CREATE TABLE flights_notify (
  user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  alerts INTEGER NOT NULL DEFAULT 1,
  threshold INTEGER NOT NULL DEFAULT 30 CHECK (threshold IN (30, 50, 70)),
  night_before INTEGER NOT NULL DEFAULT 1,
  night_time TEXT NOT NULL DEFAULT '20:00',
  email INTEGER NOT NULL DEFAULT 1,
  updated_at INTEGER NOT NULL
);

-- What was sent for one trip: one row per change (kind and value), so each change is said once.
-- chance (the threshold crossed), rise (the level or chance it rose to), fall (it went down
-- after a chance alert), faa (airport, program and end), safer (a plan named, with its chance),
-- waiver (the waiver), night (the day). The sender keeps a trip's rows until the trip goes.
CREATE TABLE flights_sent (
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  trip_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('chance', 'rise', 'fall', 'faa', 'safer', 'waiver', 'night')),
  value TEXT NOT NULL,
  sent_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, trip_id, kind, value)
);

-- A connected Google account (dormant until the Worker has GOOGLE_CLIENT_ID and
-- GOOGLE_CLIENT_SECRET): its email address (where alerts are emailed, from itself), the scopes
-- granted, and the refresh token encrypted with AES-GCM under a key derived from the client
-- secret (api/src/google.ts). Deleted on disconnect and with the account.
CREATE TABLE google_links (
  user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  google_email TEXT NOT NULL,
  -- The Google account itself (the ID token's sub): its email can change or be given to another.
  google_sub TEXT,
  scopes TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  connected_at INTEGER NOT NULL,
  used_at INTEGER
);

-- A connect in progress: the SHA-256 of its state, the account that started it, its PKCE
-- verifier and the site address it returns to (its origin and base path). Used once, within 10 minutes.
CREATE TABLE google_states (
  state_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  verifier TEXT NOT NULL,
  return_origin TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX google_states_user ON google_states (user_id);
