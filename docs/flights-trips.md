# Flights trips, Google, alerts and email

Flights spec FL-3 (D12, D18, D19, D20 W8). One account serves Schools and Flights.

## What a person gets

- **My trips** (Flights menu, `?mode=flights&page=trips`): saved flights by date, the next one
  big, later ones below, past ones folded away (kept 14 days after their day). Each shows its
  risk in the chance words from the live file, gray when the file is old. A trip opens on its
  flight (`&trip=<id>`), with its arc on the map.
- **Save trip** on a flight: the flight number and date; the route and times come from the usual
  flights (D11). A number that makes more than one stop that day asks which leg, one tap. Right
  after saving, one tap asks the ticket type (Basic economy, Regular economy, Premium or first,
  Not sure; Skip is Not sure), changeable later on the trip. Optional "I need to be there by".
- **Backup plans** when the flight is at some or high risk: other flights on the same airline
  that day and the day before, other airlines, covered airports within 120 miles at either end
  (straight line, "about N miles away"), and one stop through a hub with a 1 to 4 hour layover.
  Ranked by a rough chance of getting there with no cancel and no 45+ minute delay: each leg's
  shown cancel and delay percents multiplied across legs, never 100%. The plans 10 points safer
  than the trip come first, the same airline and route first among them (D11), then other
  airlines, nearby airports and one stop, each by chance; the page and the alerts use the same
  order (`backup.ts` rankPlans, `flights_rules.py` rank_key). A need-by time drops plans
  that land later, and a plan is offered only when it leaves at least 2 hours from now (3 from a
  nearby airport): time to change the ticket and get there. With them, every time: the advice for the ticket type with the airline's waiver
  state (W8) and the money words. Never a seat, a fare or a booking.
- **Alerts** (Settings, Notifications, Flights): when the shown cancel or 45+ minute delay chance
  reaches the threshold (30, 50 or 70%, default 30); after a chance or rise alert, when the risk
  rises a full step, or 20 more points at the threshold (an evening check alone never starts a
  rise); once when it falls back under the threshold by 20 points (a new
  crossing after that is said again); when the FAA holds flights at either end (ground stop,
  ground delay, closed; today, read under 30 minutes ago; once per end time the FAA gives); when
  a plan 10 points safer than any plan already named appears; when the airline posts a waiver for
  the trip; and an evening check the night before (default on, 8 PM at the departure airport;
  when that time is in quiet hours, in the hour before they start; with no current live file,
  it says it could not check; with a current one that has no forecast for the trip, it says there
  is none yet). Each change is said once (`flights_sent`); a chance, rise or fall alert sent in
  the evening window, or in the hour before it, stands for the evening check only when it said
  the same round, level and top chance the evening check would say now. Every alert but the
  FAA's waits out the account's quiet hours. Each push says when the trip leaves and the
  flight, the chance, why (and at which airport), the top one or two plans with the money words,
  "Leave a day early" for a plan the day before, and the time it was checked. An FAA push is
  held by the push service no longer than the FAA read is trusted (30 minutes from the read) or
  the program's end, and an FAA end at the other airport names its clock; a push that arrives
  late leads with when it was checked (for the FAA, when it was read), and names no backup that
  leaves within 2 hours (3 from a nearby airport), the sender's own lead (`BACKUP_LEAD_S`). So
  that a late one still has a later flight to name, each alert carries up to six safer plans best
  first (`ALERT_CARRIED`) and a `more` flag when the sender found others past them; it names the
  top live one (push) or two (email). It says "We see no safer usual flight you can still catch."
  only when that is so: the sender found none, or every plan it found has left and it found no
  more. When the carried ones have left but it found more, it says "The safer flights in this
  alert have left. Open the trip to look for others." A safer push whose new flight (the best of
  the one or two it names, the one that made it) has left reads as the trip's chance. The risk
  pushes of a trip (chance, rise, fall, safer, evening check) share one notification and one push
  topic (`fl-risk-<trip>`), so the push service keeps only the newest for a phone that was
  offline, and the worker never lets one checked earlier replace a newer one in the tray (it
  shows the newer one again without a sound). Each one that replaces another rings again
  (`renotify`), as FAA and waiver pushes do (each on its own topic); a safer push whose new
  flight has left says nothing new and updates the tray without a sound. Web push through the
  existing push path, and email when Google is connected.

## Google (dormant until configured)

Set up by the owner (the checklist is in the lead's build notes): the repository variable
`GOOGLE_CLIENT_ID` and the secret `GOOGLE_CLIENT_SECRET`, which `api.yml` hands to the Worker.
Until both exist `GET /v1/google/config` says not configured, every other Google route answers
404 `google_off`, and the page shows no Google option.

- **Connect**: OAuth 2.0 authorization code with PKCE (S256) through the Worker, scopes
  `openid email calendar.readonly gmail.send`. The state is kept only as its SHA-256, for 10
  minutes, used once, and only by the account that started it. Google returns to the site's
  `/google.html`, which hands the code to the signed-in trips page, which sends it to
  `POST /v1/me/google/finish` with its session. The refresh token is kept encrypted (AES-GCM, a
  key from HKDF over the client secret, the account id as additional data). Rotating the client
  secret disconnects everyone; they connect again. The connect never folds in scopes granted
  before (no `include_granted_scopes`); a token answer, or a later refresh, that holds any scope
  outside these four (above all `gmail.readonly`) is revoked at Google and nothing of it is kept;
  Google's revoke ends that Google account's whole grant, so every link to it (this account's on
  a reconnect, or another Snowlight account's) is deleted with it and reads as disconnected.
  Connecting a different Google account revokes the old account's grant first. A Google account
  is known by its ID token's `sub` (`google_links.google_sub`; by its email only for a row with
  none), so a renamed address is the same account and a reused one is not.
- **Calendar**: `POST /v1/me/google/calendar` returns the next 60 days of events that read like a
  flight, cut short; the page matches each to the usual flights and the person confirms it.
  Nothing from the calendar is kept.
- **Email**: the Actions sender calls `POST /v1/internal/flights/mail` with a fresh key whose
  SHA-256 it wrote in `settings` (`flights_mail_key`, 15 minutes); the Worker words the alert
  (web/src/copy-trips.ts) and sends it from the person's own Gmail to themselves.
- **Disconnect** and account deletion revoke the token at Google and delete it; while another
  Snowlight account holds a link to the same Google account, the token is only deleted here (a
  revoke would end that link too).
- `GET /v1/me/google` says when the link was made (`since`); My trips and Settings show the day,
  since a Google client in Testing mode ends its tokens after 7 days. A link over 6 days old that
  has not been used in 6 hours is checked with Google when the page reads it; a token Google has
  ended deletes the link, so the page reads disconnected. Only that token's link: a reconnect
  that finished meanwhile keeps its new link and any waiting connect, and the answer is read from
  the row after Google answers. Back from Google's consent screen, the page sends only the finish
  and takes its answer as the state (an older read is never shown).
- **Gmail demo** (D19 GOOGLE RULE): only with the variable `GMAIL_READ_DEMO=1` and the demo's
  own client id `GMAIL_DEMO_CLIENT_ID` (a second OAuth client in its own Google Cloud project,
  never Connect Google's), a separate "Find
  my flights in Gmail" button asks for `gmail.readonly` on its own with a short-lived browser
  token (Google Identity Services, client id only), reads airline confirmation emails from the
  last 6 months on the device (schema.org FlightReservation, then a small checked table of fare
  words), and sends nothing from them anywhere. Off by default; never the public product. It
  asks with `include_granted_scopes: false` and always revokes its grant when it is done: on its
  own client that revoke can never end a Connect Google link (Google's revoke ends every scope a
  person gave one client), and no Gmail read grant is left standing. While a read runs its token
  sits in the tab's session storage (a list, one per read running, each dropping only its own),
  so a read a reload cut short is revoked on the next load; a
  tab closed mid-read leaves a grant the person removes in their Google account.

## How it works

- API (`api/src/trips.ts`, `api/src/google.ts`, migration `0006_flights.sql`): trips, Flights
  choices, Google links and states, and the sent log. Every route is a few D1 statements, well
  inside the free plan's 10 ms of CPU.
- Web (`web/src/modes/flights/`): `trips-host.svelte.ts`, `TripsPanel.svelte`,
  `TripTools.svelte`, `BackupPlans.svelte`, `backup.ts`, `ticket.ts`, `found.ts`, `gmail.ts`
  (lazy), `gmail-read.ts` (lazy); the words in `web/src/copy-trips.ts`.
- Sender (`pipeline/snowlight/notify/flights.py`, `flights_rules.py`): the last step of each
  `flights-live.yml` pass, `snowlight notify flights`. It reads the published files through
  GitHub's API, works each trip's alerts as the page works its numbers, and fails dark.
