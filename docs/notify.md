# Notifications

Signed-in people can get a notification on their phone or computer about the
schools they saved (up to 5): when a school closes, starts late, goes remote or
lets out early, when that changes or the school says it is open, when tomorrow's chance of no
school gets high, and, if they want it, an evening check. It is free: web push
through each browser's own push service, sent from GitHub Actions in this
public repository, with the accounts database on Cloudflare's free plan. There
is no email.

## What a person gets

For each saved school, in Settings > Notifications:

| Kind | When | Default |
|---|---|---|
| **Closings, delays and early dismissals** | As soon as the map shows the school closed, delayed (with its time), remote or dismissing early on its today or tomorrow; again when that changes; and when the school says it is open after all. At most 4 a school-day. Sent at any hour. | On |
| **High chance of no school tomorrow** | When tomorrow's chance first reaches the person's threshold (30, 50 or 70%). At most once per school and day, plus once more only if it then rises 20 points or more. | On, at 50% |
| **Evening check** | At the person's chosen time (5 PM to 9:30 PM), tomorrow's chance for each saved school when it is 10% or more. | Off, 8 PM |
| **Quiet hours** | Hold chance and evening notifications (from and to, on the hour). Closings still come through. | 10 PM to 5 AM |

Every time is the school's own local time: its today and tomorrow, its evening,
its quiet hours. A held chance notification is sent after quiet hours if the
chance is still that high and it is still about tomorrow; an evening check is
sent only in the three hours after its time. A school-day that already shows a
status gets no chance notification.

A status is lifted only where the school has said it is open that day (an open
statement in `opens.json`, or the admin's **Open**): the person hears "Open
today". A status that only leaves the map is never said to be lifted, because
a school with no row has no status on file, which is not the same as open: a
source whose read failed is held off the map until it reads again
(docs/live.md), a blanked file shows no status at all, and a list can drop a
row. Nothing is sent then, and nothing again if the same status comes back.
A school-day gets at most 4 status notifications, so a status that flips
between passes cannot keep sending.

A chance or evening notification is kept by the push service for 45 minutes
only (a closing until the end of its day), so a phone that comes online later
never shows a chance that later passes may have moved.

The words are the site's (src/copy-notify.ts), written by the service worker
when the notification shows: the title is the school's name, the text is
"Closed today (Tue, Jan 12)", "Delayed start tomorrow (Wed, Jan 13) · 2-hour
delay · Starts at 10:00 AM", "Open today (Tue, Jan 12)", "Tomorrow (Wed, Jan
13): 62% chance of no school". A notification delivered late names
the date instead of "today". A tap opens the map on the school (`?school=ID`).

**Asking**: the browser's permission question only ever follows a press of
**Turn on notifications**, in Settings or in the small offer that shows once
after saving a school (**Not now** hides that offer on this device). Nothing
asks on page load.

**iPhone and iPad**: Safari shows web notifications only for a site added to
the home screen (iOS 16.4 or later). In Safari itself, Settings shows how to
add it instead of the switch (one row, its steps behind **How**); opened from
the home screen, the switch works.

**Private schools**: their own chances (docs/predict.md, private schools) are
used, so a saved private school gets chance and evening notifications like a
public one.

**Each browser's notifications last as long as the sign-in they were turned
on in.** Logging out on a device stops that device's. A password change stops
every other device's (this one carries over to the new sign-in); an admin
password reset or disable stops all of them; a sign-in that expires (30 days
without a visit) stops its device's until the same account signs in there
again. **Turn off everywhere** in Settings stops every device at once.
Deleting an account removes all of its subscriptions, settings and its sent log
at once. A disabled account gets nothing.

A browser remembers which account turned its notifications on. Signing in
there again as that account brings them back; signing in as another account
turns them off on that browser, and that account gets its own only by turning
on the **Notifications** switch in Settings. Nobody starts getting another person's
notifications, or moves them, without asking.

## How it works

- **The API** (`api/src/notify.ts`, migration `0004_notify.sql`, additive):
  `GET /v1/push/key` (the VAPID public key; 404 until there is one),
  `PUT /v1/me/push` and `DELETE /v1/me/push` (this browser's subscription,
  kept with the session it was turned on in; `{"all": true}` deletes every
  browser of the account; an account keeps its newest 5; only Chrome's, Edge's,
  Firefox's and Safari's push services are accepted), `GET` and
  `PATCH /v1/me/notify` (the settings, and how many browsers whose sign-in
  lasts get notifications). Tables: `push_subscriptions` (with the session's
  `token_hash` as `session_hash`, and the push service's refusals in a row),
  `notify_settings` (no row: the defaults) and `notify_sent` (what each account
  was sent for a school, kind and day). Ending sessions (`auth.ts`
  `endSession`, `revokeSessions`, the sweep) deletes their browsers' rows. The
  Worker only stores: nothing is sent from it, so every request stays far
  inside the free plan's 10 ms of CPU.
- **The key pair**: `api.yml` runs `api/scripts/vapid.mjs` after each deploy.
  The first time, it makes a P-256 key pair and stores both halves in the
  database's `settings` table (`vapid_public`, `vapid_private`) in one INSERT
  with the keys as bound parameters; after that it keeps them ("kept"). The
  private key is never printed, and never served: only the sender reads it.
- **Status notifications**: `live-ingest.yml`'s `notify` job, after the publish
  job, on every run whose check finished. Its first step counts the browsers
  that get notifications over the Cloudflare API; with none, no Cloudflare
  secrets, or the tables not there yet, it says one line and stops before any
  setup. Otherwise `snowlight notify status` reads the public
  `v1/live/closings.json` and `opens.json` through GitHub's API, refuses a file
  older than 20 minutes or for another directory (nothing is sent), maps each
  row to its school with the deployed directory, and sends what is new or
  changed, and what an open statement lifted. The job is `continue-on-error`
  and the command always exits 0 (a problem is one `::warning::` line with an
  error type or HTTP status), so a notification problem never turns the
  closings run red.
- **Chance and evening notifications**: `predict.yml`'s loop
  (`snowlight predict run`), after every pass whose file is the one the site
  shows (published, or unchanged from it), on the live root only. Passes run at
  :07 and :37 at least, so an 8 PM evening check goes out at 8:07 PM. A
  notification problem only warns; it never darkens a pass. Only the step that
  runs the loop gets the Cloudflare secrets, not the job's other steps.
- **Sending** (`pipeline/snowlight/notify/`): reads the accounts with a
  browser whose sign-in lasts (not disabled), their saved schools and
  settings, and the log, over
  the Cloudflare API with the existing `CLOUDFLARE_API_TOKEN` and
  `CLOUDFLARE_ACCOUNT_ID` secrets (no new secret); encrypts each message for
  each browser (RFC 8291, with `http_ece`), signs it with VAPID (RFC 8292), and
  posts it to the browser's push service. A push is logged once a browser took
  it, so one that failed everywhere is sent again next time; the log is written
  as the run goes (every 16 rows), only for accounts that still exist, so an
  account deleted mid-run never fails the others' rows, and a database error
  stops the run having lost at most 16 rows. A browser whose push service
  answers 404 or 410 is deleted; one that refuses (another 4xx, as after a
  VAPID key that no longer matches) 10 times in a row over more than a day is
  deleted too. A run stops sending after 4 minutes and leaves the rest for the
  next one. Errors name an HTTP status at
  most, never a key, an address or a name.
- **The page** (`web/src/account/notify.ts`, `web/src/ui/account/NotifySettings.svelte`,
  `NotifyOffer.svelte`): loads with the account controls, never in the first
  script. **The worker** (`web/src/pwa/push.ts`): bundled by
  `web/tools/push-worker.ts` into `sw-push.js`, which the generated service
  worker imports and precaches (so a new version updates the worker).

## What the owner does

Nothing new: the two Cloudflare secrets the accounts already use are all it
needs. After this lands, `api.yml` applies `0004_notify.sql` and makes the key
pair; from then on the **Notifications** section shows in Settings. To check:

1. **Actions** > **API**: the run's last step says `made` the first time
   (`kept` after).
2. `https://snowlight-api.<subdomain>.workers.dev/v1/push/key` answers with a key.
3. **Actions** > **live-ingest**: each run's `notify` job says
   `notify: no browser gets notifications: nothing to send` until someone turns
   them on, then `notify status: ... sent ...` lines with counts only.

To stop all notifications at once, remove the `vapid_private` row (Cloudflare
dashboard > D1 > snowlight-accounts > Console:
`DELETE FROM settings WHERE name = 'vapid_private'`): the sender then says
`no VAPID key pair yet` and sends nothing, and the next `api.yml` run makes no
new pair while `vapid_public` is there. Put the row back, or delete both and
run **API** again (every browser then has to turn notifications on again).

## Free plan use

Each live-ingest run with no browser costs two Cloudflare API calls (find the
database, count). Each predictions pass costs the same, plus a few reads when
someone gets notifications. Sent pushes cost the push services nothing. The
D1 free plan allows 5 million rows read and 100,000 written a day; a log row is
written per notification sent.
