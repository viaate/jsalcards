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

Two spans are left out of fitting and testing, because their cancellations were not weather:
July 19-23, 2024 (the airline computer outage) and November 7-15, 2025 (the FAA's ordered flight
cuts in the shutdown).

## The held-out test and the gate

The test year is the newest 12 posted BTS months. It is never used to fit or to choose a
setting. For every airport, target and lead, the test scores the Brier score per departure (or
per day) against the airport's own usual rate. A chance is published only where all of these
hold (`model.passes`):

* skill above 0 (a lower Brier score than the usual rate), on the whole year and on each half
  of it (the even and the odd ISO weeks);
* at least 10 events in the test year (2 rough days for the rough-day chance);
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
  airport's chance is published for that target and lead (today: neither late target, at any
  lead; their skill out of selection is under 1%, so every airport shows its usual late rate).

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
same test with the non-weather spans put back, and the validation-year checks behind each input
group.

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

`snowlight flights live --host github` (`.github/workflows/flights-live.yml`). The workflow is
started by every run of live-ingest.yml (the owner's 5-minute timer, the way chances-watch.yml
is started) and goes on only when `v1/flights/latest.json`, read from the live host's repository
(not the Pages cache, whose copy can be 10 minutes old), is 15 minutes old or more,
so a pass runs about every 20 minutes; GitHub's own schedule on this repository fires only a few
times a day, so its hourly cron is a backstop. A pass:

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
   snapshots (a day without one is not scored). Each month's score says the month's days
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
