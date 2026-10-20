# Snow-day chances: runbook

`snowlight predict` (pipeline/snowlight/predict) gives every public school district a
chance of no school today and tomorrow, every school day, in `predictions/latest.json`
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
  plain or advisory day's. Advisory and cold classes mix VTEC codes, so their sentence says
  "days like this". A borrowed day after a snow day says "The chance is counted over
  recorded days like this that did not follow a recorded snow day": the counted days are
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

Environment: `PREDICT_PUBLISH` (`on` writes `v1/`, `shadow` writes `v1-shadow/`, `off`
writes nothing and is the default; the workflow sets `on`), `LIVE_HOST_TOKEN` (the
workflow passes `SNOWLIGHT_LIVE_TOKEN`), `GITHUB_TOKEN` (reads the site's deployments for
the directory handshake).

## When a pass stays dark

A pass publishes nothing, and the page hides the old file within 90 minutes, when:

1. the NWS alerts cannot be read, or the feed's `updated` is older than 20 minutes;
2. the deployed directory cannot be known for certain, or its `meta.json` and
   `points.bin` are not the ones its `edition.json` names;
3. fewer than 99% of the deployed districts are in the model;
4. the winter alerts drop by more than 80% from a pass that had more than 50 (published
   once the next pass confirms the count);
5. the file does not validate, or is over budget (16 MB raw, 1.5 MB gzip; the worst case,
   every district under a winter storm warning, the longest alert name a base carries, on
   both days with a previous chance and every recorded district with a full record, measures
   15.8 MB raw (15,795,035 bytes) and 0.2 MB gzip:
   `tests/predict/test_loop.py`);
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
