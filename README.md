# Snowlight

Snowlight is a near-black map of the continental US where every K-12 school closed, delayed, remote or dismissing early for weather today glows like city lights seen from space.

Live preview of the work in progress: https://viaate.github.io/jsalcards/ (rebuilt on every push to the default branch).

```text
.
├── web/                  Svelte 5 + TypeScript + Vite static site for GitHub Pages
│   ├── src/              App code; every UI string lives in the copy modules, src/copy*.ts
│   ├── public/           Static files served as-is; npm run stage puts the pipeline's outputs in public/data/
│   ├── tests/            Vitest unit and component tests (module tests sit in src/**/tests)
│   ├── e2e/              Playwright smoke tests against the production build
│   └── tools/            Build-time helpers used by vite.config.ts
├── pipeline/             Python 3.12 package "snowlight" (uv) that writes the site's static data
│   ├── snowlight/        Package source
│   └── tests/            pytest and Hypothesis tests, plus contract tests for ci.yml
└── .github/workflows/    CI (web checks, e2e, Lighthouse gates, pipeline checks), the Pages preview, and the archive capture reader
```

## Data

The site reads only what the pipeline writes. To see it with its data:

```sh
cd pipeline
uv sync
uv run snowlight directory build   # schools/: meta.json, points.bin, schools.pmtiles (needs tippecanoe), edition.json
uv run snowlight places build      # search/: cities.jsonl, zips.jsonl
cd ../web
npm ci
npm run stage                      # stages pipeline/out/site-data in public/data/
npm run dev                        # or: npm run build && npm run preview
```

Locally both builds download from NCES and Census as before. Preview's deploy sets `SNOWLIGHT_MIRROR` (the `--mirror` option) instead: every source file then comes from the download cache or the data mirror, a release of this repository holding the pinned files, and never from NCES or Census ([docs/deployed-edition.md](docs/deployed-edition.md), "Source files").

The snow-day chances read each school's height (for alerts that say "above 8,000 feet") from one table that `.github/workflows/elevation.yml` builds from Terrain Tiles by Mapzen on AWS Open Data and keeps in the data mirror, pinned in `pipeline/config/elevation.yaml` ([docs/predict.md](docs/predict.md), "Heights in alerts"). United States 3DEP (formerly NED) and global GMTED2010 and SRTM terrain data courtesy of the U.S. Geological Survey. Global ETOPO1 terrain data courtesy of the U.S. National Oceanic and Atmospheric Administration.

The directory build merges `pipeline/config/directory-supplement.yaml`, real private schools the NCES files miss. It stops, and Preview's deploy with it, when a newly published NCES private school file puts a school near, at the same address as, or under the name of a kept entry (the 2024-25 private geocode file, once a reviewer pins it in `pipeline/config/directory.yaml`; the weekly NCES release check says when NCES publishes it). A reviewer then lists the NCES ids that are other schools in the entry's `distinct_from`, or retires the entry. Entries drop off the map, without stopping the build, when their evidence is from before last school year or their address was not checked since August 1, so every entry is checked again each year before August 1 (its address against the school's own page or its diocese list, its evidence and its grades), and any entry before its evidence turns a year old. The build report, and Preview's log as warnings, list the entries whose evidence or address goes stale within 60 days.

`npm run stage` (`web/scripts/stage-data.mjs`) replaces `web/public/data/` with the pipeline's outputs, which dev, preview and every build then serve under `data/`. The school directory, the school tiles and the search index go under names that carry a hash of their content (`schools/meta.b5c6259854.json`), so browsers can keep them for good; files that change during the day, such as `live/`, keep their names, and so does `schools/edition.json`, which names the directory by its content for the live ingest and the next deploy (the page never reads it). The search index is built from the directory's schools and districts and the places build's cities and ZIP codes. Staging stops, and stages nothing, if an input is missing or does not match the rest.

With nothing staged, the site runs without data: nothing glows, search shows nothing, and no school is drawn. `SNOWLIGHT_DATA=none npm run build` builds that way whatever is staged, as the end-to-end tests do. The Pages preview (`.github/workflows/preview.yml`) runs both pipeline builds, stages their outputs and builds the site with them on every push to the default branch.

The directory's date (`generated_on` in `schools/meta.json`, and so in the stamp every live file carries) names its content; it is not the day of the build. The preview first reads the edition the site serves (`snowlight directory deployed-edition`: made from the directory in the live deploy's artifact through the GitHub API, or a CDN copy fetched after the last deploy settled and checked against the directory the CDN serves the page, since Pages' CDN ignores query strings and no-cache headers and can answer with an earlier deploy's file; "none deployed" only when the live deploy predates editions). An unchanged directory keeps the deployed date, so a redeploy leaves the live files valid. A changed one takes the build's date, or the day after the deployed one when that is already today or later, so the date can run ahead of the calendar. When the deployed edition cannot be read for certain, the preview fails and the site stays as it is; [docs/deployed-edition.md](docs/deployed-edition.md) says what each failure means and how to clear one that lasts. Dates are kept apart only while deploys are read in order, so a live ingest must still publish nothing for a directory whose deployed digest is not its own.
