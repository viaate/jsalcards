# Flights

Flights is Snowlight's second mode: the chance a US departure is cancelled or leaves 45 or more
minutes late, by airport and time of day, for today and the next two days. This page covers the
data and the model (piece FL-1). The code is `pipeline/snowlight/flights/`; the files it
publishes are described in `pipeline/snowlight/schemas/flights.py` and `schemas/flights-*.schema.json`.

## Sources

All public, free, with no key or sign-up. Raw downloads stay in RAM (`/dev/shm/flights`) and are
never committed.

| what | where | used for |
| --- | --- | --- |
| Every scheduled domestic flight of the reporting carriers, 2015 on | BTS On-Time Reporting monthly files | outcomes, usual rates, own records, usual flights |
| Forecast weather by airport, 00Z runs, mid 2020 on, and the two newest 00Z runs live | NBM station text (NBS) in the public NBM bucket on AWS | the model's inputs, history and live alike |
| The same forecast, 00Z runs from 2018-11-07 to 2020-02-25 | IEM's copy of the NBS (`mos.py`, model NBS), read into the bulletin's rows (`nbs_iem`) | read and checked, not fitted: the validation year did not keep them (below) |
| Hourly airport weather reports, 2015 on | IEM ASOS archive | the weather kinds of each airport's own record |
| Airport stations, time zones, NWS offices and zones | IEM station tables | the airports table |
| Airport names and four-letter codes | OurAirports | the airports table |
| Ground stops, ground delays, delays, closures | FAA airport status | live only |
| Active alerts | NWS alerts | live only |
| Latest weather reports and TAFs | aviationweather.gov caches | live, and the archive |

One request at a time per host, a plain User-Agent with no personal details, a few tries with
pauses on errors, and every download skipped when it is already kept.

## The airports

`pipeline/data/flights/airports.json`: every airport with BTS departures in the last 12 posted
months that has a weather station (359 today; Saipan has none in the station tables), with its
station, location, time zone, NWS office, forecast zone and county, and departures per day.
Palm Beach changed its code from PBI to DJT in August 2026: its history under PBI is read as DJT,
and its forecast station is still KPBI.

## Blocks

A day has five local blocks: early 5-9, morning 9-12, afternoon 12-17, evening 17-21, night
21-5. The night block belongs to the day it starts on.

## The model

For each airport and block, five targets: a departure is cancelled; a departure leaves 45+
minutes late; an arrival is cancelled; an arrival is 45+ minutes late; and per airport day, a
rough day (10% or more of departures cancelled, on days with 5 or more departures).

Inputs per block, from the NBS run: snow and ice amounts, the chance of snow, freezing rain and
thunder, wind, gust, visibility, ceiling and temperature, the snow and ice of the two blocks
before, the run's snow and ice from its first hour to the start of the block's day (a storm on
the days between the run and the block), the snow and thunder at ten big hubs, the airport's own
usual rate for that block and month, and the whole day's snow, ice and thunder from the same run.
And the weather that already came, known when the run is issued: the hours of falling snow
observed at the airport in the 24 hours before the run and in the 24 before those, and the hours
of freezing rain or ice pellets in the 48 hours before it (`obs.before_runs`, from the IEM
hourly reports; the live pass reads the same reports over the 49 hours before its runs, so the
history and the live pass count the same hours). So the day after a storm knows the storm.

The chance's inputs are the forecast, the usual rate and the hubs, and of the groups of inputs
(the whole-day ones, `day_*`; the run's snow and ice before the block's day, `pre_*`; the weather
that already came, `obs_*`), only those the validation year keeps (`train.choose_inputs`): a
group stays only when the Brier score on the validation year (the 12 months before the test
year, fitted on the rows before it) is lower with it than without it on every check (departures
cancelled, departures late and the rough day, lead 1). The test year never picks an input. The
model file lists the inputs it uses (`inputs`); the report says which groups stayed. The
groups kept are then scored together on the validation year, against every input and against the
same without the whole-day inputs (`train.validation_chosen`); the model is fitted on them only
when they are no worse than both on every check, else on the set that is (`train.confirm_inputs`). The weather
that already came is read either way: it decides which rows are the days after a storm (below).
D6 also names NWS alerts, the FAA programs of today and the airport's own record as inputs; they
are not in the model (the FAA programs have no history here, and the alerts and the record are
not tested yet), so the site shows the FAA state beside every chance and never a low chance
without it. Each target and lead class
has its own weighted binomial logistic regression (`model.fit`). The lead class counts days by
the airport's own calendar: lead 1 is the 00Z run issued the afternoon or evening before the
block's day, lead 2 and 3 one and two days earlier. A run issued on the block's own day is never
used, and only blocks a run covers whole (from 3 hours after it, ending by 72 hours) count: the
history and the live pass read exactly the same kind of row.

Every row's usual rate comes from the 3 years before its own 12-month period (the periods run
back from the test year, so a January 2025 row reads October 2021 to September 2024): no row's
usual rate holds its own outcome or anything after it. The window length (3 years, 5 years or
every year) is chosen on the validation year, the 12 months before the test year.

Three spans are left out of fitting and testing, because their cancellations were not weather
(`spans.NOT_WEATHER`): March 10 to June 7, 2020 (the COVID-19 collapse in flying: the national
cancelled share was 0.9% on March 10, over 5% from March 17 and above 2% to May 31), July 19-23,
2024 (the airline computer outage) and November 7-15, 2025 (the FAA's ordered flight cuts in the
shutdown). One airline's own days are left out of that airline's flights only, before they are
summed to airports (`spans.CARRIER_NOT_WEATHER`): Southwest from December 24 to 31, 2022 (its
meltdown: 44% to 78% of its flights cancelled from December 24 to 29 while the other airlines
were back to 1% to 16%). The same filter holds everywhere: the fit, the test, the usual rates, the
own records, the replays and the usual flights.

## The two winters before the bucket

IEM keeps the same NBS run by run from 2018-11-07; its 00Z runs end on 2020-02-25 (01Z after).
`nbs_iem.to_rows` reads them into the bulletin's own rows, element by element: the same numbers
for temperature, wind, gust, the chances and the snow and ice amounts; ceiling 888 (none) as the
bulletin's -88; 999 in any element as no value; visibility as tenths of a mile, IEM's whole miles
times 10 for the runs before 2020-02-20 (NBM 3.1: the median of every 00Z run is 9 to 15 through
2020-02-19 and 110 from 2020-02-21; there is no 00Z run on 2020-02-20). On the 00Z runs both
sources hold from 2026-10-01 to 2026-11-21 (359 stations, 18,309 runs, 421,107 rows), every
element is equal on every row. A run IEM lacks stays a hole.

They are not in the model. Fitted with them (`--first-run 2018-11-07`), the validation year's
departure-cancel Brier at lead 1 was 0.012140 against 0.012134 without them, and 629 heavy
departure block-days were said far too low against 616: both worse, so the step is reverted
(the lead's rule H3). In those winters the forecast gave snow in 6 to 7% of its 6-hour cells
against 13% in 2020-21 (an older NBM version); a version input is the next thing to try. The
code stays ready: with a first run before 2020-06-01 the fit reads them (`build.nbs_rows`,
`nbs-iem/` beside `nbs/`), and the monthly job fetches them once into its history cache through
the polite IEM client and publishes no refit until every station-winter is kept.

## The long history pull

`python -m snowlight.flights.pull iem|bts|status` (`flights.pull`) fetches the 20 years before the
bucket into RAM, re-runnable, one file at a time, each reduced and its raw body dropped. One IEM
queue, in order: the NBS overlap above, the two NBS winters, GFS MOS (MAV; AVN until 2003-12-16)
00Z from 2000-06-01, one station-year a request, then the hourly reports 2000 to 2014. IEM
requests are serial, and each waits at least 2 s (3 s from 13:00 to 01:00 UTC) after the last
reply ended. A busy reply (429, 5xx, "Too many requests", a dropped connection) or a body that is
not the table stretches the pause and waits the shared backoff: 60 s, doubled on each busy reply
whichever task got it, to 15 minutes, and halved only after 50 calm replies in a row; its end is
kept with the pace, so a restarted queue waits it out. A request the local agent proxy refused
never reached IEM: it leaves the pace and the backoff alone, and three in a row stop the queue
(exit 3) with that reason in the status. Five tasks failing in a row stop the queue. While the
live pass may be reading IEM (its `latest.json` 14.5 to 27 minutes old) no request goes. A hole (a
header-only reply) is asked once more a day later and noted as confirmed. The status file, written
at least once a minute through every wait, says whether each queue runs (its lock, pid, last
request, pause, backoff and its end) or why it stopped, "no table kept for N min" with the last
error once a running queue kept nothing for 15 minutes, and the hours left at the pace of the last
2 hours up to now ("unknown" when nothing was kept in them). `pull stuck iem` gives the pid of a
running queue that kept nothing for 30 minutes; the restart command replaces such a queue with a
fresh copy from its own shell. The BTS queue runs on its own hosts: PREZIP
2000-01 to 2014-12 and the Data Expo copy (Harvard Dataverse, CC0) for 1997-10 to 1999-12 (old
years keep `dep`, `arr`, `legs` and `places`). The Data Expo copy and PREZIP agree on flights and
cancels on every airport-day of 2000-01 to 2000-03 (17,956 airport-days).

## The held-out test and the gate

The test year is the newest 12 posted BTS months. It is never used to fit or to choose a
setting, and it sets no gate (the lead's ruling LR-H1, `train.fit_and_gate`): every gate below is
set on the validation year (the 12 months before the test year) by a fit on the years before it;
the model is then fitted on every year before the test year with those gates fixed, and the test
year scores the published choice once. An airport, target and lead with no rows in the
validation year is never published. For every airport, target and lead, the validation year
scores the Brier score per departure (or per day) against the airport's own usual rate. A chance
is published only where all of these hold (`model.passes`):

* skill above 0 (a lower Brier score than the usual rate), on the whole year and on each half
  of it (the even and the odd ISO weeks);
* at least 10 events in the validation year (2 rough days for the rough-day chance);
* expected events within 0.67 to 1.5 times what happened;
* where it said 20% or more, what happened was at least half of what it said: pooled, and in
  every reliability bin from 20% up that holds 2 or more block-days (days for the rough-day
  chance; the blocks of one storm day go together, so block-days are the units, not flights);
* heavy block-days said far too low stay rare: of the block-days with 30% or more of their
  flights cancelled (late, for the late chances; a day, for the rough day) and 10 flights or
  more, those whose chance was under a third of what happened are at most a quarter (one is
  always allowed);
* a high bin of a single block-day counts too when it has 30 flights or more: it fails when it
  saw under a quarter of the chance it said;
* no bin says too little: in every reliability bin from 2% up with 5 or more block-days and 5
  or more events, what happened is at most 1.5 times what it said; the same holds for the
  chances shown pooled over the airports that passed (a bin of a few block-days at each of many
  airports is what a reader sees at that chance), and where it does not, the airport with the
  most events over what it said in the failing bins is taken out, one at a time, until it holds
  (`model.drop_under_said`);
* the target and lead holds out of selection: the airports chosen on the even weeks, scored
  together on the odd weeks, and the reverse, have a skill of 1% or more. Under that no
  airport's chance is published for that target and lead.

The test year's own split-week figures (the airports its even weeks would choose, scored on its
odd weeks, and the reverse) stay in the report as a second view only; they set nothing.

The days after an observed storm (6 or more hours of falling snow or freezing rain in the 48
hours before the run) are held to their own test (the lead's ruling LR-F6): those rows at the
airports that passed, pooled, must have at least 50 events, a skill whose lower 90% bound (whole
days drawn again 1,000 times with a fixed seed, `model.skill_lower`) is above 0, be calibrated, have no bin from 2% up that saw over 1.5 times what it
said (5 or more block-days and events), and keep heavy block-days said far too low rare
(`model.after_storm_ok`). The same must hold out of selection: the airports the even ISO weeks
chose, scored on their odd-week rows after a storm, and the reverse, so the rows that chose an
airport never score its after-storm gate. Where either does not hold, every airport shows the
usual rate on such days
(the model file names the targets and leads that passed, `after_storm`). When the live pass
cannot read the reports before its runs, it cannot know whether a storm came, so every value is
the usual rate.

Everywhere else the files give the usual rate with its `usual` bit set, and the site shows it
as the usual rate, never as a forecast. The report (`snowlight flights train --out DIR`, then
`DIR/heldout.md`) lists every airport and target, the pooled skill of the model, of what the
files show (as published) and out of selection, the usual rates' own score on the test year, the
same three with the non-weather spans put back, and the validation-year checks behind each input
group. A candidate (a span, an input group, a winter tried) is judged by
`train.gate_on_validation` alone, so choosing never scores the test year.

The usual rates are a dated average: each block's share over the window chosen on the
validation year, ending the day before the test year (non-weather spans left out). The live
files' usual rates come from the same model, so they average over the same days. The track
record says the window (`usual_first`, `usual_last`); the report sets the usual rates' expected
events against what the test year saw (in the test year ending Sep 2026 that year saw about 1.3
times the cancels the usual rates said, and about 1.15 times the late departures).

Chances are published in tenths of a percent (0 to 1000), so a small chance is never shown
as 0.

## Each airport's own record

`flights/records/<code>.json` (the code in lower case, as every per-airport file name is): for
each weather kind (freezing rain, snow, thunder, low clouds and fog, strong wind), the airport's
matched days (days with a block of that weather with 3+ departures, and at least one other
airport in the same weather that day), the blocks and how many were bad (10%+ cancelled), the
share of its departures cancelled in those blocks, and its same-day peers' share: the other
airports in the same weather on the same days, each day's share weighted by the airport's own
departures that day, so a line of only storm days is held to its peers' storm days and never to
their mild ones (the lead's ruling LR-F1).

The test counts days, not flights or blocks, since cancels come in clusters (a whole bank goes on
one day, none on the next), and it holds under its own null (the lead's ruling LR-F5). A matched
day counts toward the test only when the airport's departures that day times its peers' share
that day are at least 1 (one cancel expected); on fewer, one cancel or none crosses the lines by
luck, so those days stay in the plain numbers only. On each counted day the airport's share is set
against its peers' that day: WORSE when it is at least 2 points above and at least 1.5 times
theirs, BETTER the other way round, else a tie, dropped. The file gives both day counts. A verdict
needs, all the same way: at least 8 untied counted days; the number of BETTER among them far from
its exact law had the airport cancelled at its peers' share each day (each day's own chance of
BETTER given untied at the peers' share, never 1 in 2), two-sided under 1 time in 20 by luck; its
cancels over all matched days far from what its peers' same-day shares give at its departures,
two-sided under 1 time in 20, with the spread the larger of the line's own day-to-day spread and
the clustered spread at the peers' shares; and the pooled shares over the matched days at
least 1.25 times apart, as computed and as published (per mille). Both day tests read each day
with the day clustering of cancels: a day's share at an airport moves with its own storm far more
than independent departures would (on the 2015 to 2026 lines, about 3 for the beta concentration;
a binomial day test there says LONGER by luck up to 6% of the time). Each weather kind's clustering
is the larger of the median of its lines' own moment estimates against their peers' same-day
shares (so a few big lines never set it low for the many small ones) and the pooled estimate over
all their days (where the hubs, whose banks go together on a storm day, weigh most)
(`records.line_clustering`, `records.day_clustering`; the group's lines pooled when a kind has
under 5). Each day's chances of WORSE and BETTER, and the spread of the pooled cancels, are
the beta-binomial's at that clustering (R6-S1). WORSE: cancels sooner than
most; BETTER: holds out longer than most. Otherwise there is no verdict and the box gives the
numbers alone; a record like the others' gets
no words. An airport that sees a weather kind only on big storm days is held to its peers on those
same storm days, never to the others' mild days. The non-weather spans (see the model) are never
counted. Each carrier is held the same way to the other carriers at the same airport in the same
weather blocks on the same day; a carrier with no verdict in any weather is left out of the file.

## Usual flights

`flights/routes/<code>.json`: every flight number that flew from the airport in the newest posted
month, and in this month and next month a year before, with its route, times, weekdays, days
flown, cancellations and late departures (the days of a non-weather span left out). One-offs
(fewer than 2 days) are left out. They are
what usually flies, never a claim that a flight is on sale.

## The live pass

`snowlight flights live --host github`, run about every 20 minutes by the live loop below
(`.github/workflows/flights-live.yml`). A pass:

1. reads the two newest 00Z NBS runs out (the only runs the test scored), the FAA status, the
   NWS alerts, the weather reports and the hourly reports of the 49 hours before the runs, each
   on its own: any failure of one (a refused request, a body that does not read) leaves that one
   not read and the pass goes on. Each request waits 20 s at most per step and never runs past
   the pass's end, and the pass asks for nothing more after 6 minutes (what was read by then is
   written, the rest is not read);
2. computes every airport's chances for today and the next two days: each day from the newest
   run that covers it at lead 1 to 3, every block of the day from that one run (`runs` names it
   per day); a newer run never mixes its partial rows into a day; a block that is over, or that
   the run does not cover whole, has no value;
3. writes `v1/flights/live/slot-N.json` (three slots taken in turn) and
   `v1/flights/latest.json` naming it, in one write.

A slot file is rewritten in turn, so a reader takes it as current only when its `stamp` is the
one `latest.json` names; any other stamp is an older pass (a cached copy) and is stale.

Every part carries its time: `run` (and each day's `runs`), `programs_at`, `alerts_at`,
`weather_at`, `observed_at` (the newest hour of the observed reports), or `None` when it could
not be read. An airport whose own observed reports end more than 3 hours before the newest run
shows the usual rate. A value outside the file's range (a visibility over 100 miles, a gust over
200 knots, a delay over a day, `nan` or `inf`) is read as no value. Every source time is read
against the pass's clock, from 7 days before it to 10 minutes after it (`inputs.on_clock`): a
weather report off the clock is left out (it never hides the real newest one), an FAA status or
alert list whose update time is off the clock is not read, and an observed hour after the newest
run is left out before the per-airport check, so a lagging station is never marked fresh. An
observed row whose time does not read is that row's alone. Each source's line in the pass log
counts the values read as none and the times left out. An airport whose entry does not fit the
file as written and read back shows its marked usual rate (`live.Pass._entry`) with its FAA
programs, alerts and report as read, each kept on its own guard; a part that does not fit is
`None` (not read for that airport), never an empty list under a set `programs_at` or
`alerts_at`. An airport's `programs` or `alerts` is `None` whenever that source was not read; an
empty list means none in effect when read. A source time that does not fit the file leaves that
source alone as not read, in the file and at every airport; when the run's or the observed
reports' time does not fit, or the file itself does not, every airport shows its usual rate with
every source as not read. An airport whose usual rate cannot be written either is left out of
that pass alone. None of these stops the pass. A source time a few minutes after the pass (a
source clock ahead, within the 10 minutes allowed) is published as the pass's time, so no time
in the file is after `generated_at`.
A pass writes the slot after the one `latest.json` names (read back from the host), so two
passes in a row never share a slot. With neither the forecast nor the FAA status
read, nothing is written (exit 3) and the page grays the old file by its age. FAA programs older
than 30 minutes are not live. An FAA program's reason is published as its kind (weather, volume,
equipment, runway, other); its end time is read from the FAA's own form (`8:00 pm EST`, or a
UTC time), and a form that does not read gives no end time.

The model knows only the weather. During a known non-weather event (an airline's computer
outage, flight cuts the FAA orders) its chances say what the weather alone would do; the FAA
programs at each airport are then the only live sign of it. Such spans are left out of fitting
and testing, and the report shows the test with them put back.

Once a day, the first pass that has that day's 00Z run (before 06Z, still the evening before
across the US) keeps the day's snapshot in a write of its own, after the live files, so a failed
archive never stops them: `v1/flights/archive/NNN.json` (plain JSON; NNN is the day's number in
a ring of 30 days, so the published tree keeps the current files and at most 30 days of history
(the lead's ruling LR-F7), and a day's slot is rewritten 30 days later). BTS posts a month about
50 days after it ends, so the monthly job, every day it runs, copies the host's snapshots into
its history cache (`monthly.keep_archive`, kept 200 days) and scores from that copy; a day lost
from both before its month was scored is said with a warning and not scored. It holds the day, the published file, the usual rates behind tomorrow's values
(rounded as the published chances are), the FAA programs with their own reasons, the weather
reports and the TAFs as read, and validates against `schemas/flights-archive.schema.json` when
written and when read. A pass reads the slot back first and keeps no second snapshot of a day.

The host's tree is the site's, uploaded whole by every Schools deploy, so every Flights file has
a budget (`live.HOST_BUDGET`, 200 MB): the archive 150 MB, the live files 1.5 MB, the monthly
build 40 MB (a larger build is not published), each held by a test.

## The live loop

`snowlight flights loop --until +300m` (`pipeline/snowlight/flights/loop.py`), the `live` job of
`.github/workflows/flights-live.yml`, keeps itself running all day the way the closings reader
does (live-read.yml): it runs a pass about every 20 minutes for 300 minutes, then the job
dispatches its successor (workflow_dispatch with the run's own token, naming the run in `after`).

- A pass starts only when `v1/flights/latest.json`, read from the live host's repository (the
  contents API, not the Pages cache, whose copy can be 10 minutes old; the Pages copy past its
  cache only when that read fails), is 15 minutes old or more, or missing or unreadable (a stamp
  more than a minute ahead of the clock reads as unreadable), and never sooner than 20 minutes
  after the loop's previous pass began. So two loops back to back keep the 20-minute rhythm.
- Each pass is a child process with a hard limit of 9 minutes, so a hang ends that pass and never
  the loop; the trip alerts (`snowlight notify flights`, docs/flights-trips.md) follow each pass
  that wrote, a child with a limit of 4 minutes. The pass's child never sees the Cloudflare
  secrets, the alerts' child never the live host's token.
- A pass that fails (exit 3: nothing written; 1: an error; 124: its time limit) is one warning
  annotation and the loop goes on to its next pass. The loop step fails only when no pass of the
  run wrote; the successor is dispatched either way, but not when the run is cancelled (cancel
  it, or disable the workflow, to stop the chain).
- If the successor cannot be dispatched (3 tries), one warning: the next start below begins the
  next loop.

What starts a run: its predecessor; the `*/20` schedule (GitHub fires it late and seldom on this
repository, so it is a backstop); every run of live-ingest.yml (workflow_run, requested); the
owner (workflow_dispatch); and a push that changes the workflow file. The `check` job (a few
seconds, no checkout, the Actions API) ends a run quietly when another run's `live` job is not
completed, the predecessor named in `after` excepted; a push, or a check that failed, always
goes on. The `live` job's concurrency group (`flights-live`, never cancelled) keeps one loop at a
time whatever the check saw, so there is never a second writer, and the loop holds no group of
live-ingest or live-read.

## The monthly job

`snowlight flights monthly` (`.github/workflows/flights-monthly.yml`, its own workflow and
concurrency group, so it never holds the live pass; started by every live-ingest tick and gone
on once a UTC day, a marker in the Actions cache saying the day's run started, with a daily cron
as a backstop), in steps
(`snowlight.flights.monthly.run`):

1. check for a newly posted BTS month;
2. fetch what the cached history lacks, through the newest posted month only, for 200 minutes
   at most (a cold start takes several days; each run goes on from what the last kept). A body
   that does not read (an error text, a page for a zip) is skipped like a failed download. The
   cache is saved only when the run kept a file it did not have (a BTS table, bulletin or
   report, or a copy of a day's archive snapshot), even when the run fails, under a new key each
   time (`flights-history-<date>-<run id>-<attempt>`; restore takes the newest) and never over
   1 GB, so the old and the new entry together stay under 2 GB. Only once that save succeeded
   and is listed does the job delete every older flights-history entry and every day marker but
   today's (`gh cache delete`, the job's only `actions: write` use): a failed save leaves the last
   history in place, and the Flights caches never push the Schools caches out of the shared
   10 GB (LR-F7). The
   months the refit needs come first; a run that ran out of time only in the reports of the
   oldest years (2015 to April 2020, used by the own records only) still goes on to publish. A needed month that
   could not be fetched with time to spare is said with `::warning::` (read from the history
   fetch alone, so a day that kept only an archive copy still says it);
3. once the history is whole, read back from the live host which month the published model's
   test year ends with (`v1/flights/model.json`, else the committed model) and which months its
   track record has scored; with nothing new, and the host holding the airports file and a model
   that validates, stop. A host without them (the first run after landing) gets the whole build
   with no month to score;
4. score every month after the published one that the track record lacks, against the day's
   snapshots (a day without one is not scored; a non-weather span's days, and an airline's own
   span days, are left out as in every other count). Each month's score says the month's days
   (`days_in_month`) and the days it was scored on (`days_scored`), so a month scored on part of
   its days never reads as the whole month, and the run says such a month with `::warning::`;
5. refit and test on the newest 12 months, rebuild every file, and publish them with the refit
   model (`v1/flights/model.json`, plain JSON, which the live pass then uses when it is newer
   than the committed one, once it validates against `schemas/flights-model.schema.json`), in
   writes of 6 MB at most, the model and the track record last.

A run stopped anywhere before that write is done again the next day: what is published is read
from the host, never from what the cache holds.

## Past storms

`flights/replays/<id>.json` (the id in lower case): the worst rough days of the test year at busy
airports whose lead-1 departure cancel chance passed the test (ties broken by departures, then
code, so every run picks the same days), replayed from the evening-before run with the model as
published, and MCI on Jan 5, 2025, replayed with a separate fit that leaves its whole winter
(Nov 2024 to Mar 2025) out, on usual rates from before that winter's period. Two choices were
made on the validation year, which holds that winter: the usual rates' window length and which
input groups the model uses; neither fits the model's weights, which never see the winter. Every
replay shows
what the files would have shown: where the airport's own gate fails (MCI's does), the usual
rate with its bit set, never the model's number. Each is marked with how it was kept from the
model.

## Windy days

Are the chances low on windy days (asked after the wind storm of November 26, 2026)?
`snowlight flights wind --raw RAW --gusts GUSTS --out OUT` (`flights.wind`) scores the held-out
test year (October 2025 to September 2026) with the published model, on the rows the live pass
reads (the evening-before 00Z run, lead 1), and the values the files would have shown: the
model's chance where the airport's own gate passed (and the after-storm gate on a day after a
storm), else the usual rate. Each block is put in a band twice: by the run's strongest forecast
gust in it (the forecast path: what the page knew) and by the strongest gust or wind the hourly
reports saw in it (the observed path: what came), so a forecast that missed the wind is told
apart from a model that read it and still said too little. Per band and outcome: blocks, days,
the chance said per flight, what happened, their ratio with a 90% interval from whole days drawn
again 1,000 times with a fixed seed (cancels cluster by day, LR-F5), and the log loss and Brier
score per flight of the values shown and of the usual rate. Two groups: the airports whose chance
for that outcome passed its gate, and EWR, JFK, LGA, PHL, BOS and DCA whatever they show. The
verdict says too low only when, at the airports that passed, on the forecast path, the 35 kt
band's interval for departures cancelled or late lies wholly above 1.15, on 30 days or more;
with fewer days on that line it says too few days to tell for that outcome, never not shown too
low. A line on fewer than 5 days prints no interval (-): drawing one or two days again cannot
give one.
A third table, seen against forecast, splits the blocks the reports saw at 35 kt or more by the
band the forecast had put them in (and adds the blocks forecast at 35 kt or more that the reports
saw under 30 kt), so a rerun keeps the answer to whether the forecast or the model said too
little.

Verdict on the test year: not shown too low. Departures cancelled 1.18 (about 0.8 to 1.5) on 32
days; departures late 1.37 (about 1.0 to 1.8) on 107 days. The second decimal of the bounds moves
with the bootstrap's seed, far below 1.15 either way. No model code changed.

That verdict reads the forecast path, as the rule says. The observed path says the chances were
too low when the wind came: where the reports saw 35 kt or more, the airports that passed said
13.98% of departures late and 18.52% were, 1.32 (1.19 to 1.46) on 282 days, wholly above 1.15.

What else the tables say:

* The whole year ran above what was said, wind or not: under 30 kt, 1.32 for cancels and 1.13
  for late departures, the year's own excess over the usual rates (about 1.3 and 1.15, above).
* No airport passed the gate for arrivals late, so its lines are only in the six's tables. Of the
  six, none passed for cancels and only JFK and PHL for departures late. So at the six, cancels
  are the usual rate on every day, marked as usual, and it does not move with the wind: where
  the reports saw 35 kt or more it said 1.81% and 10.74% were cancelled. The site shows it as the
  usual rate, never as a forecast, beside the FAA state.
* The observed path's excess on late departures is not explained by the forecast missing the
  wind alone. Split by
  what the forecast said (seen against forecast, airports that passed), the blocks the reports
  saw at 35 kt or more ran 1.42 (0.96 to 1.89, 380 blocks on 97 days) where the forecast also
  had 35 kt or more, 1.36 (1.11 to 1.61, 499 blocks) where it had 30-34 kt, and 1.29 (1.16 to
  1.44, 895 blocks) where it had under 30 kt. Where the wind came and was forecast, departures
  late still ran about 1.4 times what was said, by no less than elsewhere. That line alone, on
  97 days, reaches down to 0.96, and blocks under 30 kt already ran 1.13 all year, so these lines
  cannot tell how much of it is the model on a gust it was given and how much is the year's own
  excess.
  The forecast does catch fewer windy blocks (485 forecast at 35 kt or more against 1,774
  the reports saw), but the excess is no smaller where it caught them. Blocks forecast at 35 kt
  or more that the reports saw under 30 kt ran 1.13 (0.81 to 1.41, 30 blocks).
* Departures cancelled split the same way: 1.32 (0.80 to 2.05, 57 blocks) seen and forecast at
  35 kt or more against 1.19 (0.69 to 1.90, 220 blocks) seen at 35 kt or more and forecast under
  30 kt. Where the reports saw 45 kt or more they ran 2.86 (1.42 to 4.80) on 32 days.

The hourly reports of this run (the weather before each run, and the observed peaks) are NCEI's
Local Climatological Data, the same METAR text ISD keeps, read by the ISD reader, while the long
pull's IEM queue held IEM. This backtest's LCD pull had no file for 40 airports (Alaska, Hawaii,
the territories and nine small airports), so they are left out: a gap in this backtest's data,
not in the live pass, which reads their METARs. Seven airport-outcomes among them passed their
gate at lead 1 and are missing from the airports that passed: departures cancelled at BQN, HHH
and ITO, and departures late at HHH, JNU, WRG and XWA (each run names them under its verdict).
They are to be scored once FL-1b's IEM tables exist. `--gusts` is a folder of hourly peaks
(`station`, `hour`, `gust`, `wind`, in knots); without it the observed path is empty. The
validation year is not scored yet: it needs the fit on the years before it, from the whole
history. Once FL-1b restores that history it is to be rerun with that fit, labeled apart from the
test year.

**Forecast gust, airports that passed**

| outcome | band | blocks | days | said | happened | ratio (90%) | log loss shown / usual | Brier shown / usual |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| dep_canc | under 30 kt | 22,946 | 355 | 1.24% | 1.64% | 1.32 (1.16-1.48) | 0.0764 / 0.0818 | 0.01525 / 0.01606 |
| dep_canc | 30-34 kt | 244 | 92 | 5.06% | 4.50% | 0.89 (0.54-1.17) | 0.1588 / 0.2044 | 0.03850 / 0.04379 |
| dep_canc | 35 kt or more | 80 | 32 | 7.30% | 8.60% | 1.18 (0.79-1.50) | 0.2662 / 0.3881 | 0.06487 / 0.08392 |
| dep_canc | 45 kt or more | 1 | 1 | 7.59% | 0.00% | 0.00 (-) | 0.0790 / 0.0124 | 0.00577 / 0.00015 |
| dep_late | under 30 kt | 100,366 | 355 | 9.93% | 11.21% | 1.13 (1.09-1.17) | 0.3359 / 0.3375 | 0.09625 / 0.09666 |
| dep_late | 30-34 kt | 1,258 | 211 | 15.19% | 15.21% | 1.00 (0.84-1.17) | 0.4278 / 0.4411 | 0.13030 / 0.13221 |
| dep_late | 35 kt or more | 485 | 107 | 15.66% | 21.42% | 1.37 (0.99-1.77) | 0.5225 / 0.5764 | 0.16956 / 0.18055 |
| dep_late | 45 kt or more | 39 | 19 | 19.61% | 28.41% | 1.45 (0.78-2.26) | 0.6926 / 0.8005 | 0.22681 / 0.24723 |
| arr_canc | under 30 kt | 40,395 | 355 | 1.11% | 1.32% | 1.19 (1.05-1.33) | 0.0642 / 0.0684 | 0.01226 / 0.01296 |
| arr_canc | 30-34 kt | 420 | 142 | 2.26% | 2.59% | 1.15 (0.58-1.72) | 0.1115 / 0.1286 | 0.02445 / 0.02540 |
| arr_canc | 35 kt or more | 126 | 51 | 2.35% | 3.14% | 1.34 (0.43-2.16) | 0.1220 / 0.1482 | 0.02861 / 0.03069 |
| arr_canc | 45 kt or more | 5 | 4 | 5.00% | 7.14% | 1.43 (-) | 0.2395 / 0.3552 | 0.06291 / 0.07042 |

**Forecast gust, EWR JFK LGA PHL BOS DCA**

| outcome | band | blocks | days | said | happened | ratio (90%) | log loss shown / usual | Brier shown / usual |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| dep_canc | under 30 kt | 10,348 | 355 | 2.11% | 3.55% | 1.68 (1.35-2.06) | 0.1498 / 0.1498 | 0.03382 / 0.03382 |
| dep_canc | 30-34 kt | 195 | 35 | 1.27% | 9.14% | 7.22 (3.90-11.25) | 0.3926 / 0.3926 | 0.08848 / 0.08848 |
| dep_canc | 35 kt or more | 95 | 19 | 1.43% | 17.67% | 12.39 (4.71-23.63) | 0.7528 / 0.7528 | 0.17112 / 0.17112 |
| dep_canc | 45 kt or more | 2 | 1 | 2.18% | 100.00% | 45.92 (-) | 3.8294 / 3.8294 | 0.95692 / 0.95692 |
| dep_late | under 30 kt | 10,348 | 355 | 10.51% | 12.44% | 1.18 (1.13-1.23) | 0.3614 / 0.3619 | 0.10580 / 0.10592 |
| dep_late | 30-34 kt | 195 | 35 | 10.84% | 19.64% | 1.81 (1.49-2.11) | 0.5251 / 0.5285 | 0.16444 / 0.16493 |
| dep_late | 35 kt or more | 95 | 19 | 10.60% | 18.41% | 1.74 (1.31-2.39) | 0.4992 / 0.5073 | 0.15444 / 0.15608 |
| dep_late | 45 kt or more | 2 | 1 | 6.90% | 0.00% | 0.00 (-) | 0.0716 / 0.0716 | 0.00497 / 0.00497 |
| arr_canc | under 30 kt | 10,358 | 355 | 2.13% | 3.51% | 1.64 (1.31-2.01) | 0.1494 / 0.1494 | 0.03355 / 0.03355 |
| arr_canc | 30-34 kt | 195 | 35 | 1.20% | 9.05% | 7.53 (4.10-11.83) | 0.3920 / 0.3920 | 0.08770 / 0.08770 |
| arr_canc | 35 kt or more | 95 | 19 | 1.47% | 18.66% | 12.68 (5.59-22.56) | 0.7901 / 0.7901 | 0.18060 / 0.18060 |
| arr_canc | 45 kt or more | 2 | 1 | 2.21% | 100.00% | 45.33 (-) | 3.8208 / 3.8208 | 0.95637 / 0.95637 |
| arr_late | under 30 kt | 10,358 | 355 | 11.70% | 13.71% | 1.17 (1.11-1.23) | 0.3861 / 0.3861 | 0.11501 / 0.11501 |
| arr_late | 30-34 kt | 195 | 35 | 9.48% | 22.76% | 2.40 (1.95-2.88) | 0.6016 / 0.6016 | 0.19005 / 0.19005 |
| arr_late | 35 kt or more | 95 | 19 | 9.27% | 23.25% | 2.51 (1.75-3.64) | 0.6358 / 0.6358 | 0.19722 / 0.19722 |
| arr_late | 45 kt or more | 2 | 1 | 6.32% | 0.00% | 0.00 (-) | 0.0653 / 0.0653 | 0.00399 / 0.00399 |

**Observed gust, airports that passed**

| outcome | band | blocks | days | said | happened | ratio (90%) | log loss shown / usual | Brier shown / usual |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| dep_canc | under 30 kt | 22,266 | 355 | 1.22% | 1.60% | 1.31 (1.14-1.47) | 0.0747 / 0.0800 | 0.01487 / 0.01568 |
| dep_canc | 30-34 kt | 575 | 216 | 2.73% | 3.74% | 1.37 (1.08-1.71) | 0.1530 / 0.1765 | 0.03312 / 0.03645 |
| dep_canc | 35 kt or more | 372 | 145 | 3.52% | 4.22% | 1.20 (0.86-1.59) | 0.1642 / 0.1957 | 0.03871 / 0.04118 |
| dep_canc | 45 kt or more | 40 | 32 | 2.82% | 8.06% | 2.86 (1.42-4.80) | 0.3164 / 0.3728 | 0.07598 / 0.07881 |
| dep_late | under 30 kt | 96,791 | 355 | 9.84% | 11.04% | 1.12 (1.09-1.16) | 0.3329 / 0.3343 | 0.09509 / 0.09546 |
| dep_late | 30-34 kt | 2,749 | 329 | 12.85% | 14.48% | 1.13 (1.00-1.24) | 0.4024 / 0.4093 | 0.12104 / 0.12244 |
| dep_late | 35 kt or more | 1,774 | 282 | 13.98% | 18.52% | 1.32 (1.19-1.46) | 0.4680 / 0.4845 | 0.14787 / 0.15115 |
| dep_late | 45 kt or more | 244 | 107 | 17.02% | 25.52% | 1.50 (1.12-1.93) | 0.5860 / 0.6348 | 0.19649 / 0.20735 |
| arr_canc | under 30 kt | 39,123 | 355 | 1.10% | 1.30% | 1.19 (1.04-1.32) | 0.0636 / 0.0677 | 0.01210 / 0.01280 |
| arr_canc | 30-34 kt | 1,117 | 266 | 1.52% | 1.85% | 1.21 (0.80-1.71) | 0.0864 / 0.0942 | 0.01770 / 0.01814 |
| arr_canc | 35 kt or more | 615 | 200 | 2.16% | 2.90% | 1.34 (0.82-1.96) | 0.1165 / 0.1377 | 0.02682 / 0.02829 |
| arr_canc | 45 kt or more | 82 | 55 | 2.48% | 3.48% | 1.41 (0.84-1.94) | 0.1473 / 0.1653 | 0.03308 / 0.03406 |

**Observed gust, EWR JFK LGA PHL BOS DCA**

| outcome | band | blocks | days | said | happened | ratio (90%) | log loss shown / usual | Brier shown / usual |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| dep_canc | under 30 kt | 9,867 | 355 | 2.12% | 3.37% | 1.59 (1.28-1.94) | 0.1435 / 0.1435 | 0.03212 / 0.03212 |
| dep_canc | 30-34 kt | 462 | 121 | 1.63% | 8.04% | 4.95 (3.13-7.14) | 0.3199 / 0.3199 | 0.07614 / 0.07614 |
| dep_canc | 35 kt or more | 309 | 72 | 1.81% | 10.74% | 5.95 (3.39-9.25) | 0.4430 / 0.4430 | 0.10310 / 0.10310 |
| dep_canc | 45 kt or more | 33 | 19 | 2.38% | 22.07% | 9.29 (2.71-19.18) | 0.8662 / 0.8662 | 0.21109 / 0.21109 |
| dep_late | under 30 kt | 9,867 | 355 | 10.47% | 12.31% | 1.18 (1.12-1.22) | 0.3591 / 0.3595 | 0.10490 / 0.10501 |
| dep_late | 30-34 kt | 462 | 121 | 10.63% | 15.34% | 1.44 (1.25-1.62) | 0.4263 / 0.4283 | 0.12900 / 0.12935 |
| dep_late | 35 kt or more | 309 | 72 | 11.66% | 18.99% | 1.63 (1.41-1.84) | 0.4926 / 0.4966 | 0.15461 / 0.15546 |
| dep_late | 45 kt or more | 33 | 19 | 13.78% | 23.81% | 1.73 (1.37-2.04) | 0.5550 / 0.5601 | 0.18272 / 0.18368 |
| arr_canc | under 30 kt | 9,876 | 355 | 2.15% | 3.31% | 1.54 (1.25-1.86) | 0.1426 / 0.1426 | 0.03177 / 0.03177 |
| arr_canc | 30-34 kt | 463 | 121 | 1.61% | 7.71% | 4.80 (3.08-6.79) | 0.3141 / 0.3141 | 0.07350 / 0.07350 |
| arr_canc | 35 kt or more | 309 | 72 | 1.73% | 11.01% | 6.35 (3.65-9.44) | 0.4555 / 0.4555 | 0.10590 / 0.10590 |
| arr_canc | 45 kt or more | 33 | 19 | 2.46% | 20.32% | 8.28 (3.48-15.70) | 0.8096 / 0.8096 | 0.19486 / 0.19486 |
| arr_late | under 30 kt | 9,876 | 355 | 11.72% | 13.55% | 1.16 (1.10-1.21) | 0.3834 / 0.3834 | 0.11393 / 0.11393 |
| arr_late | 30-34 kt | 463 | 121 | 10.36% | 17.11% | 1.65 (1.40-1.89) | 0.4634 / 0.4634 | 0.14221 / 0.14221 |
| arr_late | 35 kt or more | 309 | 72 | 11.07% | 22.03% | 1.99 (1.66-2.32) | 0.5681 / 0.5681 | 0.17989 / 0.17989 |
| arr_late | 45 kt or more | 33 | 19 | 12.87% | 28.13% | 2.18 (1.81-2.53) | 0.6445 / 0.6445 | 0.21438 / 0.21438 |

**Seen against forecast, airports that passed**

| outcome | band | blocks | days | said | happened | ratio (90%) | log loss shown / usual | Brier shown / usual |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| dep_canc | seen 35 kt or more, forecast under 30 kt | 220 | 129 | 2.40% | 2.85% | 1.19 (0.69-1.90) | 0.1319 / 0.1376 | 0.02885 / 0.02791 |
| dep_canc | seen 35 kt or more, forecast 30-34 kt | 95 | 48 | 4.88% | 5.53% | 1.13 (0.73-1.62) | 0.1901 / 0.2467 | 0.04841 / 0.05363 |
| dep_canc | seen 35 kt or more, forecast 35 kt or more | 57 | 26 | 6.79% | 8.95% | 1.32 (0.80-2.05) | 0.2856 / 0.4047 | 0.07214 / 0.08734 |
| dep_canc | forecast 35 kt or more, seen under 30 kt | 6 | 4 | 8.46% | 2.44% | 0.29 (-) | 0.1204 / 0.1216 | 0.02395 / 0.02401 |
| dep_late | seen 35 kt or more, forecast under 30 kt | 895 | 266 | 13.94% | 18.04% | 1.29 (1.16-1.44) | 0.4550 / 0.4597 | 0.14322 / 0.14402 |
| dep_late | seen 35 kt or more, forecast 30-34 kt | 499 | 141 | 12.90% | 17.54% | 1.36 (1.11-1.61) | 0.4638 / 0.4895 | 0.14447 / 0.14960 |
| dep_late | seen 35 kt or more, forecast 35 kt or more | 380 | 97 | 15.83% | 22.42% | 1.42 (0.96-1.89) | 0.5378 / 0.5980 | 0.17598 / 0.18844 |
| dep_late | forecast 35 kt or more, seen under 30 kt | 30 | 20 | 15.45% | 17.48% | 1.13 (0.81-1.41) | 0.4541 / 0.4811 | 0.14189 / 0.14611 |
| arr_canc | seen 35 kt or more, forecast under 30 kt | 365 | 178 | 1.89% | 2.23% | 1.18 (0.85-1.59) | 0.0971 / 0.1054 | 0.02099 / 0.02173 |
| arr_canc | seen 35 kt or more, forecast 30-34 kt | 159 | 78 | 2.45% | 3.28% | 1.34 (0.50-2.16) | 0.1299 / 0.1630 | 0.03046 / 0.03220 |
| arr_canc | seen 35 kt or more, forecast 35 kt or more | 91 | 37 | 2.95% | 5.28% | 1.79 (0.49-2.91) | 0.1829 / 0.2425 | 0.04725 / 0.05155 |
| arr_canc | forecast 35 kt or more, seen under 30 kt | 11 | 9 | 2.12% | 2.91% | 1.37 (0.25-2.70) | 0.1296 / 0.1409 | 0.02737 / 0.02855 |

**Seen against forecast, EWR JFK LGA PHL BOS DCA**

| outcome | band | blocks | days | said | happened | ratio (90%) | log loss shown / usual | Brier shown / usual |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| dep_canc | seen 35 kt or more, forecast under 30 kt | 153 | 68 | 2.23% | 8.05% | 3.61 (2.27-5.24) | 0.3150 / 0.3150 | 0.07628 / 0.07628 |
| dep_canc | seen 35 kt or more, forecast 30-34 kt | 86 | 23 | 1.38% | 8.46% | 6.14 (3.21-10.36) | 0.3681 / 0.3681 | 0.08182 / 0.08182 |
| dep_canc | seen 35 kt or more, forecast 35 kt or more | 70 | 17 | 1.45% | 19.54% | 13.45 (5.29-25.91) | 0.8170 / 0.8170 | 0.18877 / 0.18877 |
| dep_canc | forecast 35 kt or more, seen under 30 kt | 8 | 5 | 1.32% | 7.04% | 5.32 (0.95-12.35) | 0.3342 / 0.3342 | 0.06906 / 0.06906 |
| dep_late | seen 35 kt or more, forecast under 30 kt | 153 | 68 | 12.17% | 18.91% | 1.55 (1.34-1.76) | 0.4771 / 0.4785 | 0.15041 / 0.15079 |
| dep_late | seen 35 kt or more, forecast 30-34 kt | 86 | 23 | 11.44% | 20.98% | 1.83 (1.48-2.13) | 0.5385 / 0.5454 | 0.17176 / 0.17324 |
| dep_late | seen 35 kt or more, forecast 35 kt or more | 70 | 17 | 10.85% | 16.56% | 1.53 (1.10-2.16) | 0.4657 / 0.4711 | 0.14107 / 0.14212 |
| dep_late | forecast 35 kt or more, seen under 30 kt | 8 | 5 | 10.43% | 22.24% | 2.13 (1.18-2.91) | 0.5633 / 0.5705 | 0.18096 / 0.18237 |
| arr_canc | seen 35 kt or more, forecast under 30 kt | 153 | 68 | 2.10% | 8.16% | 3.89 (2.23-5.99) | 0.3222 / 0.3222 | 0.07766 / 0.07766 |
| arr_canc | seen 35 kt or more, forecast 30-34 kt | 86 | 23 | 1.30% | 8.05% | 6.19 (3.17-10.45) | 0.3535 / 0.3535 | 0.07806 / 0.07806 |
| arr_canc | seen 35 kt or more, forecast 35 kt or more | 70 | 17 | 1.47% | 21.20% | 14.40 (6.46-26.09) | 0.8851 / 0.8851 | 0.20487 / 0.20487 |
| arr_canc | forecast 35 kt or more, seen under 30 kt | 8 | 5 | 1.38% | 6.71% | 4.86 (0.24-12.26) | 0.3173 / 0.3173 | 0.06578 / 0.06578 |
| arr_late | seen 35 kt or more, forecast under 30 kt | 153 | 68 | 12.42% | 21.17% | 1.70 (1.40-2.00) | 0.5252 / 0.5252 | 0.16787 / 0.16787 |
| arr_late | seen 35 kt or more, forecast 30-34 kt | 86 | 23 | 9.93% | 24.30% | 2.45 (1.99-2.89) | 0.6287 / 0.6287 | 0.20129 / 0.20129 |
| arr_late | seen 35 kt or more, forecast 35 kt or more | 70 | 17 | 9.46% | 21.08% | 2.23 (1.54-3.28) | 0.5877 / 0.5877 | 0.17970 / 0.17970 |
| arr_late | forecast 35 kt or more, seen under 30 kt | 8 | 5 | 10.21% | 27.82% | 2.72 (1.31-3.98) | 0.7250 / 0.7250 | 0.23137 / 0.23137 |

## Running it locally

From `pipeline/`:

```
uv run snowlight flights train --out OUT --model data/flights/model.json.gz
uv run snowlight flights static --out OUT
uv run snowlight flights live --host dir --host-dir OUT/host
```

`train` and `static` read the history under `/dev/shm/flights` (`--raw` to change it), fetched
by the same functions the monthly job uses (`snowlight.flights.history`). The fit refuses to run
while a month of hourly reports it needs is missing (it would count that month's storms as none).

`uv run snowlight flights seed --out OUT --host github` publishes a checked local build (`OUT`
holding `files/` and `model.json.gz`) once, through the same writes: the integrator's step so
the files are on the host at landing. Nothing is written unless every file validates.
