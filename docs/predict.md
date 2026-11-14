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
  Label reason rule 2 (Nov 3, 2026, `labels.reason_rule`): flooding, severe storms and a
  hurricane are a weather closing only on a day whose class is `tropical`; on any other
  class they are never positive, as heat and a power outage are not. A likely break day is
  also the general Election Day, Veterans Day as observed (the Friday or Monday for a
  weekend one), Columbus Day and Good Friday, so a planned day off, listed or not, labels
  nothing. Neither changed a label here: none of the labeled dates is one of those four
  days, and no flooding, storm or hurricane closing was lit on a labeled day.
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
- Backtest (`out/internal/predict/backtest/report.md`, internal), with the truth rule above
  and, since 2026-10-25, the per-fold rule: each fold trains on labels built only from the
  seasons before its test season (station audiences, gates and markets too; the fold label
  files `folds/labels-before-YYYY-07-01.parquet` that `predict label-audit` writes; see the
  label audit below); `--labels-rule whole` re-runs the earlier rule for comparison. Storm
  district-day Brier 0.0612 against 0.0974 for the national rate per class (B0), all rows
  0.0418 against 0.0665; pooled G1 passes with and without 2020-21. 177 storm rows of 2020-21
  (179 rows in all) are not scored: the 2020-21 fold's labels hold no rows of their situation.
  On the same 1,208 storm rows the earlier rule scored 0.1166 against B0's 0.1267; the report
  says so under its rule line, with the rows each rule left unmodeled per season (and
  `metrics.json` under `per_fold_beside_whole`). Under the earlier rule: 0.1090 against 0.1188 on
  1,385 storm rows, all rows 0.0774 against 0.0844.
  The truth rule costs accuracy: before it (round 3, a 0.05 tolerance) the storm Brier was
  0.0888. The national rate per class and region (B1) scores 0.0659 (0.1053 under the earlier
  rule); that is reported, not gated.
- Piece 1 gate (spec addendum 2026-10-20 d): G4 (the leakage tests in `tests/predict`, run by
  pytest with every gate, `test_fold_labels.py` among them; the report does not compute it) and
  pooled G1 (model against B0, with and without 2020-21) gate piece 1, and both pass. G1 per
  season, G2 and G3 are reported, not gated, because the model and B0 are judged on the same
  labels, which the archive biases high under alerts (earlier rule in brackets):
  - G1 by season (amended gate, addendum b): 2023-24 (567 storm rows) -0.0107 against B0, within
    the 0.005 tolerance [+0.0117, over it]; the other seasons have under 300 storm rows: 2020-21
    (8) -0.0600 [185 rows, -0.0093], 2021-22 (20) +0.0119 [+0.0121], 2022-23 (225) -0.1348
    [+0.0072], 2024-25 (131) -0.0511 [-0.1524], 2025-26 (257) -0.0016 [-0.0012].
  - G2: fails one bin: 0.8 to 0.9 (333 rows, 11 storm-day clusters, mean chance 0.872, observed
    0.988) [every bin with enough rows and clusters within its bound].
  - G3: closings given 50% or more 98.4% against B0's 100% at precision 0.941 against B0's
    0.886 [91.4% against 98.1%, 0.889 against 0.896].
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

## The storm-class levels (advisory-sane L3): what an alert day serves

Every advisory, warning and cold day is served from its **class's level**, never from an
archive closure share (`config/predict.yaml` `serve.anchor: true`,
`pipeline/snowlight/predict/anchor.py`). The archive's lists were picked from storm mornings
and big pages (it read 0.28% of plain mornings, 7.4% of advisory mornings and 20.6% of warning
mornings), so its shares (74% to 93% on an advisory day) say how the lists were picked, not how
often districts close. The days with no alert (`none`, `none_after`) stay on the chain above.

- **Classes** (`live_score.classes`): `advisory` (winter weather, freezing rain and lake effect
  snow advisories, and the day after a closing under one), `cold` (extreme cold warnings),
  `warning` (winter storm, lake effect snow, ice storm, blizzard and tropical warnings: one
  level until a kind has 5 live dates).
- **The level** is `E_e[sigmoid(alpha + o + e)]`, the mean over a market-day effect `e ~ N(0,
  1.5^2)` (20-point Gauss-Hermite), at the posterior mean of `alpha` (the plug-in level). The
  prior on `alpha` is normal, its mean set so a reference district's level is the
  capture-corrected target: 10% for advisory (80% band 4.3% to 20.6%), 10% for cold (3.6% to
  23.1%), 45% for warning (21.2% to 71.0%), from the capture-odds correction (k about 26.4) and
  the sampling bound. The delay chance is `(1 - p) x q`, `q` from Beta(1.1, 8.9) (11%) updated
  on the rows not closed. *Lead ruling (Oct 31): serve the plug-in level (registered).* The
  spec's words ("posterior mean of the marginal") would serve the Bayes predictive chance,
  which with no live label is 11.5% advisory, 12.0% cold and 45.6% warning; its prior table
  and the registered L0 comment ("mean solved so the level at the prior mean is the target")
  give the plug-in. The predictive (advisory 0.1146) is reported in `anchor.json`
  (`predictive`), not served; L4's frozen scorer judges calibration, and its shrink fallback
  acts on misfit.
- **The district's standing.** `o = delta_region + 0.5 x`, `x = -ln((f + 0.5) / (f_ref + 0.5))`
  with `f` the district's school days of the class a winter (2015-16 to 2024-25) and `f_ref`
  the national median over districts with at least one (advisory 4.0, warning 1.4, cold 0.3):
  a district that gets many advisories closes on a smaller share of them (Methow Valley, 9.4 a
  winter: 7%), one that rarely gets any on a larger share (at most 3 times the odds). A share,
  never a count: with the exposure weight 0.5, the closures a winter (`f x p`) still rise with
  `f`. A district with no history
  of its own (no eligible schools: charter and virtual districts) takes its county's median
  days and says nothing of its standing. The region delta is half the archive's log odds ratio
  of the region against the nation, clipped to 1, only for the advisory class (the spec's G7:
  "today only the advisory Northeast qualifies") and only where the region's archive record
  has level support (30 days, 3 dates, no date over half): today advisory Northeast, -0.415.
  The warning class's region shares sit at the archive's ceiling (Ohio Valley 106 of 107 closed
  against 1,027 of 1,071 nationally, a log odds ratio resting on one open day), so warning and
  cold take no region delta. A delta moves the level relatively; the archive's own share never
  sets one.
- **The live update** (Addendum B2). The posterior of `alpha` is refit, every process, on the
  outcome-blind live labels of `predict read-labels` (L1's private record
  `out/internal/predict/reads/`: `no_school`, `delayed`, and `unnamed` counted open, owner O5),
  read through one adapter (`snowlight/predict/anchor_labels.py`), from 2026-10-27 on, each
  market-day one cluster of the random effect. An unnamed row counts open with the list's
  sensitivity: `P(unnamed) = 1 - s (p + (1 - p) q)`, `s_A` from Beta(9, 1) and `s_B` from Beta(4,
  2) updated by the closed co-listing trials; tier B rows enter only once `s_B` is at least 0.7
  over 20 trials on 5 dates. With 30 live market-days `tau` is chosen from 1, 1.5, 2 and 2.5 by
  marginal likelihood, and with the ramp below only once the class's ramp is full: until then
  it is the registered 1.5 (at an unchanged `alpha` another `tau` alone would move the advisory
  level from 10.0% to 7.2% or 16.7%, and one date of 30 markets would free it). With no
  record (L1 not on the head, or no day labeled) the level is the
  prior's, which is correct. The record is kept forever, so the adapter skips a day file
  before 2026-10-27 by its name, unread (its trials too): a process reads only the days the
  fit can use, and a test holds a winter-sized record (100 days, 60,000 rows) to the 10 s bar,
  read and fit together.
  - *The market-day integral.* Each market-day's likelihood is a function of `alpha + e` alone;
    it is tabled once on the `alpha` grid's own points and summed against the `N(0, tau^2)`
    density (the trapezoid rule on an even grid: exact to under 1e-6 for any market-day whose
    likelihood is wider than one grid step). The registered 20-point Gauss-Hermite rule on
    `N(0, tau^2)` was inaccurate once a market-day holds hundreds of rows, as live advisory and
    warning markets will: its likelihood in `e` is then far narrower than the nodes' spacing
    (simulated, 80 sets with heavy-tailed market sizes: level errors up to 0.035, a band that
    could exclude the converged answer; the grid's level matches a 120-node rule to under 1e-4
    in every set, its band ends to 0.007). `quadrature_points` now sets only a level's mean over
    `e` (a smooth integrand, where 20 points are exact to 1e-6). *Lead ruling (Oct 31):
    accepted*, the grid market-day integral for each market-day's likelihood, with the
    registered 20-point quadrature for the served level.
  - *The delay share.* `q` is fitted with `p` in every unnamed row's likelihood (an unnamed row
    may hide a closing as well as a delay), at the posterior mean of `alpha`, in turn with
    `alpha` until it moves under 1e-4. Fitted as if no unnamed row could hide a closing, it came
    out low on warning days (0.092 at a true 0.10 at warning 45%, 0.085 at 70%); now 0.100 and
    0.104.
  - *The list sensitivity per row* (R2-S4). `s` is one list's naming rate
    (the registered estimand `named`, which L1 notes is biased low), while an unnamed row means
    no list named the district all day, and a row may be read by several. If the lists' misses
    were independent, a row read by `k` lists would hide fewer closings (`1 - (1 - s)^k`); the
    trials cannot tell, since they condition on a list having named the district, and misses a
    district causes (it told no list) are common to every list. L3 keeps the registered form
    and reports, per class, the unnamed rows read by two lists or more (`multi_list` in
    `anchor.json`), the rows the one-list form may overstate. *Lead ruling (Oct 31): keep one
    list's sensitivity per unnamed row (registered)*; the lead revisits once L1's real record
    shows the multi-list share.
  - *Speed and checks.* A row's offset is counted in whole grid steps (0.015, at most half a
    step off), each label's log chance is tabled once on the grid, and the grid is computed in
    full only where a coarse pass finds the posterior within e^-40 of its top: a season of rows
    of all three classes (240 market-days of 40 to 60 districts each) fits in about 0.2 s of
    one core. The fit is checked against scipy's adaptive quadrature (posterior mean of `alpha`
    to 1e-3, `q` to 2e-4), against an independent fine-grid integration of a 300-row market-day
    (mean and both band ends), and by simulated recovery (true levels 5%, 10%, 25% and 45%:
    mean estimates within 0.02, `q` within 0.005 of its true 0.10).
  - *The 80% band* (in `anchor.json` and the log line; not served). In simulations with
    heavy-tailed market sizes and the real exposure offsets it covers the truth in 21 to 26 of
    30 replicates at warning levels 30% to 70%, 32 of 40 at 30% over 80 market-days, and 22 to
    27 of 30 at advisory levels 3% to 25% over 15 to 60 market-days (it was 16 to 28 of 30,
    mostly under 20, with the fixed rule and the low `q`). It does not carry the uncertainty of
    `q`, `s` or the choice of `tau`, so it can still run narrow at the edges (22 of 30 at 3%
    and at 25%), and narrower when the lists name fewer closings: the figures above are at a
    list sensitivity of 0.9; at 0.7 it covered about 20 of 30 at advisory 10% over 60
    market-days, with the point estimate still unbiased (mean 0.100, `q` 0.102). L4 should
    read it as a guide, not a calibrated interval.
- **The ramp, the storm and the cap** (predict-next ONE-STORM, `live_update.ramp:
  "capped_storms"`). One storm is far too little to know a class's level (3 market-days cannot
  tell a true 45% warning level from anything between 20% and 71%), so one storm cannot move a
  level far, and each later storm adds to it.
  - *A storm* is a class's mornings with at most one weekday between them
    (`ramp_storm_gap: 1`). Monday, Tuesday and Wednesday are one storm. Monday and Wednesday
    are one: a morning the record lost, or one taken back, does not split a storm. Friday and
    Monday are one, and so are Friday and Tuesday, and Thursday and the next Monday. Monday
    and Thursday are two. A weekday with no school counts as a day between, so a holiday
    between makes two: a storm on the Wednesday before Thanksgiving and one on the Monday
    after are two storms, as are the last day before the winter break and the first after it.
    A storm is the class's own (a warning on Monday and one on Thursday are two warning
    storms even with advisory rows between), and mornings in different markets on
    neighbouring days are one storm, as markets on one date are.
  - *What a storm may count for.* Each market-day counts its information about the level,
    from its row count alone, never from a label: `n / (n + c)` whole market-days for `n`
    rows (`c` 6.50 for advisory and cold, 2.58 for warning). A lone row counts 0.13 (0.28
    for warning); a market-day of hundreds of rows counts almost 1, because it fixes the
    level only to that day's own spread. The start (the level with no live row) counts 3.11
    market-days for advisory, 1.56 for warning and 2.25 for cold. No storm may hold more than
    the class's registered share (`supply.<class>.max_date_share`: 25% advisory, 40% warning
    and cold) of all of it, the start counted in: a storm over its share is tempered to it,
    whether it has one morning or five. Because the start is counted the cap acts from the
    first storm on, and it never lowers an earlier storm when a storm is added. The delay
    share has the same cap of its own: a storm's rows not labeled closed against that
    start's 10 rows, so a first storm's open rows count 3.33 rows (advisory) or 6.67
    (warning, cold) there, however many they are.
  - *The ramp.* The served level, both ends of its band and the delay share go from the
    start toward that tempered posterior by a weight `w`: the least of the class's rows,
    storms and market-days over their registered full counts (`ramp_advisory: {rows: 300,
    storms: 8, market_days: 15}`, `ramp_warning` and `ramp_cold: {rows: 100, storms: 8}`),
    never over 1. A storm counts as one once it holds a whole market-day of information
    after the cap (a lone-row storm counts 0.13 or 0.28), and the market-days are counted by
    their information. With no row in use the served numbers are the start itself, the same
    as before this piece; at `w` 1 they are the tempered posterior itself, with `tau` chosen
    as built.
  - *What it does.* A first storm, whatever it holds (1 to 5 mornings, 1 to 1,000 rows a
    market, 1 to 100 markets, any labels), moves a warning from 45% to at most about 52% or
    down to about 38%, an advisory or cold level by at most 6 points, and the chance of a
    delay by at most 5. As built, one storm of 3 markets of 100 rows moved a warning to 6%
    (none closed) or 91% (all closed). Counted as one storm, three mornings of such a storm
    serve what one morning serves (49.3% all closed, 41.0% none closed). Later storms that
    agree are not bounded: storms of 3 markets all closed, a week apart, move a warning 45.0%
    to 49.3%, 61.9%, 70.7% (as built 90.6%, 93.9%, 94.7%), and two storms labeled in one
    refit move a level by both (a warning by up to about 17 points).
  - *What lowers the weight.* While the newest date's rows are the only change to the rows
    in use, `w` cannot fall, and `tau`, once free, stays free. It can fall when rows leave
    or storms join: a take-back ("To drop a misread day"), tier B leaving (it is judged anew
    from all trials at every fit, so a newest date of misses can take every tier B row
    out), a day file that stops reading, a lost labels cache, and rows that join two storms
    into one (a morning labeled between a Monday storm and a Thursday storm). The level is
    then the ramped fit of the rows in use, as defined, and the line says the lower count.
  - *The price is slower learning when the start is far off.* Mean error of the served
    level in points after 1, 3, 8 and 16 storms, on 200 made-up winters a case (storms a week
    apart, each of 1 to 3 markets of 60 to 100 rows a morning; seeded, in memory).

    One morning a storm:

    | Class, true level | As built | With the ramp |
    |---|---|---|
    | advisory 10 (the start is right) | 2.3, 2.3, 1.9, 1.8 | 0.2, 0.8, 1.8, 1.8 |
    | advisory 5 | 3.3, 2.1, 1.4, 1.4 | 4.8, 3.7, 1.5, 1.4 |
    | advisory 25 | 10.7, 6.4, 4.0, 2.8 | 14.8, 12.5, 4.6, 2.8 |
    | warning 45 (the start is right) | 8.5, 6.5, 4.5, 3.5 | 0.8, 2.4, 4.5, 3.5 |
    | warning 25 | 11.1, 6.7, 3.9, 3.0 | 19.0, 13.8, 3.9, 3.0 |
    | warning 65 | 11.9, 8.0, 4.8, 3.5 | 19.1, 14.3, 4.8, 3.5 |
    | cold 10 (the start is right) | 2.9, 2.7, 2.1, 1.8 | 0.3, 1.0, 2.1, 1.8 |
    | cold 5 | 3.0, 1.8, 1.3, 1.1 | 4.7, 3.4, 1.3, 1.1 |
    | cold 25 | 9.6, 6.6, 4.0, 3.2 | 14.6, 11.8, 4.1, 3.2 |

    One to three mornings a storm, a market's effect shared by the storm's mornings (what a
    real storm does):

    | Class, true level | As built | With the ramp |
    |---|---|---|
    | advisory 10 (the start is right) | 3.3, 3.2, 2.5, 1.9 | 0.2, 1.0, 2.4, 1.9 |
    | advisory 5 | 3.1, 2.0, 1.6, 1.2 | 4.8, 3.5, 1.6, 1.2 |
    | advisory 25 | 8.8, 6.5, 4.3, 3.1 | 14.7, 12.2, 4.4, 3.1 |
    | warning 45 (the start is right) | 10.8, 7.6, 5.3, 3.6 | 0.9, 2.8, 5.3, 3.6 |
    | warning 25 | 10.2, 6.7, 4.6, 3.4 | 18.9, 12.9, 4.7, 3.4 |
    | warning 65 | 11.2, 7.8, 5.2, 3.9 | 18.9, 13.3, 5.1, 3.9 |
    | cold 10 (the start is right) | 4.1, 3.4, 2.5, 1.9 | 0.3, 1.2, 2.3, 1.9 |
    | cold 5 | 2.7, 2.1, 1.8, 1.3 | 4.7, 3.0, 1.7, 1.3 |
    | cold 25 | 9.1, 6.7, 4.4, 3.3 | 14.5, 11.6, 4.4, 3.3 |

    In plain numbers: if the true warning level were 25% or 65% and not 45%, we would be
    about 19 points off after the first storm where the fit as built would be 10 to 12,
    about 13 to 14 against 7 to 8 after three, and the same from eight on (about 4 to 5, then
    3 to 4). Where the start is right it is the other way round: under 1 point off after the
    first storm against 8 to 11. The largest one-storm step among a winter's first 6 storms
    is, at the 95th percentile of winters, 5.2 to 8.1 points for warning with the ramp (21.9
    to 33.9 as built), 1.8 to 5.4 for advisory (5.1 to 20.3) and 1.9 to 5.8 for cold (6.0 to
    22.3).
  - *The morning the ramp fills* (`w` first reaches 1, and `tau` may be chosen anew) is the
    9th storm at the median of such winters (60 a case, 14 storms of one to three
    mornings). The step that morning is, for warning, 1.8 to 2.0 points on average, 4.7 to
    5.6 at the 95th percentile and 8.3 at most, with `tau` chosen anew in 16 to 19 of 60
    winters; for cold 0.9 to 1.7, 2.1 to 3.7 and 6.7; for advisory 0.9 to 1.6, 2.1 to 4.4 and
    6.5.
  - *The fit as built is made on every run* beside the served one (one more fit a class),
    for the log line and `anchor.json` only: it is what `ramp: "off"` would serve. If that
    fit raises, the served fit is untouched, the line says `built unavailable` and the run
    warns `anchor: the fit as built of <class>: <error type>: not in the line`.
- **To turn the ramp off** (a reviewed change on the default branch, by the lead's word).
  Three edits in one commit: (1) `config/predict.yaml`: `ramp: "off"`, quotes kept (a bare
  `off` is YAML's false: the config loads, the settings refuse it with the way to write it,
  and every predict run would stop at its start); (2) `predict/config.py`: `LIVE_SCORE_SHA256`
  recomputed, with a dated sentence in its docstring (with nothing else changed since landing
  it is `e69d3c72...`), and its sentence in the dated history below; (3)
  `tests/predict/test_retention.py`: the one assert of the committed `ramp`. Before pushing,
  `cd pipeline && uv run python -c "from snowlight.predict.config import PredictConfig as C;
  from snowlight.predict.anchor import AnchorSettings as A; print(A.of(C.load()).ramp)"`
  prints `off`. It acts at the next process start. What families see on the first file
  after: each class with rows goes from its ramped level to its as-built one, the `built`
  figure of the last line before (after a first warning storm of 3 markets of 100 rows, all
  closed, 49.3% to 90.6%), with no new "Up from" on those days on that file; a chance carried
  across a person's 30, 50 or 70% line sends that push. A class with no row does not move.
  The line then says `ramp off`, the take-back still works, the bus switch does not restart,
  and the frozen rows after it carry the new sha256. Turning it on again is the same three
  edits back.
- **Deferred** (Addendum B2 makes the live update a pure posterior over per-class label
  counts): the registered live region and state deviations (`standing.live_region_sd` 0.5,
  `live_state_sd` 0.4, from 5 live dates) and the warning split by alert kind (`split`, from 5
  live dates) are not fitted in L3; a test keeps them so until a later piece takes them up.
- **The day after a closing under an advisory** (`advisory_after`) is served as a plain
  advisory day, at the advisory level, and says the advisory sentence: the class has one level.
- **Plausibility** (G6, Addendum A item 5, before anything serves). Implied closures a winter =
  the sum over classes of `f x p`. Four steps, over the deployed districts:
  1. *The registered pull.* A district over 6 is pulled toward its class levels on the
     log-odds scale (`level + s (district - level)`, `s` down from 1 in steps of 0.05, never
     below the level) to the largest `s` that passes.
  2. *The cap (kept by the lead's ruling of Oct 31 as the G6 backstop on published chances,
     with the class shrink of step 4; both act only when a published value would break G6).*
     The districts over 6 are the most
     exposed ones, whose exposure already puts them under their class level, so pulling them
     toward it adds closures and the registered rule cannot reach 6. Such a district takes the
     `s` with the fewest closures, then one downward shift of every class's log-odds, the least
     that brings it to 6. Raised class levels well inside the prior's own bands would need it:
     on the served path (18,227 deployed districts, county exposure and region deltas
     included), advisory 12% and warning 50% cap 12 districts, advisory 21% and warning 71%
     150, advisory 15% and warning 85% 336.
  3. *The registered national steps.* While a national clause fails (advisory mean at most 1.0
     and p99 at most 3.0, advisory and warning mean at most 2.0), the districts with the most
     implied closures take one more step each toward their level, in that order, until it
     passes. A round finds how many must step by bisection (a step must lower a district's
     closures and add none of advisory, or of advisory and warning, so every clause only eases
     as more step), at most 20 rounds: the same districts as one at a time, in milliseconds.
  4. *A class level the national clauses refuse* (every movable district at its level and a
     clause still failing) is shrunk toward its prior: `alpha = prior + w (posterior -
     prior)`, `w` down from 1 in the pull's steps until the clauses pass (advisory alone; with
     the advisory and warning clause, warning too). The priors pass, so a live update cannot
     serve an implausible nation; this is Addendum A item 4's fallback, taken earlier. On
     today's exposure the national steps never act (pulled 0 at every raised level tried):
     this shrink does that work, and the advisory-mean clause holds the advisory reference
     level to about 29% at most (an advisory raised to 35%, 40% or 52% serves at 28.5% to 28.7%).
  Every clause is judged on the chances **as published** (to the hundredth, with the 1% floor),
  never only on the raw ones: rounding adds up to half a hundredth of a class's days a winter,
  so a capped district rounded up would be served over 6 (at advisory 21% and warning 71%, 97
  districts at up to 6.11). A district rounding would put over 6 takes, class by class from
  the one rounding raised most, the hundredth under its raw chance instead, and the national
  steps check the published chances throughout; the log line and `anchor.json` report the
  published figures, which publishing then keeps.
  The pass logs `predict: anchor plausibility: advisory mean 0.31 p99 0.87, advisory and warning
  mean 0.97, most 5.51; pulled 0, capped 0, shrunk 0` (districts pulled and capped, classes
  shrunk) for every serving model it builds (the outlook's
  too), warns (an Actions annotation) whenever a district was capped, a class shrunk or a clause
  still fails, and writes it to `anchor.json` (`plausibility`: before and after, pulled, capped,
  rounds, failing, shrunk, the served levels). Today, on the served path, nothing is pulled or
  capped: advisory mean 0.31 and p99 0.87, advisory and warning mean 0.97, the most of any
  district 5.51, all as published.
- **What it serves** (dry run of the live head's directory, no live label). Advisory: 0.80
  mean before (p10 0.56, p50 0.74, p90 0.97), 0.116 after (p10 0.07, p50 0.10, p90 0.21);
  warning 0.95 before, 0.46 after (0.27 to 0.57); cold 0.77 before, 0.11 after. The exposure
  term centres on the median district, not on the day-weighted mean, so averaged over the
  advisory days districts actually get the served chance is 8.6% (warning 41.5%, cold 8.6%).
  *Lead ruling (Oct 31): no re-centring on the day-weighted mean now*: about 8.6% over the
  advisory days districts get is near 1 in 10, as the spec asks. L4 reports the day-weighted
  served mean per class, and the lead revisits with scored nights. On October 28, Methow Valley
  SD (advisory) went from 93% to 7%, and Yosemite-Wawona's advisory chance from 74% to 13%.
- **Private schools** take the same levels at their county's exposure, with no private offset,
  and never say a standing.
- **The sentence.** The base is `class` (`ClassBase`): "Districts like Yosemite-Wawona close or
  go remote on 1 in 8 winter advisory days." The share is true to the whole percent by the
  record sentences' own rule (`shareOf`: an exact plain share, else "more than" the largest
  under it, "more than 2 in 5" for 45%), never hedged. Where the district's standing holds of
  the number shown (its exposure says it gets more of the class's alerts than most districts
  and its chance is under the class level by a published point, or fewer and over it) and the
  two read as different shares: "Methow Valley gets more winter advisories than most, so it
  closes or goes remote on a smaller share of them: 1 in 14." (a share, never "fewer of them":
  a district that gets more advisories may close on more of them in all). The share is joined
  with no-break spaces, so a phone never wraps it. A share that is not exact is bounded the way
  the sentence points: a smaller share "under" the smallest plain share over it ("under 2 in
  5" for 34% to 39%), a larger one "more than" the largest under it; the fixed words are at
  most 136 characters. "Half of" says "half of the days with a blizzard warning". The warning
  class is named by the storms it warns of, never by amounts, and from the district's own
  history: "winter storm warnings" for a district that had no hurricane or tropical storm
  warning day in the winters its standing counts, "storm warnings" for one that had (the
  base's additive `tropical` flag, sent on a warning-class day from the exposure file's list;
  a private school takes its county's). A reader of an older file, or one without the flag,
  says winter storm warnings. Every more and fewer claim stays true against most districts
  with these names: on the committed exposure, 4,194 more and 3,768 fewer winter storm warning
  claims (each against the other districts' winter warning days) and 398 more and 1,007 fewer
  storm warning claims (against all warning days), 0 false. An advisory or extreme cold alert
  names its own class. For a Northeast
  district the advisory region delta (-0.415) also lowers the chance, so the "so" of a "more"
  standing credits the whole gap to its advisory count; the line stays true (the number shown
  is under the usual level and the district does get more advisories), and a capped
  district's shift does the same. The base carries the class level (`usual`) for that check. It
  never says "recorded".
- **Previous chances across a change of method.** A storm day's cell whose last chance came
  from the other method carries no previous chance: the first pass that serves it from its
  class level (the old chain's 93% is another method's number, not the storm weakening), and
  the first pass after `serve.anchor` is turned off (the class level's 7% beside the chain's
  93% would read as the storm worsening). A day that was quiet at the last pass keeps its
  previous chance when an alert comes ("Up from 3% at 5 PM" is an earlier forecast of the same
  day), and so does a storm day whose alert has passed. A day counts as stormy when its
  forecast named weather (a quiet outlook day with forecast snow counts too, so it drops a true
  previous chance rather than show a false one).
- **Previous chances on the morning a level moves** (predict-next ONE-STORM). A class's
  level moves at a process start: a refit on a newly labeled date, a take-back, tier B
  entering or leaving, or a deploy that changes the levels. That is no change in the
  weather, so on the first file after it no day served from that class in both files makes
  a new previous chance ("Up from 45%" beside 47% would read as the storm worsening), the
  days the forecast moved and the private schools included. A previous chance the last file
  already carried ("Up from 3% at 5 PM", made when the alert came) stays while the chance
  now shown is on the same side of it, and is dropped where the level took the chance to it
  or across it. A district whose class changed keeps its previous chance, and the next file
  compares as before. A pass reads this from the last public file only (a class has moved
  when some district's class base points differ between the two files), so a refit too small
  to move any district's whole point is not seen. If the forecast read fails on that first
  pass, an adjusted day shows its bare class level for that one pass, with no previous
  chance, and the next pass that reads the forecast shows the forecast's chance again. One
  thing this does not hold back: a refit can carry a chance across a person's 30, 50 or 70%
  alert line (a warning day going from 45% to 50%), and that sends the person's "high chance"
  push once, with no change in the weather.
- **Learning.** `predict learn` builds the models it scores and compares with the class anchor
  too, as the passes build them (`cli.learn_builder`), so its no-worse decision scores every
  storm-class cell on the class level that serves it, the same in the committed and the
  learned model, and rests on the days with no alert; the chain's storm numbers, which no
  longer serve, never decide a swap.
- **Turning it off** (`serve.anchor: false`): only outside an alert evening. Every storm-class
  cell then serves the chain's numbers again (74% to 93% on an advisory day), with no previous
  chance, and the chance pushes fire on them: a school whose chain chance is over a
  subscriber's threshold sends its first "chance" push that evening.
- **Files.** `data/predict/exposure.json.gz` (codes and counts: each district's class days a
  winter in tenths, county medians, the national references, the archive's nation and region
  tallies of each class, and the districts and counties with a hurricane or tropical storm
  warning day in the winters) is built by `snowlight predict exposure --work <labels folder>`
  from `weather.parquet`, `districts.parquet` and `labels.parquet`; the same inputs give the
  same bytes. The command refuses to write a file whose class levels at the priors (no live
  label) fail G6 over the districts it holds, after the pull and the backstop, so such a file
  never reaches a pass (the committed one passes with nothing beyond the registered pull). A
  file without the tropical list does not read (the pass then serves the class levels alone,
  with no standing). A pass logs one line, `predict: anchor: advisory 0.100 (0.043-0.206) q 0.110 rows
  0 on 0 dates; warning 0.450 (0.212-0.710) q 0.110 rows 0 on 0 dates; cold 0.100 (0.036-0.231)
  q 0.110 rows 0 on 0 dates; ramp advisory w 0.000 no rows, warning w 0.000 no rows, cold w
  0.000 no rows; tempered none; take-back none listed; 9 labeled days` (counts and numbers
  only). After a first advisory storm of two mornings of 3 markets of 100 rows it reads
  `...; ramp advisory w 0.125 by storms 1.00 of 8 raw 0.114 q 0.124 built 0.138 q 0.166,
  warning w 0.000 no rows, cold w 0.000 no rows; tempered advisory 2026-12-02 x2 level 0.644
  to 0.250 delays 0.982 to 0.250; take-back 1 day listed (1 in the record), 3 rows listed (2
  in the record); 11 labeled days`: per class the ramp weight and the count that holds it
  under 1 (`by rows 212 of 300`, `by storms 1.00 of 8`, `by market_days 0.94 of 15`, or
  `full`), `raw` the tempered posterior's level and delay share, and `built` the fit as
  built's (what `ramp: "off"` would serve); each storm held to its share with its first
  date, its mornings (`x2`) and its share before and after, in the level and in the delay
  share (six are named, then `and N more`); and each take-back list with what it names and
  what of it the record holds. With `ramp: "off"` the two segments read `ramp off`. The
  pass keeps the private report `out/internal/predict/anchor.json` (never
  published; per class the level, the prior's and the predictive, the band, `q`, `tau`, the
  sensitivities, rows, market-days, dates, `k_eff` and `multi_list`, and `ramp`: the weight,
  its three counts and their full counts, the start, the tempered posterior, the fit as
  built and every tempered storm; the rule's name, `ramp`; the take-back counts, `left_out`;
  the labels' days and the last labeled day, `through`; the plausibility outcome). An exposure
  file that does not read
  leaves every unit at its class level. `anchor.json` is not kept after the job: no workflow
  caches or stores it. Until L4 stores the score history (L4 is the next piece but one in this
  lane), the two log lines of each pass (`predict: anchor:` and `predict: anchor
  plausibility:`) in the Actions logs are the record.
- **The lead's rulings (Oct 31)** (also in `config/predict.yaml`'s plausibility comments): (1)
  the cap and the class shrink beyond the registered pull are kept as the G6 backstop on
  published chances, acting only when a published value would break G6 (with them the
  effective ceiling of about 29% on the advisory reference level), and the log line counts
  pulled, capped and shrunk; (2) the plug-in level serves (registered), the predictive mean
  (0.1146) is reported, not served, and L4's frozen scorer judges calibration, its shrink
  fallback acting on misfit; (3) no re-centring on the day-weighted mean now (8.6% over the
  advisory days districts get is near 1 in 10), L4 reports the day-weighted served mean per
  class and the lead revisits with scored nights; (4) accepted: the grid market-day integral
  for each market-day's likelihood, with the registered 20-point quadrature for the served
  level; (5) one list's sensitivity per unnamed row is kept (registered), `anchor.json`
  reports the multi-list rows, and the lead revisits once L1's real record shows their share.

Not yet here: the
nightly scorer with its shrink toward the prior (L4). With L2's held record cancelled, nothing
in L3 freezes the candidate variants (C-v2, C-prior, C-flat, C-exp) at 20:07 D-1 and 05:07 D;
the fit is deterministic from the committed exposure file and the append-only label record
(the labels of days before D, `through` in `anchor.json`), so L4 can rebuild each frozen
variant exactly, or keep them in the private evidence store: L4's call, with the lead.


## The forecast adjustment (advisory-sane L5): the forecast within the class

With `serve.anchor` and `serve.forecast_adjust: "on"`, the forecast for the school morning moves
each advisory and warning day's chance within its class (Addendum A item 3,
`pipeline/snowlight/predict/forecast_adjust.py`). The class level of the section above is the
start, `p0`; from the day's class snapshot on (9 PM the evening before on the school's clock),
the forecast read at that snapshot (the newest NDFD run at most 3 hours old, the district's 50%
value over its deciding schools) adds transparent terms on the log-odds scale, each with a
physical reason. It is our own method; nothing in it reads a closure share.

- **Snow against the district's own climate** (both ways): `1.0 x ln((s + 0.5) / (u + 0.5))`,
  `s` the window's snow still to come (the periods ending 06, 12 and 18 UTC on the day, the
  period under way only for its part after the snapshot: SF-R5-1 is fixed first, so snow
  already on the ground is never counted as coming), `u` the district's usual snow on days of
  the class (below). The same inches matter more where snow is rare: an inch over Atlanta's
  usual 0.65 in raises its advisory chance far more than an inch under Buffalo's usual 1.96 in
  lowers Buffalo's. Where a district's days of the class are often icy, its `u` counts the ice
  days and is over its usual snow alone `u_a` (`u` solved with its ice days as quiet ones), so
  the same inches count for a little less there: a documented limit (PHYS-R3-S1 (i), counted
  below). Round 4 anchored the term at `u_a` (never under 0 from `u_a` up); the lead withdrew
  the anchor on Nov 1, since its flat stretch from `u_a` to `u` let the ice and timing terms
  make more snow lower the chance (with 0.1 in of ice Memphis-Shelby's warning fell from 65% at
  1.5 in to 55% at 5 in; at 0.25 in of ice the chance fell with more snow in 9,522 districts'
  advisory days and 7,276 districts' warning days). `u_a` is the snow line's second bar only
  (below).
- **Timing** (both ways): snow from 10 PM the evening before to 9 AM on the school's clock is on
  the roads for the buses, with little time to plow; snow earlier in the evening is plowed by
  morning, and snow after 9 AM falls on a school day already under way. Each deciding school's
  own snow in those hours is counted first (each period's snow taken as even through it), and
  the district takes the 50% value of it by the same rule as `s` (`snow_commute`). The snow
  weighed by its hours is `W = (0.5 s + 0.5 commute) / even`, `even` the window's even weight
  (`0.5 + 0.5 x` the share of the window's hours inside 10 PM to 9 AM, taken at most 0.9, so
  snow at least 80% inside those hours never lowers the chance, in Alaska and Hawaii too), and
  the term is `ln((W + 0.5) / (s + 0.5))`, held within 0.4 either way, a band phased in from no
  snow to half an inch (0.4 x min(1, s / 0.5)). In every zone the overnight period raises it
  (Eastern 1 to 7 AM +0.15, Central midnight to 6 AM +0.13, Mountain 11 PM to 5 AM +0.10,
  Pacific 10 PM to 4 AM +0.09, for 4 inches over a usual 3) and snow ending by evening or
  falling after 9 AM lowers it. This is L5's timing, served until Nov 3, 2026; then the bus
  hour timing term served in its place (`timing_bus`: snow before 7 AM against snow after it,
  measured on past winters; "The bus hour timing term" below), and with it off the timing is
  this one exactly. Since Nov 4, 2026 (predict-next TIMING-AUTO) no timing serves:
  `timing_after_bus` is 1.0, so the timing part is 0 everywhere and no timing line shows; the
  bus term at its fit 0.95 is the live switch's on arm, served only once it is consistently
  better on live storm mornings ("The live switch" below).
- **Ice** (adds only): an inch of the window's ice counts as 25 inches of snow on top of the
  day's snow (a tenth of an inch as 2.5 inches): `ln((s F + 25 i + 0.5) / (s F + 0.5))`. A
  trace of ice adds a little to a dusting's term (Buffalo's advisory: 1% with no ice, 2% with
  0.01 in), never the jump to a raise that replacing the snow term made.
- **Cold at the bus stop** (adds only, snow classes): 0.02 a degree that it feels below 15 F at
  7 AM, at most 0.3.
- **One log.** Snow, timing and ice together are `ln((W + 25 i + 0.5) / (u + 0.5))` (`W` held
  to the timing band), one usual `u` for every forecast (the anchor withdrawn, above). `s`
  and the commute snow are each a 50% value of a quantity that only grows with any school's
  snow in any period, `W` only grows with both, and the band's edges
  only rise with `s` (the settings are refused otherwise: (0.5 + 0.5) x 0.4 <= 1.0 x 0.5), so
  more snow in any period at any deciding school, more ice or more cold never lowers the
  chance. Round 2 took the timing factor from the periods' own 50% values while `s` was the 50%
  value of the schools' totals; where the deciding schools differed, the two did not match and
  adding snow could lower the chance (PHYS-R2-B1: New York advisory 28% to 27% when 1.9 in was
  added after 7 AM at one of two schools, Los Angeles warning 75% to 72%; through the reader now
  29% and 75%). Tests add snow to each period at one school and at every school of districts of
  2 to 7 deciding schools through the reader, in Eastern, Central, Mountain and Pacific time and
  both classes, and to each period of one-school districts on a grid: never lower. A probe of
  432,000 additions through the reader, each checked in both classes (six zones, Alaska and
  Hawaii too, 2 to 7 schools independent or sharing one timing pattern with 30% noise), found
  none lower the total or the published chance (round 2: 53,005 of 960,000 lowered the total).
  Through the path serving takes (`fa.adjusted` with the snow alone's `u_a` and
  `serve._order_cap`'s cap) on the deployed directory, every one of 18,227 districts' advisory
  and winter storm, lake effect, ice storm and blizzard warning days, snow 0 to 8 in even or
  late in the window, ice 0, 0.05, 0.1 and 0.25 in, and 10, -5 and -20 F beside 25 F (0 to 8
  in, even, with and without 0.1 in of ice): 0 falls with more snow, 0 with more ice, 0 with
  more cold (the round-4 anchor: 14,558 advisory and 17,973 warning steps fell at 0.25 in of
  ice). A test runs the same grid through the same path on
  the committed climate's icy districts (the 30 warning and 10 advisory districts whose `u` is
  most over `u_a`), the named ones and every 400th, and one through `forecast_file`; both fail
  on the round-4 code (6,331 falls).
  A timing line names the heaviest snow by the hour where that is on the term's side, else
  the period on its side with the most snow by the hour
  (`snow_hours`: "The forecast has snow 12 to 6 AM, just before the buses."). The periods' 50%
  values only name the hours, and only where they add up to at least half of `s`: where the
  deciding schools' snow falls at different hours no one period stands for them, and the
  timing's points are said with the snow line instead (the chance is the same; PHYS-R2-S3).
- **Bounds** on the terms together: advisory -0.7 to +2.0 (10% moves between about 5% and 45%);
  warning -0.4 to +1.5. A 9 PM read cannot see snow already down (SF-R5-1 counts only the snow
  still to come), so a forecast of no new snow lowers a warning day only a little and an
  advisory day to about half its level, no less (PHYS-R3-S2, the lead's ruling of Nov 1: round
  3's -1.5 took 82% of districts' 0.00 in advisory days under half their level and 6.6% to
  1%). Each pass's shift note gives the share of each class's district-days at its lower bound.
  `QUIET` (0.1 in, what a quiet day's code stands for) is assumed, a POSTLAND check: measuring
  it on live advisory nights is on the after-landing list.
- **Class order** (PHYS-R3-S1 (ii)): for the same forecast, an advisory day's chance is never
  over the same district's winter storm, lake effect, ice storm or blizzard warning day's: the
  advisory's terms are held under `logit(lowest warning chance) - logit(p0)` (the warning
  situations' chances unrounded, a blizzard warning's its class level), so the published
  advisory chance never passes the published warning chance. The warning class is solved first
  and the advisory's `u` is solved with the cap in, so the advisory class still averages its
  level. The cap only lowers, and is the lowest of chances that each only rise with snow, ice
  and cold, so the direction rules hold. On the deployed directory every warning level at its
  -0.4 bound is still over the advisory level (the least gap 0.56 log-odds), so the cap never
  takes an advisory day under its level. Round 3 put an advisory day over the warning day in
  279 of 255,178 district-forecasts (0 to 8 in, with and without 0.1 in of ice; Arkansas mostly)
  and over a blizzard warning day in 36,429; now none: 0 of 2,150,786 for each warning
  situation through `serve._order_cap` (the grid of the One log above). Tests hold it over
  every committed-climate district and morning on the solve's chances, through
  `serve._order_cap` and `fa.adjusted` on the served grid, and through `forecast_file` (every
  class of the order on the same day and forecast).
  A blizzard warning day keeps its class level (PHYS-S8):
  its wind is the hazard as much as the new snow and wind is not a term, so a ground blizzard
  with little new snow is never lowered; and since the class's climate does not tell blizzard
  days apart, raising them without ever lowering them would put their days about 6 points over
  their level (52% for 46%). A cold day is not moved (the cold is the class itself), nor a
  tropical storm or hurricane warning day (its hazard is not the snow).
- **Only from the class snapshot on** (turn-on items 8 and 10, the first option those items
  gave): before 9 PM the evening before, and for any day after the next school day's, a day
  keeps its class level and is not read. So no earlier run with a longer lead than the 9 PM
  calibration is served, a Saturday evening pass says nothing of Monday's forecast (Monday's
  snapshot is Sunday 9 PM), and "overnight" always means the night before the day.
- **No forecast** (the run did not list or read, none at most 3 hours old, an unknown code, a
  deciding school with no snow value in the run, such as one off the lower 48's grid, a day
  said open, a private school, which has no deciding schools of its own to read): no term,
  the chance is the class level and no forecast line shows, unless the last file holds the same
  district-day's lines from the same snapshot at the same class level (below).

**The reader's limits** (B1). The adjustment reads through the outlook's bounded reader
(`outlook_live.settled_reader` over `forecast_reader`): 10 s per request (5 s to connect), 2
tries, the day listings once a pass (`Listings(again=False)`), and every request inside the
pass's 60 s (`ADJUST_SECONDS`, a `Budget` started each pass), each answer read as it arrives
and stopped once the 60 s are up, so a host that drips bytes holds a pass no longer than its
60 s and one 10 s gap (S-R2-4). A day is read at each zone's fixed 9 PM snapshot, so a run's
values are kept until the day they were read for has passed everywhere (`prune_days`), not
4 hours as the outlook keeps them: round 2 dropped them after 4 hours and re-read every zone's
run on every pass from about 1 to 4 AM local on, the passes that matter most (S-R2-2, on the
real feed for Oct 30: 21.7 to 27.6 s a pass, all 18,227 districts read). Now the first pass
after each zone's 9 PM reads its run (one to five runs a night: about 22 to 30 s of the 60 s
for all five together) and later passes of the same process read nothing new. The cache is per
process: the predict job is one `snowlight predict run --until +320m` process that restarts
every 320 minutes, so each restart's first pass reads every zone's snapshot run again (the same
22 to 30 s), at least two full reads a night; the cache is not kept across restarts. Zones are
read largest first by their deciding districts, so a pass whose time runs out part-way leaves
the fewest districts unread (T-R3-S1).

A run read that fails part-way (an element that does not read, a range read that fails twice,
the pass's 60 s running out mid-run) is a failed read, never a read (T-R3-B1): it gives no
district of its zones a forecast, is never kept, and leaves those zones unread (`error`) with
one warning line a cause naming the zones and their runs ("forecast: 2026-10-30
America/Chicago (run 03:47Z): not read, read again next pass: snow: read: the pass's 60 s of
forecast reads are up"). The same snapshot's lines then stand (below), with no previous
chance, and the next pass reads the run again with its own 60 s; the read memory for previous
chances counts only district-days read without error. Round 3 kept such a run as read (every
district code 13, no line), so on the real feed a 4 s budget swung all 18,227 adjusted
district-days to their class level with "Down from N%" until the day was over. The outlook
(S7-F) reads through the same function, so a partly read run is a skipped sample there, never
one recorded as unknown. A host that stalls costs a pass at most its 60 s
and one request under way (a test with a stalled fake host: under 72 s simulated, then the
class levels with no previous chance), never the 14 minutes the history's reader (30 s limits,
6 tries, listings again on every read) would take, so the chances never fall behind the
alerts.

**A failed read keeps the same snapshot's lines** (PHYS-S7). From the snapshot on every pass
reads the same run, so a read that fails in a later pass gives the last file's chance and lines
for that district-day where the last file was made at or after the snapshot and its class level
and the alert or weather its base names are the same (a lake effect snow warning's lines are
never kept for a winter storm warning at the same level: PHYS-R2-S4); never a swing to the
class level and back. Where the class level or the situation changed (a new alert, the live
labels) or no file holds the lines, the class level.

**Calibration: each district's days still average its class level.** `u` is solved per district
and class level (bisection on `ln(u + 0.5)` in 0 to 30 in) so that over the forecasts the
district had on its own days of the class, its adjusted chance averages `p0`. Those forecasts
are the forecast history's 9 PM codes (2018-19 to 2025-26) on the weather history's class days,
`data/predict/forecast-climate.json.gz` (codes and counts only, 236 KB, built by `snowlight
predict forecast-climate --codes <codes folder> --window whole|still_to_come --work <labels
folder>`; the same inputs give the same bytes). Each code stands for its bucket's middle (0.5-2
in 1.2; 2-4 3; 4-6 5; 6-9 7.5; 9 or more 11), a quiet day (and a cold or ice day, whose snow is
under half an inch or not known) for 0.1 in; each snow or ice day's 7 AM is cold as the
district's own quiet and cold mornings are, since the codes keep a morning's feel only on a
day with under half an inch of snow while the live cold term counts a cold snowy morning too
(PHYS-S1: the cold term is in the solve). The codes keep the window's total alone, so each
day's snow is taken as even through the window, with the timing term even snow has in its zone:
none where the window's even weight is under the 0.9 cap (Eastern, Central, Mountain), and
where the cap holds it the solve counts it (Pacific 1.0205 times the snow inside the log;
Alaska and Hawaii more), so those zones' days still average their level (PHYS-R2-S2: round 2
left it out, about +0.01 log-odds in Pacific time and +0.05 in Alaska on the class level). With
the bus hour timing term on (below), even snow has no timing term in any lower-48 zone, so
their factor is exactly 1 (Pacific's too), and Alaska's and Hawaii's are 1.0013 and 1.0055 (L5:
1.0570 and 1.0606); no district of the committed climate is in Alaska or Hawaii time. No timing
(`timing_after_bus` 1.0, served since TIMING-AUTO) makes every zone's factor exactly 1, Alaska's
and Hawaii's too. A
district with few days of a class takes 10 days' worth of its county's mix (its region's where
the county has under 30). A place with no region of its own in the climate (it holds no Alaska
or Hawaii rows) never borrows the nation's: its days keep their class level (S-R2-1; on the
deployed directory every district has a region). Each situation's level is solved on its own
(the situations of a class share one level today: PHYS-S4).

The file says how its codes counted the period under way at 9 PM (`window`): `whole`, as the
history was collected before SF-R5-1 was fixed. A `whole` climate's amounts are scaled to the
fixed window by the zone's share of the window still to come at 9 PM (each period's snow even
through its 6 hours, the window's even through its periods), averaged over five school days
from November to March (daylight time in November and March; in Hawaii and Alaska 9 PM falls
after the first period, so only the later periods count): Eastern 0.900, Central 0.844,
Mountain 0.789, Pacific 0.733, Alaska 0.944, Hawaii 0.917. A climate built from codes collected
the fixed way says `still_to_come` and is not scaled; a file that says neither is refused (the
class levels alone), so a rebuild can never be scaled twice (PHYS-S5, S2, S10).

The calibration is exact on those code values. How far the live days can sit off it (dry run of
the live head's directory, the published chances averaged over each district's days, the
solved `u` held): a live quiet day that reads 0.00 in instead of 0.1 takes the advisory class
average from 0.1156 to 0.1131 (1 district in 100 has its own days 11% or more under its level,
the median 1% under), one that reads 0.2 in to 0.1188 (1 in 100 10% or more over), 0.4 in to
0.1253; snow spread evenly through each bucket instead of at its middle, 0.1161 (1 in 100 2%
under or 3.5% over). Warning days: 0.4570 to 0.4593 for 0.0 to 0.2 in (round 4's anchor: advisory
0.1112 to 0.1216, warning 0.4552 to 0.4611, where a quiet day sat on the steep part of its
phase). How live quiet days read is a POSTLAND check (`QUIET`). Live snow is not even through the window, so a
day's timing term is not even snow's: over random shapes (each period's rate drawn at random,
1 to 6 in, January and March), its mean less the solve's even snow's is -0.008 to +0.002
log-odds in Eastern, Central and Mountain time, -0.007 to -0.026 in Pacific, -0.003 to -0.001
in Hawaii and +0.007 to -0.042 in Alaska (round 2 left the cap's part out: +0.005 to +0.015
in Pacific, about +0.05 in Alaska and Hawaii); under a point at a 45% level. Re-measured for
the bus hour timing term (each 6-hour period's snow drawn at random, 1 to 6 in, a period under
way for its part, January and March, a usual of 3 in, the registered class slopes, 2,000
shapes each): -0.000 to +0.001 log-odds in every lower-48 zone, -0.003 to +0.001 in Alaska and
0.000 in Hawaii; L5's at the same slopes is -0.005 to +0.000 in Eastern, Central and Mountain
time, +0.005 to -0.064 in Pacific, +0.020 to -0.094 in Alaska and -0.002 to -0.001 in Hawaii.
Each pass logs the class's mean shift
(`forecast adjustment: advisory N days, M moved, mean +0.0012`), so a drift shows at once.

Ice days set `u` too: ice only adds, so a district whose days of a class are often ice days
balances them with a higher usual snow, and its snow-only days are moved against that `u`: the
same inches count for less there (PHYS-R3-S1 (i), a documented limit since the lead's ruling of
Nov 1). Of the 1,443 warning districts with at least 5 days of their own and 30% or more of
them ice days, 2,068 snow-only warning cells (0, 1, 2, 3, 4, 6 and 8 in, no ice) over `u_a` are
lowered, in 1,389 of those districts; over all 18,227 districts 6,384 of the 67,659 cells over
`u_a` (in 5,412 districts), by at most 10 points. Memphis-Shelby's warning (`u` 3.55 in, 1.50
alone): 0 to 2 in 35% (its lower bound), 2.5 in 38%, 3 in 41%, 4 in 48%, 5 in 53%, 6 in 57%, 8 in
63%; with 0.1 in of ice 48% at 1.5 in, 62% at 5 in, never falling. Round 4's anchor lowered none
of those cells but broke the direction rule (above), and a total that keeps both is a
follow-up piece. The line between `u_a` and `u` says no comparison (below). A test pins the
limit's count on the committed climate at its test levels (5,394 cells), so any change to it
shows.

Three guards keep the average true:

- A district whose days of a class no `u` can balance keeps its class level on those days,
  which is calibrated: on the committed files none of the 18,227 (round 4's anchor left 296
  districts' advisory days and 165 districts' warning days without one).
- G6 is checked again on the adjusted chances as published (to the hundredth, with the floor),
  averaged over each district's days and mornings (a class's at its highest situation's): a
  district whose days would then come to more than 6 closures a winter (and more than at its
  class levels) is not adjusted at all. On the committed files no district is.
- Then every G6 clause is asserted on those adjusted means in `build_model` (PHYS-R3-S3, the
  lead's ruling of Nov 1): the national advisory mean (at most 1.0) and p99 (3.0), the advisory
  and warning mean, and the most of any district. A clause that fails, where the adjustment
  makes it worse than the class levels do, turns the adjustment off for every district (the
  class levels serve) and the pass warns: `predict: forecast adjustment plausibility: advisory
  mean 0.310 p99 0.876, ... FAILS advisory_mean: the class levels serve, no adjustment`. Every
  pass logs the line. Tests cover both paths.

**What it does** (dry run of the live head's directory, no live label, the committed climate):

| | advisory | warning |
|---|---|---|
| usual snow `u`, median (p10 to p90) | 1.45 in (0.42 to 2.23) | 3.19 in (1.15 to 5.43) |
| usual snow alone (ice days as quiet), median (p10 to p90) | 1.16 in (0.27 to 1.83) | 2.78 in (0.90 to 5.28) |
| districts with no `u` (class level) | 0 (round 4: 296) | 0 (round 4: 165) |
| class average, class level then adjusted (published, over each district's days) | 0.1158, 0.1156 | 0.4586, 0.4581 |
| most any district's average moves | 0.0048 | 0.0047 |
| a 0.00 in day: mean, p5 to p95 | 0.065, 0.03 to 0.13 (round 3: 0.046, 0.01 to 0.13) | |
| a 0.00 in day under half its level, at 1%, at the lower bound | 0%, 0%, 87% (round 3: 82%, 6.6%, 47%) | |

G6 at the class levels: advisory mean 0.310 and p99 0.868, advisory and warning mean 0.971, most
5.51; with the adjustment (expected over each district's days and mornings): 0.310 and 0.876, 0.971,
most 5.54 (L5's; with the snow amount term on, below); no district over 6 either way. The check in
`build_model` passes every clause (0 districts held at their class levels for the most).

**Worked examples** (a forecast even through the window, 25 F at 7 AM; each district's served
level and usual snow):

| Forecast snow | 0 | 0.3 in | 1 in | 2 in | 4 in | 6 in | 10 in |
|---|---|---|---|---|---|---|---|
| Atlanta, advisory (level 16%, usual 0.65 in, 0.44 alone) | 9% | 12% | 20% | 29% | 43% | 49% | 49% |
| Buffalo, advisory (level 6%, usual 1.96 in, 1.73 alone) | 3% | 3% | 4% | 6% | 10% | 14% | 21% |
| Atlanta, warning (level 49%, usual 1.62 in, 0.93 alone) | 39% | 39% | 40% | 53% | 67% | 75% | 81% |
| Buffalo, warning (level 38%, usual 5.70 in) | 29% | 29% | 29% | 29% | 31% | 39% | 51% |

(Round 4, with the anchor: Atlanta advisory 9, 13, 19, 29, 42, 49, 49%; Buffalo advisory 3, 3,
4, 6, 10, 14, 21%; Atlanta warning 39, 39, 49, 49, 60, 69, 78%.) A dusting (0.3 in) takes
Atlanta's advisory to 12% and 6 inches nearly quadruples it, held at Atlanta's warning level
(49%) by the class order; Buffalo, where an advisory's inch or two is ordinary, moves from 3%
(its lower bound) to 14% over the same range. Atlanta's warning days are often icy, so its
warning `u` (1.62 in) is over its snow alone's 0.93 in and an inch of snow lowers its warning
day to 40% (the documented limit above; round 4's anchor held it at 49%). Three inches on an
Atlanta advisory day: 40% falling overnight into the commute, 37% spread evenly, 32% after 9
AM; 0.15 in of ice alone 41%; 2 inches at -10 F feels 36% (29% at 25 F). Memphis-Shelby's
warning (level 45%, `u` 3.55 in) from 0 to 8 in: 35, 35, 35, 35, 35, 38, 41, 48, 53, 57, 63% at
0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6 and 8 in.

**October 28** (the 9 PM PDT read of Oct 27, run 03:47Z, 0.00 in still to come at each): Methow
Valley SD went from 93% (the chain) to 7% (L3's class level) to 4% (round 3: 3%), at the
advisory's lower bound, its usual advisory snow 1.01 in (0.96 in alone); Yosemite-Wawona from
74% to 13% to 7%, at the bound too, usual 0.46 in (0.45 alone; Stehekin 7% to 4%, usual 0.78
in). Each says one line: "The 8:47 PM forecast has no new snow by 11 AM, less than usual here."

**The lines.** A moved day says its terms as lines on the class base, split by Shapley values in
whole points that add up to the chance (the base's points plus the lines' is the chance shown):

- `snow_total` with `against: "here"` ("The 8:47 PM forecast has 1 to 3 inches by 10 AM, more
  than usual here."), the range only where every deciding school's forecast is in it and on the
  line's side of the usual snow, "overnight" only of snow every deciding school gets overnight.
  "More" or "less than usual here" holds against both `u` and the usual snow alone `u_a`: a
  forecast between them is lowered (the documented limit above) but never called more or less
  snow than usual (`against: "none"`, the range alone); one under both says less, one over
  both more.
  Where the deciding schools' snow lies on both sides of the usual snow (one school gets 6
  inches, another none), `against: "none"`: the range alone, "The 8:47 PM forecast has 0 to 6
  inches by 10 AM.", never "less snow than usual here" of a district one of whose deciding
  schools gets 6 inches (SF-R4-1).
- `timing` (the heaviest snow by the hour, S6) or `snow_hours` (above).
- `ice`, said with the window's end: "The 8:47 PM forecast has freezing rain leaving 0.2 inches
  of ice by 1 PM." (by 12 PM Central), since the window's ice can fall after the buses.
- `wind_chill`.
- Since Nov 1, 2026 every forecast line says "The forecast has ...", never when its run was
  issued, neither its time nor its day (the owner's ruling, chart-on and its follow-up, below;
  turn-on item 11). The timing lines carry no run of their own and need none.

A term worth no whole point says nothing; a day no term moves by a point is the class level
with no line. The period under way at the snapshot counts for its part still to come at an even
rate through its 6 hours (NDFD gives no finer split): where snow fell early in that period, up
to its share already down is still counted (at most the period under way's part, about 4 of 6
hours in the East at 9 PM; PHYS-S6). The range a line states holds every deciding school's
amount as read, so it is as true as that reading.

**Previous chances.** A storm-class day's chance that moved only because the forecast arrived
(the last file was made before the day's class snapshot) or because this pass's read failed
with no lines of the same snapshot to keep carries no previous chance: "Down from 10%" would
read as the storm weakening. Nor does one at its class level in the last file that this pass's
forecast moves, unless the pass that made that file is known to have read it: the loop keeps
the district-days its last pass read, by that file's time, so a failed read followed by one
that works is never said as "Up from 10%" (S-R2-3); after a restart it is not known, and no
previous chance is said. Between two files from the snapshot on that both read it, the change
is the forecast's (a read that moved it under a point and one that moves it now too) and is
said ("Up from 25% at 9 PM").

**Cost.** Solving `u` (and the usual snow alone) per level with the cold mix adds about 4.7 s CPU
to a model build (9.8 and 9.3 s without, 13.9 and 14.6 s with, on this machine; the class
order's solve adds about 3 s more: 17.5 s under the heavy lock on Nov 1, round 4 17.4 s against
14.4 s side by side); a zone's first forecast read of a night takes about 10 s for one run
(1.3 s CPU) and 22 to 30 s for all five (30.2 s on Nov 1 for Oct 30's runs), later passes of
the same process read nothing new, and each job restart (every 320 minutes) reads them all
again; a file with every district under an advisory and a forecast on day one takes 4.2
s CPU instead of 2.1 s and 10.5 MB raw instead of 7.3 MB, inside the worst case
(`tests/predict/test_loop.py` holds every adjusted day to it).

**Registered.** The numbers are `live_score.forecast_adjustment` (S7 addendum i, 2026-11-01,
revised the same day before any row was scored: `ice_snow`, `timing_even_max`, the timing
phase-in; revision 2, no value changed: the school-by-school timing, the timing band, even
snow's timing in the solve and the snow alone in the words; revision 3: `bounds_advisory`
-0.7, the snow term anchored at the snow alone, the class order and G6 asserted on the
adjusted chances; `LIVE_SCORE_SHA256` f03c3d9a...; the anchor was withdrawn the same day by the
lead's ruling, with no registered value changed);
L4's frozen scorer scores the chance as served. Revised Nov 2, 2026 (predict-next SNOW-AMOUNT,
below): `snow_amount` (false), `snow_amount_high` (3.0) and `snow_amount_floor_ratio` (3.0)
added, no served value changed, `LIVE_SCORE_SHA256` e3903496.... Revised Nov 3, 2026
(predict-next SNOW-AMOUNT-2, below), for rows after it: `snow_amount` true,
`snow_amount_slope_advisory` (1.65) and `snow_amount_slope_warning` (3.0) added,
`LIVE_SCORE_SHA256` a228204e...: each class's slope is its own (not `snow_per_log`'s 1.0), the
total bends toward 3.0 over the upper bounds instead of stopping, and the snow alone's floor
holds (below); the description above is the term off. Revised Nov 3, 2026 (predict-next
BUS-TIMING, below), for rows after it: `timing_bus` true, `timing_after_bus` (0.95) and
`timing_bus_share_max` (0.8) added, `LIVE_SCORE_SHA256` 78861639...: the timing weighs snow
before the bus hour (7 AM) against snow after it in place of 10 PM to 9 AM. Revised Nov 4, 2026
(predict-next TIMING-AUTO, "The live switch" below), for rows after it: `timing_after_bus` 1.0 (no
timing) and `switch_bus_timing` added, `LIVE_SCORE_SHA256` ce2a224e...: the bus term's 0.95 is
the live switch's on arm, served only once it is consistently better on live storm mornings.
Revised Nov 10, 2026 (predict-next ONE-STORM, "The storm-class levels" above):
`live_update.ramp` ("capped_storms"), `ramp_storm_gap` (1) and each class's `ramp_<class>`
added, `LIVE_SCORE_SHA256` 7707b6ec...: the served level and delay share ramp from the start
by the class's rows, storms and market-days, no storm holds more than its registered share,
and `tau` stays registered until the ramp is full; no served value changed: no class row was
in use, so it is for every row there will be.
Turning it off (`serve.forecast_adjust: "off"`) serves the class levels alone, as L3 did, with
no previous chance on a day the forecast had moved.

**Other users of the window.** Since SF-R5-1 the forecast history's live codes count the period
under way for its part still to come. The outlook (S7-F, shadow) and piece 3's reason terms
(off) were fit on codes that counted it whole, so the outlook shadow's private scoring now
compares codes from a slightly shorter window (Pacific 9 PM: about 27% less of an even window)
and the reason terms would read them so too; both are on their turn-on lists to be refit on
codes of the fixed window before either serves (S3). The night chart (off) names its heaviest
hours from the hourly blend, which will rarely equal an NDFD period: a timing line beside it
makes the panel leave the sum out (it fails closed, never false); before the chart turns on,
the timing line must be aligned with the chart's heaviest hours or the check relaxed for the
adjustment's lines (S7, on the chart's turn-on list).

**After it lands** (for the integrator, POSTLAND): deploy the web before the first file with
the adjustment on and confirm the service worker updates (an old client leaves the sum out for
a day with an `against: "here"` or `"none"` line or a `snow_hours` line: never false); on the
first storm nights report the share of advisory and warning district-days with a forecast read,
the share at each class's lower bound (the shift note), the quiet-day window snow (to check
`QUIET`), how ice-heavy districts' snow warnings moved, any pass whose read failed part-way
(its warning line) and the read time of the first pass after each job restart,
the logged mean shift per class, the pass's forecast read time (p50 and most) and an
Oct-28-style spot check; watch CI for the full pytest, desktop and phone e2e and Lighthouse.

## The snow amount term (predict-next SNOW-AMOUNT and SNOW-AMOUNT-2: on)

The owner asked (Nov 2) that the forecast snow amount, against the place's normal, drive the
chance: under L5 a typical warning district stops at 79% from about 15 inches up, so 15 and 30
inches read the same. SNOW-AMOUNT built a term that keeps rising and landed it off, judged by a
rule that could not judge it (below). SNOW-AMOUNT-2 judged it again by a fair test, found it no
worse than L5, and switched it on (`live_score.forecast_adjustment.snow_amount: true`, with
each class's own slope), for rows after Nov 3, 2026.

**Why the first rule was unfair.** It scored the absolute log loss and Brier score of each
arm's chances on the archive's alert days. The archive's dates were picked because there was a
storm (the owner's ruling O6), so most districts on them closed: a model that says a high
chance everywhere scores well there whatever it knows about which districts close, and the
score mixes how high a date's chances run with how well they are spread across its districts.
The term's whole point is the spread (more snow than usual, a higher chance than a district
with less), so a level score could not judge it. The forecast history's codes also stop at "9
inches or more", so the archive cannot show what happens over 9 inches either way.

**The fair test.** A season is held out at a time: each class's slope is fit on the other
seasons only and the held-out season's dates are scored. The score is the conditional
log-likelihood of which districts closed on each date and class, given how many closed (the
conditional logit, exact by the recursion over the date's districts), per district-day. Given
the count, a date's level cancels: adding the same amount to every district's chance on a date
changes nothing (checked: L5 plus 3.0 log-odds everywhere scores exactly L5's), so only the
order and spread within a date count. A date and class where every district closed (or none)
says nothing and scores 0 for both arms. The arms:

- (a) L5 as served before: slope 1.0, the class bounds clipping, `u` and the snow alone's usual
  solved with the term off.
- (b) the term on as built (below), each class's slope fit on the training seasons by the same
  conditional likelihood on a grid of 0.05 from 0.8 to 3.0, `u` and the snow alone's usual
  re-solved with the term on at that slope, `H` 3.0 unless the training seasons prefer 4.0 by
  more than 2 log-likelihood units at its own best slope. The grid starts at 0.8, not 0.5:
  under 0.8 the timing band's lower edge would fall as the snow rises (`(m + c) timing_max <=
  a m`, which `AdjustSettings.of` enforces for every slope). It stops at 3.0: on the archive's
  dates where nearly every district closed a steeper slope keeps scoring a little better
  without bound (the within-date slope's bootstrap upper bounds run to 4 and 5), so past 3.0
  the fit says nothing the record supports. `H` 2.0 is not a choice: it must be over the
  advisory's upper bound, 2.0.

Rows: the archive's labeled district-days joined to the forecast history's 9 PM codes on
advisory and winter storm, lake effect and ice storm warning days, 2018-19 on (1,436
district-days on 24 dates; 609 advisory on 18, 827 warning on 11), each code's amounts as the
climate counts them, the snow even through the window (the history keeps the window's total
alone) and the cold of a cold code's morning. Each district's `u` is solved from the committed
climate at the class's typical level (advisory 0.1158, warning 0.4586), with no class order
cap; the climate counts every season, the held-out one's too, so the normal is not held out
(the same for both arms; a small part of each district's count). 90% bounds are a date-block
bootstrap of the difference (2,000 draws of the held-out dates):

| rows | district-days | dates | date-classes that say something | L5 | term on | on less L5 | 90% bounds |
|---|---|---|---|---|---|---|---|
| all | 1,436 | 24 | 15 | -0.1207 | -0.1194 | +0.0013 | -0.0011 to +0.0035 |
| advisory | 609 | 18 | 8 | -0.1528 | -0.1538 | -0.0010 | -0.0068 to +0.0035 |
| warning | 827 | 11 | 7 | -0.0970 | -0.0940 | +0.0030 | +0.0005 to +0.0080 |

(log-likelihood per district-day, higher is better; a model with no information, every
district alike, scores -0.1261.) Within-date concordance (pairs on the same date and class,
one closed and one not: the share where the closed one had the higher chance, ties half):

| rows | pairs | L5 | term on |
|---|---|---|---|
| all | 4,346 | 0.618 | 0.642 |
| advisory | 2,009 | 0.700 | 0.689 |
| warning | 2,337 | 0.547 | 0.602 |

The slopes fit with each season held out (2018-19, 2020-21 to 2025-26): advisory 2.80, 1.65,
1.65, 2.05, 1.50, 1.55, 1.65; warning 3.0 in every fold but 2022-23's 2.85. On every season
they are 1.65 (advisory) and 3.0 (warning), the registered `snow_amount_slope_advisory` and
`snow_amount_slope_warning`. The warning's slope sits at the top of its range in 6 of 7
folds: the record says only that it is steep. `H` 3.0 and 4.0 score the same on the training
seasons (to the third decimal over every season; 31 held-out days pass a class bound), so `H`
stays 3.0 (SA-R2-S3: the fold's choice of `H` is a tie, not a measurement).

**The decision.** The rule (the lead's, Nov 3): on if the overall difference is 0 or more and
its lower 90% bound is -0.005 or more per district-day, neither class is worse by more than
0.005, and every safety rule below holds. Overall +0.0013 (bounds -0.0011 to +0.0035);
advisory -0.0010, warning +0.0030: it passes, so the term is on.

The test's limits, from the review: it leaves out the class order cap serving applies, which
moves 27 advisory rows; with the cap the result is +0.0012 overall and -0.0012 advisory, so the
decision holds. It scores at the national class levels, not each district's own served level.
The gain is thin and comes mostly from one 2022-23 warning date: without it the overall
difference is +0.0003.

For information only, the old absolute score with each class's intercept fit on the training
seasons: log loss 0.4440 for L5 and 0.4506 for the term on. It cannot decide because the
archive's dates were picked for their storms: most districts on them closed, so the score
rewards whatever runs a date's chances high, and a model that said a high chance everywhere
would beat both arms on it.

**What the record cannot show.** The codes stop at 9 inches or more (bucket 5, 11 inches in
the climate), so no archive day shows the effect of 12, 18 or 30 inches: the bend over the
class bound toward `H` 3.0 is a choice, not a measurement. With the warning's slope of 3.0 a
typical warning day nears the asymptote by about 12 inches (94% from 12 to 30 inches as
published, still rising unrounded); a higher `H` would keep it rising further, and no record
here can say which is right.

**The term** (`forecast_adjust.saturated`, `floor_lift` and `AdjustSettings.for_class`, with
`snow_amount` on):

- Each class has its own slope `a` (`snow_amount_slope_<class>`) in place of `snow_per_log`
  for snow, timing and ice (one log), in the solve and serving alike; the timing band is held
  to `timing_max` either way at every slope.
- The total (snow, timing and ice as one log, with the cold) is never under the snow alone's
  floor `min(0, a ln((W + 0.5) / (b + 0.5)))`, `W` the snow weighed by its hours and `b` the
  usual snow alone (ice days as quiet), but never under `u / 3` and never over `u`
  (`snow_amount_floor_ratio` 3). So snow from what the snow alone makes usual up never lowers
  a day because the place's days of the class are often icy (PHYS-R3-S1 (i)); the floor and
  the total each only rise with snow, so the larger does too. The floor has no cold: the snow
  alone's usual is solved with the ice days' mornings as quiet ones. The anchor at `u / 3` or
  more keeps the solve determinate: anchored at a snow alone's usual near a quiet day's trace,
  a floor held every day of the class at its level or over whatever `u` was, so the solve ran
  to its 30-inch end. With the term on as registered, `u` is under 3 times its snow alone's
  usual for 92.5% of advisory and 97.7% of warning districts (every 4th of the committed
  climate, at the typical levels), so for them the anchor is the snow alone's usual; for the
  rest it is `u / 3`.
- Up to the class's upper bound (+2.0 advisory, +1.5 warning) the total is held as L5 holds it
  (at the class's slope); over it, it bends toward 3.0 instead of stopping, `high + (3.0 -
  high) tanh((T - high) / (3.0 - high))`: slope 1 at the bound, so it is continuous and keeps
  rising, never reaching 3.0. The lower bounds stay hard (-0.7, -0.4: a 9 PM read cannot see
  snow already down, PHYS-R3-S2).
- The solve and serving hold the total in one function (`saturated`, with the class order's
  cap as the most it may be), so each code's total in the solve is the served total for that
  forecast, and each district's days of each class still average its class level as served.
  Serving splits the held total back over the terms (`bounded`); where the class order's cap
  is under 0 and under the lowering terms' sum (or every term is 0), there is no raising term
  to scale, so the lowering terms (or the snow's) take the rest and the sum is still the
  solve's total (SA-R2-S4: no deployed cap is under 0, the least gap being 0.56 log-odds, but
  the guard holds the two equal whatever the levels).
- The chance never falls with more snow. It is level only where the floor holds a day at its
  class level (snow between the floor's anchor and `u`), at the class's lower bound, or near
  the asymptote at whole points.
- The words stay true with no new copy: a lift is the snow term's points, and a snow line
  compares the forecast with both `u` and `u_a`, so a day the floor holds up between them says
  the range alone, never more or less snow than usual. The frozen record keeps the lifted snow
  term in `raw` and the asymptote as `hi` (SA-R2-S5, out of scope here: the bend's start, the
  class's upper bound, is not recorded; it is the registered bound).

**Safety, with the term on as registered** (every district of the committed climate, 13,404, solved
as serving solves it at four mixes of class levels): every advisory, snow warning, lake effect and
ice storm usual is solved (none unsolved, none at the 30-inch end), G6 holds (no check failing; the
first predict run with the term on, 41618702328, logged advisory mean 0.311 p99 0.889, advisory and
warning mean 0.973, most 5.59, 0 districts at their class levels), and over 0 to 30 inches with ice
(0, 0.05, 0.25 in), timing (even, overnight, late) and cold (25 F, -20 F) no chance falls for every
7th district (0 falls). A residual plateau remains (SA-R2-S1): at advisory 30% and warning 85%
levels, 2 of 13,404 districts whose advisory days are almost all traces solve to any usual from 0.09
to 0.27 inches (their chance at 1 inch reads 56 to 67% across that range); at the typical levels and
at 5, 20 and 45% advisory levels none does.

Tests (`tests/predict/test_snow_amount.py`): the block is registered on with its slopes, and
off it is L5 exactly, with and without the class order's cap; a bad block is refused (an
asymptote not over every upper bound, a floor ratio under 1, a slope that is not a number, not
over 0 or too flat for the timing band); on, the chance never falls with more snow over a grid
of usuals (0.3 to 6 in), snow-alone usuals, ice (0 to 0.25 in), timing (even, overnight, late)
and cold, nor with more ice or cold; up to the bound it is L5's shape at the class's slope,
and 18, 24, 30 and 60 inches each read higher, under the asymptote; for every code and cold
morning, usual, snow-alone usual and cap (under 0 too), off and on, the served terms add up to
the solve's total, and over 3,000 random term sets and caps the split terms add up to the held
total with each term keeping its sign; an icy place's snow over its snow alone's usual never
lowers its day; random climates still average their level; every 15th committed-climate
district solves, none at the 30-inch end, and G6 holds; over 1 to 30 inches each solved
district's chance never falls, is level only where the floor holds it or at the lower bound,
and rises strictly from its usual up; through the served path the class order, the direction
and the floor and ceiling hold. `tests/predict/test_forecast_adjust.py` holds L5's own terms
(the term off).

**The owner's table** (a forecast even through the window, no ice, 25 F; each district's usual
and snow-alone usual solved as serving solves them (`serve._usual_snow`), with the term off for
before and on for after; every advisory cell through `serve._order_cap`, as serving holds it;
typical: the district with the median usual of the committed climate at the national levels,
advisory 11.58% and warning 45.86%, for each class, as picked when the term was measured; the bus
hour timing on or off gives every cell the same, since the snow is even):

| place, class | 1 in | 2 in | 4 in | 6 in | 9 in | 12 in | 18 in | 24 in | 30 in |
|---|---|---|---|---|---|---|---|---|---|
| typical warning district, warning (level 46%, usual 3.37 in), before | 36% | 36% | 50% | 59% | 68% | 73% | 79% | 79% | 79% |
| typical warning district, warning (level 46%, usual 3.05 in), after | 36% | 36% | 63% | 84% | 92% | 94% | 94% | 94% | 94% |
| typical advisory district, advisory (level 12%, usual 1.46 in), before | 9% | 14% | 23% | 30% | 39% | 45% | 46% | 46% | 46% |
| typical advisory district, advisory (level 12%, usual 1.80 in), after | 8% | 13% | 28% | 42% | 46% | 46% | 46% | 46% | 46% |
| low usual (Atlanta), warning (level 49%, usual 1.62 in), before | 40% | 53% | 67% | 75% | 81% | 81% | 81% | 81% | 81% |
| low usual (Atlanta), warning (level 49%, usual 2.39 in), after | 39% | 49% | 78% | 91% | 94% | 95% | 95% | 95% | 95% |
| low usual (Atlanta), advisory (level 16%, usual 0.65 in), before | 20% | 29% | 43% | 49% | 49% | 49% | 49% | 49% | 49% |
| low usual (Atlanta), advisory (level 16%, usual 0.87 in), after | 18% | 34% | 49% | 49% | 49% | 49% | 49% | 49% | 49% |
| high usual (Buffalo), warning (level 38%, usual 5.70 in), before | 29% | 29% | 31% | 39% | 48% | 55% | 65% | 71% | 73% |
| high usual (Buffalo), warning (level 38%, usual 6.39 in), after | 29% | 29% | 29% | 34% | 62% | 78% | 89% | 92% | 92% |
| high usual (Buffalo), advisory (level 6%, usual 1.96 in), before | 4% | 6% | 10% | 14% | 20% | 24% | 32% | 32% | 32% |
| high usual (Buffalo), advisory (level 6%, usual 2.21 in), after | 3% | 6% | 13% | 21% | 34% | 38% | 38% | 38% | 38% |

**The class order caps every advisory day.** `serve._order_cap` holds an advisory day at or under
the lowest chance any of the same district's winter warning situations has with the same
forecast, and a blizzard warning is never moved by the forecast, so it keeps the district's
warning level: an advisory day never serves over its district's warning level. Atlanta's
advisory stops at 49%, its warning level, from 6 inches before and from 4 inches after;
Buffalo's at 38% from 12 inches after; the typical advisory district's at 46% from 18 inches
before and from 9 inches after. Without the cap the term on would read Atlanta's advisory 57 to
79% from 4 inches and the typical advisory district's 57 to 72% from 9 inches: serving never
publishes those. Under the cap, the term still moves an advisory day from 1 to about 6 inches
(the typical district 30% at 6 inches before, 42% after).

With the term on, the snow amount moves a warning day much more: a typical warning district
reads 63% at 4 inches and 84% at 6 (L5 50 and 59%). Each usual is solved again so the class's
days still average its level: some rise (Buffalo's warning 5.70 to 6.39 inches, Atlanta's 1.62
to 2.39) and some fall (the typical warning district's 3.37 to 3.05), and amounts under a usual
that rose read a little lower (Buffalo's warning 34% at 6 inches, L5 39%; Atlanta's warning 49% at
2 inches, L5 53%). From about 12 inches a warning day nears the asymptote (above).

## The bus hour timing term (predict-next BUS-TIMING; off since TIMING-AUTO: the live switch's on arm)

**Since Nov 4, 2026 no timing serves** (predict-next TIMING-AUTO, the owner's ruling: no timing
scored best): `timing_after_bus` is 1.0 with `timing_bus` on, so `W = s`, the timing part is 0 and
no period is named. The bus term at `o` 0.95, as measured below, is the live switch's on arm: it
serves again only once it is consistently better than no timing on live storm mornings, and goes
back off when it falls behind ("The live switch" below). Everything below is the term as measured
and as it served from Nov 3 to Nov 4.

The owner asked (Nov 2) that snow down by the time the buses go out raise the chance. L5's
timing (above) was set by hand: snow from 10 PM to 9 AM weighs 1, snow outside it 0.5, held to
0.4 log-odds either way, and no fair test had measured it (every test took each archive day's
snow as even through the window). BUS-TIMING replaces it with a weight measured on past winters
by the bus hour, switched on by the within-date test with each season held out, for rows after
Nov 3, 2026 (`live_score.forecast_adjustment.timing_bus: true`).

**The bus hour.** 7 AM on each district's own clock (`ndfd.bus_time`, the cold term's hour).
No source gives district bus times, first buses run about 6:15 to 7:30, and the forecast's
6-hour periods (each taken even through its hours) cannot resolve finer: half an hour moves a
twelfth of a period. The web's timing words stay free of bus times ("The forecast has the
heaviest snow 12 to 6 AM.", no bus clause), so no line names a bus time the pipeline does not
have.

**The term** (`forecast_adjust.window_even`, `weighed`, `bus_weight` and `_named`, with
`timing_bus` on):

- `snow_bus`: each deciding school's own window snow from the snapshot to 7 AM (each period's
  snow even through it), the district's 50% value taken by the same rule as `s`, never over
  `s`, school by school first, so it only grows with any school's snow in any period.
- `W = (o s + (1 - o) snow_bus) / even_bus`, `even_bus = o + (1 - o) min(f, F)`: `f` the
  window's share before 7 AM by the hour, `F` 0.8 (`timing_bus_share_max`: snow at least 80%
  before the bus hour never lowers), `o` 0.95 (`timing_after_bus`, what snow after the bus hour
  weighs against snow before it). The term is L5's log with this `W`, `a ln((W + 0.5) / (s +
  0.5))`, in L5's band (0.4 either way, phased in to half an inch) and at each class's slope.
- Zero point: even snow gives `snow_bus = f s`, so `W = s` and a timing part of 0 wherever `f <=
  0.8`. At 9 PM `f` is 0.625 in Eastern (0.588 daylight), 0.667 Central, 0.714 Mountain, 0.769
  Pacific (0.714 daylight), 0.833 Alaska (0.769 daylight) and 0.909 Hawaii, and it only falls
  as the snapshot moves later, so every lower-48 zone has no timing part for even snow at every
  snapshot to the bus hour and a solve factor of exactly 1. Only Alaska (standard time) and
  Hawaii cap it: factors 1.0013 and 1.0055 (L5: Pacific 1.0205, Alaska 1.0570, Hawaii 1.0606).
  The factor is solved at 9 PM; in Alaska the cap holds until 11 PM and in Hawaii until 3 AM,
  after which an unchanged even forecast's timing part goes from at most +0.016 log-odds (Hawaii,
  warning slope) to 0 while the usual keeps the 9 PM factor (a bound for the newest-run piece).
- The timing line weighs each period by `o + (1 - o) g`, `g` its share before 7 AM, against
  `even_bus`; a line that raises names only a period more than half before 7 AM, one that
  lowers only a period more than half after it, else its points go with the snow line. At 9 PM
  the split period is 12-18 UTC (Eastern daylight: 06-12 UTC, 5/6 before): Central's (1/6
  before) is never named by a line that raises; Pacific standard (3/6), Alaska standard (4/6)
  and Alaska daylight time's (3/6) are named by neither; Hawaii's (5/6) may be named by a line
  that raises.
- More snow in any period at any school, more ice or more cold, or snow moved before the bus
  hour, never lowers the chance: `W` only rises with `snow_bus` and with `s`, `even_bus` is a
  constant of the window, and the band's edges only rise with `s`.

**What the archive can and cannot show** (a row: a labelled advisory or warning district-day,
2018-19 on, that the replay read; a date-class is informative when it has a closed and an open
row):

- The forecast history's codes hold one bucket of the window total per sample hour, so 0 of
  the 1,436 labelled district-days carry snow before or after the bus hour; the 4 AM code is a
  run 7 hours later, not a split of the 9 PM one. The codes alone cannot show timing.
- The archived NDFD runs can be replayed: the 9 PM read through the live reader on 26
  zone-nights (24 dates), 0 failed, gives each row's `snow_bus`. Rows: 1,436 on 24 dates, 29
  date-classes; 15 informative date-classes (928 rows, 13 dates), with 157 open district-days
  in all, most of them on two date-classes (2023-03-14 and the 2023-02-28 advisory day).
- The hourly blend's archive (NOAA's no-cost `noaa-nbm-grib2-pds` bucket) holds the 1-hour
  snowfall from the 2020-09-29 12 UTC cycle on: 17 of the 24 dates, 1,209 rows, 22
  date-classes and 11 of the 15 informative ones. Read at each zone's 9 PM (the cycle 2 hours
  before, one a 9 PM pass could read: 18 zone-nights, 0 failed), its before-bus share
  correlates 0.933 with the NDFD replay's (mean difference 0.081), its window total 0.913.

**The test** (the snow amount term's within-date test: per date and class, the exact
conditional log-likelihood of which districts closed given how many, per district-day; each
season held out in turn; date-block bootstrap 90% bounds, 2,000 draws; every arm at today's
served settings: snow amount on, slopes 1.65 and 3.0, no class order cap). Arms: (a) L5's
timing as served; (b) the bus term, `o` fit on the training seasons over 0.0 to 0.9 by 0.1 and
0.95 (ties to the largest, the weakest timing, since the record does not show the effect), the
usual re-solved at its factor; (n) no timing (`o` 1.0). The rule: on only if (b - a) is at
least 0 at the point with its lower bound at least -0.005, no class's (b - a) is under -0.005,
and every safety check holds.

- Profile, all seasons (fit grid, then 1.0): 0.0 -169.124, 0.3 -169.769, 0.5 -169.571, 0.8
  -168.400, 0.9 -167.881, 0.95 -167.614, 1.0 -167.356; L5 -169.292. Both classes rise from 0.3
  or 0.4 to 1.0. Every fold's training profile peaks at 0.95 and picks it (the 2022-23 and
  2023-24 seasons carry most of the held-out signal; 2025-26 has no informative date-class).
- (b) less (a): +0.0012 (-0.0000 to +0.0029); advisory +0.0019 (-0.0004 to +0.0058); warning
  +0.0006 (+0.0002 to +0.0010). The rule holds: on at `o` 0.95.
- (n) less (a): +0.0013 (+0.0000 to +0.0033); advisory +0.0022 (-0.0004 to +0.0064); warning
  +0.0007 (+0.0002 to +0.0013). L5 at its hand-set strength measurably lowers the warning
  class's within-date likelihood.
- (n) less (b): +0.0002 (+0.0000 to +0.0004); advisory +0.0002 (-0.0000 to +0.0006); warning
  +0.0001 (+0.0001 to +0.0002).
- Concordance (4,346 pairs): L5 0.645, the bus term 0.672, no timing with L5's usual 0.674
  (it differs from (n) only on 66 Pacific rows, whose usual L5 inflates by 1.0205).
- Size at 0.95, the timing part on the rows: advisory mean +0.003 (sd 0.014, largest 0.042),
  warning -0.020 (sd 0.044, largest 0.091); L5's +0.017 (sd 0.083) and -0.039 (sd 0.175).
- The blend's hours (information only, the 1,209 covered rows: the bus term with `snow_bus` as
  `s` times the blend's before-bus share, the NDFD amount kept): profile 0.0 -142.316, 0.5
  -141.521, 0.95 -141.487; the NDFD-timed 0.5 -143.734, 0.95 -141.658; no timing -141.395; L5
  -143.371. The blend's timing less the NDFD's at 0.5: +0.0018 (-0.0001 to +0.0054); at 0.95
  +0.0001 (-0.0000 to +0.0004); less no timing at 0.5 -0.0001 (-0.0007 to +0.0008).

**The finding.** On this record neither the 9 PM forecast's 6-hour periods nor the blend's hours
rank districts within a storm date by timing: no timing scores best. The rule switches the bus term
on at the weakest timing the fit grid holds, which removes L5's hand-set 10 PM to 9 AM weighting,
whose swings reached the 0.4 band (measurably worse on warning days), and keeps the factor wired,
measured and refittable. The band stays registered and holds the bus term too; only the weighting
changed, and at `o` 0.95 the term's largest value on the archive rows is 0.091 log-odds, so the band
rarely binds. The measured `o` is the grid's top, not an interior optimum; `o` 1.0 (the term 0
everywhere, every factor 1) is the registered way to drop timing, and that is the owner's call, not
the fit's. The owner made it on Nov 3 (TIMING-AUTO): no timing serves from Nov 4, since (n) less
(b) above passes the switching rule, and the bus term switches on by itself only once live storm
mornings show it consistently better ("The live switch"). Serving the blend's hours is a later piece: it must first be calibrated against NDFD
(their amounts differ), its reader splits the CONUS and Alaska files, and on this record it would
not pass against no timing either.

**Safety, with the term on as registered** (every district of the committed climate, 13,404,
solved as serving solves it at four mixes of class levels): G6 holds (no check failing), every
advisory, snow warning, lake effect and ice storm usual is solved within 1e-6 of its level
(none unsolved, none at the 30-inch end); Eastern, Central, Mountain and Arizona usuals are
unchanged from L5's, Pacific's move with its factor (median advisory 0.687 to 0.670 in,
warning 2.642 to 2.603 in); for every 7th district in its own zone, over 0 to 24 inches even
and in each single period, no chance falls (0 falls). The replay's reader `snow_bus` equals the
probe's school-by-school value (to its 4-place rounding) on all 1,436 rows, and the served
path's total equals the test's bus arm (largest difference 4e-16) at every `o`.
On the live host with the term on (predict run 41718729677, Nov 4): `forecast adjustment
plausibility: advisory mean 0.311 p99 0.889, advisory and warning mean 0.973, most 5.59; 0
districts at their class levels for the most`, and the anchor's `advisory mean 0.31 p99 0.87,
advisory and warning mean 0.97, most 5.51; pulled 0, capped 0, shrunk 0`, with 0 product
warnings. They equal the snow amount term's term-on figures, since no snow fell in school hours
that night.
Under no timing (`o` 1.0, TIMING-AUTO) every zone holding a solved district has even factor 1 at
both `o` 0.95 and 1.0, and the solve and G6 see the arm only through that factor, so the usual,
the snow-alone usual and G6 (failing clauses, capped count, summary) are bit-equal under both
arms: a no-timing run logs the same G6 figures as a term-on run on the same directory and anchor.
Measured at the TIMING-AUTO head on every district of the committed climate (13,404, in five
lower-48 zones; four mixes of class levels), as serving solves them: with no timing and with the
on arm alike, G6 holds (no check failing), no advisory, snow warning, lake effect or ice storm
usual is unsolved or at the 30-inch end, the usual is bit-equal between the two arms, and over 0
to 24 inches even and in each single period no chance falls (0 falls, every 7th district in its
own zone).

Tests (`tests/predict/test_bus_timing.py`): `snow_bus` is each school's own, never over `s`, grows
with any school's snow in any period, and is unread where a school is; the 7 AM split of each zone's
period in standard and daylight time; off, every term, bound, line and even factor over a grid of
zones, both times, shapes, ice, cold, usuals, classes and floors is L5's bit for bit (a digest taken
at the head before the change), with any `snow_bus` and bus settings; on, over 1 to 7 schools, six
zones, both times, `o` 0 to 1, usuals, both classes, floors and class order caps, more snow at one
or every school, snow moved before the bus hour, more ice or more cold never lowers; even snow has
no timing part and no timing line in each lower-48 zone at 9 PM and every hourly snapshot to 6 AM,
and even snow at the solved usual reads usual (snow and timing parts 0, no snow or timing line)
through the live reader in each; the even factors by zone; `o` or `F` out of range is refused, `o`
1.0 is accepted and gives no timing; each place's days still average its class level in every zone;
the line's side rule per zone; and through `serve._order_cap`, for the owner's table's districts, an
advisory day never over the warning level or any warning's chance for the same forecast, never
falling with more snow, and Atlanta's at its 49% from 4 inches. `tests/predict/test_frozen.py`: the
record keeps `bb` and rows without it still read.

**The owner's table** (each district's usual solved as serving solves it with L5's timing and
with the bus term; 9 PM read on a January school day, no ice, 25 F; "before": all the snow in
the last period to end by 7 AM local, 1 to 7 AM in Eastern time, midnight to 6 AM in Central; "after":
all of it in the next period, 7 AM to 1 PM Eastern, 6 AM to noon Central (five sixths of it
after 7 AM); each advisory day held by the class order through `serve._order_cap`, as serving
holds it: under every winter warning's chance for the same forecast, where a blizzard warning
keeps the district's warning level; typical: the median usual at the national levels):

| place, class | 4 in before | 4 in even | 4 in after | 8 in before | 8 in even | 8 in after |
|---|---|---|---|---|---|---|
| typical warning district, warning (level 46%, usual 3.94 in), L5 | 57% | 47% | 38% | 89% | 85% | 80% |
| typical warning district, warning, bus term | 48% | 47% | 45% | 86% | 85% | 84% |
| typical warning district, warning, no timing (served since TIMING-AUTO) | 47% | 47% | 47% | 85% | 85% | 85% |
| typical advisory district, advisory (level 12%, usual 1.70 in), L5 | 34% | 30% | 26% | 46% | 46% | 46% |
| typical advisory district, advisory, bus term | 30% | 30% | 29% | 46% | 46% | 46% |
| typical advisory district, advisory, no timing | 30% | 30% | 30% | 46% | 46% | 46% |
| low usual (Atlanta), warning (level 49%, usual 2.39 in), L5 | 84% | 78% | 71% | 94% | 94% | 93% |
| low usual (Atlanta), warning, bus term | 79% | 78% | 77% | 94% | 94% | 93% |
| low usual (Atlanta), warning, no timing | 78% | 78% | 78% | 94% | 94% | 94% |
| low usual (Atlanta), advisory (level 16%, usual 0.87 in), L5 | 49% | 49% | 49% | 49% | 49% | 49% |
| low usual (Atlanta), advisory, bus term | 49% | 49% | 49% | 49% | 49% | 49% |
| low usual (Atlanta), advisory, no timing | 49% | 49% | 49% | 49% | 49% | 49% |
| snow belt (Buffalo), warning (level 38%, usual 6.39 in), L5 | 29% | 29% | 29% | 63% | 53% | 44% |
| snow belt (Buffalo), warning, bus term | 29% | 29% | 29% | 55% | 53% | 51% |
| snow belt (Buffalo), warning, no timing | 29% | 29% | 29% | 53% | 53% | 53% |
| snow belt (Buffalo), advisory (level 6%, usual 2.21 in), L5 | 16% | 13% | 9% | 35% | 30% | 23% |
| snow belt (Buffalo), advisory, bus term | 13% | 13% | 12% | 30% | 30% | 29% |
| snow belt (Buffalo), advisory, no timing | 13% | 13% | 13% | 30% | 30% | 30% |

Even snow reads the same under both (each district here is in Eastern or Central time, factor
1). The class order holds an advisory day at the district's warning level: Atlanta's advisory
reads 49%, its warning level, in every cell, and the typical advisory district 46% at 8
inches, under both, so the bus term cannot move those cells. Elsewhere, snow all before 7 AM
now raises a day 0 to 2 points over even snow (L5: 0 to 10), and snow after it (all of it in
Eastern time, five sixths of it in Central) lowers a day 0 to 2 points (L5: 0 to 9): on this
record the timing is a small tilt, not the large swing L5 gave it. The no-timing rows (TIMING-AUTO,
rebuilt through `serve._order_cap` with the committed settings, not assumed) read every cell at
its even column: where the snow falls no longer moves the chance.

**Limits.** One `o` for both classes (15 informative date-classes cannot fit two); the bus hour is 7
AM everywhere; the archive's dates were picked for storms, so the absolute log loss is not a measure
of the term (only the within-date comparison is). The frozen record keeps `bb` on every freeze; with
`sn` and each period's span (`pp`) it is enough to refit `o` and `F` under this shape and bus hour.
Another bus hour, per-district bus times or hourly timing need each school's snow by period or hour,
which the record does not keep (`pp` holds the district's 50% value per period, and 50% values do
not add across schools): such a change needs a replay of the archived runs, as this measurement did.
On the first passes after the switch, a district-day whose read fails keeps the last file's chance
and lines (the same snapshot's, above), which L5's timing made, and the frozen record stamps it with
the new `LIVE_SCORE_SHA256`, as it did on the snow amount term's switch night: never a false or
stale state (it is the same snapshot's chance), but rows kept across the switch carry L5's timing,
which a refit can leave out.

## The usual call time (predict-next CALL-TIME: off)

The owner asked (Nov 2) for "average call time, with the chance declining once it passes", and
only while the district's lists were read healthily (audit piece 19). CALL-TIME-1 lands the
samples, the estimator, the proof that the lists were read, the decline, its registered test and
two counts lines, with the term **off**: nothing served changes, the golden serve files and the
frozen rows are as before (but the header's `live_score_sha256`, now 6484a3c3...: `call_time`
registered, the term off, no served value changed), and only `predict read-labels` imports
`predict/call_time.py`. The archive cannot time a call (it holds capture times, not map times),
and no storm morning has come since the live read began, so nothing here is fitted yet.

**Samples are map times.** A district's call on school day D is the first local minute of D's
final day timeline at which the map showed it no school for the weather (the labels' share rule:
at least half its eligible schools closed or remote for the weather) on an advisory, warning or
cold day. Before 18:00 the evening before it is *ahead* (no sample); 18:00 to midnight, *evening*
(kept apart, never in u); midnight to 09:30, *morning* (the samples); later, *late*. A day with any
school of the district taken back (relit or not), a likely break or another directory's timeline
gives none. The minute is the wall clock's, also on the days the clocks change.

**The usual call time u.** The median of the district's own morning calls (weight 1 each) and 3
pseudo-samples at its pool's median. The pool is the district's market on D (the registry market
of its tier-A list with the most days of a whole read in the record's 14 days before D; ties: more
captures, then the lowest id, so a dead lowest-id list never picks it) when the market's districts
hold 10 morning calls from 3 districts; else its state on that minimum; else none, and then no
term (never a national u). With 3 own calls the decline starts 15 minutes past u, else 30. u is
worked out again on each run from the final day timelines before D (public, kept for good), with no
store of its own. A call also needs its day's weather class, and that comes from the predict
state's class snapshots, which leave the state after 45 days (the evidence store keeps them, and
the predict job does not read it). So for now u reaches back only about 45 days, not to every
final timeline: a district's own u and its pools forget older storms, and the counts line's u
kinds count only the calls of those days. Keeping each final day's class for good (codes only), so
u grows every storm morning, is left to CALL-TIME-2.

**Proof that the lists were read.** Every tier-A list of the district that the live reader attempts
(it is in the registry) is required. One with no whole read in the record's 45 days is *dark*: it
proves nothing, and by the lead's ruling it is still required, so its districts are never proven
and a reading failure (refused, failed, deferred or never whole) can never lower a chance; the
counts line counts those districts by cause where the host holds the ledger's outcomes (below). A list only the archive knows is not required. Tier B
never proves. At each slot end s, L1's read checks 1 to 3 run on a copy of the rule windowed
[05:00, s) and on D's record cut at s (no read or peer read after s), with condition 4 for the
district; each required list's mark is the end of its latest qualifying slot whose read holds no
unplaced row, and P(s) is the earliest mark (none while any required list has none). P* is P's
running maximum: a failed, refused, deferred, partial, unshown, stale, unhealthy, thin or withheld
read adds no slot, so P* holds. If a required list's mark falls (its latest qualifying slot fails a
peer check of the longer window, `stale_populated` or `voided_empty`, and no later slot
qualifies), D's proof is void: Delta 0, a rise, counted. A row naming the district for D or for
every day (`*`) in D-1's record or in a slot before s ends proof the same way; a row with no
status names its districts `*` `?`, so it does too.

**The decline.** x = 0 before proof; at each slot end s_k from 05:30 to 09:30,
x_k = max(x_{k-1}, min(P*_k - (u + g), x_{k-1} + 30)), held after 09:30; Delta =
ln(m + (1 - m) exp(-x / tau)). (m, tau) come only from the registered domain F: m 0.35 to 0.60 by
0.05, tau 20 to 90 minutes by 5, and Delta(30) at least -0.40, 75 of the 90 points; a point outside F
is refused, never clamped. On F, Delta is never under ln 0.35 = -1.05, and since x grows at most 30
a slot and the curve's steepest 30 minutes are its first, no slot falls more than 0.40. Before any
training date (m, tau) is (0.35, 45), whose first 30 minutes are -0.3802:

| minutes past an own u (grace 15) | 15 | 30 | 45 | 60 | 105 | 165 | floor |
|---|---|---|---|---|---|---|---|
| x | 0 | 15 | 30 | 45 | 90 | 150 | |
| Delta | 0 | -0.20 | -0.38 | -0.53 | -0.83 | -0.99 | -1.05 |
| a 50% chance | 50% | 45% | 41% | 37% | 30% | 27% | 26% |
| an 80% chance | 80% | 77% | 73% | 70% | 64% | 60% | 58% |
| a 20% chance | 20% | 17% | 15% | 13% | 10% | 9% | 8% |

At the corners of F the first 30 minutes are -0.3802 (0.35, 45), -0.1203 (0.60, 90), -0.3721
(0.60, 20) and -0.2037 (0.35, 90). Once on, Delta would be added to the log-odds of the model's own
chance (no reason kinds, or kinds within the forecast adjustment's with the raw chance known: the
cells the frozen record keeps a `pr` for, never `said_open`, a lit status, an override or the
outlook) after L5, `serve._order_cap` and the G6 pull, then the publish floor and ceiling, on D's
morning and unlit districts only, the published delay held at its value without the term. Delta is
0 or below, so the class order and G6 hold.

**What the archive says** (counts only, probes p1 to p6). Own posted stamps: 614 districts with one
day, 123 with two, none with three. The first capture showing a known closing (1,547 days; capture
times, not calls): 172 before 18:00 the evening before, 3 at 00:00 to 04:00, none at 04:00 to 06:00,
281 at 06:00 to 07:30, 1,066 at 07:30 to 09:30, 25 later. A carrying list captured silent before
06:00: 8 of 2,388 known district-days, on one date. **How fast u can qualify** (p6, the morning
first captures of known closings standing in for calls: 1,350 on 31 dates in 909 districts): no
district held 3 in one season (1,062 held one, 144 two), and 115 districts reach 3 over 10 seasons;
of the 18 archive markets with any, 12 held 10 calls from 3 districts on their first such date (26
of 39 date-market pairs lit 10 or more). So a market's pool can qualify on its first storm morning,
while a district's own u takes about three closings: the first season is pool-driven.

**Switching on (CALL-TIME-2).** The switch will be automatic, as the owner asked for the bus hour
timing term: the shared live switch ("The live switch" below), which runs at the end of `predict
read-labels` (not in the learn step: L1's labels it judges by are restored after `predict learn`),
on only when the registered rule below holds on live mornings, with several passing evaluations in
a row, and back off if it later fails, each switch logged with its numbers. CALL-TIME-2 plugs in
its own block (`live_score.switch_call_time`: `arm_block` call_time, `arm_key` serve, the arms
the names `off` and `on`, no `frozen_key`, so it freezes no variant) and its code in
`live_switch.TERMS`: a group builder, its extra checks and its config checks. The group builder
reads D's frozen rows, D's labels, the config and L1's record folder, from which it reads only
D's inputs cut at each time (the folder holds every date's labels too, so the term's own code
keeps it from reading a label there, and its review checks that). It fits (m, tau) only on the
dates before D, from its own likelihood sums over F's 75 points kept once in each earlier
date's entry (in one of its groups, not in every one: in all 30 groups a date the state grows
by about 5.2 MB a winter, once a date by about 0.7 MB, on synthetic dates of its shape), handed
it as the ledger (those dates' frozen rows are released once counted), and their labels
through the switch's reader, which refuses D and every later date. In the switch every date is
judged once, from fits on earlier dates only (earlier seasons and the season's own earlier
dates), and is never judged again: the held-out season of the rule below is the archive test's,
not the switch's. Its extra checks
(its stratum lower bounds, its dropped-closing check, its calibration interval, its own supply of
200 at-risk district-times with Delta < 0, the LIVE-READS-landed gate) see every group it built,
informative or not (a band where every district at risk stayed open is part of the calibration),
and read its registered numbers from `live_score.call_time`, which they are handed with the
rule. Its rule maps onto the switch's: `on_lower` -0.005 with `tolerance` 0.005 (its lower bound
at least -0.005 holds as over -0.005, and its gain at least 0 as over 0: they differ only on an
exact tie, which goes to off), no `new_date_min` (it has no clause on the new date), its 8 dates
and 3 states as the switch's supply, `supply.date_classes` and `supply.rows` 1 and
`max_date_share` 1.0 (its 200 rows are its own check), and `class_min` rows 1 and date_classes
1, so every class with a row binds and its clause (2), no class under -0.005, holds for each
(the bus term's 100 rows over 3 date-classes would let a small class under it pass).
CALL-TIME-2's review measures its state's size and replay time on a winter of its shape. Its arm reaches
its per-pass decline through `live_switch.served_value` (the run's served arms, on each pass),
since its value is read outside the anchor, which alone is built from the served config. The
ledger, evaluation, truth table, replay, state and lines are the switch's, unchanged; a test
plugs in a term of that shape (name arms, strata, sums, a fitted arm, an extra check over every
group with a registered number) and checks the frozen record and serving with it. Until
LIVE-READS lands (the per-pass proof from
the live reader, with a test that it equals `call_time.proof` on the same record cut),
`live_score.call_time.serve` is `off` and config refuses any other value. The rule, registered now
with every number (`live_score.call_time`, under `LIVE_SCORE_SHA256` and its test): rows are each
live date with an advisory, warning or cold class, every 30 minutes from 05:30 to 09:30 and at
10:00 (the held value); at risk are the class's districts in L1's read set with a served frozen row
(`s` 1, `pr` known, no `sa`; `d0_0507` before 06:30, `d0_0630` from 06:30), not lit no school and
not named by then; L1's labels score them (unknown dropped, counted). OFF and ON share the frozen
base; the score is the within-date conditional log-likelihood of which districts closed given how
many, with a 2,000-resample date-block bootstrap and 90% bounds, in bands [05:30, 06:30), [06:30,
07:30), [07:30, 08:30), [08:30, 09:30] and 10:00. (m, tau) maximise the training rows' likelihood
over F: with one live season, the dates before D; from two, each season held out, with no call of
it in a fitted value. It needs 8 dates, 3 states and 200 at-risk district-times with Delta under 0,
and turns on only with: the overall gain at least 0 and its lower bound at least -0.005 a
district-time; no class under -0.005 and no stratum of 100 or more such rows with a lower bound
under -0.005; at least -0.005 with every dropped row a closing; the observed closings on Delta < 0
rows, pooled and per class, within the 90% interval of ON's expected count and no further from it
than OFF's; every safety check; and LIVE-READS landed.

**The counts line.** After each run's summary, `predict read-labels` logs one counts-only line per
day it added, `call time (off) <day>:` calls by kind and lit after a reader gap (the lighting list
had no whole read in the hour before); the read districts of a class day by the kind of their u
(own, market, state, none); the districts named `*` in D's or D-1's record, and of them read; at
07:30, those at risk, named by then and dropped later; the districts proven by 06:30, 07:30, 08:30
and 09:30; voided; and the unproven by cause (no required list, dark lists, a required list with
no qualifying slot, named). At risk at 07:30 counts only districts with a served `d0_0630` row (the
rule's freeze from 06:30), so one with only a `d0_0507` row is not served. A district with dark
lists counts once, under every cause they show joined by `+` (`dark refused+failed`). The cause
is the ledger's last outcome of each dark list, and the predict job reads the live state's export,
whose ledger is schema only (no rows, no outcomes), so there every dark district counts as `dark
(cause not on this host)`, never as one cause guessed; the causes show where the full ledger is
read (the box, a dry run). Counting them by cause in the predict job needs codes-only outcomes in
the export, a privacy decision for the lead. Only the timelines of final days whose class
snapshot the state holds with a district of an advisory, warning or cold class are read from the
host, each once a run. The line stops 80 s after the step began: the workflow sets
`READ_LABELS_STARTED` (`date +%s`) before `uv run`, and every limit of the step (the live switch's
45/55/65 s, this line's) counts from it, the time `uv` takes to start included (else from the
module's import). The clock is checked before each day, each timeline read, the morning record's
parse and each district, so no host read or new day starts past 80 s and a stalled read (20 s a
phase) ends by 100 s, inside the step's 2 minutes; then one `skipped past 80 s` line is printed
instead. Only that limit is a skip (a private signal): any other timeout, a socket's or a
library's, is the one warning any error is: it never changes a label, the audit, `added` or the
exit. F itself is held to the registered block: a settings object whose grids, first-slot bound
or step differ from `config/predict.yaml`'s is refused, however it was made. Beside each counts
line, `call time digests <day>:` gives the live parity population's size (every district of a
term's class at D's snapshot whose R is not empty), a context digest and the proof digests at
06:30, 07:30, 08:30 and 09:30 local (below).

**The live proof (LIVE-READS: shadow).** A serving pass could not tell which lists were read this
morning: the predict job held the live record only as the export, written at the end of each
320-minute live-read run. Now the live reader ships each changed morning day file at every :00
and :30 UTC mark to two private tables of its state database (`docs/live.md`, "The state"), and
after each serving pass (published or dark, so the reads never hold a file back) the view
(`predict/live_reads.py`) reads them with SELECTs only:

- s is the latest :00 or :30 UTC mark at or before now less 15 minutes (the version shipped in
  that mark's idle time holds the slot before s). One request reads D's and D-1's heads; a new
  version brings its parts (16 a request), checked (count, sha256, gzip, the day file), and every
  district's proof is made from scratch by `call_time.proofs_for`, the one implementation the
  counts line uses, so a view and `call_time.proof` on the same record cut agree by construction
  (the parity tests drive SYNTHETIC mornings pass by pass through the live record and its
  shipper and find zero differences at every slot end). Each district takes the proof at its
  latest local slot end at or before s (the 10:00 row held).
- The context, once a run per class morning: read-labels' own proof inputs
  (`read_cli.proof_inputs`: the list stats, the lists read with no second list, the record's
  whole reads, D-1's `*` namings) from the export, L1's coverage, the registry, the directory
  and the run's class snapshots, with day timelines from the live host's Pages copy (no API call).
  Nothing of it is read before it is needed: `make_pass` only wires the view (any failure there
  is one warning and no view, the passes run as before), and the registry, the coverage and the
  export (unpacked into a scratch folder, removed at the run's end) are read once a run, when
  the first class morning's context is built. A day with no district of a term's class at its
  snapshot is asked again at the next mark, and nothing is unpacked or read for it. A class
  morning whose export gives no context (no live state, `none (no live state)`, or an empty
  population, `none (no population)`: its districts have no covered list) is built once and is
  a final no that run, counted among the summary's builds.
- The build is bounded: it runs on a worker thread the view joins after 90 s (past that: no
  context that run, coded `none (TimeoutError)`, and the pass goes on), its own bound (a later
  build never moves it) is asked between its phases and before each Pages read, and each Pages
  read has 10 s (connect 5 s), so a stalled read ends the build by 100 s at the latest. A
  build that fails (a damaged archive, a registry that does not read, any error, a
  `SystemExit` on its thread included) is coded `none (<type>)` and not tried again that run;
  it never raises into a pass. At the run's end a build still running is told to stop (its
  next check raises) and waited for 5 s before the scratch folder goes; one still running
  after that removes the folder itself when it ends, so nothing it writes outlives the run. Measured on a SYNTHETIC 45-day export with a storm day in
  five (this 4-CPU machine, under the heavy lock, timelines not read): 2,000 districts and 500
  lists (16.2 MB raw), p50 12.4 s, p99 14.2 s over 7 builds; 4,000 and 1,000 (28.1 MB), p50
  24.6 s, p99 25.9 s over 5. Each Pages read of a storm day's timeline adds its latency, which
  is not measurable here. The unpack inside it: 2.2 MB gzip p50 0.21 s, p99 0.22 s; 4.1 MB p50
  0.36 s, p99 0.37 s. The build holds the pass after which it runs by that long, once a run.
- No proof is the safe side, coded, one line a run per code: `none` (no class morning or
  context, with the reason or the error's type), `missing` (no head of D, or no D-1 record
  shipped or exported), `stale` (`through` before s, or no slot before s: the reader did not
  run; or `stale (d-1 not final)`, below), `unreadable` (parts missing or failing their checks,
  after the previous version's, which a reader racing the shipper's delete reads; D-1's head
  too, when it is the newer D-1),
  `mismatched` (another day, schema or directory, or `through` more than 2 minutes ahead of
  now), `d1` (no answer; 5 s a request, or no secrets) and `late` (past 10 s a pass, counted
  from after the context). A view never raises. A version read from the head's previous parts
  is kept under its own sha256, never the head's: its line names that version and its
  `through`, and the next pass asks for the head's parts again.
- One line per new (version, s): `live reads (off) <day> <s>Z: version <12 hex> (through
  <HH:MM>Z), <n> districts: proven, unproven, named, void, before first slot, history changed;
  context <12 hex>`, then the proof digest at each of 06:30, 07:30, 08:30 and 09:30 local once s
  has passed it in every zone. `history changed` counts the districts whose proof at a slot end
  the line before had already reached differs in this version (a slot rewritten after shipping).
  The context digest covers every input of a proof but D's record: the population with each R,
  the lists read with no second list, the districts D-1 named for D (with the kinds) and for every
  day, the lists' counted captures, and L1's station stats (each source's populated reads, median
  rows and placed share, which L1's stale rule reads). A digest equal to read-labels' says the
  view saw what the final record shows; a different one with an equal context digest names a slot
  changed after shipping; a different context digest names the inputs (read-labels' station
  stats span the whole folder, days after D included, and its D-1 is the export's). The run ends
  with `live reads (off): <views> views, <lines> lines; no proof <code> <count>, ...; history
  changed <n>; slowest <s> s; context <s, each build> s`.
- D-1's rules (the districts D-1's record named for D, and for every day) are one implementation,
  `live_labels.named_for` and `live_labels.named_every_day`, which the learning step's source,
  read-labels' proof inputs, the counts line and the view all call. D-1's record is chosen by
  its `through`: the shipped head when it is at least as new as the export's D-1, else the
  export's. D-1's evening namings (its `named` rows are kept after 21:00 UTC, its reads are
  not) reach the channel only through the final ship after 00:00 UTC, so a D-1 proves only
  when a record known final stands behind the choice: the head's own version shipped after
  00:00 UTC of D, or an export that records a pass of D (its run went past midnight). Else
  every pass is `stale (d-1 not final)`. A shipped head at least as new as the export's that
  does not read gives its own code (`unreadable`, `d1`, `late`), never the older export. The
  parity tests cover D-1 naming D, D-1 naming every day (both end proof as `named`), a shipped
  D-1 other than the export's (the newer is read), a shipped 21:00Z D-1 against a final export
  that names D (`named`; with an export not final either, no proof), a newer shipped D-1 that
  does not read (`unreadable`), and no D-1 at all (`missing`).
- Shadow only: `serve.live_reads: true` sits outside `live_score` (its sha256 is unchanged); the
  view reaches no served value and no frozen key (a test runs the frozen passes with a view of
  proofs and finds every public and frozen byte equal), and `call_time.serve` stays off only.
- Measured on SYNTHETIC mornings (in-memory D1, this 4-CPU machine, under the heavy lock): a new
  version's view, 2,000 districts and 500 lists, p50 2.10 s, p99 2.48 s over 7; 4,000 and 1,000,
  p50 6.21 s, p99 6.82 s over 5 (almost all of it `call_time.proven`, as in read-labels); the
  same version at a later pass, p50 0.023 s, p99 0.036 s (2,000) and p50 0.072 s, p99 0.103 s
  (4,000). A view past 10 s is `late`, never a lowered chance. Up to 25 versions a day reach a
  run.
- Read-labels' digest line shares the counts line's record cuts and is printed after it, so a
  limit reached in the digest's proofs loses only the digest line. Its added proofs, measured as
  above: p50 0.34 s, p99 0.71 s (2,000 districts) and p50 0.79 s, p99 0.86 s (4,000), against
  p50 2.09 s and 5.56 s with a second set of cuts.
- Rare edge cases. **A shipment dies mid-write**: its parts went first, so the head still names
  the last whole version and the view reads that one (`stale` once s passes its `through`). **A
  reader races the shipper's delete**: it reads the previous version's parts, else one
  `unreadable`. **A restart**: the successor pulls the record of the last push (up to 30 minutes
  behind the head, more once the push is hourly), its shipments are refused until its `through`
  reaches the head's, the view codes the head `stale` once s passes it, and P holds over the gap;
  slots the successor writes again count in `history changed`. The successor's record can lack
  the slots the head held after the last push (up to 30 minutes, an hour once the push is
  hourly), and the proof recomputed on it can hold where a lost slot had ended it; that is
  counted in `history changed`, and read-labels sees the same record. **D-1's age**: a shipped
  D-1 that is not final (its 21:00Z version, the final ship after midnight lost to a D1 outage
  or failed pushes) gives way to a newer export's D-1, and with no final record behind either
  every pass is `stale (d-1 not final)`; a newer shipped D-1 that does not read is `unreadable`,
  never the older export; an export's D-1 cut before D-1's evening ended (its run ended before
  midnight) is not final. **Two passes race**: one loop runs
  at a time (the job's concurrency), and an old epoch's head write is refused. **A clock goes
  back**: a pass writes into a shipped slot, the next version recomputes every proof from scratch
  and the changed districts count in `history changed` (CALL-TIME-2 caps the served x step); a
  clock forward makes `through` ahead, `mismatched`. **A deploy mid-morning**: predict's next run
  rebuilds the context and every proof (the context digest moves); a record schema the running
  reader cannot parse is `mismatched` or `unreadable` until predict deploys. **The required set
  changes mid-morning**: R is fixed per run (its registry and coverage); the next run rebuilds it,
  and a list that joins has no mark until it qualifies, so proof ends early (a rise), never late.
  **A damaged export**: any decoding error (a broken gzip stream raises `zlib.error`, which is no
  `OSError`) is a `StateError` at the unpack and `none` at the view.
- POSTLAND: the first live-read run logs `morning shipped:` at each mark (its real D1 latency:
  p50/p99 from those lines), `read causes:` at its export with counts only, and no `ALERT state
  push failed` on a mark where a ship ran; the first class morning's serving lines show versions,
  no `unreadable` or `mismatched`, `stale` under 5% of passes, digests equal to read-labels' or a
  named cause, and the summary line gives the slowest view and each context build's time.

**Limits.** The term never fixes the standing cold rows (the live lane's; `docs/live.md`, "What
`unknown_start` counts"). Their cost to the samples is a late or missing call, never an early one
(the map cannot show a call before a read of a list holding it): a closing posted on a list read
cold lights only from another list or not at all, and one lit after a reader gap lights late, so
u errs late and the decline starts later, the safe side; the counts line counts calls lit after a
gap. Their districts are never proven (a `*` naming ends proof). The gate needs D's morning
record, which the cache keeps 45 days, while a call needs only the public timeline and its day's
class, so a call is never gated by its day's reads.

**After it lands** (POSTLAND): the first live-read run's export logs the census (the standing
against the re-cold rows), and the first `predict read-labels` after a class day logs the counts
line.

## The live switch (predict-next TIMING-AUTO: the bus term registered, served off)

The owner (Nov 3): serve no timing "until the bus one gets consistantly better in which case it
autoswitches on". The live switch (`pipeline/snowlight/predict/live_switch.py`) turns a registered
live-measured term on by itself only when it is consistently better on live storm mornings, back
off when it falls behind, and logs every evaluation and every switch with its numbers. The bus term
is its first term; CALL-TIME-2 plugs in later with its own block and code ("Switching on
(CALL-TIME-2)" above), not a change to the switch.

- **The registry.** One `live_score` block per term, `switch_<name>`, under `LIVE_SCORE_SHA256`:
  `switch_bus_timing` names its two arms (`arm_off` 1.0, no timing; `arm_on` 0.95, the bus term),
  the value they set (`forecast_adjustment.timing_after_bus`), the default arm (`off`, which the
  committed config must hold), its frozen variant (`bt` at `d0_0507`), its classes (advisory,
  warning) and every number of the rule below. Config refuses a committed value that is not the
  default arm's, `timing_bus` false while the block exists, an unknown arm or term, any number
  out of range, and a default of `on` (the truth table's ties, its evidence and its new-date
  clause all go toward off, so it is written for a term off by default). A term with no clause
  on the new date leaves `new_date_min` out. An arm is a name or a number, compared as stored
  (both arms and the committed value of one kind). `live_switch.TERMS` maps a name to its code:
  its group builder, its extra checks (handed the config, the rule and the ledger), its config
  checks and, for a term like the bus term, its shadow (the forecast
  adjustment's settings under each arm, whose chances each row carries as `v.<frozen_key>`; a
  term with no shadow takes no `frozen_key` and its rows carry no variant). Every frozen header
  names every term's served arm and key.
- **Arms only.** The state names `off` or `on`, never a value. Each run reads it once
  (`make_pass`, so the passes, the outlook and `predict learn` alike) and builds only the serving
  anchor from a copy of the config with the arm's registered value in it; the committed config,
  and so every frozen header's and `predict learn`'s `live_score` sha256, is the registered one
  whichever arm serves. The headers record which arm served (`switch`).
- **The key.** A term's state is made over its term sha256 (its switch block and its scope blocks,
  here `forecast_adjustment`) and the committed model artifact's sha256. A deploy that changes
  either restarts the term: an empty ledger, counting from the newest labeled date, the default
  arm, one line. Rows frozen under another key never count.
- **Rows.** Per L1-labeled date D and class, the served `d0_0507` rows with `v.bt` under the term's
  key that L1 labeled (`no_school` closed; `unnamed` or `delayed` open; tier A or B), where L1's
  class of the day is the row's. `v.bt` is the model's own chance under each arm at the `d0_0507`
  freeze, chosen and valued without any outcome (lit and said-open rows included; a freeze past
  by over 90 minutes is written missed); neither arm is fitted on live data, and the class levels
  both share were fitted on labels through D-1 at most, so nothing a date is judged by saw its
  outcome. A term with a fitted arm fits only on the dates before D: their labels through the
  switch's reader (it refuses D and every later date) and its own sums of them in the ledger
  (their frozen rows are released once counted). A term is also handed L1's record folder, for
  D's inputs cut at a time; that folder holds D's labels too, so this part of the guard is the
  term's own code, which never reads a label there, and its review checks it. The bus term
  reads neither.
- **Score.** Per arm, the exact conditional log-likelihood of which districts closed given how
  many (the snow amount term's within-date test), summed per group; per district-day, the sum over
  the rows. A group is informative with some closed and some open, moved where the arms' frozen
  values differ on a row. Only informative groups are scored and counted as evidence; a term's
  own checks see every group it built. Concordance (closed over open pairs, ties half) is
  reported only.
- **The ledger.** Every labeled date with a group enters once, in date order, with every group
  its term built (one where every district stayed open, or every one closed, included), and is
  frozen once counted (`through` advances over dates with none too). An evaluation is made once
  per ledger date holding a moved informative group, on the ledger through that date and over its
  informative groups: P the overall on less off a district-day; L and U the 5th and 95th
  percentiles of 2,000 date-block resamples (a block per date with an informative group) from
  numpy's `default_rng(23)`, so the same ledger always gives the same numbers; each class's own
  (a class binds once it holds 100 rows over 3 moved date-classes); N the new date's own. A
  date-class is a distinct date and class, however many strata a term splits it into.
- **Evidence** (switching on only): 8 moved dates, 10 moved date-classes, 3 states, 300 rows, no
  date over 40% of the rows.
- **The truth table** (ties go to the default, which is off for every term; N only where the
  term registers `new_date_min`):

  | served | verdict | when | then |
  |---|---|---|---|
  | off | confident | evidence, P > 0, L > 0, L >= -0.005, every binding class >= -0.005, N > 0, no failing extra | ON streak + 1; at 3: on, both streaks 0 |
  | off | not confident | anything else (each failing clause named) | ON streak 0 |
  | on | clear | P < -0.005, L < -0.010, or a binding class < -0.010 | off at once, both streaks 0 |
  | on | holding | not clear, and P > 0, L >= -0.005, every binding class >= -0.005, no failing extra | OFF streak 0 |
  | on | behind | anything else | OFF streak + 1; at 2: off, both streaks 0 |

- **What it means.** On the archive no timing beat the bus term within date, so the switch starts
  off. On synthetic winters drawn from the archive's informative dates (26 a winter): when the two
  are truly equal it turns on in about 1 winter in 14 (6.9%), and then serving it costs nothing on
  average, and it goes back off after a median 8 dates; when no timing is truly better, as on the
  archive, it never turned on in 1,000 winters; when the bus term is better by the archive's
  margin, it turns on in 92.8% of winters, at a median 12 moved dates. The live record supplies
  about 25 informative dates a winter, so the evidence is met between mid December and early
  February, and a quiet November cannot flip it: it adds no informative date.
- **The replay.** The served arm, both streaks and the evaluations are always the replay of the
  ledger with the committed rule (`switches` is the term's history, kept over restarts and
  exclusions; it is never served or said). A date later added to `learn.excluded_days`, or
  one a pair of `learn.excluded_rows` names (the ledger keeps sums per date and no district,
  so one row cannot be taken out of a counted date: the date is dropped whole), is
  dropped and the rest replayed in the next `predict read-labels`, as if it had never been
  counted; its line names the list (`excluded (learn.excluded_rows)`, or both lists for days
  of both kinds), and the switch never counts that date again, even if the pair is later
  removed (for a term with a fitted arm, the later dates keep the fits made with it, so the
  remedy that removes it fully is a restart: a revision bump); serving takes the default while
  the ledger holds it, and, with a warning, whenever the stored arm, a streak or an evaluation is
  not the replay (a hand edit, a bug, a numpy change in the draws), so the serving line never
  says a number the ledger does not give, and whenever `through` is after the run's UTC date
  (it only ever advances to a labeled date). The next step writes the replay, and repairs such a
  `through` to its ledger's last date (the dates after it are counted again, each entering the
  ledger once) or, with an empty ledger, to the newest labeled date; a ledger holding a date
  after the run's date is restarted over. Neither is counted past, and the frozen marker never
  passes the run's date. The step replays the stored ledger once and goes on from it over the
  dates it counts (the same numbers to the bit); serving replays it once a run. A replay costs
  about the square of the moved dates: 0.9 s of CPU at 250 (about 8 bus winters), and a test
  bounds it.
- **Where and when.** At the end of `predict read-labels`, after its audit and summary and before
  the call time counts lines, since the switch decides what that run's passes serve (the next
  read-labels is about 5.5 hours later). The step's process first builds its model (about 20 s;
  it reads no switch state and says no serving line, since it serves nothing) and labels the new
  days (7 s on Nov 2's labeled run), so the switch starts only before 45 s of the step. It starts
  no new date past 55 s, nor one that the longest date of the run so far would take past 55 s (it
  writes the dates it counted, `through` advancing only that far, and the next run counts the
  rest, so a backlog is never retried whole). It writes only before 65 s, unless a date it counted
  ran past 55 s: that write goes through with every date counted, so a slow date never stops a
  backlog. A host write and its read-back take a few seconds, at most about 20 s for the write
  and each read (a read-back that meets a lagging copy, or follows a write that failed, reads
  again after 2, 4 and 8 s: up to 14 s more), so the step's 2-minute limit can cut off only a
  worst-case or late one. That is safe: the write is one
  commit and the frozen marker is rewritten only after a read-back, so the days are kept (the
  lines of a write cut off after its commit are lost, since no counted date is evaluated again;
  a date that ran past 55 s is said at once, before the write, so a step cut off still says
  it).
  A storm date costs about 4 s to count (its frozen day 2.5 s, its groups 1.6 s); a quiet run
  needs under a second. The state is
  `predictions/switch.json` on the live host beside `learn.json`: counts, sums and state FIPS
  codes, no LEAIDs; written by a compare and swap (`guarded_write`: refused unless the host's
  bytes are the ones this run read, in the same commit on GitHub) and read back: at once, then
  again after 2, 4 and 8 s while the host gives other bytes (GitHub's API can answer with the
  file it held before the commit for a second or two). A write whose answer is lost (a timeout
  after the commit) is read back the same way: the lines are said as written where a read gives
  the new bytes, `nothing written` where the last gives the old, and otherwise the outcome is
  unknown, nothing is said as written and the marker stays. The passes read it in a
  new process soon after; one behind the frozen marker (a host replica that has not caught up)
  is read once more, and one still behind is served as read with a warning. After each
  read-back the frozen folder's marker (`frozen/switch.json`, `through`) is rewritten, and the
  folder keeps each finished day until the switch counted it ("The frozen record").
- **Lines** (counts and numbers only). Each run, per term: `predict read-labels: switch
  bus_timing (served off): through 2026-11-05; 0 of 8 moved dates, 0 of 10 date-classes, 0 of 3
  states, 0 of 300 rows; ON streak 0 of 3; 1 new labeled date (0 informative, 0 moved, 0 with no
  frozen rows)`. Each evaluation: `switch bus_timing: 2027-01-12 evaluation 9 (served off): 9 moved
  dates, 12 date-classes, 4 states, 412 rows, largest date 31%; on - off +0.0004 a district-day
  (90% +0.0001 to +0.0008); advisory +0.0006 (130 rows), warning +0.0002 (282 rows); this date
  +0.0011; concordance on 0.671 off 0.668; confident, ON streak 2 of 3` (an unbound class reads
  `(62 rows, not binding)`; a verdict names each clause that failed, `not confident: short of
  evidence (7 of 8 moved dates), this date at or under 0; ON streak 0 of 3`). Each switch:
  `SWITCHED on after 3 confident evaluations (...): timing_after_bus 0.95 serves from this run's
  passes`, `SWITCHED off: behind 2 in a row (...)`, `SWITCHED off at once: clear (lower bound
  -0.0121)` or `SWITCHED off: <date> excluded (learn.excluded_days); the ledger without it ends
  off`. An exclusion that leaves the arm as it was: `switch bus_timing: 2027-01-14 excluded
  (learn.excluded_days): dropped from the ledger; served off, ON streak 2 to 1` (or `ON streak 2
  unchanged`). The counts line ends, where dates were not counted, `; 3 labeled dates waiting
  for the frozen day of 2027-01-11`, `; 4 labeled dates from 2027-01-12 left for the next run
  (past 55 s)` or `; 2 labeled dates held at 2027-01-12, which does not read`. These lines are
  said only once the state they report is written; where it is not, each ends `(not written)`
  and a switch line says `would serve (not written)`. So are the two warnings of what a write
  will do: `::warning::... the stored arm, streaks or evaluations are not the replay of its
  ledger: the replay's (off, 9 evaluations) is written` (where no exclusion explains it),
  `::warning::... through 2030-01-01 is after the run's date: repaired to 2027-01-12 (its
  ledger's last date)` (or `(the newest labeled date)`, or `..., and so is its ledger's
  2030-01-01: restarted over it`) and `::warning::... switch.json does not read (<TypeName>):
  every term restarted over it`, which read `would be written (not written)`, `would repair to
  ... (not written)` and `would restart over it (not written)` when nothing is. Said at once:
  `::warning::... switch bus_timing: through 2027-01-14 is after L1's newest labeled date,
  2027-01-12` and `switch bus_timing: 2027-01-12 ran to 78 s of the step, past 55 s: kept`. Also `switch: skipped past
  45 s of the step`, `switch: skipped past 65 s of the step: nothing written`, `switch: a date
  counted ran to 78 s, past 55 s: written through every date counted`, `switch: wrote
  predictions/switch.json (5,812 B), read back` (or, written but not read back, a warning
  `wrote ... read back failed (<TypeName>)`; written and read back as other bytes on every
  read, `wrote ... but it did not read back as written (4 reads, none the blob 1a2b3c4d5e6f
  sent: HTTP 200 blob 9f8e7d6c5b4a, HTTP 304 blob 9f8e7d6c5b4a, ...)`; a lost answer read
  back as written, `::warning::... the write's answer was lost: predictions/switch.json
  (5,812 B) read back as written`; one not,
  `::warning::... <TypeName>: the write's outcome is unknown (the host holds other bytes):
  nothing is said as written and the frozen days are kept`), `::warning::... switch.json is
  2,104,000 B, over 2,000,000 B`, `switch bus_timing: started (no state; term sha
  1a2b3c4d, model sha 9f8e7d6c)` on the first run, `switch bus_timing: restarted (term sha
  1a2b3c4d to term sha 5e6f7a8b)` and
  `::warning::predict read-labels: switch: <TypeName>: nothing written`. Serving (every pass
  run and `predict learn`): `predict: switch: bus_timing served off (switch.json through
  2026-11-05, 0 evaluations)` or `... served off, the committed default (<why>)`, and for a state
  behind the frozen marker after a second read `::warning::switch: predictions/switch.json is
  behind the step's read-back (through 2027-01-12, the frozen marker 2027-01-14): served as
  read`. The freeze:
  the `d0_0507` `predict frozen:` line ends `, bt on 6,410 rows` or `, bt none (even factors
  differ by arm)`.
- **Edge cases.** A restart mid-step changes nothing on the host before its one-commit write; a
  kill after it leaves a valid state and an unwritten marker, so days are kept, and the next run
  rewrites the marker from the host. Two writers: the second's compare and swap is refused, it
  writes nothing, and the next run re-reads. A counted date whose L1 file changed (L1 never
  relabels) keeps its counted numbers and warns once for each new file; the remedy for a wrong
  day is `learn.excluded_days`. A labeled date whose frozen day the folder neither holds nor lists
  as released waits up to 7 days for the evidence step's restore (with every later date, counted
  in the line), then is passed as absent; the folder keeps a finished day 9 days, so the days
  after it are still there when it passes. A failed or refused host write changes nothing, its
  lines say `(not written)`, and the next run evaluates the same dates to the same numbers; one
  whose answer is lost is read back, as above. A host
  state that does not read serves the default in every run until it is mended, and the next
  `predict read-labels` restarts every term over it (one warning; the old bytes stay in the
  host's history); one of a later schema is never written over. An L1 file of a date that does
  not read stops the count before that date in every run, with a warning, while the dates before
  it are written: the remedy is to add the date to `learn.excluded_days`. A frozen day that does
  not read does the same until the folder releases it (9 days), when it passes as absent. A date
  taken out of `learn.excluded_days` after `through` passed it is never counted, and the counts
  line does not name it: the ledger takes dates once, in order. A group a term builds that is not
  counts and short names (a state that is not a two-digit FIPS code, a stratum or count or sum
  key that is not a short name, a run of five digits) stops the count before its date with a
  warning, and a failing clause that is not short plain text writes nothing, so no LEAID or list
  text reaches the state or a line.
- **Limits.** Every run reads, parses and replays the state, which no run prunes under one key:
  the bus term's is about 0.05 MB a winter with its evaluations (0.18 MB after 4), and a state
  over 2,000,000 B is written with a warning, so a term that keeps more a date says how it
  stays under it (or restarts each winter). The synthetic winters resample only the archive's
  13 informative dates, so the rates are indicative; the supply figure models archive-audience districts read at Nov 2's share. The
  N clause and `on_lower` 0 are stricter than a floor at -0.005 alone: with the floor alone,
  truly equal arms would switch on in 36% of winters, since the bus term moves only about 0.0003 a
  district-day, far inside 0.005.

Tests (`tests/predict/test_switch.py`): the registry and each refusal; the key; the served config
changes one value and the committed sha stays; the exact likelihood equals brute force; every
cell of the truth table (each clause failing alone, ties, an unbound class, 3 confident, holding
with L under 0, each behind and clear clause); a 3-date backlog is 3 evaluations, no new date
writes nothing, the replay is the live sequence; an ON reached on a day later excluded replays off
with a switch line, a robust ON stays on, serving takes the default meanwhile; a sha or model
change restarts; a relabel said once a file; failed, refused and racing writes (their lines `not
written`), a read-back that fails after a write, an unreadable state restarted over and a later
schema left alone; a hand-edited arm, a state that overflows or nests too deep and a replay that
fails all serve the default; the 45 s, 55 s and 65 s limits, a backlog counted over two runs,
slow dates of 14 s counted 3 a run with every run written, a date past both limits (and a run's
first) still written, a late write with no slow date refused, and a date that does not read; a
waiting date in the line; the keep window against the wait; a second term with name arms, no
shadow, strata, sums, a fitted arm that cannot read D's labels through the reader and an extra
check plugs in beside the bus term (served config, `served_value`, serving, the frozen headers
and shadows, and `tests/predict/test_frozen.py` freezes no variant for it); a term's check sees
every group it built and its registered number (a band where none closed turns its verdict) and
a date with only such a band enters the ledger with no evaluation; a stratified ledger counts as
the same unstratified one; an exclusion that moves only a streak, or nothing, says so with no
warning, and a fault warning waits for the write; a group or clause with a LEAID or list text is
refused; a rule with no new-date clause, and a default of on refused; a `through` after the
run's date served as the default and repaired by the step (to the ledger's last date, to the
newest labeled date, or restarted over a ledger date after it), with the marker never past the
run's date and a date L1 labeled after it never counted; hand-cut, dropped or edited
evaluations served as the default and rewritten; a lost write's answer read back as written,
as other bytes and as a failed read; a state behind the frozen marker read once more and,
still behind, served with a warning; the step's replay going on from the stored one (one
evaluation a new date, the same to the bit) and a 250-date ledger replayed under 8 s of CPU; a
slow date said at once and a large state warned of; every line; and read-labels' labels,
audit, `added` and exit are the same with the switch on or off.

**After it lands** (POSTLAND): the first predict run logs `switch: bus_timing served off`, the
plausibility line at `o` 1.0 and the `d0_0507` `bt on` counts; the first read-labels logs the
`started (no state; ...)` line, the counts line (`0 of 8 moved dates`), `wrote
predictions/switch.json (... B), read back`, `frozen/switch.json` written, and its step wall time;
on the first labeled storm day, how long after the step began the switch started (no `skipped
past 45 s` line) and the step's wall time, under 100 s; the first heavy-storm `d0_0507` freeze's
`predict frozen: recorded in ... s`.

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
  The 12:09Z pass of 2026-10-25 had 3,146 thin district-days and 15,560 thin private
  school-days (Monday, all calm): the marker showed on all of them before this rule and shows
  on none. A dry pass over the October 22 advisories (`tests/predict/fixtures`, no heights
  read) has 6,292 thin district-days over its two days; the marker shows on the 4 under an
  advisory.
- **Advisory rates stayed the archive's recorded days** (before L3; with `serve.anchor` on,
  every advisory, warning and cold day is served from its class level, see "The storm-class
  levels"; this is what `serve.anchor: false` serves). Under an advisory alone every district
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
  apart from the districts', per fold like theirs: `labels-private-before-YYYY-07-01.parquet`):
  storm-row Brier 0.0711 against B0's 0.0771 on 169 storm rows (B0 here is the national rate
  per class over the private school-days of earlier seasons), all rows 0.0468 against 0.0508:
  pooled G1 passes (earlier rule: 0.0802 against 0.0820 on 251 storm rows, all rows 0.0594
  against 0.0609). G2 and G3 pass (closings caught at 50% or more 100% against B0's 100%,
  precision 0.923 each). No season holds 300 storm rows, so G1 by season is reported only. The
  report ends with Pembroke Hill's and Visitation Catholic's named days, each predicted
  walk-forward on its own season's fold labels (one of Pembroke Hill's 13 named days,
  2025-02-18, has a morning read: no school, predicted 94% [95%]; the 2023-24 days that were
  87% [87%] have no chance under the per-fold rule, since that fold's private labels hold no
  day of their situation). On the 169 storm rows both rules score, the earlier rule scored
  0.0731 against its B0's 0.0791.
- Learning: `predict learn` re-anchors the districts' rates on days read live; it does not
  yet label private schools from live reads. Until it does (the first follow-up), the
  private chain's sentences count the archive's recorded days only, never days read live.
  A private school on the districts' rates around it carries their live flag, so its
  sentence says "days we read live" only when those district rates were counted on them.
- Launch gate (addendum d), with `serve.anchor` off only: the private storm levels are the
  archive's selection-biased recorded days (an advisory 91%, nation, 226 of 248; 99% in a state or county holding 73 of
  74 or 57 of 57), worded truly as recorded days. Until the private learn follow-up
  re-anchors them on days read live, as `predict learn` does the districts', they block the
  public launch the same way the districts' unlearned levels would. With `serve.anchor` on
  (L3) a private school's storm-class day takes the class level at its county's exposure, with
  no private offset (advisory 0.127 mean, 0.05 to 0.21; "The storm-class levels").
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
  (`snow_total.at`, `ice.at`, `wind_chill.at`). Since Nov 1, 2026 the web never says when it
  was issued, neither its time nor its day: every line is "The forecast has ..." (the owner's
  ruling, chart-on: "don't say which forecast time you got it from ... but you don't wanna say
  that it's hella outdated", so the follow-up dropped the "Last night's forecast" and weekday
  words the first pass gave). A run's `at` still picks the line's form (null keeps the shorter
  approved forms) and its window's end ("by 1 PM"). In the panel, the area view and the
  outlook's line alike (the outlook's "the weather service's 9:46 PM forecast has ... between
  then and 12 PM Tuesday" is now "the forecast has ... by 12 PM Tuesday", or "... between 6 PM
  Monday and 12 PM Tuesday" for a run issued before the window opens). The examples elsewhere
  on this page keep the time each round wrote. The fields stay in the file for older clients.
  The night chart's gates (150 min in the pipeline, 195 on the phone) keep a stale cycle off the
  chart; these lines have no age gate at the reader's clock and no day word: they are given only
  from the day's class snapshot (the 9 PM run before the school day), so the run they read is at
  most about 15 hours old when the panel shows it, and the owner chose not to word its age. The
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
  archive holds at most 2 such days for any district (614 districts one, 123 two), so no district
  has one, `terms.json.gz` holds none, and it is not shown (`serve.announces` false, riding only
  with `serve.reasons`, off). The usual call time ("The usual call time" above) takes its place
  for the chance: it reads the map's own times from the live day timelines, not posted stamps,
  and pools a district with its market or state until it has 3 calls of its own.

Backtest v2 on the labels of 2026-10-25 (internal report; storm district-days of the test
seasons 2019-20 to 2025-26; 2019-20 has no storm rows), under the per-fold rule (each row's base
and each fold's terms fit on labels built only from the seasons before; `--labels-rule whole`
gives the earlier rule's report):

- The gate passes on the archive: storm Brier 0.06122 with the base alone, 0.05814 with the
  terms (5.0% better; the gate asks 2% better), 0.062 to 0.059 without 2020-21 (5.0% better). G2
  holds and every sign holds. Only 2023-24 has the 300 storm rows piece 1's rule gates (0.03015
  to 0.02427, better); no reported season is worse (2022-23: 225 rows, 0.234 either way). This is
  not evidence for turning the reasons on. The report-only checks find the gain is raised chances
  on alert days (P9: 253 storm rows raised, 9 lowered), which counts as no evidence until live
  labels, and it rests on two training dates (P8, the dates picked from the rows the per-fold
  candidate's own fold fits move: with 2016-02-16 left out of every fit the base and the terms
  both score 0.102, with 2023-03-14 left out both 0.124, against 0.061 and 0.058 with every
  date). The committed terms file is unchanged and still records the gate as the earlier rule
  judged it (failed, -6.3%, `labels_rule` whole), and `serve.reasons` stays off in the config,
  so nothing serves the terms. The served terms fit keeps the earlier rule's bases, so `predict
  terms` writes a terms file only under that rule (`--labels-rule whole`; any other run must be
  `--report-only`, `terms_cli.terms_write_refusal`) and records the rule in the gate: a gate
  judged per fold never stands for the served fit. Whether the served fit and its gate move to
  the per-fold rule is the lead's call.
- Under the earlier rule (the whole archive's labels in every fold) the gate failed: 0.10898 to
  0.11580 (6.3% worse), 0.117 to 0.125 without 2020-21 (6.7% worse); 2023-24 0.08494 to 0.08350;
  2022-23 worse (0.393 to 0.440). What drove it: in 2022-23 the advisory snow term fit on the
  seasons before it (penalty 0.3, from almost only 2018-19's forecast rows) added 2.91 log odds at
  4 to 6 inches; 47 advisory test rows there, 36% of them closed, went from a mean 77% to 94%
  (Brier 0.401 to 0.627), more than the whole pooled loss. Under the per-fold rule the 2022-23
  fold's labels hold none of those rows' forecast levels and its snow term is 0 there.
- The penalty grid: the inner loop picks an end of it in 2 of 6 folds (0.3 in 2022-23 and
  2023-24; under the earlier rule 5 of 7, 0.3 in 2019-20 to 2022-23 and 1000 in 2023-24). A grid
  widened to 0.03 and 10,000 picked its ends again and scored worse under the earlier rule (7.2%),
  so it was not kept: with one or two seasons holding forecast levels the inner loop has too
  little to choose from.

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
  exists. The step at 6 in or more rests on 1 row. Walk-forward, 146 advisory test rows were
  moved by the snow term (Brier 0.031 to 0.008) and none by the ice term; all advisory rows
  0.102 to 0.093 (earlier rule: 43 rows 0.443 to 0.690, worse, 71 by the ice term 0.091 to
  0.079, all advisory rows 0.275 to 0.301).
- The ice term adds 3.43 log odds at 0.10 inch of ice or more: a 74% advisory base becomes 99%
  (80% of districts hit the ceiling). It is fit on storm-picked labels (addendum f) and swings
  across folds (0 in 2020-21 to 2023-24, then 2.31 in 2024-25 and 2025-26 under the per-fold
  rule; 5.27 in 2019-20 to 2022-23, 0.08, 4.34, 3.43 under the earlier rule). The owner should see
  it before turn-on.

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
   already holds. (The forecast adjustment of advisory-sane L5 takes the first: it adjusts and
   reads a day only from its class snapshot on.)
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
    next school day's snapshot, or name the day ("Sunday night", "by 12 PM Monday"). (The
    forecast adjustment takes the first: no line before the day's class snapshot.)
11. The morning panel names last night's run without its day ("The 8:46 PM forecast" at 6
    AM), and the chance stays at the 9 PM forecast while a newer run may differ (by design,
    item 5). The owner may want "Last night's 8:46 PM forecast" when the run's date is before
    the viewer's day. (Done for every forecast line with L5: a run from the evening before is
    "Last night's", one from earlier that day "Yesterday's", an older one by its weekday; an
    ice line also says the window's end, "by 1 PM". Since chart-on, Nov 1, 2026, the owner's
    ruling: neither the time nor the day; every line is "The forecast has ...".)

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
         - name: Keep the learning files off the site
           run: rm -rf v1*/predictions/learn*.json v1*/predictions/outlook
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

   The learning step's files (`predictions/learn.json`, `learned.json`, and the outlook's
   `predictions/outlook/`: its private record, cases, learned T and internal report) sit
   beside `latest.json` in the hosting repository. Their contents are public-safe (model
   chances, NOAA-derived states and counts, never list text), but they are not for the site:
   the step "Keep the learning files off the site" leaves them out of what Pages serves, so
   the S7-F chances recorded in shadow are not fetchable from the site before `on`. The passes
   and the learning step read them through the GitHub contents API, never from Pages, so
   leaving them out changes nothing they read. They remain readable wherever the hosting
   repository itself is readable (its visibility is the owner's); the lead confirms this with
   the owner before the first shadow night.

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
- **The watch.** `predict blank` keeps the 5-minute watch quiet: it reads the hold and reports
  nothing while it is set. Disabling the workflow alone does not: with no hold the watch
  reports the file stale, with a comment each hour (see "Staying on air").
- Deleting the secret or setting `PREDICT_PUBLISH` to `off` takes effect only at the next
  run (up to 320 minutes later): use the hold to stop now.

## Commands

Run from `pipeline/`. Exit codes: 0 done, 3 dark (the gate refused or the host failed: nothing
is confirmed as uploaded, and the file can be up only after a read-back that did not confirm it,
cause 6 below, or a write whose answer was lost after the commit), 1 an error.

| Command | What it does |
|---|---|
| `uv run snowlight predict labels` | The weather history (IEM season files) and the labels (archived closing lists, matched and read once) to `out/internal/predict/` (internal: never committed). Heavy: run it under the heavy lock. |
| `uv run snowlight predict train` | Fit the strengths on every labeled season and write the committed model, `data/predict/model.json.gz` (derived counts by LEAID only). |
| `uv run snowlight predict backtest` | The walk-forward backtest and its gates to `out/internal/predict/backtest/` (internal). |
| `uv run snowlight predict once` | One serving pass. `--site-data DIR` reads a local `meta.json` and `points.bin` instead of the deployed site; `--write FILE` keeps a copy; `--host dir --host-dir DIR` publishes to a folder. |
| `uv run snowlight predict run --until +320m` | A pass on every :07 and :37 (the loop sleeps to the grid minute, so passes do not drift), and between them, checked every 5 minutes, a pass when the alerts differ from the ones the last good pass used or when the last pass went dark (at most one extra pass per 10 minutes). Uploads when the file differs, and on every grid pass as the heartbeat unless an upload went out under 4 minutes before: the public file is normally under 35 minutes old. The state is saved after every pass; an unexpected error counts as one dark pass and the loop goes on. It says at its start which commit it is on, prints one line for each pass as it ends, and may end early for a newer branch head after 3 dark passes newer code may cure (see "Staying on air"). |
| `uv run snowlight predict blank` | Sets the hold and uploads a valid file with no districts to `v1/` and `v1-shadow/`: every chance disappears and stays off until `predict release`. |
| `uv run snowlight predict release` | Clears the hold. |
| `uv run snowlight predict check --max-age 45m` | The watchdog: exit 3 when the public file is missing, invalid, blank, ahead of the clock or older than the limit. The workflow runs it after every run, a failed pass included, and opens one issue, "Snow-day chances are stale", unless one is already open. The watch every 5 minutes (`chances-watch.yml`) shares that issue and closes it when a fresh file is served (see "Staying on air"). |
| `uv run snowlight predict exposure --work out/internal/predict` | Builds `data/predict/exposure.json.gz` (each district's storm-class days a winter, county medians, national references, the archive's region tallies) from the labels folder (see "The storm-class levels"). Codes and counts only. |
| `uv run snowlight predict learn` | Labels the live-read days not yet labeled and swaps in a refit only when the held-out live days find it no worse (see "The model learns on its own"). Exit 0 swapped, reset (a served file counted an excluded day) or nothing to change, 4 kept the model served because the refit was worse, 1 an error: before or in its write (nothing written that the step knows of), or after it, when a file written did not read back as written or its read failed (the file went up; see "Swap or keep"). The workflow runs it before the passes. |
| `uv run snowlight predict read-labels` | Labels the live school mornings not yet labeled by the outcome-blind read rule into the private record `out/internal/predict/reads/` and publishes `predictions/read-audit.json` (counts only) when a day is added (see "The read labels"). Exit 0, or 1 on an error (nothing more is labeled). The workflow runs it right after `predict learn` (it continues on error, 2-minute limit); it labels nothing while a coverage file is absent. |
| `uv run snowlight predict read-sources` | Builds `data/predict/read-sources.json.gz` (county FIPS to the lists proven for it, every list's populated archive captures, and the row counts of its closing-size days, one value a day) and `data/predict/audiences.json.gz` (each list's districts listed in the current or previous season as of `--as-of`, default today, no dates; it logs the pairs dropped) from `out/internal/stations/coverage.json`, a match of the whole archive and the archive's weather classes (`out/internal/predict/weather.parquet`; heavy lock). Codes and counts only. |
| `uv run snowlight predict evidence` | Keeps every finished weather-class snapshot of the pass state, the district table of the directory predict learn read and the labels it published (`learn.json`, every version) for good in the evidence databases (docs/live.md, "The evidence"); it reads the table and labels learn left in `out/internal/predict/evidence/`, and the deployed directory only when learn left none (and the pass state keeps no table). Exit 0 when both kept them, 1 otherwise. Then it asks both databases which snapshots and tables they hold and notes it in the pass state (`evidence`). The workflow runs it after the passes and before the state's save, never before the first pass (it continues on error: 30 seconds of writes, 45 seconds for the push's requests, 15 for the question, a 2-minute limit). With `--check` it reads only the pass state: one line, and exit 1 with an `::error::` line when a finished snapshot or its district table has waited 2 days for a copy in both databases (the workflow's issue). |
| `uv run snowlight predict drill [--size [--full]] [--json FILE] [--against FILE]` | The storm drill: one scripted storm through the real loop and pass on a faked clock, publishing to a host in its own memory (serves nothing, reads no secret, writes only its temporary folder and `--json`), and its table of what the panel would show at six moments, its ten risk-row verdicts and its run line. `--size` adds the storm-size night's 37% worst-case world (the CI gate), `--full` the calibration world and every share in both mixes; `--against FILE` lists every cell and verdict that moved (see "The storm drill"). Exit 0 when the story ran, whatever its verdicts say, 3 when a pass of the 37% worst-case world went dark or is not whole, 1 an error. |

Environment: `PREDICT_PUBLISH` (`on` writes `v1/`, `shadow` writes `v1-shadow/`, `off`
writes nothing and is the default; the workflow sets `on`), `LIVE_HOST_TOKEN` (the
workflow passes `SNOWLIGHT_LIVE_TOKEN`), `GITHUB_TOKEN` (reads the site's deployments for
the directory handshake), `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (the chance and
evening notifications after each pass whose file is the public one, docs/notify.md; without
them no notification is sent, and a notification problem only warns; the workflow gives them
to the `predict run` step only).

## When a pass stays dark

A pass publishes nothing, and the page hides the old file within 90 minutes, when one of these
holds (6 is the exception: see there):

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
6. no read-back after the upload gives the file sent. The host is read at once, then again
   after 2, 4 and 8 s while it gives other bytes, since GitHub's API can answer for the branch
   with the file it held before the commit for a second or two (run 205 met it 9 times, each
   file in fact deployed and served); a copy that answers 304 to the written file's ETag is
   confirmed at once. Unlike every other cause, this one comes after the commit: the file went
   up but was not confirmed, and it may well be live. The pass's state does not record the
   upload, and its chance notifications wait for the next one. The dark line says each read's
   HTTP status and the blob sha of the bytes it gave, and the blob sent: `predict: dark
   (read_back: v1/predictions/latest.json written, not confirmed (4 reads, none the blob
   1a2b3c4d5e6f sent: HTTP 200 blob 9f8e7d6c5b4a, HTTP 304 blob 9f8e7d6c5b4a, ...))`. A
   read-back that fails (a host error) is the same dark, and no read is tried after it:
   `predict: dark (read_back: v1/predictions/latest.json written, not confirmed (read failed:
   read v1/predictions/latest.json: HTTP 502 (server)))`;
7. yesterday's day timeline cannot be read (a host error or a file that does not validate);
8. the alert memory does not reach back to 18:00 the evening before the first day
   published, and cannot be rebuilt: after a lost or stale state (the feed unread for more
   than 20 minutes) the pass reads every class-making alert product issued since 48 hours
   before that from `api.weather.gov/alerts`, as the live feed would have shown them, and
   only then publishes. With `serve.memory_checks` on, a failed history read is a warning,
   not a dark pass, when the 5-minute checks kept the memory whole: each check within 20
   minutes of the last read or check found the feed fresh and holding nothing the memory had
   not taken, every read since the memory was last rebuilt from the history (each check's,
   and each pass's own) held nothing it had not taken or exactly what the pass of that same
   check (for a pass's own read, that pass) took in, and the last check was within 20 minutes
   of the pass (see "The 5-minute checks and the history" below);
9. the hold is set (`predict blank`).

A dark pass leaves the alerts it saw unhandled, so the loop tries again at its next
5-minute check. A warning the weather service cancels or upgrades (a `CAN` or `UPG`
product) leaves the memory for the zones it names at once, so the why never names a
withdrawn warning (the training snapshot counts the first product's window whatever came
after: the one place the live path is stricter).

There is never a "no alerts, so 1%" fallback: a pass with fewer inputs publishes nothing.

## Staying on air (predict-next ON-AIR)

On Monday evening, Nov 9 2026, the chances vanished from the page for about two and a half
hours. One of our own updates made the closings reader write a new key in its files, the
running chance job refused every file with a key it did not know, and nothing told anyone for
more than three hours. This section is what keeps that from happening again. It changes no
chance and no rule about when a pass may publish: the list above stands as it is.

### The files the chance job reads from our other chains

Six files, written by two other chains:

- from the closings reader: `live/closings.json`, `live/opens.json`, the day timelines
  (`live/days/<day>.json`) and their index (`live/days/index.json`);
- from the deployed site: `schools/edition.json` and `schools/meta.json`, with `points.bin`.

**The reader's four files are read tolerantly, in the chance job only**
(`snowlight/predict/host_files.py`). A file is read strictly first, exactly as before, and a
file that reads that way gives the same object and the same published bytes. Only when every
problem is a key this code does not know are those keys dropped and the rest read again, just
as strictly. An unknown status or detail code, another `schema_version`, a missing or
repeated key, or a file that breaks one of its own rules is refused as before, and the pass
goes dark with the same line as before. A reason code is the one exception: every reader takes
any whole code from 0 to 255 ("Stated causes read as dark", below). Each drop is said once per run:

```
predict: v1/live/closings.json: 3 unknown keys dropped (in (top), days[], directory); the rest validates
```

The line gives counts and our own field names. The name of the unknown key is never printed.
The chance notifier reads the closings file the same way, so a new key cannot hide a status
the site already shows; a closings file it still cannot read counts as no file, as before,
and its line now ends `; the closings file did not read (<error type>): no shown status is
known`. Everything else stays strict: the writers, the published models, the web, and the
closings reader's own reads.

**The deployed site's files are read exactly, never tolerantly.** The directory handshake
reads them "exactly or not at all" by design, and the site build and the closings reader
share it.

### Stated causes read as dark (ALL-CLOSINGS lane T)

The closings file, the day timelines and the change log may hold a status whose reason code
is not one `Reason` names (0-7: the weather and a power outage): a stated cause that is not the
weather (ALL-CLOSINGS, a later piece), or a code a newer or a reverted pipeline wrote. No such
code is written today. Every reader takes it (`ReasonCode` in `schemas/live.py`, any whole
number up to 255; the site shows no words for it), and the rule for the prediction is one
sentence: **everything that teaches or serves the prediction reads a status whose reason is not
0-7 exactly as it read the dark that status replaces.** On files whose codes are all 0-7 each
loader gives what the raw read gives, so nothing published or served changes.

The rule lives in one place per input, so a new reader of that input gets it for free:

- `as_dark` (`schemas/live.py`): a day timeline. Each such change becomes a taken-back change,
  and each school's run is collapsed again by the timeline's own rules; a school with no
  change left drops out, and a day with none left is an empty timeline.
- `as_dark_closings` (`schemas/live.py`): the closings file. Each such row is left out, and a
  day left with none.
- `as_dark_changes` (`live/history.py`): the change log, one day at a time. Each such line is
  read as the status taken back and the school-day's lines are derived again (`lit`,
  `changed`, `dark`); a `dark`, `expired` or hold line where nothing was shown is dropped.
- `history.timeline`'s emergency-stop rule stops at such a status: it is read as dark at its
  own minute and what came before stays, so the timeline of a stop read through `as_dark` is
  the base's.

They live in `schemas/` and `live/`, never in `predict/`, so the season counts can share them
without importing the prediction. They wrap the prediction's loaders only
(`snowlight/predict/dark_reads.py`); `host_files.closings` and `host_files.timeline` stay the
raw tolerant readers, and the notifier reads every status raw (a followed school's status
pushes whatever its reason). The call sites (lines at the lane T commit):

| Input | Loader | Call site | What reads it |
|---|---|---|---|
| closings file | `dark_reads.closings` | `predict/cli.py` 2490 `_neighbors` | the neighbors term (`nowcast.neighbors_posted`, its `posted_any` too) |
| closings file | `dark_reads.closings` | `predict/cli.py` 2692 `_said_open` | said open (`opens.said_open`) |
| day timeline | `dark_reads.timeline` | `predict/cli.py` 2653 `_closed_on` | the day after (`serve.closed_districts`, `closed_private`) |
| day timeline | `dark_reads.timeline` | `predict/live_labels.py` 546 `StateSource.timeline` | live labels (`lit_of`, `label_live_day`), the read rule (`live_read`), call times (`read_cli` -> `call_time.called_minutes`) |
| change log | `dark_reads.DarkChanges` | `predict/live_labels.py` 567 `StateSource.morning` | the live audience (`audience_of`) and the stop (`held_on`) |
| change log | `dark_reads.DarkChanges` | `predict/live_read.py` 2345 `StateReadSource._log` | `lit_sources`, `audience_before` |
| closings file | `host_files.closings` (raw) | `predict/cli.py` 3378 `_make_notifier`; `notify/cli.py` | status and chance notifications |

`DarkChanges.days()` leaves out a day all of whose lines were such statuses, as the base holds
no log for it. The readers that turn a code into a weather reason (`lit_of`,
`call_time._runs`, `nowcast._canceled`) do it through `named_reason`, which refuses a code not
read as dark: a loader that skipped `as_dark` fails loudly rather than teach from it. Tests:
`tests/live/test_reason_codes.py` (the base sequences, the stop, and the revert test: codes 13
and 99 in a change log, a day timeline and a closings file read on this code) and
`tests/predict/test_dark_reads.py` (every loader above, each with a mutation check: read raw,
the result differs, except the day after, which counts weather reasons only).

### The rule for changing one of these files

Read this before changing the shape of any of the six.

1. **A new key in one of the reader's four files that changes no existing key's meaning: one
   commit.** The key keeps the file's `schema_version` and has a default in its model, and the
   same commit stores the file's new form (see the stored forms below; the test fails until it
   does). Chance code that is still running drops the key; new chance code reads an older file
   as "none". It is safe whichever chain restarts first.
2. **Anything else on the reader's side: two commits, the chance job first.** That is a key
   removed or renamed, a key with no default, a new code in an existing field, a changed type,
   meaning, unit or order, or a new `schema_version`.
   - Commit 1 teaches the file's function in `host_files.py` to read both the old and the new
     form, and stores the coming form as `tests/predict/host_files/next/<file>`. The writer is
     unchanged.
   - Commit 2 is the writer's change. It moves that stored file, byte for byte, to its dated
     folder. If the bytes must change, commit 1 taught the wrong form: begin again.
   - Push commit 2 only after a `predict` run has printed `predict run: on <commit 1 or
     later>`. That is at most 320 minutes after commit 1, or at once after cancelling the run
     (the timer starts the next within 5 minutes).
   - Reverts: commit 2 may be reverted at any time. Commit 1 may be reverted only after the
     reader's chain has restarted on a commit that no longer writes the new form.
3. **What skipping step 2 costs, by which chain restarts first.** Both chains run 320 minutes
   and restart on their own; a push does not restart a running reader.
   - The writer first: chance code that is still running refuses the new files, goes dark,
     and ends its run early for the branch head (below). About 24 minutes with no new file.
   - The chance job first, with code that reads only the new form: it refuses the old writer's
     files until the reader's chain restarts, up to 320 minutes, and **the early end does not
     cure it**, because the run is already on the branch head. The stored forms stop this
     order in CI.
4. **The deployed site's files.** The same two commits: first the model accepts the key, with
   a default, while the build does not write it (for `edition.json`, which the build writes
   from the model itself, commit 1 must also keep the key out of what is written); then, once
   a `predict` run is on that commit, the build writes it.
   - The site's deploy first (a new key in `edition.json` or `meta.json`, a new form of
     `points.bin`): a running chance job refuses it until the early end restarts it, about 24
     minutes after the deploy. The directory is read before the alerts are taken into the
     memory, so no dark pass of that stretch counted the feed as read, and the successor's
     first pass must read the alert history once; each failed read adds 10 minutes, unless
     the 5-minute checks kept the memory whole (the alerts did not change during the stretch).
   - The chance job first, on code that needs what the deployed files do not hold yet: refused
     on every pass and **not cured by a restart**, until the site's deploy lands, or for good
     if that deploy fails. The stored forms stop this order in CI too.
   - The closings reader has its own rules for a changed directory (docs/live.md, "When the
     deployed directory changes").
5. **On a storm night** (from the first watch to the day after): none of steps 2 to 4 in one
   step.

**The stored forms** (`tests/predict/host_files/<form>/`, read by
`tests/predict/test_host_files.py`) hold these files as our chains have written them. A form
is a folder named by the date of the commit that first wrote it (a letter after the date for a
second one on a day), holding only the files whose form changed then; `next/` holds a form no
writer writes yet. Two checks, both kept for good:

- every stored file of every folder still reads through the chance job's own functions, with
  no "unknown keys dropped" warning (a key this code no longer reads is removed by name in the
  file's function, never dropped unseen);
- the newest dated form of each file is, byte for byte, what today's writer writes for the
  content read from it, with every part filled.

So a commit that changes what a writer writes fails until it stores the new form beside the
old ones, and a commit whose chance code can no longer read a stored form fails too. A stored
form is removed only by a commit that says why no file of that form can be read any more: no
writer of it is running and, for a day timeline, no day of that form is left in the index.
Stored at landing: `2026-11-10/` (the reader's four files and the directory's three) and
`2026-11-08/timeline.json`, the day timeline as it was before it carried `details`, which the
final day files of earlier days keep on the host.

### A run ends early for a newer branch head

A `predict` run prints, at its start, which commit it is on:

```
predict run: on 4ddffc0, the branch head
predict run: on 4ddffc0; the branch head is 9a1b2c3
predict run: on 4ddffc0; the branch head did not answer
```

While it runs it keeps a row: the dark passes since the last good pass **whose cause newer
code may cure**. Those causes are:

- one of the reader's four files does not validate (after the tolerant read);
- a deployed directory file does not validate, or `points.bin` does not decode;
- the file this pass made does not validate;
- an error no one foresaw.

A good pass sets the row back to 0. A dark pass of any other cause neither counts nor resets
it. Those causes never end a run, because a restart would not cure them: the alert feed
unreadable, stale or collapsed; the alert memory or its history; a directory that cannot be
known for certain (a deploy in progress, an API or CDN error) or is not the deployed one;
coverage; the file's size; a stale forecast; a host read error; another directory's opens
file; the upload (the hold, a read back that differs, a write error).

After a counted pass, once the row has reached 3 (`serve.restart_after_dark` in
`config/predict.yaml`; 0 never asks) and the state has been saved, the run asks GitHub once
for the head of its branch, with the job's own built-in token (the live host's token is never
sent). When the head answers and is not the commit the run is on, the run says so and ends:

```
predict run: ending early: 3 dark passes since the last good pass that newer code may cure; the branch head 9a1b2c3 is not this run's 4ddffc0
```

The workflow's remaining steps run as after any run, and "Start the successor" starts the next
run on the branch head. The same head, no answer, or a state that did not save change
nothing: the next counted dark pass asks again.

- **How soon.** No sooner than the third counted dark pass: usually 20 minutes after the first
  (two 10-minute gaps), and as little as about 10 when a grid pass comes right after another
  pass.
- **How often.** One question per counted dark pass from the third on: 6 an hour as a rule, 8
  at most. A run ends early at most once per new head.
- **What is lost.** Nothing. The state is saved before the question is asked, and a freeze is
  only ever taken by a pass that published.
- **Measured, first dark pass to the successor's first pass: about 24 minutes** (the bar is
  45): 20.0 to the third dark pass, 0.2 for that pass, 0.45 from the loop's end to the job's
  end, 0.5 for the next runner, 2.0 from the job's start to the run step (setup 10 to 18 s,
  learning 30 to 72 s, the read labels 23 to 46 s), 0.5 to its first pass. With every step at
  its own limit at once: 44.7, and 46.8 if the weather service is also silent at start-up.
- **The page.** The file is at most 34 minutes old at the first dark pass, so about 59 minutes
  old at the successor's first upload as measured, and 84 with every step at its limit: under
  the page's 90. Both figures assume the successor's first pass publishes. After a stretch of
  directory refusals it must first read the alert history once, and each failed read adds 10
  minutes, unless the 5-minute checks kept the memory whole (the alerts did not change during
  the stretch).

### Each pass's line, as it happens

Every Python step of the workflow prints each line as it is written (`PYTHONUNBUFFERED`), so
a line's time in the log is its own. Each pass ends with one line:

```
predict: pass 1 (grid) ok in 41.2 s, the live view 6.0 s more
predict: pass 2 (extra) dark in 9.8 s, the live view 0.0 s more, 1 since the last good pass that newer code may cure
```

The number counts this run's passes. The first time is the serving part: reading the inputs,
building the file, the upload and what follows it. The second is the live view taken after
it, which never holds a file back. The last figure of a dark line is the row above.

### The two watches and the one issue

| Watch | When | What it reads |
|---|---|---|
| `chances-watch.yml`, job `chances` | Every 5 minutes: each `live-ingest` run the owner's timer starts also starts one watch run. No cron, no owner step. | The public file, with the runner's own tools: no checkout, no install, no secret. |
| The Watchdog step of `predict.yml` (`predict check --max-age 45m`) | After every `predict` run. | The public file, once. |

The watch judges the file by its own `generated_at`, the time the page's 90-minute rule uses:
`fresh`, or `stale` (over 45 minutes old, less the time the CDN has held its copy, which is 10
minutes at most), `ahead` (over 15 minutes after now), `blank` (no districts), `unreadable`,
`missing` or `unreachable` (no answer in 3 tries, 20 s apart). A healthy file is at most about
38 minutes old at the host. Anything but fresh is a warning in its log and one issue, titled
**Snow-day chances are stale**. The Watchdog step uses the same title, so the two share one
issue: neither opens a second while one is open. While the file stays not fresh the watch
adds `still <verdict> at <time>` at most once an hour. Once a file 45 minutes old or less is
served, it adds `recovered at <time>` and closes the issue, so each new dark stretch opens a
new one. It never cancels, reruns or starts anything.

A dark stretch is reported at the latest 61 minutes after the public file was made (45, plus
10 for the CDN's copy, 5 for the tick, 1 for the watch run), and about 53 as a rule. That
holds while the owner's timer runs; a dead timer is reported on its own within 15 minutes
(docs/live.md, "Alerts"), and the Watchdog step still checks after every run.

The watch bounds itself by its own clock: every request waits 15 s at most, and it ends,
saying so, once 135 s have passed, so it is over within 150 s whatever answers. It always
ends green, and it is a workflow of its own so that nothing that happens to it can change a
`live-ingest` run or hold the timer's next tick. It must never be made a job of
`live-ingest.yml`.

Every upload also puts a stamp beside the file in the file's own commit, and so does `predict
blank`: `v1/predictions/stamp.json`, which holds the file's `generated_at` and its count of
districts and nothing else, about 80 bytes. Only the status page's checker reads it
(docs/status.md); neither watch does, and a stamp that cannot be made is one warning, never a
dark pass. Whoever reverts or removes the stamp's writer deletes `v1/predictions/stamp.json` and
`v1-shadow/predictions/stamp.json` from the live host in the same step: a stamp left behind
ages into a false "Not working" on the status page, while with none it reads "Could not check".

What each setting does to each watch:

| Setting | The watch every 5 minutes | The Watchdog step after a run |
|---|---|---|
| `PREDICT_PUBLISH` `on` (the default) | Watches. | Checks. |
| `PREDICT_PUBLISH` `shadow` or `off` | Quiet: one line, nothing asked. | Checks the public file all the same, and opens the issue once it is stale. |
| `predict blank` (the hold) | Quiet: it reads the hold and reports nothing while it is set. | Reports the blank file: the issue opens, and the watch leaves it alone while the hold is set. |
| The `predict` workflow disabled, no hold | Reports stale, with a comment each hour. | Does not run. |

Three things to know:

- The watch reads the repository variable `PREDICT_PUBLISH` at every tick. The chance job read
  it once, at its start. So after the variable is set back to `on`, a run that started in
  shadow or off is reported stale until it ends (up to 320 minutes, or at once after
  cancelling it).
- `PREDICT_PUBLISH` must stay a repository variable. Set on the `live` environment it would be
  seen by `predict.yml` only, and the watch would go on watching.
- The hold is read through the CDN, which can keep "no such file" well past 10 minutes. If the
  watch asked for the hold shortly before `predict blank` wrote it, the next ticks may still
  read "not held" and open the issue, or add its hourly comment, for a stop made on purpose.
  Once the hold is read the issue is left alone, and it closes at the first fresh file after
  `predict release`.

### Starting without the weather service

Every step that builds a pass needs the weather service's zone and county map: a page that
lists the releases, and the release files. Before, a page that did not answer stopped the
step. Now:

- **The saved copy is used.** When the page does not answer, or answers with something that
  does not read, the copy already in the cache is used, whatever its age. When the release in
  effect cannot be downloaded or does not read, the newest earlier release in the cache is
  used. With no saved copy the step fails with one line, as before.
- **Never silently.** Each fallback is one warning with the copy's date, for example `NWS zone
  boundaries: the release page did not answer (FetchError); using the copy checked
  2026-11-03T02:10:44Z`.
- **A silent service is not asked again for 15 minutes** (a small note in the cache folder),
  so the three steps of one job do not each wait for it. `predict run` asks once for itself
  all the same: the 320-minute run never serves on a saved copy without having asked.
  Each fetch tries twice, so the wait is about a minute at worst.

A saved copy can be out of date: a release the weather service issued since is not in it, and
a district in a changed zone could miss its alert. So a copy that lasts is reported. `predict
run` keeps since when its starts have been on a saved copy and warns `predict run: the NWS
boundaries come from a saved copy since <time> (...): the zones may be out of date`

- once runs have started on a saved copy for 24 hours, or
- at once, when the saved page was last checked over 7 days ago.

The workflow then opens one issue, **The weather service's zone map is not refreshing**. The
run's log names the newest release the copy lists: compare it with the service's page, and
close the issue once a run starts without the warning. The chances keep publishing on the
saved map meanwhile.

### The 5-minute checks and the history (predict-next MEMORY-GAP)

Item 8 above rebuilds the alert memory when the feed went unread for more than 20 minutes.
Grid passes are 30 minutes apart, so every grid pass with no extra pass in the 20 minutes
before it rebuilds the memory from the alert history: 48 history reads on a quiet day. Before
this piece an error from that history darkened a routine pass: two of the 22 dark passes on
record were exactly that (9:37 and 9:47 PM Eastern on Nov 8, when the public file waited 50
minutes for a fresh copy and the 9:30 PM freeze was taken 27 minutes late).

**What a check proves.** Between passes the loop reads the feed every 5 minutes. A check
proves the memory whole at its minute when the memory reached back far enough at its last
rebuild, the feed is at most 20 minutes old, it holds exactly what the memory last took in
(the same class-making alerts and the same `CAN` and `UPG` take-backs), and the last read or
check was at most 20 minutes before. A check never takes the feed into the memory; it only
records its minute (`checked_at` in the state).

**What breaks the chain.** Any read, a check's or a pass's own, fresh or stale, that sees
something the memory has not taken breaks the chain, unless the pass of that same check (for
a pass's own read, that pass) takes exactly that in. A check whose feed answered but could
not be read for its alerts breaks it too. No check proves anything after a break
until a pass rebuilds the memory from the history and that rebuild answers; only such a
rebuild mends a broken chain. A break is saved to the runner's state at the read that found
it, so a run that dies after it hands its successor no chain.

**When a failed read is a warning.** A pass that must rebuild and whose history read fails
goes on from the memory it kept when the memory reached back far enough at the gap, the chain
holds, the last proving check was at most 20 minutes before the pass, and the check of the
pass's own loop round, if any, read exactly what the pass takes in. Every other failure is
dark as before. The run saves its state once more at the end of its window, so the next run
starts from the last check: a run's first pass is covered when it comes within 20 minutes of
that check (the handover takes about 3.5 minutes).

**The lines.** Such a pass prints `predict: alert_memory: alert history: HTTP 500; the memory
was whole at the 03:32Z check: the pass goes on from it` as a warning, and its line ends `ok`.
With the outlook in shadow, the record step then backs off instead of asking the history that
just failed: `outlook shadow: DarkError: nothing recorded this pass (alert_memory: the product
log's history read failed; no new try before 04:07Z)`. A quiet grid pass that instead shows
`dark (alert_memory: alert history: ...)` had a broken chain: look for an alert change between
passes (an extra pass, a cancel), an unread or stale feed at the checks, or a run before it
that failed.

**What such a pass serves.** Exactly what any pass within 20 minutes of a read serves: the
memory as the last pass left it, with this pass's feed taken in. While the history answers,
nothing changes: every uploaded byte and the 48 history reads a quiet day are as before.
While it is down, a pass makes the one history read a dark pass made, and while the chain
holds the history is asked once per 30 minutes instead of three times.

**What stays dark.** A lost or stale state, a memory that did not reach back far enough, a
chain broken by an unread or stale feed or by a read that saw what the memory had not taken
(until a rebuild answers), a check whose own pass read something else, a run that died after
such a read, and any pass with the switch off. A break save the disk refuses only warns, as
every save does, so a run that then dies before a save works hands the old chain on.

**The switch.** `serve.memory_checks` in `config/predict.yaml`, on. Off restores the dark
pass, and the state then holds neither of the checks' keys from the run's first save.

**Found on the way: two answers for an alert that leaves the feed early.** The routine rebuild
stays, because the rebuild and the kept memory do not serve the same numbers. An alert that
leaves the feed before its stated end (an early `EXP`, or a feed that drops it) counts to its
stated end after a rebuild, and only to the last pass that saw it without one. With an advisory
for the Missouri zone, 12:00 to 18:30 CST, expired at 17:45 CST, the next day's chance for one
district at five uploads from 5:37 PM to 7:07 PM CST is 57%, 1%, 1%, 57%, 57% today; stopping
the rebuild would make it 1% from the second upload on, on healthy passes. A `CAN` for an event
already gone from the feed is a second case: it reaches the memory only through a rebuild. The
piece `one-memory` is queued to make the passes agree on one answer, so the routine rebuild can
stop. Until then a pass that goes on from its checks serves the kept memory's answer, the one
the page already showed.

## The storm drill (predict-next STORM-DRILL)

Before a big storm we play one through the real system, hour by hour, and read the number a
family would have seen at each moment that matters. `snowlight predict drill` does that, on any
commit, in seconds. It serves nothing: it publishes to a host that is a dictionary in its own
memory, opens no network connection, reads no secret, and writes only inside its own temporary
folder (and the `--json` file). Nothing in the live chance job runs it.

**What it runs.** Nine stories of one scripted storm, Tuesday Jan 12 2027 (Monday and Wednesday
around it are school days too), each in its own made-up zone and state, so a fix moves its own
rows and a cell of another story that moves is a change to explain:

| Story | Risk row | State | Districts | The products | The forecast at each school |
|---|---|---|---|---|---|
| `watch` | B1, C3 | NY | 6 | winter storm watch at 4 AM Mon, upgraded to a warning at 5 PM | 3 in (picks 1, 3, 5) or 20 in (2, 4, 6) |
| `cancel` | B3 | MA | 4 | warning at 3 PM Mon, cancelled at 4:30 AM Tue | 8 in |
| `late` | B4 | WA | 4 | warning at 3 PM Mon for 10 AM Tue on | 6 in |
| `daytwo` | B2 | MO | 4 | warning to 5 PM Tue; every school posts closed for the storm at 7:45 AM Tue | 10 in |
| `coldadv` | B5 | MN | 4 | cold weather advisory 3 AM to 10 AM Tue | none |
| `half` | B6 | OH | 4 x 5 schools | warning over 2 of each district's 5 schools | 8 in |
| `blizzard` | C1 | ND | 4 | blizzard warning | 6 in |
| `extcold` | C2 | MT | 4 | extreme cold warning | none, feels -35 F at 7 AM |
| `overnight` | C4 | PA | 4 | freezing rain advisory first issued at 3 AM Tue | none; from the 1 AM run on, 0.15 in of ice |

The districts are real ones of the committed model (their LEAID, county, time zone, record and
exposure: everything a chance is made of), picked by rule: those of the state in its most common
time zone, from the least to the most exposed to winter storm warnings. Their schools sit on
made-up points inside made-up zones, 69 miles apart, so no district has a neighbor. The pass is
the real one (`cli.Pass` and `cli.loop`, publishing on), on a faked clock from 3 AM Eastern
Monday to 6 PM Pacific Tuesday: 96 passes on :07 and :37 and within 10 minutes of each change in
the feed, as live. Only the callables the pass already takes are the drill's: the alerts (the
service's `/alerts/active` body, parsed by the real reader), the history, the directory, the
host, the clock, the forecast and the night. The host gives back at once what was last written,
so every read-back of a pass (the publish, the switch, the stamp) confirms at its first read. The
pass's wait before a second read is the real `time.sleep`, which the drill leaves as it is (it is
served code): a host that did not confirm at once would make the story wait for real, and the
drill's tests fail on any such sleep.

**The seams.** The forecast goes through the real settled reader
(`outlook_live.settled_reader`, which reads each zone only from 9 PM the evening before), the
real per-district arithmetic (`forecast_live.forecasts`) and the real run assembly
(`ndfd.assemble_runs`, over scripted listings whose files go up 50 minutes after their stamp);
only the run's values at each school are scripted. The night chart goes through the real night
reader over a scripted blend. So a piece that changes any of these changes code the drill runs,
and its effect shows in the table. **The one copy.** `drill.drill_read` copies the body of
`outlook_live.forecast_reader` with its two network parts scripted, and `drill.adjust_reader`
composes it as `cli._adjust_reader` does. The drill's tests compare both with the live code and
fail until a change there is followed in the drill, in the same commit.

**How to read a cell.** For each district, on its own clock: 4 PM, 8 PM and 9:30 PM Monday and 5
AM and 6:30 AM Tuesday (each the chance for Tuesday), and 4 PM Tuesday (the chance for
Wednesday). A cell is what the panel would show from the last file the host held at that moment,
by the panel's own rules: the file at most 90 minutes old and at most 15 minutes ahead; the day
the panel heads, the first of the district's today and the file's next day that is not decided
and not under way (from 7:30 AM, or once its buses ran where the file says when); the percent
rounded as the panel rounds it (a half up); then `^41` (up from 41%), `v41` (down from) or `=41`
(same as) when the panel would show its move line, then the base's letter (`C` class, `P`
pooled, `A` alert, `D` day after, `S` similar days), `b` when the base is borrowed, `f` when a
forecast line shows and `a` when the district closed for weather the day before (the drill's own
reading of the day timeline the host held). `--` is no number (no file yet, or one over 90
minutes old, as the panel shows nothing then); `n/a` is a day not in the file; `off` is a moment
at which the panel heads another day (today no file says when buses run, so no cell is `off`).
The drill's tests read each of these rules' numbers in the web source (`school-day.ts`,
`chance.ts`, `forecast-detail.ts`, `copy-chance.ts`) and fail when one changes there. The
calm-day number is 1% with no alert's weather.

**How to read a verdict.** One line a risk row, `shows` while the row is still true of the head
and `gone` once a fix took it away, each with its numbers. Each names the mechanism its fix
changes, never a threshold on a percent, so a change of a level does not flip a verdict its fix
did not:

| Row | Shows when |
|---|---|
| B1 | `watch` at 4 PM Mon: every cell the calm-day number |
| C3 | `watch` at 8 PM Mon: no forecast line, each chance its base's points; at 9:30 PM a forecast line everywhere |
| B3 | `cancel` at 5 AM Tue: every cell calm |
| B4 | `late` at 6:30 AM Tue: every cell calm |
| B2 | `daytwo` at 4 PM Tue (for Wed): every cell calm, after a weather closing and borrowed; no other district after one at any moment |
| B5 | `coldadv` at 9:30 PM Mon and 5 AM Tue: every cell calm |
| B6 | `half` at 9:30 PM Mon: every cell calm, with at least one school of each district in the warned zone and fewer than the share that makes a class cover it (the line counts them: 2 of 5 each, under the 50%) |
| C1 | `blizzard` at 9:30 PM Mon: no forecast line, each chance the district's plain winter storm warning level |
| C2 | `extcold` at 9:30 PM Mon: class base, no forecast line, each chance the district's cold class level, and the cold class still starting at 0.10 |
| C4 | `overnight` at 5 AM Tue: a forecast line, each chance under its base's points |

On the commit it landed on, every row shows, and the run line reads `drill: 96 passes (0
dark), 96 uploads, the largest file 18,149 bytes`. The table then, for Tuesday (the last column
for Wednesday):

| Story | 4 PM Mon | 8 PM | 9:30 PM | 5 AM Tue | 6:30 AM | 4 PM Tue (for Wed) |
|---|---|---|---|---|---|---|
| `watch` | 1% all six | 29-49%, up from 1% | 3 in: 29-39%; 20 in: 87-91% | as 9:30 PM | as 9:30 PM | 1% |
| `cancel` | 37-45%, up from 1% | 37-45% | 38-65% | 1%, down from 38-65% | 1%, down from 38-65% | 1% |
| `late` | 1% | 1% | 1% | 1% | 1% | 31-55% |
| `daytwo` | 44-52%, up from 1% | 44-52% | 87-94% | 87-94% | 87-94% | 1%, borrowed, after the closing |
| `coldadv` | 1% | 1% | 1% | 1% | 1% | 1% |
| `half` | 1% | 1% | 1% | 1% | 1% | 1% |
| `blizzard` | 35-42%, up from 1% | 35-42% | 35-42%, no forecast line | 35-42% | 35-42% | 1% |
| `extcold` | 6-12%, up from 1% | 6-12% | 6-12% | 6-12% | 6-12% | 1% |
| `overnight` | 1% | 1% | 1% | 3-4%, with a forecast line | 3-4% | 1% |

**How a later piece uses it.** Each serving piece that changes a number runs, on its base commit,
`uv run snowlight predict drill --json before.json`, and on its branch `uv run snowlight predict
drill --json after.json --against before.json`, which prints every cell and verdict that moved
(`LEAID story moment: before -> after`) and how many. The landing notes carry both tables and the
list. A cell that moves outside the piece's own rows is explained there or is a blocking finding.
The piece flips its own row in `test_drill.py`'s pinned rows in the same commit. A piece that
adds bytes to the file also runs `--size --full` before and after.

**The storm-size night** (`--size`). Every district of the committed model and every private
school it holds, on a 6-mile lattice of made-up points; a winter weather advisory over a share of
the districts since Sunday, upgraded to a winter storm warning at 8 PM Eastern Monday; the
forecast through the same real readers, the blend's night snow over the storm only; nine passes
from 7:37 PM Eastern Monday to 6:30 AM Pacific Tuesday, so every zone's four freezes are taken.
Each pass prints its compute seconds (the serving part only: the live job also reads the
network, uploads and runs the outlook's shadow record, which the drill does not), its file's
sizes against the budget (16,500,000 raw, 1,500,000 gzip, and 16,446,182 raw for a file with
nights; a margin under 3% is said "at the edge"), what it holds, the ladder's own warning when
it took a step, and whether the file is whole: a forecast line, the private schools and their
previous chances, a night on the storm (on every storm district through the evening), the
districts' previous chances through the evening, and a record day wherever an own base shows.
Then the frozen day's size and what storing it costs.

Two forecast mixes, the two bounds, so a size claim says which storm it is about: **worst**,
every storm school with snow, 0.05 in of ice and a 12 F morning (a snow, an ice and a cold line
on nearly every adjusted district-day), the upper bound; and **typical**, snow only, the lower
bound. A real January storm lies between: of the forecast climate's warning district-days of
2018-19 to 2025-26, 76.6% carry a snow code, 8.7% an ice code and 6.4% a cold code.

Measured on Nov 13 2026 at `210561b` by `--size --full` on a builder's 4-CPU machine (44 minutes,
peak memory 1,700 MB); CPU seconds of the serving part of each pass. A file with nights must stay
under 16,446,182 bytes raw.

| Share, mix | Largest file (raw / gzip, when) | What the ladder left out, and when | CPU a pass |
|---|---|---|---|
| none (calibration) | 8,486,502 / 699,026, its one pass | nothing; the live file of Nov 10 was 8,306,870 / 611,554, so the lattice is 2.2% larger raw | 24.0 s |
| 37%, worst | 13,462,785 / 903,008, 9:30 PM Pacific | nothing, at all nine passes (3,037,215 under the budget) | 22.8 to 33.8 s |
| 37%, typical | 11,631,835 / 859,134, 9:30 PM Pacific | nothing | 20.8 to 31.7 s |
| 70%, worst | 16,433,827 / 1,033,871, 9:30 PM Eastern, 12,355 under the night limit: at the edge | from 9:07 PM Mountain the night chart and every "Up from" (`published it with no record days or previous chances`; at 9:30 PM Pacific `... or night charts`, with no "Up from" left to carry); none in the morning either, the private schools' too; forecast lines kept | 29.4 to 37.6 s with no step; 84.5 and 131.7 s stepped down |
| 70%, typical | 14,373,585 / 992,301, 9:30 PM Pacific | nothing | 27.5 to 35.8 s |
| 100%, worst | 15,583,449 / 954,802, the advisory; the largest published with no step, 16,211,006 / 1,039,470 at 5:07 AM Eastern, has no private previous chance, 235,176 under the night limit: at the edge | from the upgrade the night chart and every "Up from"; from 9:30 PM Eastern to 9:30 PM Pacific every forecast line too (`published it with no record days, previous chances or reasons`): every district at its plain class level, 9,707,884 bytes; in the morning the lines return, 18,175 of them each with a move line from that bare level, the private schools' none, and from 6:07 AM Mountain the night chart goes again | 32.8 to 45.6 s with no step; 82.2 to 169.9 s stepped down |
| 100%, typical | 16,299,635 / 1,082,114, 9:30 PM Eastern, 146,547 under the night limit: at the edge | the night chart at 9:07 PM Mountain and 9:30 PM Pacific (`published it with no record days or night charts`); every "Up from" and forecast line kept all night | 33.9 to 41.9 s with no step; 91.4 and 96.5 s stepped down |

So, today: with snow lines only nothing is lost at 37% or 70%, and over every district only the
night chart; the "Up from" lines go only in the worst case from 70%, and every forecast line only
in the worst case at 100%. Once a pass leaves the previous chances out, the next passes have none
to carry, so they stay gone through the morning. A pass that steps down builds the whole file at
each step before it measures it, so it costs two to five times the CPU of one that does not. No
gzip size comes within 27% of its limit. No world holds an own base or a record day today.

The frozen day, as the real pass wrote it (nine passes that take every zone's four freezes of
Tuesday, each at most 60 minutes late; 72,928 lines), at the store's xz preset 9: 37% 17.9 MB raw
and 220,844 bytes (worst), 17.1 MB and 196,640 (typical); 70% 27.2 MB and 330,972 (worst), 25.6
MB and 289,000 (typical); 100% 29.3 MB and 456,952 (worst, whose evening freezes hold no lines),
33.4 MB and 369,428 in 4.7 s, 492,584 stored, 7 D1 rows a database (typical). Each is under the
1 MB a day, but the drill's forecasts repeat every 13 schools, so its rows compress better than
a real night's: the 804 KB of "The frozen record" for every district in a class stays the bound.

**The CI job.** `storm-drill` in `ci.yml` runs `uv run snowlight predict drill --size --json
drill.json` on every push and pull request (20-minute limit, no secret, its output in the job's
summary): the story, and the 37% worst-case world, the docs' "Storm, 37% of districts in a
class" at its heaviest. It is red only when the command fails: exit 3 when a pass of that world
went dark or its file is not whole, so a later piece whose lines or bytes would cost such a storm
its chart, its "Up from" lines or its forecast lines fails there. The story's verdicts never
fail it. The 70% and 100% worlds and the typical mix run by hand with `--size --full` (about an
hour on a builder's machine), never in CI: what may be dropped there is a serving decision.

## Retraining

After a new season of archived lists (or a directory change that adds districts):
`predict labels`, `predict backtest` (check the gates in its report), `predict train`,
commit `data/predict/model.json.gz` with the report's numbers in the message.

## The model learns on its own

Every predict workflow run starts with `predict learn` (`pipeline/snowlight/predict/learn.py`,
`live_labels.py`). It needs no API key and no server beyond the live host and the Actions
cache. The owner's Cloudflare Worker needs no change: it dispatches the same workflow.

What it reads is kept long enough: the live state's morning record and the passes' weather-class
snapshots keep 45 days, and `learn.morning_reads_days` is 44, so a day it can still label always
has its record, the record of the day before and its snapshot. Every finished day of both is also
kept for good in the evidence databases (docs/live.md, "The evidence"; `predict evidence` keeps
the snapshots, the district tables and the labels). Neither leaves its state before a database
holds it: after each push, `predict evidence` notes in the pass state (`evidence`) which
snapshots and district tables the databases hold, byte for byte, and a pass lets a snapshot
older than 45 days go only once a database holds it and the table it indexes. The pass state
also keeps the district table of every directory content its snapshots index (`tables`) until a
database holds it, so a content that is no longer deployed still has its table kept. A database
that does not answer changes nothing known of it. `predict evidence --check` (no network) fails
when a finished snapshot or its table has waited 2 days for a copy in both databases, and the
workflow then opens one issue, "The live evidence is not kept"; nothing is lost while it is open,
because the state keeps every such snapshot.

Every run's learning step also prints `predict learn: live_score sha256 <hex>`: the sha256 of
the pre-registered live scoring rules (the `live_score:` block of `config/predict.yaml`, the
`labels:` and `weather:` blocks and `learn.snapshot_slack_minutes`; `config.LIVE_SCORE_SHA256`,
held by a test), so the public run logs date the registration. A change to any of them is a
reviewed commit that changes the sha256 and applies only to rows that arrive after it.

`labels.reason_rule: 2` (Nov 3, 2026) is registered this way: flooding, severe storms and a
hurricane count as a weather closing only on a `tropical` day, and Election Day, Veterans Day,
Columbus Day and Good Friday are break days ("The model as fit"). It decides by reason codes
and dates only, never by outcomes, and applies to every day a label run reads: the archive and
the live record `predict learn` labels. Landed with it, the merge keeps a reason one list
names beside one that names none, and the reader reads a few more causes (docs/live.md, "The
reader").
Run over the archive against the code before it, with the same inputs, all of it changed 0 of
the 5,134 labels (advisory 0 of 667 known, none 0 of 618, blizzard 0 of 211, snow warning 0
of 860, cold 0 of 32) and moved no no-school or delayed share; 4 snow-warning school-days
gained a named winter storm reason. The committed model is not refit for it: the next refit
(a swap here, or a retrain) takes the labels as they are.

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
   unless one is already open. The same issue opens when the step fails, except in the one
   case below where the new version was written and not confirmed.
   The step writes its files (`learn.json` when it labeled a new day, then `learned.json` on
   a swap or a reset) in one commit and reads each back, in that order, the way the passes
   read theirs: at once, then again after 2, 4 and 8 s while the host gives other bytes
   (GitHub's API can answer with the file it held before the commit for a second or two;
   issue #65 was a single read that met it, after a write that had gone up). What is written
   and what is said, in each outcome:
   - **Confirmed** (every file read back as written at once) or **caught up after retries**
     (a file gave the old bytes, or no file, and then the new ones within the 3 waits): the
     files are written and live, and the step goes on as before: its decision line, then
     the outlook's step, and exit 0 (or 4 for a refit kept out).
   - **Never confirmed** (no read of a file gave its bytes): every file of the commit was
     sent and went up as far as the host said; the step stops at the first such file
     (exit 1) with `predict learn: error: wrote v1/predictions/learn.json and
     v1/predictions/learned.json but v1/predictions/learned.json did not read back as written
     (4 reads, none the blob 1a2b3c4d5e6f sent: HTTP 200 blob 9f8e7d6c5b4a, HTTP 304 blob
     9f8e7d6c5b4a, ...)` (a single file: `wrote <key> but it did not read back as
     written (...)`). No decision line and no outlook step follow.
   - **Read error** (a read-back read failed: an error from the host, not other bytes): the
     files were written just the same; the step stops there (exit 1, no later file is read)
     with `predict learn: error: wrote v1/predictions/learned.json but reading it back
     failed with an error (<the read's error>), so it is not confirmed` (several files:
     `wrote <every key> but reading <key> back failed with an error (...)`). A read-back
     that raises is a read error, as it was before the read-back retried.
   - **Write failed** (the host answered the write with an error, or its answer did not
     come): `predict learn: error: <the write's error>: the served model is as it was`
     (exit 1). A commit on GitHub moves the branch last, in one request, so a write that
     fails before that request writes nothing; the one exception is an answer to that last request lost
     after GitHub moved the branch, which the line cannot tell from a failure (the next run
     reads the files as they are).
   In the two outcomes after a write, neither line says the model is as it was. When
   `learned.json` was among the files written and not confirmed (never confirmed, or a read
   error), the step writes `learned=unconfirmed` to its step output, and the workflow opens
   "The snow-day model's new version is not confirmed" in place of the kept issue: the new
   version's files were written but could not be read back to confirm them, so the served
   version may be the new one. `learn.json` alone not confirmed (no swap or reset) keeps the kept
   issue: the served model did keep its last version.

Serving never depends on it: the step may fail or time out (5 minutes; it takes under a
minute) and the passes run anyway. A learned file that is missing, does not validate, was
made over another committed model or does not build is ignored, and the committed model
serves alone. Settings are in `config/predict.yaml` under `learn`.

**To drop a misread day, or one district's row of a day.** This is for a morning or a
district we read wrong (a list that named the wrong district, a page read from the wrong
day), never for a true closing that only looks unusual. In `config/predict.yaml` under
`learn`, add the day to `excluded_days` (`excluded_days: [2026-12-02]`) or the pair of the day
and the district's 7-digit id, the id in quotes, to `excluded_rows` (`excluded_rows:
[["2026-12-02", "2502790"]]`), with a dated reason in a comment beside the entry (`# Dec 3: the
list named the wrong district`), and commit it on the default branch. Neither list is part
of the pre-registered rules: a take-back needs no registered change. It acts at the next
process start (a predict run starts about every 5.4 hours), and removing the entry brings
the day or the row back to the class levels.

What each reader does:

- **The class levels** ("The storm-class levels"). An excluded day's files are skipped by
  name, unread. A listed row is dropped from its day as read, with that district's trial
  lines of the day. The record's files are never rewritten, and the fit is the fit of a
  record that never held them. The pass's line says `take-back 1 day listed (1 in the
  record), 0 rows listed (0 in the record)`; `(0 in the record)` means the record does not
  hold it (not labeled yet, never labeled, or a district with no labeled row that day):
  nothing was there to take out.
- **The labeling.** An excluded day is never labeled. A listed row is still written with
  its day and left out by the readers: listing it before or after the day is labeled gives
  the same fit. The live reader's own counts and the public audit keep every labeled day
  and row.
- **The live switch** ("The live switch") drops a day in either list whole and replays the
  rest; it never counts that day again.
- **The learner below** drops a day in either list whole: the next run never fits or holds
  out that day. When the served learned file counted it, that file (the file lists the
  days it counted, so this holds even if `learn.json` was lost) is judged again against the
  committed model: the refit without the day replaces it if it passes the check, and
  otherwise a file that re-anchors nothing does, so the committed model's chances serve
  until newer days pass. The file that replaces it no longer counts the day, so the run
  after says `unchanged`. To return to the committed model at once, also delete
  `predictions/learned.json` on the live host.

**Before pushing, load the config**: `cd pipeline && uv run python -c "from
snowlight.predict.config import PredictConfig as C; c = C.load().learn;
print(c.excluded_days, c.excluded_rows)"`. A list that does not read (the usual slip is a
district id without quotes, which YAML reads as a number) stops every predict command from
the next run on: the chances go stale and no morning is labeled until it is fixed. The live
reader does not stop (it does not load this config), so the mornings are still recorded and
are labeled after the fix, oldest first. The issues that say so are the workflow's own for a
failed learn step and `Snow-day chances are stale` ("Staying on air").

**A take-back can split a storm.** One middle morning taken back does not (a storm allows
one weekday between its mornings). Two weekdays in a row taken back from the middle of a
longer storm make it two storms: the line goes from `by storms 1.00 of 8` to `by storms 2.00
of 8`, and the level moves by the two-storm amount toward what the mornings left say (a
Monday to Thursday warning storm of 3 markets of 100 rows, all closed, with Tuesday and
Wednesday taken back: 49.3% to 61.9%). Read the line's `by storms` before and after, and
tell the lead when it rose.

The live state reaches the workflow through the Actions cache: the live loop keeps it with
the `cache` state store (`config/live.yaml`, folder `out/internal/live/store`), and the
workflow that runs it must save that folder under a key starting `live-state-`
(`CACHE_KEY_PREFIX` in `pipeline/snowlight/live/state.py`; a test holds every workflow to
it). The step restores the newest such key and never saves it. A machine that runs the live
ingest itself reads `out/internal/live/state` directly. No workflow runs the live loop yet
(`config/live.yaml` keeps its state `local`), so until one does the step logs "no live
ingest state reached this run" and then "nothing to learn: no live-read district-days
labeled yet; the model is unchanged".

## The frozen record (predict-next P1: a record, nothing served)

Every later change to the chance, and the nightly scorer (L4), is judged on what was actually
served. A storm night that is not recorded can never be scored, so each pass now keeps what it
served and what it was made from (`pipeline/snowlight/predict/frozen.py`). It only records:
the published files are the same byte for byte with it on or off (a test runs the same passes
both ways), and any error in it is one warning a pass (`predict: frozen record: ...: nothing
frozen this pass`) while the pass publishes as before. It is never a reason for a dark pass.

- **When.** For each school day D and each time zone the districts are in, four freezes on that
  zone's clock: 20:07 the evening before (`d1_2007`, L4's horizon 1), 21:30 the evening before
  (`d1_2130`, when families look), 05:07 on the day (`d0_0507`, L4's horizon 0) and 06:30 on
  the day (`d0_0630`). The first pass that publishes (or finds its file unchanged) at or after
  a freeze's time takes it, once per day, zone and freeze; no later pass rewrites it. The
  passes run every 30 minutes and on alert changes, so a freeze is usually taken up to 30
  minutes after its time, and its header says how late (`late_by_s`); one taken later than its
  time keeps the chance of the pass that took it. A freeze more than 90 minutes late (no pass,
  or only dark passes, in between) is written `missed` with the number of districts it would
  have held, never filled from a later chance. Daylight saving changes are on each zone's
  clock (tests cover Nov 1, 2026 and Mar 14, 2027), for the four zones, Arizona, Alaska and
  Hawaii. A row says its chance was served (`s` 1) only when the public file at the pass was
  that pass's file: uploaded by it, or, on a pass that found its file unchanged, read back from
  the host with the same content. Otherwise `s` is 0 and says why: `not_shown` (the public
  file is another, as after `predict blank`, or after a release until the next upload),
  `unconfirmed` (the read failed) or `not_public` (shadow mode).
- **What.** Codes and numbers only: LEAIDs, days, times, codes and chances; no names, no list
  text, no URLs. Each freeze of a zone is a header line (the freeze, zone, its time, how late,
  the pass's file time, the run id, the code sha and the `live_score` sha256) and one line per
  district of the zone: the chance of no school and of a delay as published and before
  rounding; the situation, the serving class (none, advisory, warning, cold) and the alert
  kind; on a class day its level (as published and before rounding) and the district's
  exposure offset; the reasons shown (kind and points); whether it said school is on; the
  forecast adjustment's read (`before` the 9 PM class snapshot, `none`, `read`, or `kept` from
  the last file) with the forecast inputs it read (window snow, commute snow, snow before the
  bus hour (7 AM local, `bb`, on every freeze, the bus hour term on or off) and each period's
  snow to the hundredth of an inch, finer than the forecast's own tenths; ice to the
  thousandth; the 7 AM feel in whole degrees; the code and the run time; each period's bounds
  in minutes from the day's 00:00 UTC) and each term (snow, timing, ice, cold, to 4 decimals
  of log odds) before the class's bounds, the bounds, and, only where the bounds clamped a
  term, the terms after them; the span of the
  class's alerts and whether one names heights; the strongest watch in the active feed
  reaching the district that day; and a `variants` map, where shadow candidates are scored on
  the same row. Since TIMING-AUTO each header also names each live switch term's served arm and
  key (`switch: {bus_timing: {arm, sha256, model_sha256}}`), and each served `d0_0507` row of an
  advisory or warning model chance holds `v.bt = [off, on]`: the model's own chance before
  rounding under each arm of the bus term, through the served path (the class order cap, the
  usual and G6 as served), 6 decimals; lit and said-open rows included, since the row set is
  chosen before any outcome. It is `null` where the pass read no forecast (`fr` before, none or
  kept), and on every row of a model build where the arms' even factors differ in a zone holding
  a solved district (then the shared usual would not be the shadow arm's), or where the model's
  settings are not the served arm's; the freeze's line says which (`bt on 6,410 rows`, `bt none
  (even factors differ by arm)`). Rows frozen before it read as before, with no `switch` and
  empty `variants`. A district with no chance in the file still has a line
  (`s` 0 and why), so coverage is measurable. The keys are listed in `frozen.ROW_KEYS`. The
  adjustment's read and terms are written only where the file applied the adjustment: not
  under a file cut to no reasons by the size budget, nor with the reasons' terms on. A file
  the outlook made (`PREDICT_OUTLOOK=on`) says so in its headers (`maker`), and its rows hold
  what it published, never the regular model's level, offset, unrounded chance or terms.
- **Where.** One file a school day, `out/internal/predict/frozen/<D>.jsonl`, compact JSON
  lines, in its own Actions cache (key `predict-frozen-`, apart from the pass state). A day is
  finished an hour after the last zone's (Hawaii's) 06:30 freeze; a freeze still not taken
  then is written missed. `predict evidence` then keeps the finished day in both evidence
  databases (kind `frozen`, key D, xz compressed, append-only), and the day leaves the folder
  only once both hold it byte for byte (the snapshots' keep-until-held rule, docs/live.md "The
  evidence") and, since TIMING-AUTO, the live switch counted it (the day is on or before the
  marker `frozen/switch.json`'s `through`, which `predict read-labels` rewrites from the host's
  state after each read-back) or it finished more than 9 days ago (two past the 7 a labeled date
  waits for its frozen day). A day both databases hold is not offered again while it is kept. So
  a day stays about 18 hours longer than before (from the run it finishes in to the run that
  labels it), at most 9 days, and CALL-TIME's counts line
  finds its served `d0_0630` rows. `predict evidence --check` fails, and the workflow opens "The live evidence is
  not kept", when a finished frozen day has waited 2 days for both. If the Actions cache is
  lost, the passes begin a fresh folder (a freeze already past by over 90 minutes is written
  missed; a day first seen after it finished is not taken up), and the next `predict evidence`
  restores the finished days of the last 7 the store holds, so they are kept until both
  databases hold them; the restore has its own 20 seconds, before the push's 45. An index
  that is lost, does not read or is of another schema is made again from the day files (every
  whole freeze in them kept as taken or missed, never cut). A day file longer than its index
  counts (a pass stopped mid-write) is cut back to the count; a shorter one (a cache that came
  back short) is cut back to its last whole freeze, and a freeze lost there is taken again
  while it is due, else written missed.
- **Reading it.** `frozen.rows(first, last, folder, store)` returns each day's rows typed
  (`FrozenRow`), and its missed freezes, from the folder and every version the evidence store
  keeps, merged: each freeze once, a taken copy over a missed one, and of two taken the one
  taken first. A day can be kept in two versions when a run's push went out but its cache was
  not saved: the next run, on the older folder, closes the day without the freezes taken
  since, and writes them missed; the merge reads them taken. The restore merges the same way.
- **Budgets.** Measured on full synthetic days over the committed model's 18,227 districts
  (synthetic points, alerts and forecasts; the forecasts at their own precision: snow in
  tenths of an inch, ice in hundredths, whole-degree feel), four freezes in every zone, 72,908
  rows a day. A finished day is kept at xz preset 9 (its 64 MiB window finds each district's
  earlier freezes, which preset 6's 8 MiB misses; any preset reads back the same):

  | Day | Rows with terms | Raw | xz | Stored (base64) | D1 rows a database |
  | --- | --- | --- | --- | --- | --- |
  | Quiet (no storm class) | 0 | 7.6 MB | 43 KB | 58 KB | 2 |
  | Storm, 37% of districts in a class | 19,311 | 15.8 MB | 390 KB | 520 KB | 7 |
  | Heavy storm, 70% in a class | 36,459 | 23.2 MB | 628 KB | 838 KB | 11 |
  | Every district in a class | 52,008 | 29.8 MB | 804 KB | 1.07 MB | 14 |

  So every day is under the 1 MB a day compressed (at preset 6 the last would be 1.17 MB).
  Compressing the largest takes about 12 s in the evidence step, as at preset 6. The folder
  holds a day raw until both databases have it, so a few days of it. The recorder takes at
  most 1.60 s on a pass that freezes a whole zone on the day with every district in a class
  (two runs: 1.46 s and 1.60 s; most such passes 0.6 to 0.8 s), 1.25 s at 70%, 0.93 s at
  37% and 0.61 s on a quiet day, under the 2 s; a pass with no freeze due takes 0.006 s. It
  takes each adjusted day's terms from the ones the file applied, never working them out
  twice, and works out the exposure offsets once per model. The live switch's shadow
  (TIMING-AUTO, `v.bt`) adds to a `d0_0507` freeze only. It takes the served arm's chance from
  the row's own terms and works out the other arm's for all the freeze's rows at once over
  arrays (`serve.arm_chances`, each class order cap's warning chances first), the same numbers
  as the served path to the bit (a test holds them equal over every situation, four zones, ice,
  cold, an unknown code and no forecast). Measured on the storm days above (the bus term's snow
  before 7 AM drawn per district), each the least of three runs with and without it (CPU time):
  with every district in a class, the worst day, +0.12 s on the Eastern zone's freeze (7,191
  rows, 6,853 with `v.bt`), +0.14 s Central (6,110), +0.08 s Mountain (1,876) and +0.06 s
  Pacific (2,497); at 70%, +0.14, +0.13, +0.03 and +0.05 s; at 37%, +0.07, +0.03, +0.02 and +0.02
  s: under the +1.0 s allowed, and the worst pass stays under 2 s (1.60 s without it, about
  1.74 s with it). Its own
  time is logged
  (`predict frozen: recorded in ... s`) on every pass that took a freeze. In D1 a finished day
  is one item row and one row per 64 KiB part (2 statements of part writes, 1 read back and
  the item row on the largest day), against the free plan's 100,000 rows written a day. Stored, a winter of
  about 150 quiet and 30 storm school days is about 25 MB a database (28 MB if 10 of the storm
  days are heavy), 250 to 280 MB in 10 winters. With the other kinds' 21 to 46 MB a year
  (docs/live.md "The evidence") a database passes the push's 300 MB warning in about 4 to 6
  winters, and the next pair of databases comes then, before the free plan's 500 MB, by a
  reviewed change (the rule docs/live.md states).

## The read labels (advisory-sane L1: a record, nothing served)

`predict learn`'s labels come only from lists that already lit a district on two live days,
so a district that is read every morning and never closes gives no label. `predict
read-labels` labels each live school morning from **which lists were read**, decided before
any outcome is looked at (`pipeline/snowlight/predict/live_read.py`; the rule is
pre-registered in `config/predict.yaml` `live_score.read` and S7 addendum h). It is a second,
separate record: `learn.json`, the learned file and their tests are unchanged.

A district is **read** on a school day when a list that may read it (tier A: it carries the
district in the archive audiences, or in the live audience built from the change log's days
**before** that day, so the day's own lightings never decide who was read; tier B: it is
proven for the district's county and has 5 **closing-size** captures in the archive and the
live record before the day together; a district's own site is neither) had a whole read in a 30-minute
slot of the district's 06:30-09:30 window, shown on the map, with the reader's healthy share
at least 0.9 in that slot, and either had a **counted day** (below) in the 14 days before or
a second list of the market read too. A whole read passes the archive's and S7-L's station
gates, one rule for all three, and more of its own:

- **closing-size captures, one test for the archive and the live record** (lead rulings C1
  and C2, `closing_size` in `live_read.py`, which both sides call so they cannot drift): a
  capture is closing-size only when the list's **own** rows named at least 3 districts under
  a warning-or-above class (snow, lake snow, ice, blizzard or tropical warning; advisory and
  cold are not). Archive: an archive capture is a Wayback snapshot of any hour of any day
  (an August page, an evening church list, a one-row list), so only a capture whose rows
  named, in the archive's match, 3 districts warned on its local day or the next (an evening
  capture lists the next morning) counts, and only **one value a day**, that day's largest
  capture (review R5-S3: an early snapshot of a list still growing is no second capture and
  never the day's value). Live: a UTC day **counts** for a list only when that day's own
  read passed every check the rule makes of a list (in a slot shown on the map with a
  recorded healthy share of at least 0.9; not judged stale, the record's `stale`, which
  holds the reader's old empties and its lists of old rows; not a read the replay step
  would drop, its placed share judged against the record's days up to and including that
  day (review R6-S5); not a district site; of a list with 5 captures by then; at least half
  its reference as it stood that day, or, for a thin reference, half the longest read that
  day of a market peer that vouches by the **same** peer-vouch rule the read applies,
  `PeerVouch` in `live_read.py`, which both sides call, with the peer's captures and
  reference as they stood that day: see the thin-reference bullet below) and its own rows
  (the record's `by`) named at least 3 districts under a warning-or-above class at that
  day's snapshot that our map lit closed, remote or delayed, in a slot wholly inside each
  such district's 06:30-09:30 window (review R6-S5); its value is that day's largest such
  read. A day whose timeline is in another directory's school indexes gives no lit
  districts (review R6-S2). That our map lit districts the list carries or
  is proven for is never enough (review R5-B1: four days of a stale 1-row list on mornings
  the map lit three of its districts made a list tier B with a 1-row reference). Counted
  days alone are a list's live captures, its live reference values, its tier B captures and
  its recent days (condition 4); a quiet, advisory or cold day, a stale read, a short read
  or a list that named fewer than 3 warned, lit districts itself never counts. The record
  keeps 45 days, so the live part counts at most those;
- never a list with under 5 captures (archive captures of any day and counted days),
  populated **or empty** (`thin_station`: a list too thin to tell a whole read from a
  partial one is never read; the archive and S7-L refuse only its populated reads);
- never, on a storm day (any class above `none`, advisory included), a populated list under
  half its **closing-size reference** (`small_capture`, a partial list): the median of its
  closing-size values (archive days and counted days), never under the median of the
  archive's alone when they number 5. Quiet days, live or archived, therefore never pull the
  reference down (round-4 review R4-B1: with every archive capture counted, 18 of the 63
  lists with 5 archive captures had a reference of 10 rows or fewer, and a 1- or 2-row
  truncated read on a blizzard morning passed the gate);
- a list with under 5 closing-size values has a **thin reference**: on a storm day a
  populated read of it counts only when it holds at least half of the **longest** read in
  the window of a market peer that vouches (review R5-S1: a short peer never vouches while a
  longer one read a storm-size list). One peer-vouch rule (`PeerVouch`, review R6-B1) decides
  this at read time and for counted days alike: a peer's read vouches only when its slot is
  shown and healthy, the read is not stale (the record's `stale`, or, on a morning its market
  named districts, a populated read naming none), the peer is not a district site, its
  captures reach 5, its own reference as it stood that day is **not thin**, and the read
  holds at least half of that reference. So two thin lists never vouch for each other, and a
  peer reading a truncated page vouches for nothing (round-6 review: with any peer counted,
  two thin lists in one market could vouch each other into tier B with a 10-row reference
  against a 200-row archive storm day, after which a 6-row read labeled every district it
  did not name open; tests P1 and P2). A vouching read is never empty and holds at least half
  a reference of populated reads, so an **empty** read of a thin list is never whole on a
  storm day (0 rows is not half of it). Otherwise it is `small_capture` for every district it
  would read: the closed ones too, since dropping only the unnamed districts of such a read
  would tilt the labels toward closings;
- never a populated list the reader judged from old rows, on any morning: its rows give
  dates and none of them is on or after the day before (a row with no date of its own is
  dated by when the list first posted it, so a row left up since an earlier storm counts;
  `stale_populated`; the live record's
  `stale` holds it from 2026-10-31, judged from the rows' own dates, never from what
  closed); and never, on a warning-or-above morning, a populated list that names no district
  for the day while another list of its market names districts for it (`stale_populated`,
  lead ruling B1.3: a list still holding the day before's rows);
- never, on a storm day, an empty list no other list of its market read with
  (`empty_uncorroborated`); only a peer whose read passed every gate in a healthy slot
  counts (a thin or unhealthy peer corroborates nothing);
- never an empty the reader judged from old rows: a list typed by hand not changed for 36
  hours, old posts or undated page text (`stale_empty`; only a page that says it holds
  nothing now is a whole empty read).

The read set is computed from the morning record's reads, prefixes, withheld states, stale
empties and healthy shares, the coverage, the change log before the day, the district's
class at the snapshot, and the earlier days' snapshots and maps only; on a warning-or-above
morning also whether each list named any district for the day (`stale_populated`), never
which. Then what the lists named and what the map lit are joined. A read district is `no_school` or `delayed` (lit at least
half), `unknown` with why (named for the day anywhere in the day's record and not lit, lit
in part, retracted, a likely break, or dark in a storm while half its market closed), or
`unnamed`: read, named by no list all day, and **dark**: not one of its schools lit with
any status (one lit school with no list naming the district, an override or a closing lit
on an earlier log day, makes it `unknown`, `partly_lit`). **An unnamed district counts as
open** (the owner's O5). Every alerted district (a class above `none`) gets a row, read or
not, with why not (`not_covered`, `withheld_state`, `no_whole_read`, `dropped_read`,
`voided_empty`, `stale_empty`, `stale_populated`, `thin_station`, `small_capture`,
`empty_uncorroborated`,
`health_unrecorded`, `unhealthy`, `not_recent`: the furthest check any of its lists
passed; `withheld_state` is `no_whole_read` with a window slot left out because a pass
withheld the state, counted apart because lists hold rows mostly on closing mornings, so
withholding may fall more on them: the first mornings after landing measure how often, by
class and by whether the state had closings). The row's `after` is whether the map lit the
district no school on its previous school day, read or not (`null` when that day's
timeline is not known), and `unplaced` whether a qualifying read held rows the matcher
placed nowhere (the district's own row may be among them; the hand audit checks those
lists' unmatched rows for an `unnamed` row so marked).

The morning record keeps each slot's lowest healthy share (`health`), the lists read whole
as an empty judged from old rows or as a populated list whose rows name only days before
the day before (`stale`) and, per day, the districts each list read whole named for that
day (`by`, one run of changes a list) from the landing on (`snowlight.live.morning`). A slot
recorded before has no share, so its reads never count (`health_unrecorded`). The live
head before landing records no `health`, `by` or `stale` at all, so **every day from Oct 25
to the landing labels nothing** (review E-R6-4): 0 read rows, every alerted row
`not_covered` or `health_unrecorded` (and no counted day either, since a counted day needs a
healthy slot and `by`). The first runs' audit is all not read for those 8 to 10 school days,
as expected; the mornings of Oct 27-29 give `not_covered` (below).

**Real slot health** (the round-4 review's count from the public live-read job logs of Oct
26-30, 10:00-18:00 UTC, the slot's share taken as the lowest of its exit-0 passes, as the
record keeps it): of 78 reconstructed slots, 44 reached 0.905 or more, 8 sat at the log's
rounding edge (0.895 to 0.905; the log rounds to 2 decimals, the record keeps thousandths)
and 26 fell below. The median pass share by UTC hour is 0.97 at 10-12Z and 0.92 to 0.94 at
15-17Z, where the share of passes at 0.90 or more falls from 60 of 60 to 31 of 48. Healthy
window slots of 6, by zone, on those days: Eastern 4 to 6, Central 4 to 6, Mountain 4 to 5,
Pacific 2 to 4, Alaska 1 to 2. With the same UTC pattern under standard time (after Nov
1): Eastern 4 to 6, Central 4 to 5, Mountain 2 to 4, Pacific 1 to 2, Alaska 0 to 1. A
district is read when any one window slot is healthy and its list read whole in it, so on
those days every contiguous zone kept at least one healthy slot every morning and Alaska
had none on 3 of 5; the supply and trial figures below assume every list read whole and
healthy, and the health-adjusted figures scale Alaska's by 2 in 5 (storm mornings may run
lower shares: the per-zone healthy-slot counts after Nov 1 are measured after landing). The
registered `named` estimand asks the naming in a qualifying slot, so fewer healthy slots
also bias the registered s low (`named_in_day` is reported beside it).

**Co-listing trials.** On a school day where the map lit a district **no school** (closed or
remote: the registered trials are of closed districts only; a delayed district gives none),
each list that read it whole in the window and had not lit it by the window's end gives one
trial: did its own rows name the district for the day in a slot it qualified in (`named`,
the registered estimand)? Each trial also keeps whether the list named it anywhere in the
day's record of its whole reads (`named_in_day`). The label rule keeps a district from
`unnamed` when any list named it anywhere in the day, so `named_in_day` is the event an
unnamed row's correction turns on, and L3 uses its sensitivity for that; `named` is never
above it, so the registered s is biased low (toward more closings hidden among unnamed
rows; on the Oct 27-30 logs only 2 to 6 of a zone's 6 window slots were healthy, so a naming
outside a qualifying slot is common). The report gives both. A list "lit it" when the change log
holds its lighting or change of one of the district's schools for that day logged before the
window ended, on any log day (a closing announced days ahead counts its lighter out); a list
that lit it only after the window is a trial. `s_A ~ Beta(9 + hits, 1 + misses)` and `s_B ~
Beta(4 + hits, 2 + misses)`, every trial taken as independent (the registered estimator).
They are not independent: one list on one storm morning gives a trial for every district it
read, all decided by whether it carried that morning's closings. So the report gives, per
tier, the distinct dates and lists the trials come from and a **day-aggregated** 90%
interval beside the Beta one (the same prior, each date one observation weighing its share
of hits): twenty trials from one list on one morning give s_B 0.923 (90% 0.824 to 0.986) but
0.714 by date (0.418 to 0.937). G1's tier B check is s_B at least 0.7 over at least 20
closed trials from at least 5 distinct dates (lead ruling B1.5), always logged with its
dates and lists (`not met (1 dates, 1 lists)`). The check can hold while the by-date mean
is under 0.7 (one storm morning of 16 hits from one list and one miss on each of four other
dates: s_B 0.769, by-date mean 0.455, by date 0.222 to 0.697). Lead ruling C5: the G1 line
always prints tier B's **by-date mean** (each date one observation) against 0.7, with its
interval, the number of lists the season's tier B trials come from and the number of lists
that are tier B as of the run, and says `met by trials, not by date` (`tier_b_not_by_date`
in `summary.json`) when the registered check holds and the by-date mean is under 0.7; the
flag is taken from the mean, no longer from the interval's upper end. It is a diagnostic,
not a gate, until **20 tier B lists exist**: the larger of the lists that are tier B as of
the run (`tier_b_lists_now`: proven, not a district site, with 5 closing-size values,
archive and counted days; review R6-S3, since the lists giving trials are never more and
usually far fewer) and the lists the trials come from (`tier_b_lists`). From then on
(`tier_b_by_date_gates`) G1 tier B also needs the by-date mean to reach 0.7, and the line
says `not met: by date` when it does not. A run that labels no day keeps the last report's
`tier_b_lists_now` (`summary.json` schema 6). The other way into G1 for tier B (the
tier-A-only and tier-B levels within the date-block 90% band) is computed by the nightly
scorer, L4.

**The private report** (`reads/summary.json`, rewritten each run after the public audit is
published, so a run cut off while making it has still published the days it labeled; the
log gives its counts and the step's seconds, the co-listing trial totals over all seasons
and the sensitivities over this season, each so labeled; the first line's label counts are
`all seasons`): it covers the current school season (from Aug 1, the one season start of
this piece, as lead ruling C4 sets it for the audiences; each run reads
that season's days only, so its time does not grow season over season, while the public
audit keeps every day). Per tier the trials, hits, the posterior mean with its 90% interval,
the dates, lists and day-aggregated interval, and the `named_in_day` sensitivity with its
interval; G1's tier B check; the alerted rows by NOAA region, class and label; the read rows
by state; and G1's **hand audit**. When the Actions cache lost days the public audit holds,
the trial totals still come from the audit but their dates, lists and hand-audit rows
cannot, so the report says `record incomplete: k days` and never claims G1 tier B met. Each ISO week's draw of up to 50
unnamed rows (by a fixed hash of day and district) is made once labeling has passed the
week (days are labeled in order) and kept in `reads/hand-audit/<week>.json`, never drawn
again, so later rows never push an audited one out. Results are entered by hand in
`reads/hand-audit/results.jsonl`, one line a row: `{"day": ..., "district": ..., "open":
true or false}` (a line that does not read stops the report, never a silent skip). The
report counts the unnamed rows in the record, the rows drawn and audited, the false opens
with their rate and its Jeffreys 90% interval, the rows still to audit, and G1's check (at
least 50 audited, at most 5% false opens). The route by which results reach the record is
L4's (lead ruling B1.6): the record stays in the private evidence store and the Actions
cache, the weekly draw is frozen, and results enter through a private file L4 defines,
merged into `reads/hand-audit/results.jsonl` before this step reads it.

**Files.** Private, in `out/internal/predict/reads/` (its own Actions cache key,
`predict-reads-`, saved right after the step, before the passes, on a run that labeled a
day: the step sets `added` as it writes each day, so a step its 2-minute limit cut off still
saves the days it wrote; kept for good by `predict evidence`, the newest 21 days offered each
run after the snapshots and tables, with what is left of the push's 45 seconds less a
10-second margin, or not at all with under 15 left: kind `labels` key `read-<day>`,
`trials` and `audit` keyed by the day): `rows/<day>.json` (the alerted districts' rows:
label, why, tier, market, lists, first slot, its healthy share, `after`, `unplaced`; and
every district the map lit no school), `trials/<day>.jsonl`, `audit/<day>.json`,
`hand-audit/` and `summary.json`. A labeled day is frozen. A run labels at most 5 days,
oldest first (the morning record starts on Oct 25, 2026, so a first run at an
early-November landing has about 8 to 10 school days to take in, two runs; the rest wait
for the next runs), and reads the morning record and the change log once however
many days it labels. Public, on the live host: `predictions/read-audit.json` (`ReadAudit` in
`pipeline/snowlight/schemas/stats.py`): per day and class, the districts alerted, covered,
read by tier, named, lit, unnamed (and of them read through a list with unplaced rows),
unknown and not read by why (`thin_list` is `thin_station`), the median healthy share, and
the trials and hits per tier. No chance, no level, no list. A day the published audit holds
is never labeled again and never dropped or rewritten, even when the Actions cache lost the
record (a warning says so; the evidence store keeps the day). A published audit that does
not read (a schema change, a broken write) stops the step with an error and labels nothing,
since the days it published could not be told apart; so does a host with no audit once the
record has published one (`reads/published.json`: a wrong prefix or a listing glitch is
never taken for a first run, which would relabel and drop published days). A day is marked
`added` just before its files are written, so a step cut off between the two still saves
the cache.

**The coverage files** (committed, codes and counts only: county FIPS, NCES LEAIDs, the
station ids already public in `config/sources`, capture counts and the closing-size values'
row counts; no date, no name, no text; lead rulings B1.7 and C3). Schema 3:
`data/predict/read-sources.json.gz` holds each county's proven lists, every list's populated
archive captures of any day (the `thin_station` gate) and the row counts of its closing-size
archive days only, one value a day, that day's largest closing-size capture (the size gate's
reference and tier B's captures); `data/predict/audiences.json.gz` each list's districts by
the archive's audience rule (listed on 2 local days), keeping only the pairs last listed in
the current or previous season, from Aug 1 of the season before the build (lead ruling C4,
`--as-of`), with no dates. A file of another schema is refused, never read as this one.
Both are built by `predict read-sources` from the stations' coverage, a match of the whole
archive and the archive's weather classes (under the heavy lock; the Oct 31 17:22Z build,
`--as-of 2026-10-31`, took 1 min 13 s with 4 workers). That build: read-sources holds 2,864
counties, 374 proven lists and 578 lists with 2,896 populated captures, of which 293 are
closing-size; **5 proven lists have 5 closing-size days** (7 had 5 closing-size snapshots in
schema 2: two of them, gray-koln and nbc-owned-kxas, had two snapshots of one storm day);
18,118 bytes. Audiences holds 71 lists carrying 1,884 districts (2,389 pairs) in 6,490 bytes;
the season bound dropped **3,211 pairs** last listed before 2025-08-01 (the archive's last
listing day is 2026-08-13), and 2,168 districts no kept pair carries. It also holds its build
season, a season code (`"season": 2026`, the year of the season's Aug 1; review R6-S4): its
pairs are those of that season and the one before, so from the next Aug 1 (2027-08-01) the
step reads none of them as tier A, logs a `::warning::` and keeps reading tier B, until the
file is rebuilt with `predict read-sources --as-of <day>` each Aug 1 (the season code was
added to the Oct 31 build's file; its pairs are unchanged).

Of the 18,227 deployed districts (`r6/coverage_by_region.out` and `r7/cond4.out` in the
build notes), 1,884 (10.3%) are tier A (22.2% before the season bound), 448 (2.5%) through
two lists or more; 1,836 (10.1%) have a proven county list with 5 closing-size archive days
(tier B from the first run); 3,212 (17.6%) have one or the other (29.1% before).

**What condition 4 allows** (review E-R6-1; `r7/cond4.out`). Condition 4 counts only counted
days as recent, so **before a list's first counted day no district is read through it
alone**: 0 districts are read peer-free until warning mornings come. Until then a district
is read only through a second candidate of the same market that read whole too: **785
districts (4.3%)** have a same-market pair of tier A or B candidates (Northeast 12.7%, Ohio
Valley 5.7%, South 1.5%, Upper Midwest 2.3%, Southeast 0.9%, Northwest 0.7%), and under the
round-7 rule (each candidate with 5 captures, and a thin one only beside a peer that
vouches) **502 (2.8%)** (Northeast 8.5%, Ohio Valley 4.3%, South 1.3%). The 1,836 districts
(10.1%; Northeast 43.2%, Ohio Valley 4.3%, South 1.3%, no other region) with a list of 5
closing-size values are the **non-thin coverage**: they read with no second list only within
14 days after that list's counted day. The run's log line gives how many lists have a
counted day in the 14 days before (`<n> lists with a counted day in the 14 days before`),
the live peer-free reach (round 5: 12.4% non-thin; with every archive capture counted, round
4, 38.1%). Lead ruling C1 accepts low coverage: it never blocks a chance, since L3 serves the
class level with zero label counts.

**How coverage grows over the season** (reviews E-R5-3 and R6-S1; `r7/cond4.out`, the
archive's seasons 2015-2025 as stand-ins, codes and counts only). A day counts only for a
list that already has 5 captures, and only counted days add captures, so **a list with under
5 archive captures never gains a counted day and is never read** (311 of the 374 proven
lists): that is lead ruling C2 read literally, and it is kept, since counting a live day
for such a list on the other checks alone would need its own label-truth argument. A list
with 5 captures and a thin reference counts a day only beside a market peer that vouches
(`PeerVouch`), so a list alone in its market, or among thin lists only, never grows either.
Upper bound under both barriers (every weekday with 3 or more of a list's districts under a
warning-or-above class a counted day, every peer reading whole): the lists with 5
closing-size values reach **5 to 8 by Dec 15** (median 6) and **5 to 8 by Jan 31** (median 8),
against 5 now (round 6 gave 7 to 39 and 33 to 107 without the barriers). Requiring 3 of its
districts closed or delayed in the archive's own labels gave 5 by Dec 15 in every season
(`r6/growth.out`). **Freshness after a counted day** (upper bound, same seasons): a counted
day keeps a list fresh for the next 14 days, at most 10 school days; Nov 1 to Dec 15, 0 to
10 lists were ever fresh (median 2), for a median of 0 to 11 school days each (at most 15 of
29 to 31), and the advisory district-days a fresh list of 5 closing-size values reads with
no second list number 0 to 996 (median 60; 0 in 5 of 11 seasons). Each run that labels a day
logs `counted live days through <day>: <n> days of <k> lists; <m> lists with 5 closing-size
values, archive and live (lead ruling C2), <t> of them tier B; <f> lists with a counted day
in the 14 days before`, which the first weeks measure.

**The size reference's spread** (review R5-S3; `r6/s3_ratio.out`): the 5 lists' reference
(median) against their largest closing-size value: abc-owned-wabc 32 of 239 (0.13; days of
14, 27, 32, 74 and 239 rows, five different days, so one value a day does not lift it),
nbc-owned-wbts 217 of 588 (0.37), nbc-owned-wvit 480 of 853 (0.56), nexstar-wdaf 168 of 263
(0.64), scripps-kshb 98 of 128 (0.77). On a storm morning a wabc read of 16 rows or more
passes the size gate. Counted live days (each the day's largest read, at least half the
reference as it stood) raise it as storm days come; the first post-landing storm days
measure each list's live values against its archive ones.

While either file is absent `read-labels` labels nothing and freezes nothing (a day labeled
without them would be frozen `not_covered`), and says so.

On Oct 27-29 the five advisory district-days give `not_covered` with the committed files
(5305020 twice, 5308430, 3000654 and 3009510: no list carries them in the archive audiences,
and their counties' proven lists have under 5 closing-size days; `r6/oct27_29.out`). That
rests on the coverage files only, so it holds whatever the lists read those mornings, unless
a list lit one of their schools on 2 live days before (the live audience); the first run
confirms it. The round-4 docs gave Stehekin `health_unrecorded` from a SYNTHETIC window;
that was a prediction, not an outcome.

**Lead rulings (Addendum B1, Oct 30, and Addendum C, Oct 31; decided conservatively: when in
doubt a read does not label a district open).**

1. Closing-size captures set the size gate's reference (B1.1), by one test for the archive
   and the live record (C1, C2; `closing_size`): the list's own rows named at least 3
   districts under a warning-or-above class. C1 confirms the archive rule as built (rule
   (a): warned on the capture's local day or the next) and rejects counting advisory-day
   captures (a') and taking short medians as thin (b): a quiet-day or advisory-day size is
   not a storm-day size, and a weak reference lets a truncated storm read label unnamed
   districts open. Low tier B coverage is accepted; it never blocks a chance, since L3
   serves the class level with zero label counts and coverage grows over the season from
   counted live days. C2: a live day counts (as a closing-size capture, a reference value,
   a `thin_station` capture or a recent day) only when the list's own read that day passed
   every check, was not stale and itself named 3 warned districts our map lit; that our map
   lit 3 warned districts the list carries is not enough. The critic's probe (a list with
   four stale 1-row days) gives `not_covered` or a thin reference, never tier B (tested).
   The archive keeps one value a closing-size day (review R5-S3), as the live side does.
2. A thin reference (under 5 closing-size values) reads on a storm day only beside the
   longest market peer whose read vouches for its length (at least half of it; review
   R5-S1) by the one peer-vouch rule the read and the counted days share (`PeerVouch`,
   review R6-B1: never a thin, short, partial, stale, unhealthy or district-site peer), and
   an empty read of it never; otherwise `small_capture`. The ruling allows named labels from such a read; the rule takes none,
   so the read set stays outcome-blind.
3. `stale_populated` as above; populated lists of old rows, on any morning, are refused
   under the same reason.
4. The capture unit: a live day counts toward a tier B list's 5 captures only when it is a
   counted day (C2). The station gate (`thin_station`) counts the archive's captures of any
   day and counted live days only; a live day with a populated read that was not
   closing-size by the list's own rows no longer counts there (until round 5 it did).
5. G1 tier B also needs 5 distinct dates (B1.5). C5: the G1 output reports tier B's by-date
   mean against 0.7 as a diagnostic, `met by trials, not by date` when it is under, until
   20 tier B lists exist (the larger of the lists tier B as of the run and the lists the
   season's tier B trials come from; review R6-S3); from then on G1 tier B needs it too.
6. The hand-audit route is L4's.
7. The coverage files are committed, codes only; no owner approval is needed (B1.7). C3:
   the closing-size captures' row counts are numbers, not text, and are kept; no dates,
   names or list text. C4: the audiences keep only the pairs listed in the current or
   previous season (seasons begin Aug 1); older pairs are dropped at build time, so the
   file holds no dates. The build logs the number dropped (above).
8. The 16 MB morning-folder valve risk is accepted as documented in `docs/live.md`; the real
   storm-day sizes are measured after landing, and `morning.py` does not change here.
9. Supply: the k about 26 posterior rests on the prior through most of November in about
   half of seasons. Under the C2 and C4 files and condition 4 it does so through November 20
   in **8 to 9 of 11 seasons** (review E-R6-2; the two-list bound below). On the archive's
   seasons 2015-2025 (every list read whole and healthy: upper bounds; `r7/cond4.out`,
   `r6/supply.out`, `r6/trials_expected.out`), before any counted day a district is read
   only through a same-market pair, tier A included (condition 4): its advisory
   district-days of Nov 1-20 reach 26 in 3 of 11 seasons and 300 in 2 of 11 (0, 0, 1, 526,
   324, 1, 0, 251, 12, 0 and 16 district-days), and under the round-7 peer-vouch rule 26 in 3
   of 11 and 300 in 1 of 11 (323, 145 and 196 in 2018, 2019 and 2022, none in the other
   seasons). Two whole lists of 5 closing-size days reach 26 by November 20 in 2 of 11
   seasons and 300 in none. The round-6 figures through any list with 5 closing-size days (26
   in 5 of 11, 300 in 3 of 11) and through any tier A or B list (26 in 8 of 11) left
   condition 4 out and are superseded. Once warning mornings give counted days, a fresh list
   of 5 closing-size values reads with no second list (above: 0 to 996 advisory
   district-days Nov 1 to Dec 15, median 60). Alaska's 2 healthy mornings in 5 change none of
   these. The expected tier B co-listing trials by December 15 reach 20 in 1
   of 11 seasons at the prior's central rates (4 of 11 at the band's high edge) and never
   from 5 dates; 6.3% of the (district, list) pairs in counties with two such lists are tier
   A pairs, whose trials go to s_A and are not counted there. Counted live days add lists as
   warning mornings come (above). The served number stays the class level's prior-based
   value until labels come (Addendum B2), which is correct, never stale.

## Each district's own record (each-school P2a1: a record, nothing served)

The owner's ruling: each district's own record, whether it tends to close early or hold out,
is the spine of the prediction. The record starts here, from every live school morning. **It
changes no number:** no pass, refit or published file reads it (a test holds every serving and
learning module to that), and nothing is published.

**The job.** `.github/workflows/each-school-record.yml` (workflow `each-school record`), once a
day at 18:43 UTC, on its own concurrency group, outside the serving chain (predict.yml is not
touched). It restores the read labels' record (the predict chain's `predict-reads-` cache) read
only and saves no cache of any kind (setup-uv's own cache is off, since the repository's cache
room is shared with the predict chain's); a run whose restore missed writes no live morning
and says so (the past records' step, below, runs either way). It reads the deployed directory as the serving pass does and each day's timeline and the
day index from the live host's public files, then runs `snowlight predict each-school record`
(`snowlight/predict/record.py`): every labeled day the evidence store does not hold yet (the
newest 10 a run; the older ones are counted and wait) whose map is known for good becomes one
record day, kept in the store's `record` kind (only this workflow may write it) and never
written again. A day whose timeline (or the previous school day's) is not final, answers an
error, or is missing while the day index lists it, waits; so does a day of another directory or
whose read day does not read (only the error's kind is logged). A missing timeline means the
map lit nothing only once the index, written after the day was over everywhere, does not list
the day (labels' own rule). A day still left 7 days after the newest labeled day is a
`::warning::`. It then writes `out/internal/predict/record.parquet` from every kept day but the
take-back days and rows (`learn.excluded_days`, `learn.excluded_rows`), in the runner only. One
log line a day says its rows by call, how many came from the read labels and how many from the
map alone, the weather days, those for a stated cause that is not the weather, the days after a
closing, the read calls the 09:30 map does not give, and the fit-usable rows.

**A row** is one district's morning: codes, ids, counts and times only (each day's bytes are
checked before they are offered, and the store checks again). A read row's market is kept as a
code (`m` and 12 hex digits of the sha256 of the registry's market text), never its name.
- **Which districts.** A district whose read row is labeled `no_school` or `delayed`, or
  `unnamed` while the map lit none of its schools at 09:30 or later that day, is a *live read* row:
  `source_complete` true, `closings_only` false, scope whole. Any other district the map lit
  closed, remote or delayed at one of its eligible schools at 09:30 is a *live map* row:
  `source_complete` false, `closings_only` true (the map shows what lists named, so a district
  it did not light is not known open). That takes in every no-alert closing, every closing no
  list read whole, every closing for a stated cause that is not the weather, and a district a
  read called `unnamed` while the map lit it (its label kept in `read`). A district the map lit
  only after 09:30 is a live map row too, its call from the day's last change, `agrees` false,
  and never a weather day.
- **The call.** `closed`, `remote` (every school lit no school was remote), `delayed`, or
  `unnamed` (a read list did not name it; never written `open`, since a list misses closings
  at its sensitivity). It is read from each school's status at the read window's end
  (`labels.read_until`, 09:30 local), not the day's last change: lists clear their rows in the
  afternoon (every one of Nov 4's 27 statuses was taken back after 13:00 local), and a status
  taken back before 09:30 counts as none. An early dismissal is no morning call. A read row
  takes the 09:30 map's call when it is of the label's kind and whole (`agrees` true); else
  (posted after 09:30, or changed later) it keeps the label's kind of call with `lit`, `cause`
  and `reasons` from the day's last change, `agrees` false, and is no weather day. Every row
  carries `map_call`, the 09:30 map's own call for any reason and of any scope (`null` when it
  lit nothing), so a row that does not agree shows both. `taken_back`: a school lit with a
  morning call at any change of the day shows no status at the day's end.
- **Class** at the read day's snapshot: `advisory`, `warning` (warning or above, tropical
  included, as the serving classes name them), `cold`, `none`, or `unknown` (the read day holds
  unclassed districts and this one has no row there); the class number and situation beside.
- **Day after.** `after`, the flag a page filters on, true to the map: on the previous school day
  the map lit no school (closed or remote, any reason or none) at at least the no-school share
  of its eligible schools at 09:30 or at that day's last change (a closing posted after 09:30
  is a closing), or its read row that day was labeled `no_school`, or `after_weather` is true
  (a closing for the weather is a closing; the row model refuses `after_weather` true with
  `after` not true). `after_weather`: labels.py's
  flag, for the weather only, which the situations use; `situation` is made from it. Either is
  `null` when not known (no previous map: the host holds no timeline of a day older than every
  day its index lists; or no previous read day), and `situation` is then `null` for a class with
  an after situation.
- **Cause and weather days** (owner ruling, Nov 13: every real closing is shown with its
  reason, and the snow-day prediction never learns from a closing that is not for the
  weather). A school's reasons are read at every change of the day with a morning call, not
  only at 09:30: a status naming no reason at 07:00 and a power outage at 10:00 was a closing
  for a power outage (Oct 26 2026 held same-status reason changes). `cause` is `named` and
  `weather_day` false when any of the district's eligible schools names a cause that is not the
  weather (heat, a power outage, any code above 7) with a morning call at any change of the
  day. Otherwise `weather_day` is true only when the schools lit for the weather at 09:30 (a
  weather reason named, or none named on an alerted morning: labels.py's rule) reach the call
  on their own by the label rule's shares; `cause` is then `weather` (a reason named) or `any`
  (none named). Else `cause` is `weather` when only weather reasons are named (a tropical
  reason on a day that is not tropical), else `any`, and `weather_day` is false. A read row is
  held to the same rule, whatever its label. `reasons` keeps every code the district's schools
  named with a morning call that day. The row model
  refuses a weather day with a `named` cause, nothing lit, no morning call, or no agreement.
- **Fit use.** `weather_day` is not a fit filter. `fit_usable` is: `source_complete`, scope whole,
  `agrees`, no `named` cause, not tropical, `after` false and `after_weather` not true, nothing
  taken back, and a weather day or `unnamed` (spec rules 6, 6b, 10 and 13, as far as the rows
  can say; held-out checks and the hand audit come on top). The row model refuses any other
  value.
- **Scope**: `whole` when the label rule's shares give the call, else `share` (`lit` of
  `eligible`, the district's deciding schools). Also kept: the read row's tier, market code,
  list ids and first slot, its label and why when it did not decide the call, and `tropical`.

**Gate.** None serves: the record is evidence only. No learned value, served chance or published
byte changes (the live score's sha256, the golden files, the storm drill's lines and the alerts
digest are unchanged). Its weather fields (observed snow, `snow_seen`) come with P2a2; what a
page shows comes with P2e.

## Past records (each-school P2d, R1 Kentucky: a record, nothing served)

Public state records of past school days give a district's record the winters the live map
never saw. They are written into the same record as their own coarse kind, `past_records` (a
page may say a day was seen live by us or comes from past records, never which agency's file:
LR8). **They change no number:** no pass, refit or published file reads them (the same test
holds every serving and learning module to that, `state_records` included).

**The files** (`pipeline/config/state-records.yaml`): each by URL, the page that links it, fetch
date, size, SHA-256 and parser version. Kentucky's Department of Education school calendar page
gives, by plain GET:
- the **Amended Calendar Summary** of 2024-25 and of 2025-26 (one row per district): its
  dated weather days (code `W`: days missed for the weather and made up), dated illness (`I`)
  and district-wide emergency (`D`) days, its count of at-home NTI days used (`N`, not dated),
  and its own calendar (first and last student days, every dated day off);
- the **Five Year Weather Trend**: each district's weather make-up days per school year,
  2020-21 to 2024-25.

**The step.** `snowlight predict each-school past` (`snowlight/predict/state_records.py`), the
last step of the `each-school record` job, whether or not that run had read labels. A state
whose record keys the store holds already is not fetched again. Otherwise each file is fetched,
refused unless its size and SHA-256 are the pinned ones (a changed file needs a reviewed pin),
read (the summaries by column header, never position; the trend by a small reader of the PDF's
text runs, a page's content streams joined in order), checked, and its keys offered once:
`past/<file id>/v<edition>/days` and `past/<file id>/v<edition>/counts` in the `record` kind.
The record is append-only and a key is written once, so each file's rows carry its reviewed
`edition` and the SHA-256 of each key's bytes is pinned in the config (`written`): a build whose
bytes differ from the pins (a parser, model, map or exception drift) is refused and warned of,
never written. A reviewed change to a file's rows bumps its edition and its pins and writes new
keys beside the old; the record job reads only each file's newest edition, and a past key whose
name or rows do not read is warned of and left out, never the whole record. A state that fails
any check writes nothing and is warned of. The record job's `record.parquet` then holds the past
rows beside the live ones (the columns a past row lacks left empty, plus its `code`), and
`record-counts.parquet` the yearly counts, both in the runner only.

**The written map.** `W` (Weather Day) becomes a dated row: call `closed`, cause `weather`,
`weather_day` true, scope `whole` (the district's own calendar), `closings_only` true and
`source_complete` false, since a day not listed is not known open (an NTI day at home is not
dated, and a weather day not made up is removed from the amended calendar), so it is never
fit-usable (spec rule 6; rule 9's statewide slope is a serving piece's own filter). Its class is
`unknown` until a backfill or P2a2 fills it (LR14): counted in the step's lines as unknown, and
never fit-usable. Its day-after flag comes from the district's own calendar in the same file:
`true` when its previous scheduled student day is a listed `W` (`after_weather` true), `I`
(`after_weather` false) or `D` day (`after_weather` not known); otherwise not known (that day
may have been an NTI day). `N`, `I` and `D` are kept as yearly counts only. Every count stays a
count, never spread into dates: `W` for 2020-21 to 2023-24 from the trend and for 2024-25 and
2025-26 from each summary; `N`, `I` and `D` for 2024-25 and 2025-26. COVID years (2020-21 here)
are kept and flagged `covid`; a district-year with a `D` day is flagged `disaster` (spec rule 8).
`D` is counted from its dated days: the file's own `D` total reads 0 in 11 of the 12
district-years that list `D` days (the twelfth, 8 days, agrees).

**What `W` means, and the days it carries that are not the weather.** A `W` count is the
weather days a district *made up*: a weather day not made up is removed from the amended
calendar, so it is not a count of weather closings. And the state's weather code can carry a
closing for another cause. A review on Nov 14 2026 checked three windows of the dated years
against each district's own notice and local news: every `W` day outside December to
mid-March; every `W` date held by three districts or fewer; and every `W` day from 2025-02-03 to
2025-02-14, the week a wave of flu and other illness closed many districts. `W` days held by
four districts or more inside December to mid-March (the big storms) were not checked one by
one. The review writes two lists in the config:

- `not_weather`, a closing for another cause: 7 days (Jefferson County, 2025-11-05, a
  shelter-in-place order after an aircraft crash nearby; Bullitt County, 2025-08-19, a city
  water main break, and 2025-02-05 to 02-07, closed for illness in the flu wave; Letcher County,
  2026-02-12 and 13, closed with no water after a leak drained the town's tanks). Such a row
  keeps the state's code `W` but has cause `named` and is never a weather day (LR12), and the
  next school day's day-after flag reads it as a day off for a named cause.
- `unconfirmed`, a checked day the review could not tie to the weather for that district (no
  notice or report found that ties it to the weather): 40 days, 29 of 2024-25 and 11 of 2025-26.
  Such a row keeps the code `W` with cause `any` and is never a weather day either; the next
  school day's day-after flag reads it as a day off of a cause not known. A later review that
  ties one to the weather moves it out in a new edition. One of them may be the state's own
  year slip: Jackson County's 2026-01-23 is the only `W` that day, and its 2024-25 row lists
  2025-01-23 and 01-24. The row stays as the state lists it.

The other checked days were tied to the weather (the Helene windstorm and its power cuts of
2024-09-27 to 10-02, the first snow of 2024-11-22, the high water of 2025-02-06 in the
northeast, the snow of 2025-02-11 and 12, the February and April 2025 floods, the snow of
2025-11-10 and 11 and of 2026-03-17). A year's `W` count stays the state's number, and its
`not_weather` and `unconfirmed` say how many of those days each list names, so the weather days
known are `days - not_weather - unconfirmed`. An undated count (the trend's years) cannot be
checked: both read `None` there, never `0`. A listed day the files do not list, or a day in
both lists, refuses the state.

**Internal names.** The past rows' fields `source_kind`, `source_complete` and `sources` follow
the live record rows'. They stay in the evidence store and the runner's `record.parquet`
(neither is published); the published shard (P2e) maps them to its coarse two-value `seen`
field (seen live by us, or from past records) and never carries these names (LR8).

**Ids, never guessed.** The state's three-digit district number is digits 7-9 of the NCES
`ST_LEAID` (`KY-CCCddd000`), written once into the config as a number-to-LEAID table from the
CCD LEA directory 2024-25. 171 of the files' 172 numbers map to a district of the directory; 606
(the Model Laboratory School, whose CCD LEA is an education agency of another type and not a
district of the directory) is listed and not matched. A number in neither list refuses the
state.

**Checks** (each refuses the state): every summary row's `W` and `I` counts equal its dated
days; the trend's 2024-25 counts equal the 2024-25 summary's in every row (172 of 172); every
date reads and lies in its file's school year; no date comes twice in one cell; no district
number comes twice. A `W` day that
is not a student day on the district's own calendar is listed and not written (4 of 1,603
mapped: three of Green County's, in May 2026 after its last student day, and one of Hardin
County's); its yearly count stays the state's.

**What it holds** (fetched Nov 14 2026, edition 1): 817 dated `W` rows over 143 districts in
2024-25 (785 weather days, 3 another cause, 29 unconfirmed) and 782 over 148 in 2025-26 (767
weather days, 4 another cause, 11 unconfirmed), so 1,599 rows, 1,552 of them weather days and
643 the day after a day off school; and 2,052 yearly counts (`W` 817 and 786 days in the
summaries' years, of them 3 and 4 not the weather and 29 and 11 unconfirmed, and 1,072 over
2020-21 to 2023-24 in the trend's; `N` 1,351 and 1,328; `I` 14 and 11; `D` 21 and 9).

**Gate.** None serves. No learned value, served chance or published byte changes (the live
score's sha256, the golden files, the storm drill's whole lines and the alerts digest are
unchanged). What a page shows of them comes with P2e; whether they may move Kentucky's numbers
is a serving piece's own gate (SPEC r5).

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
less what is already over (whole periods, and the elapsed part of the period under way, below);
apparent temperature is read at 7 AM local. A district's value
is the one at least half its deciding schools reach (the class's rule), and its bucket is
one of 0 quiet, 1-5 snow (0.5, 2, 4, 6, 9 inches), 6-8 ice (0.01, 0.10, 0.25 inches), 9-12
feels (10, 0, -10, -20 F or colder), 13 unknown.

Every snow and ice message holds a whole 6-hour period, the period under way included. The
first message of a run is stamped from the run's reference time, but its values are the
whole period's: measured against the same period in the last run before the period began,
cell by cell where it held 1 inch or more (0.1 inch of ice), the median ratio stays 1.00
however late in the period the run comes (8% of the period left on 2025-01-06 snow, 2022-02-03
ice; 42% on 2019-01-19 snow and 2018-10-14 snow). So a message of the period under way holds
snow before the run too, and the window counts that period only for its share still to come at
the time asked (as of: the class snapshot, 9 PM the evening before, or the pass if earlier), at
an even rate through its 6 hours, the forecast giving no finer split: a run read at 03Z counts
half of the 00-06Z period, and nothing of a period already over (SF-R5-1, fixed in
advisory-sane L5: counting the period whole said "overnight" and "by 10 AM" of snow already
down, 71 of 85 Mountain lines on 2023-02-23). The overnight part of the words is counted the
same way. The stored history (2018-19 to 2025-26) was collected before the fix, with the period
under way whole; a rebuild counts it the fixed way. Spec-f section 4 had assumed the part after
the reference time; pieces F2 and F3 name the period's start. NCEI's files stamp the periods
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

**Kept past 90 days** (each-school P0). The same workflow's `keep` job runs on its own two
monthly schedules (10:41 and 10:47 UTC on the 2nd; `KEEP_CRONS` in `forecast_history.py`), and
the backfill never runs on either. For `forecast-history` and `label-night-forecast-extract` the
first run keeps the newest copy and the second the pinned copy the committed model learned from
(`KEPT_PINS`: manifest SHA-256 77b684fe of run 39748984910, and 4a58d614 of extract run
40262501880), so a newer backfill never lets that copy expire; a run holds one artifact of a
name, hence two runs. A copy is taken only from this repository's own runs on its default branch
that succeeded: a run of the workflow that makes it (on push or by hand), or a keep run whose
keep job for it succeeded. A copy from a fork, another branch, another workflow or a failed run
is passed over, and so is one whose run does not read. Each copy taken has every file checked
against its `manifest.json` SHA-256 (a copy with a missing, extra or changed file is passed over
with a warning, and the next older one tried), is uploaded again under the same name for
another 90 days, and is read back: the run fails unless the kept copy's manifest SHA-256 is the
original's. A staged copy whose manifest differs is refused before anything is uploaded. Each
schedule has its own concurrency group, so a pending keep is never dropped behind a running
backfill. It reads and uploads only: nothing is deleted, committed or published, and the serving
workflow is not touched. Three runs fall within an artifact's 90 days, so one missed month loses
nothing.

**The record kind** (each-school P0). The evidence store (docs/live.md) gains kind `record`, each
school's own record, one day a key. Only the daily record job writes it (each-school P2a1,
workflow `each-school record`; "Each district's own record" above). It holds codes, ids, counts
and times only. The writer refuses, before anything is written, a version whose bytes hold `://` or
`www.` (a backstop: the record job checks its decoded rows too), and a push after which a
database would hold over 2 MiB raw of one day (every version of it together) or over 30,000,000 B
stored in the kind, counting every record version either database holds and the ones offered.
The cap is under a tenth of the 313,840,866 B left under the 300 MiB warning when each database
held 731,934 B (Nov 13 2026, live-read run 43431486056).

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

## Inputs for the tuning candidates (calc-data lane: data and checks only)

Nothing on the site changes with this lane, and `predict.yml` serves exactly as before. It
gathers, as known at 21:00 the evening before, what the tune lane's candidates read (7 AM
temperature and the rain/snow line, when the snow falls, alert start, end and words), checks
two possible leaks in today's labels and history, and adds report-only checks to backtest v2.
The archive's labels come mostly from big storm days, so a backtest on them can veto an idea
that hurts but cannot show one helps; turning anything on waits for live labels.

**The label audit** (`snowlight predict label-audit`, internal, heavy lock). The labels build
each station's audience (the districts it listed on 2 or more days) and its gates (populated
captures, median rows) and the markets from the whole archive, later seasons included. The
audit rebuilds them, for each test season, from the listings and reads before it, relabels the
seasons before it and counts the training labels that change. On 2026-10-25 every fold changed
far more than 1% of its training labels (11% in 2025-26 to 100% in 2016-17 and 2017-18; mostly
a known label that has no row or is unknown when only earlier seasons are counted), so the
walk-forward backtest's training labels depended on later seasons' lists. The served fit, which
counts every past season, is not affected in kind.

**The per-fold rule** (the lead's decision of 2026-10-25). `predict label-audit` also writes each
test season's fold labels (`folds/labels-before-YYYY-07-01.parquet` and the private schools'
`labels-private-before-YYYY-07-01.parquet` in the labels folder, with `manifest.json`: rows,
known labels and SHA-256 of each; `labels.fold_label_days` builds them, and
`tests/predict/test_labels.py` fails if a fold's labels move when a later season's listings or
reads are added, through each channel: audiences, station captures, median rows and markets;
`test_fold_labels.py` runs `train.run_labels` and `run_private_labels` on a stand-in archive). `predict backtest` and `predict terms` read them by default
(`--labels-rule fold`): piece 1's folds, every row's walk-forward base, the terms' folds and
the private report's named-days table fit only on the labels of their own fold
(`backtest.walk_forward`, `backtest.chances_on`, `backtest_terms.base_by_season` and
`walk_forward` with `training`; `tests/predict/test_fold_labels.py` fails if a fold reads
another fold's or the whole archive's labels), and the test rows stay the whole archive's
labels. A missing fold file stops the run rather than fall back. Known training labels by
fold: 67 for 2019-20, 188, 319, 405, 647, 1,419 and 1,825 for 2025-26 (the whole archive's:
438 to 2,049). The served model, the served terms and every served chance are unchanged: a real
pass on 2026-10-25 wrote the same file with the code before and after, bar its `generated_at`,
and the serving model's every rate hashed the same.

Old and new, for each headline number (the earlier rule re-run with the new code reproduces
every earlier figure):

| figure | whole archive's labels | per-fold labels |
|---|---|---|
| piece 1 storm rows scored | 1,385 | 1,208 (177 of 2020-21 unmodeled) |
| piece 1 storm Brier against B0 (pooled G1) | 0.1090 against 0.1188, pass | 0.0612 against 0.0974, pass |
| the same, on the 1,208 rows both score | 0.1166 against 0.1267 | 0.0612 against 0.0974 |
| piece 1 all rows against B0 | 0.0774 against 0.0844 | 0.0418 against 0.0665 |
| G1, 2023-24 (567 storm rows) | +0.0117, over the tolerance | -0.0107, within |
| G2 | pass | fails the 0.8 to 0.9 bin |
| G3 (caught at 50%, B0) | 91.4%, 98.1% | 98.4%, 100% |
| advisory no-school rate of the training labels, 2019-20 to 2025-26 folds | 0.77, 0.77, 0.77, 0.77, 0.61, 0.74, 0.74 | 0.13, 0.76, 0.74, 0.75, 0.74, 0.70, 0.72 |
| advisory test rows' mean chance, 2022-23 (140 rows, 26% closed) | 77% (Brier 0.450) | 37% (Brier 0.196) |
| advisory test rows' mean chance, 2023-24 (216 rows, 99.5% closed) | 59% (Brier 0.188) | 81% (Brier 0.047) |
| private storm Brier against B0 | 0.0802 against 0.0820 (251 rows) | 0.0711 against 0.0771 (169 rows) |
| backtest v2 storm Brier, base to terms | 0.10898 to 0.11580, 6.3% worse, fail | 0.06122 to 0.05814, 5.0% better, pass |
| backtest v2 checks: vetoes | pooled 6.3% worse; advisory 4 to 6 in, Northeast | none |
| P5, 90% interval of the Brier difference | -0.002 to +0.022 | -0.005 to -0.001 |
| P8, base and terms without 2016-02-16 | 0.118, 0.116 | 0.102, 0.102 |
| P8, the other dates (base, terms without each) | from the served terms: 2020-12-17 0.115, 0.122; 2019-02-06 0.092, 0.103; 2024-01-22 0.109, 0.116 | from the fold fits: 2023-03-14 0.124, 0.124; 2024-01-22 0.062, 0.060; 2023-02-28 0.061, 0.058 (the served terms' dates gave 0.071, 0.068; 0.102, 0.080; 0.062, 0.060) |
| within-day ranking, every market-day (base, terms) | 10 market-days: 0.840, 0.858 | 9 market-days: 0.846, 0.847 |
| within-day ranking, without the 4 split days; the split days alone | 0.856, 0.856 (6); 0.838, 0.859 (4) | 0.901, 0.905 (5); 0.839, 0.839 (4) |
| Pembroke Hill 2025-02-18 (no school), named-days table | 95% | 94%, as the named cases give it |

The per-fold labels drop the rows that existed only because a later list named the district,
mostly no-school days, so the earlier folds train on fewer and quieter rows. Both the base and
the terms score better on the archive's storm-picked labels, which can veto an idea but not show
that one helps; the terms' gain is raised chances on alert days and leans on 2016-02-16, so
nothing turns on from it.

**Alerts as known at 21:00** (`snowlight predict alert-streams`, then `alert-classes`;
`pipeline/snowlight/predict/alert_streams.py`). IEM's VTEC event record holds each event's
first product and every follow-up with its issue time. For a zone at the snapshot, only the
products issued by then count; the latest one that names the zone states the start (its VTEC
begin, or its issue time when the event is already in effect, as the live path reads onset or
effective), the end and the words; a CAN or UPG withdraws the zone from its issue time (rule
D2). The type flags (snow, sleet, freezing rain, freezing drizzle, rain, mix, ice) and the
elevation band (`sources/nws/elevation.py`) are kept, never the text. The fetch asks one record
a second with the site's User-Agent, caches under `pipeline/.cache/predict/vtec-events/`
(gitignored), takes the events whose recorded span can meet a label night's window first, and
keeps the cached records of its events within the cap (`--cap`, 100 MB by default): it asks for
no more once the room left is less than the largest record seen, and a record that would still
pass the cap is dropped, not cached. (The first run, before that rule, stopped one record past
the 100 MB cap, at 100,018,036 bytes; the lead's raised cap of 112,000,000 bytes holds every
record.)
`alert-classes` gives every district on the label dates its class by the history's rule and by
the streams, and checks that the history side equals the labels' own class.

On 2026-10-25 the fetch took all 2,606 event records of the 58 label dates (2,606 requests over
three runs, no errors, 111,117,979 bytes cached; the lead raised the cap to 112,000,000 bytes
for the last 252). With every stream read, the history side equals the labels' class on all
2,388 known labels. A later product moved a zone's start across 09:00 on 61 zone-days (later)
and 156 (earlier), none of them a labeled district-day, so that leak changes no label's class.
As of 21:00, 59 of the 2,388 known labels (2.47%) take another class from the streams than from
the history. These training labels carry a class that was no longer current at 21:00 the evening
before, all from products issued before the snapshot (none from a later one):

- 54 (all no school, all in the Kansas City market) on 2018-11-26 the history counts as
  blizzard days: the Kansas City office (EAX) cancelled its blizzard warning for zone groups
  there at 19:27 and 20:55 CST, before the snapshot; read product by product, the streams hold
  no class-making alert in force for these districts at 21:00, while the history's season rows
  still do.
- 4 (all open) on 2023-03-14 the history counts as winter storm warning days: Mount Holly
  (PHI) had replaced the warning for NJZ008 with an advisory (WW.Y NEW) at 20:30 EDT.
- 1 (open) on 2019-02-04 the history counts as a day with no alert: Seattle (SEW) had extended
  the WAZ503 advisory at 15:36 PST to 22:00, past 21:00, where the first product ended it at
  18:00.

Whether these labels are relabeled is rule D2's call (S7-F, lane F2): the training labels keep
the history's class until then.

**The label-night forecast extract** (`.github/workflows/label-night-forecast-extract.yml`,
`snowlight predict night-extract`; `pipeline/snowlight/predict/night_extract.py`). For each
(school day, time zone) of `pipeline/config/label-nights.yaml` (56 nights from 2018-19 on), every
district whose own zone reaches 21:00 the evening before at that instant: snow, ice and liquid
per 6-hour period, the 12-hour chance of precipitation (GRIB template 4.9, now read by
`ndfd.py`), air and apparent temperature at 5 to 8 AM local, the snow and ice window totals as
the forecast history keeps them, and the hourly NDFD weather strings (decoded from the files'
section 2; each district's most common string among its schools, a tie going to the string
first in that hour's message table) from 9 PM to noon. Snow, ice and apparent temperature come from the run the forecast
history's 21:00 sample uses; temperature, the chance of precipitation, liquid and the weather
strings each from that element's own newest file that counts by 21:00. Each file's stamp,
reference time and availability are kept, and the job fails if any counts after 21:00. A run
is made of snow, ice and apparent temperature files alone, so another element's file never
completes one or moves its time. NCEI holds no complete run within three hours of 21:00 on
2018-11-26 (Central; none from 23:47 to 04:17 UTC) and no liquid or weather file then, so that
night keeps air temperature and the chance of precipitation only, with the rest named in the
manifest's errors. A dry
run of two nights (2019-02-06 from NCEI, 2024-01-16 from AWS) matched the forecast history's
21:00 codes for all 7,191 districts of each night. The readers were checked against eccodes
2.49.0 on the first message of each file of the 2024-01-16 01:48 UTC run (chance of
precipitation, liquid, temperature, weather): every head key and every decoded grid agree, and
the weather table holds 315 strings, one more than the largest grid index. Those messages'
sections 0 to 4 are test fixtures (`pipeline/tests/predict/fixtures/ndfd/`, with the eccodes
keys). eccodes gives the first chance of precipitation message's step as 0-12 from its 02 UTC
reference, though the period ends at 12 UTC; the reader takes the period as its end less its
span (00 to 12 UTC). The workflow runs when its own file changes
and keeps NOAA's values only, as the artifact `label-night-forecast-extract` with a SHA-256
manifest (about 18 to 26 MB streamed and 170 KB kept a night).

**5 AM airport reports** (`snowlight predict morning-obs`;
`pipeline/snowlight/predict/morning_obs.py`). For the 05:00 pass only: at each labeled
district's nearest ASOS station within 40 km, the last routine report at or before 05:00 local
and at most 90 minutes old, its temperature and present weather codes and the flags read from
them. One request a second to IEM, cached under `pipeline/.cache/predict/asos/`.

**Snow cover (SNODAS).** Measured only: the label dates need 111 daily analyses; the daily
files hold 3 to 35 MB (2.4 GB in all) and the snow depth member alone about 0.9 GB, over the
100 MB cap, so nothing is fetched until the lead decides. Files from 2019-03 on were posted 7 to
8 hours after their 06 UTC analysis time (the day's analysis is up by 9 PM); older files were
rewritten years later, so their posting time cannot be shown and a night would use the analysis
a day older.

**Report-only checks in backtest v2** (`backtest_terms.run_checks`; `snowlight predict terms`
writes `checks.md` and `checks.json` beside its report, which no gate and no terms file read;
`--drop-training-dates` adds P8). For a candidate against today's model on the storm test rows:
P3 strata (class, 9 PM forecast bucket, Northeast or the rest; a stratum of 30 or more rows on 2
or more dates may be no worse by more than 0.01), P4 (each test date left out), P5 (storm test
dates resampled 2,000 times, the 90% interval of the Brier difference), P8 (2016-02-16 and the 3
training dates with the most rows the candidate moves, each left out of every fit, the base's
too; under the per-fold rule the rows its own fold fits move in their fold labels, each
district-day once, under the earlier rule the rows the served terms move), the raised-vs-lowered split (a gain from raised chances on alert days counts as no
evidence), the level-free check (each model's own best logit shift per class) and the
within-day ranking over every market-day with both outcomes (the pre-registered figure, then
apart from it every market-day but the four split ones, and the split ones alone,
in sample).

## The tuning candidates on the archive (tune-v3: nothing turns on)

Nothing on the site changes with this lane, and `predict.yml` serves exactly as before: no pass
reads a candidate, and every candidate's shadow switch (`candidates.SHADOW`) is off. It runs
the research plan's candidates through the archive test written down before any score
(`docs/research/candidates-preregistration.md`, committed first and never changed):
`snowlight predict candidates` (internal; `pipeline/snowlight/predict/candidates.py`,
`candidates_cli.py`, `candidates_run.py`) writes `report.md` and `metrics.json` to `--out`
only. The archive's lists come mostly from big storm days and its test seasons were studied
when these candidates were designed, so the test can veto a candidate that hurts; it cannot
show that one helps.

**What runs.** Every fit reads its own fold's labels (the per-fold rule) and the P2 support
rule (a fitted step or column needs 20 training rows on 3 dates, else it is 0; a served or
split-off level needs 30 labeled days on 3 dates, no date over half). In order, each against
today's model plus the earlier candidates the archive did not veto:

- the **P2 control**: piece 3's terms with P2;
- **C2a**, the rain/snow line at 7 AM: a term from the 7 AM temperature (32 F and 34 F edges)
  and a mixed type (liquid against snow, or the alert's words as of 21:00);
- **C3**, timing: snow done overnight or ending in the early morning (from the alert's end as
  of 21:00 and the 6-hour snow periods in local bands), mostly afternoon snow, a delay term,
  and a gate that keeps a snow term from taking away once the alert has begun by 21:00;
- the **C4 stage**: the control's terms on that stack, with the snow terms reading the
  district's 9 PM bucket against its own pooled snowy nights (C4) instead of the nation's
  band, judged against the same stack with piece 3's own levels;
- **C1 with C2b**: a state, else a region, serves its own record when it has level support,
  and on snow days the rate moves by the cold or warm record against the level's whole;
- **C2c**, beside them: the C2 columns from the 5 AM airport report, on the 05:00 labels.

Each gets P1 (piece 3's gate), P3 to P6, P8, P9, the level-free check, the within-day ranking,
the T2 sentinels, and the owner table (chance before and after by class, region and 9 PM snow
bucket).

**What it found (2026-10-26, labels SHA-256 38e1c9ca, extract run 40262501880).** Today's model
scores 0.06122 on 1,208 storm rows on 17 dates, as backtest v2 gives it under the per-fold rule.
Every verdict below is **provisional**: two veto checks the plan names did not run (see "Checks
that did not run"), and C3's verdict waits for the lead's ruling on the shifted-input sentinel.

| candidate | its baseline | storm Brier | rows it moves | verdict, sentinel as pre-registered | verdict, sentinel as plan T2 states it | not run (verdict provisional) |
|---|---|---|---|---|---|---|
| P2 control | today's model | 0.06122 to 0.06094 (+0.46%) | 98 raised (all closed), 0 lowered | no archive evidence | no archive evidence | P7 (waits for F3); T2 later-product sentinel on the real data |
| C2a | today's model | unchanged (+0.00%) | none | no archive evidence | no archive evidence | P7 (waits for F3); T2 later-product sentinel on the real data |
| C3 | C2a (equal to today's model's chances) | unchanged; delay Brier on 382 advisory rows 0.0744 either way; shifted inputs +0.023% | none | no archive evidence | harm (veto: T2 sentinel) | P7 (waits for F3); T2 later-product sentinel on the real data |
| C4 stage | the stack with the control's terms | unchanged | none | no archive evidence | no archive evidence | P7 (waits for F3); T2 later-product sentinel on the real data |
| C1 with C2b | the C4 stage (equal to today's model's chances) | 0.06122 to 0.06083 (+0.65%) | 189 raised (99.5% closed), 0 lowered | no archive evidence | no archive evidence | P7 (waits for F3); T2 later-product sentinel on the real data |
| C2c | today's model on the 05:00 labels | 0.07090, unchanged | none | no archive evidence | no archive evidence | P7 (waits for F3); T2 later-product sentinel on the real data; P8 |

Every candidate is also reported against today's model (P1, P5 and harm), as pre-registered.
Here every stack below C1 gives today's chances, so the two comparisons coincide: C1 with C2b
against today's model is +0.65%, its P5 interval -0.00099 to -0.00000, no harm.

- **The shifted-input sentinel (T2 (a)): two readings, and the lead rules.** The
  pre-registration set its bar at a 2% pooled gain (P1's bar). Plan T2 says "an input shifted
  by one day must not help", and plan T3 makes a failed sentinel a veto. The pre-registered bar
  is the weaker one, and the pre-registration did not record it as a departure. Both readings
  are reported, each with its own cumulative stack. C3's own inputs move nothing (+0.000%), but
  shifted by one label night they gain +0.023%: under the plan's rule that is a veto, and the
  stack drops C3 and its gate; the C4 stage and C1 with C2b re-run on that stack give the same
  numbers. The other shifted gains are 0.000% (C2a, C2c) and -0.279% (C1 with C2b), so the two
  readings disagree on C3 alone. C3 stays "no archive evidence (pre-registered) / harm (plan
  T2)" until the lead rules; the pre-registration itself is unchanged.
- **No candidate has archive support.** Under the per-fold rule, the fold labels hold few rows
  with a base before the 2024-25 fold (0, 0, 4, 35 and 270 rows for the 2019-20 to 2023-24
  folds), and the forecast inputs exist only from 2018-19. A candidate's columns reach P2's
  support only in the 2024-25 and 2025-26 folds, and there the inner leave-one-season-out loop
  picks the largest penalty (1,000): fit on one season, the warm and mixed steps do not carry
  to the other. So their weights stay under 0.02 and no published chance moves by a hundredth.
- **Which way the training rows lean** (a diagnostic, never a verdict: the last fold's fit at
  a penalty of 1): 34 F or warmer at 7 AM -0.75, mixed at 32-33 F -1.80, mixed and cold +0.77;
  ending in the early morning -0.53 with the control's terms (-0.81 with C4's levels); at 5 AM
  (C2c) 32 F or warmer -0.36 and mixed and warm -1.50. These are the signs the plan expected,
  from the two 2022-23 rain/snow-line days and 2023-24 alone; only live labels can say if they
  hold.
- **The gains that exist are raises on alert days** (P9): the control's 98 rows and C1 with
  C2b's 189 rows are all raised, on days that closed, so they count as no evidence until live.
  C1a served no state or region record on any scored storm row (in no fold did a state or
  region record of the row's situation have level support); all of C1 with C2b's moves are
  C2b's cold/warm split.
- **C1 with C2b's other checks.** P8 refits without 2016-02-16 and the busiest 3 training dates
  of every level record its scored rows rest on (2024-02-13, 2020-12-17, 2019-02-06, 2024-01-22,
  2024-01-16, 2023-03-14, 2021-02-01): in each refit it stays below today's model, by 0.0000006
  (2020-12-17) to 0.00096. Piece 1's G1 for the new base alone against B0 passes pooled (0.06083 against
  0.09743) and in 2023-24, the one gated season (0.03015 against 0.04087); G2 fails the 0.8-0.9
  bin, as today's base does. On every labeled season C1a would serve 7 cells: the CT and NY
  winter storm warning records (0.97, 0.86), NY's advisory record (0.17 against the nation's
  0.74; 72 days on 3 dates), the Northeast's advisory and winter storm warning records (0.56,
  0.95), and the Ohio Valley's and Upper Midwest's winter storm warning records (0.98, 0.93).
  Another state in those regions takes its region's record; every other place keeps today's
  base. These records are which days each place's lists were captured (T4). None of the 7 is in a region with fewer than 8 labeled days of its
  situation (a served cell needs 30), so C1a turns no "Few local records" flag on or off, and
  C2b's split never changes the level a base names: the flag's count on alert days is today's.
  `test_truth.py` for its cells is deferred to F3, since C1 with C2b builds no model file; its
  sentence ("recorded cold advisory days") waits for the owner.
- **C3's delay term** never reached support (one delay date on the archive), so the delay
  chance is unchanged. **C4** leaves every chance unchanged at the chosen penalty; its
  advisory table by snow bucket is in the report.
- **The owner table** (chance before and after by class, region and 9 PM snow bucket) changes
  in these cells only, all upward: winter storm warnings
  0.92 to 0.93 (P2 control; C1 with C2b); the Ohio Valley 0.84 to 0.85 and the South 0.86 to
  0.88 (C1 with C2b); winter storm warning 2-6 in 0.91 to 0.92, under 2 in 0.94 to 0.96 (on
  rows that closed 0.85) and 9 in or more 0.93 to 0.95 (C1 with C2b) or 0.96 (P2 control).
  The report lists every changed cell.

**Departures from the plan, recorded after the scores** (the pre-registration is unchanged):
- **The shifted-input sentinel's bar** (above).
- **C2's temperature** is the 7 AM value alone (`temp_h07`). Plan sec. 2.2 also names the
  minimum over 5-8 AM; the pre-registration left it out without saying so. It is not added now,
  since that would be a choice made after seeing the scores; the extract keeps `temp_h05` to
  `temp_h08` for a later pre-registered test or the live shadow.
- **C2's date-forward diagnostic** (1,208 storm rows: 0.06122 to 0.06121) fits on each fold's
  labels plus the same season's earlier test dates, and those same-season rows carry the
  whole-archive labels, not per-fold ones (station audiences built from every season). No
  per-fold file is clean for them (the next season's fold builds its audiences from the whole
  test season, its later dates included), so it never gates.
- **C2c's 5 AM reports** were first fetched for the 21:00 labels' 2,388 district-days only. A
  refetch for every district-day of the 05:00 labels and their fold files (2,460: 2,374 with an
  airport within 40 km, 2,253 with a report in the 90 minutes before 05:00; identical on the
  first 2,388) gives C2c's inputs on 919 of its 1,003 scored snow-class rows, and on 635 of 686
  and 656 of 715 snow-class training rows in the 2024-25 and 2025-26 folds. The rest have no
  report and enter as unknown temperature (0).

**Checks that did not run** (every verdict is provisional on them):
- **P7 parity** of the candidates' inputs with the live builders waits for F3, which builds
  them; the Kansas 2025-01-06 replay is not a label night of the extract.
- **T2's later-product sentinel on the real data** (drop every alert product issued after
  21:00 and recompute these candidates' alert inputs: end, begin and type words) did not run:
  the product cache left with the calc-data worktree. What exists is the unit test
  `test_dropping_products_after_the_snapshot_changes_nothing_at_it` and the calc-data lane's
  real-data check of the labels' classes and start moves across 09:00, which does not cover
  these inputs. Every forecast file read was available by 21:00 (387 files, 0 late).

**What happens next.** Nothing turns on. Every candidate goes to S7-L's live shadow when F3
wires its live inputs behind its switch, and live labels decide (T5: 300 or more live storm
rows on 8 or more dates, no harm plus direction, the owner's approval of any new row's words).
A real `predict once` pass on 2026-10-26 (18,227 districts, 22,110 private schools, 4 winter
alerts, publishing off) wrote the same 8,307,105-byte file with the code before this lane and
with it, bar its `generated_at`, and the serving model's every rate hashed the same (checked
again on the lane's final code at 17:22 UTC).

## The night-before outlook (S7-F, piece F2: model and backtest, nothing visible)

Nothing on the site changes with this piece, and `predict.yml` serves exactly as before: no
pass reads the outlook, the heads-ups or the 05:00 labels yet (piece F3 wires them in behind
`PREDICT_OUTLOOK`, off by default). It builds what the night-before chance will serve and
judges it on the archive. All its outputs are internal (`out/internal/predict-outlook/` or a
folder named with `--out`), except the model file below.

**One withdrawal rule (D2).** An alert counts at a moment when it was issued by then and not
yet taken back, its span is not empty and the span overlaps the day's window (18:00 the day
before to 09:00). History reads a row whose final action is a cancel or an upgrade as taken
back at its final `utc_expire`, and before that as its first product gave it; any other row
ends early once its ending product was out, as before. Watches and cold advisories count by
the same rule. The shipped pass is unchanged: its live memory already drops a cancelled or
upgraded alert at once (exactly this rule at the present moment), and its 21:00 training
snapshot keeps the shipped rule until a refit takes the new one (spec-f s. 3). The one place
the rule is new in code is `situations.issued_counts`; the live pass keeps `counts` until F3.

**Heads-ups.** Winter storm watch (WS.A, and the retired BZ.A, LE.A), extreme cold watch (EC.A,
WC.A), cold weather advisory (CW.Y, WC.Y), hurricane watch and tropical storm watch, in that
order of strength. A school's heads-up is the strongest that counts, a district's the
strongest that covers half its eligible schools or more with itself or a stronger one (the
class's rule). A heads-up never changes a class, a label or a rate. The live feed's heads-ups
read by `alerts_live.live_heads_ups`, which no pass calls yet.

**The 05:00 record (D3).** The outlook's target and its labels use the class at 05:00 local on
the school day: what the district woke up to. `predict outlook states` writes that class
history in the files `predict labels --reuse-weather` reads, so the 05:00 labels come from the
shipped label code unchanged.

**States and cases.** `predict outlook states` sweeps the class and heads-up rows of every
school year once: under rule D2 each row counts on one interval of moments per day, so one
pass gives every moment of every night: the 21 sample hours (08:00 the day before to 04:00,
three per slot), the late-in-slot scoring times (10:15, 13:15, 16:15, 19:15, 22:15, 01:15,
04:15) and the 05:00 record. A case is one district at one sample hour of one school night
(15 August to 15 June): the class issued then, the heads-up, the forecast bucket of the newest
run by then (piece F1's `code_filled`: a school whose cell has no value reads as nothing
forecast of that element, as piece 3 reads it; 13 when no run counted) and the 05:00 class.
A late-in-slot time takes its whole hour's forecast (the hourly history holds no later run)
and its class and heads-up exactly as issued by then.

**The outlook (D5).** For each slot S1-S7 (before 10:30 the day before, 10:30-13:30,
13:30-16:30, 16:30-19:30, 19:30-22:30, 22:30-01:30, 01:30-05:00), class issued (none or
advisory), heads-up and bucket, the share of cases that woke up to each class. A cell the
nation holds on fewer than 20 nights merges with the next bucket of its ladder (snow, ice,
feels), the nearer side first and the larger amounts on a tie, then any bucket, then any
heads-up; the merged cell is the cell counted at every place. Each state shrinks toward its
region and each region toward the nation, the strengths chosen from 8, 32, 128, 512, 2048 by
leave-one-season-out log loss over the training seasons' cases. A sentence may name the most
specific place whose merged cell holds 20 nights or more, else the nation, with that cell's raw
share.

**The chance (D6).** `outlook.chance` is the one function serving, the backtest and S7-L will
use: the class's own rate (today's chance, exactly) when a warning is issued, from 05:00, or
when the outlook is not on; otherwise the mixture of the district's rates under each class,
weighted by the outlook, and the delay chance alike, then the shipped clamp and rounding. A
class the outlook gives no weight adds nothing to the mixture, even where it has no rate. A
row whose outlook is empty (F3 passes none when the forecast is stale, the lead's
`Dark.FORECAST` decision, and an empty row for a district whose forecast is unknown) or that
weighs a class with no rate gets today's chance instead, never a blank or a mixture with a
term missing; `chance` refuses an outlook row that is not a distribution.

**The model file.** `predict outlook fit` writes `data/predict/model-f.json.gz` (v3): the 05:00
rates (a v2 model fit on the 05:00 labels) and the outlook's counts by place, derived counts
only. `data/predict/model.json.gz` (v2) stays beside it and is still the one served.

**Commands** (run from `pipeline/`, internal, under the heavy lock):
`predict outlook states` (the states, the cases and the 05:00 weather history; 4 minutes for
2015-16 to 2025-26), then `predict labels --reuse-weather --out <its labels-0500 folder>` (the
05:00 labels), `predict outlook reasons --labels <that folder>` (the share of each closed or
delayed label's schools lit with a weather reason named), `predict outlook backtest`
(`--fold-labels DIR`: each fold's training labels, `labels-<S>.parquet` and
`shipped-<S>.parquet`) and `predict outlook fit`.

**The backtest (2026-10-25).** Walk-forward over 2019-20 to 2025-26: the outlook fit on the
cases of the seasons before each test season (from 2018-19, the first forecast season), the
rates on the labels before it. The same 05:00-labeled rows for three models: S7-F; B-issued
(the class issued by the moment, rates refit on the 05:00 labels); B-shipped (the class issued
by the moment, today's 21:00 rates). The 05:00 labels hold 2,231 known district-days (1,455
no school, 99 delayed, 677 open; the 21:00 labels 2,388). The archive's lists come mostly
from big storm days, so this backtest can veto an outlook that hurts, not prove one helps.

The research lane's label audit (calc-research plan T1) found that the training labels of
every fold depend on later seasons' lists (station audiences and gates built from the whole
archive: 11% to 100% of a fold's training labels change when they are built from the seasons
before it). So the primary run (`--fold-labels`) fits each fold's rates on labels rebuilt from
the seasons before it (the research lane's code); the whole-archive run is kept beside it.
With fold labels, 2019-20 and 2020-21 have no warning-class rate before them, so S7-F's
mixture has no rate for the classes the outlook weighs there: those rows (52 and 46 at 20:00,
762 E(t) rows over all moments) get today's chance from S7-F, as serving will give it, and
are scored for every model. 159 E(t) rows of 2019-20 have no rate under their own class for
any model (no closing among them) and are left out for all three; the report gives each
model's count by season and moment. 56 E(t) rows whose forecast is unknown also get today's
chance from S7-F (lead decision `Dark.FORECAST`).

- Rows with no warning issued at 8 PM the evening before (E20): 890 rows on 34 dates, 278
  closings; 792 of them where the outlook moved the chance (270 closings). With no alert and
  no heads-up at all: 441 rows and no closing. So the archive holds no "nothing issued yet"
  closing: that case rests entirely on S7-L's live check.
- Fold labels (primary): Brier on E20 S7-F 0.0760, B-issued 0.0755, B-shipped 0.0514 (on the
  792 moved rows 0.0837, 0.0832, 0.0567); log loss 0.247, 0.244, 0.187. GF1 fails against
  both (ratio 1.006 and 1.478, bootstrap bounds +0.016 and +0.053; late slots pooled 0.0678
  against 0.0692 and 0.0538). Its explicit-reason rows hold 1 closing, so that subcheck is not
  informative on the archive, and no season reaches 300 E20 rows (largest 287), so the
  per-season check is untested. GF2 fails (closings at 30%: 97.1%, 97.1%, 96.0%; the bar is
  B-shipped's plus 3 points). GF3 fails (precision at 30%: 0.778 against B-shipped's 0.850).
  GF4 fails (ECE at 20:00 0.041 against 0.034 and 0.029; at 22:15 and 04:15 too). GF5 fails in
  89 of 220 bins as T moves from season to season. GF6 passes with no change at all. GF8
  fails (5 AM rates 0.0709 against today's 0.0635; amended G1 passes).
- GF7 (daytime slots) passes on the numbers (0.138 against 0.175 and 0.155), but its whole gain
  comes from raised chances on alert days: against B-issued, raised rows save 104.5 summed
  squared error (124.5 on advisory and warning days) and lowered rows lose 2.6; against
  B-shipped 63.3 and -17.6. Two dates carry it (2024-02-13 and 2023-03-14, a split day chosen
  by outcome), and on quiet rows S7-F is worse (0.015 against 0.0001). Under the research
  plan's T4 that is no archive evidence, so it cannot support the daytime heads-up option
  until live labels arrive.
- Each gate's rows (E20, late slots pooled, 22:15, 04:15, all rows at 20:00, the daytime slots,
  the 05:00 storm rows) are reported with the strata by 05:00 class and storm size and by the
  class issued, the level-free check, the within-day ranking, the gain by date and the raised
  and lowered split with its T4 verdict. On E20 S7-F is worse than B-shipped on advisory
  nights with under 4 in forecast (0.139 against 0.113 and 0.067) and with 4 in or more
  (0.257 against 0.138), and on quiet-label nights with under 4 in (0.062 against 0.035).
- Named dates (20:00, closings with no warning yet): on 2024-01-16 the median chance falls from
  0.86 to 0.66 (117 closings, all at 30% or more either way); on 2023-03-14 from 0.75 to 0.61
  (31 closings, 90.3% at 30% or more either way).
- The strength m sits at the top of the grid (2048) for the region and the state in every fold
  from 2020-21 on: leave-one-season-out wants more pooling than the grid allows. A wider grid
  (up to 131,072, chosen on the training seasons only) picks 8,192 to 131,072, lowers E20
  Brier to 0.0723 (still above B-shipped's 0.0514, so GF1 still fails) and GF5's failing bins
  to 70 of 214 (still failing); the model file keeps the spec's grid, and the lead decides.
- Whole-archive run (leaky, for comparison only): S7-F 0.1443, B-issued 0.1534, B-shipped
  0.1825; GF1 and GF2 fail there too.
- The research lane's T2 check (a later product moving an alert's start), re-measured at
  20:00 the evening before and at 05:00 against these states: 67 and 0 zone-days moved later,
  161 and 87 earlier, none on a labeled row, so no scored row moves.
- Verdict: nothing turns on. The outlook stays off (F3 builds shadow), and only live labels
  can show whether it helps (300 live storm rows on 8 or more dates, the research plan's T5).
The full report is internal (`report.md`, `metrics.json`).

## The night-before outlook on the passes (S7-F, piece F3: shadow, nothing visible)

`PREDICT_OUTLOOK` (the predict workflow's environment, `vars.PREDICT_OUTLOOK`, default
`shadow` there; unset is `off`) switches it. The owner chose to test it quietly first: it runs
in shadow until it proves itself on real storms (300 or more live storm rows on 8 or more
dates) and the owner approves its words; the lead then sets it `on`.

- **off**: the pass is S7-L's, byte for byte (`tests/predict/test_outlook_serve.py` holds a
  synthetic night of 44 passes to the bytes the pass wrote before this piece,
  `tests/predict/golden/off_night.json`), and it keeps no outlook state.
- **shadow** (landed): the file is exactly off's (the same golden). After a pass has published,
  or found nothing to change, it takes the outlook's private record; any error there is a
  warning, never a dark pass. It reads the newest forecast run itself (the newest at the pass,
  at most 3 hours old) and keeps the alerts it saw as products (`state.products`, beside the
  alert memory: every class and heads-up product with its sent time, cancels and upgrades
  included), so it rebuilds what stood at any moment of the last 30 hours. When the log does not
  reach back far enough (the first shadow pass, a gap in the feed over `memory_gap_minutes`, a
  lost cache), it is rebuilt from the NWS alert history of the classes' products and the
  heads-ups' (`inputs.PRODUCT_EVENTS`: winter storm, extreme cold, hurricane and tropical storm
  watches and cold weather advisories, retired codes too), so a watch whose current product was
  sent after a sample hour still stood at it. That read is the product log's own: the alert
  memory's read keeps its events and its 40-page bound. Its reads have 90 seconds a pass
  (`outlook_live.READ_SECONDS`, started once per pass where the outlook's work begins: the
  record step in shadow, before the product log in the pass with `on`): the forecast reader
  checks it before every request (requests of 10 seconds, 5 to connect, two tries, and a day
  listing that failed is not asked again in the pass) and the history read before every page.
  So an AWS feed or an NWS history that is slow or down holds the loop's next pass back by at
  most 90 seconds and one request under way; what it did not read in time is not read (a
  skipped sample, never imputed). A rebuild that fails in the record step is not tried again
  for 30 minutes (`cli.PRODUCTS_RETRY`), and those passes record nothing (a warning that says
  why). With the outlook on, the file's classes come from the product log, so a log that cannot
  be rebuilt within that time darkens the pass (`alert_memory`, as a failed
  alert-memory rebuild does when the 5-minute checks did not keep the memory whole) and the
  next pass tries again: never a class from a log with a gap. Its inputs (the v3 file, the
  learned files on the host) are read before the first pass: any that fails turns the outlook
  off for the run with a warning, never a dark run.
- **on**: every chance from the v3 rates (`data/predict/model-f.json.gz`, the 05:00 record's),
  the class as issued under rule D2, and the outlook's line where it moves the whole percent:
  the base keeps its points, the line `outlook` takes the rest, and the file names the
  forecast's time (`forecast_at`). Private schools keep their base alone; piece 3's reasons are
  not used (they were fit over the v2 rates). The loop also starts a pass between grid passes
  when a slot boundary or 5 AM passes in a district's zone, a forecast period ends (00, 06, 12,
  18 UTC) or a newer complete forecast run counts.

**What the outlook gives the issued-alerts-only chance instead** (the identity, exactly the
class's own rate, with no outlook line; with the outlook on that is the v3 rates' rate, the
rates every chance of an `on` file comes from, not the v2 rates' of the file with the outlook
off, a test pins it with v3 rates that differ; the lead decision of 2026-10-20 says "exactly
the S7-L output", and the lead confirms before `on` that this means `on`'s own rates): a warning issued, 5 AM on the day or later, no
forecast run under 3 hours old for the district's zone (the lead's decision of 2026-10-20,
`serve.forecast_stale: identity`; `dark` would darken the pass, `Dark.FORECAST`), a bucket that
reads unknown, a forecast range that cannot be stated true of every school, a class with no
rate (the own-class guard: no number is ever published from a NaN), a line no class or place
can say truly, and a district that read another run than the file's `forecast_at`. The pass
counts each in its line (`predict: outlook: issued-alerts-only chance (identity) for ...`) and
in `state.outlook_health`. A file over the size budget drops the outlook's lines at
`Fit.NO_REASONS` (every chance the issued-alerts-only one) before it drops any school.

**The line.** `OutlookReason {kind: "outlook", points, now, f, like, to, share, scope}`
(`pipeline/snowlight/schemas/predictions.py`): what was out (`now`: class issued x 6 +
heads-up), the forecast kind and the district's schools' least and most, rounded outward
(snow in whole inches, ice in hundredths, feels in whole degrees; absent when the forecast is
quiet), the cases counted (`like`), the class whose term moved the chance most the way it
moved (`to`), the raw share of the counted cases at the most specific place with 20 nights or
more that counts `to` at all (`scope` 0 state, 1 region, 2 nation; a share true of the raw
count by `share.says_true`, and exact at its ends: 100 only when every case counted ended in
`to`, said "in every case like this", 99 "in almost every case" when nearly all but not all
did, 1 "in almost no case" when some but nearly none did). The web words it (`web/src/copy-chance.ts`, `outlookReason` and
`outlookHelp`), with the slot and the window derived from `generated_at` and the school day
(the slot table is shared, `tests/predict/golden/outlook_slots.json`). The owner approves the
words before `on`; the three example lines are in the internal shots folder of this piece.
Each word is true of its inputs: the class and the heads-up are each the district's 50% value
(the strongest that, with stronger ones, covers half its eligible schools), so nothing out is
said as "No winter storm warning, winter advisory or winter storm watch covers half of
Olathe's schools yet"; the advisory class (winter weather, freezing rain and lake effect snow
advisories) is "a winter advisory", as the base copy names it; the school day is named by its
weekday ("12 PM Tuesday"), never "tomorrow", since a file stays on screen past midnight; a
quiet forecast is said per kind ("little or no snow at most of Lakota's schools and little or
no ice at most of them": the two halves need not be the same schools). A file made before 5 AM
keeps its line on screen until the next file (at most the 90 minutes every chance may age):
with the outlook on, the loop starts a pass at 5 AM in each zone, which replaces it within
minutes.

**The class issued.** On reads each district's class from the product log under rule D2
(`outlook_serve.district_states`: an event counts from its issue until it is cancelled or
upgraded, and an empty span never counts), the v2 file from the alert memory
(`serve.unit_classes`: an event counts from its issue while the memory holds it). Both apply
the schools' heights. Through the synthetic night of the tests (a watch upgraded to a warning,
an advisory issued then cancelled, a cold watch replaced by a cold advisory) they give the same
class at every pass (`tests/predict/test_outlook_bounds.py`). They can differ when the memory
keeps an event the product log has seen withdrawn, or one whose span is empty; private schools
keep the v2 path's class.

**The private record** (`snowlight/predict/outlook_record.py`). Per school day and district:
at each of the 21 sample hours, the class issued, the heads-up and the forecast bucket as they
stood at that hour exactly (taken by the first pass within 15 minutes after it; a zone whose
forecast did not read is not taken, never imputed; a stale run reads as bucket 13 as in the
history); the 8 PM chances, the published one and S7-F's as `on` would show it; and the 5 AM
record (the label class), taken by the first pass between 5 and 9 AM as of 5 AM exactly. The
passes keep the newest 3 days in their state (the Actions cache); `predict learn` merges them
into `predictions/outlook/record.json` on the live host beside `learn.json` (10 school days),
counts each finished day's cases into `predictions/outlook/cases.json` (counts by state, cell
and 5 AM class, frozen once counted), and writes the internal report
`predictions/outlook/report.json`. Model chances and NOAA-derived states only: no list text.
The site never reads any of them.

**T learns** (`snowlight/predict/outlook_learn.py`). With more than 7 live days counted, a
candidate T counted over the committed one plus the live days before the newest 7 is judged
on those 7 days' cases against every T that has not counted them and is not the candidate
itself (`outlook_learn.judges`): the committed T (the archive alone) always, and the served T
without those 7 days when that differs from both. It needs a log loss no worse than each, every
calibration bin of 2,000 cases or more within its bound (GF5's rule), and with 300 or more
labeled E20 rows of those days an E20 Brier no worse than each. Then T refit over every live
day is swapped in (`predictions/outlook/learned.json`, made over the committed artifact's
SHA-256; the passes read it, a file made over another artifact or that does not validate is
ignored). No judge has seen the held-out days: the served T with them in it would be judged on
days it counted, and once T swaps nightly the served T without them is the candidate itself, a
check that could never reject. So T can take in a new live day every night, while live days
that hurt T on the days after them (a fault in taking the record, a stretch unlike the archive)
keep the served T until a candidate beats the archive's T again (a test replays such a run);
a run with no new live day changes nothing. The report
is written only when it says something new (its time aside), so a run that learned nothing adds
no commit to the live host. A new directory edition carries the record over by LEAID (the
host's record keeps its districts' LEAIDs): a district keeps its days, a new one reads as not
taken, and no day not yet counted is lost. The learning step's own outcome (its exit code, its
v2 swap) never depends on the outlook's: every outlook outcome is a warning at most. An error
before its write (the model, the record, the count) writes nothing and is the warning
`predict learn: outlook: <TypeName>: nothing written`. A write that fails is the warning
`predict learn: outlook: writing <every key> failed (<TypeName>): none of it is confirmed
written` (a host that writes file by file may have written some). Its files are read back as
the step's own are (at once, then after 2, 4 and 8 s): confirmed, at once or after the waits,
its lines are said; a file that never reads back as written is the warning `predict learn:
outlook: wrote <every key> but <key> did not read back as written (4 reads, ...)`, and a read
that fails `... but reading <key> back failed with an error (...), so it is not confirmed`:
the files were written either way, and its lines are not said.
`learn.score` now scores through `outlook.chance` (the identity on a labeled morning, exactly
the published rates, a test holds it).

**Size.** The outlook's longest line is 108 bytes. With every district carrying one on both
days and the private schools' table full (9,000 outlooks, no previous chances), the file is
18.93 MB: over the 16.5 MB budget, which spec-f s. 9 counted before the private schools
(contract C3) took its room. On such a night the pass publishes the issued-alerts-only chances
(`Fit.NO_REASONS`, no line and no `forecast_at`) and keeps every school; the districts alone
with every line come to 15.05 MB. With lines on 15% of the district-days the worst case keeps
them (about 19% fit). `tests/predict/test_loop.py` asserts all three. Real files run about
6.3 MB. The lead picks the policy before `on`: as built, every school keeps a chance and the
lines go first.

**The v3 rates learn too.** The same learning step labels the live days under the 5 AM
record's class (the record's morning part read as the passes' class snapshots, so S7-L's
labeling rules are unchanged) into `predictions/outlook/learn.json`, and swaps a refit of the
v3 rates in under S7-L's own no-worse check (`predictions/outlook/learned-rates.json`, made over
`model-f.json.gz`). The passes use it with the v3 rates (shadow and on); a file made over
another artifact, or that does not build, is ignored. The v2 store and its swap are untouched.

**Before `on`, the lead decides** (none changes a file while the outlook is shadow): the line's
"by 12 PM Tuesday" (chart-on, Nov 1: the line no longer names its run's time) counts the snow from
the run's time, up to about 3 h of run age and 90 min of file age before the reader's clock once
the window is under way, so snow that fell in between can read as still to come: count it from
the pass's time, or keep the line off once the window has begun; the size
policy (above: the lines go first on the biggest nights); the tgftp fallback (below); that the
identity of the Dark.FORECAST decision is `on`'s own v3 rates' issued-alerts-only chance (the
class's rate under 5 AM labels, not the v2 rates' 9 PM one); that a file made before 5 AM keeps
its line on screen after 5 AM until the next file (The line, above); that the learning files
stay off the site (the Pages step); and the owner approves the line's words from the shots of
this piece (they changed from the spec's examples: "a winter advisory", "covers half of",
weekdays, the quiet forecast per kind, "in every case").

**Not built here.** The tgftp fallback for a stale AWS listing (a stale run serves the
identity instead; the lead decides before `on`), and the triggers in shadow (shadow keeps off's
pass schedule: grid passes take every sample). The outlook's reader keeps a run's values only
while a read can still use them (4 hours, `outlook_live.RUNS_KEPT`).

## The night chart (option (iv), NOAA's hourly blend: on since Nov 1, 2026)

The owner chose option (iv) of the night snow chart spec (design `chart-data/spec.md`, revision 3,
Oct 26): true hourly bars to 7 AM. `serve.chart` (`config/predict.yaml`) switches it: `shadow`
from the chart-shadow piece (design `chart-shadow/spec.md`, Oct 31), so every gated pass built
the chart in memory and published the file with the chart off, byte for byte, while GC4's
evidence collected itself (below). `on` since Nov 1, 2026, with the owner's OK after the GC5
pictures (design `chart-on/spec.md`), with `chart_fault: none` in the same change, landed after
the web that never names the forecast's time had reached returning visitors (an installed copy
runs its first session on the old code: chart-on critic S1).

**What it shows.** "New snow, hour by hour" on the panel's headline day, when that day carries a
`night`: an empty first bar at Start (the first whole hour after the file's time, never before
6 PM the evening before; labelled by its clock time, never "Now"), then one bar an hour to 7 AM on
the day. Each bar is the least new snow at any of the district's deciding (public) schools from
Start to that hour's end, in tenths rounded down: true at every school as "at least this much".
Over the last bar, "6 to 9 in by 7 AM" covers every deciding school's total (tenths under 2 in,
whole inches from 2 in, rounded outward). "Heaviest snow 1 to 4 AM" lights a span of 3 or 4 hours
only when every school gets 0.5 in or more, each school's heaviest 3 hours (the earliest on a tie)
fall inside it, and the bars rise over it at 1.5 times the night's mean rate or more. The times at
the foot are Start, 7 AM, the span's end and every third hour where they keep clear, and never one
under the gray bar where the span starts or under a lit bar but the last, so the key's hours are
never contradicted (the forecast chart's rule since 4300322; critic r2 B1). The key under the
chart sits with its words: the lit bar drawn small at the words' cap height, 7 px before
"Heaviest snow 1 to 4 AM", from the chart's left edge like the hours (the owner's change, Nov 1).
The chart never says the cycle's time (the owner's ruling, Nov 1: "From the 7 PM hourly forecast"
under the chart until then): the gates below keep a stale cycle off the chart instead, the
pipeline's 150 min and the phone's 195. The screen reader's sentence says "From 10 PM to 7 AM,
the forecast has 6 to 9 inches of new snow at the district's public schools." No bus time is
known anywhere, so no chart word names the buses.

**The source.** NOAA's National Blend of Models (an NWS product) on AWS
(`noaa-nbm-grib2-pds`, public, no key, no cost): the deterministic 1-hour snowfall
`ASNOW:surface:N-(N+1) hour acc fcst:` of the CONUS core files, read by range (one `.idx` and one
message of 0.5 to 0.65 MB per hour), on NDFD's own Lambert projection. Each school reads the NBM
cell nearest it, counted from NBM's own first point (`nbm.cells`): NDFD's cell shifted 200 columns
is a neighbour for about 0.4% of schools, since the two first points are 200.003 columns apart
(critic r1 S1). Every number on the chart is a sum of the cycle's own 1-hour amounts
(`predict/nbm.py`, `predict/night_chart.py`). NBM packs them in whole millimetres; the amounts are
converted to inches unrounded and summed, and every rounding step runs after a 1e-5 in snap, so a
school whose night is exactly 127 mm reads 5.0 in ("5 in", a 5.0 bar), never 4.9 or "4 to 5 in":
whole-millimetre totals sit on a tenth step or at least 7.9e-4 in from one (critic r1 B1). The reasons quote the forecaster's grid
(NDFD), which disagrees often on the same hours; so while a night chart shows, the snow reason
states no amount (owner decision O6): "The forecast has more snow by 1 PM than most storms."
One amount for the night's snow is ever on screen.

**When a district-day carries a night.** Its night is open at the pass (from 7 AM the day before
to before 6 AM on the day, `schemas/predictions.py` `night_day` / `night_open`, one definition
with a TypeScript twin held to `tests/predict/golden/night_day.json`), the day is a school day of
the file, every deciding school is on the grid and read, its 50% value of the night's total is at
least `serve.chart_min_inches` (1 in), and the numbers are inside the contract's bounds. One NBM
cycle serves every night of a file (`night_at`): the newest whose every needed core file and
`.idx` is listed with an S3 `LastModified` at or before the pass, and at most
`serve.chart_nbm_max_age_minutes` old.

**The cap, from the posting lag measured on the right files** (critic 3 B3; measured for this
piece from 1,536 S3 listings of every hourly cycle of January 2025 and January 2026, f001 to
f036, the file and its `.idx`). A cycle's files post over
a median 1.6 min (p90 10.6, at most 32), and f036 is the last in only half the cycles. The age of
the cycle a pass can use, when it waits for every file of every open zone's window: median 97 min
at the :07 and :37 heartbeats, p98 127 (2025) and 157 (2026), over 150 min at 0.27% and 2.76% of
heartbeats (the old f036-only figures were 0.60% and 3.36%; January 2026 holds an outage of 12
cycles posted over 6 h late). Ages fall on steps of 37, 67, 97, 127 and 157 min, so a cap of 150
admits a late or extended cycle (127) and refuses the next step. The pipeline caps at 150 min
(also the contract's `NIGHT_MAX_AGE`); the phone shows the chart while the cycle is at most
195 min old (one missed heartbeat and the file's way), and drops it once its first hour is wholly
past (Start + 60 min). The panel hides the chart on its own ticking clock at that moment
(`data/night.ts` `nightUntil`, the first moment `nightShows` is false), and a phone that wakes
shows the panel by its clock at once, before the read it starts comes back (critic r2 S4). The chart
is gone by 6 AM, before its day is under way (7:30 AM on the school's clock, a770f4c), and a night
only ever sits beside its own day's chance: the next school day's never carries the night just
ending (`app/tests/chance-night.test.ts`).

**The fetch gate.** The pass reads nothing for the chart unless `serve.chart` is not off, some
district that can chart (every deciding school on the blend's grid, so never Alaska, Hawaii or the
territories) has its night day a school day of the file with its window open, and some such
district has a snow-bearing class that day (an advisory, lake effect snow, a winter storm warning,
ice or a blizzard). So an Alaska advisory alone opens nothing (critic r1 S1). A calm night, a
Friday night and July cost no request.

**Cost when open.** Each pass lists afresh the newest cycles until one counts (one page each,
starting at the first hour it needs: about 53 KB for a posted cycle, under 1 KB for one not yet
posted, measured on live S3 on Oct 31; the listing started an hour early until critic r3 S1, so
every posted cycle took a second page), the one it takes included, so a core file NOAA posts anew under the same cycle (a
new LastModified or size) is seen. Each new cycle then costs one `.idx` and one range read per
needed hour, kept by (cycle, hour) with the file's LastModified and size from the listing, so the
:37 pass on the same cycle reads no message again, and a file posted anew is read again, never
served from the old one's values (critic r2 S2): up to 13 to 16 messages, about 9.2 MB (the GC1
replays read 438 requests and 111.7 MB over 20 passes, at most 34 requests a pass; a warm pass
makes two listing requests, the newer cycle's empty page and the taken cycle's one page, about
54 KB, and three, about 0.1 MB, while a newer cycle is part posted). The gate is open from 7 AM Eastern the day before to 6 AM Pacific, about 26
cycles, so a gated day is about 240 MB of messages and about 3 to 5 MB of listings (48 grid
passes at 54 KB to 0.1 MB each, and an event pass adds the same; it was about 13 MB at two pages
a cycle before the listing fix); other days cost nothing. All of it is free public data.

**A chart failure never touches a chance** (`predict/night_serve.py`, `cli.fitted`):
0. every blend read of a pass runs inside one budget through `nbm.NbmHttp`: two tries, 10 s read
   and 5 s connect timeouts, the budget checked before every request, wait, chunk of a body and
   message decode, a wait between tries never past it, a body never past its size, and a range
   read answered with the whole file (a 200) refused before its body is read (a core file is 166
   to 202 MB). The live client (`nbm.bounded_client`) ends every DNS lookup, connect, TLS
   handshake and socket read at the budget's deadline: each socket call's timeout is cut to the
   time left when it starts, and the lookup runs on a helper thread the pass stops waiting for.
   A socket read's timeout holds for each read, not the whole request, so cutting only a
   request's timeout at its start (as until chart-shadow critic B1) let a host that trickles a
   byte now and then and then stalls hold a 15 s budget for 24.5 s; on a real local socket that
   trickle now ends at the budget (`tests/predict/test_nbm_deadline.py`, and at live scale
   15.0 s against 24.5 s before). In `shadow` the budget is `nbm.READ_SECONDS` (60 s), after the
   pass has published. With `on` it is `serve.chart_hold_seconds` (15 s), before the pass
   publishes: a slow, trickling, hanging or failing bucket holds the chance back by at most the
   15 s, plus the decode of a message already read when the time ran out (about 0.1 to 0.6 s of
   CPU), never the 77 s and 1 to 8 s of decode it could before (critic r3 S5). On six replay
   moments, each cold and then warm 30 min later, the reads and decoding of an `on` pass took
   0.8 to 8.8 s (p50 5.6, p95 8.8), nothing withheld. After the reads, `on` builds the larger
   file with nights before it publishes (Pass time, below). A read the budget cut short says
   `nbm_slow`, and what was read before the time ran out is kept for the next pass (critic r1
   B1, G1 and S2; critic r2 S5). These are the only waits the chart can add before the chance is
   published;
1. the whole stage, reading included, runs under one guard before the file is made, and hands
   the file its nights as data;
2. each district's night is built and checked alone with the contract's own check functions: one
   that raises is dropped and counted;
3. a file with nights that fails to make, write or parse back strictly (the parse the pass gives
   its file; any exception but the private schools' `TableError`) is made again at the same fit
   with none, and raises only if that fails too;
4. the chart's own lines and health note, and all of shadow, run under their own guard: a failure
   there says `invalid (<type>)` and the pass goes on.

The pass says `chart: withheld, <code>` and keeps it in `state.chart_health`, with counts
(`invalid (least_falls) x3`). Every chance, why line and base is byte for byte the file with the
chart off (`tests/predict/test_night_guard.py`).

| Code | When |
|---|---|
| `nbm_stale` | no cycle at most `serve.chart_nbm_max_age_minutes` (150) old has every file the pass needs posted |
| `nbm_unreadable` | a listing, `.idx` or range read failed (after its two tries), or an `.idx` holds no one matching line |
| `nbm_slow` | the reads' budget ran out: 60 s in shadow, `serve.chart_hold_seconds` (15 s) with `on`, a read the deadline ended included |
| `grid` | a message is off NBM's grid |
| `size` | the pass published at `NO_NIGHTS` or below |
| `invalid (<check>)` | a night or the file failed a contract check (`least_falls`, `night_at_age`, ...), or the chart code raised (`RuntimeError`, ...) |

On the phone, `data/night.ts` `nightOf` and the
`forecast-detail` call around it are total, and `parsePredictions` never looks at `night` or
`night_at` (a malformed `night_at` reads as no night): a bad night or a bug there is no chart,
never a hidden chance, status or district (`web/src/data/tests/night-isolation.test.ts`). The
section also holds itself without the chart (`app/chance.ts` `ChanceView.bare`): the moment the
chart stops showing, on the panel's ticking clock at its `until` or because it failed to draw,
the timeline says when the district usually announces and the snow reason states its amount at
once, never up to a read later; a chart that failed to draw is hidden until a new reading brings
another, which draws in a new boundary (`ui/tests/chance-section.test.ts`; critic r3 S1, S2). A
day with a night that no longer shows has no chart, never the forecaster's hourly chart in its
place, and the night chart's heaviest-hours key never stands in for a timing reason's own hours
(`app/tests/chance-night.test.ts`; critic r3 S3, S4).

**Pass time.** Measured by critic r2 under the heavy lock on the s4 directory (the 2024-01-08
23:07Z replay): the pass's file with the chart off builds in 12.2 to 12.8 s of CPU; with 2,318
real nights 15.7 to 17.6 s; with a night on all 18,227 districts 19.2 to 20.0 s; each strict
parse of a file with nights 2.6 to 3.4 s. So `shadow` adds about 16 to 20 s of CPU per gated pass,
after the pass has published, plus its reads (cold 6.4 to 7.0 s for 34 requests and about 9 MB on
live S3; warm 0.7 s). `on` builds the file with nights before publishing instead of the
chart-off file: 3 to 5 s more CPU on that replay, and 11 to 18 s more on the GC3 national replay
below (52 to 62 s against 41 to 44 s, a local CPU under load), plus its reads (at most the 15 s
hold). Before `on` (chart-on, Nov 1, local CPU under the heavy lock, the s4 directory, live S3
history): an `on` pass's reads and decode took 4.9 to 7.0 s cold and 0.8 to 4.9 s warm on the
GC1 moments 2024-01-08 23:07Z, 2025-01-05 23:07Z and 2026-01-26 02:07Z (p50 4.9 s, nothing
withheld; at most the 15 s hold), and on the 2024-01-08 23:07Z replay (every district on a
warning) the file with its 2,318 nights built in 16.2 to 16.5 s against 12.4 to 13.3 s with the
chart off: 2.9 to 4.1 s more. So `on` held that pass back 10 to 11 s before it published, and at
most the 15 s hold plus the build's difference (11 to 18 s on the GC3 national replay). The
2-vCPU runners' own numbers come from the `read N ms, built N ms` line on every gated pass. The
loop counts its
next alert check from the pass's start, so this tail never moves an alert check, or the pass an
alert change brings, later (`tests/predict/test_loop.py`; critic r2 S3). GC4 logs `read N ms,
built N ms` on every gated pass, on the 2-vCPU runners, and the summary counts them.

**The job's time with the shadow tail** (chart-shadow W4, Oct 31). The job's limit is 345 min and
`predict run` runs 320 min; a pass that starts just before the end runs to its end, shadow tail
included. Measured: the two latest runs on fa24c4d (41180029926, 41157674791) took 321.1 and
321.4 min in all: 46 and 61 s before `predict run` (the learning step 37 and 46 s, its limit 5 min),
the run step 320.07 and 320.05 min, 18 s after it (the evidence steps' limits 2 and 1 min); a grid
pass starts at :07:00 or :37:00 and its commit lands on the live host 14 to 34 s later. On the
GC3 national replay (the s4 directory with every district on a warning and its record days, the
2024-01-08 23:07Z nights; a local CPU under load from other work), the published chart-off file
takes 41 to 44 s of CPU, the in-memory file with the replay's 2,318 nights 52 to 56 s, with a
night on every district 57 to 62 s, and an injected pass's check 39 to 43 s. So the last pass ends
at most about 1.3 min (publishing: the GC3 day's 44 s chart-off build plus the 34 s the slowest
commit landed after its pass started; a light pass publishes in under 1 min) plus 2.1 min (60 s
of reads, a 62 s build) after the 320 min, and the job at most 5.4 + 320 + 3.4 + 3.3 = 332.1 min
with every step at its limit (12.9 min to spare), about 324 min as measured (21 min to spare).
Nothing needed shortening. These are local CPU times, not a runner's: the first runs after
landing check the run step's real time.
With `on` (chart-on, Nov 1) the tail moves before publishing and the shadow's after-publish
reads and build are gone: the last pass publishes at most 15 s of reads, a 62 s build (GC3, a
night on every district) and the 34 s commit after its start, about 1.9 min after the 320 min,
and the job at most 5.4 + 320 + 1.9 + 3.3 = 330.6 min with every step at its limit (14.4 min
inside the 345), about 322 min with the GC1 replay's 7.0 s of reads and 16.5 s build (1.0 min).

**Size.** The longest night is 124 bytes (13 bars, a 2-digit span; the spec's 99.9 example fails
its own range check, so the longest valid one is 13 bars of 99.0). `Fit.NO_NIGHTS` follows
`NO_RECORDS`, and a file with nights publishes only at or under `serve.night_max_raw_bytes`
(16,446,182, today's measured worst case): the synthetic worst case with a night on every district
steps to `NO_NIGHTS` (today's `NO_RECORDS` file), and up to 10,787 districts fit with the longest
night at that base (`tests/predict/test_loop.py`). With the chart off, the ladder is the one before
it, step for step. With nights and `serve.reasons` on, the whole file without nights comes before
any fit without record days (`cli._fit_steps`, the lead's recorded order; critic r1 and r2 S6): the
`snow_total` and record reason sentences read the record days, so a storm night's charts never
change a reason's text; the nights come back at `NO_RECORDS` only when the whole file is over the
budget even without them. With reasons off (today), record days show nowhere, and the ladder
drops them (`NO_RECORDS`) before the nights.

GC3 (spec 6.3) on the spec's dry-run shape: the s4 directory and committed model with a learned
file anchoring winter storm warnings with 8 live days for every district (own record days on
every district), a nationwide warning pass after an advisory pass, the nights of the 2024-01-08
23:07Z replay (a probe outside the repository, critic r2 S3/S4). Its whole file is 19,101,483 bytes,
over the budget, so it publishes without record days: 9,258,903 bytes with the chart off, 2,397,704
bytes under the spec's dry-run file (the learned file's own bases differ), so the probe pads it with
trailing blanks to exactly the spec's 11,656,607. Then, through the pass's own ladder: a night on
every district (18,227), each the longest real night of its bar count, publishes at 13,596,990 bytes
(659,966 gzip); the longest night the contract allows on every district (124 bytes at 13 bars, on
11,036 of them) at 13,873,643 bytes (630,600 gzip). Every night is carried and nothing withheld: 2.57
MB or more under the night cap (16,446,182) and 0.84 MB or more under the gzip budget (1,500,000).

**The switch.** `off`: the file is byte for byte as before, nothing is read, no state is kept.
`shadow`: the pass publishes the off file first; only then does it read the blend and build the
file with nights in memory through the same guard and ladder, and report its nights, cycle, age,
bytes, withheld codes and the stage's time ("would publish it with no ..." when it steps down), so
shadow never delays a chance. `on`: it publishes the file with nights.

**GC4's faults, in shadow only** (`serve.chart_fault`, refused unless `shadow`;
`predict/chart_evidence.py`). They act on the in-memory build alone; the published file is the
chart-off file whatever they do (`tests/predict/test_night_guard.py`, each fault through the
budgeted blend reader):

| Fault | What it does | The code it must give |
|---|---|---|
| `raise` | the night builder raises | `invalid (RuntimeError)` |
| `stale_night_at` | `night_at` one minute past the cycle cap | `invalid (night_at_age)` |
| `frozen_listing` | the listing hides every file posted within the cap and a minute | `nbm_stale` |
| `bad_host` | every blend request goes to `noaa-nbm-grib2-pds.invalid`, which never resolves | `nbm_unreadable` |
| `nbm_slow` | the reads run on a budget already spent (no request is made) | `nbm_slow` |

A fixed fault injects on every pass. `rotate` (the setting since chart-shadow) injects them in
that order on 1 grid slot in 6, by the pass's scheduled grid slot (the latest :07 or :37 at or
before it, counted from the epoch; slot `k` injects `FAULTS[(k // 6) % 5]` when `k % 6 == 0`),
so a pass run again in its slot picks the same fault, each fault comes back every 15 hours (3
or 4 times in 48 hours, 9 hours later in the day each day, so a calm hour does not hold a fault
for good), and an event pass never injects. A slot injects once: a run's first pass counts as a
grid pass wherever it starts, and one that lands in a slot the run before already injected (the
records in the state say so) injects nothing, so at most 1 grid pass in 6 injects (chart-shadow
critic S1). `nbm_slow` joined the four the spec names so the `on` hold's code is seen on the
runners too (critic S5); it costs no request. A pass that injects one and opens the gate builds
the file with nights in memory whatever its nights, and checks in the pass that it has no
`night` and the published file's bytes ("fault bad_host: no night, the published bytes").
`stale_night_at` moves the nights' `night_at`, so it acts only on a gated pass that built a
night: one with none gives no code and counts apart, as `no_night`.

**The evidence, on the public host** (W3). Each shadow pass adds a record to the state's last 48
hours (`state.chart_shadow`: its time, fault, whether the gate opened, the cycle's age, its codes,
its nights, and its read, build and whole-tail times), and each upload puts their summary beside
the file in the same commit (`v1/predictions/chart-shadow.json`; one tree, so no GitHub request
more; never the predictions file itself, and only in shadow): passes, how many opened the gate
and how many injected; the cycle's age at the clean passes (min, p50, p95, max); the clean
passes' withheld codes (passes per code); the shadow tail's whole, build and read times (p50,
p95, max); and per fault `injected`, the passes it acted on (its slot came with the gate open,
and for `stale_night_at` a night was built), `gate_shut` (its slots with the gate shut, which ran
nothing), `no_night` (`stale_night_at`'s gated passes with no night), how many injected passes
gave its code (`with_expected_code`) and left the with-nights file with no night and the
published bytes (`clean_chances`), `not_clean` (every gated pass of it whose in-pass check
failed: it must stay 0), and the codes it gave. Counts and codes only: no name, district or
text. The summary lags the shadow pass by one upload (the shadow tail runs after its pass
published). One plain GET reads it, with no GitHub API:
`curl -s https://viaate.github.io/snowlight-live/v1/predictions/chart-shadow.json`.

**When GC4 is met.** The lead judges it on `faults`, never on `passes`: for every fault,
`injected` is 1 or more and `with_expected_code` and `clean_chances` both equal it, and
`not_clean` is 0 for every fault. A fault's slot only acts when the gate is open (a snow-bearing
class in a district that can chart, in its night window), so a calm 48 hours (early November, a
Friday and Saturday) can leave a fault at `injected: 0` with only `gate_shut`; then shadow runs
on until every fault has met it, and the 48 h window is read again then (its records keep the
last 48 hours, so the lead reads it while the evidence is in the window, or notes the counts as
they come). The file is written only in shadow: once the chart leaves shadow it keeps its last
counts and `mode: shadow`, dated by its `generated_at`, and the lead removes it from the live
host when turning the chart on.

**GC1, the truth gate.** `snowlight predict night-replay --site-data <directory> --out <dir>
<UTC moments>` makes the file a pass would have made at past moments (the NBM cycles as S3 listed
them then; every chance the calm base), and `snowlight predict night-check <file> --site-data
<directory>` checks it against the blend, freshly listed, read and decoded by a second
implementation (`predict/night_check.py`, grown from the design probe) that imports only NDFD's
`cells` (a first guess it corrects): a test runs it in a fresh interpreter and fails if the rule's
modules are loaded, and a ruff `banned-api` rule forbids the imports there. It finds each
district's deciding schools from the directory's own school kinds, each school's nearest grid
point from the message's own coordinates, and works in whole millimetres with integer rounding. It
holds that `night_at` is the newest cycle its own listing shows counting at the file's time, that
each message is that cycle's 1-hour snowfall of that hour (reference time and steps), that every
bar, range end, mode and heaviest span is the rule's exactly, and, both ways, that every open
district on a night day carries a night exactly when its 50% value reaches 1 in. 100%, or nothing
ships.

**Before `on`** (the lead): the 48 h shadow review and the GC4 faults (both read from the
summary above, in shadow with `rotate`, by the rule in "When GC4 is met"), the whole delay before
an `on` pass publishes measured on the GC3 every-district replay and the runners (Pass time),
the owner's look at real shadow screenshots (GC5),
and O7 (two NOAA forecasts on one panel: the chart is the blend,
the reasons the forecaster's grid). O7 includes the words: the chart says "From the 7 PM hourly
forecast" while the snow reason says "The 7:19 PM forecast ...", two forecasts from two products a
few minutes apart that print the same range in 0.7 to 33% of districts; the copy rules forbid
"model" and naming a source, so the lead and owner either accept that wording or pick a
lint-clean name that tells them apart (critic r1 S4). Turning it on is one change of two lines
in `config/predict.yaml`: `chart: "on"` AND `chart_fault: none`. Config refuses any fault unless
the chart is in shadow, so `on` with `rotate` left in would stop predict loading its config
(`tests/predict/test_night_guard.py` loads the committed file). The area (ZIP) panel carries no night chart
(the spec leaves it out); only a district's own panel does.
