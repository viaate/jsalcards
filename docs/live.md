# Live closings ingest: runbook

The live ingest reads the closings sources, resolves each row to schools and days, and
publishes `live/closings.json` through a publish gate. Code: `pipeline/snowlight/live/`.
Settings: `pipeline/config/live.yaml`. The list readers' workflow (S8-E) is not here yet;
`.github/workflows/live-ingest.yml` publishes the admin's manual statuses for now (see
[Manual statuses](#manual-statuses-the-admin)).

## Commands

All from `pipeline/` (`uv run snowlight live ...`).

| Command | What it does |
|---|---|
| `live once [--only ID ...]` | One pass: read, resolve, merge, gate, publish. `--only` reads only those sources, so the health check counts every other due source as unread and refuses: it is for looking, not for publishing. |
| `live run --until +330m` | Passes on a 5-minute grid. The directory check runs every 60 s between passes and while a pass reads. A pass that fails is logged and the next one runs. A new deployed stamp for the same directory starts one extra pass at once, never more than one per stamp, and none while the hold is set or publishing is off. The run stops early only when the deployed directory has other content (its successor builds the new one). |
| `live blank` | The emergency stop for a wrong light. Sets the hold and blanks every public closings file. |
| `live release` | Clears the hold. The next pass publishes again. |
| `live check --url URL --max-age 15m` | The watchdog. Checks that the public file is fresh, is not stamped ahead of the clock, and carries the deployed directory's stamp. |
| `live state pull` / `live state push` | Restore or keep the private state. |
| `live overrides --api ROOT` | One pass of the admin's manual statuses: read the active overrides from the API, check them against the deployed directory, gate and publish. Stops, writing nothing, when the overrides light nothing and the public files show no status. |
| `live sweep --cache-dir DIR --state DIR --log FILE --report FILE` | One measured pass of the pool over every source the ingest polls (or `--only` ids), resolving and publishing nothing. Appends each request to the log (its pace key, its floor and when it held the key) and writes a report: the sweep's time, when each source finished, the outcomes, the requests sent against those paced, the pacing violations and the robots.txt requests per origin (every attempt, counted from the log). Exits `1` on any violation or unpaced request. Ids, hosts, codes and times only. |
| `live overrides --none` | The same pass with no override: takes every manual status down (`live-ingest.yml` runs it when no API is left to read). |

Exit codes:

- `0`: published, or held on purpose (nothing changed, publishing off).
- `3`: the gate refused and nothing was uploaded. `check` also exits `3` when the file is stale, missing (HTTP 404), more than 60 s ahead of the clock, or on another stamp than the deployed edition.
- `1`: an error. Nothing is known to be published. This includes a state push that failed after a pass (whatever the pass's own exit), and a `check` that could not read the file or the deployed edition.

`live run` exits with the worst exit of all its passes: `1` over `3` over `0`. One failed pass in a 330-minute run makes the run exit `1`, even when every later pass published. A blank made by the check between passes counts like a pass: `3` when it went up, `1` when it failed (even if a later try landed). A run that ends while a blank is still failing exits `1`, and so does a run that stops for its successor after a state push failed.

Unchanged files still go up on every pass, as the heartbeat. It is measured on the passes' start times (the 5-minute grid), not on when their reads ended, so a pass whose reads finish sooner than the last one's still uploads. Only a pass that starts less than 4 min after the last uploading one skips an unchanged upload.

A refusal is never retried by hand: the next pass decides again.

## The emergency stop

`live blank` works the same whatever `LIVE_PUBLISH` says.

1. It writes `live/hold.json` (`held: true`) in `v1/` and `v1-shadow/`, first and in a write of its own, so the hold stands whatever happens next.
2. In each of those with a closings file, it publishes an empty closings and opens file under the file's own stamp.
3. It empties every day timeline the day index lists, and empties the index.
4. It reads and writes no private state, so it works while the ingest is broken.

Run `live check` a minute after a blank to see that the public file is empty.

While the hold is set:

- Every pass is refused (`held`) and nothing lights. That includes a loop that was already running and a new run.
- The first pass that reads the hold records in the change log that the statuses went dark at the moment of the blank. Those lines carry `"by": "hold"`.
- If a file still shows statuses, the pass blanks it again.
- A hold file that does not read counts as set.
- A pass that was already running when the blank landed cannot undo it. Every upload is refused when the hold is set: on GitHub the hold is read in the very commit the upload builds on, and on a folder or bucket just before writing. The hold is also read again right after every upload, and a file lit over a blank is blanked at once.

The emergency stop is not history. Which status was false is not recorded, so every status the hold darkened is left out of the day timelines from the moment it was lit. The replay never shows it.

`live release` writes `held: false` and keeps the time the hold began. A run that never saw the hold still records the dark minutes. After a release:

- The next pass publishes again, and every day timeline is published again.
- A status the hold darkened lights again only while a source still lists the row that lights it. Merge keeps a row through its day after the source takes it down, but not for these school-days: they stay dark until the day ends.
- A status a source still lists lights again, and the timeline shows it from the release on.

So to remove one false status for good, fix its cause first: the source takes the row down, or a fix to the code, the matcher or the registry stops it from lighting. Then release. If the cause cannot be fixed, keep the hold until the day ends.

Exit `0` means every prefix is held and every file is blanked. Exit `1` means the host could not be written, so try again. Exit `3` means the hold is set but a file was not blanked, because its blank would be stamped more than 60 s ahead of the host's clock. Fix the clock. The running ingest blanks that file as soon as the clock allows.

## Switches and secrets (environment only)

| Name | Meaning |
|---|---|
| `LIVE_PUBLISH` | `shadow` (default): write under `v1-shadow/`. `on`: write under `v1/`, the root the site reads. `off`: run the gate, write nothing. `off` is not an emergency stop: lights already published stay until their day ends. Use `live blank`. |
| `LIVE_HOST_TOKEN` | Writes the Pages repository (host `github`). Contents write on that repository only. |
| `LIVE_R2_ACCESS_KEY_ID`, `LIVE_R2_SECRET_ACCESS_KEY` | The bucket keys (host `r2`, or state `bucket`). |
| `GITHUB_TOKEN` | Reads the site's deployments for the directory check, in the ingest and in `check` (`deployments: read`, `actions: read`, `contents: read`). |

Host `github` needs the Pages repository to serve its whole tree: today
`viaate/snowlight-live` deploys only the S8-A probe, so a committed file is never served.
The workflow that serves the repository root, and the one-time shadow check, are in
`docs/predict.md` (What the owner sets up once, step 4).

## Reading the sources

A pass reads the sources due through a concurrent pool (`snowlight/live/pool.py`) on the cadence (`snowlight/live/cadence.py`).

- **Politeness.** One request in flight per host and starts at least `max(5 s, Crawl-delay)` apart, across all 24 workers. Each of Gray's list files, path-style on `s3.amazonaws.com`, is paced under its own bucket (owner decision Q3), the same as its documented per-station address. robots.txt is read at most once per origin a day (kept in `robots.json`), and is still a record, never a gate. A robots.txt that fails, or that asks for a `Retry-After` the pass will not wait for, is kept as unreachable for the day; that wait holds every source on the origin as `deferred` until it ends, and a stopped source starts no further request. A request must answer by its source's deadline (plus a second).
- **Deadlines.** A source gets 60 s, attempts and follows included (two attempts); nothing starts after 240 s into the pass. A source cut off is `late` and due next pass. A server's `Retry-After` is honoured: the source is `deferred` until that wait has passed, and no other source waits for it. A 403 or 401 blocks the source for 24 hours. A refusal is never worked around.
- **Cadence.** Every 5 minutes from 18:00 to 23:00 and from 04:00 to 09:00 in the station's own zone (the zone most of its counties are in; real zone rules, so the windows follow daylight saving time), and while an NWS alert of an allowlisted type covers one of its counties (the alerts are read every 5 minutes; a failed read keeps the last set for 2 hours). Otherwise every 30 minutes, or the registry's `poll_minutes` when longer. A source the pass did not get to (`late`) is due at the next pass; a failed read (`error`, such as a 429 or 5xx without `Retry-After`) keeps its cadence, so outside the windows and alerts it waits its calm interval. A source is never read again in the same 5-minute grid slot, nor less than 4 minutes after its last pass.
- **Health share.** G12b counts the sources due in the passes of the last 15 minutes, and every source blocked now.

## Where files go

Public, on the live host. These hold school indexes, days, codes and times only.

- `v1/live/closings.json`.
- `v1/live/opens.json`: explicit "school is open" statements, for the prediction model.
- `v1/live/days/<day>.json`: when each school's status changed that day, for the timeline.
- `v1/live/days/index.json`: lists only the days whose file carries the current stamp, and is written with every upload, even when it lists no day. A finished day is published again from the change log after a restamp or a directory change.
- `v1/live/hold.json`: the hold, a flag and two times. The web never reads it.

The files go up in this order: closings, opens, day timelines, index.

Private state (`out/internal/live/state/`, kept by the state store):

- `ledger.sqlite`.
- `publish.json`: the last stamp, the gate's memory, and which day file went up under which stamp and prefix.
- `changes/<day>.jsonl`: every change the map showed, with its source and row key.
  - Each file is rewritten whole and atomically.
  - A torn line from an older copy is skipped and counted.
  - Nothing is pruned until `changes/durable.json` (`{"through": "YYYY-MM-DD"}`) says a durable copy holds those days. That copy is the push to the private data repository (spec 19), and it is not built yet.
  - Until it lands, the Actions cache store is the only copy of the replay history. A cache eviction loses the private log, so land the durable push before relying on `cache`.
  - A successor that lost its state takes each day it has no log for from the public day file under the current stamp (lines with `"by": "seed"`), but only when the file's `content_sha256` is its own directory content: two contents can share one stamp (risk R6), and a file built on the other one indexes other schools. Such a file is skipped with a warning in the log. The public timeline then goes on from where it was, rather than starting again at the successor's first publish. The private details of those changes (source and row key) are lost.
- `robots.json`: robots.txt verdicts per origin (the parsed rules, the read time and the file's digest), kept 24 hours.
- `cadence.json`: per source, the start of the pass that last read it, its outcome, and the earliest next read of a deferred or blocked source.
- `morning/<UTC day>.json`: the morning record the prediction model learns from (docs/predict.md, "The model learns on its own"). Per 30-minute UTC slot: the prefixes a pass was shown under, each whole read of a shown pass between 09:00 and 21:00 UTC (rows, rows placed, rows read as no status), the states a pass withheld whole, and the districts its rows named with the days and the status kinds (`?` when a dissenting, unsure or unread row named it). Counts, ids and codes only. Rewritten whole and atomically by every pass; kept 10 days. A file that does not read is marked damaged and no day of it is learned from.
- `unmatched.json`: names the matcher did not place. Only ever in a private store, never in the Actions cache.

A workflow that runs the live loop with the `cache` store saves `pipeline/out/internal/live/store` under a key starting `live-state-` (`CACHE_KEY_PREFIX` in `snowlight/live/state.py`): the predict workflow's learning step restores the newest such key, read only.

Private output (`out/internal/live/`):

- `health.json`: counts only. A check between passes, or while a pass reads, that raised the alert or published a blank adds `check` (its time, the verdict, `alert` and the blank's report) beside the last pass's health. `withheld.source_unknown` counts statuses held back because a source's say was unknown. `gate.counts.redacted` counts statuses the hold darkened that only gone rows light. A failed write of this file is logged and leaves the pass's exit as it was.
- `provenance.jsonl`: the last publish's sources, row keys and times.

No raw listing text is written anywhere. Log lines go to stderr as `time level logger: message`. An error shows only its type, never its message or a traceback, because a page's words could be in either.

## Manual statuses (the admin)

The admin sets a status by hand in the admin view (`?admin`): Closed, Delayed (its minutes),
Early dismissal (its time) or Open, for a district (every one of its schools) or one school,
until an expiry (the end of that school's local day today or tomorrow). The API keeps it and serves the active ones, without the note or who set it, at
`GET {API}/v1/overrides`. Code: `pipeline/snowlight/live/overrides.py`.

`live-ingest.yml` runs every 5 minutes: the owner's Cloudflare timer dispatches it when no run is
queued or running. Its first job holds no secret beyond the Cloudflare ones and makes no
deployment:

- **No API root**: no repository variable `SNOWLIGHT_API_ROOT`, and not both `CLOUDFLARE_API_TOKEN`
  and `CLOUDFLARE_ACCOUNT_ID` (from which it reads the account's `workers.dev` subdomain and
  takes `https://snowlight-api.<subdomain>.workers.dev/`), or an account with no subdomain.
  One notice; the run succeeds.
- **The API is not deployed**: with the Cloudflare secrets, the account's list of Workers has no
  `snowlight-api` (what `workers.dev` answers for a Worker that is not there is never relied on);
  with `SNOWLIGHT_API_ROOT`, `v1/overrides` answers 404 twice, 10 s apart. One notice; the run
  succeeds.
- **`SNOWLIGHT_API_ROOT` is not an https URL** (http, a query or fragment, a space): one
  warning, so the owner sees it; the run succeeds and reads no API.
- **No API left, but statuses on the map**: in either case above, while the public
  `v1/live/closings.json` or `v1/live/opens.json` still shows a status (a deleted or renamed
  Worker, a removed variable or secret), one warning, and the `publish` job takes them all down
  (`live overrides --none`). A public file that cannot be read is never taken down on a guess:
  one notice, and the next run reads it again.
- **The Cloudflare lookup fails** (no answer, an HTTP error such as a token without the Workers
  read permission, or an answer that is not a subdomain or not a list of Workers): one notice
  naming the likely cause;
  the run succeeds and nothing changes. While it lasts, statuses already on the map are neither
  republished nor taken down: the page stops calling the file live 20 minutes after its last
  update, and the statuses drop out of the file at the next run that reads the API.
- **Nothing to do**: no active override, and the public closings and opens files are missing or
  show nothing (read through GitHub's API, never the CDN, whose copy can be 10 minutes old).
  One line; the run succeeds.
- **The API does not answer, or answers with something that is not a list of overrides** (an
  HTTP error, not JSON): one error line, the run fails and publishes nothing. The public files
  stay as they were. No answer, a 404 or a 5xx is asked again once, 10 s later, so one bad
  answer neither fails the run nor takes the map down.

Otherwise the `publish` job (environment `live`, `SNOWLIGHT_LIVE_TOKEN`; without it, one notice)
runs `snowlight live overrides`:

1. The API's answer is read strictly: a field missing, unknown or out of range anywhere refuses
   the whole answer (exit 1, nothing published).
2. Every id is checked against the deployed directory, read as the predictions pass reads it
   (S8-0's reader, never a plain GET of the CDN): a school id must be in the deployed
   `meta.json`, a district id in its district list, and a district covers each school
   `points.bin` places in it. An id the deployed directory does not hold lights nothing.
3. An override lists its days: one or two school-local dates, the ones the admin picked in the
   admin view (Today, Tomorrow, or Today and tomorrow, in the school's own time zone). The
   API keeps one override per district or school: every save replaces it, days, status, delay
   and time together, and the API serves only the listed days that have not ended. The pass
   lights exactly the listed days that are the school's today or tomorrow, with the
   override's current status, delay and time, and nothing else: nothing is guessed from when
   it was set or kept from what the map showed. Today and tomorrow are taken in the school's
   district's time zone from the committed model (`pipeline/data/predict/model.json.gz`, the
   zones the predictions file gives the page); a school without a district (a private school)
   takes the zone of the nearest school that has one. The admin view works its days out in the
   same zone (the predictions file's zone for the district, read only from a file for the
   deployed directory, and the same nearest school for a school without a district) and
   refuses to set a status while it cannot. An override whose days it named in another zone
   than the pass's lights nothing (`zone_differs`): its dates may not be the school's.
   - A day the override no longer lists (saved again with other days, or deleted) leaves the
     map at the next run. An Open takes its days down (no row; an open statement).
   - A saved change shows at the next run on every listed day: an early dismissal moved from
     1:00 PM to 12:30 PM after noon shows 12:30 PM.
   - "Posted" is the time the admin set that day's status. A day shown with the same status,
     delay and time as manual status keeps the time it was first posted (a save that changes
     nothing on that day, such as a new note, does not move it); any change on that day posts
     it anew. A public file under another directory stamp gives no times, and a public file
     that cannot be read fails the run with nothing published.
   - An override past its expiry (the end of its last day in the zone the admin view used)
     lights nothing.
4. A school's own override beats its district's; among equals the one set last wins. In the
   merge (`merge.py`, rule 7, `with_overrides`) the admin outranks every list read: an admin
   status replaces the lists' status for that school and day, and an admin Open removes it and
   stands as an open statement in `opens.json`. When S8-E brings the list readers, their pass
   must take the overrides through `with_overrides` in the same publisher (one memory per
   public file), and `live overrides` stops running on its own.
5. The publisher is the lists' (`LivePublisher`): stamped with the deployed directory, refused
   while the hold is set (`live blank` darkens manual statuses too), uploaded when the statuses
   changed and every 10 minutes while any show (the live repository's Pages site is built
   from its branch, and GitHub builds a branch about 10 times an hour at most; a 5-minute
   heartbeat beside predict.yml's commits would hold builds back, a take-down with them). Each row is a status with no weather reason,
   posted at the time the admin set it, and marked in the day's `manual` column (row positions);
   the school panel leads its note with "Confirmed by our team" and never names a list or a
   station. A closings file written before the column existed reads as having no manual rows.
   The private provenance line says `source_type` `admin`. Overrides that
   light nothing (ids not in the directory, days after tomorrow) write nothing while the public
   files show nothing, so they cause no heartbeat commits.

`LIVE_PUBLISH` for this job comes from the repository variable `LIVE_OVERRIDES_PUBLISH`, `on`
when unset: manual statuses go straight to the map. `shadow` and `off` write nothing under
`v1/`, so they also take nothing down there: statuses already on the map stay until their day
ends (the page stops calling the file live 20 minutes after its last update). To stop manual
statuses, take them down first while the variable is still `on` (delete the overrides in the
admin view and wait for the next run, or `live blank` for every status at once), then set it.
While it is `shadow` or `off` and `v1/` still shows statuses, every run prints one warning.

After the `publish` job, the `notify` job sends status notifications from the public files
(docs/notify.md): one line and nothing else while no browser gets notifications, and nothing
from a file older than 20 minutes or for another directory. A status that only leaves the file
(a held source, a blank) is never sent as lifted; only an open statement lifts one. The job
never turns the run red.

Both `predict.yml` and `live-ingest.yml` commit to `viaate/snowlight-live`. A commit that loses
the race (the other moved the branch first) is built again on the new head, keeping the other's
files, up to 3 times (`GitHubPublisher.attempts`); only then does the run fail.

From setting a status to the map: up to 5 minutes for the next dispatch, about 1 to 2 minutes
for the run with its setup, about 20 to 40 s for the live host's Pages deploy, then the page's
next read (once a minute): about 9 minutes at most.

## When the deployed directory changes

The check compares the deployed edition with this build's own. It runs at start, every 60 s between passes, every 60 s while a pass reads, and before each publish.

- **Other content:** each public file that carries the deployed stamp is blanked with its day timelines. The stamps checked are read back from the host, so this works after the private state is lost. When a public file cannot be read back, the blank runs under the deployed stamp anyway (it skips a file under another stamp). The pass is refused (`edition`), the alert is set, and the run stops so its successor can build the new directory. If the blank fails, or is refused because it would be stamped ahead of the host's clock, the run tries it again at every check, with no passes, for up to 10 min, then stops with exit `1`. After a blank, `--push` pushes the state at once, so the successor pulls the dark lines.
- **The same content under a new stamp:** one pass runs at once, so the new stamp is up within about a minute.
- **A new deployment in progress:** the deployment before it is still the one served, so the last good verdict stands and nothing goes dark. Every push to the site deploys, and a deploy is in progress for tens of seconds. Once it settles, the next check reads it.
- **The edition cannot be read:** the last good verdict stands for 30 min, then passes are refused and the alert is set. A new deployment that has settled and cannot be read gets no grace, because its content may have changed: every public file is blanked under its own stamp, the alert is set, and passes are refused until it reads.

The ingest reacts within one 60 s check of a deploy going live. The host's cache adds its own delay before visitors see the blank: GitHub Pages serves the live files with `max-age=600` (S8-A), so up to 10 more minutes there.

## The gate refused: what each reason means

| Reason | Meaning | What to do |
|---|---|---|
| `edition` | The deployed directory is not the one this build indexes into, or it cannot be read (see above). | Nothing by hand: the run waits, or stops for its successor. If it repeats, see `docs/deployed-edition.md`. |
| `held` | `live blank` set the hold. | `live release` once the cause is fixed. |
| `health` | Under 60% of the sources due (the active, pollable stations) read cleanly in the last 15 min, or the share is under half the previous pass's. A due source not read counts as not clean. | Look at `health.json` `reads`. A network or runner problem passes by itself. |
| `not_newer` | Another writer published a newer file, or the clock went back. | Make sure only one ingest runs. |
| `clock_ahead` | The box's clock is more than 60 s ahead of the host's. | Fix the clock (NTP). |
| `oversize` | The file is over 400 KB gzipped. | A breaker or a bad match is likely: look at `health.json` `published`. |
| `invalid` | The file does not validate. For example: a school index outside the directory, two rows for one school and day, or an open statement dated after the file. | A bug: keep the map as it is and report it. |
| `spike_hold` | More than 2,000 new school-days at once with few alerts. Held once, then published if the next pass shows the same. | Check a few new rows by hand. `live blank` if they are wrong. |

The pass report sets `alert` (S8-E opens an issue for it) when:

- two passes in a row are refused;
- the deployed directory has other content, or a settled new deployment cannot be read (a check between passes prints the same `ALERT` line and records it in `health.json`);
- the hold could not be read right after an upload: that prefix's files are blanked at once (a `live blank` may have landed during the upload) and the pass exits `1`;
- the deployed edition could not be read for more than 30 min;
- two passes in a row have a source whose say is unknown (below).

Some sources' say is unknown in a pass:

- a source whose read could not be taken into the ledger, or whose resolve failed;
- a source due for reading (active, on a platform whose terms permit polling) holding a row that was read but never resolved within the last 36 hours (a run cut off mid-pass).

Each such source holds back every status and open statement in its registry states until it is read again. The rest of the map publishes. A source not due (the registry no longer lists it, it has no endpoint, or its terms do not permit polling) is never read again, so its unresolved rows are left out and expire.
