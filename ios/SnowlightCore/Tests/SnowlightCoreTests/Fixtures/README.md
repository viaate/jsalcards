# Fixtures

Files the core tests read from the test bundle. No test reads the network.

Two folders arrive here with the tools that make them, and neither is edited by hand:

- `golden/`: answers made by running the site's own code, one file per family
  (`ios/tools/gen-golden.mjs`).
- `site/`: byte-for-byte copies of the pipeline's synthetic test files
  (`ios/tools/sync-fixtures.mjs`).

Every school and district name in these files is made up.
