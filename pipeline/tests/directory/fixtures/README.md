# Directory test fixtures

Every zip here is a slice of the official NCES file with the same name, cut by
`tests/directory/make_fixtures.py` from the copy the build downloaded. No value
is typed by hand or invented.

| Fixture | Source file | What is kept |
|---|---|---|
| `EDGE_GEOCODE_PUBLICSCH_2425.zip` | https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2425.zip | 25 lines of the `.TXT`, unchanged; the `.xlsx` cut to its header row |
| `EDGE_GEOCODE_PUBLICLEA_2425.zip` | https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICLEA_2425.zip | 24 lines of the `.TXT`, unchanged; the `.xlsx` cut to its header row |
| `EDGE_GEOCODE_PRIVATESCH_2324.zip` | https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2324.zip | the `.xlsx` header row and 8 worksheet rows |
| `ccd_sch_029_2425_w_1a_073025.zip` | https://nces.ed.gov/ccd/Data/zip/ccd_sch_029_2425_w_1a_073025.zip | header and 25 lines of the `.csv`, unchanged |
| `ccd_sch_052_2425_l_1a_073025.zip` | https://nces.ed.gov/ccd/Data/zip/ccd_sch_052_2425_l_1a_073025.zip | header and 80 lines of the `.csv` (each school's two total rows and first two detail rows), unchanged |
| `ccd_sch_129_2425_w_1a_073025.zip` | https://nces.ed.gov/ccd/Data/zip/ccd_sch_129_2425_w_1a_073025.zip | header and 22 lines of the `.csv`, unchanged |
| `pss2324_pu_csv.zip` | https://nces.ed.gov/surveys/pss/zip/pss2324_pu_csv.zip | header and 8 lines of the `.csv`, unchanged |

`PROVENANCE.json` records, for each fixture, the source URL, the SHA-256 of the
source zip the slice was cut from, the member names, and the line number (text
files) or worksheet row number (workbooks) of every row kept. It also lists the
school and district ids chosen and why each is there (for example "dropped:
status Closed" or "kept: charter school"); the tests assert those outcomes.

How rows are copied:

- Text members keep the selected lines byte for byte, after the original header
  line when the file has one. The EDGE `.TXT` files have no header line.
- Workbooks are rebuilt as a minimal one-sheet `.xlsx` holding the original
  header row and the selected `<row>` elements with their original row numbers
  and cell values. Only the shared-string indexes are renumbered, into a
  shared-string table cut down to the strings those rows use.
- The source membership zip stores its 2.3 GB member with Deflate64; the fixture
  uses ordinary Deflate. The tests cover the Deflate64 path by streaming a
  fixture through `unzip`.

`tests/directory/test_directory_fixtures.py` checks this record: every fixture is
listed with the SHA-256 pinned in `config/directory.yaml`, and, when the full
source zip with that checksum is in the download cache, every fixture row equals
the source row it was cut from: for text members the line at the recorded line
number, for the private workbook the row with the same PPIN (skipped in a clean
checkout).

Regenerate after a full `uv run snowlight directory build` has filled the cache:

```sh
cd pipeline
uv run python tests/directory/make_fixtures.py
```

Anything synthetic in the tests is built inside the tests and named so: the
`SyntheticTiles` writer in `conftest.py` (which tiles the build's own input when
tippecanoe is not installed, and builds deliberately faulty tilesets to prove
the tile check catches them), small frames for filter edge cases, and payloads
for download-error tests. Nothing in this directory is synthetic.
