# Tuning candidates C2, C3, C4, C1 with C2b: pre-registration (tune-v3 lane)

Written 2026-10-26, before any candidate score was computed, and not changed after. Internal.
Nothing here turns on: every served chance stays exactly as it is, and a candidate that the
archive does not veto goes to the live shadow (S7-L, from about Oct 31), where live labels
decide. The archive's lists come mostly from big storm days, and its test seasons were already
studied row by row when these candidates were designed, so this test can veto a candidate
that hurts; it cannot show that one helps.

## 1. Rows, base and folds (the common test)

- **Test rows:** the whole archive's known labels (`labels.parquet`, 2,388 known district-days,
  SHA-256 prefix 38e1c9ca), test seasons 2019-20 to 2025-26 (`backtest.test_seasons`).
  Scored: storm rows (the day's own weather class above none) that have a base.
- **Training rows: the per-fold rule** (lead decision of 2026-10-25): every fit for test season
  S, its base included, reads only S's fold labels (`folds/labels-before-S-07-01.parquet`,
  built from the listings and reads before S).
- **Today's model:** piece 1's walk-forward base under the per-fold rule, published (rounded to
  hundredths within the floor and ceiling), with piece 3's terms off.
- **Fit:** L2-penalized logistic regression with the base's log odds as offset and sign
  bounds (`terms.fit`), the penalty from the inner leave-one-season-out loop over `PENALTIES`.
  Every row weighs 1.
- **P2 support, in every fit (inner fits included):** a fitted step or column is fit only when
  the training rows it reaches span at least 3 distinct dates and at least 20 rows; otherwise
  it is fixed at 0. A level a candidate serves (C1) or splits off (C2b) needs at least 30
  labeled days on 3 or more dates, with no single date holding more than half of them.
- **Order, cumulative:** the P2 control first; then C2a, C3, the C4 stage, C1 with C2b. C2c
  (the 05:00 form) runs beside them on the 05:00 labels. A candidate's baseline is today's
  model plus every earlier candidate that was not vetoed (verdict "no archive evidence" or
  "archive support"); a vetoed one leaves the stack. The baseline is never B0.

## 2. Inputs, all as known at 21:00 local the evening before

- **Forecast** (label-night forecast extract, workflow run 40262501880 on 3616047; NOAA values
  only): 7 AM air temperature `temp_h07` (F, the deciding schools' 50% value counted from the
  cold side); snow and liquid per 6-hour period (`snow_e06` to `snow_e24`, `qpf_e06` to
  `qpf_e18`); the history's snow window total `snow_window`. Every file of every night was
  available by 21:00 (the extract's `late` list is empty; checked again from `runs.parquet`).
  Nights before 2018-19, and 2018-11-26 for every element but temperature, have no values:
  the level is unknown and adds 0, never a default.
- **Alerts** (calc-data's product streams, `alert-inputs.parquet`): per district-day the state
  of the alert reaching most of its schools as the products issued by 21:00 state it (rule
  D2): start, earliest stated begin, end, and the type flags (sleet, freezing rain, freezing
  drizzle, rain, mix).
- **5 AM airport reports** (C2c only, calc-data's `morning-obs.parquet`): the nearest ASOS
  station within 40 km, the last routine report at or before 05:00 local and at most 90 min old:
  temperature and the flags rain, sleet, freezing, drizzle, mix.
- **Local forecast climate** (C4): the forecast history's 21:00 codes (sample 13,
  `code_filled`), from 2018-19.
- **Not available on the archive, so not used:** snow cover (SNODAS, lead decision: not
  fetched); snow already fallen before 9 PM from NDFD (the 21:00 run holds no period already
  over); the NDFD weather strings for timing (C3 uses the 6-hour periods and the alert end);
  the WSSI category (C6, lead decision: deferred); neighbors closing, snow days used, day of
  week and extreme cold (L1-L4: live only).

## 3. The candidates

Weather classes: advisory (1), winter storm warning (5). "Snow classes" below means these two,
as the plan states it; blizzard warning days (7) take no C2 or C3 term.

**Temperature levels** (C2a, C2b, C2c): cold below 32.0 F; near 32.0 to under 34.0 F; warm
34.0 F or more. Band edges and their sources: 32 F is the freezing point; 34 F follows from
R3's coastal airport readings (EWR and ISP at 33-34 F on 2023-02-28; all six stations at
33-37 F on 2023-03-14; r3-errors.md sec. 3). Both edges were chosen after seeing test-day
observations, which is one more reason the archive is only a development check for C2.

**Mixed type** (C2a, C2b), either source:
- (i) snow vs liquid over the window's periods (ending 06, 12 and 18 UTC on the school day):
  liquid of 0.10 in or more with forecast snow under 5 times the liquid. Source of the edge:
  about 10 to 1 is the common snow-to-liquid rule of thumb; under 5 to 1 is taken as rain or
  sleet in the mix. Fixed here, not tuned;
- (ii) the alert's type flags as of 21:00: sleet, freezing rain, freezing drizzle, rain or mix.

**C2a, a term (rank 1).** On snow-class rows with forecast snow in the window (`snow_window`
above 0) and a known 7 AM temperature; five columns:
- warm, step 1: 32 F or more, may only subtract;
- warm, step 2: 34 F or more, may only subtract (with step 1, the term is monotone);
- mixed and warm (34 F or more): may only subtract;
- mixed and cold (under 32 F): may only add;
- mixed and near (32 to under 34 F): sign free.
The cold reference adds 0. Unknown temperature adds 0.

**C2c, the 05:00 form.** Scored on the 05:00 labels (S7-F's 05:00 class, lane F2's files)
against piece 1's walk-forward base on those labels (per-fold, F2's fold files), on snow-class
rows at 05:00 with a station report: the same five columns from the observed temperature and
present weather (mixed: rain, sleet, freezing, drizzle or mix).

**C3, timing (rank 2).** Local bands on the school day D in each district's own zone (standard
or daylight time): overnight before 1 AM, early morning 1-7 AM, school day 7 AM-1 PM, afternoon
after 1 PM. A 6-hour period's snow goes to the band holding most of its local hours, half to
each when split 3 and 3. On snow-class rows:
- **done overnight**: the alert ends (as of 21:00) by 1 AM, or 90% or more of the forecast snow
  (periods ending 06 to 24 UTC on D) is overnight; may only subtract;
- **ending in the early morning**: not the above, and the alert ends by 7 AM, or 90% or more of
  the snow is overnight or early morning; may only subtract;
- **mostly afternoon**: neither, and more than half of the snow is in the afternoon; sign free
  (its fitted sign is reported);
- otherwise snow through the school day, the reference (0); no snow total and no alert end:
  unknown (0).
- **Delay:** "ending in the early morning" as a term on the delay chance q, may only add, fit on
  the delay rows (days with school) with q's walk-forward base as offset. No school, delay and
  open still add to 100% (p_delay = (1 - p) q).
- **"Already down" gate** on piece 3's snow term (it bites from the C4 stage on, where a snow
  term exists): on a row whose alert had begun by 21:00 (its earliest stated begin, else its
  start, at or before 21:00 D-1), the snow term may not subtract. The second half of the plan's
  gate (2 in fallen in the 24 h before 9 PM) has no archive input and is not applied.

**P2 control (step 2).** Piece 3's terms (snow on advisory days, snow on warning days, ice,
cold, neighbors) exactly as backtest v2 fits them under the per-fold rule, plus P2.

**C4, amounts against what is normal there (rank 3).** The snow terms' levels are redefined.
A place's climate is its 21:00 snow codes 1 to 5 over the nights of the seasons before the test
season (one climate per fold; 2019-20's fold gets 2018-19 alone), pooled from the district to
its state, region and the nation, taking the first with 20 or more snowy nights. With the
row's own 21:00 snow bucket b (0 to 5), "lower" the share of the place's snowy nights with a
bucket below b and "higher" the share above it:
- below most: higher above 0.5 (may only subtract; advisory days only, as piece 3's warning
  term only adds);
- far above most: lower above 0.9 (adds, a second step);
- above most: lower above 0.5 (adds);
- otherwise typical (0).
The C4 stage is the P2 control with C4's snow levels in place of the national bands, on top of
the accepted C2a and C3 terms and C3's gate. C4's verdict is judged against the same stack with
piece 3's own snow levels (the control), so it gets credit only for what it adds; the stack
against today's model is reported too, and the stage enters the cumulative baseline only if
that is not vetoed either.

**C1 with C2b (rank 4), a new base.**
- **C1a, the level rule:** on alert-class rows, a state, else a region, serves its own raw
  rate (closings over labeled days of the row's situation in the fold's training rows of the
  seasons before the row's own) when it has P2's level support (30 labeled days, 3 dates, no
  date over half); else today's base stands.
- **C2b, the split:** on snow-class rows with a known kind (cold: under 32 F and not mixed;
  warm or mixed: the rest with a known temperature), at the finest of state, region and nation
  whose days of that kind have level support, the kind's rate is shrunk toward that unit's rate
  over every kind, r_k = (y_k + 8 r) / (n_k + 8), and the row's rate moves by
  logit(r_k) - logit(r) (rates held within the served floor and ceiling). Otherwise it does not
  move.
- The stack's terms are refit on the new base (training rows get it walk-forward within their
  fold). Also reported: the new base alone against B0 (piece 1's G1) on the same rows.

## 4. Checks and verdicts (plan T3, T4)

Reported for every candidate, against its baseline and against today's model:
- **P1** (piece 3's gate): pooled storm Brier at least 2% better, with and without 2020-21;
  worse in at most 2 gated seasons (300 or more storm rows); signs hold; G2 on the unclamped
  chance.
- **P3** strata (class x 9 PM bucket x Northeast or the rest; checked at 30 rows on 2 dates;
  worse by more than 0.01 vetoes). **P4** each test date left out. **P5** storm test dates
  resampled 2,000 times (seed 7), 90% interval of the Brier difference. **P6** chances on
  no-alert rows unchanged. **P8** 2016-02-16 and the 3 training dates with the most rows the
  candidate moves, each left out of every fit. **P9** raised vs lowered. The level-free check.
  The within-day ranking over every market-day with both outcomes (the pre-registered figure),
  with the 4 split market-days also reported apart (in sample).
- C2: each of 2023-02-28, 2023-03-14 and 2024-01-16 apart; a date-forward diagnostic (never
  gates). C3: delay Brier on advisory rows and a three-way log score; the no-school storm Brier
  must not get worse (a C3 veto).
- **T2 sentinels:** (a) the inputs shifted by one label night (each row takes its district's
  values from the next label night of its zone, the last from the first): the shifted
  candidate's pooled gain over the baseline must stay below 2% (P1's bar), else the input
  carries something other than its own night; (b) no forecast file available after 21:00 is
  read (from `runs.parquet`); (c) the alert inputs come only from products issued by 21:00
  (`alert_streams.zone_state` and its tests; the product cache was removed with the calc-data
  worktree, so the drop-every-later-product rerun is not repeated here); (d) parity with the
  live builders on the P7 days waits for F3, which builds the live inputs.

**Verdicts:**
- **Harm (a veto):** pooled storm Brier 2% or more worse than the baseline; P5's interval wholly
  worse; any checked P3 stratum worse by more than 0.01; P6 fails; a sentinel fails; for C3,
  any worse no-school storm Brier.
- **No archive evidence** (expected): no harm. It goes to the live shadow.
- **Archive support:** no harm, P1 passes, P4 holds, P5's upper bound below 0, the gain stays
  above 0 with each P8 date left out, and the gain is not from raises: the squared error
  taken away on lowered rows is positive and the pooled gain stays at least 2% with every
  raised row put back to the baseline's chance. Even then it is in sample: it only orders
  the shadow reports.

## 5. The owner table

Chance before (today's model) and after (each candidate, and the final stack), mean chance and
closed share, by class, by region (NOAA's nine climate regions) and by 9 PM snow bucket, on the
storm test rows.

## 6. What happens after

Nothing turns on. A candidate not vetoed is wired behind an off switch (off) for F3's shadow;
live labels decide under T5 (300 or more live storm rows on 8 or more dates, no harm plus
direction, the owner's approval of any new row's words).
