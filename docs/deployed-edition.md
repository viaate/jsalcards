# The deployed directory edition: runbook

Every preview build reads the edition the site serves before it builds the school directory
(`snowlight directory deployed-edition`, `pipeline/snowlight/directory/deployed.py`). The build
keeps the deployed date while the directory's content is unchanged, and dates changed content
past it. When the reader cannot know the deployed edition for certain it fails, the preview
fails, and the site stays as it is. That is always safe, but the site then stops updating until
the cause clears. This page says what each failure means and how to clear it.

The reader runs before any deploy, and only a deploy changes the newest `github-pages`
deployment. So a failure that does not clear itself repeats on every push until someone acts.

## How the reader decides

1. **The live deploy's artifact** (for a day after the deploy). The newest deployment succeeded,
   so it is live; its run's `github-pages` artifact holds the files the site serves. The edition
   is made from the artifact's `data/schools/meta.<hash>.json` and `points.<hash>.bin`, and an
   `edition.json` beside them must name them. A deploy from before editions so still has one.
2. **The CDN**, from a copy fetched (`Date` less `Age`) at least two minutes (`SETTLE`) after
   the newest deployment last changed: its creation, last update, each status, and the end of
   its workflow run. Older copies are refused and asked for again for up to 15 minutes. The
   edition is checked as the artifact's is: it must name the `meta.<hash>.json` and
   `points.<hash>.bin` the CDN serves the page. The reader finds them where the page does, in
   the list of data files the page's scripts carry: from a copy of `index.html` fetched after
   the same moment, through its module scripts and the chunks they import, all on the site.
3. **"None deployed"** only when nothing was ever deployed, or when the CDN answers 404 and the
   newest deployment's commit predates editions (`web/scripts/edition.mjs` is not in its tree,
   `web/index.html` is). Any other 404 is an error: it may be an origin's passing 404, which the
   CDN keeps for ten minutes or more.

A deployment that never settled (queued, in progress, or with no status) is read as ended once
its workflow run has ended. With no run to ask (none named, or deleted) it is read as ended one
hour (`STUCK_AFTER`) after its last change.

## Failures and how to clear them

Commands below use `gh api`; `OWNER/REPO` is this repository and `ID` the deployment's id from
`gh api "/repos/OWNER/REPO/deployments?environment=github-pages&per_page=1"`. Marking a
deployment inactive or deleting it needs a token with `deployments: write`; it changes no
repository setting.

| The reader says | What it means | What to do |
|---|---|---|
| `a deploy is in progress (its state is 'X'); run again after it` | A deploy is running. | Re-run the preview after that run ends. |
| `a deploy is in progress (its state is 'X' and it names no workflow run)` or `... its run N is gone); run again after <time>` | A deployment that never settled, with no run to ask. | It clears itself at the time given. To clear it sooner, mark it inactive: `gh api -X POST /repos/OWNER/REPO/deployments/ID/statuses -f state=inactive`, then re-run the preview. |
| `the CDN's copy of ... is from <time>, before the last deploy settled ..., and no newer copy came within 0:15:00` | The CDN still holds a copy from before the newest deploy. | Re-run the preview a few minutes later. Pages sends `max-age=600`. |
| `... edition.json is a 404, but the newest deploy (commit X) is not provably from before editions` | The site serves no edition, though the newest deployment's build stages one. Either the 404 is a passing one, or the newest deploy failed and the live site is still a deploy from before editions. | Re-run the preview 10 to 30 minutes later. If it repeats and the newest deploy failed: within a day, re-run that run's failed deploy job (Re-run failed jobs), which deploys the same artifact; after a day, mark that deployment inactive and delete it (`gh api -X DELETE /repos/OWNER/REPO/deployments/ID`), so the newest deployment is the live one again. |
| `commit X is not a build of the site` | The newest deployment names a commit whose tree has no `web/index.html`, or a commit that is gone. | Re-run the preview later. If it repeats, check the deployment's commit. |
| `... no Date and Age to tell how old the copy is` | Something in front of Pages answers without an `Age` header. | Nothing in the preview can work around it. Remove the proxy, or teach the reader that host's header. |
| `GitHub API ...: HTTP 403` or `HTTP 401` | The job token lacks a permission. | preview.yml needs `contents: read`, `actions: read` and `deployments: read`. |
| `GitHub API: ... is of an unexpected shape` | The API answered in a shape the reader does not know. | Fix the reader; nothing is wrong with the site. |
| `edition.json from ... is not an edition` | The deployed `edition.json` does not parse with today's `DirectoryEdition`. | A change to the edition's schema must keep reading every version a live deploy may serve, until a deploy with the new one is live. |
| `edition.json in the artifact of run N does not name the ... beside it: it says ...; they are ...`, or the same `in the CDN, a copy fetched ...` | The live deploy's edition and directory disagree. Staging refuses that, so it should never happen. | Re-run the preview once first. Read from the CDN, the edition and the page are two fetches, and while `SETTLE` is unmeasured they can straddle a deploy going live; a re-run then reads one deploy and passes. If it repeats, it does not clear by itself, and no push or further re-run gets past it: every preview's reader reads the same deploy, from its artifact for a day and from the CDN after that, refuses it the same way, and stops before it builds. It never turns into a build dated from the wrong edition. Find out how that deploy was made and fix the cause first. Then run the recovery below, once. |
| `snowlight directory build: refused: the deployed directory is dated D, more than 31 days after T` (exit 4) | The deployed date runs more than 31 days ahead of the build day. Each change on a day already used moves the date a day on, so it takes more than 31 such changes, or a wrong clock. | Wait for the calendar to catch up, or find the cause. Taking the build date instead could reuse a date that names other content. |
| `snowlight directory build: refused: previous edition ...` (exit 4) | The file the reader wrote is missing or not an edition. | A bug between the two steps; the reader writes only checked editions. |
| `snowlight directory build: refused: time zones are known for N of M schools, below the 99.9% a build needs` (exit 4) | The NWS county and zone files read give too few schools a zone. | Check the NWS boundary release the build report names. Only a build with `--zones` (the live ingest's) reads them. |
| `the page at ... does not name one schools/meta.<hash>.json and one points.<hash>.bin`, `... names no module script`, or `... on the CDN is not named by its bytes` | The CDN's copy of the page does not lead to one directory, as the page's own reads would. | Re-run the preview later. If it repeats, the site's build has changed how the page lists its data files (web/tools/data-files.ts): teach the reader the new form. |
| `... is not on the site` or `... was redirected off HTTPS or off the site` | A script of the page, or an answer for one, is on another host. | Nothing in the preview can work around it. Check what serves the site. |
| `error: SSL_CERT_FILE ...` | The CA bundle named in `SSL_CERT_FILE` cannot be read. | Fix or unset `SSL_CERT_FILE`. The reader trusts that bundle in place of the default store, for a proxy that terminates TLS. |
| `::error::snowlight directory build exited 2: a usage error or a uv failure (see the log above)` | argparse refused the step's command line (a flag the command does not take), or `uv` failed on its own, for instance setting up the environment. | The log above the line says which. For a usage error, fix preview.yml against `snowlight directory build --help`. For a uv failure, re-run the preview. Nothing is wrong with the site or the data. |

Exit 4 from `snowlight directory build` is a refusal its inputs decide, and exit 2 a usage error
or a failure of `uv` itself; the preview retries neither. Exit 1 may be a passing download
failure (from the cache or the data mirror, below), and the preview tries twice more.

`snowlight directory deployed-edition --max-wait SECONDS` bounds the wait for a fresh CDN copy
(default 900, at most 86400). The preview keeps the default; a caller with a start-up budget,
such as the live ingest, gives less, fails sooner, and tries again on its next run.

## Recovery from an edition that names another directory

Only for the error above, and only once its cause is fixed and on the default branch:

1. Actions > Preview > Run workflow, on the default branch, with "date_past_mismatch" checked.
2. The reader step logs `::warning::recovery run`. When the deployed `edition.json` names
   another directory, the reader (`--date-past-mismatch`) writes an edition dated the later of
   the deployed `meta.json`'s date and that `edition.json`'s, with a digest no directory has.
   The build then dates the directory the day after that date, or on the build date when that
   is later: a date no deploy has used, so no stamp can name two contents. Live files indexed
   into the old directory go dark until the live ingest restamps against the new one.
3. Every other failure still fails, so the input does nothing when the read is sound: the
   reader writes the deployed edition as it is.
4. Check that the run you started is the one that ran. Of the runs waiting in the group
   `pages`, only the newest goes on, so a push that queues after the recovery run, before it
   starts, cancels it, and the push's own run reads the mismatch and fails. Start the recovery
   again once nothing else is queued.

After that run deploys, the newest deploy names its own directory and later pushes read it as
usual. The recovery is pinned by tests in `pipeline/tests/directory/test_directory_deployed.py`
(`test_the_recovery_edition_dates_any_directory_past_both`,
`test_cli_date_past_mismatch_dates_past_a_mismatching_edition_and_nothing_else`) and
`pipeline/tests/test_preview_workflow.py`
(`test_the_recovery_input_reaches_the_reader_on_a_run_by_hand_only`).

## Source files: the data mirror, and bumping a pinned source file

The preview reads every NCES and Census file the directory and places builds need from its
download cache, else from the data mirror: the release of this repository tagged
`data-mirror-<digest>` for the current pins (`uv run snowlight mirror tag` prints it). It never
contacts nces.ed.gov or census.gov: its build step sets `SNOWLIGHT_REQUIRE_MIRROR=1`, so a build
with no mirror set exits 2 instead of reading the origins, and a test fails if a deploy step names
either host or runs a directory or places build without both settings
(`pipeline/tests/test_preview_workflow.py`). The pins are every candidate with a `sha256` in
`pipeline/config/directory.yaml` and every file in `pipeline/config/places.yaml`, which also pins
the Gazetteer, GRF and population estimate releases. Each file is checked against its pin
wherever it comes from. The LSAD code list's page changes on every load, so it is pinned, and
mirrored, as its code table written as a plain page (`lsad-table`). A newer NCES release that is
not pinned (the 2024-25 private school geocodes, while NCES has not published them) is never read
by a deploy; the build log says it is skipped as not pinned.

`.github/workflows/data-mirror.yml` seeds the mirror: on a push that changes either pin file (or
itself) it stages each pinned file the release lacks, or holds with a SHA-256 other than the pin's
(it is replaced). A file an earlier `data-mirror-` release holds intact is copied from there, so a
pin bump reads only its new files from the origins, with the same checks a build makes. After an
upload it proves the release by building the directory and the places records from the files it
staged and from the release alone, and comparing them byte for byte. It is the only job that
contacts NCES or Census. `.github/workflows/nces-check.yml` asks NCES once a week
whether a newer release of a pinned file family is out, and opens or updates the one issue
"New NCES release available" when one is. A closed issue reopens only when the check finds a file
it did not list. The check fails when no probe gets an answer, so it never goes blind quietly.
Neither changes a pin or a deploy.

| The build says | What it means | What to do |
|---|---|---|
| `the mirror release T does not hold F (HTTP 404); data-mirror.yml seeds it from the pins` | A pin changed and its release is not seeded, after the preview waited `SNOWLIGHT_MIRROR_WAIT` (480 s, on each of its three tries) for it. | Open the data-mirror run of the push that changed the pin. If an origin was down, re-run that job from its Actions page (Re-run failed jobs) once the origin answers; data-mirror runs only on pin pushes, so nothing re-runs it otherwise. Until it is green every preview fails and the site stays as it is; after it, the next push deploys. |
| `... does not match the pin of URL` | A mirror asset is not the pinned file. | Re-run data-mirror.yml from its Actions page: it stages again any asset whose digest is not the pin's and replaces it. |
| `URL changed upstream: SHA-256 X, config pins Y` in data-mirror.yml | The origin now serves other bytes under a pinned URL. | Review the new file, then pin it as below. Deploys keep reading the release of the old pins meanwhile. |
| `... its code table changed upstream` in data-mirror.yml | The Census LSAD code list changed. | Review the change, then pin the new table's digest as below. |

Bumping a pinned source file:

1. Download the new file and review it. Its pin is `sha256sum FILE`; for the LSAD page it is
   `uv run python -c "import sys, hashlib; from snowlight.sources.mirror import lsad_table_page;
   print(hashlib.sha256(lsad_table_page(open(sys.argv[1]).read())).hexdigest())" PAGE`.
2. For a directory file, add it as the first candidate of its source in
   `pipeline/config/directory.yaml` with its `sha256` (keep the older candidates). For a places
   release, change the year in `pipeline/config/places.yaml` and pin every file it lists; the
   build refuses a pins file that misses one or names one too many.
3. Push. data-mirror.yml seeds the new release and proves it; the Preview of the same push reads
   the files its cache lacks from that release, waiting for the seed up to 8 minutes on each of
   its three tries. If data-mirror fails, see the table above: re-run it from its Actions page.
4. Check both runs: data-mirror green, then the Preview green with its log line
   `Fetching NCES files from the cache, else the data mirror https://github.com/.../data-mirror-<digest>/`.
   A changed directory takes a new edition date as usual; nothing about dating changes.

## What stays open

- `SETTLE` (two minutes) is not measured: spec §9.1 lists Pages deploy-to-visible as unknown,
  and S8-A measures it. A deploy that goes live later than that after its last recorded change
  can be missed: the next build then reads the edition before it, and a changed directory can
  take the missed deploy's date, so two contents share one stamp (spec risk R6). The date only
  ever moves forward from what was read. The live ingest's blank-on-mismatch rule (spec §8
  step 4) covers that case, so it must stay.
- Stamps are kept apart only while deploys are read in order. The default branch's preview
  runs one at a time in the group `pages` and none is cancelled: a newer run waits for the
  running one to end, its deploy included, and of the runs waiting only the newest goes on. So
  each reader reads a deploy that has ended. Pushes to other branches (which build nothing) sit
  in groups of their own. A run cancelled by hand while it deploys can still go live after the
  next run read the deployed edition; the reader then reads the CDN after the run ended, and the
  blank rule covers a deploy that goes live later than `SETTLE` after that.
