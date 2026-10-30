# Live closings ingest: runbook

**To take every live status off the map at once:** Actions > **live-blank** > Run workflow,
action `blank`, prefix `every` (it works from GitHub mobile too, in about a minute). To let
the next pass publish again: the same with action `release` and the prefix you held. See
[The emergency stop](#the-emergency-stop).

The live ingest reads the closings sources, resolves each row to schools and days, and
publishes `live/closings.json` through a publish gate. Code: `pipeline/snowlight/live/`.
Settings: `pipeline/config/live.yaml`. Three workflows run it:

- `.github/workflows/live-read.yml`: the reader, one self-chained loop all day
  ([The reader](#the-reader)).
- `.github/workflows/live-ingest.yml`: on the owner's 5-minute timer it keeps the reader
  going (`reader` job), watches the served file (`watch` job), and publishes the admin's
  manual statuses to `v1/` while the reader is not the one writing it
  ([Manual statuses](#manual-statuses-the-admin)), then sends notifications.
- `.github/workflows/live-blank.yml`: the owner's stop. `live-drill.yml` holds the drills.

## The reader

`live-read.yml` runs `snowlight live run --until +320m --push-every 30` and then starts its
successor, so one run follows the other all day (about 5 a day), like `predict.yml`.

- **Passes.** One on every 5-minute grid mark. Each source's cadence decides what a pass
  reads (every 5 minutes inside its zone's 18:00-23:00 and 04:00-09:00 and during alerts, else
  every 30), so the heartbeat, the admin's statuses and alert-area reads never wait for a
  window. Every grid pass uploads, changed or not. The run's first pass (off the grid) skips
  an unchanged upload only when it starts under 4 minutes after the last uploading pass. The
  next due mark is the first grid mark after a pass's start, so a pass that overran runs the
  missed mark at once.
- **A successor's first reads.** A process holds a source's statuses only once it has read
  the source itself, so a run first reads every source whose last good read held rows, as
  soon as the politeness floor allows (another grid slot, 4 minutes on), whatever its
  cadence. The run's first pass is the next grid mark when its predecessor read one of them
  in the current slot, and also when there is none to read now and the predecessor passed in
  the current slot (most of the off-season: a pass then would find almost nothing due, count
  a share near 0 and be refused). A handoff is so one slot, as before: the last upload at
  about G+1 min, the successor ready at about G+2.5, its first pass at G+5 and its upload
  about a minute later. The gap between uploads is unchanged by design (about 5-6 minutes);
  what changed is that the successor's first pass is no longer refused and no status goes
  dark at the handoff. A source a server's wait or block holds past the next mark is not
  waited for, nor read early when it is free. A source whose last read failed (`error`,
  `partial`) is not read early either: it keeps its cadence, so a throttled host is never
  asked more often than the owner's cadence allows, and its statuses, which the run before
  still held under G13, are dark in the successor (never shown stale) until its next good
  read, at most 30 minutes (5 in a window or an alert). So is a source whose first read in
  the successor fails. A first read cut off (`late`) is due at the next pass. (Until Oct 30 a successor read a holding
  source only on its own cadence, so a half-hourly source's statuses were dark for up to 25
  minutes after a handoff, and its first pass at G+2 read nothing and was refused for
  health.)
- **The end.** A run ends right after its last grid pass that starts before +320 minutes,
  and before its job's start + 330 minutes (the 345-minute job timeout less 15 for that last
  pass at its 4.5-minute cut and its publish, the successor's dispatch, the end push at its
  bound and the other end steps), so a slow set-up (checkout, uv and its sync are bounded at
  15 minutes each against the 2-9 s they take, the directory at 10, the pull at 8) shortens
  the loop and never takes the job past its timeout, which would cancel it before its
  successor and end push. A set-up step past its bound fails the job before the loop: no
  successor and no `chain` record, so the timer's `reader` job or the schedule starts the
  next run 5-20 minutes on.
  Its successor step runs whether the loop succeeded or failed (never on a cancel, and never
  when the loop did not run because the directory step failed: the `reader` job or the
  schedule starts the next run 5-20 minutes on, not a tight chain of cold runs), 3 tries; a
  successor that cannot be dispatched is a warning and the `chain` alert.
- **Restarters.** The successor step; live-ingest.yml's `reader` job on every tick (it starts
  one when no live-read run has a reader job that is not completed (the evidence job after it
  is not counted), and switches a run whose mode is
  not `LIVE_PUBLISH`'s); and the `*/20` schedule, for when the timer itself stops. While a
  reader job runs (all day), each scheduled run waits as the group's pending job and is
  cancelled by the next one queued (the next successor): grey cancelled live-read runs in the
  Actions tab, never red. GitHub's default notifications email on failed runs only.
  (POSTLAND: confirm no email reaches the owner for them.) GitHub creates far fewer
  scheduled runs than the cron asks: 22 from Oct 25 12:45Z to Oct 29 18:38Z (about 5 a day),
  each pending with no step run until a successor replaced it, so one stood pending 47% of
  the time and none for up to 5.9 hours at a stretch. A pending one starts as soon as a run
  ends with no successor, by the same group rule that starts every successor (11-30 s after
  its predecessor's job ends); with none pending, the schedule restarts the chain only at
  GitHub's next scheduled run. The timer's `reader` job is the restarter to count on.
- **One at a time.** The job-level concurrency group `live-read` keeps one reader job, so
  there is one writer of the state and of the prefix.
- **Stuck passes.** A pass is cut 30 s after its 240 s deadline whatever its workers do: the
  sources not finished are `late`, and a thread still running is abandoned. With more than 8
  abandoned threads alive the run exits 1 and its successor starts clean. A process that ends
  with any abandoned thread still running ends at once with its exit (`os._exit` after its
  output is flushed): the interpreter's own exit would wait for that thread for good, until
  the watcher killed it. The live client
  keeps no idle connection, so every request's deadline cuts its own connection, header phase
  included. A bash watcher (`.github/scripts/pulse-watch.sh`) sends TERM, then KILL 10 s
  later, when `out/internal/live/state/pulse` is 3.5 minutes old. The loop touches it at
  every tick of a pass's reads (every 5 seconds while the pool's workers run), per read it
  folds into the ledger and per source it resolves, at every request to and answer from the
  live host, D1, the deployed site and GitHub's API (at most every 5 s), and after each pass,
  push and 60-second check. So a hang that holds the interpreter is caught, and a healthy
  loop's longest silence is one request (its timeout, 60 s at most) or the wait before a
  60-second check, never a whole slow publish or push. Worked through from a hang at the
  start of a grid pass (last pulse up to 60 s before it, the upload before it at G-3.5): the
  kill under 4 minutes after that pulse, the job's end steps (about a minute; 100 s with the
  end push at its 60-s bound), the successor's queue and cold start (about 1.5 minutes) and
  its first pass's reads (1.5 minutes, or 2.5 for a full sweep in a busy window) make a
  publish gap of about 12.3 minutes, 13.0 at worst, under the 15-minute bar. The job's end
  steps are the successor's dispatch, the record, the end push, the closing report, the
  export, its check and the cache save, and nothing else: the evidence push is a job of its
  own outside the `live-read` group ([The evidence](#the-evidence)), so the successor never
  waits for it (a test holds both).
- **Cancels.** The runner signals only the loop step's own shell on a cancel (a mode change,
  the stall drill, the job's timeout): SIGINT, then SIGTERM 7.5 s later. The step runs the
  watcher in a process group of its own and traps both: it passes a TERM to the watcher,
  which passes it to the reader (TERM keeps its default there, so it ends at once) and KILLs
  it if it still runs 5 s later, then exits. No reader outlives its step. Before anything
  packs the state, a step (`.github/scripts/reap-reader.sh`) KILLs whatever of that group is
  left and says `clear`; the record, end push, export, its check and the cache save run only
  then, so no state is packed while a reader may still write it. A step that stalls is
  bounded too: the directory step at 10 minutes, the pull at 8 (its own bound is 6).
- **Exit codes.** A run exits 1 only for a persistent failure: 3 failed passes in a row, a
  blank that keeps failing for 10 minutes, a lost state swap, more than 8 abandoned threads,
  a failed end push, a directory step that failed (the loop never ran), or the watcher's kill
  (124). Otherwise 3 when a pass was refused or the deployed directory changed, else 0. A 3
  never fails the loop step (refused passes are routine in a 320-minute run), so in `on` only
  a persistent failure turns a run red; in shadow and off a run never turns red
  (`continue-on-error`). A step before the end push records the run's exit in `exits.json`
  in the state folder (`live finish --record`), so the end push carries it to D1 and the next
  run's closing step counts it for `chain`. The closing step runs after the end push and
  prints the exit and its cause as one annotation and a summary notice (state size, D1 pushes
  and rows written today, the live host's size and the hour's `GITHUB_TOKEN` count); it
  replaces the recorded exit with its own (a failed end push makes it 1) and never counts a
  run twice. A cancelled run (a mode change) records no exit. A run that records any exit
  but 1 or 124 (0, or the routine 3) closes `chain`.
- **Notices for the soak report.** The loop prints `live-read ready <time>` when it could pass
  (the cold start ends there), `live-read first pass <time>` (a successor's first pass may
  wait for the next grid mark or skip an unchanged upload, so its first commit can be the next
  grid pass) and `live-read end <cause>` (`until`, `edition`, `overrides`, or an exit-1 cause
  such as `passes`, `threads`, `state`). A job still running has no annotations on the API
  yet, so the report gives it no cold start. A step prints `live-read caches
  restored <bytes> bytes`, and live-ingest's `reader` job `github token used <n> of <limit>
  reset <time>` on every tick.
- **Code ahead of the deploy.** `publish.<prefix>.json` keeps the directory content each
  upload was made against. When the deployed content differs from this run's build but is
  that content, this run checked out a directory-changing head before Preview deployed it:
  nothing is blanked, passes are refused, the check every 60 s passes at once when the deploy
  matches, and `edition` opens after 15 minutes of it. A deploy that moved under a public stamp
  (other content than the last upload's) is blanked at once, then the run stops for its
  successor, as before.
- **The admin's statuses.** Each pass reads `GET {API}/v1/overrides` (the check job's rules:
  `SNOWLIGHT_API_ROOT`, else the account's `snowlight-api` Worker) and puts them on top of the
  lists. No API means none; an API error refuses the pass, so a status is never dropped on a
  blip. A pass refused only for health (G12b) or the spike hold (G12e), when the admin's
  statuses changed since the last upload, publishes the last published list rows unchanged
  with the new statuses under `generated_at` = the last published + 1 s, so the file's age
  stays the list's age (a status set after that moment shows no "Posted" time).
- **Commits.** Each upload's commit message is `live <prefix> pass <start> run <id> sweep <s>
  due <n> good <n> lit <n> state <bytes>`: counts only, the public record the soak report reads.
  A message names its own commit only: any other write of a live-read process (an alerts file,
  a blank) gets its own message, by default `Publish the live files (live-read run <id>)`, so
  a reader commit under `v1/` can always be told apart from the overrides job's. The
  overrides job (`live overrides`) keeps the message it always wrote, `Publish the live
  files`. The owner's stop writes `live-blank <prefixes> hold|blank|release <time>`.
- **Logs** are public for 90 days: `PYTHONWARNINGS=ignore`, the redacting formatter on the root
  logger (a library's or a warning's record prints no words), `httpx` and `httpcore` at
  WARNING, and an uncaught exception prints its type only, in the main thread, in any other
  thread, and where Python cannot raise it (a `__del__`).
- **Tokens** reach only the steps that use them: the live host's token the token check, the
  loop, the end push and the closing report; `GITHUB_TOKEN` the directory, the loop, the
  successor, the end push and the closing report; the Cloudflare secrets the pull, the loop
  and the end push.

Cold start (the job's start to the loop's `ready`): 50-90 s in the 21 runs of Oct 25-29 with
logs (p95 85 s; the soak report's 254 s was its last run, still running, measured to its first
commit). The soak report gives it beside the cold start to the first pass and the wait between
them (at most one grid slot when the run waits for the next mark, bar 310 s):
job set-up 0-2 s, checkout 2-6, setup-uv 3-9, `uv sync` 0-1, the cache restores 3-4, the
deployed edition and `directory build --zones --no-tiles` 24-42, the D1 pull 2-6, then about
10 s for the matcher, gazetteer, registry and status reader. The job's own queue behind its
predecessor adds 11-30 s.

## The state

The reader's private state lives in the D1 database `snowlight-live-state` of the owner's
Cloudflare account (`state.kind: d1`, `snowlight/live/d1.py`), reached with the repository
secrets `CLOUDFLARE_API_TOKEN` (Account / D1 / Edit) and `CLOUDFLARE_ACCOUNT_ID`, which reach
only the pull, loop and end-push steps (and the evidence job's push, [The evidence](#the-evidence)). No Worker is bound to it: nothing on the internet
reaches it. It is created by the first run (only when the account's list answers and names no
database exactly `snowlight-live-state`), on the free plan with no card.

- **What goes in:** the packed state folder: `ledger.sqlite`, `publish.json` and
  `publish.<prefix>.json`, `robots.json`, `cadence.json`, `pacer.json`, `exits.json`,
  `changes/`, `morning/`, `unmatched.json`. Never packed: `d1.json` (this run's epoch) and
  `pulse`. Never off the runner: request bodies and validators (`.cache/stations/live`),
  `health.json`, `provenance.jsonl`.
- **Pull** (at start, `live state pull --retry`: 3 tries 10 s apart, then every 60 s, for 6
  minutes in all, the request in progress included, so a hanging API cannot stretch it):
  `head` names a slot; its chunks are read and checked against its sha256, falling
  back to the previous slot. The run then takes the epoch (the newest puller wins), only
  while `head` still names the sha256 just read: a push that swapped `head` meanwhile (the run
  before's end push) is read again, up to 3 times, so its state is never dropped. A pass that
  newly blocks or defers a source writes its `holds` row at once; holds are merged into the
  cadence at pull, so a block or a `Retry-After` is never asked again from a new runner after
  a crash. Before its first publish a run catches its change log up from the public day
  timelines of recent days: changes published after the log's last minute (by an
  overrides-only run, which pushes nothing, or in a run's last minutes before its last push)
  are taken in first, so a stretch the map showed dark stays dark in the history. A slot whose
  ledger fails SQLite's `quick_check` counts as one that fails its sha256 (the previous slot
  is read).
- **Push** (every 30 minutes in the idle time after a pass; after an edition blank, or in the
  idle time after the next pass when the blank left too little time; and at the end in its own
  step): the whole push, each request's timeout included, ends 30 s before the next grid mark.
  This epoch's own slot is written with upserts, then `head` is swapped to it only if the
  epoch and the sha just read still hold. A run that sees another epoch writes nothing and
  stops (`state`, exit 1). A swap or epoch take whose answer was lost and which was sent again
  changes no row: `head` is read again, and when it already names this push (or this run's
  epoch) the push (or the pull) is good. After an epoch's second good push the older epochs'
  chunks are deleted, counted first, and only when the delete fits under the write cap (else a
  later push deletes them; nothing reads them). A failed end push raises `state` and is the
  run's exit 1. The end push is bounded at 60 s, every request included; it first writes
  every hold `cadence.json` still has (a few rows). The ledger is packed through SQLite's own
  locks only: a read-only connection's backup (consistent while another process writes), or,
  when that fails beside a hot journal a killed process left, a read-write connection to the
  file itself, which rolls the journal back under SQLite's lock first; the copy must pass
  `quick_check`, or nothing is packed. (POSTLAND: the first runs' end push lines give its
  seconds and size; over about 30 s at storm sizes, the bound is raised against the
  watcher's gap, or the end push skipped when the last loop push is recent and nothing
  changed.)
- **Write cap.** Every answer's rows written are counted per UTC day in `budget` (an answer
  without the count is billed one row a writing statement at least, and a write sent again
  after its answer was lost or a 5xx is billed for each try): each push bills its own,
  the pull bills its own at its end, and each holds write bills itself at once. Past 20,000
  the loop pushes hourly; a push that would pass 30,000, counting each chunk as two rows (D1
  does not say how an upsert is billed), is refused and the loop runs on in
  memory (`state`). The holds have their own 200 rows a day past 30,000 (the account's limit
  is 100,000), so a new block is kept at once even on a day the cap stops the pushes. A holds
  write that fails (D1 does not answer, or the allowance is spent) is kept pending, tried
  again in the loop's idle time and with the next holds, and the end push writes every hold
  `cadence.json` has, so a successor on a new runner pulls it. A first push that writes more than 1.2 times its plan goes hourly too. That
  leaves 70% of the account's 100,000 daily writes to `snowlight-accounts`. The packed state is
  at most 16 MB (`state` over 12 MB).
- **Failures.** D1 unreachable at pull: the loop runs **overrides-only** (no source read, no
  push, no cache; each grid pass publishes the admin's statuses alone, so list rows go dark,
  never wrong) and ends with exit 0 once a pull would succeed (a read-only probe each pass,
  60 s at most: `head` reads and names bytes that match, or is old enough to start empty), so
  its successor starts from the pulled state. Both slots failing their sha256: overrides-only
  too, and the run goes on (the probe still fails) until `head` was last pushed over 2 hours
  ago; then the next run takes the epoch and starts empty (cold: every
  undated row is withheld). An empty state never overwrites a readable one. A failed push is
  tried again at the next slot.
- **Repair.** To start the state over, delete the database in the Cloudflare dashboard (D1 >
  snowlight-live-state > Delete); the next run makes a new one and starts cold. Only a
  live-read run takes an epoch or pushes (`GITHUB_WORKFLOW` must be `live-read`).
- **predict learn** reads only the export: at the end of each run `live state export` writes
  `out/internal/live/store/live-state.tar.gz` with `morning/`, `changes/` and a schema-only
  `ledger.sqlite` (no secret, no rows); a step requires the archive, lists it and refuses the
  save on any other name or file, then it is saved as `live-state-<run id>`, the key
  predict.yml restores. The Actions cache is readable by pull requests. What the export holds,
  exactly: per district (its LEAID), which days present rows of any source named it, withheld
  or not, and for each slot of the morning windows the prefixes it was shown under; per change,
  the school's NCES id, the source's registry id and type, the row's key (a keyed HMAC that
  cannot be reversed without the ledger's secret, which the export leaves out), and codes and
  times. No name, listing text, URL or secret. That is more than the public day files show
  (they hold no LEAID of an unlit district and no row key), and none of it is personal.
  predict learn labels only days with a pass shown under `v1`, so the shadow reader's export
  labels and writes nothing (no `v1/predictions/learn.json` commit from a shadow day).
- **The overrides job's memory** (live-ingest.yml's publish job, unchanged): its own cache
  entry `live-overrides-state-<run id>` of `out/internal/live/state`, a few KB: the publisher's
  memory (`publish.json`) and the day's change log (school ids, codes and times). It is the
  one cache in `live-*.yml` besides the export, kept so the owner-visible overrides publish
  stays exactly as it was (its publisher takes no recent day from the public day timeline
  and blanks under its old commit message, as before the reader); at go-live, when the
  reader writes `v1/` and that job is skipped,
  it stops being written. A test holds that `live overrides` writes only `publish.json` and
  `changes/` there (never a ledger, unmatched rows, robots rules or a pacer). (Lead decision
  pending: amend E1 to name it, or move it at go-live.)
- **The box** (`state.kind: local`) keeps the archive in `out/internal/live/box`.

## The evidence

What the reader saw on a morning cannot be read again, so every finished day of the morning
record and the change log is kept for good, beside the state and apart from it
(`snowlight/live/evidence.py`, advisory-sane L0; the owner's decision of Oct 29: keep them
forever). The state folder keeps 45 days, which is what predict learn reads, and lets a day go
only once the evidence store holds it; the evidence store keeps every day.

- **Where.** Two D1 databases of the same Cloudflare account, `snowlight-evidence` and its
  backup `snowlight-evidence-backup`, made by the first push the same way as the state's (only
  when the account's list answers and names none), with the same two secrets. No Worker is
  bound to either, so the site cannot serve them and nothing on the internet reaches them.
  Deleting `snowlight-live-state` to start the state over leaves them as they are. Each push
  writes both, and copies across whatever one holds and the other lacks, so a database
  deleted by hand is filled again from the other on the next run. D1 Time Travel restores
  either to any minute of its window (7 days on the free plan). Both are in the one account,
  under one token: they guard against a database lost or a bad write, not against the account
  lost or the token misused. An off-account copy (spec 19's private data repository) is the
  next step when the owner allows it.
- **What.** `morning/<UTC day>.json` once 2 hours have passed after its day,
  `changes/<day>.jsonl` 4 days after its day, and from the predict workflow (`predict
  evidence`) each school day's weather-class snapshot once 12 hours of its day have passed, the
  district table of every directory content predict ran under (kept while it is deployed,
  before a snapshot indexed under it settles; a finished snapshot whose content has no kept
  table is named in a warning) and every version of the labels (`learn.json`). The live
  labels' trials and read audit (advisory-sane L1) go here too (kinds `trials` and `audit`).
  The bytes are the files' own, xz compressed: codes, LEAIDs, NCES ids, registry ids, keyed
  row HMACs, counts and times. No name, listing text, URL or secret; nothing personal.
- **Append-only.** Tables `items(kind, key, sha256, bytes, packed, parts, codec, kept_at,
  run_id)` and `parts(sha256, n, data)` (64 KiB a part as base64). Every statement is an
  `INSERT ... ON CONFLICT DO NOTHING` or a `SELECT`; the store has no `UPDATE`, `DELETE` or
  `DROP`, so nothing kept is ever changed or removed. A file that changed after it was kept is
  kept again as a second version beside the first. A version's parts go first and are read
  back whole and checked against its sha256 and size; only then is its item row written, so an
  item row always means a whole copy. A damaged version is never copied to the other database.
  Versions are told apart by sha256 before anything is compressed: only a version a database
  lacks is compressed and written.
- **When.** The `evidence` job of every live-read run (`live evidence push --export`), after
  the reader job: it restores the export that job just saved (this run's cache key only) and
  reads the finished days straight from the archive. It has no concurrency group, so the
  successor reader never waits for it (two pushes that overlap write the same rows, `DO
  NOTHING` on conflict). It gives itself 4 minutes of new writes and at most 1,000 rows a
  database (a finished day is a few rows), with an 8-minute step limit; what is left waits for
  the next run, which offers the same days again. The job runs only after a reader job that ran
  (succeeded or failed), with read-only contents permission, and sets nothing up before it finds
  this run's export. `predict evidence` runs after the passes, 30 seconds of writes, a 2-minute
  limit, then notes in the predict pass state what the databases hold (docs/predict.md). Both
  continue on error (one `::error::` line when not every database was written), and neither
  touches the live state. Only live-read keeps morning records
  and change logs, and only predict snapshots, tables and labels.
- **Before a day leaves the state.** Once an hour, in the loop's idle time (20 seconds at most,
  ending 30 seconds before the next grid mark, and never after the run's last pass, so it never
  holds a pass, the run's end or its successor's start; a run's first check comes after a cold
  start's first pass, or in a successor's wait for its first mark), the reader asks both databases which versions they hold
  (read only: nothing is created) and writes the answer to `kept.json` in the state folder
  (packed with the state, never exported): per day, the sha256 of its file and the databases
  that hold exactly those bytes. Each database gets its own share of the 20 seconds, so a slow
  one never starves the other, and a database that does not answer changes nothing known of it
  (no false alarm from one missed check). A morning day or change-log day older than 45 days is
  pruned only when a database holds it, and so is a morning day the size valve drops (oldest first, never the last 10,
  while the folder holds more than 16 MB). A day no database holds stays however old, unless
  the folder passes 32 MB: then the oldest go anyway, each with an `::error::` line and the
  `evidence` alert, so the packed state stays inside its 16 MB budget whatever the evidence
  store does. The `evidence` alert also opens when a finished day has waited 2 days for a copy
  in both databases (counted from the first check after this landed), and closes when they
  hold it. With no evidence store to ask (a state outside D1, or its secrets missing), a day
  the valve dropped still opens the alert, for 7 days.
- **Reading it back.** `snowlight live evidence pull --kind morning --since 2026-10-27 --out
  <private folder>` writes the newest version of each kept day, checked, from whichever
  database holds it whole, an older version when no copy of the newest reads (a warning names
  it), and a warning for a day kept in more than one version; `--all` writes every version as
  `<day>.<sha256 prefix>.<ext>`. It needs the two secrets, as a workflow step has them.
  `snowlight live evidence size` prints each database's versions and bytes per kind. Every
  push logs what each database holds in all, and warns (an annotation) past 300 MB.
- **Size, 10 winters.** Measured on the real formats (`live/morning.py`, `live/history.py`)
  filled with synthetic days, xz compressed, base64 stored: a morning day is 27 to 66 KB with
  400 to 1,011 sources read every slot and counts that change every slot, 73 to 121 KB on a
  storm morning naming 800 to 9,000 districts; a change-log day 2 KB calm, 54 KB with 2,000
  schools lit, 397 KB with 15,000; a snapshot 3 KB; a district table 58 KB. At the worst of
  those (every day of the year at 66 KB, 30 storm days, 15,000-school days included) a year
  is about 46 MB a database, 460 MB in 10 winters. October's real record is far smaller (the
  live export of 4 days of morning record and change log, with the schema-only ledger, was
  60,685 B gzipped on Oct 29, about 8 KB a morning day once xz compressed), and a year of
  300 such days and 65 storm-season days at the sizes above is about 21 MB, 210 MB in 10
  winters. D1's free plan allows 500 MB a database, 5 GB and 10
  databases an account (accounts, state and the two evidence databases make 4). The push's
  size line gives the real growth; past the 300 MB warning, the next winters go to a new pair
  of databases (or the paid plan's 10 GB) before the limit, by a reviewed change.
- **Not here.** The public day timelines are on the live host, whose git history keeps every
  version.

## Alerts

Where an alert goes depends on the mode:

- **shadow** (the default): no issue is ever opened, so nothing emails the owner. Each open
  and close is recorded in `v1-shadow/live/alerts.json` (kinds, UTC times, codes, counts,
  registry ids) and printed as one annotation (8 a run at most, later ones as plain log lines,
  so with the loop step's own warning a step never passes Actions' 10 of a level and the
  soak's 3 notices are always kept); the `watch` job adds one annotation on every tick that
  finds the shadow file stale.
- **on** and **off**: one issue per kind and prefix, labelled `live-alert` and found by its
  marker, at most one comment an hour, closed with "recovered at HH:MMZ". While `state` or
  `stale` is open, `gate`, `health`, `source`, `cold` and `chain` comment on it instead of
  opening their own.

| Kind | Opens when | Clears when |
|---|---|---|
| `gate` | 2 refused passes in a row | a pass publishes |
| `health` | healthy share under 60% for 3 passes in a row (a real reading problem lasts) | 2 passes at 60% or more |
| `source` | the daily digest (after 15:00 UTC): sources erring 3 h or more inside their windows that did not err in the 24 h before | the next digest has none |
| `breaker` | the breaker or the spike hold fired | 2 clean passes |
| `edition` | a mismatch, a blank, an unreadable deployment, or code ahead of the deploy for 15 min | the handshake is good |
| `cold` | 20 or more candidate rows and over 25% `unknown_start` in a morning window | the window ends |
| `state` | a failed pull or push, a lost swap, overrides-only, the write cap, state over 12 MB | the next good push |
| `chain` | 2 runs in a row exited 1, a successor could not be dispatched, or a run's directory step failed (it starts no successor) | a run records any other exit (0, or the routine 3) |
| `timer` | no live-ingest run created in 15 minutes | one is created |
| `stale` | the served file is over 15 minutes old, missing or over 60 s ahead (`watch` job) | a fresh file is served |
| `evidence` | a finished morning-record or change-log day not in both evidence databases 2 days after it ended, or a day the size valve dropped before any database held it ([The evidence](#the-evidence)) | both hold every finished day (a dropped day: a week on) |

Titles, bodies, comments, annotations and `alerts.json` carry kinds, times, counts, codes,
registry ids and the run link only: never a listing's words, a name, an email, a token or a
response body.

## The switch: LIVE_PUBLISH

The repository variable `LIVE_PUBLISH` decides who writes `v1/`, read as Actions compares
strings (case ignored, nothing trimmed): `on`, `shadow` or `off`; unset and any other value
are `shadow`. The overrides job's own `LIVE_OVERRIDES_PUBLISH` is read as before: exactly
`on`, `shadow` or `off` (another value, another case included, fails the job and publishes
nothing).

| Value | live-read | live-ingest.yml |
|---|---|---|
| unset or `shadow` | writes `v1-shadow/` | check, publish and notify as before: the admin's statuses reach `v1/` |
| `on` | the one writer of `v1/` (lists and the admin's statuses in every pass) | the publish job is skipped; notify as before |
| `off` | runs the gate, uploads nothing (alerts are issues) | as in shadow |

`LIVE_OVERRIDES_PUBLISH` stays the publish job's own switch while `LIVE_PUBLISH` is not `on`
([Manual statuses](#manual-statuses-the-admin)). A change takes effect within one tick: the
`reader` job cancels the run in the old mode and starts one in the new; each prefix keeps its
own memory. Shadow to on: `v1/` has no writer for up to about 9 minutes (the admin's statuses
stay as they were meanwhile). On to shadow: the publish job takes `v1/` back at its next run;
the cancelled reader ends within 5 s of the cancel, so the two overlap for seconds only.

**Go-live** (after the trial, on the owner's word): Settings > Secrets and variables > Actions
> Variables > New repository variable `LIVE_PUBLISH` = `on`. Within one tick live-ingest stops
its overrides publish and restarts the reader in `on`; `v1/` carries the lists and the admin's
statuses within about 9 minutes. From then on alerts are issues (one email each).
**Rollback:** set the variable back to `shadow` (or delete it), or run live-blank.

## Drills

`live-drill.yml` runs only from a push to the default branch that changes its own file: each
drill is one push that changes its `DRILL:` line. It lands as `DRILL: none` (one notice, no
drill), so the push that adds the file starts nothing. A drill refuses when `LIVE_PUBLISH` is
`on` or `v1/live/hold.json` holds the map, and names `v1-shadow` itself. Each drill prints
its moments as `live-drill <drill> <event> <time>` notices, which `live soak` reads on the
public API (its `drills` section).

- `stall`: cancels the running live-read run, disables live-read for 35 minutes, then waits
  for the moment 75 s before the next timer tick (the ticks land at :x0:40 and :x5:40) and
  enables it, so the reader job's dispatch at that tick finds it enabled; it logs the enable
  and the first live-read run that starts after it. Expected: `stale` within 30 minutes of
  the last shadow commit, the reader running again within 5 minutes of the enable, `stale`
  cleared within 10 minutes of the first fresh commit, every live-ingest run green.
- `gate`: dispatches live-blank (`blank`, `v1-shadow`), finds the blank's own commit (message
  `live-blank v1-shadow blank <time>`) and the `generated_at` it carries, reads the shadow file
  through the CDN every 5 s until that exact blank is served (an ordinary empty upload under
  another stamp never counts), and logs the commit time, the served time and the delay as one
  annotation, within or over the 60-s bar; then waits 12 minutes and dispatches live-blank
  (`release`, `v1-shadow`). Expected: `gate` in `alerts.json` within 15 minutes of the hold
  commit and cleared within 10 minutes of the release; the blank served within 60 s of its
  commit in 3 of 3 drills; nothing under `v1/`.
- `switch` (E8, before go-live): `snowlight live rehearse` runs the overrides writer, the
  reader in `on` (one pass) and the overrides writer again, all on `v1-rehearse` of **a folder
  on the runner** (never the public live host: the SYNTHETIC status below is committed
  nowhere and served to no one), each with its own cold local state, with no Cloudflare secret
  and no live host token in the step (so no D1 state; the command refuses to run with a
  Cloudflare secret, or with `LIVE_PUBLISH` on). The reader's pass **reads no source**: a
  second runner never asks a station page or a robots.txt again, past the holds, robots rules
  and Crawl-delays the live reader keeps; with every due source unread, G12b refuses the lists
  and the admin's status is published alone under the G12b/G12e exception. The admin's status
  is a SYNTHETIC override served on the runner's loopback (one school of the deployed
  directory, open today in its own zone). After each writer the override must be in the
  folder's file under that writer's stamp within one pass; at the end `v1-rehearse` is blanked
  and held. Serving through the CDN is the gate drill's measure (E6).

A drill never turns its run red (the job continues on error): a refusal or a missed bar is an
annotation in the drill's log, so the pusher gets no email.

The 48-hour soak's report: `uv run snowlight live soak --since 2026-10-31T18:00Z --until
2026-11-02T18:00Z` (local, read only, public records). It reads the reader's commits to the
shadow file, every commit under `v1/live` (any naming a live-read run, or a `live v1 pass` or
`live v1 alerts` message, is a reader commit: there must be none in shadow), predict's
commits to `v1/predictions/latest.json`, the live host's whole commit order with its Pages
deployments (a commit whose own deployment was superseded is served by the next one), the
runs, jobs and annotations above, and githubstatus.com incidents. Every boundary is typed
(successor, mode change, restart after a kill, restart after exit 1, edition stop,
restart); the cold start is the job's start to the loop's `ready` notice (bar 120 s),
beside the job's start to its first-pass notice (no bar) and the wait between them
(bar 310 s). The first-pass number is the spec's original cold start: since a successor now holds
its first pass for the next grid mark, it reads about 180-300 s by design for most
successors, the wait being at most one slot. Its `drills` section
measures each drill in the window from the drill's notices, the `watch` job's stale
annotations and the commits of `v1-shadow/live/alerts.json` (`live v1-shadow alerts
open|close <kind> <time>`): for `stall`, `stale` after the last shadow commit (30 min), the
first live-read job after the enable (5 min), `stale` cleared after the first fresh commit
(10 min) and every live-ingest run green; for `gate`, `gate` opened after the hold commit
(15 min) and closed after the release (10 min), the blank served after its commit (60 s) and
no reader commit under `v1/`; for `switch`, the rehearsal's verdict. Run it with a
`GITHUB_TOKEN` in the environment (a 48-hour window makes about 3,000 requests; the
unauthenticated limit is 60 an hour).

## The timer token

The owner's Cloudflare Worker `snowlight-timer` dispatches `predict.yml` and
`live-ingest.yml` every 5 minutes with a fine-grained personal access token (Actions: read and
write on this repository). Its expiry date is set when it is made. When it expires, live-ingest
stops (the admin's statuses in shadow, notify, watch, and the `reader` restarter); live-read
keeps itself going through its successor and schedule, and `timer` opens within 15 minutes. To
renew: GitHub > Settings > Developer settings > Fine-grained tokens > the timer's token >
Regenerate (or make a new one with the same access), then in the Cloudflare dashboard >
Workers > snowlight-timer > Settings > Variables and secrets, replace its token secret.

## Commands

All from `pipeline/` (`uv run snowlight live ...`).

| Command | What it does |
|---|---|
| `live once [--only ID ...]` | One pass: read, resolve, merge, gate, publish. It always uploads. `--only` reads only those sources, so the health check counts every other due source as unread and refuses: it is for looking, not for publishing. |
| `live run --until +320m [--push-every 30] [--overrides-only]` | The reader's loop ([The reader](#the-reader)). |
| `live blank [--prefix every\|v1\|v1-shadow]` | The emergency stop for a wrong light. Sets the hold and blanks the public closings files (every prefix by default). |
| `live release --prefix every\|v1\|v1-shadow` | Clears the hold under the prefix named (required). The next pass there publishes again. |
| `live check --url URL --max-age 15m` | The watchdog. Checks that the public file is fresh, is not stamped ahead of the clock, and carries the deployed directory's stamp. |
| `live state pull [--retry]` / `live state push` / `live state export` | Restore or keep the private state; write the export predict learn reads. |
| `live evidence push [--export ARCHIVE]` / `live evidence pull --kind K [--since DAY] [--all] --out DIR` / `live evidence size` | Keep the finished morning-record and change-log days (of the state folder, or of a live-state export) for good in both evidence databases; read kept files back into a private folder; print what each holds ([The evidence](#the-evidence)). |
| `live rehearse` | The switch rehearsal on `v1-rehearse` ([Drills](#drills)); live-drill.yml's `switch`. |
| `live alert --kind K --open\|--close` | A workflow step's alert (in shadow an annotation and `alerts.json`, else an issue). |
| `live finish --exit N` | live-read.yml's closing step: the exit, the summary notice, the `chain` alert. |
| `live soak --since T --until T [--prefix v1]` | The soak report from public records; `--prefix v1` reads the reader's commits under `v1/` (LIVE_PUBLISH on), where the shadow soak's bar of no reader commit under `v1/` does not apply. |
| `live overrides --api ROOT` | One pass of the admin's manual statuses: read the active overrides from the API, check them against the deployed directory, gate and publish. Stops, writing nothing, when the overrides light nothing and the public files show no status. |
| `live sweep --cache-dir DIR --state DIR --log FILE --report FILE` | One measured pass of the pool over every source the ingest polls (or `--only` ids), resolving and publishing nothing. Appends each request to the log (its pace key, its floor and when it held the key) and writes a report: the sweep's time, when each source finished, the outcomes, the requests sent against those paced, the pacing violations and the robots.txt requests per origin (every attempt, counted from the log). `--state` keeps what servers asked of the sweep across sweeps: robots.txt verdicts and holds in `robots.json`, and in `cadence.json` only each source whose server asked for a `Retry-After` or answered 403. Such a source is not asked again until that wait or the 24 h block ends, and the report lists it under `held_back`. A source the sweep read is not recorded as read, so a live reader sharing the folder still reads it on its own cadence. Exits `1` on any violation or unpaced request. Ids, hosts, codes and times only. |
| `live overrides --none` | The same pass with no override: takes every manual status down (`live-ingest.yml` runs it when no API is left to read). |

Exit codes:

- `0`: published, or held on purpose (nothing changed, publishing off).
- `3`: the gate refused and nothing was uploaded. `check` also exits `3` when the file is stale, missing (HTTP 404), more than 60 s ahead of the clock, or on another stamp than the deployed edition.
- `1`: an error. Nothing is known to be published. For `live once` this includes a state push that failed after the pass; for `live run`, see [The reader](#the-reader).

A refusal is never retried by hand: the next pass decides again.

## The emergency stop

`live blank` (and live-blank.yml) works the same whatever `LIVE_PUBLISH` says. A shadow reader
blanks only `v1-shadow/` on its own (an edition blank, a hold it finds); only `live blank`
touches every prefix.

1. It writes `live/hold.json` (`held: true`) in `v1/` and `v1-shadow/` (or only the `--prefix` named), first and in a write of its own, so the hold stands whatever happens next.
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

`live release --prefix P` writes `held: false` under `P` (`every` for both) and keeps the time the hold began. A run that never saw the hold still records the dark minutes. After a release:

- The next pass publishes again, and every day timeline is published again.
- A status the hold darkened lights again only while a source still lists the row that lights it. Merge keeps a row through its day after the source takes it down, but not for these school-days: they stay dark until the day ends.
- A status a source still lists lights again, and the timeline shows it from the release on.

So to remove one false status for good, fix its cause first: the source takes the row down, or a fix to the code, the matcher or the registry stops it from lighting. Then release. If the cause cannot be fixed, keep the hold until the day ends.

Exit `0` means every prefix is held and every file is blanked. Exit `1` means the host could not be written, so try again. Exit `3` means the hold is set but a file was not blanked, because its blank would be stamped more than 60 s ahead of the host's clock. Fix the clock. The running ingest blanks that file as soon as the clock allows.

## Switches and secrets (environment only)

| Name | Meaning |
|---|---|
| `LIVE_PUBLISH` | `shadow` (default, and any value but `on` or `off`, case ignored): write under `v1-shadow/`. `on`: write under `v1/`, the root the site reads. `off`: run the gate, write nothing. `off` is not an emergency stop: lights already published stay until their day ends. Use `live blank`. See [The switch](#the-switch-live_publish). |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | The D1 state store (state `d1`), and the API root's lookup. Only the pull, loop and end-push steps of live-read.yml get them. |
| `SNOWLIGHT_API_ROOT` | The API root for the admin's statuses (optional; else the account's `snowlight-api` Worker). |
| `LIVE_HOST_TOKEN` | Writes the Pages repository (host `github`). Contents write on that repository only. |
| `LIVE_R2_ACCESS_KEY_ID`, `LIVE_R2_SECRET_ACCESS_KEY` | The bucket keys (host `r2`, or state `bucket`). |
| `GITHUB_TOKEN` | Reads the site's deployments for the directory check, in the ingest and in `check` (`deployments: read`, `actions: read`, `contents: read`). |

Host `github` needs the Pages repository to serve its whole tree: today
`viaate/snowlight-live` deploys only the S8-A probe, so a committed file is never served.
The workflow that serves the repository root, and the one-time shadow check, are in
`docs/predict.md` (What the owner sets up once, step 4).

## Reading the sources

A pass reads the sources due through a concurrent pool (`snowlight/live/pool.py`) on the cadence (`snowlight/live/cadence.py`).

- **Politeness.** One request in flight per host and starts at least `max(5 s, Crawl-delay)` apart, across all 24 workers. Each of Gray's list files, path-style on `s3.amazonaws.com`, is paced under its own bucket (owner decision Q3), the same as its documented per-station address. robots.txt is read at most once per origin a day (kept in `robots.json`), and is still a record, never a gate. A robots.txt that fails, or that asks for a `Retry-After` the pass will not wait for, is kept as unreachable for the day; that wait holds every source on the origin as `deferred` until it ends, and a stopped source starts no further request. A request must answer by its source's deadline (plus a second): its connection, opened fresh for it, is shut then, so a server that trickles its headers or body holds the host no longer. A file several sources read (Cowles' five stations share one) is asked once a pass, and a `Retry-After` or a slow answer it gave is what every source reading it gets for that pass.
- **Deadlines.** A source gets 60 s, attempts and follows included (two attempts); nothing starts after 240 s into the pass. A source cut off is `late` and due next pass. A server's `Retry-After` is honoured: the source is `deferred` until that wait has passed, and no other source waits for it. A 403 or 401 blocks the source for 24 hours. A refusal is never worked around.
- **Cadence.** Every 5 minutes from 18:00 to 23:00 and from 04:00 to 09:00 in the station's own zone (the zone most of its counties are in; real zone rules, so the windows follow daylight saving time), and while an NWS alert of an allowlisted type covers one of its counties (the alerts are read every 5 minutes; a failed read keeps the last set for 2 hours). Otherwise every 30 minutes, or the registry's `poll_minutes` when longer. A source the pass did not get to (`late`) is due at the next pass; a failed read (`error`, such as a 429 or 5xx without `Retry-After`) keeps its cadence, so outside the windows and alerts it waits its calm interval, a successor's first read of it included. A source is never read again in the same 5-minute grid slot, nor less than 4 minutes after its last pass.
- **Health share.** G12b counts the sources due in the passes of the last 15 minutes, and every source blocked now, each by its latest read in that time. Both windows are counted from the passes' starts: a read is kept under the start of the pass that picked its source, the moment the cadence counted that source due, and both are dropped by the same test on the same start, so a source due in the window always has its picking pass's read in it, and that read is its latest (only a pass that picks a source reads it). A pass that read 10 sources or more also counts its own reads alone, and the gate takes the lower share: an outage that starts at a pass is refused at that pass, not only once the window holds nothing but failing reads (up to two passes later after a half-hourly sweep). From Oct 25 to 29 each of the 1261 uploaded passes with 10 reads or more had 84% or more of them good. This makes the gate stricter in one case: a broad degradation that keeps a pass's own reads under 60% (late reads of our pool and deferred reads count as not good, as in the window, since neither gives a fresh say) now refuses every pass until reads recover. Before, good reads still in the window from a half-hourly sweep before the degradation began could carry passes through it. A refusal is exit 3 and the loop goes on; v1 keeps its last good pass, and the `stale` alert opens once the served file is over 15 minutes old. Watch the own share (the commit's good over due) on the first storm-day soak. (Until Oct 30 the reads were kept under their own fetch times and measured from the clock after the reads: each :10 and :40 pass, 15 minutes after a half-hourly sweep, counted the sweep's sources due without their reads, dipped to 37-53% and was refused, 48 times from Oct 25 to 29.)

## Where files go

Public, on the live host. These hold school indexes, days, codes and times only.

- `v1/live/closings.json`.
- `v1/live/opens.json`: explicit "school is open" statements, for the prediction model.
- `v1/live/days/<day>.json`: when each school's status changed that day, for the timeline.
- `v1/live/days/index.json`: lists only the days whose file carries the current stamp, and is written with every upload, even when it lists no day. A finished day is published again from the change log after a restamp or a directory change.
- `v1/live/hold.json`: the hold, a flag and two times. The web never reads it.

The files go up in this order: closings, opens, day timelines, index.

Private state (`out/internal/live/state/`, kept by the state store, [The state](#the-state)):

- `ledger.sqlite`.
- `publish.json` (the `v1` publisher's: the overrides job's, and the reader's in `on`) and `publish.<prefix>.json` (`publish.v1-shadow.json`, `publish.off.json`): the last stamp, the gate's memory, the directory content the last upload was made against, and which day file went up under which stamp and prefix.
- `changes/<day>.jsonl`: every change the map showed, with its source and row key.
  - Each file is rewritten whole and atomically.
  - A torn line from an older copy is skipped and counted.
  - A day leaves the state only once it is more than 45 days old and a durable copy holds it: an evidence database holding its exact bytes (`kept.json`, [The evidence](#the-evidence)), or `changes/durable.json` (`{"through": "YYYY-MM-DD"}`, the push to the private data repository of spec 19, not built yet).
  - A day no copy is known to hold is never pruned, however old.
  - A successor that lost its state takes each day it has no log for from the public day file under the current stamp (lines with `"by": "seed"`), but only when the file's `content_sha256` is its own directory content: two contents can share one stamp (risk R6), and a file built on the other one indexes other schools. Such a file is skipped with a warning in the log. The public timeline then goes on from where it was, rather than starting again at the successor's first publish. The private details of those changes (source and row key) are lost.
- `robots.json`: robots.txt verdicts per origin (the parsed rules, the read time and the file's digest), kept 24 hours.
- `pacer.json`: each pace key's last request start, so a host's Crawl-delay holds across a handoff.
- `exits.json`: the last runs' exits (the `chain` alert).
- `d1.json` (never packed): this run's epoch and its last push's counts. `pulse` (never packed): the watcher's heartbeat.
- `cadence.json`: per source, the start of the pass that last read it, its outcome, and the earliest next read of a deferred or blocked source.
- `morning/<UTC day>.json`: the morning record the prediction model learns from (docs/predict.md, "The model learns on its own"). Per 30-minute UTC slot: the prefixes a pass was shown under, each whole read of a shown pass between 09:00 and 21:00 UTC (rows, rows placed, rows read as no status), the states a pass withheld whole, and the districts its rows named with the days and the status kinds (`?` when a dissenting, unsure or unread row named it). Counts, ids and codes only. Rewritten whole and atomically by every pass; kept 45 days in the state, and every finished day kept for good in the evidence databases ([The evidence](#the-evidence)). A day leaves the state only once a database holds its exact bytes (`kept.json`): when it is over 45 days old, or (never the last 10) while the folder holds more than 16 MB; past 32 MB the oldest go even unkept, loudly. `live state export` and `predict learn` log `morning record: <days> days, <bytes> B (<first day> to <last day>)`. A file that does not read is marked damaged and no day of it is learned from.
- `kept.json`: what the evidence databases were last found to hold, per morning-record and change-log day: the sha256 of the file and the databases holding exactly it; when the first check was, and days the size valve dropped unkept ([The evidence](#the-evidence)).
- `unmatched.json`: names the matcher did not place. Only ever in a private store, never in the Actions cache.
- `good_reads` in the ledger keeps each source's first good read of every UTC hour for 14 days: all the resolver asks of it.

live-read.yml saves only the export (`pipeline/out/internal/live/store`, holding `live-state.tar.gz`) under a key starting `live-state-` (`CACHE_KEY_PREFIX` in `snowlight/live/state.py`): the predict workflow's learning step restores the newest such key, read only.

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

- **Other content:** each public file of the mode's own prefix that carries the deployed stamp is blanked with its day timelines (a shadow reader never touches `v1/`). The stamps checked are read back from the host, so this works after the private state is lost. When a public file cannot be read back, the blank runs under the deployed stamp anyway (it skips a file under another stamp). The pass is refused (`edition`), the alert is set, and the run stops so its successor can build the new directory. If the blank fails, or is refused because it would be stamped ahead of the host's clock, the run tries it again at every check, with no passes, for up to 10 min, then stops with exit `1`. After a blank the state is pushed at once, so the successor pulls the dark lines.
- **Code ahead of the deploy:** the deployed content is the one the last upload was made against, and this build's is new: nothing is blanked; passes are refused until the deploy matches, then one runs at once ([The reader](#the-reader)).
- **The same content under a new stamp:** one pass runs at once, so the new stamp is up within about a minute.
- **A new deployment in progress:** the deployment before it is still the one served, so the last good verdict stands and nothing goes dark. Every push to the site deploys, and a deploy is in progress for tens of seconds. Once it settles, the next check reads it.
- **The edition cannot be read:** the last good verdict stands for 30 min, then passes are refused and the alert is set. A new deployment that has settled and cannot be read gets no grace, because its content may have changed: every public file is blanked under its own stamp, the alert is set, and passes are refused until it reads.

The ingest reacts within one 60 s check of a deploy going live. The host's cache adds its own delay before visitors see the blank: GitHub Pages serves the live files with `max-age=600` (S8-A), so up to 10 more minutes there.

## The gate refused: what each reason means

| Reason | Meaning | What to do |
|---|---|---|
| `edition` | The deployed directory is not the one this build indexes into, or it cannot be read (see above). | Nothing by hand: the run waits, or stops for its successor. If it repeats, see `docs/deployed-edition.md`. |
| `held` | `live blank` set the hold. | `live release --prefix P` (or live-blank.yml, action `release`) once the cause is fixed. |
| `overrides` | The admin's statuses could not be read from the API this pass. | Nothing by hand: the next pass reads them again. If it repeats, check the API (docs/accounts.md). |
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
