# Snowlight

Snowlight is a near-black map of the continental US where every K-12 school closed, delayed, remote or dismissing early for weather today glows like city lights seen from space.

```text
.
├── web/                  Svelte 5 + TypeScript + Vite static site for GitHub Pages
│   ├── src/              App code; every UI string lives in src/copy.ts
│   ├── public/           Static files served as-is
│   ├── tests/            Vitest unit and component tests
│   ├── e2e/              Playwright smoke tests against the production build
│   └── tools/            Build-time helpers used by vite.config.ts
├── pipeline/             Python 3.12 package "snowlight" (uv) that writes the site's static data
│   ├── snowlight/        Package source
│   └── tests/            pytest and Hypothesis tests, plus contract tests for ci.yml
└── .github/workflows/    CI: web checks, e2e smoke test, pipeline checks
```
