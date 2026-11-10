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
- **A successor's first reads.** A process reads a source's rows itself (they live in memory
  only), so a run first reads every source whose last good read held rows, as
  soon as the politeness floor allows (another grid slot, 4 minutes on), whatever its
  cadence. The run's first pass is the next grid mark when its predecessor read one of them
  in the current slot, and also when there is none to read now and the predecessor passed in
  the current slot (most of the off-season: a pass then would find almost nothing due, count
  a share near 0 and be refused). A handoff is so one slot, as before: the last upload at
  about G+1 min, the successor ready at about G+2.5, its first pass at G+5 and its upload
  about a minute later. The gap between uploads is unchanged by design (about 5-6 minutes).
  A source a server's wait or block holds past the next mark is not
  waited for, nor read early when it is free. A source whose last read failed (`error`,
  `partial`) is not read early either: it keeps its cadence, so a throttled host is never
  asked more often than the owner's cadence allows. A first read cut off (`late`) is due at
  the next pass. (Until Oct 30 a successor read a holding source only on its own cadence, so
  a half-hourly source's statuses were dark for up to 25 minutes after a handoff, and its
  first pass at G+2 read nothing and was refused for health.)
- **The handover carry.** A handover never changes what the file shows; only reads and the
  ordinary aging rules do. Every pass writes `carry.json` to the state: the sources whose
  statuses it held, each with the time of the good read holding them and the end of the hold
  it applied (that read's time plus 45 minutes in a window or an alert, 90 otherwise, as the
  pass saw the source), and a key of the resolver's `derived_version` (without the station
  part) and the merge rules. The successor reads it at its start (one line, `carry: <n>
  sources` or `carry: none (<code>)`) and, for each listed source it has not read itself,
  takes the rows the ledger holds present for the rows of that read: their statuses stand
  while both its own G13 bound, measured from that read's own time (never from the
  handover), and the listed end allow, so a carried status never stands longer than in the
  run before, even when the successor counts the source quiet because its first alerts read
  failed (a new process has no alert set to keep yet); and only derivations stored under its
  own version light (another version only darkens). Its own record keeps the earlier end for
  the run after it. A successor whose clock runs behind the run before's, by up to the minute
  a record may be ahead, finds that run's last good reads stamped ahead of its clock: G13
  counts such a read as made now (age 0, never younger), so the source stays held and in its
  own record, and its hold still ends at that read's time plus the bound on the successor's
  clock, the instant a run in step ends it, or sooner when the source's states are withheld
  for a failing resolve and that withholding ends first (below; a read further ahead is not
  held, as before). Its
  own first good read of the source replaces them, as any later read
  does; a read that fails (`error`, `partial`, `late`, a wait or a block) leaves them as the
  run before would have: held until G13 or the listed end stops them. So a source whose last
  read failed, which is not read early, stays shown exactly as long as the run before would
  have shown it, and goes dark at the same instant. Nothing is carried, today's rule (a source
  not read in this process gives only its dissents), when the record is missing (`missing`),
  does not parse (`unreadable`), has another schema (`version`) or key (`key`: new reader,
  matcher, guards, directory edition or rules), is stamped more than a minute ahead of the
  clock (`future`) or is older than the longest hold, 90 minutes (`old`); and a source whose
  ledger read time is no longer the listed one (a good read the record does not know) is not
  carried. The record and the ledger travel in the same pushed state, and only the run's
  end may hand one over: every pass writes the record afresh, unmarked, and `live finish
  --record` (the step after the reader has ended and before the end push, one line `carry
  final: <n> sources` or `carry final: none (<code>)`) marks it final. A successor carries
  nothing from a record without the mark (`not final`): a snapshot pushed while the run went
  on, which a successor pulls when the run's end push failed (it is tried again only at the
  next slot), the runner was lost or the job cut off (no end push), the pushes were hourly
  or refused under the write cap, or the pull fell back to the previous slot. That snapshot's
  pass may have held a closing the run then retracted and held dark while its uploads after
  the snapshot failed or were refused (host writes failing, a refusal for health, an owner
  hold, a rate limit): the host then still serves the snapshot's pass, and nothing on the
  host tells the two apart, so carrying it would show the retracted closing as current. A
  pass whose write fails removes the record, so an earlier pass's record is never marked
  for the run's end. A final record is the run's last completed pass's, uploaded or not. A
  pass cut off or failed after its reads (a kill, or an error the loop logs as a failed pass)
  leaves the record of the pass before it beside a ledger that already holds the cut pass's
  reads: a good read folded in that gap moves the ledger's read time, so its source is not
  carried (the entry check above); a read the ledger could not take moves nothing, but the
  reader holds that source dark from that moment, so it takes the source out of the record
  on disk at once (one line `carry drop: 1 source (observe), <n> left`; a record it cannot
  rewrite is removed, `carry drop: record removed (<error type>)`). A source whose resolve
  failed at the pass is carried as any other and also listed `unknown` with an end (the
  lines read `carry: <n> sources, <m> unknown` and `carry final: <n> sources, <m> unknown`):
  the run before withheld its states (`source_unknown`) at every pass while its resolve
  failed. The successor cannot tell a failure that would recur from one that has passed. It
  resolves a carried source from the derivations the ledger stores, without the read's rows,
  so a step only a read's rows reach (the unmatched-listing queue, a dated row's successor)
  never runs there, and a failure in such a step would not recur until it reads the source
  itself (a row never derived is already withheld, as any undecided row). So it withholds the
  same states until it holds rows of that source from its own read, whose resolve then judges
  at each pass as in any run, or until a read of it cannot be taken in (it then holds no rows
  of it, as the run before would not), and never past the end listed: 90 minutes (the longest
  G13 bound, the age past which a record carries nothing) from the last pass whose own resolve
  failed. A run that only inherited the listing hands it on with the same end, or with 90
  minutes from its own record's time when that is earlier (its clock running behind the run
  before's, by up to the minute a record may be ahead; the run after would refuse a later end
  as `unreadable` and carry nothing), so it never outlives that bound, and the withholding can
  end up to that minute sooner: a pass of the run after inside that minute lights the other
  sources' statuses in those states, which a run in step still withholds, each under its own
  G13 bound; the withheld source's own stay dark. A run lists a withheld source as held no
  later than the end of its withholding, so the run after never lights that source's carried
  statuses once the withholding ends (with its clock behind, a last good read up to that
  minute ahead would otherwise hold it up to that minute longer). A source the run before
  no longer held is listed the same way. The
  withholding counts toward the two-pass alert as any unknown source does. The cost falls on a
  failure that had passed at the run before's last pass: those states stay dark in the
  successor until its own read of the source (a source whose last good read held rows is
  read early, 4 minutes on, unless its last read failed or a hold or deferral stops it) and at
  most until the end. Past the end, a failure the successor has not read again is not withheld, as in a run
  without the record. A state withheld only for a read the ledger could not take is withheld
  for that pass alone, in the run before as in any run, and is not carried (the record drops
  the source from both lists). Then, once the record passes the checks above, the successor
  reads back the closings file the live host serves (one call to our own host's API per process start,
  as the publisher's G12c reads it, never a list server; a refusal it meets, a rate limit
  included, is kept by the host client for the rest of the process) and carries nothing
  when the record's time is earlier than that file's `generated_at` (`behind`; whole
  seconds, as published: another writer's later file, an overrides-only run or a blank),
  when the host cannot be read (`host <error type>`, a timeout or a rate limit's
  `HostRefusedError` included) or when it holds no file (`unpublished`). Stopping the carry
  is always the safe side: today's behaviour. Carrying asks nothing of any list server.
  Nov 5 showed the need: a calm source's 18:25Z read in the run before was not good, so the
  successor (run 42084876453) did not read it early, held nothing of it, and the lit count
  fell 3 to 1 from 18:35 to its calm read at 18:55. That run before recorded its exit and
  then pushed its state at its end, so its record would have been final.
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
- **Exit codes.** A run exits 1 only for a persistent failure: 3 failed passes in a row (a
  pass the live host refused for a rate limit is not a failed pass: it is refused, exit 3,
  and it starts the count again; see [When the live host refuses](#when-the-live-host-refuses)),
  a blank that keeps failing for 10 minutes (counted from the end of a rate limit, which no
  writer can get past), a lost state swap, more than 8 abandoned threads,
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
  grid pass) and `live-read end <cause>` (`until`, `edition`, `overrides`, `host` (the run
  ended while the live host refused an edition blank), or an exit-1 cause such as `passes`,
  `threads`, `state`). `live-read host refused <reason> until <time>` is a notice for each new
  refusal of the live host (2 a run at most, then plain lines), and `live-read host answers
  <time>` a plain line when it answers again, so the soak report can type such a gap as
  `host`. A job still running has no annotations on the API
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
- **Reasons.** A status shows the one reason its winning rows name, rows that name none
  left out (two different reasons: none). When they name none, it shows the one reason the
  rows of the same status since the school's status last changed name (after a real tie,
  the school's own rows only). Wherever every winning row names one reason, it is that one,
  as before Nov 3, 2026; status, times and the winning row never change with it. The
  replay settles a reason the same way, in one list and across stations. The status reader
  reads "power issues" and "power problems" (not after "no"), and "lack of power", as a
  power outage, and a water break, water lines and building problems as causes that are not
  weather: a status that names one of those does not light, as one naming a water main or
  building issues did not. Downed power lines are storm damage, the weather on an ice day,
  and name no cause. The reader, the merge and the replay are part of `derived_version`, so
  a change to them lands on a day the public closings file holds few rows, not in a storm.
- **Plain details** (`snowlight/live/details.py`, Nov 9, 2026). Beside a lit status the panel
  and status notifications say a closed set of details in the site's own words
  (`web/src/copy-details.ts`), never a list's: who (students and staff; staff report, students
  stay home; staff report late), buses (snow routes, emergency routes, paved roads only,
  limited routes, no buses), meals (no breakfast, no lunch, no hot lunch, grab-and-go meals),
  pre-K (no morning, no afternoon, no pre-K), after school (activities, after-school
  activities or evening activities cancelled; childcare closed or open) and offices (closed,
  open). closings.json carries them as codes (`Detail`, `schemas/vocab.py`) in each day's
  `details` column, `[row position, [codes]]` for the rows that have some, and the day
  timelines in theirs, by change; a file written before the column reads as none, and the site
  reads the column only with the panel, so one that does not read shows the status alone.
  `details` on a day timeline is the only top-level field of a stored file the schema test
  lets be absent (`ADDED_LATER` in `tests/schemas/test_schema_examples.py`): timelines written
  before it must still read, as no details. The rules:
  - A row's words are cut into clauses at list marks (a period before a space, a comma,
    semicolon, bar, exclamation mark or line break) and at scoping marks (a colon, a
    parenthesis or bracket, a slash between words, a spaced dash). A detail is read only from
    a clause that is that detail and nothing else, in one of the reader's own patterns; a
    negation only as the pattern spells it ("no" before the program, "will not be served"
    after it). A clause with more in it gives nothing: part of the buses, the day or the
    staff, a place, a route, a time, a hedge.
  - The rest of the row must be plain too, or the row gives no detail at all. Every other
    clause must be a status in a closed set of plain shapes (closed, a delay of some hours, a
    late start, remote or e-learning, an early dismissal, no school), with at most a day, a
    clock time and a weather reason, or a day or a year alone. Any other clause voids every
    detail in the row, wherever it stands: a negation or hedge (no, none, TBD, optional, if
    able), a part of the staff (essential, 12-month, custodians), a school's, area's, road's
    or route's name, a second sentence about the same staff or buses, a contradiction. So
    does a question mark anywhere, a detail set off by a parenthesis or bracket, a colon
    after a detail, and a slash or spaced dash after a detail that another detail does not
    follow. Unknown words never give a detail and never pass as plain; nothing is inferred.
  - None is read from a row that names more than one day (a weekday counts as one day with
    its own date only), that labels part of a day before a colon, whose other words name part
    of a district or a school (the part rule below), that lights two days or two kinds, or
    that lights nothing. A detail says something only beside some statuses: buses, breakfast
    and lunch on a delayed or early-dismissal day, staff reporting and grab-and-go meals on a
    closed or remote day, staff reporting late on a delayed one, pre-K on a delayed,
    early-dismissal or remote day; the others beside any. Evening activities cancelled counts
    only for a row first seen on the day it lights, in every zone of its schools (posted the
    evening before beside the next day's closing, it may be about that evening). Two details
    of one group that cannot both hold (snow routes and no buses) drop the group.
  - A school-day shows what its winning rows state, group by group: the rows that state
    something of a group must state the same, else the group is dropped; a row that states
    nothing of it is left out. A status taken back or replaced takes its details with it.
  - A detail never changes a status, a time or a light: it is read only for a row that already
    lights, after every gate. On the s4 archive (118,950 rows, each read as its own school with
    a read 5 minutes before) the published status columns are byte-identical with and without
    the change: 5,987 rows lit both ways, 0 differences (digest `54d709cc1ad8b870` both ways,
    sha256 over every row's day, status, announcement, reason, shift, clock and manual flag).
  - The reader holds most rows that state a detail: its notes `partial_program` (pre-K or a
    meal not held), `transportation` (bus routes or no buses), `childcare`, `offices_closed`
    and `activities_cancelled` are not notes a counted claim may carry, so a delay beside no
    morning pre-K stays dark as before. Those rows show nothing, details included, until a
    separate change lets the notes a detail fully accounts for light (a lighting change, for
    the critic and the lead). `partial_program` is also a dissent note, so such a row darkens
    another list's status for its school. On the archive 400 distinct texts a status reader
    reads at 0.8 or more are held only by those notes (by note: `activities_cancelled` 198,
    `partial_program` 72, `childcare` 70, `transportation` 27, `offices_closed` 18, the rest
    two or more of them), and 360 of them would show a detail if they lit; of the 5,987 rows
    that light, 4 show a detail. South Winneshiek's Nov 5 row (activities cancelled) is in
    this class: this change leaves it dark.
  - The archive counts (rows whose words state each detail, distinct texts, and rows lit with
    it):

    | Detail | Rows whose words state it | Distinct texts | Rows lit with it |
    |---|---|---|---|
    | students and staff | 11 | 10 | 1 |
    | staff report | 184 | 25 | 2 |
    | buses on snow routes | 29 | 12 | 0 |
    | limited routes | 1 | 1 | 0 |
    | no buses | 67 | 38 | 0 |
    | no breakfast | 25 | 7 | 0 |
    | no lunch | 3 | 2 | 0 |
    | no morning pre-K | 204 | 43 | 0 |
    | no afternoon pre-K | 17 | 6 | 0 |
    | no pre-K | 100 | 52 | 0 |
    | activities cancelled | 826 | 125 | 0 |
    | after-school activities cancelled | 346 | 105 | 0 |
    | evening activities cancelled | 445 | 83 | 0 |
    | childcare closed | 62 | 52 | 0 |
    | childcare open | 115 | 34 | 0 |
    | offices closed | 143 | 40 | 0 |
    | offices open | 8 | 6 | 1 |

    Staff report late, emergency routes, paved roads only, no hot lunch and grab-and-go meals
    are read from no archive row. Hand checks: the first round found false readings where a
    detail's own clause was clean but another clause limited it (a colon or dash before a
    no, a hedge, a part of the staff, an area's buses on snow routes, a road's no buses),
    which the plain-rest rule above now voids, and the synthetic class sweep in
    `tests/live/test_plain_details.py` (every detail beside every qualifier, joined by every
    mark on either side) holds it. The second round checked 474 archive texts by hand (50 a
    detail at a fresh seed, or all of them) against the row words: 474 right, 0 false; the 4
    lit rows are all right. Every row-like fixture and example in the code, tests and docs is
    synthetic: a literal-against-archive scan finds 0 archive rows of two or more clauses or
    25 or more characters.
  - The details reader is part of `live_version`, so this change moves `derived_version`: the
    first run on it refuses the carry (`carry: none (key)`) and reads every stored derivation
    again, and a source not read yet gives only dissents until its first read. It lands, as
    any such change does, on a day the public closings file holds few rows.
- **Part of a district.** A district's row whose words name one part of it (a campus, a
  building, a level such as "Lincoln Elementary" or "high schools", a grade band such as
  "K-8", the preschool, an intermediate school, bus routes, a side of the district, "only")
  lights none of its schools: they only stand against another row's status. "All campuses"
  and "every elementary" speak for every school. The pre-K program counts in every spelling:
  "pre-K", "PreK", "Pre K", "PK", in any case, and with any dash for the hyphen (U+2010 to
  U+2015, U+2212), so "Closed for Pre K students" and "PK: 2 hour delay" light no school, as
  "Closed for pre-K students" lights none. A band such as "PK-5", "PreK-8" or "Pre-K–12" is a
  part as "Pre-K-12" is, and "PK" inside a word ("PKWY") is not the program. The replay and
  the live guards read the words through one function (`names_part_of_district` in
  `snowlight/replays/build.py`), so both see the same text.
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

### When the live host refuses

`LIVE_HOST_TOKEN` is the owner's fine-grained token, so its 5,000 GitHub API calls an hour
are the owner's user's budget. Everything that acts as that user draws on the same budget:
`predict.yml` (the same token), any other token of the user, and agents calling
api.github.com through the agent proxy. On Oct 30 two soak fetches run in parallel by agents
used it up twice (16:55-17:35Z and 18:15-18:35Z): every call of the reader was refused with
HTTP 403 until the hour reset. So agent traffic follows a rule: soak routes never run in
parallel, a fetch over more than 6 hours of history runs alone and only after `GET
/rate_limit` shows core used under 2,000 (stopping when it passes 3,500), and nothing bulk
runs while the host refuses.

- **What is logged.** Every error answer of the live host but a missing file (404) and a
  branch another writer moved first (422) logs one warning: the step, the status and
  GitHub's reason, as a fixed code (`primary_rate_limit`, `secondary_rate_limit`,
  `bad_credentials`, `no_permission`, `forbidden`, `not_found`, `conflict`, `unprocessable`,
  `server`, `other`), the rate counts and reset, the retry wait, the permission it needs and
  GitHub's request id, for example `live host refused read v1/live/hold.json: HTTP 403
  (primary_rate_limit; 0 of 5000 left, used 5000, core, resets 17:31:15Z; request
  40BC:27D4F6)`. The pass's error and its note carry the same text without the `live host
  refused` prefix. GitHub's older words for a secondary limit ("abuse detection") count as
  `secondary_rate_limit`. Never the body's words, never a header the reader sent. Every pass line ends with what the last answer said
  is left, `host 4321/5000 reset 17:00Z`, so a budget that drains shows before it is gone.
- **The wait.** A rate limit names when to ask again: the answer's `Date` + `retry-after`
  when GitHub gives one; else, with no call left, its reset + 1 s; else (a secondary limit
  that names no wait) 60 s, doubling on each repeat, up to 15 minutes. GitHub's times are
  moved onto the box's clock by the answer's `Date`, as of when the answer came (a slow
  answer never shortens the wait), and the wait is kept between 10 s and 61 minutes. Until then the host sends nothing at all, whoever asks (the pass, an edition
  blank, the alerts, the admin's statuses, predict), so a refusal costs one request where it
  cost 2-5 a minute (GitHub warns that calling on while limited may ban the integration).
  The first answer after it logs `live host answers again after N s`; the first answer after
  an error that named no wait (a 5xx, a plain 403) logs `live host answers (after HTTP 502,
  server)`. An answer that succeeds with no call left does not stop the next call: that call
  is refused (one request) and the wait starts from it.
- **The state is kept.** A pass the host refuses is refused (`host`, exit 3): it counts toward
  the `gate` alert (open from the second), and nothing else moves. What is lit, the change
  log, the spike hold and the day files stay as they were, so the first upload after the
  wait carries every change. A refusal that comes after the gate ran (in the commit, from
  reading the branch to moving it) puts the gate's memory back as the pass found it: a spike
  the pass would have released is still pending, so the first allowed pass releases it, and
  the refused streak goes on from its value before the pass. The reads go on at their cadence meanwhile, so the ledger, the
  health window and the held statuses stay current. The run does not stop and hand off: a
  successor would be refused the same way and lose its statuses to a cold start.
- **The pass at the reset.** When the time the host gave is at least a minute before the
  next grid mark, the next pass runs then (once per refusal) and uploads under the heartbeat
  rule. A refusal that outlasts the run ends it as usual (`live-read end until`, exit 3); its
  successor learns of it from its first call and waits the same way.
- **Other refusals** (a plain 403, a 401, a 5xx) keep their rule: the pass fails, and 3 in a
  row stop the run for its successor.
- **`live blank` cannot write either** until the host allows calls again: it fails with the
  reason and the reset time. Run it again after the reset. An edition blank the reader owes is
  tried at every 60-s check and goes out at the first check after the reset.
- **Fewer calls.** A steady hour costs about 88 calls (76 counted, 36 of them writes) where it
  cost 228: the 60-s checks read no public file while the deploy is equal, a read at the
  branch asks with the ETag it has (a 304 is free), a read at a commit sha is never sent
  twice, the files a write sends are kept with their git blob sha (GitHub's ETag), and a
  commit on the head the process made itself skips reading that commit and its hold (both
  are known). Both hold reads of a pass stay. A read at a commit GitHub does not know yet
  (a 404 "No commit found", a replica behind a fresh head) is not kept, and a hold read so
  is not carried on: the next commit reads it again. The 88 counts the reader alone, with
  no admin statuses: on a day with admin statuses each pass also reads closings.json for
  them (a free 304 after the reader's own write), about 100 sent an hour, 76 counted.
  predict.yml's own reads and commits on the same token, and anything else acting as the
  owner, come on top. live-ingest's checks of the public files use the workflow's
  `GITHUB_TOKEN`, which has its own budget.

## The state

The reader's private state lives in the D1 database `snowlight-live-state` of the owner's
Cloudflare account (`state.kind: d1`, `snowlight/live/d1.py`), reached with the repository
secrets `CLOUDFLARE_API_TOKEN` (Account / D1 / Edit) and `CLOUDFLARE_ACCOUNT_ID`, which reach
only the pull, loop and end-push steps (and the evidence job's push, [The evidence](#the-evidence)). No Worker is bound to it: nothing on the internet
reaches it. It is created by the first run (only when the account's list answers and names no
database exactly `snowlight-live-state`), on the free plan with no card.

- **What goes in:** the packed state folder: `ledger.sqlite`, `publish.json` and
  `publish.<prefix>.json`, `robots.json`, `cadence.json`, `carry.json`, `pacer.json`,
  `exits.json`, `changes/`, `morning/`, `unmatched.json`. Never packed: `d1.json` (this run's epoch) and
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
- **The morning tables** (predict-next LIVE-READS): the predict job's serving passes read the
  morning record as it stood minutes before, not the export (written only at a run's end, so up
  to 640 minutes old). Two tables beside the state's own: `morning_head(day, sha256, parts,
  bytes, through, epoch, run_id, shipped_at, prev_sha256)` and `morning_parts(sha256, n, data)`.
  In the idle time after the pass of each :00 and :30 UTC mark, after the state push (which keeps
  the whole idle time it had: the shipment starts on a fresh clock, ends inside the push's 30 s
  margin and is skipped with less than 20 s left, so a slow D1 can never starve the push into a
  false `state` alert) and never after a failed push (the shipped record is never ahead of the
  saved one; the next mark ships), the loop ships each changed `morning/<day>.json`: the day itself from 09:00 to
  21:00 UTC, and before 09:00 the day before (its final file, after midnight). The file's bytes,
  gzip (level 6, mtime 0) in 64 KiB parts, base64, keyed by the raw file's sha256: the parts
  first, then the head, which takes only an epoch at least the one it holds and a `through` at
  least its own (a cancelled run's end, or a successor whose pulled record is behind, is
  refused until it passes), then the heads before D-1 and every part no head names as current
  or previous are deleted. Each shipment is one line, `morning shipped: <day> <outcome>, <raw>
  B raw, <gzip> B gzip, <parts> parts, <rows> rows, <requests> requests, <ms> ms`; a failure is
  one line (`morning ship: <day> failed: <type>`) and never touches the pass or the push; a
  file that failed is shipped at the next mark. Billed in `budget` under the day and under
  `<day>/morning`, which has its own 1,000 rows a day past the 30,000. The rows count in the
  day's own row too, which the state push compares with its hourly switch (20,000 rows) and
  its cap (30,000), so the shipments (about 75 rows a quiet day, at most about 925) bring both
  that much closer, as the holds do. Once the push is hourly, the shipment at the :30 mark
  between two pushes is up to 30 minutes ahead of the saved record; a successor that pulls
  the saved one ships again only when its `through` reaches the head's; a serving pass
  reads the head until s passes its `through`, then codes it `stale`, never a proof. Only the epoch holder
  of a live-read run ships (never an overrides-only run or the box). Measured on SYNTHETIC
  days with the in-memory D1 stand-in: 0.07 MB raw, 1 part, 10 ms; 0.73 MB, 2 parts, 100 ms;
  3.26 MB, 6 parts, 66 ms (gzip level 6); 4 requests a shipment (the latency of the real API
  is not measurable here: the first runs' lines give it). Nothing ships inside a pass. D-1's
  `named` rows after 21:00 UTC (the evening's calls for D) reach the predict job only through
  that final ship after midnight: a serving pass reads D-1's head only when it is at least as
  new as the export's D-1, and proves from D-1 only when a final record stands behind it (the
  head's own version shipped after 00:00 UTC, or an export of a run that went past midnight),
  else `stale (d-1 not final)` (`docs/predict.md`, "The live proof").
- **What predict may read of it:** the two morning tables only, with two SELECTs
  (`MORNING_READS` in `live/d1.py`, `MorningReader`: it finds the database by its exact name,
  never creates it, and sends nothing else; a test holds it); never `chunks`, `head`, `budget`
  or `holds`, whose packed state holds the ledger's secret.
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
  labels' trials and read audit (advisory-sane L1) go here too (kinds `trials` and `audit`),
  and each finished day of the frozen record (kind `frozen`: every chance served and its inputs
  at four freezes a night, docs/predict.md "The frozen record").
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
  and change logs, and only predict snapshots, tables, labels and the frozen record.
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
  schools lit, 397 KB with 15,000; a snapshot 3 KB; a district table 58 KB. The read labels'
  fields (`health`, `stale`, the per-day `by` run) add about 1.3% raw and 4.5% gzip to a
  synthetic 8,000-district storm day named by 400 lists all morning (13.9 to 14.1 MB raw, so
  one such day stays under the 16 MB valve; 1.36 to 1.42 MB gzip, so the 16 MB packed state
  budget still holds about 11 such days; 13 to 57 KB xz in the evidence databases), and 4%
  gzip at 2,000 districts; written per slot they had added 31% raw and 108% gzip. The run
  helps only while lists are steady: in the worst case, every list rotating half its
  districts in and out every slot, each change is written, and the same synthetic storm day
  (8,000 districts in the size test's layout) grows 60% raw (7.0 to 11.2 MB), 21% gzip (0.67
  to 0.81 MB) and from 11 to 83 KB xz, about the per-slot shape (the size test bounds it at
  900 districts). On the 13.9 MB layout above such a day could pass the 16 MB valve on its
  own; the valve then lets older days the databases hold leave first (never the last 10),
  and only past 32 MB does a day leave unkept. Against the packed state's budget, the last
  10 days are never pruned: 10 steady storm days are about 10 x 1.42 = 14.2 MB gzip, past
  the 12 MB `state` alert and under the 16 MB budget; 10 rotating ones (21% over the
  steady 1.36 MB, about 1.65 MB each) are about 16.5 MB before the ledger, over it, so the
  push is refused (`state`, D1Error) and the loop runs on in memory: restart continuity is
  lost, the map is not (its holding rules keep it from a false state). Each push bills two
  D1 rows per 64 KB chunk: about 434 rows at 14.2 MB and 504 at 16.5 MB, so the 20,000-row
  hourly fallback comes after about 46 or 39 such pushes in a UTC day, against about 48 at
  13.6 MB without the read labels' fields. Ten storm days in a row at these sizes have not happened on the live
  map; the lead accepted the risk as documented (advisory-sane Addendum B1.8), and the real
  storm-day sizes are measured after landing. At the worst of
  those (every day of the year at 66 KB, 30 storm days, 15,000-school days included) a year
  is about 46 MB a database, 460 MB in 10 winters. October's real record is far smaller (the
  live export of 4 days of morning record and change log, with the schema-only ledger, was
  60,685 B gzipped on Oct 29, about 8 KB a morning day once xz compressed), and a year of
  300 such days and 65 storm-season days at the sizes above is about 21 MB, 210 MB in 10
  winters. D1's free plan allows 500 MB a database, 5 GB and 10
  databases an account (accounts, state and the two evidence databases make 4). The push's
  size line gives the real growth; past the 300 MB warning, the next winters go to a new pair
  of databases (or the paid plan's 10 GB) before the limit, by a reviewed change. The frozen
  record adds about 25 to 28 MB a database a winter (58 KB a quiet day, 0.5 to 1.07 MB a storm
  day as stored: docs/predict.md "The frozen record"), so with it the warning comes in about
  4 to 6 winters rather than 7 or more.
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

**What `unknown_start` counts.** The `cold` alert's `unknown_start` is the resolver's count of
rows withheld because their posting time cannot be bounded (`Withheld.UNKNOWN_START`): a present
row with no row stamp near its first sighting whose `lo` is unknown from a cold start
(`Start.COLD`). A row starts cold three ways: its list had no good read in the 36 hours before
the read that first held it (a first read, or a reader gap); it came back after 3 hours or more
on a later day; or it is a successor whose predecessor ties with another (the ledger's rules,
`live/ledger.py`). The count is of rows, not of districts, and a row stays withheld as long as it
stands, so the same rows are counted pass after pass. From Oct 27 to Nov 2 the `cold` alert's
`unknown_start` field read 116, then 115 on 5 mornings, then 117, of a `candidates` field of 115
to 161 (CALL-TIME-1's measure). Which of
the three made them is inferred, not measured, until the census: `live state export` (the end of
every live-read run) prints one counts-only line, `ledger cold census:` (read only, never
raising, no ids). It counts the standing rows the resolver withholds as `unknown_start` when it
reaches them: present, `lo` unknown from a cold start, and no row stamp in the 36 hours up to
their first sighting (a row with one is dated by it, never withheld). It splits them into those
first seen with no good read of their list in the 36 hours before, those with one (back after 3
hours, or a tied successor) and those older than the 14 days of good reads the ledger keeps, with
the rows by UTC first-seen day and how many lists hold them. The ledger keeps only the first good
read of each UTC hour, so a row first seen within an hour of the 36-hour edge can count as having
no good read when a later read in that hour was good. Beside it the export prints `read causes:`
(predict-next LIVE-READS, `live/causes.py`; read only, never raising, no ids): per tier (`A`: a
list with an archive audience, `audiences.json.gz`; `B`: a county-proven list with none,
`read-sources.json.gz`; `other`: every other source the state holds), the count of lists by the
cause of their last read (`ok`, `empty`, `stale`, `refused_401`, `refused_403`, `refused_429`,
`http_4xx`, `http_5xx`, `no_answer`, `timeout` for the pass deadline, `deferred`, `partial`,
`error`), those `never read` (no cause kept and no ledger row) and those `dark` (no good read in
45 days, the ledger's `last_good_at`). The cause is kept per source in `cadence.json` from each
pass's pool result and its last health record, since the ledger keeps only the outcome (a 401
and a 403 are both `blocked` there). With status words such a row names its districts `*` (every day) in
the morning record each slot, so the prediction's call time never counts a district it names as
proven silent (docs/predict.md, "The usual call time").

**Self-dated rows.** A row held as `unknown_start` whose status words name a
weekday or state a date is **self-dated** when that day is the school's local today at the
row's first sighting, or tomorrow on an evening read (the reader dates a bare "Closed" read then
the next day, and would at the same local time on a weekday): "Closed Thursday" or "Closed Nov.
5" first seen on a cold start Thursday at 06:00 lights Thursday; first seen Wednesday at 19:00 it
lights Thursday; first seen Friday, or Wednesday morning, it stays held. A Sunday counts as an
evening read only in the evening: "Closed Monday" first seen Sunday at 08:00 stays held, though
the reader dates a bare "Closed" read then Monday, since a list left unchanged over the weekend
may still hold last Monday's row. It is read once, at its first sighting, through every gate,
and lights only when that reading claims the day it was dated by and no day its words do not
name ("Closed Thu & Fri" first seen Friday lights Friday; Thursday is a past day). A weekday
counts in the reader's own spellings ("Weds", "Thurs"); it is not read when the words hold an
explicit date (the date dates the row instead: "Closed Thursday, Nov. 5"), a relative day word
("today", "tomorrow", "next") or a word that puts the status before ("previously", "earlier",
"was"), a weekday as the end or another day ("until Thursday", "reopens on Thursday", "back to
school Thursday", "through Thursday", "instead of Friday", "rather than Friday", "not Friday",
"moved to Friday"), a weekday followed by a day number that is not the day it lights ("Thursday
29" on Nov. 5) or by one with a mark ("Thursday #5") or a letter ("Thursday 5d"), or after one
("Closed 29 Thursday"), a weekday a notice went out on ("Issued Friday", "Released Friday",
"sent out Friday", "notified families Friday", "notified all parents and staff Friday",
"communicated Friday", "confirmed Friday", "Closed Thursday, message Friday", "update Friday",
"decision made Friday", "Friday post", "Friday text", "Friday release", "per Friday's notice";
"Thursday's classes are
cancelled", "Games called off Thursday" and a heading such as "Alert Thursday. Closed Thursday"
name Thursday), a span ("Mon-Wed") or a holiday's
name ("Ash Wednesday", "Black Friday"), or a weekday whose clause ends in a bare "late",
"early", "AM" or "PM" with no status word before it ("Closed Thursday · Friday late", "Closed
Thursday · Friday PM": a late start, or a post's time; "Early dismissal Thursday PM" and
"Thursday late start" light) (`live/weekdays.py`). "Closed Thursday 5" first seen
Thursday Nov. 5 lights. Nor is it read, and the row stays held, when the words:

- give a posting age of a day or more, or one that cannot be read exactly ("(1w)", "• 6d", "2d",
  "1d", "24h", "1440m", "1 wk", "3 days ago", "a few hours ago", "Posted yesterday" with no time;
  a length in days with no "ago", "2 days", counts as one). An age under a day ("2h", "8h",
  "23h", "5m", "an hour ago", "just now") dates the posting to the read's day or the evening or
  night before, as a stamp of the day before does ("Posted Wed 9pm", "Posted yesterday at 9 PM",
  "Updated last night" read Thursday), and the row lights: "Closed Thursday • 8h" first seen
  Thursday at 06:00 lights. The bound is the same from every read, so a feed age that ticks
  between reads ("• 1h", then "• 2h", then "• 8h") keeps a lit row lit, and one that reaches a
  day ("• 1d") darkens it. A delay's length of up to five hours ("2 hr delay", "2 hr. delay",
  "Open 2 Hrs. Late", "90 Min. Delay", "2 hours late", "delayed 2 hours", "Delayed Thursday 2
  Hours") is no age; a longer one, or one after a bullet, a dot or a spaced dash, is ("Delayed
  Thursday • 168h" stays held). An age glued to the word before it, with any mark or none, is an
  age too ("Closed Thursday,5d", "Closed Thursday.5d", "Closed Thursday:6d", "Closed
  Thursday/6d", "Closed Thursday 6:00,5d", "Closed Thursday 6:00:5d", "Closed Thursday 11/5,5d"
  stay held), and a decimal one is what it says, glued to a word's "." too ("Closed Thursday ·
  1.5d", "Closed Thursday.1.5d" and "Posted 1.5 days ago" stay held; "Closed Thursday · 1.5h"
  lights, "1.5 hr delay" is a delay's length); a count in thousands groups before a minute or
  hour unit is its whole number ("Closed Thursday · 2,880 min" and "Posted 1,440 min ago" stay
  held, "· 1,200 m" lights), and "dy" and "dys" are days ("Closed Thursday · 5dys" stays held);
  an age is never the end of another number ("10:30m", "3-6 hours", "$1,500 m"); a glued,
  grouped or decimal one under a day ("Closed Thursday,2h") is bounded as every age is and the
  status rules read the words as before. A count grouped in thousands with a "." or a space
  before a minute or second unit may be a day or a minute and a half and cannot be read exactly
  ("Closed Thursday · 1.440 min", "· 1 440 min" stay held); seconds are read when grouped or of
  four digits or more ("Closed Thursday · 86,400 s" stays held; "the 1990s" is no age); and the
  end of a spaced span of lengths cannot be read exactly ("Closed Thursday · 1 - 2w", "9 to 3
  hours" stay held), unless it is a delay's ("Delayed 2 to 3 hours" lights);
- hold a number that may be a month and day, with a year or not ("1029", "#1105", "115": Jan.
  15 or Nov. 5; "1029-26", "102926", "10292026": Oct. 29, 2026) and is not, in every reading,
  the day the row lights ("Closed Thursday 1105" and "Closed Thursday 110526" light on Nov. 5),
  unless the words just around it make it exactly no date: a bus, route, room or district
  number ("Bus 1029", "Room 104", "USD 105"), a clock time ("at 1030", "1030 am", "0530 hrs") or
  a length ("120 minute delay"); "0530" alone may be May 30 and holds. A day number standing
  alone as the first or the last clause ("29: Closed Thursday", "Closed Thursday, 29"), never
  one of a list of numbers ("routes 2, 3, 4"), holds unless it is the day;
- say the school is open again or back on its schedule ("open since", "reopened", "resumed",
  "back in session", "is in session", "open on time", "classes resume", "normal schedule", "now open", "open again", "back open",
  "lifted", "all clear"), or that the closure or delay is over ("closure over", "is over",
  "(over)", "[over]", "*over*", "- over", "over" ending the words or a clause, "open once more",
  "ended", "expired", "no longer", "delay cancelled", "closing rescinded"), or put the status
  before ("was", "were", "had been closed"): the row may report a closure that has ended. "Closed Thursday, open
  Friday", "Delayed opening Thursday" and "Closed Thursday, over 6 inches of snow" still light;
- void the post or call it an old one, anywhere in the words and its stamps, before the status
  or after it ("Revoked. Closed Thursday", "Closed Thursday rescinded", "Withdrawn",
  "Reversed", "Retracted", "Resolved", "(old)", "Old. Closed Thursday", "Archived", "Past
  event", "Not in effect", "Sent in error", "Nevermind", "Ignore previous", "Please
  disregard"), call it a correction ("Correction: open. Closed Thursday", "Correction - Closed
  Thursday", "(corrected)"), or open with an update heading that says the school is open
  ("Update: open. Closed Thursday", "Update - school open. Closed Thursday"); on the date path
  too ("Closed Nov. 5 (old)"). "Old Mill school closed Thursday" and "UPDATE: Closed Thursday"
  still light;
- name more than sixteen weekdays: a schedule or a list of days, which names no day exactly and
  gives no stamp that can be read (the archive's lit rows name at most ten).

A weekday with a clock time right by it and no status word in its clause is a posting stamp with
no stamp word, in every form the clock time takes: after it ("Closed Thursday · Fri 9:14 PM",
"Closed Thursday | Fri 9:14 PM", "Closed Thursday Sat 7:12am", "Closed Thursday. Friday 21:14",
"Fri 2114"), in brackets or quotes ("Friday (9:14pm)", "Friday [9:14 PM]", 'Friday "9:14 PM"'),
before it ("9:14 PM Fri", "21:14 Fri", "9:14 PM, Friday", "at 9:14 PM Friday"), as a bare or
approximate hour ("Friday at 9", "Friday around 9 PM", "Friday about 9:14 PM"), as a part of
the day ending the words ("Closed Thursday · Friday evening", "Friday late evening"), as a
24-hour time with a leading zero ("Thursday 0900", "Thursday 0514 hrs", "0900-1500"), or past
any run of marks, as long as it is, spaced or glued, after it or before it ("Closed Thursday ·
Friday: 9:14 PM", "Friday | 9:14 PM", "Friday · 9:14 PM", "Friday/9:14 PM", "9:14 PM - Friday",
"9:14 PM (Friday)", "9:14 PM; Friday", "Friday...9:14 PM", "Friday::9:14 PM", "Friday _9:14
PM", "Friday,.9:14 PM", "Friday)/9:14 PM", "9:14 PM-- Friday", "9:14 PM– Friday", "5:14 AM -----
Thursday", "Thursday .......... 5:14 AM"; one rule, swept over every run of up to three of 41
marks and 34,428 longer runs either way round). Every Unicode space is read as a space (a
no-break, thin or ideographic space between "Thursday" and "5:14 AM"). A clock time past a run
of marks
is only ever a stamp's: by a weekday with a status word it is that weekday's time only when a
start or a dismissal owns it ("Early dismissal Friday: 1:30 PM" lights Friday), and otherwise a
clock time with no day (below: "Closed Thursday @ 9:14 PM" and 'Closed Thursday "9:14 PM"' read
at 06:00 stay held). A span of hours ("9 AM - 3 PM", "8:30-3:15", "10 AM to 3 PM", "9 AM until 3
PM", "(9:14-9:30 PM)") is a weekday's hours only when a status or an event word stands in that
weekday's clause or around the span: "Closed Thursday · Friday closed 9 AM - 3 PM", "Closed
Thursday · Friday 9 AM - 3 PM closed", "Early dismissal Friday 1:30-2 PM", "Closed 6 a.m. to 8
p.m. on Friday" and "6 a.m. to 8 p.m. on Friday: closed" name Friday, while in "Closed Wednesday
· Thursday 9 AM - 3 PM", "Closed Thursday · Friday 9 AM - 3 PM", "Closed Thursday · 9 AM to 3 PM
on Friday" and "Wednesday closed, Thursday 7:45-2:45" the second weekday is a stamp, read as one,
and the row lights neither the stamp's day nor, read on it, the day before. The same holds
for a clock time or a span further on in the weekday's clause, or in the clauses past the marks
that end it, read on over each clause and each run of marks to the first with a status or event
word (or the next weekday, or 400 characters past the marks), either way round, whatever words with no status or
event word stand between ("Closed Wednesday · Thursday hours 8:30-3:15", "Thursday office hours 9:00-11:00", "Thursday:
from 9 AM to 3 PM", "Thursday | from approx. 9 AM - 3 PM", "Thursday hours: 9 AM - 3 PM", "9 AM
- 3 PM: hours Thursday", "8:30-3:15 hours on Thursday", "Friday: between 9 AM and 3 PM",
"Thursday posted 5:14 AM", "Thursday hours 5:14 AM", "Thursday | hours (8:30-3:15)", "Thursday |
from (9:14-9:30 PM)", "Thursday: hours - 8:30-3:15", "Thursday | office | hours 8:30-3:15",
"(8:30-3:15) | hours | Thursday", "between 9 and 3 hours Thursday"), for bare hours ("Thursday: 9
to 3", "9 to 3 on Thursday", "Friday: 9 - 3", glued to the marks too: "Thursday:9 to 3",
"Thursday...between 9 and 3", "Friday!#9 to 3", "Friday _9 to 3", "9 to 3_ Thursday"; never "0-5
degrees" or "2 to 4 inches"; "9 to 3 in effect" and "9 to 3 students report" are hours, and a
spaced dash in such a span ends no clause: "Thursday: 2 - 3 hour delay" lights), for a bare
number of one or two digits on either side of the marks, glued or spaced, with words after it
or none, after the "." a weekday ends with too, with a mark glued before it before the
marks, and with a line break in or by the marks, as a clock time past them is read ("Thursday:
45" and "45 · Thursday" on two lines; "Thursday...9", "Thursday ... 9", "Thursday: 9 | info", "Thursday.45", "Thursday. 60
info", "10.Thursday", "9:: Thursday", "3_ Thursday", ":9 · Thursday", "#12 :: Thursday", "$9 ·
Thursday": unreadable; a clock time, a date and a count with a delay's length unit are read as
before: "Thursday: 2 hour delay", "Thursday. 2 hour delay", "Closed Thursday. 45 schools",
"Closed Wednesday · 10:30 · Thursday"), for a 24-hour time with a leading zero
before a run of marks ("0900: } Friday"), for a time cut short after the weekday ("Friday: 9 a")
and for a span cut short or written with an "h" on either side ("9a-3p >> Friday", "Thursday
time 8h30-15h15"): one rule, swept over 21,888 shapes and the round 7 critic's 96,921 (0 that
light), every run of one to three of 33 marks either way round, glued or spaced, by seven forms
of span (448,448 shapes, 0 that light), and 119,952 shapes of a weekday, marks, a connector
word, more marks and a span (0 that light). With a status word in the weekday's clause such a
row is read as before ("Closed Thursday:9 to 3" and "Thursday | closed | 8:30-3:15" light
Thursday). A weekday glued to a "_" ("5:14 AM| . _Friday") names no day: the row is held. Words that name hours
are no status ("Thursday school hours 8:30-3:15", "Thursday open hours 9 to 3" are stamps), and a
single clock time something runs until is no stamp ("Friday Evening: help desk available until 8:30 PM"
names Friday). A span of hours gives no time a row went up at, so a stamp with one is
unreadable and keeps the hold ("Closed Thursday · Wednesday 9 AM - 3 PM" read Thursday). A
weekday right before a stamp word that starts its clause is the stamp's day ("Closed Wednesday ·
Thursday posted 5:14 AM", "Closed Wednesday · Thursday. Posted 5:14 AM" are "Posted Thursday
5:14 AM"; "Closed Thursday · Friday posted 9 PM" read Thursday stays held); with a word before it
in its clause it is the day the row is for ("Closed Thursday, updated 5:00 AM", "Snow day
Thursday. Updated 5:00 AM" light). A stamp is never a
day the row lights,
and on the weekday path it bounds the row as "Posted Fri 9:14 PM" would (below), so "Closed
Thursday · Fri 9:14 PM" read Thursday stays held and lights neither Thursday nor Friday, while
"Closed Thursday · Thu 5:02 AM" read Thursday at 06:00 lights. A bare hour is after the read
when it is so in the morning or in the evening. A status word in its clause makes it a day the
row is for ("Early dismissal Thursday 1:30 PM", "Early dismissal Thursday (1:30 PM)", "Thursday
10 AM start"), and so does a word that makes the clock time when the school starts, opens,
closes or lets out, or a notice takes effect ("Opening at 10 AM Thursday", "Closing at 1 p.m.
Thursday", "In effect at 5 p.m. Saturday"), a report or an arrival only with who it is for or
with a status or event word ("Staff report Thursday 9 AM", "2 hour delay Thursday, staff report
9 AM"; "Closed Wednesday · Thursday report 5:14 AM" and "Thursday arrival 7:45 AM" are stamps).
A word that is no status word ("begins", "in effect", "effective", a report or an arrival,
and the start, opening and dismissal words the status reader reads no status from: "dismiss",
"starting", "opened") owns only a single clock time in the weekday's own clause with no mark
between the weekday, the word and the clock time, wherever the word stands, and never a span of
hours or a clock time a mark parts from the weekday, a clause mark or a stamp's ("=", "#", "»"):
"Closed Wednesday · Thursday | begins (8:30-3:15)", "Closed Wednesday · Thursday in effect 9 to
3", "Closed Wednesday · Thursday: staff report 9:14 PM", "Closed Wednesday · in effect Thursday:
9:14 PM", "Closed Wednesday · 9:14 PM: Thursday begins", "Closed Wednesday · Thursday: 9:14 PM
effective immediately", "Closed Wednesday · Thursday = begin 9:14 PM", "Closed Wednesday ·
Thursday | dismiss 9:14 PM", "Closed Wednesday · Thursday | starting (8:30-3:15)", "Thursday:
students report 10 AM" and "Closed Thursday · Friday in effect 9 AM - 3 PM" are stamps, while
"Closed Wednesday · Thursday begins 9:14 PM" and "Closed Wednesday · Thursday begins around 9:14
PM" name Thursday. "At" or "@" between such a word and the clock time changes none of this
("Closed Wednesday · Thursday: started at 9:14 PM", "Closed Wednesday · opened at 9:14 PM,
Thursday", "Closed Wednesday · Thursday started at 9 AM - 3 PM" and "Closed Wednesday · Thursday
opened at 9 to 3" are stamps), and a "~" is a mark there as anywhere by a weekday ("Closed
Wednesday · Thursday begins ~ 9:14 PM" and "... begins ~9:14 PM" are stamps, as "Thursday ~
9:14 PM" is). The one such word that owns a clock time past the marks is a dismissal with "at"
or "@" right before a single clock time the status reader reads a dismissal at, 8 a.m. to 1:30
p.m. ("Thursday: dismiss at 1:30", "Thursday | dismiss @ 1:30" light; "Closed Wednesday ·
Thursday: dismiss at 9:14 PM", "... dismiss at 7:30" and "... dismiss at 8:30-3:15" are
stamps). So does an event named next to it ("No 8 AM Mass Thursday",
"10am Thursday worship canceled") or a span of hours a status word is said with ("6 a.m. to 8
p.m. on Thursday: closed"); a part of the day as a heading ("Thursday Afternoon: Closed") is no
time.

A weekday the row lights whose clock time, right by it or in its clause, is after the read on
its day, and that no such word owns, keeps the hold: "Closed Friday 9:14 PM", "Friday closed
9:14 PM" and "School closed Fri 9:14 PM" read Friday at 06:00 may be last Friday night's post,
and "Closed Thursday · Fri 9:14 PM closed" read Thursday lights neither day. "Closed Friday 5:30
AM" read Friday at 06:00 lights, and "Closed Friday 6 AM" read Thursday evening, whose Friday
may be last week's, stays held.

A night-before stamp of either kind dates the row by the day it names on an evening read:
"Thursday closed. Wed 9:14 PM", "Closed Thursday | Wed 9:14 PM" and "Thursday closed (Wed 9:14
PM)" read Wednesday at 21:30 light Thursday, as "Closed Friday. Posted yesterday Nov. 5 9 PM"
read Friday morning lights Friday. On the date path the date names its day and such a weekday
bounds nothing.

A date is stated as a
month and day, a numeric or an ISO date in no other year ("Closed Nov 5, 2025" and "Closed Nov. 5
'25" stay held), and the same end words and spans keep a date from dating its row, today's date
too: "Closed until Nov. 5", "Classes resume Nov. 5", "Closed through Nov. 5" and "Closed Nov.
5-6" read on Nov. 5 stay held.

A weekday that may be part of a proper name never dates its row, and the row stays held: a
weekday the row's name holds, or the directory name of a school the row lights or of the record
the match chose ("Friday Harbor SD"); in words with both cases, a weekday followed by a
capitalised word that is no status, date, time or connective word ("Friday Harbor schools
closed", "Closed for Friday Harbor district", "Monday Creek campus closed", "Sunday River routes
closed"), or by a capitalised status word that also names a school ("Friday School closed",
"Monday Learning Center": School, Schools, Academy, Preschool, Learning, Day, Early); in words of
one case, where case tells nothing, a weekday followed by any such word ("closed friday harbor",
"FRIDAY SCHOOL CLOSED"); and a weekday after a place word ("St. Friday", "Lake Monday").
"Closed Friday due to weather", "CLOSED FRIDAY DUE TO SNOW" and "Closed Thursday / No Activities"
still name their weekday.

A row's own dates bound it. Its row date, when it has one (a row stamp too old to date it, or a
date-only row date such as Gray's), and each stamp in its words ("Posted 10/29", "Updated Oct.
29", "(updated Oct 29, 2025)", "Updated 2026-10-29", "Posted Wednesday, October 28", "Updated
Wednesday 9:00 PM", "Updated last night", "Posted yesterday at 9 PM"; a date with no year is the latest such date, a weekday
alone the latest such weekday when that is the read's day or the day before) must fall after the same weekday a week before the day it lights
and not after the read's local day, on the weekday path and the date path alike: "Closed
Thursday. Posted 10/29" read Thursday Nov. 5 is last week's and stays held, "Closed Thursday.
Updated Nov. 4" lights. On the weekday path a stamp in the words must also fall on the read's
local day or the day before, as a weekday-only stamp must: "Closed Thursday. Updated Fri 10/30",
"Posted Oct 30", "Updated 10/31 6:00 AM" and "Updated Nov. 3" read Thursday Nov. 5 may be of a
post about the Thursday before and stay held (`STAMP_LATEST_BACK`), while "Closed Nov. 5. Posted
10/30", whose date names its day, still lights. A stamp of the read's day at a clock time after
the read ("Closed Thursday. Updated 11/5 6:30 AM", or "Closed Thursday · Thu 5:02 AM", read at
04:30), or of the day before at a time after the read in the zone it states ("Updated 11/4 11:30
PM PT" read at 23:00 Pacific), is unreadable, since it may be the same weekday's a week before,
and keeps the hold. A stamp's clock time is read past the "." that ends its weekday or date
("Updated Thu. 7:00 AM", "Updated Thu., 7:00 AM", "Updated Thu. Nov. 5 7:00 AM", "Updated Nov.
5. 7:00 AM" read at 06:00 stay held, and light read at 08:00). On the weekday path a clock time
that gives no day, in a stamp ("Updated 7 AM", "Updated noon", "Posted this evening", "Posted
tonight") or standing in its own clause with no other number and no word that makes it the
time of a status or an event on its day ("Closed Thursday · 7:14 AM", "Thursday: Closed. 7:14
AM", "Friday: Closed 9:14 PM", "Closed Thursday. 7:14 AM update", "Closed Thursday. Released
7:14 AM", "Closed Thursday | Fr 9:14 PM", "Closed Thursday. 7:14 AM upd", "7:14 AM revised",
"7:14 AM by admin", "7:14 AM report"), that is
after the read on the
read's day keeps the hold: the row went up at that time on an earlier day, and which day it
does not say, as with "Posted Friday" read Thursday. So "Closed Thursday. Updated 9:14 PM" read
Thursday at 06:00 stays held, as "Closed Thursday 9:14 PM" and "Closed Thursday (7:14 AM)" do,
and read Wednesday at 21:30 it lights Thursday; "Closed Thursday. Updated 5:30 AM" and "Closed
Thursday · 5:14 AM" read at 06:00 light. A clock time a start, an opening, a span of hours or an
event owns, or one in a clause with another number or with a start, an opening, a delay, a
dismissal, a closing time, a span's end, a bus, a staff call, an office, a meal, a stream, a
schedule, a school, a decision still to come or an event ("offices open 8 AM - 4 PM", "Buses run
2 hours late, 10 AM start", "front office at 9:50am", "10:50 a.m. for Delta Elementary",
"decision by 6:45a", "Livestream only at 10:15"), is no posting time (the lead's ruling, round 6 S1: this hold stays,
knowing its cost: a night-before row that gives only a clock time, read the next morning, is
missed; 3 rows in the archive). The date path reads no such stamp: its date names its day (the
lead's ruling, round 6 S5: the round 4 bound stays on dated rows; reading clock-only stamps
there would hold 536 today and 207 tomorrow rows in the archive). A row date that cannot be read, one after the read, and a stamp that
carries a day it does not read exactly ("Updated last week", "Posted 3 days ago", "Posted
yesterday" with no time, "Posted Feb. 30", a weekday that is not its date's, and a weekday alone two or more
days back, which may be any week's or after the day the row is for: "Posted Friday", "Updated
Saturday" or "Posted Mon" read Thursday) keep the hold, while "Closed Thursday. Posted Wed 9pm"
and "Closed Thursday. Posted Thu" read Thursday still light; an age in a stamp ("Updated 2 hours
ago") gives no day and is bounded as every age is; a stamp with no day ("Updated 5:30 AM" read
at 06:00, "Posted by the district") bounds nothing. A stamp is read over all the words the weekday rule
leaves out as the stamp: from its stamp word to the first ".", ";" or "|", across lines, with a
date or time that runs on past a "." read whole ("Oct. 29", "6 a.m."). Words in it that give no
day are passed over ("Posted by the district on 10/29", "Updated per district, 10/29", "Updated"
and "Oct 29" on two lines all read Oct. 29; "a 2 hour delay", "two hours later" and "snow day"
give no day), and any number, month, weekday or relative day word in it that it cannot read as
part of a date, a time or a day makes the stamp unreadable ("Posted by District 5", "Updated by
staff, 29 October"): the row stays held. What a "." leaves in the status words is read by the
status rules, and a date there in a form they do not read ("29 October", "10-29", "10.29" or
"29.10", "20261029", a day number in parentheses "(29)", a month alone) or a posting age of a
day or more ("3 days ago") names no weekday or date for this rule either: "Closed Thursday. Posted by Supt. Lee 10-29" stays held. A weekday or
date inside a stamp never names the day the row is for. A page's own stamp (page-scoped or unmarked) still dates nothing and is no part
of a key (D2), but when it reads as a day on or before the same weekday a week before, the page
was last changed then and so was the row: it keeps the hold.

Some rows still light though an earlier-day reading of them exists; the lead accepts each as
listed (round 6 S4), every one within the bounds above or the residual below: a weekday-only
stamp of the day before may be a week earlier ("Closed Thursday. Posted Wed 9pm" read Thursday
at 06:00, "Updated Tue 9:30 PM" read Wednesday at 21:00); a stamp of the read's own weekday read
on it ("Closed Thursday. Posted Thu" read Thursday at 06:00, "Thursday closed. Wed 9:14 PM" read
Wednesday at 21:30); bare and repeated rows ("Closed Thursday again", "Still closed Thursday",
"Closed Wednesday and Thursday": the cold-source residual below); ages under a day ("Closed
Thursday · 0.9d", "Updated 1 hour ago"); and date-path rows, whose date names their day. A row
that names two weekdays, or a weekday and a date, with no status word in the piece of the words
one of them stands in ("Thursday: Closed | Friday: TBD", "Closed Thursday | Wednesday") is not
held for that alone: holding such rows would hold 203 lit archive rows (175 when only the day
it lights must have one), past the 30 the lead set, and the lead rules later. The same goes for a
status word between two weekdays with no clause mark ("Thursday closed Friday 9 AM - 3 PM", or
"Thursday closed [Friday 9 AM - 3 PM": a "[" ends no clause), which lights both days, with the
reader's reading of the span (round 7 critic S6, with the 203-row measurement). So do, for the
same reason, an event word or a status-time word that owns a clock time in the second weekday's
clause, which the first weekday's status then lights (round 7 second critic S4, read Thursday at
06:00: "Closed Wednesday · Thursday classes 8:30-3:15", "Thursday school day 8:30-3:15",
"Thursday lunch 11:30", "Thursday breakfast 7:15 AM", "Thursday board meeting 6 PM", "Thursday |
open (9 AM - 3 PM)"; read Wednesday at 19:00, "Closed Wednesday · Thursday buses 6:45 AM"),
and a span of hours with a degree or inch mark after it ("9 to 3° Thursday", '9 to 3" Thursday':
read as no span of hours). Round 8 leaves these, each lit at db3f087 and at the round 7 head: a
word that is no status word owning a single clock time in the weekday's own clause with no mark
between, the lead's ruling ("Closed Wednesday · Thursday begins 5 a.m.", "Closed Wednesday ·
5:14 AM staff report Thursday": 73 of the round 7 last critic's 3,000 owner shapes light through
the resolver, each such a shape, and 11 lit archive rows hold a weekday, such a word and a clock
time in one clause); a clock time or a span glued to a word, read as no clock time, and a span
after a quote mark or a number sign ("Closed Wednesday · Thursday ·staff arrival5 a.m.",
"Thursday .reports21:14", "Thursday ;: xbetween 9 and 3", 'between 9 and 3" info ·@ Thursday',
"Thursday(= info #9 to 3": 33 of those shapes, which light with the owner word taken out too,
and 0 lit archive rows of that form); a span past the marks with "regular", a status word, on
the way ("Closed Wednesday · Thursday# regular families (9 AM - 3 PM)": 19 of the critic's 3,000
far shapes, 0 lit archive rows); a span or a bare number more than 400 characters past a
weekday's marks ("Closed Wednesday · Thursday | " and 82 words, then "(9 AM - 3 PM)"): 37
archive rows hold a weekday, its marks and a number that far on, 6 of them lit, all on the date
path and none on the weekday path the reach bounds; a bare number one clause away from a
weekday ("Closed Wednesday · 9 · info · Thursday": 2 lit archive rows hold a bare number two
clause marks before a weekday, both on the date path, none on the weekday path); and a count of hours right by a weekday's marks, with or
without a delay word, read as a posting age under a day and bounded as every age is ("Closed
Wednesday · Thursday|2 hrs", "Closed Wednesday · Thursday: 15 mins ago": 49 of the critic's 3,000
bare-number shapes, 88 lit archive rows; the lead rules on these). The round 8 second critic's
also stay, each lit at db3f087 and at the round 7 head with 0 lit archive rows: a number glued
to a mark or a word, or a word between it and the weekday's marks, outside the bare-number rule
("Closed Wednesday · #45 Thursday", "Closed Wednesday · Thursday: No 45", "... Thursday: no.
45", "... Thursday: v45", "... Thursday: 45x": 48 of 48 function-level shapes of each light; 0
archive rows hold a "#" or "$" glued to a number before a weekday); and a spaced span of bare
hours followed by a count word that is a status word ("Closed Wednesday · Thursday | 2 - 3
schools", "... Thursday: 9 - 3 buses": 1,008 function-level reads newly lit against the round 7
head, each with such a word in the weekday's clause, as "Thursday: 9 schools" was lit there; 0
archive rows; the lead's awareness). Two more stay, lit at all three heads with 0 lit archive
rows: a bare hour after "at" past the weekday's marks with a word between, read as no clock
time, so the row reads as "Closed Wednesday · Thursday: info" does, an owner word there or not
("Closed Wednesday · Thursday: started at 9", "... Thursday: info at 9": 80 of the critic's 88
reads of each such word after the weekday; 16 archive rows hold a weekday's marks, a word and a bare
hour after "at", and the one of them lit has a status word in its weekday's clause); and a line
break with no mark between a weekday and a clock time, a span or a bare number, or a clock time
before marks and a line break ("Closed Wednesday · Thursday", then "5:14 AM" or "45" on the
next line; "Closed Wednesday · 5:14 AM |", then "Thursday": 86 of the critic's 504 line-break
reads; 0 of the archive's 118,950 reader texts hold a line break).

A row whose words may be older than its first sighting is not self-dated unless the ledger can
bound them. Every key the ledger adds keeps `earliest`, the earliest its words may have been on
the list (a nullable column a ledger written before gets on open, so the schema version and the
ledger stay): its own first sighting; for a key back on the list after 3 hours or more (gone or
not), the earliest the ledger saw it before; for a successor (new words in a listing, tied or
not), the earliest the ledger saw every key of that listing it replaced, since it may re-render
their words; and, on a source the ledger read before, for a key the ledger cannot link to what
it replaced (no predecessor, never seen before), whether it is dated from the read before or not
(part of a list moved to another section on a warm read re-keys without churn: the moved rows
are dated as new by their window, a separate rule this one leaves as it is, but their tied
successors and their returns on a later day take their `earliest`), and for a key with no known
posting bound on a cold read (more than 36 hours after the source's last good read, successors and returning
keys too: their words may have gone up any time in the gap), the earliest of that source's
previous good read and every sighting the ledger holds of it. When any of those sightings is of
a row written before the column, `earliest` stays unknown. The resolver bounds a successor by
its predecessor the same way when it settles how the successor is dated (both readings, and the
widened one, carry the earlier sighting), so a row held on a cold read and re-worded on the
next warm read stays held. A row is self-dated only when its `earliest` dates it to the same
day, as if it had never left the list. "Closed Thursday" first seen last
Wednesday evening, off the list for a day and back this Thursday morning stays held; first seen
this Wednesday evening, off for six hours and back Thursday morning, it lights Thursday. A list
re-identified on a cold read after a reader gap (a renamed section header gives every row a new
key), any new row on such a read and a listing whose words changed during the gap ("2 hour
delay" before it, "Closed Thursday" after it: it may have gone up any time in the gap, a week
ago too) stay held: the read before the gap is over 36 hours earlier, so it never dates the row to the
same day. A churn read (`churn`, warm) is never self-dated at all: the list it replaced may hold
the same rows under other keys, or the page may be an old copy re-served from a cache, and
nothing bounds when such a row went up. A row written before the column (`earliest` unknown) is
never self-dated. A new ledger (a first run, a lost file, a new schema version) reads every
source as never read, so no row whose `earliest` falls in the ledger's first 7 days of watching
(its earliest kept good read of any source, `Ledger.watching_since`) is self-dated: a source's
first read, and every row descended from it (its successors, tied or not, and its returns); a ledger in use
keeps 14 days of good reads, so it watches long enough from the start. The one class this leaves
is a source a ledger that has watched for a week has never read (new to the registry, or failing
until now), read cold for the first time while it still shows a row from an earlier week that
names today's weekday: the reader cannot tell, and the day the row names, today or an evening's
tomorrow, bounds it. That first read carries on through the same local day as built (the
lead's ruling): a warm read later that day carries the row on, and a tied successor that
escalates it ("2 hour delay Thursday" first, "Closed Thursday" an hour later) lights too, since a
successor's `earliest` is its predecessor's first sighting, the same day. It never outlasts the
day the words name. The live ledger's own counts find such reads rare: in the four consecutive
live reads up to Nov. 7, 2026 that round 4 measured, every list group counted "never read 0",
and of the 193 rows the cold census held as `unknown_start`, 0 came from a first read of their
source or a gap.

A self-dated row gives no announced time, and merge takes it as posted at an unknown time: when
it is the newest word for a school and day, every other row for that school and day counts as
posted at the same time, so an earlier retraction or a different status still darkens it. It
never lights a day it does not name and never outlasts that day. The resolver counts such rows as
`weekday_dated` or `date_dated` (they leave `unknown_start`) and by why they were held
(`self_dated:unknown_start`). The `cold` alert adds `self_dated:unknown_start` to its
`unknown_start`, since their posting time is as unknown as before, so it reads as it did before
the rule; the cold census still counts them too, since it reads the ledger's dating and not the
words. A row date that does not exist ("2026-02-30 12:00" in a board's day field) keeps the hold
and never stops the pass. A board row keeps its board rule (G5), and a row the ledger holds at a
known posting bound over 36 hours (`interval_too_long`, a re-worded successor dated from its
predecessor's posting) is not self-dated. A row whose reading carries a note other than
`undated` and `unread_words` keeps its `note` hold: "Closed Thursday / No Activities" names its
weekday, but the reader's `activities_cancelled` note holds it, self-dated or not.

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
3. It empties every day timeline the day index lists, empties the index, and publishes an empty season file ([The season counts](#the-season-counts)).
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

- The next pass publishes again, and every day timeline and the season file are published again.
- A status the hold darkened lights again only while a source still lists the row that lights it. Merge keeps a row through its day after the source takes it down, but not for these school-days: they stay dark until the day ends.
- A status a source still lists lights again, and the timeline shows it from the release on.

So to remove one false status for good, fix its cause first: the source takes the row down, or a fix to the code, the matcher or the registry stops it from lighting. Then release. If the cause cannot be fixed, keep the hold until the day ends.

Exit `0` means every prefix is held and every file is blanked. Exit `1` means the host could not be written, so try again. Exit `3` means the hold is set but a file was not blanked, because its blank would be stamped more than 60 s ahead of the host's clock. Fix the clock. The running ingest blanks that file as soon as the clock allows.

## The season counts

Owner decision, Nov 9: each school's panel says how many days it was closed, delayed, remote or dismissed early this school year, exactly, never inflated, and says when counting began (`snowlight/live/season.py`).

**The rule.** Only a final day timeline counts (`final: true`: the day is over everywhere); a day in progress never does. Each school on it counts once, under the status its run of changes ends on: what the map showed at the end of the day, after any correction.

- A status taken back before the day ends (retracted, corrected away, or taken down that evening) counts nowhere.
- A status changed during the day counts once, as the one it ended as.
- The admin's manual statuses are in the timelines like any other and count the same.
- A status the emergency hold darkened is no part of a timeline, so it never counts.
- The school year runs July 1 to June 30. The file counts the days from `since` through `through`: `through` is the last day over everywhere when it is built, and `since` is July 1, or the later day counting began.

**Directory editions.** A timeline's school indexes point into the edition it was built from. Each day is turned into NCES ids with that edition's own ids, and the counts are placed into the current edition by NCES id, never by position. A day whose edition's ids are not known is left out whole, and counting begins after it. A school the current edition does not hold is left out.

**The ledger** (`season.json` in the state) keeps each counted day's final statuses by NCES id. The reader puts a day in once an upload has carried that day's final timeline, so a day whose change log has left the state, or that was built from another edition, still counts, mapped by id. A final day the ledger does not hold yet is built again from the change log on the next pass, even when its public file is already final (the first pass after this landed fills the ledger from the change log's days, up to the 30 a pass rebuilds). `since` is set when the ledger is first written: the oldest final day it was filled with then, or, with none, the first day not yet over. A ledger lost or unreadable starts again with a later `since`, so the panel then says the later day; it never claims days it does not hold. Rebuilding from the same days gives the same bytes. The overrides job (`reader` off) neither writes the ledger nor publishes the file.

**The file**, `live/season.json` under the mode's prefix (schema `schemas/live-season.schema.json`): the school year, `since`, `through`, the directory stamp and content digest, and one row per school with a day counted, in school order (`gaps` as in closings.json, then the four counts). It goes up with an upload when its bytes differ from the last one published under the prefix: once a day as `through` moves on, and when a day's counts change. Every blank (an edition change, the emergency stop) publishes it empty (`content_sha256` null), and the next upload after the blank or the release puts it back.

**Sizes.** On the public final archives of Oct 26 to Nov 6 (one edition, 10 final days, 293 final school-days with a status): 155 schools listed, 1,954 B raw and 445 B gzip, built in under 1 ms, the same bytes on a rebuild. 113 of the 293 school-days ended dark and are not counted, 41 of them taken down after 3 PM on the school's clock. With synthetic counts: 15,000 schools listed, 154 KB raw and 38 KB gzip; every school of the directory, 1.18 MB raw and 191 KB gzip. The ledger (synthetic NCES ids drawn at random, which compress worse than a district's run of ids): one day of 15,000 schools is 225 KB raw and 94 KB gzip, 30 such days 6.8 MB raw and 2.8 MB gzip in the packed state.

**The panel** (`web/src/data/season.ts`, `web/src/copy-season.ts`): the school panel reads the file when it opens, from the live root beside the closings (at most once in 10 minutes for every panel opened), never with the page. It shows one line, "This school year: closed 2 days, delayed 1.", and, when counting began after July 1, "This school year, since Oct 27: closed 2 days, delayed 1.". The line names each status with a day, in the order closed, delayed, remote, dismissed early. It shows nothing when the school has no day counted (a school the map does not cover could have closed), when the file is missing, does not read, is empty, is for another directory, or is stale: its `through` older than the last day over everywhere an hour before now. A past day on the map (a replay) shows no line.

## The share cards

Owner decision, Nov 9: the school panel's Share gives a picture of the school's day, made to post, as well as the link (`web/src/ui/DetailPanel.svelte`).

**The options.** Share opens three: **Story** (a 1080 by 1920 PNG), **Post** (1080 by 1350) and the link (`?school=ID`, unchanged). On a phone that can share files (Web Share with files: iOS Safari, Android Chrome) a card opens the system share sheet with the image, the link and a short text (the school, its status with the day and times, or its chance with the day, and as of when: "Lantern Hill High: Closed today · Monday, Jan 12. As of 6:55 AM."), so Instagram, Messages and the rest take it. Anywhere else the image is saved and the link copied, and the button says so for a moment. The link option is **Share link** on a phone with a share sheet (a coarse pointer and Web Share), which opens the sheet with the link alone, as Share did before the cards (the link copied where the sheet will not open); **Copy link** anywhere else. Nothing asks for a permission. Story and Post show only where a tap makes a card, by the same rule the card's model is made by (`web/src/app/share-offer.ts`), read before the cards' code loads and checked against its model once it has: a past day on the map (a replay), a panel still loading, a page that cannot write a link yet, and a school with no status and no chance (a nameplate alone is not a card) offer the link alone. Where a card still cannot be made (the image fails), the link is copied in its place and the button says "No image, link copied" ("No image made" where the clipboard refuses too): never a tap that does nothing.

**One source.** A card says what the panel says at that moment, from the panel's own view (`web/src/app/school.ts`), never from a second reading of the files (`web/src/app/share-card.ts`): the school's name, campus and place; each status line as the panel words it, with the day it is for named in full ("Closed today", "Monday, Jan 12", the school's own day by the clock its status was read by); the delay or dismissal line; the reason the panel gives (never who posted it or when); the plain details the panel says below a status ("Buses run snow routes. No breakfast."); the chance with its meaning, the day it is for named in full ("Tuesday, Jan 13", so a post kept for good still says which Tuesday) and "Few local records" where the panel shows them; the season line where the panel shows one. No source is named: the map cites only school and district websites, and the card cites nothing.

**As of when.** Every card says "As of 6:55 AM": when the live closings file its status lines come from was made, or the predictions file its chance comes from (the earlier of the two where it shows both), on the school's clock, with the day where that is not today there ("As of Mon, Jan 12, 6:55 AM") and the school's zone where the viewer's clock reads otherwise ("As of 6:55 AM CT"). Where the school's clock cannot be read (the predictions file shipped but not read yet, a failed fetch, a stamp for another directory, a predictions outage: `UNREAD_ZONE` or `UNKNOWN_ZONE`, or a build with no predictions file), the same moment is told on the viewer's clock, always named ("As of 7:55 AM ET"), and the status lines name the day only where the panel does. A status or chance without the time its file was made gives no card at all (and no Story or Post button), never a card without its time.

**The picture** (`web/src/ui/share-card.ts`): a near-black dark like the map, the school's status lit in its own color behind its dot (closed `#7fd4ff`, delayed `#ffc46b`, remote `#b79cff`, early dismissal `#6bffb0`; a chance glows in the closed blue behind its number, by its number): a tight bright core and a faint wide light, so the frame stays dark and never takes the status's tint. Above: a round badge with the school's initial on a disc lit faintly in the status's color, where its logo will stand, then the school. Below: as of when, a hairline, and the site's mark (the Snowlight bloom of `web/public/icons/glyph.svg`) beside the wordmark, with the site's host at the right. Its words are in the site's own face (Geist, which the page already has; nothing new downloads), each line measured and wrapped to the card's width, a word too wide for a line broken rather than cut. A headline's or name's last word is never left alone on its line ("Delayed / start today", a step smaller where that is what it takes). The type is as large as fits, from 1.2 times its size on a Story (1.1 on a Post, never onto more lines for a headline or name) down to 0.7, where the smallest words are still 25 pixels; a card that does not fit at 0.7 leaves out the season line, then the plain details, then the reason, in that order, and one that still does not fit is not made at all (the link goes in its place): no line is ever drawn over another. The worst real card (the longest name, two days, every plain detail on each) fits at 0.7 with lines left out. A Story keeps its top and bottom 250 pixels free of words, where a story's own bars sit. The backdrop is drawn an eighth of the size and smoothed up, which keeps the PNG small (about 300 KB for a Story) and quick to make. The sample pictures use an invented school, town and county.

**Speed.** The cards' code (`web/src/ui/share-cards.ts` and what it reads) loads with the first press of Share, never with the page. The cards are made one after another as the options open, so a tap shares at once, within the tap a phone's share sheet needs; a tap on a card whose panel has changed since makes it again first. Each made card is timed on the page's performance timeline as `share-card story` and `share-card post`. In the e2e (`web/e2e/app.spec.ts`, a Pixel 7 with the CPU at a quarter of its speed) a Story takes 197 to 359 ms and a Post 156 to 212 ms (three runs, Nov 10), under the 500 ms bar.

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
- **Cadence.** Every 5 minutes from 18:00 to 23:00 and from 04:00 to 09:00 in the station's own zone (the zone most of its counties are in; real zone rules, so the windows follow daylight saving time), and while an NWS alert of an allowlisted type covers one of its counties (the alerts are read every 5 minutes; a failed read keeps the last set for 2 hours). Otherwise every 30 minutes, or the registry's `poll_minutes` when longer. A source the pass did not get to (`late`) is due at the next pass; a failed read (`error`, such as a 429 or 5xx without `Retry-After`) keeps its cadence, so outside the windows and alerts it waits its calm interval, a successor's first read of it included (the successor shows its carried statuses meanwhile). A source is never read again in the same 5-minute grid slot, nor less than 4 minutes after its last pass.
- **Health share.** G12b counts the sources due in the passes of the last 15 minutes, and every source blocked now, each by its latest read in that time. Both windows are counted from the passes' starts: a read is kept under the start of the pass that picked its source, the moment the cadence counted that source due, and both are dropped by the same test on the same start, so a source due in the window always has its picking pass's read in it, and that read is its latest (only a pass that picks a source reads it). A pass that read 10 sources or more also counts its own reads alone, and the gate takes the lower share: an outage that starts at a pass is refused at that pass, not only once the window holds nothing but failing reads (up to two passes later after a half-hourly sweep). From Oct 25 to 29 each of the 1261 uploaded passes with 10 reads or more had 84% or more of them good. This makes the gate stricter in one case: a broad degradation that keeps a pass's own reads under 60% (late reads of our pool and deferred reads count as not good, as in the window, since neither gives a fresh say) now refuses every pass until reads recover. Before, good reads still in the window from a half-hourly sweep before the degradation began could carry passes through it. A refusal is exit 3 and the loop goes on; v1 keeps its last good pass, and the `stale` alert opens once the served file is over 15 minutes old. Watch the own share (the commit's good over due) on the first storm-day soak. (Until Oct 30 the reads were kept under their own fetch times and measured from the clock after the reads: each :10 and :40 pass, 15 minutes after a half-hourly sweep, counted the sweep's sources due without their reads, dipped to 37-53% and was refused, 48 times from Oct 25 to 29.)

## What the page lights

The page lights each school with its row of `live/closings.json` on the school's MAP DAY, and
with that row only (`web/src/data/map-day.ts`). One rule tells every school's day, wherever
the page shows it: the glow, the key's counts and day line, the menu's counts and their
heading, the area panel's list and counts, the school panel's nearby list (each glyph is the
school's light, `closings.ts litStatus`), and the school panel's own today and tomorrow.

- Its own today until 3:30 PM on its own clock, and its own tomorrow from 3:30 PM until
  midnight there (owner decision, Nov 9). After midnight that date is its today, so nothing
  changes at midnight. A row for its today never lights after 3:30 PM, nor a row for its
  tomorrow before.
- Its clock is its district's time zone (a private school's own) as `predictions/latest.json`
  gives it, for the directory the closings file names, however old the file: a district's
  zone does not age. The map and every panel take the same zones (`live.ts toldZones`): the
  ones the map lights by, else a panel's own read, else the newest file the page's one reader
  holds. So a school lit for tomorrow says tomorrow in its panel, even when the panel's own
  read of the file fails.
- A school the file gives no zone keeps the rule from before: the day that is today in every
  contiguous US zone (UTC-4 to UTC-8), and nothing from 04:00 to 08:00 UTC. The predictions
  file of Nov 9, 2026 gave a zone to every district (18,227) and every private school
  (22,110) of its directory (118,211 schools): none lacked one. It names five zones (New
  York, Chicago, Denver, Phoenix, Los Angeles).
- While no zones for the directory can be had (the predictions file still on its way, offline
  after a reload, a failed read, a file for another directory), a school in the contiguous US
  (by its place: 24.3 to 49.5 N, 125 to 66.8 W) lights on the day that is today everywhere,
  and only while it is also the map day of all five contiguous clocks: from 08:00 UTC to 3:30
  PM in the East. Every clock in the lower 48 keeps one of those five, so that day is the map
  day of every school there, the ones the file gives a zone and any it gives none alike, and
  no light steps back to another day once the zones come. From 3:30 PM in the East until
  08:00 UTC nothing lights (the West past 3:30 PM is on its tomorrow then, while a school with
  no zone is still on its today); a school outside the contiguous US (Alaska, Hawaii, the
  territories) never lights this way. Its panel then reads its today as the day that is today
  everywhere, so its words name the row its light shows, and a school whose record puts it
  outside the contiguous US names no day. In those dark hours the page gives no update time
  and names no day: no time stands over a map that cannot show the file's rows.
- The first lights never wait for the predictions file (about 600 kB compressed, 6 to 9 MB
  to read): the page lights by the agreed day as soon as the closings file and the directory
  are in, and lights again by the zones when they come, with no pulse. Outside the hours the
  agreed day has none, it is every contiguous school's own map day, so the map reads the zones
  only from 5 minutes before those hours (a page not seen wakes for that read too, so it is not
  dark at the East's 3:30 PM), and for a school outside the contiguous US; once held for the
  directory they are not read again. After a read that brings no zones for the directory (it
  failed, or the file is for another directory, as at a change of directory), the map waits 5
  minutes before the next, then 10, 20 and 30 at most, so a file that stays on another
  directory is not downloaded every few minutes all evening; a panel's own read still brings
  the zones to the map at once.
- The page relights at the next 3:30 PM and midnight of every zone it shows, and at the
  visitor's own midnight, without waiting for a read; an open school or area panel shows again
  at the same minutes for the schools it lists, so its glyphs, counts and heading turn with the
  lights. A light that appears only because a
  school's day turned is no news and does not pulse; a row new since the last file read
  still pulses, also when the file's directory came late or no day could be told when the file
  came (the rows of a file are taken as seen only once the file is shown).
- Over the key, the page names the day it shows whenever that is not both the visitor's own
  today and today on every clock it is shown in ("Showing Tuesday"), so a visitor whose browser
  keeps UTC still sees it named; and both days and where while it shows two, between 3:30 PM
  in the East and 3:30 PM in the West ("Tuesday in ET · Monday in CT, MT and PT"). The line
  stays while the map's credits are open, lifted clear above them.
- The menu heads its counts with the same day ("Tuesday", or "Monday and Tuesday" while the
  map shows two), and Today only for the visitor's own today; the area panel heads its counts
  the same way.
- The page reads `predictions/latest.json` through one reader the map and the panels share (a
  panel just opened reads it afresh, for its chance). A closings file that lists no school
  asks for nothing more.
- A replay lights the day it replays, as before. Notifications are unchanged
  ([docs/notify.md](notify.md)).

## Where files go

Public, on the live host. These hold school indexes, days, codes and times only.

- `v1/live/closings.json`.
- `v1/live/opens.json`: explicit "school is open" statements, for the prediction model.
- `v1/live/days/<day>.json`: when each school's status changed that day, for the timeline.
- `v1/live/days/index.json`: lists only the days whose file carries the current stamp, and is written with every upload, even when it lists no day. A finished day is published again from the change log after a restamp or a directory change.
- `v1/live/hold.json`: the hold, a flag and two times. The web never reads it.
- `v1/live/season.json`: each school's closed, delayed, remote and early-dismissal days this school year ([The season counts](#the-season-counts)). Written by the reader only, when it changes.

The files go up in this order: closings, opens, day timelines, season file, index.

Private state (`out/internal/live/state/`, kept by the state store, [The state](#the-state)):

- `ledger.sqlite`.
- `publish.json` (the `v1` publisher's: the overrides job's, and the reader's in `on`) and `publish.<prefix>.json` (`publish.v1-shadow.json`, `publish.off.json`): the last stamp, the gate's memory, the directory content the last upload was made against, and which day file went up under which stamp and prefix.
- `changes/<day>.jsonl`: every change the map showed, with its source and row key.
  - Each file is rewritten whole and atomically.
  - A torn line from an older copy is skipped and counted.
  - A day leaves the state only once it is more than 45 days old and a durable copy holds it: an evidence database holding its exact bytes (`kept.json`, [The evidence](#the-evidence)), or `changes/durable.json` (`{"through": "YYYY-MM-DD"}`, the push to the private data repository of spec 19, not built yet).
  - A day no copy is known to hold is never pruned, however old.
  - A successor that lost its state takes each day it has no log for from the public day file under the current stamp (lines with `"by": "seed"`), but only when the file's `content_sha256` is its own directory content: two contents can share one stamp (risk R6), and a file built on the other one indexes other schools. Such a file is skipped with a warning in the log. The public timeline then goes on from where it was, rather than starting again at the successor's first publish. The private details of those changes (source and row key) are lost.
- `season.json`: the season ledger, each counted day's final statuses by NCES id and the day counting began ([The season counts](#the-season-counts)). Written by the reader after an upload that carried a day's final timeline; the overrides job never writes it. NCES ids, days and codes only.
- `robots.json`: robots.txt verdicts per origin (the parsed rules, the read time and the file's digest), kept 24 hours.
- `pacer.json`: each pace key's last request start, so a host's Crawl-delay holds across a handoff.
- `carry.json`: the sources the last pass held, each with the time of the good read holding them and the end of that hold, the sources whose states it withheld for a failing resolve, each with the end of that (`unknown`: 90 minutes from the last pass that failed to resolve it; a successor withholds the same states until its own read of the source, at most to that end, and a list that does not read carries nothing), the pass's time and a key of the resolver's version and the merge rules, so a successor shows them as that pass would have until its own read ([The handover carry](#the-reader)). Rewritten whole and atomically by every pass, unmarked, and marked final by `live finish --record` before the end push (a successor uses only a final record); ids, codes and times only; never exported.
- `exits.json`: the last runs' exits (the `chain` alert).
- `d1.json` (never packed): this run's epoch and its last push's counts. `pulse` (never packed): the watcher's heartbeat.
- `cadence.json`: per source, the start of the pass that last read it, its outcome, the cause of that outcome (`live/causes.py`: a 401 apart from a 403, a 429, a timeout; counted in the export's `read causes:` line), and the earliest next read of a deferred or blocked source.
- `morning/<UTC day>.json`: the morning record the prediction model learns from (docs/predict.md, "The model learns on its own"). Per 30-minute UTC slot: the prefixes a pass was shown under, each whole read of a shown pass between 09:00 and 21:00 UTC (rows, rows placed, rows read as no status), the states a pass withheld whole, and the districts its rows named with the days and the status kinds (`?` when a dissenting, unsure or unread row named it); for the outcome-blind read labels (docs/predict.md, "The read labels"), the lowest healthy share of the slot's shown band passes in thousandths (`health`) and the sources whose whole read was an empty judged from old rows, a list typed by hand not changed for 36 hours, old posts, undated page text or a list last written before the last winter, and the populated lists whose present dated rows all name days before the day before (`old_lists`: a list still holding an earlier storm's rows, judged from the rows' own dates, a row with no date of its own dated by when the list first posted it, never from what closed) (`stale`; a page that says it holds nothing now is not one). The read labels never count a stale read whole, nor count it toward a list's captures, size reference or recent days (lead ruling C2). A worst case of 400 stale ids (about 20 characters each) in each of 24 band slots adds about 196 KB raw and 2.5 KB gzip to a day (measured on synthetic ids). Per UTC day, `by`: each source read whole with the districts its own rows named for that day or every day, stored once a day per source as a run of `[slot, added, removed]` entries written only where its set changes, so a list naming the same districts all morning costs them once, not once a slot. Counts, ids and codes only. Rewritten whole and atomically by every pass; kept 45 days in the state, and every finished day kept for good in the evidence databases ([The evidence](#the-evidence)). A day leaves the state only once a database holds its exact bytes (`kept.json`): when it is over 45 days old, or (never the last 10) while the folder holds more than 16 MB; past 32 MB the oldest go even unkept, loudly. `live state export` and `predict learn` log `morning record: <days> days, <bytes> B (<first day> to <last day>)`. A file that does not read is marked damaged and no day of it is learned from.
- `kept.json`: what the evidence databases were last found to hold, per morning-record and change-log day: the sha256 of the file and the databases holding exactly it; when the first check was, and days the size valve dropped unkept ([The evidence](#the-evidence)).
- `unmatched.json`: names the matcher did not place. Only ever in a private store, never in the Actions cache.
- `good_reads` in the ledger keeps each source's first good read of every UTC hour for 14 days: all the resolver asks of it.

The morning record's changed day files also go, in the loop's idle time each :00 and :30 UTC mark, to the private state database's two morning tables, for the predict job's serving passes ([The state](#the-state)).

live-read.yml saves only the export (`pipeline/out/internal/live/store`, holding `live-state.tar.gz`) under a key starting `live-state-` (`CACHE_KEY_PREFIX` in `snowlight/live/state.py`): the predict workflow's learning step restores the newest such key, read only.

Private output (`out/internal/live/`):

- `health.json`: counts only. A check between passes, or while a pass reads, that raised the alert or published a blank adds `check` (its time, the verdict, `alert` and the blank's report) beside the last pass's health. `withheld.source_unknown` counts statuses held back because a source's say was unknown. `gate.counts.redacted` counts statuses the hold darkened that only gone rows light. A failed write of this file is logged and leaves the pass's exit as it was.
- `provenance.jsonl`: the last publish's sources, row keys and times.

### Admin sources

The admin view's **Lists** tab (docs/accounts.md) shows where each lit status came from.
In the idle time after the morning record's shipment (every :00 and :30 UTC, after a good
state push), the reader reads `provenance.jsonl` and ships, for each local day of that
publish (the far west's today to the far east's tomorrow), one summary per status: its NCES
id, status, reason and level, the winning list's id and type, the list's public link from the
registry (its page, else the list file the reader GETs; none for a POST-only endpoint), the row's `lo`, `hi` and `row_stamp`, `present`, the list whose time shows as
"Posted", and each contributing list's id and type. No row key and no list text.

Each day's head also carries the publisher's mode (`on`, or `shadow`, which the page labels
as not on the public map; with publishing `off` nothing ships) and `latest_at`: the
publisher's last publish, or the start of the last hold it recorded, from its memory, when
that is later than the publish the summary is from (the `generated_at` its lines carry, which
is the time the page shows for the day). A blank publish (a hold, the breaker, the clock
check), a hold set by `live blank` (another process, which leaves the reader's last publish as
it was: the reader records the hold's start on its first held pass) and an upload that failed
after the closings file do not rewrite `provenance.jsonl`, so the page then says the map was
published again at that time and that the list is the earlier publish's. A summary with no
status is judged by the file's time, so a later publish (a first lit one whose upload failed
after the closings file) is still named. A run whose first publish
was blank (no `provenance.jsonl` yet) sets it on the heads already stored. A day too big for
16 parts keeps its last shipped summary and its time, and gets the later publish's time as
`latest_at`, so the page says the map was published again. A day whose shipment failed
partway (some parts written, not its head) shows as being written until the next shipment,
which writes it whole again even if its content went back to the stored one. The shipment
takes at most 20 s of the idle time, so the evidence check after it keeps its time.

It goes to the accounts database (`snowlight-accounts`, found by its exact name and never
created), which the API Worker already reads, so no Worker is bound to the state database
and no new binding is needed: `lit_sources_head` (a day's sha256, part count, status count,
the publish's time and the write's), `lit_sources` (the summary as gzip, 64 KiB parts,
base64, at most 16) and `lit_sources_budget` (rows written each UTC day). A changed day's
parts go first, then its head and the trim (until the head names the new parts the admin
page finds they fail its sha256 and says the day is being written); an unchanged day only has
its head's times updated;
an unchanged file asks nothing. Days before the publish's first day are kept as last shipped
(yesterday), and older ones are deleted. Writes are capped at 5,000 rows a UTC day (a usual
day writes a few hundred: about 5 rows a shipment, 48 shipments; a 20,000-status storm day
about 25 a changed day), 5% of the account's free 100,000; past the cap nothing ships and the day keeps its last version with its time. The rows a shipment wrote are billed even when it ran out of time or a request's answer was lost (one last request, given 5 s past the deadline, inside the 30-s push margin; a bill that fails is sent with the next shipment). Only a
`live-read` run ships. The one log line holds counts only (`sources shipped: shipped, 3 days,
1 changed, 412 statuses, 1 parts, 9 rows, 0 too big, 210 ms`, printed when something
changed); a failure is one line (`sources ship: failed: <type>`) and never touches the pass
or the push.

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
| `host` | The live host (GitHub) refused for a rate limit; the pass line says until when. Nothing was sent after the refusal and nothing is lost. | Nothing by hand: the pass at that time uploads every change. Stop any bulk GitHub API use acting as the owner ([When the live host refuses](#when-the-live-host-refuses)). |
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
- a source the run before listed so in its handover record, until this run holds rows of it from its own read, at most 90 minutes from the run before's last pass that failed to resolve it ([The handover carry](#the-reader));
- a source due for reading (active, on a platform whose terms permit polling) holding a row that was read but never resolved within the last 36 hours (a run cut off mid-pass).

Each such source holds back every status and open statement in its registry states until it is read again. The rest of the map publishes. A source not due (the registry no longer lists it, it has no endpoint, or its terms do not permit polling) is never read again, so its unresolved rows are left out and expire.

## The breaker (G9)

Each pass counts, per source, the claim items it kept after the day window: one per school and day each row claims, so a district row that claims today and tomorrow counts each of its schools twice, and duplicate rows, until-further-notice extensions and vanished rows still kept all count. A source over its limit has every claim and open statement dropped for that pass (its dissents stay); its claims are counted under `withheld` `breaker`, it is named in `health.json` `breakers`, and the `breaker` alert opens. The limit is the larger of the floor and 3 times the source's archived limit (`snowlight/live/guards.py`, `breaker_limit`).

The archived per-source limits are not built yet, so the floor alone decides. The default floor is 50: on Nov 2 it tripped on a real storm list and hid one station's statuses for about 5 hours. Until the per-source limits exist, the live run's merge uses a floor of 15000 (`LIVE_MERGE_RULES` in `snowlight/live/cli.py`), above twice the largest single station's coverage (about 6,800 schools), so no real list for two days trips it. The window can hold three days for a school west of Eastern time in the hours after midnight in the East, and a list would then need over 5,000 schools on each of them; G8, the spike hold, the size gate and `live blank` still bound a misread. Only the ingest's merge takes it: the resolver keeps the default rules, whose digest is part of `derived_version`, so no stored row is derived again.

A trip logs one warning line naming the tripped source ids and nothing else: `breaker: <id>,<id>`.
