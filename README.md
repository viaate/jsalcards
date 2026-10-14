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
uv run snowlight directory build   # schools/: meta.json, points.bin, schools.pmtiles (needs tippecanoe)
uv run snowlight places build      # search/: cities.jsonl, zips.jsonl
cd ../web
npm ci
npm run stage                      # stages pipeline/out/site-data in public/data/
npm run dev                        # or: npm run build && npm run preview
```

The directory build merges `pipeline/config/directory-supplement.yaml`, real private schools the NCES files miss. It stops, and Preview's deploy with it, when a newly published NCES private school file puts a school near, at the same address as, or under the name of a kept entry (the 2024-25 private geocode file is used as soon as NCES publishes it). A reviewer then lists the NCES ids that are other schools in the entry's `distinct_from`, or retires the entry. Entries drop off the map, without stopping the build, when their evidence is from before last school year or their address was not checked since August 1, so every entry is checked again each year before August 1 (its address against the school's own page or its diocese list, its evidence and its grades), and any entry before its evidence turns a year old. The build report, and Preview's log as warnings, list the entries whose evidence or address goes stale within 60 days.

`npm run stage` (`web/scripts/stage-data.mjs`) replaces `web/public/data/` with the pipeline's outputs, which dev, preview and every build then serve under `data/`. The school directory, the school tiles and the search index go under names that carry a hash of their content (`schools/meta.b5c6259854.json`), so browsers can keep them for good; files that change during the day, such as `live/`, keep their names. The search index is built from the directory's schools and districts and the places build's cities and ZIP codes. Staging stops, and stages nothing, if an input is missing or does not match the rest.

With nothing staged, the site runs without data: nothing glows, search shows nothing, and no school is drawn. `SNOWLIGHT_DATA=none npm run build` builds that way whatever is staged, as the end-to-end tests do. The Pages preview (`.github/workflows/preview.yml`) runs both pipeline builds, stages their outputs and builds the site with them on every push to the default branch.
