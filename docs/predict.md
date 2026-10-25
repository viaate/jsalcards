# Snow-day chances: runbook

`snowlight predict` (pipeline/snowlight/predict) gives every public school district, and
every private school of the contiguous states, a chance of no school today and tomorrow,
every school day, in `predictions/latest.json`
on the live host, beside `live/closings.json`. The page reads it from the live root
(`VITE_SNOWLIGHT_LIVE_ROOT`, defaulted in `.github/workflows/preview.yml` to
`https://viaate.github.io/snowlight-live/v1/`) and hides it once it is 90 minutes old.

Piece 1 (this): pooled rates per weather situation, the base alone in "How we got N%",
and the district's own record where it has one. Late October means 1% almost
everywhere: 1% is the lowest number shown. Numbers rise when the weather service issues a
winter storm warning or advisory for the area.

## The model as fit (piece 1, round 2)

- Labels (`predict labels`, internal): 5,134 district-days a station that carries the
  district read that morning (06:30 to 09:30 local): 1,547 no school, 109 delayed, 732 open,
  2,746 unknown. A district is labeled only from what a kept morning list can show
  (`snowlight/predict/labels.py`); unknown, never open, when:
  - the replay step dropped the station's only morning read (`dropped_read`, 163);
  - the station has fewer than 5 populated captures in the archive, so a whole list cannot
    be told from a partial one (`thin_station`, 1,458; its empty reads still count);
  - on a storm day the list held under half the station's median rows (`small_capture`,
    35), or only an empty list with no market peer reading (`empty_uncorroborated`, 66);
  - a list named the district in a row the replay step did not light (`listed_unread`,
    434: the 100-label audit found eight such districts labeled open while their rows
    said closed or delayed);
  - on a storm day it was absent from the lists while at least half of its market closed
    (`absent_in_storm`, 176: the audit found districts left off full lists that day);
  - a likely break day (`break`, 162), or more than a tenth but under half lit
    (`partly_lit`, 252).
  A station carries a district from the first day it listed it (never earlier), when it
  listed it on 2 or more days.
- The 100-label audit (`out/internal/predict/labels-audit.{md,jsonl}` and
  `labels-audit-verdicts.md`, internal: they hold list rows): every label with its morning
  reads, its rows and a verdict. 50 of 50 no-school labels are correct (the row says closed
  or remote for the day). Of 50 open labels: 2 correct by their rows (school ran), 47
  consistent (an empty list on a quiet day, or absent from a full list), 1 doubtful (a
  statewide district of state schools). No label in the sample is wrong by its rows.
- Rates (`snowlight/predict/pool.py`): own rate from 4 labeled days, a pooled level from
  8, each `m` chosen per level and class group by leave-one-season-out log loss inside the
  training seasons only (grid 1 to 1024), all fixed before the backtest ran. Round 1's
  values (m = 1024 everywhere, own 1,024 days, levels 64) were picked after looking at the
  walk-forward test seasons, so that backtest was not out of sample, and in effect it
  published the national rate per situation.
- The base sentence is true of what it names (spec addenda b and d): a level is named only
  when its own days hold at least half the weight (`n >= m`) and the share the website says
  for its published chance is true of that level's recorded days, `y` closed or remote of
  `n` (`snowlight/predict/share.py`, `says_true`): an exact share ("3 in 4") only when `y/n`
  rounds to the same whole percent, "more than 3 in 5" only when `y/n` is above 3/5,
  "almost never" (1%, the floor) only under 1 in 20 and "almost always" (99%, the ceiling)
  only over 19 in 20. Otherwise the base moves up the chain to the nation ("Districts across
  the country ...", contract C1b: `PooledBase.scope` may be `nation`), whose rate is its
  record `Y/N`, so its sentence is true by construction. The share rule is one rule in two
  languages: `pipeline/tests/predict/golden/shares.json` holds it for every percent and both
  `tests/predict/test_share.py` and `web/src/copy.test.ts` check their side against it.
  `tests/predict/test_truth.py` checks, with exact fractions, every cell of the committed
  model and of a served model against the counts of the level it names. With the committed
  model the bases name the nation, region, state, county and nearby districts; no district's
  own record is named (a shrunk own rate does not round to its own few days), so no record
  is shown under a base.
- A situation with fewer than 30 labeled days in the nation is not modeled: it publishes its
  fallback's rates, never the 1 in 2 of an empty count. The config allows lake effect snow,
  blizzard, ice, cold and tropical warnings to take the winter storm warning's rates, and
  the day after a snow day (plain or advisory) the same weather's without it; the committed
  model borrows only for ice, lake_snow, tropical, none_after and advisory_after (blizzard
  and cold have enough labeled days and are modeled). Its base is `borrowed` (contract C1c, `AlertBase`, `SimilarDaysBase` and
  `PooledBase` carry `borrowed`), and the sentence names the days it counts first: "The
  chance is counted over recorded days with a winter storm warning. Districts across the
  country closed or went remote on 9 in 10 of them." Today ice, lake effect snow and
  tropical warnings borrow the winter storm warning's days, and the day after a snow day the
  plain or advisory day's. The advisory and cold classes mix VTEC codes and lake effect snow
  and tropical warnings have no published alert kind, so their bases name the weather of
  the days counted instead (addendum e, E2; `SimilarDaysBase.weather` and
  `PooledBase.weather`, additive): "recorded winter advisory days" (winter weather,
  freezing rain and lake effect snow advisories), "recorded cold warning days" (extreme
  cold and wind chill warnings), "recorded lake effect snow warning days", "recorded
  hurricane or tropical storm warning days". The name claims the share over all the place's
  days of that weather, so it is said only where that is true (`serve.whole_weather`): never
  over the days after a snow day (the advisory days after one are a smaller set, said "days
  like this"), and over the other advisory days only where the level the base names holds no
  advisory day after a snow day (in the same source: recorded, or read live for a live base).
  The committed model holds none, so today every advisory base names it; once live days
  after a snow day are counted, the levels holding them say "days like this" again, and a
  base anchored on the live days names it less as the winter goes on (the nation's level
  holds every district's days, so one such day there takes the name from every pooled
  base). Keeping it would take the borrowed form ("recorded winter advisory days that did
  not follow a recorded snow day") on a day that is not borrowed, which waits for the
  owner's word on the copy. Days
  with no winter alert always say "days like this". The share check
  (`tests/predict/test_truth.py`) judges a named sentence against all the weather's days. A
  borrowed day after a snow day says "The chance is counted over
  recorded days like this that did not follow a recorded snow day" (or "recorded winter
  advisory days that did not follow a recorded snow day"): the counted days are
  those whose previous school day is not labeled no school, and most have no record of that
  day at all, so the sentence never says they did not follow a snow day (`web/src/copy.test.ts`
  pins it, and every "snow day" in a base sentence is "a recorded snow day").
- Every base sentence counts the recorded days, in the past tense (spec addendum
  2026-10-20 d, item 4), and says "closed or went remote", since a day with no school counts
  both (55 of the 1,547 no-school labels are remote): "Districts in Shawnee Mission’s region
  closed or went remote on 3 in 4 of their recorded days with a winter storm warning." (a
  pooled count is of district-days), "Shawnee Mission almost never closed or went remote on
  recorded days like this.", "After a recorded snow day, Shawnee Mission stayed closed or
  went remote the next day 1 time in 4." No sentence claims a share of all the warnings the
  weather service issues (`web/src/copy.test.ts`, "counts every base over the recorded
  days").
- "Recorded days with a winter storm warning" (and a blizzard or ice storm warning) means
  the district-days whose weather class was that alert's (`snowlight/predict/situations.py`):
  the strongest class that, with itself or a stronger class, covered at least half of the
  district's schools (`covered_share`), from alerts issued by the morning snapshot. A day
  whose blizzard or ice storm warning outranked the winter storm warning is counted as a
  blizzard or ice day, and a warning over fewer schools or issued after the snapshot does
  not count, so the sentence's days are the ones the class counted, the same rule that
  gives today's class and so today's base. The share in the sentence is true of those days
  (`tests/predict/test_truth.py`); it is not measured over every day any winter storm warning
  touched the district (the archive keeps one class per district-day).
- Backtest (`out/internal/predict/backtest/report.md`, internal), with the truth rule above:
  storm district-day Brier 0.1090 against 0.1188 for the national rate per class (B0), all
  rows 0.0774 against 0.0844; pooled G1 passes with and without 2020-21. The truth rule
  costs accuracy: before it (round 3, a 0.05 tolerance) the storm Brier was 0.0888, and the
  national rate per class and region (B1, 0.1053) now does better than the model; that is
  reported, not gated.
- Piece 1 gate (spec addendum 2026-10-20 d): G4 (the leakage tests in `tests/predict`, run by
  pytest with every gate; the report does not compute it) and pooled G1 (model against B0,
  with and without 2020-21) gate piece 1, and both pass. G1 per season, G2 and G3 are
  reported, not gated, because the model and B0 are judged on the same labels, which the
  archive biases high under alerts:
  - G1 by season (amended gate, addendum b): 2023-24 (567 storm rows) +0.0117 against B0,
    over the 0.005 tolerance; the other seasons have under 300 storm rows: 2020-21 (185)
    -0.0093, 2021-22 (20) +0.0121, 2022-23 (225) +0.0072, 2024-25 (131) -0.1524, 2025-26
    (257) -0.0012.
  - G2: every bin with enough rows and clusters is within its bound.
  - G3: closings given 50% or more 91.4% against B0's 98.1% (B0 gives every storm class 50%
    or more, so it catches nearly every closing), at precision 0.889 against B0's 0.896.
- Launch gate (before the public launch, addendum d item 3): the storm classes' absolute
  levels are re-anchored on live-read days (complete daily reads of every list this winter)
  by piece 3's automatic retrain under its no-worse rule. Until then the alert-class chances
  are what the recorded storms say, and the why sentence says exactly that.
- Known bias: the archive holds lists mostly from storm days it was asked to capture, and
  absence on a storm day is no longer read as open, so the labeled rates under a warning
  are high (winter storm warning 817 of 860 closed, advisory 495 of 667). The nation's
  sentence is true of the labeled days, not of every warning the weather service issues.
- The day after a closing comes from the live ingest's day timeline for the school day
  before (`live/days/<day>.json` on the live host): a district at least half of whose
  schools ended that day closed or remote for weather. Only a timeline the host does not
  hold means no district had the day off; one that cannot be read, or that indexes another
  directory and shows a closing, darkens the pass.

## Heights in alerts (addendum e, E1)

A winter alert for a mountain zone often applies only to part of it: on October 22, 2026
the Winter Weather Advisories KHNX WW.Y 0005 (zone CAZ323) and KREV WW.Y 0009 (CAZ073) said
"above 8,000 feet", and the zone polygons reached Yosemite-Wawona's school at 4,068 ft and
Eastern Sierra's at 5,150 to 6,800 ft, which then showed 74% from the nation's advisory
rate. The serving pass now reads those lines and counts a school as reached by such an
alert only within the heights it names.

- What is read (`snowlight/sources/nws/elevation.py`): a band phrase is "above N feet"
  ("elevations above N", "N feet and above", "N feet and higher"), "below N feet" ("N feet
  and below") or "between N and M feet" ("from N to M feet"), `ft` too. Only the numbers are
  kept (on the live event and in the pass's alert memory), never the text. Most band phrases
  in an alert do not say where it applies: they qualify an amount ("3 to 5 feet above 7000
  feet" in a Lake Tahoe warning whose basin lies at 6,200 ft), a wind, or one of several
  areas ("Grand and Summit Counties below 9000 feet, South Park, Byers, and Limon"). So a
  band counts only from a statement of where the alert applies, one band and nothing else:
  the `NWSheadline` when it is the product's own line ("... IN EFFECT UNTIL 5 PM ABOVE 8000
  FEET", "... REMAINS IN EFFECT FOR ELEVATIONS ABOVE 7000 FEET"), with nothing after the
  band but when or the one area it lies in ("... ABOVE 5000 FEET IN JOSEPHINE COUNTY AND FOR
  SOUTH CENTRAL OREGON" is no statement), or a `WHERE` paragraph that is a band, a band over
  the areas it names ("Above 8,000 feet in the Sierra Nevada") or one area and its band
  ("Mono County above 7500 feet"). A `WHAT` paragraph is never one ("Snow above 7000 feet. A
  rain and snow mix around 6000 feet." speaks of the weather), nor a headline that is not
  the product line ("HEAVY SNOW EXPECTED ABOVE 7000 FEET"). A statement may carry no amount,
  wind or hedge ("inches", "gusts", "heaviest", "locally", "mainly", "except", "as well
  as"). There is no limit, and the alert reaches its whole zones as before, when no
  statement names a band; when any part of the alert speaks of the lower ground in words
  ("lower elevations", "all elevations", "all of", "valleys", "valley floor", "foothills",
  "lake level", "snow levels", "down to", "as low as", "lowering to", "thousand feet"); when
  it names any height outside a band phrase that lies outside the stated bands ("as low as
  3500 feet", "a pass at 4489 ft" under "above 4500 feet", any "5 kft"); or when any band
  phrase anywhere in its headlines or description reaches outside the stated bands ("1 to 4
  inches between 3000 and 5000 feet" under "above 5000 feet"). Several stated bands are one
  limit: a school in any of them is reached. So a limit leaves out only ground that a
  statement of where the alert applies leaves out and no other part of the alert names, and
  any other wording counts the whole zone. Amounts named for towns ("4 to 8 inches in
  Truckee") are not judged against the band: the statement already says whether those towns
  lie in it. Checked on 1,655 distinct segments of public winter weather messages from 21
  western offices (IEM AFOS, 2023-2026, full descriptions): 244 get a limit, every one from
  such a statement (216 from the headline); a reviewed sample of 45 is the test fixture
  `tests/weather/fixtures/wsw-elevation-sample.json`.
- The rule (`serve.reached_by`): a school is reached by an "above N" alert when its height
  is at least N minus 500 ft (`serve.elevation_margin_feet` in `config/predict.yaml`), by
  "below N" when at most N plus 500 ft, by "between" likewise. A school whose height is not
  known is reached, and each pass logs the count: `predict: 2 alerts name heights; 6 schools
  of their zones lie outside them, 0 with no known height counted as reached`.
- Serve only, as the cancel and upgrade rule: the season CSVs the model is trained on carry
  no alert text, so training counts each zone whole. The live pass is the stricter of the
  two here. The learning step's snapshots record each district's class with every alert
  reaching its whole zones, as the history labels count them, so the days learned live mean
  what the archive's days mean; only the served chance uses the heights.
- The heights (`snowlight/elevation`): one table of every school of the directory, by NCES
  id and point, in whole feet, read from Terrain Tiles (Mapzen's Terrarium PNG tiles on AWS
  Open Data, `s3://elevation-tiles-prod`, zoom 11, pixels about 60 m across in the states;
  bilinear between the four pixel centers around the school). It is built only by
  `.github/workflows/elevation.yml`, on a push that changes `config/directory.yaml`,
  `config/elevation.yaml` or the workflow: the job builds the directory from the data
  mirror (as Preview does), reads each tile once (about 14,200 tiles for 118,000 schools),
  and puts the table in the data mirror release of the current pins as
  `school-elevations-<first 16 hex of its SHA-256>.json.gz`, so a rebuild never replaces a
  pinned table. The run's summary gives the `table` block to pin in
  `config/elevation.yaml` (URL, SHA-256, schools, unknown, and `directory_sha256`, the content
  digest of the directory it was built from); committing it runs the job again, which checks
  the table it builds is the pinned one. A table built from the pinned table's very directory
  that is not the pinned one (other tile bytes, or tiles that did not read) fails the run
  before anything is uploaded (`snowlight elevation pinned --directory`, exit 3).
- The predict pass reads only the pinned table (`snowlight/predict/heights.py`), from
  `.cache/elevation` when the cached bytes have the pinned SHA-256, else from the pin's URL,
  and uses it only when its bytes and counts are the pin's. A school's height counts only
  when the table has a row for its NCES id at its very point in the deployed directory; a
  school added or moved since is unknown until the table is rebuilt and pinned. With no
  table pinned, or none readable, no height is known and every alert reaches its whole
  zones (the pass warns). A failed download is tried again 15 minutes later (the loop runs
  for hours), and a remembered alert whose stored heights do not read is kept reaching its
  whole zones (the pass warns with the count). Nothing in the deploy or the predict loop
  reads the tiles.
- Checked against USGS (EPQS) at the eight schools those advisories reached: the zoom 11
  heights are within 9 ft of USGS's (Wawona 4,069 against 4,068; Mammoth 7,808 and 7,854
  against 7,805 and 7,852; Lee Vining 6,798 and 6,751 against 6,806 and 6,754).
- Attribution (required by the tiles' sources for the data used; the joerd project's
  attribution page): "Terrain Tiles by Mapzen on AWS Open Data. United States 3DEP
  (formerly NED) and global GMTED2010 and SRTM terrain data courtesy of the U.S. Geological
  Survey. Global ETOPO1 terrain data courtesy of the U.S. National Oceanic and Atmospheric
  Administration." It is in `config/elevation.yaml`, the README's data section and the
  map's credits (the attribution button, beside the map tiles' credits).
- Bumping: a new directory edition (a pin bump in `config/directory.yaml`) runs the
  workflow; pin the new block it prints. Until then the old table serves every school it
  holds at the same point, and the rest are unknown (reached).

## Places with no record of their own (spec addendum 2026-10-24 e and f)

- **Thin (E3b).** A base that names the nation because the district's region holds fewer than
  `level_min_days` (8) labeled days of the situation published carries `thin: true`
  (`PooledBase.thin`, additive; `pool.thin_cells`), never with `live` (a situation read live
  names the nation's live record). The chance is still the nation's record and the sentence
  is true of it. The flag says only that, on any situation, the plain no-alert one too: a
  calm day in the West is often thin. With the committed model, 4,191 of the 18,227
  districts are thin under an advisory (all of California and Nevada among them) and publish
  the nation's 74%.
- **When "Few local records" shows (owner, 2026-10-25: "only when it is actually
  happening").** The web shows it as the owner approved on 2026-10-24 (mockup B): the chance
  number in the panel's gray (`--text-2`, 7.8:1 on the panel) and "Few local records" on its
  own line directly under "Chance of no school <day>". It shows only for a forecast whose day
  has a weather alert **and** whose base carries `thin` (`fewLocalRecords` in
  `web/src/app/chance.ts`). The alert is read from the forecast's `reasons`, which the pass
  writes from the day's alert class (`why.reasons_for`): an advisory, a winter storm, ice
  storm, blizzard, lake effect snow, extreme cold or wind chill, hurricane or tropical storm
  warning names its weather there, and a day with none of them (class `none`, the day after
  a snow day without one too) leaves it empty. A watch or a cold weather advisory makes no
  class (they are heads-ups), so such a day's chance is counted over calm days and shows no
  marker. A day with no threat (`no_threat`), a weekend, a posted status and a file without
  the flag show no marker either (`forecastDetail` reads `thin` from the base alone, true
  only on a pooled nation base not read live). In the ZIP code's area panel it shows only
  where every school the number counts is counted by such a forecast (a posted status, a day
  with no threat, a day with no alert or a chance with local records in the mix leaves it
  off). Nothing else changes: on a calm thin day the panel looks as it did before the marker.
  The 12:09Z pass of 2026-10-25 had 3,146 thin district-days (Monday, all calm): the marker
  showed on all 3,146 before this rule and on none after.
- **Advisory rates stay the archive's recorded days.** Under an advisory alone every district
  is above 50%: the nation's record is 495 of 667 recorded days (74%), and those days come
  mostly from the storm days the archive captured. Two ways to an honest lower rate were
  tried on 2026-10-24 and neither can be shipped:
  - *Calibration on held-out rows (E3a).* Levers fixed before a walk-forward backtest run once
    (the nation's rate counted by storm-day cluster, or earlier seasons' held-out share); it
    failed every gate (advisory Brier 0.297 against B0 0.255 and B1 0.205, pooled G1 failed),
    because the test labels carry the same storm bias as the training labels. The code is
    removed.
  - *Capture-independent rows (addendum f, A1).* The idea: count the rate over the days of
    lists the archive read on a regular schedule, whose reads the weather did not pick. The
    rule, fixed from capture times alone before any row was counted: the capture index (the
    workflow's CDX listings) holds a capture of the list on half or more of the season's
    labeled school days, and the archive read 9 in 10 or more of the mornings (06:30 to 09:30
    local) the index captured, on 10 or more mornings. Of the 158 stations whose lists label
    a district, no station-season qualifies, so there are no such rows (addendum f stops
    under 60 advisory rows on 10 dates). The 77 station-seasons the index captured on half
    their days or more hold 2,296 morning captures, and the archive read 8 of them: the
    downloads were planned storm days first. Looser rules that do find rows fail the proof
    that reads do not rise on storm days: over every station-season with a morning read,
    morning reads fall on 0.28% of plain days (45 of 15,989), 7.4% of advisory days (24 of
    324) and 20.6% of warning days (39 of 189); even the index's own morning captures rise
    from 3.9% to 15.7% and 29.6% (the Wayback Machine is saved more on storm mornings).
  So the advisory chance is what the recorded days say, and the base sentence counts recorded
  days, which is true of them. Real validation comes from the live labels this winter (S8
  reads every covered district every morning, open days included), which the automatic
  retrain re-anchors the storm classes on (The model learns on its own, below).
- **Charter-only districts (E4) are not labeled.** Labeling a district with no regular school
  by all its schools added 192 labeled days (172 districts, mostly storm-day closings) and made
  the walk-forward backtest worse on the rows both label sets share (advisory Brier 0.27495 to
  0.29495); addendum f admits them only if they pass its capture-independent gates, which
  could not run, so `train.eligible_schools` labels every district as before. Yosemite-Wawona,
  Eastern Sierra USD, Mammoth USD and Mono COE have no label rows either way: no archived list
  carries them.

## Private schools and "school is on" (piece 2)

- Every private school of the contiguous states (no district, the private flag in the
  directory: 22,031 in the September 25 directory) gets its own entry in the file's
  `schools` section (contract C3): its directory position, its time zone as its position in
  the file's shared `zones` table, the districts within 10 miles (nearest first, at most 4)
  and, for each day, the position of its outlook in the file's shared `outlooks` table.
  Schools with the same day share one outlook and schools in the same zone one zone name, so
  the section stays small (a real pass: 22,031 schools, 5 distinct outlooks, 5 zones).
  Alaska and Hawaii get none, as their districts get none. A private school of the
  contiguous states whose time zone neither the model nor its point gives is left out (its
  today is unknown); every pass then prints a warning with how many (none today).
- Neighbors: the contract (spec C3) says up to 12 districts within 10 miles; the file keeps
  the nearest 4, because 12 would add about 1.1 MB raw to the worst case (8 more indexes of
  five digits for each of 23,133 schools with growth) and about 1 MB to every pass. With the
  size fit above, 12 would still fit the worst case without record days (about 16.2 MB of
  16.5) but would drop the committed model's record days in a nationwide storm. Signed off
  by the lead on October 21 (it saves about 1 MB on every pass); piece 3's neighbors reason
  for a private school sees only those 4.
- Labels: each private school is its own unit, labeled from the archive by the districts'
  rules and from the same settled days (`predict labels`, `labels-private.parquet`): 1,426
  school-days, 661 known (463 no school, 9 delayed, 189 open). An unread or absent school is
  unknown, never open.
- Rates: a chain over private schools only (the school's own record, private schools nearby,
  in its county, state, region, the nation). A place below the nation is named only with 30
  labeled private school-days (`model.private_level_min_days`); with the districts' 8, a
  state's rate rested on one or two storm days. That one setting was chosen after the
  private backtest, so the backtest is not out of sample for it. A situation private schools
  hold too few recorded days of (the nation's minimum, 30) takes the districts' rates around
  the school where the districts hold that situation's own days, and its sentence then
  counts districts' days ("Districts near ..."): the day's own weather comes before another
  weather's private days (`serve.counted_over_private`). Only where neither chain holds the
  situation does the private chain's fallback stand, when it can be said truly (borrowed:
  "recorded days with a winter storm warning"), else the districts'. With the committed
  model: private schools hold clear days, advisories, winter storm warnings and blizzards;
  an extreme cold warning takes the districts' cold days (Pembroke Hill: 75%, nation, of
  districts, where the private fallback would have said 97% over private winter storm
  warning days); ice, lake snow and tropical days, and the days after a snow day, fall back
  on both chains alike, so the private chain's fallback stands. Either way the base is
  literally true of what it counts, by the same share rule (`tests/predict/test_truth.py`
  covers private cells). The private backtest scores the private chain alone; the
  situations served from the districts' rates are a handful of its rows (4 cold days). A private base's sentence reads
  "Private schools near St. Ann closed or went remote on 3 in 10 of their recorded days like
  this." (`PooledBase.of`: `private_schools`).
- Private backtest (`out/internal/predict/backtest/private/report.md`, internal, reported
  apart from the districts'): storm-row Brier 0.0802 against B0's 0.0820 (B0 here is the
  national rate per class over the private school-days of earlier seasons), all rows 0.0594 against 0.0609: pooled G1 passes. G2
  passes (every bin with enough rows within its bound) and G3 passes (closings caught at
  50% or more 100% against B0's 100%, precision 0.924 each). No season holds 300 storm rows,
  so G1 by season is reported only. The report ends with Pembroke Hill's and Visitation
  Catholic's named days, each predicted walk-forward (one of Pembroke Hill's 13 named days,
  2025-02-18, has a morning read: no school, predicted 95%).
- Learning: `predict learn` re-anchors the districts' rates on days read live; it does not
  yet label private schools from live reads. Until it does (the first follow-up), the
  private chain's sentences count the archive's recorded days only, never days read live.
  A private school on the districts' rates around it carries their live flag, so its
  sentence says "days we read live" only when those district rates were counted on them.
- Launch gate (addendum d): the private storm levels are the archive's selection-biased
  recorded days (an advisory 91%, nation, 226 of 248; 99% in a state or county holding 73 of
  74 or 57 of 57), worded truly as recorded days. Until the private learn follow-up
  re-anchors them on days read live, as `predict learn` does the districts', they block the
  public launch the same way the districts' unlearned levels would.
- Manual statuses the admin sets (the closings file's `manual` rows) light private schools
  as any status does; a posted status for a day hides that day's chance in the panel, and
  the area panel counts it as posted.
- "School is on" (`snowlight/predict/opens.py`, rule 7): once the live ingest publishes
  `live/opens.json` (S8; not published yet, so today the rule never fires), a district every
  one of whose eligible schools said school is on for a day (a statement the district posted
  reaches all of them), or a private school that said so, drops to 1% with no delay chance
  that day, and its "How we got" ends with "Riverside said school is on." taking the rest
  away (`said_open`, points at most 0), so the lines still add up to the chance. A district
  only some of whose schools said so did not say it, and its usual chance stands (the spec's
  50% share would have put words in the district's mouth). A day said open shows no previous
  chance: its line already shows what the chance was and why it fell (the schema refuses
  both on one day, which keeps the worst case below). It never fires for a unit with a posted status that
  day, and only on an opens file and a closings file from the same publish, at most 60
  minutes old (`serve.opens_max_age_minutes`); otherwise the usual chance stands. An opens
  file for another directory that holds statements darkens the pass.
- Size: the file leaves every default out (a null, a false, an empty list) except each
  forecast's `reasons`, so a real pass (October 21, s4 site data, publishing off) is
  8,225,511 bytes raw and 609,384 gzip (12.0 MB before). The budget is 16.5 MB raw
  (`serve.budget_raw_bytes`). A learned file (S7-L) may give any district with 4 live-read
  days of an anchored situation an own base with up to 8 record days, so no fixed count of
  recorded districts bounds the whole file: under a winter storm warning over the whole
  country with every district holding a full record, it is about 24.9 MB (26.1 MB with 5%
  growth). The private schools' shared outlook table has a cap too: once a learned file
  counts a situation over the districts around each private school (each school's nearby
  rates its own), previous chances multiply the (chance, previous) pairs into thousands of
  outlooks. A pass whose file is over the budget, or whose private schools name more
  outlooks than the table holds (counted before any school's entry is made,
  `serve.TableError`), makes it again with the next step of `serve.Fit`: without the record
  days under each own base; then also without the private schools' previous chances; then
  without any previous chance; then the districts alone, as the file was before private
  schools; then the districts alone without record days. It goes dark only when even that
  is over, so the private schools can never darken the districts. The pass prints a
  warning saying why and what it left out. Every chance and every why it holds stay the
  same: the base sentence counts its own days, so it is true without them listed, and the
  web does not show a base's record days today. A file with no schools section shows a
  private school no chance, as before this piece.
- Table: the table holds 9,000 outlooks (`MAX_OUTLOOKS`, every index four digits). With no
  previous chance the outlooks a pass can give the private schools are counted before any
  pass (`serve.possible_outlooks`: each school in every situation, with the scope and
  record its rates name, said open or not); `tests/predict/test_learn.py` checks that every
  such pass names only those, and measures: the committed model 72 (s4 site data, the
  two days of a pass); a SYNTHETIC learned file anchoring cold for every district 384 to
  394, and with random live delay counts 2,494 to 3,411; one anchoring every situation
  at once 1,493 to 1,594, and with random delays 13,220 to 17,549 over all ten
  situations together (a pass names only the outlooks of the one situation each
  school-day is in; one naming more than 9,000 publishes the districts alone). The critic's three-pass probe (a learned cold anchor, mixed classes) names
  2,241 outlooks with previous chances and publishes them all, without record days, at
  11,068,283 bytes.
- Worst case: every district and every private school of the committed model and 5% more of
  each, the longest lines on both days (both base flags, the longest alert and zone names,
  twelve districts next door with the highest indexes), asserted in
  `tests/predict/test_loop.py`, which reads the counts from the committed model: with no
  record days and no previous chances (the last step that keeps the private schools), every
  district said open (its longest day) and 9,000 distinct private outlooks each counted as
  long as a day said open: 16,326,296 bytes; with no record days, a previous chance on
  every day and 2,000 outlooks: 15,108,482 bytes (14,414,906 at today's counts); and the
  committed model alone (its 1,452 recorded districts, 5% more) keeps its record days with
  2,000 outlooks: 16,446,182 bytes. A real-data dry run (s4 site data, a learned file
  anchoring winter storm warnings with 8 live days for every district, 11,149 own bases, a
  nationwide warning pass after an advisory pass) makes a whole file of 17,718,603 bytes and
  publishes it without record days at 11,656,607 bytes (685,923 gzip), every chance and
  previous chance kept. The same test checks that no day the pass can make (every
  situation, base, scope, flag, said open or not, previous or not, record or not) is longer
  than the worst case's, so a day said open cannot break it. More than 64 time zones is a
  `serve.TableError` too: the pass publishes the districts alone.
- Rollout: the web reader before this piece (ed5d405) refuses a whole file whose forecast
  has no `reasons` list, so the file always writes it, even empty; that reader still drops
  the "How we got" detail of a compact file (its why and flags left out) for the one load a
  stale page runs, and shows no private school's chance. Land the web build before the
  first compact file is published, and expect a page still on the old script to show the
  chance without its detail until it reloads.

## The reasons (piece 3): built, switched off

`serve.reasons` and `serve.announces` in `config/predict.yaml` are `false`: every chance is the
base alone, byte for byte as before piece 3. The lead turns them on; nothing else changes then.
The gate fails (below), so they stay off.

- **What they add.** On top of the base, terms on the log-odds scale
  (`snowlight/predict/terms.py`), each a monotone step function of one level, 0 at its
  reference, fit by L2-penalized logistic regression with the base as offset and bounds that
  keep each sign (the penalty picked by leave-one-season-out log loss inside the training
  seasons, each inner fit taking its bands from its own rows): the forecast snow, ice (only
  adds), how cold it feels at 7 AM (only adds), and the share of the districts next door that
  canceled (only adds). The lines' points are the terms' exact Shapley values on the chance,
  rounded by the largest remainder so the base (its own points, never re-rounded) and the lines
  add up to the chance shown (`shapley.py`, `reasons.py`). Private schools keep the base alone.
- **Which terms a day has** follows the day's own weather class, not the class its base counts
  (`TERMS_OF`, `has_term`): a class that is not modeled publishes its fallback's rates
  (`model.fallback`: lake effect snow, ice, tropical and cold days take the winter storm
  warning days'), and such a day never takes the storm's snow term. A snow term also needs the
  base to count days of its own group (advisory days; winter storm and blizzard warning days),
  as its band and its words are of those days. Training and serving use the same rule.
- **The snow term** is counted against the recorded days of the same class group: 0 on every
  bucket that is not above or below more than half of those days' buckets. The band comes from
  the nation's counted days of the group, not from each district's own typical storm (spec c.2,
  addendum g): no district holds 4 or more advisory days of its own with a known forecast, and
  only 4 hold that many storm days, so a district's own band cannot be told. On warning days
  the snow term only adds ("more than most storms"): the forecast window starts at 9 PM the
  evening before, so a storm mostly fallen by then reads light (KC on January 6, 2025 read 1 to
  3 inches at 9 PM; February 19, 2025 0 to 1 inch), and a line saying such a storm is lighter
  than most would mislead. Over advisory days it can take away. A day of freezing drizzle (code
  6) has no snow level (the advisory is for the ice). The storm term that only adds departs from
  addendum g (the snow term "relative to the district's typical recorded storm ... so it can be
  negative"), for the lead to sign off with the alert text departure below.
- **Serving moves the rows training moves.** The terms read the forecast's bucket code alone
  (`terms.levels_of`), in training (`term_rows.py`, the history's code at 21:00 D-1) and in
  serving (`reasons.levels`, the live code at the same snapshot), and the neighbors' share; a
  test runs the same rows through both and checks the levels, the terms and the chance agree.
  Nothing the history does not keep decides whether a term applies, so backtest v2 scores the
  rule a pass serves (unrounded; the pass rounds to whole points and clamps as every chance).
  Round 2 had a serving-only words rule (no line, so no term, when every school read 0 inches
  or the schools' range crossed the band); on three replayed advisory days it left 443 of 719
  under-half-inch advisory districts at the base, which the fit had never done. It is gone.
- **The words follow the code, and state an amount only where it is true of every deciding
  school.** A snow line's range is the code's bucket cut to the deciding schools' lowest and
  highest window totals in whole inches (`reasons.snow_words`), said only where those schools'
  totals as read (`forecast_live` keeps them unrounded) all lie in the bucket; then the range
  holds every deciding school's amount and lies wholly on the side of the band its sign says
  ("0 to 0.5 inches", "2 to 3 inches", "9 to 14 inches"), and a district with no new snow at
  all says "no new snow". Where any deciding school's forecast leaves the bucket, the line
  drops the amount and says only the comparison, which the code alone makes true: "The 8:19 PM
  forecast has less snow by 2 PM than most advisory days.", "The 8:47 PM forecast has more
  snow by 1 PM than most storms." (`snow_total.low` and `high` are then left out). An ice line
  says the 50% value in tenths, rounded down, and a wind chill line its whole degrees, each
  only where every deciding school reads that same amount; otherwise "The 8:50 PM forecast has
  freezing rain." and "The 8:16 PM forecast has a wind chill at the bus stop." Which terms
  apply and their points never depend on the words (a test holds a day's points the same with
  and without its amount). "Overnight" is said only where every deciding school's own
  overnight snow (the periods ending 06 and 12 UTC, which `forecast_live` keeps per district
  as the schools' lowest and highest, unrounded) lies in the stated range
  (`reasons.overnight`), so "9 to 11 inches overnight" is never said where a school gets
  under 9 inches overnight and the rest after 6 AM; otherwise the line says where the window
  ends ("by 12 PM"), which its range makes true, and a line with no amount never says
  overnight. A school's amount at a bucket's end is the next bucket's, as the codes read it,
  so a school at exactly 2.0 inches never sits under "lighter than most advisory days" (whose
  band starts at 2). A wind chill line states degrees only where every deciding school has a
  7 AM feel read. Every other thing a forecast line says is the same at every deciding school:
  the run's time (one run per time zone), the window's end (18:00 UTC on the day) and the bus
  hour. A neighbors line names the districts that canceled.
- **Round 3's words were not always true (corrected).** Round 3 cut the bucket to the schools'
  range rounded outward to whole inches and said that range whatever the schools read, and
  these docs called it always true. It held the district's 50% value but could leave out what
  the district's own deciding schools were forecast: on the three replayed critic days 31 of
  411 snow lines (March 14, 2023), 25 of 483 (February 6, 2025) and 21 of 520 (January 26,
  2026) did, the worst "0 to 0.5 inches ... lighter than most advisory days" for a district
  whose schools read 0 to 6.54 inches; and rounding to whole inches hid every crossing at the
  under-half-inch code (any trace reads 0 to 1). Through the same serving path in round 4:
  on those days 31 of 411, 25 of 483 and 21 of 520 snow lines drop their amount (the same
  districts), and 0 lines state a window range that leaves out a deciding school's amount; 95
  of 712 and 29 of 322 ice lines (February 6, 2025 and January 26, 2026) drop theirs, and no
  wind chill line fires on those days. Points and chances are unchanged.
- **Round 4's "overnight" was not always true (corrected in round 5).** Round 4 checked the
  stated range against every deciding school's window total but said "overnight" from the
  district's 50% value of the overnight snow alone, and these docs and its report said no line
  stated an untrue amount. On January 26, 2026, 26 of the 164 lines that said "overnight" had
  a deciding school whose overnight snow was under the stated low ("9 to 11 inches overnight"
  for 5000418, whose schools get 7.99 to 9.09 inches overnight and the rest by 1 PM), 5 of
  them by more than half an inch. Now "overnight" needs every deciding school's overnight
  snow in the range. Both round 4 critics' probes, copied and rerun unchanged on round 5's
  code: 0 untrue snow ranges, overnights, ice tenths or wind chill degrees, and no ice or
  wind chill amount with a school not read, on March 14, 2023, February 6, 2025 and January
  26, 2026 (9, 120 and 138 lines say "overnight"; the 26 now say "by 1 PM"), and 0 on the
  second critic's other three days (January 6 and February 19, 2025; January 16, 2024).
  Round 5 also counts a school's amount at a bucket's end as the next bucket's (a school at
  exactly 2.0 inches is in advisory days' 2 to 4 band, so never "lighter than"), found by the
  random property test's new check of the comparison's side. What stays true of the
  district's 50% value but not of every school is the comparison-only lines and the ice lines
  with no amount (turn-on item 2). Points and chances are unchanged.
- **The forecast.** The NDFD grids (`forecast_live.py`, with the forecast history's reader and
  rules): for school day D the newest run that counts at 21:00 local the evening before, or
  now if earlier. From 9 PM on that is the class snapshot the base and the terms were counted
  at; before 9 PM it is an earlier run, with a longer lead, than the terms were fit or
  backtested on (same window, school cell and 50% value; see the turn-on list), so these docs'
  earlier "snapshot parity" holds only from 9 PM. Every pass from 9 PM on, the morning's too,
  reads the 9 PM forecast, so the chance never changes at an hour
  for the forecast's sake alone (round 2 dropped the lines from about 10 PM: the chance went
  back to its base with nothing in the weather changed, the panel showed that as a change and
  the chance notifications could count it). A run that does not list or read leaves those
  terms out for the pass (it warns), as a night with no run is unknown in training.
- **The forecast's time.** Each forecast line carries the run it was read from
  (`snow_total.at`, `ice.at`, `wind_chill.at`), and the web words it "The 8:16 PM forecast
  has ...". That names the run's time but not its day: a morning panel's "The 8:46 PM
  forecast" is last night's, and the line does not say so (turn-on list). The
  window ends at 18:00 UTC on the day (`ndfd.WINDOW_END_HOURS`, held to the web's
  `FORECAST_WINDOW_END_UTC_HOUR` by a test), worded in the school's zone ("by 12 PM" Central
  in winter, "by 1 PM" Eastern). A snow line also says the days it is weighed against
  (`snow_total.against`: `storms` or `advisory`), so the web never infers it from the base's
  kind (a day-after base over a storm's days would have read "most advisory days"). These three
  fields are a contract change; the spec's piece 3 named none, so the lead signs it off. The
  file leaves `against: storms` and a missing `at` out, as every default.
- **The neighbors.** From `live/closings.json` on the live host (`nowcast.py`). A neighbor has
  canceled when at least half its eligible schools (the label's no-school share) have a closed
  or remote row with a weather reason or none named; one building closed for a water main break
  is not its district canceling. A district with a row of any status of its own gets no
  neighbors term. A file for another directory, over `neighbors_max_age_minutes` (60) old, or
  unreadable says nothing (no line).
- **Training data.** `predict labels` also writes `posts.parquet` (per unit and day: its first
  status of any kind over its eligible schools, when it first showed no school by the same
  half-of-eligible weather rule, and its list's own posted stamp) and `snapshots.parquet`: the
  6 AM pass on D (`posts.PASS_AT`), the same hour whatever the day turned out to be. A district
  that had shown any status by then has no snapshot; else the snapshot is the last capture of a
  list that carries it from 18:00 the evening before up to 6 AM. (Round 1 took an open day's
  snapshot as late as 9:30 and a closed day's before its first post, so which rows had one, and
  when, followed the outcome.) The archive has 8 such snapshots, so the neighbors term fits to
  0 and cannot be judged; it can fire only once live labels retrain it. Times and ids only. The
  forecast levels come from the forecast history artifact (run 39748984910,
  `codes-*.parquet`, sample 13 = 21:00 D-1, `code_filled`), downloaded to
  `pipeline/.cache/predict/ndfd-districts/` and checked against its manifest's SHA-256s.
- **`predict terms`** (`terms_cli.py`): backtest v2 (`backtest_terms.py`: each row's piece 1
  base fit on the seasons before its own; each test season's terms fit on the seasons before
  it) to `backtest/terms/report.md` in the labels folder, then the terms fit on every season
  and the usual posting times to `data/predict/terms.json.gz`, which names the committed model
  it was fit over. A pass uses the terms only over that model with no learned file serving
  (`cli.terms_refused`): they are offsets on the archive rates, and a learned file (S7-L)
  re-anchors rates they were not fit on. When S7-L serves, the terms must be refit over its
  rates (addendum b.3) before they can be used; until then the pass warns and serves the base.
  The terms file also records the gate as the run judged it (`gate`: passed, the pooled storm
  Brier gain, and the SHA-256 of the report it wrote; the committed file: failed, -6.3%), and a
  pass refuses terms whose gate failed, or that record none, unless
  `serve.reasons_gate_override` names the lead who signed off on serving them anyway (empty in
  the committed config); so turning `serve.reasons` on alone serves the base and warns. Its gates are computed as piece 1's:
  pooled storm Brier with and without the season reported apart (2020-21); "worse in" counts
  only seasons with 300 or more storm rows (others are reported); G2 bins the terms on piece
  1's unclamped base; a penalty at either end of the grid is named.
- **Size.** A snow line with the forecast's time is about 120 bytes; snow, ice and 12 districts
  next door at most about 320 bytes a district-day. A file over the budget steps down
  the `serve.Fit` ladder as before; after the step with no previous chances comes
  `NO_REASONS`, the file before piece 3, which the worst case already holds.
- **The alert text (a departure from addendum g, for the lead to sign off).** `alert_text.py`
  reads snow ranges, ice and wind chill from NWS text and is tested, but is wired into neither
  side: the live alerts reader keeps no description, and the IEM product-text fetch for the
  seasons before the grid history (102 labeled rows) is not made. Training and serving agree
  (no text amount on either). Wiring both together waits for the live reader to keep the
  description.
- **Usual posting time.** `announces_at` is the median of a district's own posted stamps in
  the archive, from 18:00 the evening before to 09:30, with 3 or more days (`announce.py`). The
  archive holds at most 2 such days for any district, so no district has one yet.

Backtest v2 on the labels of 2026-10-25 (internal report; storm district-days of the test
seasons 2019-20 to 2025-26; 2019-20 has no storm rows):

- The gate fails: storm Brier 0.10898 with the base alone, 0.11580 with the terms (6.3% worse;
  the gate asks 2% better), and 0.117 to 0.125 without 2020-21 (6.7% worse). G2 holds and every
  sign holds. The season gate ("worse in at most 2 of 7 seasons") covers 1 season: only 2023-24
  has the 300 storm rows piece 1's rule gates (0.08494 to 0.08350, better), so "worse in 0 of 1"
  says little, and the pooled gate decides. Of the reported seasons, 2022-23 is worse (225 rows,
  0.393 to 0.440); the lead may weigh it at turn-on. The report says both.
- What drives it: in 2022-23 the advisory snow term fit on the seasons before it (penalty 0.3,
  from almost only 2018-19's forecast rows) adds 2.91 log odds at 4 to 6 inches; 47 advisory
  test rows there, 36% of them closed, went from a mean 77% to 94% (Brier 0.401 to 0.627), more
  than the whole pooled loss. Round 1's account (the 9 PM window on warning days) was wrong:
  there the cold days of 2024-25, counted over winter storm days, took the storm's snow term
  (Brier 0.0036 to 0.1999). With the terms keyed on each day's own class, 2024-25 scores as the
  base.
- The penalty grid: the inner loop picks an end of it in 5 of 7 folds (0.3 in 2019-20 to
  2022-23, 1000 in 2023-24). A grid widened to 0.03 and 10,000 picked its ends again and scored
  worse (7.2%), so it was not kept: with one or two seasons holding forecast levels the inner
  loop has too little to choose from.

For the owner, the advisory chance by forecast snow (the 9 PM forecast's 50% value), before and
after, computed through the serving path (`reasons.moved`, the published floor and ceiling)
over every deployed district's advisory base (median 74%, all 18,227 above 50%):

| forecast snow | before (median) | after (median) | after, mean | above 50% after | districts moved |
|---|---|---|---|---|---|
| under 0.5 in (no new snow, or a trace) | 74% | 38% | 55.9% | 49.1% | 18,227 |
| 0.5 to 2 in | 74% | 74% | 80.6% | 100% | 0 |
| 2 to 4 in | 74% | 74% | 80.6% | 100% | 0 |
| 4 to 6 in | 74% | 74% | 80.6% | 100% | 0 |
| 6 in or more | 74% | 75% | 81.5% | 100% | 12,589 |

- This is what a pass publishes now, for every district at that code, the ones with no new snow
  at all too (round 2's table was the model's step; its serving rule kept 62% of under-half-inch
  advisory districts at the base). The history keeps bucket codes only (edges 0.5, 2, 4, 6 and
  9 in), so 0 to 1 and 1 to 2 in cannot be told apart, and 1 to 2 inch advisories stay at about
  74% until live labels re-anchor the base (S7-L).
- The snow lever has no held-out evidence. The under-half-inch step (-1.52 log odds, a 74%
  base to 38%) is an in-sample fit on 29 training rows and was never tested on rows the fit had
  not seen: walk-forward, no advisory test row under 0.5 in falls in a fold where that step
  exists. The step at 6 in or more rests on 1 row. Walk-forward, 43 advisory test rows were
  moved by the snow term (Brier 0.443 to 0.690, worse) and 71 by the ice term (0.091 to 0.079);
  all advisory rows 0.275 to 0.301.
- The ice term adds 3.43 log odds at 0.10 inch of ice or more: a 74% advisory base becomes 99%
  (80% of districts hit the ceiling). It is fit on storm-picked labels (addendum f) and swings
  across folds (5.27 in 2019-20 to 2022-23, 0.08, 4.34, 3.43). The owner should see it before
  turn-on.

Replays through the serving path with the reasons on (real NDFD runs at 9 PM, s4's directory;
phone and desktop shots in the build folder for the lead; rerun in round 5, every row below as
in round 4, so the shots stand; of the replayed lines only 26 on January 26, 2026 changed,
from "overnight" to "by 1 PM", none of them shown, with the same points). On the three
advisory days the
round 2 critic replayed (March 14, 2023; March 22, 2024; February 6, 2025), all 719 advisory
districts at the under-half-inch code by the history take the step a pass serves (round 2:
276):

- A light advisory, Shawnee Mission, February 11, 2019 (NWS: "sleet and snow accumulations of
  less than an inch and ice accumulations of a light glaze", 3 to 9 AM): 97% to 88%, "The 8:46
  PM forecast has no new snow by 12 PM, lighter than most advisory days." -9.
- Kansas on January 6, 2025 (an advisory; the snow fell on January 5, before the 9 PM forecast):
  district 2000001, 97% to 88%, "The 8:47 PM forecast has 0 to 0.5 inches overnight, lighter
  than most advisory days." -9; 239 advisory districts take the step that day.
- Hartford, March 14, 2023 (an NWS 2 to 6 inch advisory whose snow fell mostly after 2 PM, the
  window's end; the district open): 78% to 44%, "The 8:19 PM forecast has 0 to 0.5 inches by
  2 PM, lighter than most advisory days." -34.
- A crossing, the same day: Regional School District 05 (Orange, Connecticut), whose district
  50% value is under 0.5 inch but whose deciding schools read 0.31 to 1.38 inches: 71% to 35%,
  "The 8:19 PM forecast has less snow by 2 PM than most advisory days." -36 (round 3 said "0
  to 0.5 inches", which left out the schools above half an inch).
- A Kansas City storm day, February 17, 2022 (a winter storm warning; North Kansas City area
  districts): 95% to 99%, "The 8:50 PM forecast has freezing rain leaving 0.1 inches of ice."
  +4. No Kansas City storm day in the history reads 9 inches or more at 9 PM, so none has a
  snow line (the storm term adds only from 9 inches); January 6 and February 19, 2025 and
  January 9, 2024 show the base alone.
- Christina, Delaware, February 6, 2025 (an advisory): 56% to 98%, "The 8:46 PM forecast has
  freezing rain leaving 0.1 inches of ice." +42.
- Boquet Valley, New York, January 26, 2026 (a winter storm warning): 89% to 98%, "The 8:47 PM
  forecast has 10 to 11 inches by 1 PM, more than most storms." +9 (8.5 inches of it overnight,
  so not "overnight").
- A heavy advisory, March 22, 2024: 74% to 75%, "The 8:19 PM forecast has 6 to 7 inches
  overnight, more than most advisory days." +1.

Before the reasons are turned on (the lead and the owner):

1. The gate must pass, or the lead must decide otherwise in writing; it fails today (and the
   season gate covers one season; 2022-23, reported only, is worse). This is enforced: the
   committed terms record the failing gate, and a pass refuses them unless
   `serve.reasons_gate_override` names the lead's sign-off.
2. Wording, none of it approved with real data yet; the shots show each. Every forecast line
   names the forecast's time and, for snow, overnight or where the window ends: "The 8:16 PM
   forecast has 6 to 9 inches overnight, more than most storms.", "The 8:19 PM forecast has 0
   to 0.5 inches by 2 PM, lighter than most advisory days.", "The 8:46 PM forecast has no new
   snow by 12 PM, lighter than most advisory days.", "The 8:50 PM forecast has freezing rain
   leaving 0.1 inches of ice.", "The 8:16 PM forecast has a wind chill of -4 F at the bus
   stop." New with round 4, the forms with no amount, for a district whose deciding schools'
   forecasts leave the range: "The 8:19 PM forecast has less snow by 2 PM than most advisory
   days.", "The 8:47 PM forecast has more snow by 1 PM than most storms.", "The 8:50 PM
   forecast has freezing rain.", "The 8:16 PM forecast has a wind chill at the bus stop."
   Addendum g's approved forms ("6 to 9 inches overnight, more than most storms", "Lighter than
   most advisory days, 1 to 2 inches") name neither the forecast's time nor its window, and
   stay only for a line with no forecast time, which the pipeline never sends. The timed forms
   run about twice the approved mockup's length, and where the viewer's clock differs a line
   carries two zone names ("The 8:19 PM ET forecast has ... by 2 PM ET"); "0 to 0.5 inches"
   may read better as "under half an inch". A shorter time form is the owner's call.
   Two cases for the owner's choice, neither decided here (the points stay either way):
   - The comparison-only lines are true of the district's 50% value, which the term reads,
     but in a wide district a deciding school's own forecast can sit inside the band or past
     it. Counted by the round 4 critic's measure, on March 14, 2023, 17 comparison-only lines
     have a deciding school inside or past the band (4 clearly past it: CTECS, 0900002, "The
     8:19 PM forecast has less snow by 2 PM than most advisory days." -34 with one school at
     6.54 inches; 0903520, 3619740 and 5000417 "more" with a school at 1.93, 2.99 and 4.21);
     on February 6, 2025, 0; on January 26, 2026, 15 (storm lines with a school at 7.76 to
     8.98 inches, inside the 6 to 9 inch band); also 4 on January 6, 2025 and 1 on February
     19, 2025 (5680180, "less" with a school at 4.37). The same holds for the ice line with no
     amount, "The 8:50 PM forecast has freezing rain.": 3 on February 6, 2025 and 2 on
     January 26, 2026 (2 on January 6, 2025) have a deciding school under 0.01 inch of ice,
     at 0 in 3900237 and 5100330 (February 6) and 2106001 (January 6). The options: qualify
     the line ("at most of CTECS's schools", "at most of its schools") or state nothing for
     that line (the lines add up to the headline, so the web would need a form for points
     with no words, or the panel leaves the sum out for that day).
   - The wind chill line with no amount, "The 8:16 PM forecast has a wind chill at the bus
     stop.", says little: every forecast has some wind chill. It cannot fire today (the
     committed cold and neighbors steps are all 0, and no wind chill or neighbors line came up
     on any probed day). The options: a form with the code's bound ("a wind chill of 10 F or
     colder at the bus stop", said only where every deciding school reads it) or state
     nothing for that line, as above.
3. The ice term's size (a 74% advisory base to 99%).
4. The window. The forecast counts the snow still to fall from its time (about 9 PM) to 18:00
   UTC on the day (noon to 2 PM in the East and Central zones in winter, earlier in the West).
   Snow that fell before 9 PM or falls after the window is not in it, and the model, fit on the
   same window, moves the chance for that: an advisory whose snow fell the day before (Kansas,
   January 6, 2025) or comes in the afternoon (Hartford, March 14, 2023: an NWS 2 to 6 inch
   advisory whose snow fell mostly after 2 PM) takes the under-half-inch step. The words now say
   what the forecast has and when it ends; whether the step should apply to such days is the
   owner's call.
5. The forecast lines stay all night with the 9 PM forecast's time (above); this replaces
   round 2's hour limit, so it needs the owner's approval of the timed wording.
6. Departures for the lead's sign-off: the alert text (above); the storm term that only adds;
   the snow band taken from the nation's counted days of each class group, not from each
   district's own typical recorded storm (addendum g; no district has enough known-forecast
   days of its own); and the contract fields (`snow_total.against`; `at` on snow, ice and wind
   chill; and, new with round 4, `snow_total.low` and `high`, `ice.inches` and
   `wind_chill.feels_like` left out where the line states no amount).
7. A learned file (S7-L) turns the terms off until they are refit over its rates.
8. Passes before 9 PM. The terms were fit and backtested on the 21:00 D-1 forecast only, but a
   pass before 9 PM reads an earlier run (from about midnight, when D becomes tomorrow). On the
   1,371 labeled advisory district-days the round 3 critic checked, the advisory term at an
   earlier sample differs from the 9 PM term in 9.7% of them at 8 AM the day before, 7.6% at
   1 PM, 6.3% at 4 PM and 0.6 to 1.1% at 6 to 8 PM. Pick one before turn-on: serve the forecast
   terms only from the 21:00 D-1 snapshot on (earlier passes show the base alone), or fit and
   backtest the terms per pass slot from the history's samples 0 to 12, which the artifact
   already holds.
9. Old web clients. The web on origin before piece 3, and any cached app bundle older than it,
   words every snow line "... than most storms" with no forecast time ("The forecast has 6 to
   7 inches overnight, more than most storms." for an advisory line, which is false: the storm
   term starts at 9 inches), and does not read a line with no amount (it then leaves the sum
   out). The web that reads `against`, `at` and the lines with no amount must be deployed, and
   old service-worker clients updated, before `serve.reasons` is set; or the pipeline sends the
   lines only to clients that say they read them.
10. A headline day that is not tomorrow. A Friday evening pass for Monday reads the newest run,
    2 to 3 days out, and says "overnight" or "by 12 PM" with no day, which reads as tonight;
    the terms were fit only at the D-1 9 PM snapshot. Either give forecast lines only for the
    next school day's snapshot, or name the day ("Sunday night", "by 12 PM Monday").
11. The morning panel names last night's run without its day ("The 8:46 PM forecast" at 6
    AM), and the chance stays at the 9 PM forecast while a newer run may differ (by design,
    item 5). The owner may want "Last night's 8:46 PM forecast" when the run's date is before
    the viewer's day.

## What the owner sets up once

The predict workflow (`.github/workflows/predict.yml`) needs a token that can push to the
live host's repository. Nothing is published until it exists; every run ends at its
first step with a notice, and nothing fails.

1. Create the token. On GitHub: your profile picture, **Settings**, **Developer
   settings**, **Personal access tokens**, **Fine-grained tokens**, **Generate new
   token**.
   - Name: `snowlight-live publish`. Expiration: as long as you like (a year is fine).
   - Resource owner: `viaate`.
   - Repository access: **Only select repositories**, and pick `viaate/snowlight-live`
     only.
   - Permissions, Repository permissions: **Contents: Read and write**. Nothing else.
   - Generate it, and copy it.
2. Paste it where the workflow reads it. In `viaate/jsalcards`: **Settings**,
   **Environments**, **live** (create it with **New environment** if it is not listed),
   **Environment secrets**, **Add environment secret**.
   - Name: `SNOWLIGHT_LIVE_TOKEN`. Value: the token.
3. Start the chain: **Actions**, **predict**, **Run workflow** (or wait for the
   20-minute schedule). The owner's Cloudflare Worker also dispatches the workflow on
   `claude/keen-faraday-oy7yqw` every 5 minutes when no run is queued or running; such a
   dispatch starts a new chain like any other, and the `predict` concurrency group holds
   any run that arrives while one is going, so passes never overlap.

4. Serve the live host's whole repository on Pages (once, the owner or the lead: it is
   the owner's hosting repository, and nothing here changes it). Today the only Pages
   workflow in `viaate/snowlight-live` is the S8-A timing probe, which deploys a folder
   holding only `probe.json`; a file the publisher commits is never served, so
   `v1/predictions/latest.json` stays 404. Replace `.github/workflows/probe.yml` there with
   this workflow (it keeps the probe), in a commit to `main`:

   ```yaml
   name: pages
   on:
     push:
       branches: [main]
     workflow_dispatch:
   permissions:
     contents: read
     pages: write
     id-token: write
   concurrency:
     group: pages
     cancel-in-progress: false
   jobs:
     deploy:
       runs-on: ubuntu-latest
       timeout-minutes: 10
       environment:
         name: github-pages
         url: ${{ steps.deploy.outputs.page_url }}
       steps:
         - uses: actions/checkout@v4
           with:
             persist-credentials: false
         - name: Stamp the probe
           run: printf '{"n":%s,"t":"%s"}\n' "${{ github.run_number }}" "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" > probe.json
         - uses: actions/upload-pages-artifact@v3
           with:
             path: .
         - id: deploy
           uses: actions/deploy-pages@v4
   ```

   Then check it with one shadow publish before `on`: set the repository variable
   `PREDICT_PUBLISH` to `shadow`, run **predict** once, and open
   `https://viaate.github.io/snowlight-live/v1-shadow/predictions/latest.json`; it must load
   (and `README.md` too). Then set `PREDICT_PUBLISH` back to `on` (or delete it).

The token is never written to a log, a file or a chat.

## To stop the chances

- **At once, and they stay off:** run `predict blank` (with `LIVE_HOST_TOKEN` set): it
  sets the hold (`v1/predictions/hold.json` and `v1-shadow/...`, written first, in its own
  commit) and uploads a file with no districts. Every later pass's upload is refused while
  the hold is set (it is read in the very commit the upload builds on), so a running loop's
  heartbeat or an alert change never brings the chances back. GitHub Pages may serve the
  old file for up to 10 more minutes.
- **To stop the runs:** **Actions**, **predict**, **...**, **Disable workflow**. A
  disabled workflow also refuses the owner's Worker's dispatches. Cancelling a run starts
  no successor (the successor step runs only after a run that succeeded or failed), but
  the Worker or the 20-minute schedule starts a new run within minutes unless the
  workflow is disabled.
- **To publish again:** `predict release` clears the hold; enable the workflow.
- Deleting the secret or setting `PREDICT_PUBLISH` to `off` takes effect only at the next
  run (up to 320 minutes later): use the hold to stop now.

## Commands

Run from `pipeline/`. Exit codes: 0 done, 3 dark (nothing uploaded: the gate refused),
1 an error.

| Command | What it does |
|---|---|
| `uv run snowlight predict labels` | The weather history (IEM season files) and the labels (archived closing lists, matched and read once) to `out/internal/predict/` (internal: never committed). Heavy: run it under the heavy lock. |
| `uv run snowlight predict train` | Fit the strengths on every labeled season and write the committed model, `data/predict/model.json.gz` (derived counts by LEAID only). |
| `uv run snowlight predict backtest` | The walk-forward backtest and its gates to `out/internal/predict/backtest/` (internal). |
| `uv run snowlight predict once` | One serving pass. `--site-data DIR` reads a local `meta.json` and `points.bin` instead of the deployed site; `--write FILE` keeps a copy; `--host dir --host-dir DIR` publishes to a folder. |
| `uv run snowlight predict run --until +320m` | A pass on every :07 and :37 (the loop sleeps to the grid minute, so passes do not drift), and between them, checked every 5 minutes, a pass when the alerts differ from the ones the last good pass used or when the last pass went dark (at most one extra pass per 10 minutes). Uploads when the file differs, and on every grid pass as the heartbeat unless an upload went out under 4 minutes before: the public file is normally under 35 minutes old. The state is saved after every pass; an unexpected error counts as one dark pass and the loop goes on. |
| `uv run snowlight predict blank` | Sets the hold and uploads a valid file with no districts to `v1/` and `v1-shadow/`: every chance disappears and stays off until `predict release`. |
| `uv run snowlight predict release` | Clears the hold. |
| `uv run snowlight predict check --max-age 45m` | The watchdog: exit 3 when the public file is missing, invalid, blank, ahead of the clock or older than the limit. The workflow runs it after every run, a failed pass included, and opens one issue, "Snow-day chances are stale", unless one is already open. |
| `uv run snowlight predict learn` | Labels the live-read days not yet labeled and swaps in a refit only when the held-out live days find it no worse (see "The model learns on its own"). Exit 0 swapped, reset (a served file counted an excluded day) or nothing to change, 4 kept the model served because the refit was worse, 1 an error (nothing changed). The workflow runs it before the passes. |

Environment: `PREDICT_PUBLISH` (`on` writes `v1/`, `shadow` writes `v1-shadow/`, `off`
writes nothing and is the default; the workflow sets `on`), `LIVE_HOST_TOKEN` (the
workflow passes `SNOWLIGHT_LIVE_TOKEN`), `GITHUB_TOKEN` (reads the site's deployments for
the directory handshake), `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (the chance and
evening notifications after each pass whose file is the public one, docs/notify.md; without
them no notification is sent, and a notification problem only warns; the workflow gives them
to the `predict run` step only).

## When a pass stays dark

A pass publishes nothing, and the page hides the old file within 90 minutes, when:

1. the NWS alerts cannot be read, or the feed's `updated` is older than 20 minutes;
2. the deployed directory cannot be known for certain, or its `meta.json` and
   `points.bin` are not the ones its `edition.json` names;
3. fewer than 99% of the deployed districts are in the model;
4. the winter alerts drop by more than 80% from a pass that had more than 50 (published
   once the next pass confirms the count);
5. the file does not validate, or is over budget (16.5 MB raw, 1.5 MB gzip) even as the
   districts alone without record days (see Size under piece 2: the worst case with the
   private schools and without record days or previous chances measures 16.3 MB raw and
   0.3 MB gzip, `tests/predict/test_loop.py`);
6. the file read back after the upload is not the one sent;
7. yesterday's day timeline cannot be read (a host error or a file that does not validate);
8. the alert memory does not reach back to 18:00 the evening before the first day
   published, and cannot be rebuilt: after a lost or stale state (the feed unread for more
   than 20 minutes) the pass reads every class-making alert product issued since 48 hours
   before that from `api.weather.gov/alerts`, as the live feed would have shown them, and
   only then publishes;
9. the hold is set (`predict blank`).

A dark pass leaves the alerts it saw unhandled, so the loop tries again at its next
5-minute check. A warning the weather service cancels or upgrades (a `CAN` or `UPG`
product) leaves the memory for the zones it names at once, so the why never names a
withdrawn warning (the training snapshot counts the first product's window whatever came
after: the one place the live path is stricter).

There is never a "no alerts, so 1%" fallback: a pass with fewer inputs publishes nothing.

## Retraining

After a new season of archived lists (or a directory change that adds districts):
`predict labels`, `predict backtest` (check the gates in its report), `predict train`,
commit `data/predict/model.json.gz` with the report's numbers in the message.

## The model learns on its own

Every predict workflow run starts with `predict learn` (`pipeline/snowlight/predict/learn.py`,
`live_labels.py`). It needs no API key and no server beyond the live host and the Actions
cache. The owner's Cloudflare Worker needs no change: it dispatches the same workflow.

1. **Labels.** A school day is labeled once it is over everywhere, its timeline on the live
   host (`live/days/<day>.json`) is final (or the host's day index, written after the day,
   does not list it), and the live state's morning record of that day reads and runs past
   every read window. Every live pass adds itself to that record
   (`pipeline/snowlight/live/morning.py`, `morning/<day>.json` in the live state): whether
   the map showed it, the whole reads it made (rows, rows placed, rows read as no status),
   the states it withheld whole, and the districts its rows named with the status kinds
   named. Counts, ids and codes only. A district gets a label only when a list that carries
   it had a whole read between 06:30 and 09:30 local, in a pass the map showed, with the
   district's state not withheld, and the record of that day holds a pass in the last half
   hour of the window (a record that stops partway through reads nothing).
   A list carries a district when it lit a school of it on 2 or more live days, from the
   first of them. The archive's read gates then apply: an unreadable or barely placed read,
   a list with too few reads, a storm-day list under half its usual rows, an empty list
   while a market peer holds 5 rows or more, and on a storm day an empty list no other list
   of the market backs up, are not reads. A district a list named that morning is never
   open: whatever the live guards kept off the map (a conflict, a weak reading, a tripped
   breaker, a refused publish) shows up this way. It is delayed only when every status a
   list named it with is one the map showed on one of its schools: a district the map lit
   delayed is delayed, and one a list also named closed, remote, dismissed early, or with
   words the reader was unsure of, that the map never showed, is unknown.
   The archive's rules then decide what it did: half its schools lit closed or remote is no
   school, half lit delayed is a delay, at most 10% lit is open. Everything else is unknown:
   an unread or partly read district, a district whose status was taken back, a break day, a
   day the emergency stop held the map dark, a dark district on a storm day when half its
   market closed, and a district whose weather class the passes did not record by 21:00 the
   evening before (the training snapshot; the passes keep it in their state). The labels go
   to `predictions/learn.json` on the live host: LEAIDs, days and outcomes, no text. A
   labeled day is never labeled again, so a rerun changes nothing. A day that is not ready
   waits and is tried again on the next run, and so does the school day after it, since
   which districts follow a closing is told from the day before.
2. **Hold out.** The newest live days holding at least 100 storm district-days, on at least
   3 storm days and in at least 2 states (and at most half the live days), are held out.
   The refit counts only the days before them.
3. **Re-anchor.** A storm situation (a weather class above none) with at least 200 live-read
   district-days nationally, and at least 30 held out to check it on, is counted over the
   live days: they are complete daily reads, unlike the storm-picked archive, so they give
   its level. The archive gives only how much more or less readily each place closes than
   the places around it. Its "How we got N%" sentence then says "days we read live". Every
   other situation, the clear-day ones included, keeps the archive's rates and says "recorded
   days". While no storm situation qualifies, nothing changes.
4. **Check.** The refit and the model served now are scored on the held-out district-days,
   as published. The refit is swapped in only when its storm Brier is no worse pooled and in
   every situation either model re-anchors, for the chance of no school and for the chance
   of a delay (re-anchoring sets both levels), it has no more reliability bins (of 20
   held-out storm rows or more) out of bound, and its ECE is at most 0.01 higher. A score
   that is not a number counts as worse. A misread that runs through every live day, the
   held-out ones too, is beyond any held-out check: the drop below is for that.
5. **Swap or keep.** A swap publishes `predictions/learned.json` (counts by LEAID, the days
   counted, the check it passed). The next serving pass uses it with the committed model it
   was made over. A refit that is worse is kept out: the step exits 4, says why in its log
   line, and the workflow opens one issue, "The snow-day model kept its last version",
   unless one is already open. The same issue opens when the step fails.

Serving never depends on it: the step may fail or time out (5 minutes; it takes under a
minute) and the passes run anyway. A learned file that is missing, does not validate, was
made over another committed model or does not build is ignored, and the committed model
serves alone. Settings are in `config/predict.yaml` under `learn`.

**To drop a misread day.** Add the day to `learn.excluded_days` in `config/predict.yaml`
(for example `excluded_days: [2026-01-06]`) and commit it on the default branch. The next run
never labels, fits or holds out that day. When the served learned file counted it, that file
(the file lists the days it counted, so this holds even if `learn.json` was lost) is judged
again against the committed model: the refit without the day replaces it if it
passes the check, and otherwise a file that re-anchors nothing does, so the committed model's
chances serve until newer days pass. To return to the committed model at once, also delete
`predictions/learned.json` on the live host.

The live state reaches the workflow through the Actions cache: the live loop keeps it with
the `cache` state store (`config/live.yaml`, folder `out/internal/live/store`), and the
workflow that runs it must save that folder under a key starting `live-state-`
(`CACHE_KEY_PREFIX` in `pipeline/snowlight/live/state.py`; a test holds every workflow to
it). The step restores the newest such key and never saves it. A machine that runs the live
ingest itself reads `out/internal/live/state` directly. No workflow runs the live loop yet
(`config/live.yaml` keeps its state `local`), so until one does the step logs "no live
ingest state reached this run" and then "nothing to learn: no live-read district-days
labeled yet; the model is unchanged".

## The forecast history (S7-F, piece F1: data only)

Nothing on the site changes with this piece, and `predict.yml` serves exactly as before. It
gathers what the night-before chance (pieces F2 and F3) will learn from.

**The forecast.** The Weather Service's forecast grids (NDFD, the forecaster-edited 2.5 km
grids behind weather.gov), read by `pipeline/snowlight/predict/ndfd.py` from the public NOAA
bucket on AWS (from April 2020) and NCEI's archive (2018-19 and 2019-20). Three elements:
snow amount and ice accumulation (6-hour periods) and apparent temperature (hourly; the wind
chill when it is cold). A run is the three elements issued in one half hour; it counts 10
minutes after its time (and never before AWS wrote all three), and only while it is at most
3 hours old.

The delay and the archive copies, measured by the history's prepare step over every listing of
2018-08-14 to 2026-06-15 (2,863 days, 391,656 objects, 3.7 GB of listings, 21 minutes, on
2026-10-21): of the 181,524 AWS objects of school days written within 3 hours of their stamp,
0.50% were written over 10 minutes late (98th percentile 7.7 minutes, longest 167 minutes), so
the delay stays 10 minutes. Left out of that measure: 4,429 school-day objects written over a
day late and 11 written 3 to 24 hours late. AWS's first weeks (stamps 2020-04-17 to 2020-05-29)
were uploaded in bulk on 2020-06-01 to 06-03, 1 to 46 days after their stamps (6,139 objects);
a day on which AWS wrote at least 100 objects over a day late is such an archive fill, and its
objects count from their stamp plus the delay, as NCEI's files do (NCEI keeps no publication
time either), and are flagged in the sample table (`archive_copy`). Any other late object keeps
its write time (19 written a day late in 2023 and 2025, 12 written 3 to 24 hours late): its run
is too old by then and never counts. Read as publications, the bulk upload alone made 2.4% of
the school days' objects "late" and would have set the delay to 8 days, every code unknown.
Hours of school days with no run at most 3 hours old: 6.1% in 2018-19 and 8.2% in 2019-20
(NCEI's sparse evenings), under 0.4% in every AWS season. NCEI has no folder for 12 days
(2019-01-06, 06-15, 06-16, 07-28, 09-16, 11-17 to 11-22, 12-20; it answers 404): such a day
lists no files, the other day's runs still count, and a sample with no run says
`day_not_in_archive`. A day that does not list after the retries makes its nights unknown
(`listing_failed`, with the error), and no night stops a job. Prepare also probes the run newest at 03:00 UTC on the first night of every week, or at
12:00 UTC when none counts at 03:00 (its heads only, as a night reads them). On 2026-10-21 it
probed 343 of the 349 nights (6 had no run at either hour): no element failed to read, 12 runs
were stamped at the end (August to October 2018), 4 held their messages twice, and the 6 runs
of 2018-09-24 00:16 to 02:46 were refused. Prepare fails, and the matrix never starts, when the delay
is over 30 minutes, a season's school-day hours are gaps more than half the time, over 1% of
days did not list, or a month's probed runs mostly have an element that does not read.
Collect fails when a month's samples mostly come from runs or listings that did not read (the
share by month is in `manifest.json`). Every decode asserts the grid (a change stops the history), reverses every odd
row (the grids are scanned back and forth), and reads each school's cell. The window is the
periods ending 06, 12 and 18 UTC on the school day (7 PM to 1 PM Eastern, 6 PM to noon
Central, 5 PM to 11 AM Mountain, 4 PM to 10 AM Pacific, an hour later in daylight time),
less the periods already over; apparent temperature is read at 7 AM local. A district's value
is the one at least half its deciding schools reach (the class's rule), and its bucket is
one of 0 quiet, 1-5 snow (0.5, 2, 4, 6, 9 inches), 6-8 ice (0.01, 0.10, 0.25 inches), 9-12
feels (10, 0, -10, -20 F or colder), 13 unknown.

Every snow and ice message holds a whole 6-hour period, the period under way included. The
first message of a run is stamped from the run's reference time, but its values are the
whole period's: measured against the same period in the last run before the period began,
cell by cell where it held 1 inch or more (0.1 inch of ice), the median ratio stays 1.00
however late in the period the run comes (8% of the period left on 2025-01-06 snow, 2022-02-03
ice; 42% on 2019-01-19 snow and 2018-10-14 snow). So the period under way counts whole, snow
before the run included. Spec-f section 4 had assumed the part after the reference time; this
is its one switch, and pieces F2 and F3 name the period's start. NCEI's files stamp the periods
two ways: until 2018-10-30 13:15Z every message at its period's end, after it every message at
its start (the first at the reference time). Both read as the period ending at the message's
end, once every message is checked: 6 hours long, ending 00, 06, 12 or 18 UTC, one reference
time, ends rising, the first the period under way (the sample table's `period_stamp` says
`end` or `start`). Checked on 58 runs of every school year from 2018-08-15 to 2026-01-26
(13 stamped at the end, all before 2018-10-30 13:47Z, 44 at the start, one refused, below;
an end-stamped run of 2018-09-14 decodes and reads its window) and by prepare's probe (below). A run whose file holds another run (its first reference time not
within an hour after the run's time: NCEI's `201906030016` and `0017` files hold the run of
2019-07-03 00:30, and its six runs of 2018-09-24 00:16 to 02:46 hold those of 2018-10-24) is
refused before any value is read, and the run before it is used (`refused_runs` in the sample
table, the runs in each job's summary). Some NCEI files hold every message twice (half the
runs of 2019-08-19 and 2019-09-09): a repeated period is read once, and only when both copies
are the same bytes (`repeated` in the sample table). An element whose file
does not read leaves only its own values unknown (`element_error`; `run_error` when none
read), and the code is 13 only when the unknown value could change the bucket.
Every range read is checked against the file's size the host states (Content-Range, or a 416's
`bytes */N`), kept from the file's first answer that states it (a whole-file 200 is checked
against its own body length, which never sets the size): one that returns fewer bytes than the
file holds there, another range or another size, or a 416 without a size (S3 sends no
Content-Range with it) inside the size an earlier answer gave, is asked again up to 4 times (2,
4, then 8 s apart; `--range-attempts`) and is then an error of its element. A head the file
itself cuts short, or a file that ends inside a frame line (from its first `*`), is an error of
its element too, never a crash, and so is a file that ends inside its last message's body (the
walk checks that message ends in `7777` at the file's end), whether or not the night reads that
message: AWS's ice file `YZUZ98_KWBN_202412172147` ends 27 bytes into its last message
(1,709,991 bytes; its frame declares 150,916 more), which stopped the night of 2024-12-18 in
run 39698719822. Each job logs every run that did not read, whole or in part, and collect's
`manifest.json` totals them by run-night, a run counted once for each night that samples it
(`run_totals`: `run_nights`, `run_error`, `element_error`; collect prints `run-nights N,
unreadable N, with an unreadable element N`).

**The history workflow** (`.github/workflows/predict-forecast-history.yml`) streams the
2018-19 to 2025-26 school nights on GitHub's runners: 80 jobs (school year by months), each
about 30 nights, 25 runs a night, about 140 MB a night read and dropped at once. It keeps a
bucket per district, night and sample hour (every whole local hour from 8 AM the day before
to 4 AM, three per slot), and the tables that say how good the feed was: each sample's run
and its age, each object's lateness, the hours with no usable run, how each run stamped its periods,
and the runs and elements that did not read. It runs once when its workflow file lands and
whenever the owner starts it (Actions, "predict forecast history", Run workflow). It costs
nothing (a public repository's runners, public buckets, no key) and commits nothing: the
results are the artifact `forecast-history` (kept 90 days), with `manifest.json` listing
every file's SHA-256. Piece F2 downloads it to `pipeline/.cache/predict/ndfd-districts/`.

Each sample keeps two codes: `code` reads a school whose cell has no value as unknown, and
`code_filled` reads it as nothing forecast of that element; `missing` says which element had
no value (1 snow, 2 ice, 4 apparent temperature). Some offices issue no grid of an element:
on 2025-01-06 no ice grid covered about 18,000 of the 93,116 deciding schools (most of the
West) and no snow grid about 900 around Tampa Bay. Piece F2 picks the reading.

**The heads-up files.** `snowlight predict headsup` downloads the watches and cold
advisories (WS.A, BZ.A, LE.A, WC.A, EC.A, HU.A, TR.A, CW.Y, WC.Y) of every school year from
2015-16 from the same IEM service as the warning files, 12 requests and 28 MB, into
`pipeline/.cache/predict/mesonet.agron.iastate.edu/watchwarn-headsup-csv/` (its own cache;
the weights build's files are untouched), each with its SHA-256 provenance, and writes the
rows per season and code to `out/internal/predict/headsup.json`. Tropical Storm and Hurricane
Watches are issued until further notice, like the warnings, and IEM keeps a placeholder end
days later on a row no product ended: such a row ends when its event's last explicitly ended
row did (30 rows of 2015-16 to 2017-18, cut by 5.5 to 21 days; the count per season is in the
report). That end comes from products issued after the row's own, so such a row keeps IEM's
placeholder in `recorded_end`: piece F2 reads it as open until its end has passed, and as
ended only at a time after that. It exits 1 when a code has
rows in a season it cannot (Blizzard and Lake Effect Snow Watches after 2016-17, the Wind
Chill Watch and Advisory after 2023-24, the Extreme Cold Watch and Cold Weather Advisory
before 2024-25); on 2026-10-21 there were none. No class reads these yet.
