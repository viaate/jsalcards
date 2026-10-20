# Live closings ingest: runbook

The live ingest reads the closings sources, resolves each row to schools and days, and
publishes `live/closings.json` through a publish gate. Code: `pipeline/snowlight/live/`.
Settings: `pipeline/config/live.yaml`. The workflows that run it (S8-E) are not here yet.

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
- `unmatched.json`: names the matcher did not place. Only ever in a private store, never in the Actions cache.

Private output (`out/internal/live/`):

- `health.json`: counts only. A check between passes, or while a pass reads, that raised the alert or published a blank adds `check` (its time, the verdict, `alert` and the blank's report) beside the last pass's health. `withheld.source_unknown` counts statuses held back because a source's say was unknown. `gate.counts.redacted` counts statuses the hold darkened that only gone rows light. A failed write of this file is logged and leaves the pass's exit as it was.
- `provenance.jsonl`: the last publish's sources, row keys and times.

No raw listing text is written anywhere. Log lines go to stderr as `time level logger: message`. An error shows only its type, never its message or a traceback, because a page's words could be in either.

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
