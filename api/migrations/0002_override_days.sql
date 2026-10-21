-- Manual statuses list their days: one or two school-local dates (a JSON array of
-- "YYYY-MM-DD", ascending) and the IANA time zone they are in. expires_at stays:
-- the end of the last listed day. Additive and safe on the live database.
-- An override set before this migration had only expires_at, which the admin view
-- set to 23:59 on the school's local day; every US zone is 4 to 10 hours behind
-- UTC, so that day is the UTC date of expires_at less 12 hours. It keeps that one
-- day and no zone (the Worker then holds it until expires_at, as before).

ALTER TABLE overrides ADD COLUMN days TEXT;
ALTER TABLE overrides ADD COLUMN time_zone TEXT;
UPDATE overrides SET days = json_array(date(expires_at / 1000 - 43200, 'unixepoch')) WHERE days IS NULL;
