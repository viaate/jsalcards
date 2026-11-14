# Fixtures

Files the core tests read from the test bundle. No test reads the network.

Two folders arrive here with the tools that make them, and neither is edited by hand:

- `golden/`: answers made by running the site's own code, one file per family
  (`ios/tools/gen-golden.mjs`).
- `site/`: byte-for-byte copies of the pipeline's synthetic test files
  (`ios/tools/sync-fixtures.mjs`).

Beside them:

- `tour/`: the picture tour's three fixtures, each a school, its record and its two live files,
  made once from the pipeline's synthetic files (M1 5.1) and the source from then on; the
  school-view family reads them. Not edited by hand.
- `rules-version.json`: the app's rules version and the sha256 over every family's cases,
  written by `ios/tools/gen-golden.mjs` beside `golden/`, never in it (RulesVersionTests).

Every school and district name in these files is made up.
