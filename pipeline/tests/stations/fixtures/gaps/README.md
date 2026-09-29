# Gap-state adapter fixtures (Cowles, Flathead County, county sheets, GOHSEP, district sites)

Every file here is a real response body, live or archived.

Live bodies were read once from the source's server (or the file its closings
page frames) with the pipeline's own client,
`snowlight.sources.stations.http.PoliteClient`, as `gap_fixtures capture` does:
the repository's User-Agent, robots.txt read first and its verdict recorded,
per-host pacing. A live body cannot be downloaded again as it was: its SHA-256 is
the one the capture log recorded when it was read.

Archived bodies are Wayback Machine `id_` captures (the bytes the source served
when the archive read the page), downloaded on GitHub's runners by
`.github/workflows/archive-captures.yml` and added with `gap_fixtures
add-archived`. `Captured` is when the archive read the page (the capture the
archive served, which may be near rather than at the one asked for) and
`Retrieved` when the runner downloaded it. The original SHA-256 is of the bytes as
the archive sent them (a page served gzip-encoded is still gzip): download the
capture link without decoding it, confirm the SHA-256, slice it, and compare bytes.

Bodies are cut with the method named below
(`snowlight.sources.stations.gap_fixtures.SLICERS`): a station page keeps only
the frame naming its list file, the Flathead County page keeps its "Last Updated"
line, its notice card and its closures tables with their headings, a sheet's table
view keeps each cell's text and span, an Apptegy district homepage keeps only its
`__NUXT_DATA__` state (whole), a Finalsite homepage keeps its title, its `<body>`
tag with every attribute (its `data-pageid`) and any page-pop collection it holds,
and list files (the ticker, a sheet's CSV, the GOHSEP layer's query answer, a Smart
Sites alerts file, a Finalsite page-pops answer) are kept whole. Slicing a
slice changes nothing, and a slice reads exactly as its original did (the same
variant, state and row names). Full SHA-256 values and the exact names the adapter
reads are in `PROVENANCE.json`.

This file is generated from the provenance files; edit those, not this.

## Adapter fixtures

| File | Source | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256 | Slice | Variant | State | Rows |
|---|---|---|---|---|---|---|---|---|---:|
| `alsde/closures-20250121.html` | alsde-statewide (archive) | https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx ([capture](https://web.archive.org/web/20250121172646id_/https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx)) | 2025-01-21 17:26:46 | 2026-09-28 16:53:02 | `f57653ff2c123334…` (200148 bytes) | alsde-v1 | alsde-closures-grid | populated | 180 |
| `alsde/closures-20250603.html` | alsde-statewide (archive) | https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx ([capture](https://web.archive.org/web/20250603172615id_/https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx)) | 2025-06-03 17:26:15 | 2026-09-28 19:30:31 | `7e34e1e453be8294…` (374554 bytes) | alsde-v1 | alsde-closures-grid | populated | 387 |
| `alsde/closures-live-20260928.html` | alsde-statewide (live) | https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx | 2026-09-28 14:42:02 | 2026-09-28 14:42:02 | `7fb5b66ba26b621d…` (47742 bytes) | alsde-v1 | alsde-closures-grid | populated | 8 |
| `apptegy/alachua-20241009.html` | apptegy-alachua-fl (archive) | https://www.sbac.edu/ ([capture](https://web.archive.org/web/20241009034101id_/https://www.sbac.edu/)) | 2024-10-09 03:41:01 | 2026-09-27 19:22:19 | `4fa9c0221cc0cc44…` (427492 bytes) | schoolwires-v1 | schoolwires-important-announcements | populated | 1 |
| `apptegy/alpena-live-20260928.html` | apptegy-alpena-mi (live) | https://www.alpenaschools.com/ | 2026-09-28 15:06:58 | 2026-09-28 15:06:58 | `c7715f8ee2c18798…` (1356877 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `apptegy/brevard-20241011.html` | apptegy-brevard-fl (archive) | https://www.brevardschools.org/ ([capture](https://web.archive.org/web/20241011190512id_/https://www.brevardschools.org/)) | 2024-10-11 19:05:12 | 2026-09-27 18:57:55 | `950516d1e84bad4a…` (881849 bytes) | apptegy-v2 | apptegy-nuxt2-state | populated | 1 |
| `apptegy/brownsville-live-20260928.html` | apptegy-brownsville-tx (live) | https://www.bisd.us/ | 2026-09-28 01:43:41 | 2026-09-28 01:43:41 | `7b9e1ae9346fe506…` (1618092 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 3 |
| `apptegy/cassia-20250214.html` | apptegy-cassia-id (archive) | https://www.cassiaschools.org/ ([capture](https://web.archive.org/web/20250214111150id_/https://www.cassiaschools.org/)) | 2025-02-14 11:11:50 | 2026-09-27 19:36:09 | `0e9da3c8688c50d1…` (1048576 bytes) | apptegy-v2 | apptegy-nuxt-state | empty | 0 |
| `apptegy/corpus-christi-live-20260928.html` | apptegy-corpus-christi-tx (live) | https://www.ccisd.us/ | 2026-09-28 01:43:29 | 2026-09-28 01:43:29 | `bff0039c3a9d2a4d…` (1398163 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `apptegy/fremont-6-live-20260927.html` | apptegy-fremont-6-wy (live) | https://www.fremont6.org/ | 2026-09-27 19:40:12 | 2026-09-27 19:40:12 | `af75e1cc34953482…` (1298508 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `apptegy/fremont25-20251205.html` | apptegy-fremont25-wy (archive) | https://www.fremont25.org/ ([capture](https://web.archive.org/web/20251205090925id_/https://www.fremont25.org/)) | 2025-12-05 09:09:25 | 2026-09-27 20:30:53 | `645f6db6fc385ba7…` (1200381 bytes) | apptegy-v2 | apptegy-nuxt-state | empty | 0 |
| `apptegy/fremont25-live-20260927.html` | apptegy-fremont25-wy (live) | https://www.fremont25.org/ | 2026-09-27 15:28:27 | 2026-09-27 15:28:27 | `693cae3f987380aa…` (1222816 bytes) | apptegy-v1 | apptegy-nuxt-state | empty | 0 |
| `apptegy/hamilton-20250216.html` | apptegy-hamilton-mt (archive) | https://www.hsd3.org/ ([capture](https://web.archive.org/web/20250216092010id_/https://www.hsd3.org/)) | 2025-02-16 09:20:10 | 2026-09-28 01:13:00 | `6ab3bdeccd9d0819…` (228894 bytes) | apptegy-v2 | apptegy-nuxt-state | populated | 1 |
| `apptegy/hardin-20221221.html` | apptegy-hardin-mt (archive) | https://www.hardin.k12.mt.us/ ([capture](https://web.archive.org/web/20221221103018id_/https://www.hardin.k12.mt.us/)) | 2022-12-21 10:30:18 | 2026-09-28 11:29:00 | `41d1564a4d4599c9…` (61782 bytes) | campussuite-v1 | campussuite-alert-banner | populated | 1 |
| `apptegy/hardin-20230327.html` | apptegy-hardin-mt (archive) | https://www.hardin.k12.mt.us/ ([capture](https://web.archive.org/web/20230327192646id_/https://www.hardin.k12.mt.us/)) | 2023-03-27 19:26:46 | 2026-09-28 11:28:53 | `b4c17ed732e9b25c…` (58318 bytes) | campussuite-v1 | campussuite-alert-banner | empty | 0 |
| `apptegy/hillsborough-live-20260927.html` | apptegy-hillsborough-fl (live) | https://www.hillsboroughschools.org/ | 2026-09-27 15:26:30 | 2026-09-27 15:26:30 | `9b28146a6fc5103c…` (1537815 bytes) | apptegy-v1 | apptegy-nuxt-state | empty | 0 |
| `apptegy/lake-live-20260927.html` | apptegy-lake-fl (live) | https://www.lake.k12.fl.us/ | 2026-09-27 15:26:47 | 2026-09-27 15:26:47 | `2dbbfb081f935587…` (1632894 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `apptegy/manatee-20241009.html` | apptegy-manatee-fl (archive) | https://www.manateeschools.net/ ([capture](https://web.archive.org/web/20241009114003id_/https://www.manateeschools.net/)) | 2024-10-09 11:40:03 | 2026-09-27 19:01:39 | `df555cf7631aa30f…` (604623 bytes) | schoolwires-v1 | schoolwires-important-announcements | populated | 1 |
| `apptegy/martin-20220928.html` | apptegy-martin-fl (archive) | https://www.martinschools.org/ ([capture](https://web.archive.org/web/20220928113027id_/https://www.martinschools.org/)) | 2022-09-28 11:30:27 | 2026-09-27 20:02:03 | `20229d34245ec97d…` (543198 bytes) | apptegy-v2 | apptegy-nuxt2-state | populated | 1 |
| `apptegy/martin-20241009.html` | apptegy-martin-fl (archive) | https://www.martinschools.org/ ([capture](https://web.archive.org/web/20241009183831id_/https://www.martinschools.org/)) | 2024-10-09 18:38:31 | 2026-09-27 19:55:30 | `f5586f9aab2b2d1f…` (874066 bytes) | apptegy-v2 | apptegy-nuxt2-state | populated | 1 |
| `apptegy/martin-live-20260927.html` | apptegy-martin-fl (live) | https://www.martinschools.org/ | 2026-09-27 15:27:31 | 2026-09-27 15:27:31 | `15f09e49e2544b84…` (1513136 bytes) | apptegy-v1 | apptegy-nuxt-state | empty | 0 |
| `apptegy/mobile-live-20260928.html` | apptegy-mobile-al (live) | https://www.mcpss.com/ | 2026-09-28 14:27:36 | 2026-09-28 14:27:36 | `3fbaaf89b58be729…` (1396833 bytes) | apptegy-v1 | apptegy-nuxt-state | empty | 0 |
| `apptegy/monroe-20241007.html` | apptegy-monroe-fl (archive) | https://www.keysschools.com/ ([capture](https://web.archive.org/web/20241007224045id_/https://www.keysschools.com/)) | 2024-10-07 22:40:45 | 2026-09-27 20:53:23 | `a3f70febc4987f71…` (425154 bytes) | schoolwires-v1 | schoolwires-important-announcements | populated | 1 |
| `apptegy/putnam-20241012.html` | apptegy-putnam-fl (archive) | https://www.putnamschools.org/ ([capture](https://web.archive.org/web/20241012163838id_/https://www.putnamschools.org/)) | 2024-10-12 16:38:38 | 2026-09-27 20:33:24 | `2e5131b34c6ead8c…` (805358 bytes) | apptegy-v2 | apptegy-nuxt2-state | empty | 0 |
| `apptegy/santa-rosa-live-20260928.html` | apptegy-santa-rosa-fl (live) | https://www.santarosaschools.org/ | 2026-09-28 14:32:17 | 2026-09-28 14:32:17 | `c699d227bdf00858…` (1554745 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `apptegy/sarasota-20240924.html` | apptegy-sarasota-fl (archive) | https://www.sarasotacountyschools.net/ ([capture](https://web.archive.org/web/20240924213703id_/https://www.sarasotacountyschools.net/)) | 2024-09-24 21:37:03 | 2026-09-27 19:33:34 | `b093cde8d8617502…` (841448 bytes) | apptegy-v2 | apptegy-nuxt2-state | populated | 1 |
| `apptegy/st-ignatius-live-20260927.html` | apptegy-st-ignatius-mt (live) | https://web.stignatiusschools.org/ | 2026-09-27 19:29:54 | 2026-09-27 19:29:54 | `6509349eb80bce9e…` (1252885 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `apptegy/sweetwater-2-live-20260927.html` | apptegy-sweetwater-2-wy (live) | https://www.swcsd2.org/ | 2026-09-27 19:39:30 | 2026-09-27 19:39:30 | `502b1d5b13af48d1…` (1257731 bytes) | apptegy-v1 | apptegy-nuxt-state | populated | 1 |
| `coesheet/shasta-page-20241021.html` | coesheet-shasta (archive) | https://www.shastacoe.org/office-of-education/school-closures ([capture](https://web.archive.org/web/20241021235424id_/https://www.shastacoe.org/office-of-education/school-closures)) | 2024-10-21 23:54:24 | 2026-09-27 12:25:48 | `939d7b9cfe60869b…` (43163 bytes) | coesheet-v1 | coesheet-page | deferred | 0 |
| `coesheet/shasta-page-live-20260927.html` | coesheet-shasta (live) | https://www.shastacoe.org/office-of-education/school-closures | 2026-09-27 11:48:54 | 2026-09-27 11:48:54 | `0272aeb7d8681297…` (47213 bytes) | coesheet-v1 | coesheet-page | deferred | 0 |
| `coesheet/shasta-sheet-live-20260927.csv` | coesheet-shasta (live) | https://docs.google.com/spreadsheets/d/e/2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_/pub?gid=541890420&single=true&output=csv | 2026-09-27 11:49:05 | 2026-09-27 11:49:05 | `c17ce033dc59be41…` (4942 bytes) | coesheet-v1 | coesheet-csv | populated | 95 |
| `coesheet/shasta-tab-live-20260927.html` | coesheet-shasta (live) | https://docs.google.com/spreadsheets/d/e/2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_/pubhtml/sheet?headers=false&gid=541890420 | 2026-09-27 11:52:57 | 2026-09-27 11:52:57 | `b9127671af3cc3a0…` (106661 bytes) | coesheet-v1 | coesheet-table | populated | 95 |
| `coesheet/shasta-widget-20230617.html` | coesheet-shasta (archive) | https://docs.google.com/spreadsheets/d/e/2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_/pubhtml?gid=541890420&single=true&widget=true&headers=false ([capture](https://web.archive.org/web/20230617153827id_/https://docs.google.com/spreadsheets/d/e/2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_/pubhtml?gid=541890420&single=true&widget=true&headers=false)) | 2023-06-17 15:38:27 | 2026-09-27 12:09:56 | `73c390fb510266c4…` (8123 bytes) | coesheet-v1 | coesheet-widget | deferred | 0 |
| `coesheet/shasta-widget-live-20260927.html` | coesheet-shasta (live) | https://docs.google.com/spreadsheets/d/e/2PACX-1vRt_q35uHlnknDJQ9VW3PzAu5a8qJdFvqA6gBrKOcLHp1Wx0toWwCFmDDqBh6ak38JSB0nC_Om6VOA_/pubhtml?gid=541890420&single=true&widget=true&headers=false | 2026-09-27 11:52:52 | 2026-09-27 11:52:52 | `47e4a687ae9bb86f…` (53176 bytes) | coesheet-v1 | coesheet-widget | deferred | 0 |
| `coesheet/trinity-page-20260516.html` | coesheet-trinity (archive) | https://www.tcoek12.org/school-districts/school-closure-information ([capture](https://web.archive.org/web/20260516132206id_/https://www.tcoek12.org/school-districts/school-closure-information)) | 2026-05-16 13:22:06 | 2026-09-27 12:15:13 | `be17a8069c9cd2e3…` (58470 bytes) | coesheet-v1 | coesheet-page | deferred | 0 |
| `coesheet/trinity-page-live-20260927.html` | coesheet-trinity (live) | https://www.tcoek12.org/school-districts/school-closure-information | 2026-09-27 12:01:19 | 2026-09-27 12:01:19 | `5834186d8a78a82a…` (59599 bytes) | coesheet-v1 | coesheet-page | deferred | 0 |
| `coesheet/trinity-sheet-live-20260927.html` | coesheet-trinity (live) | https://docs.google.com/spreadsheets/d/e/2PACX-1vRzrIeQ579iJDJCzp_oD9jDkAFAsjdNUHS-qY1Xe-_-kRRHyLaUS0av9-eoKHphpMPKr4HUVpEMTUiX/pubhtml?gid=0&single=true&widget=false&headers=false | 2026-09-27 12:01:25 | 2026-09-27 12:01:25 | `56682603b3f03656…` (63924 bytes) | coesheet-v1 | coesheet-table | populated | 17 |
| `cowles/kulr-page-live-20260927.html` | cowles-kulr (live) | https://www.kulr8.com/schoolclosures/ | 2026-09-27 11:25:52 | 2026-09-27 11:25:52 | `71e7f8ad9848c230…` (252287 bytes) | cowles-v1 | cowles-page | deferred | 0 |
| `cowles/nonstop-page-live-20260927.html` | cowles-kfbb (live) | https://www.montanarightnow.com/schoolclosures/ | 2026-09-27 11:25:57 | 2026-09-27 11:25:57 | `60160c017dc50034…` (219754 bytes) | cowles-v1 | cowles-page | deferred | 0 |
| `cowles/ticker-live-20260927.html` | cowles-kulr (live) | https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html | 2026-09-27 11:25:46 | 2026-09-27 11:25:46 | `264e80991a023073…` (229 bytes) | cowles-v1 | closings-grid | empty | 0 |
| `dadeschools/alerts-20241009.json` | dadeschools-miami-dade-fl (archive) | https://mainapi.dadeschools.net/api/v1/alerts ([capture](https://web.archive.org/web/20241009144114id_/https://mainapi.dadeschools.net/api/v1/alerts)) | 2024-10-09 14:41:14 | 2026-09-27 21:01:10 | `fbe731ef62cdc40a…` (3350 bytes) | none | dadeschools-alerts | populated | 1 |
| `dadeschools/alerts-live-20260927.json` | dadeschools-miami-dade-fl (live) | https://mainapi.dadeschools.net/api/v1/alerts/ | 2026-09-27 23:21:08 | 2026-09-27 23:21:08 | `278c3df678d91c97…` (2670 bytes) | none | dadeschools-alerts | empty | 0 |
| `edlio/edinburg-live-20260928.html` | edlio-edinburg-tx (live) | https://www.ecisd.us/ | 2026-09-28 09:31:26 | 2026-09-28 09:31:26 | `e9234bd98d88732c…` (51215 bytes) | edlio-v1 | edlio-homepage-alert | empty | 0 |
| `edlio/hidalgo-20250120.html` | edlio-hidalgo-tx (archive) | https://www.hidalgo-isd.org/ ([capture](https://web.archive.org/web/20250120123341id_/https://www.hidalgo-isd.org/)) | 2025-01-20 12:33:41 | 2026-09-28 11:03:36 | `593e82db202a1e24…` (60787 bytes) | edlio-v1 | edlio-homepage-alert | populated | 1 |
| `edlio/lake-elsinore-live-20260928.html` | edlio-lake-elsinore-ca (live) | https://www.leusd.k12.ca.us/ | 2026-09-28 15:16:01 | 2026-09-28 15:16:01 | `a3c16e8b8f59946e…` (95360 bytes) | edlio-v1 | edlio-homepage-alert | populated | 1 |
| `edlio/los-fresnos-20250121.html` | edlio-los-fresnos-tx (archive) | https://www.lfcisd.net/ ([capture](https://web.archive.org/web/20250121230836id_/https://www.lfcisd.net/)) | 2025-01-21 23:08:36 | 2026-09-28 10:43:07 | `9c71e88338fd2ff0…` (495991 bytes) | edlio-v1 | edlio-homepage-alert | populated | 1 |
| `edlio/mission-20250121.html` | edlio-mission-tx (archive) | https://www.mcisd.net/ ([capture](https://web.archive.org/web/20250121111020id_/https://www.mcisd.net/)) | 2025-01-21 11:10:20 | 2026-09-28 09:14:57 | `7fb64a36c04d5705…` (63015 bytes) | edlio-v1 | edlio-homepage-alert | populated | 1 |
| `edlio/natrona-live-20260928.html` | edlio-natrona-wy (live) | https://www.natronaschools.org/ | 2026-09-28 09:31:14 | 2026-09-28 09:31:14 | `a9672cdf55dbf4ce…` (69628 bytes) | edlio-v1 | edlio-homepage-alert | empty | 0 |
| `edlio/sublette-9-live-20260928.html` | edlio-sublette-9-wy (live) | https://www.sublette9.org/ | 2026-09-28 09:31:14 | 2026-09-28 09:31:14 | `c43d024a6c76206a…` (105293 bytes) | edlio-v1 | edlio-homepage-alert | populated | 1 |
| `finalsite/baldwin-home-live-20260928.html` | finalsite-baldwin-al (live) | https://www.bcbe.org/ | 2026-09-28 22:35:24 | 2026-09-28 22:35:24 | `edb33cc01f383d7c…` (107743 bytes) | finalsite-v1 | finalsite-homepage | deferred | 0 |
| `finalsite/baldwin-page-pops-live-20260928.html` | finalsite-baldwin-al (live) | https://www.bcbe.org/fs/pages/10398/page-pops | 2026-09-28 14:30:57 | 2026-09-28 14:30:57 | `e3b0c44298fc1c14…` (0 bytes) | none | finalsite-no-page-pops | empty | 0 |
| `finalsite/billings-home-live-20260928.html` | finalsite-billings-mt (live) | https://www.billingsschools.org/ | 2026-09-28 22:29:54 | 2026-09-28 22:29:54 | `c3130038e0909874…` (105298 bytes) | finalsite-v1 | finalsite-homepage | deferred | 0 |
| `finalsite/billings-page-pops-live-20260927.html` | finalsite-billings-mt (live) | https://www.billingsschools.org/fs/pages/2465/page-pops | 2026-09-27 15:54:19 | 2026-09-27 15:54:19 | `e3b0c44298fc1c14…` (0 bytes) | none | finalsite-no-page-pops | empty | 0 |
| `finalsite/broward-page-pops-live-20260927.html` | finalsite-broward-fl (live) | https://www.browardschools.com/fs/pages/2/page-pops | 2026-09-27 15:53:48 | 2026-09-27 15:53:48 | `85127bfa2568735c…` (2398 bytes) | none | finalsite-page-pops | populated | 1 |
| `finalsite/chickasaw-home-live-20260928.html` | finalsite-chickasaw-al (live) | https://www.chickasawschools.com/ | 2026-09-28 22:35:35 | 2026-09-28 22:35:35 | `a9641cf00141027c…` (66541 bytes) | finalsite-v1 | finalsite-homepage | deferred | 0 |
| `finalsite/chickasaw-page-pops-live-20260928.html` | finalsite-chickasaw-al (live) | https://www.chickasawschools.com/fs/pages/2/page-pops | 2026-09-28 14:31:07 | 2026-09-28 14:31:07 | `69bba2504327a545…` (1089 bytes) | none | finalsite-page-pops | populated | 1 |
| `finalsite/great-falls-page-pops-live-20260927.html` | finalsite-great-falls-mt (live) | https://gfps.k12.mt.us/fs/pages/3076/page-pops | 2026-09-27 15:54:24 | 2026-09-27 15:54:24 | `ab8fa0f263a2145a…` (987 bytes) | none | finalsite-page-pops | populated | 1 |
| `finalsite/gulf-shores-home-20201101.html` | finalsite-gulf-shores-al (archive) | https://www.gsboe.org/ ([capture](https://web.archive.org/web/20201101024205id_/https://www.gsboe.org/)) | 2020-11-01 02:42:05 | 2026-09-28 16:14:30 | `adb0f753fc75376b…` (95940 bytes) | finalsite-v1 | finalsite-homepage | deferred | 0 |
| `finalsite/gulf-shores-home-20250121.html` | finalsite-gulf-shores-al (archive) | https://www.gsboe.org/ ([capture](https://web.archive.org/web/20250121173214id_/https://www.gsboe.org/)) | 2025-01-21 17:32:14 | 2026-09-28 16:13:45 | `690da806f4c28d3b…` (15364 bytes) | finalsite-v1 | finalsite-homepage | deferred | 0 |
| `finalsite/havre-page-pops-live-20260927.html` | finalsite-havre-mt (live) | https://www.blueponyk12.com/fs/pages/2/page-pops | 2026-09-27 19:51:07 | 2026-09-27 19:51:07 | `c6c0b78ab1356336…` (1218 bytes) | none | finalsite-page-pops | populated | 1 |
| `finalsite/hellgate-page-pops-live-20260927.html` | finalsite-hellgate-mt (live) | https://www.hellgate.k12.mt.us/fs/pages/2/page-pops | 2026-09-27 19:35:46 | 2026-09-27 19:35:46 | `0ca773dfe830c1f8…` (1936 bytes) | none | finalsite-page-pops | populated | 1 |
| `finalsite/hendry-page-pops-live-20260927.html` | finalsite-hendry-fl (live) | https://www.hendry-schools.org/fs/pages/2/page-pops | 2026-09-27 20:18:31 | 2026-09-27 20:18:31 | `16d2de2bd4470b79…` (2807 bytes) | none | finalsite-page-pops | populated | 3 |
| `finalsite/lewistown-page-pops-live-20260927.html` | finalsite-lewistown-mt (live) | https://www.lewistown.k12.mt.us/fs/pages/2/page-pops | 2026-09-27 19:24:52 | 2026-09-27 19:24:52 | `0a233590e50d821b…` (1535 bytes) | none | finalsite-page-pops | populated | 1 |
| `finalsite/palm-beach-home-20241010.html` | finalsite-palm-beach-fl (archive) | https://www.palmbeachschools.org/ ([capture](https://web.archive.org/web/20241010025056id_/https://www.palmbeachschools.org/)) | 2024-10-10 02:50:56 | 2026-09-27 22:08:09 | `0c27620b25bd70d6…` (117164 bytes) | finalsite-v1 | schoolwires-important-announcements | populated | 1 |
| `finalsite/psja-page-pops-live-20260928.html` | finalsite-psja-tx (live) | https://www.psjaisd.us/fs/pages/2/page-pops | 2026-09-28 02:03:03 | 2026-09-28 02:03:03 | `e3b0c44298fc1c14…` (0 bytes) | none | finalsite-no-page-pops | empty | 0 |
| `finalsite/south-texas-page-pops-live-20260928.html` | finalsite-south-texas-tx (live) | https://www.stisd.net/fs/pages/2/page-pops | 2026-09-28 02:15:20 | 2026-09-28 02:15:20 | `ebe23c9fc0aeba35…` (7847 bytes) | none | finalsite-page-pops | populated | 2 |
| `finalsite/volusia-home-20241014.html` | finalsite-volusia-fl (archive) | https://www.vcsedu.org/ ([capture](https://web.archive.org/web/20241014005904id_/https://www.vcsedu.org/)) | 2024-10-14 00:59:04 | 2026-09-27 22:34:06 | `676352fec1c957f2…` (182629 bytes) | finalsite-v1 | finalsite-homepage-pops | populated | 1 |
| `flathead/closures-20250427.html` | flathead-county (archive) | https://flatheadcounty.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20250427035921id_/https://flatheadcounty.gov/department-directory/schools/emergency-school-closures)) | 2025-04-27 03:59:21 | 2026-09-27 11:59:01 | `3180424d6ba29976…` (57085 bytes) | flathead-v1 | flathead-card-tables | populated | 35 |
| `flathead/closures-20260119.html` | flathead-county (archive) | https://flatheadcounty.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20260119015206id_/https://flatheadcounty.gov/department-directory/schools/emergency-school-closures)) | 2026-01-19 01:52:06 | 2026-09-27 12:06:54 | `a26eb3d68facdfd7…` (58504 bytes) | flathead-v1 | flathead-card-tables | populated | 35 |
| `flathead/closures-20260412.html` | flathead-county (archive) | https://flatheadcounty.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20260412231810id_/https://flatheadcounty.gov/department-directory/schools/emergency-school-closures)) | 2026-04-12 23:18:10 | 2026-09-27 12:06:59 | `2b4572ef2db15196…` (57873 bytes) | flathead-v1 | flathead-card-tables | populated | 35 |
| `flathead/closures-20260815.html` | flathead-county (archive) | https://www.flatheadcounty.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20260815020538id_/https://www.flatheadcounty.gov/department-directory/schools/emergency-school-closures)) | 2026-08-15 02:05:38 | 2026-09-27 12:07:05 | `8def61f59bd0c2fc…` (65142 bytes) | flathead-v1 | flathead-closure-tables | populated | 35 |
| `flathead/closures-live-20260927.html` | flathead-county (live) | https://flatheadcounty.gov/department-directory/schools/emergency-school-closures | 2026-09-27 11:26:03 | 2026-09-27 11:26:03 | `03971dcae00e8c09…` (65132 bytes) | flathead-v1 | flathead-closure-tables | populated | 35 |
| `flathead/closures-oldsite-20230103.html` | flathead-county (archive) | https://flathead.mt.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20230103134706id_/https://flathead.mt.gov/department-directory/schools/emergency-school-closures)) | 2023-01-03 13:47:06 | 2026-09-27 13:46:55 | `093dad3d0e581d92…` (53514 bytes) | flathead-v1 | flathead-card-tables | populated | 34 |
| `flathead/closures-oldsite-20240209.html` | flathead-county (archive) | https://flathead.mt.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20240209104252id_/https://flathead.mt.gov/department-directory/schools/emergency-school-closures)) | 2024-02-09 10:42:52 | 2026-09-27 13:54:44 | `c9442adc5f4745a2…` (54147 bytes) | flathead-v1 | flathead-card-tables | populated | 34 |
| `flathead/closures-oldsite-20250227.html` | flathead-county (archive) | https://flathead.mt.gov/department-directory/schools/emergency-school-closures ([capture](https://web.archive.org/web/20250227002745id_/https://flathead.mt.gov/department-directory/schools/emergency-school-closures)) | 2025-02-27 00:27:45 | 2026-09-27 14:19:18 | `928873421b7fbf8b…` (59264 bytes) | flathead-v1 | flathead-card-tables | populated | 35 |
| `gohsep/query-live-20260927.json` | gohsep-parish-schools (live) | https://services1.arcgis.com/fXHQyq63u0UsTeSM/arcgis/rest/services/Parish_School_Closures_Public_View_Layer/FeatureServer/0/query?where=1%3D1&outFields=OBJECTID%2CGEOID%2CNAME%2CDATE_GROUP%2CCLOSURE_DATE%2CSTATUS&returnGeometry=false&orderByFields=GEOID%2CDATE_GROUP&f=json | 2026-09-27 15:20:23 | 2026-09-27 15:20:23 | `bbcf8edf872bf042…` (82872 bytes) | none | gohsep-feature-query | populated | 640 |
| `npg/kq2-closings-20190405.html` | npg-kqtv (archive) | https://ftp2.kq2.com/closings.html ([capture](https://web.archive.org/web/20190405154935id_/https://ftp2.kq2.com/closings.html)) | 2019-04-05 15:49:35 | 2026-09-28 17:24:00 | `394ff3f19b0bc526…` (625 bytes) | none | npg-no-closings | empty | 0 |
| `npg/kq2-closings-20200408.html` | npg-kqtv (archive) | https://ftp2.kq2.com/closings.html ([capture](https://web.archive.org/web/20200408134548id_/https://ftp2.kq2.com/closings.html)) | 2020-04-08 13:45:48 | 2026-09-28 19:34:05 | `e01ed4d1e375e71d…` (14036 bytes) | none | newsticker-html | populated | 63 |
| `npg/kq2-closings-20210128.html` | npg-kqtv (archive) | http://ftp2.kq2.com/closings.html ([capture](https://web.archive.org/web/20210128140316id_/http://ftp2.kq2.com/closings.html)) | 2021-01-28 14:03:16 | 2026-09-28 19:35:42 | `ecf8f358408f0a13…` (752 bytes) | none | newsticker-html | populated | 1 |
| `npg/kq2-closings-20231208.html` | npg-kqtv (archive) | http://ftp2.kq2.com/closings.html ([capture](https://web.archive.org/web/20231208151924id_/http://ftp2.kq2.com/closings.html)) | 2023-12-08 15:19:24 | 2026-09-28 17:41:25 | `de16f93619feb934…` (1087 bytes) | none | newsticker-html | populated | 2 |
| `npg/kq2-closings-live-20260928.html` | npg-kqtv (live) | https://ftp2.kq2.com/closings.html | 2026-09-28 14:50:34 | 2026-09-28 14:50:34 | `b150614a92829e04…` (626 bytes) | none | npg-no-closings | empty | 0 |
| `npg/kq2-page-live-20260928.html` | npg-kqtv (live) | https://www.kq2.com/weather/closings/ | 2026-09-28 14:50:03 | 2026-09-28 14:50:03 | `bda18f59df1c7fbb…` (355912 bytes) | npg-v1 | npg-closings-page | deferred | 0 |
| `pasco/home-20221003.html` | pasco-county-fl (archive) | https://pasco.k12.fl.us/ ([capture](https://web.archive.org/web/20221003142234id_/https://pasco.k12.fl.us/)) | 2022-10-03 14:22:34 | 2026-09-27 22:31:28 | `ae36af0c82c82eba…` (41041 bytes) | pasco-v1 | pasco-red-rectangle | populated | 1 |
| `pasco/home-20241009.html` | pasco-county-fl (archive) | http://www.pasco.k12.fl.us/ ([capture](https://web.archive.org/web/20241009092654id_/http://www.pasco.k12.fl.us/)) | 2024-10-09 09:26:54 | 2026-09-27 22:30:24 | `03b6bc750ed66e89…` (55058 bytes) | pasco-v1 | pasco-emergency-banner | populated | 1 |
| `pasco/home-live-20260927.html` | pasco-county-fl (live) | https://www.pasco.k12.fl.us/ | 2026-09-27 23:11:32 | 2026-09-27 23:11:32 | `303bcf851069b790…` (54267 bytes) | pasco-v1 | pasco-emergency-banner | empty | 0 |
| `schoolblocks/browning-live-20260928.html` | schoolblocks-browning-mt (live) | https://www.bps.k12.mt.us/en-US | 2026-09-28 10:45:10 | 2026-09-28 10:45:10 | `5ced1d230e57f411…` (299088 bytes) | schoolblocks-v1 | schoolblocks-org-alerts | empty | 0 |
| `schoolblocks/grace-live-20260928.html` | schoolblocks-grace-id (live) | https://www.sd148.org/en-US | 2026-09-28 10:45:50 | 2026-09-28 10:45:50 | `592134e0510726ff…` (231822 bytes) | schoolblocks-v1 | schoolblocks-org-alerts | populated | 1 |
| `schoolblocks/monroe-al-live-20260928.html` | schoolblocks-monroe-al (live) | https://www.monroe.k12.al.us/en-US | 2026-09-28 15:09:59 | 2026-09-28 15:09:59 | `3d3fddb2e157a70a…` (260104 bytes) | schoolblocks-v1 | schoolblocks-org-alerts | empty | 0 |
| `schoolblocks/uinta-1-live-20260928.html` | schoolblocks-uinta-1-wy (live) | https://www.uinta1.com/ | 2026-09-28 10:45:14 | 2026-09-28 10:45:14 | `70eee9348b60be99…` (341469 bytes) | schoolblocks-v1 | schoolblocks-org-alerts | empty | 0 |
| `smartsites/belgrade-popup-alerts-20260814.json` | smartsites-belgrade-mt (archive) | https://www.bsd44.org/api/popup-alerts ([capture](https://web.archive.org/web/20260814172158id_/https://www.bsd44.org/api/popup-alerts)) | 2026-08-14 17:21:58 | 2026-09-27 21:46:50 | `c807e552f90716d6…` (733 bytes) | none | smartsites-popup-alerts | populated | 2 |
| `smartsites/belgrade-popup-alerts-live-20260927.json` | smartsites-belgrade-mt (live) | https://www.bsd44.org/api/popup-alerts | 2026-09-27 15:45:06 | 2026-09-27 15:45:06 | `f8b40f0791c6fef9…` (740 bytes) | none | smartsites-popup-alerts | populated | 1 |
| `smartsites/coachella-valley-popup-alerts-live-20260928.json` | smartsites-coachella-valley-ca (live) | https://www.cvusd.us/api/popup-alerts | 2026-09-28 15:20:32 | 2026-09-28 15:20:32 | `9f29982b51c10f48…` (536 bytes) | none | smartsites-popup-alerts | populated | 1 |
| `smartsites/laramie-1-popup-alerts-live-20260927.json` | smartsites-laramie-1-wy (live) | https://www.laramie1.org/api/popup-alerts | 2026-09-27 19:24:42 | 2026-09-27 19:24:42 | `e1c2ec01d08038ea…` (32 bytes) | none | smartsites-popup-alerts | empty | 0 |
| `smartsites/leon-home-20240805.html` | smartsites-leon-fl (archive) | https://www.leonschools.net/ ([capture](https://web.archive.org/web/20240805114155id_/https://www.leonschools.net/)) | 2024-08-05 11:41:55 | 2026-09-28 00:37:43 | `98c3fae93d37fa81…` (787335 bytes) | schoolwires-v1 | schoolwires-important-announcements | populated | 1 |
| `smartsites/orange-popup-alerts-live-20260927.json` | smartsites-orange-fl (live) | https://www.ocps.net/api/popup-alerts | 2026-09-27 15:44:41 | 2026-09-27 15:44:41 | `e1c2ec01d08038ea…` (32 bytes) | none | smartsites-popup-alerts | empty | 0 |
| `smartsites/osceola-home-20220928.html` | smartsites-osceola-fl (archive) | https://www.osceolaschools.net/ ([capture](https://web.archive.org/web/20220928142046id_/https://www.osceolaschools.net/)) | 2022-09-28 14:20:46 | 2026-09-27 22:32:47 | `b76304286b6ce9e2…` (561016 bytes) | schoolwires-v1 | schoolwires-important-announcements | populated | 1 |
| `smartsites/osceola-home-20241010.html` | smartsites-osceola-fl (archive) | https://www.osceolaschools.net/ ([capture](https://web.archive.org/web/20241010044321id_/https://www.osceolaschools.net/)) | 2024-10-10 04:43:21 | 2026-09-27 22:32:41 | `51c5567e23910ebd…` (605189 bytes) | schoolwires-v1 | schoolwires-important-announcements | empty | 0 |
| `smartsites/tuloso-midway-popup-alerts-live-20260928.json` | smartsites-tuloso-midway-tx (live) | https://www.tmisd.us/api/popup-alerts | 2026-09-28 02:15:06 | 2026-09-28 02:15:06 | `e50cc604172591ae…` (1001 bytes) | none | smartsites-popup-alerts | populated | 1 |

Notes:

- `alsde/closures-20250121.html`: The statewide list in the January 2025 Gulf Coast snowstorm (captured 2025-01-21 17:26 UTC): 116 reports of 54 systems, most for 'All Schools' (rows named for the system).
- `alsde/closures-20250603.html`: The statewide list at the end of the 2024-25 school year (captured 2025-06-03 17:26 UTC): the year's 387 rows from 67 systems, among them Baldwin County's and Satsuma City's snow closings of 2025-01-21 to 2025-01-24.
- `alsde/closures-live-20260928.html`: The statewide list as served: four reports (Pike County's early dismissal of 2026-09-25, Perry County's closings of 2026-09-16 and 2026-08-24, Tallapoosa County's of 2026-09-14), one row per school named.
- `apptegy/alpena-live-20260928.html`: One banner, a meal-benefits form: not a closing.
- `apptegy/brownsville-live-20260928.html`: Brownsville ISD's three published banners, all hiring calls: read, but they prove nothing.
- `apptegy/corpus-christi-live-20260928.html`: Corpus Christi ISD's one published banner (its mobile app), not a closing: read, but it proves nothing.
- `apptegy/fremont25-live-20260927.html`: One banner published with no words (content '<p></p>', no image): a skipped row, the list empty.
- `apptegy/hamilton-20250216.html`: Hamilton's banner on a February 2025 winter-warning day: phone trouble with an outside carrier, not a closing.
- `apptegy/hardin-20221221.html`: Hardin's homepage before its Apptegy site, a Campus Suite page: the alert banner 'School Closure Wednesday, Dec. 21st 2022' for extreme cold (a closing: proves the source).
- `apptegy/hardin-20230327.html`: The same Campus Suite homepage with no alert up: an empty alert banner widget.
- `apptegy/hillsborough-live-20260927.html`: No banner shown; the state keeps 13 banners not shown (closed or archived), none of them rows.
- `apptegy/lake-live-20260927.html`: A published banner (the board naming a superintendent) and drafts not shown (Lake's reopening after Milton, 'Schools and district offices are open today'), which are not rows.
- `apptegy/martin-live-20260927.html`: No banner shown; a draft 'HURRICANE MILTON UPDATE' banner (Oct 2024) is kept in the state but not shown, so it is not a row.
- `apptegy/mobile-live-20260928.html`: Mobile County Public Schools' homepage: no banner published (an empty list).
- `apptegy/santa-rosa-live-20260928.html`: One banner, a Title I parent survey: not a closing.
- `coesheet/shasta-page-20241021.html`: The archive's nearest capture to 2023-02-24 (a snow day): the page already framed the same published sheet.
- `coesheet/shasta-page-live-20260927.html`: The Shasta County Office of Education's page frames the published sheet (pubhtml, widget view).
- `coesheet/shasta-sheet-live-20260927.csv`: The sheet's CSV output (Google redirected the request to doc-10-60-sheets.googleusercontent.com), read once as a check on the tab page: the same 95 rows.
- `coesheet/shasta-tab-live-20260927.html`: The tab page the widget loads: the server-written table; every Shasta County school, Black Butte Elementary and Black Butte Jr. High 'Closing at 12:45' (updated 9/10 9:45), the rest OPEN.
- `coesheet/shasta-widget-20230617.html`: The widget view as archived on 2023-06-17: the same script naming the tab page (the tab page itself has no capture).
- `coesheet/shasta-widget-live-20260927.html`: The sheet's widget view (the page's frame): drawn in script, it names the tab page it loads.
- `coesheet/trinity-page-20260516.html`: The archive's only capture served for the requested days (2026-05-16): the page embedded the same sheet.
- `coesheet/trinity-page-live-20260927.html`: The Trinity County Office of Education's page embeds the published sheet (widget=false: the server writes the table).
- `coesheet/trinity-sheet-live-20260927.html`: Every Trinity County school, all 'Open', each updated 01/05/2026 8:47 or 8:48 AM; the sheet still says '2025-2026 SCHOOL YEAR'.
- `cowles/nonstop-page-live-20260927.html`: NonStop Local Montana's page (the site of KFBB/KHBB, KTMF and KWYB) frames the same ticker as KULR's.
- `cowles/ticker-live-20260927.html`: The ticker both Cowles pages frame, as read live (Last-Modified Thu, 16 Apr 2026 15:18:17 GMT): the empty state.
- `edlio/edinburg-live-20260928.html`: An Edlio homepage with no alert up: an empty list.
- `edlio/hidalgo-20250120.html`: The eve of the January 2025 snow: the homepage alert 'Delayed Start at Hidalgo ISD' (a delay: proves the source).
- `edlio/lake-elsinore-live-20260928.html`: One homepage alert, the district's new website: not a closing.
- `edlio/los-fresnos-20250121.html`: The January 2025 snow: a headline-only homepage alert, 'Weather Notice - Monday, January, 20' (names no closing: does not prove).
- `edlio/mission-20250121.html`: The January 2025 snow: the homepage alert 'Weather Advisory', 'No School - Jan 21, 2025 / Delayed Start - Jan 22, 2025' (a closing: proves the source).
- `edlio/natrona-live-20260928.html`: An Edlio homepage with no alert up: an empty list.
- `edlio/sublette-9-live-20260928.html`: A live homepage alert with a picture, 'School Picture Days' (not a closing).
- `finalsite/baldwin-home-live-20260928.html`: Baldwin County Public Schools' homepage: body data-pageid="10398" (not 2: the page ID is the site's own).
- `finalsite/baldwin-page-pops-live-20260928.html`: Baldwin County Public Schools' homepage page pops: none (an empty body).
- `finalsite/billings-home-live-20260928.html`: Billings Public Schools' homepage: a published Finalsite page, body data-pageid="2465", the ID its registered page-pops address holds; no page pops in the page.
- `finalsite/billings-page-pops-live-20260927.html`: No page pop: HTTP 200 with an empty body.
- `finalsite/broward-page-pops-live-20260927.html`: One page pop titled 'Notice' (the district's referendum), with a logo image and a style block that are not text.
- `finalsite/chickasaw-home-live-20260928.html`: Chickasaw City Schools' homepage: body data-pageid="2"; its page pops (Parent University) are the answer of /fs/pages/2/page-pops.
- `finalsite/chickasaw-page-pops-live-20260928.html`: One page pop, Parent University (an event): not a closing.
- `finalsite/great-falls-page-pops-live-20260927.html`: One page pop (a settlement notice, not weather), visible 2026-09-10 to 2026-10-31.
- `finalsite/gulf-shores-home-20201101.html`: Gulf Shores City Schools' homepage in 2020: a published Finalsite page whose body data-pageid is "329", not the "1994" the live homepage names and the registry's page check records (the site was rebuilt since): a changed page ID.
- `finalsite/gulf-shores-home-20250121.html`: Gulf Shores City Schools' homepage in the Gulf Coast snowstorm (2025-01-21): body data-pageid="1994", the ID of the registered page check; its page pops were not captured.
- `finalsite/palm-beach-home-20241010.html`: The School District of Palm Beach County's homepage in Hurricane Milton, on Finalsite's Web Community Manager (Schoolwires; its footer: 'Copyright 2024 Finalsite'): one important announcement about the storm and shelters.
- `finalsite/psja-page-pops-live-20260928.html`: No page pop: the empty answer.
- `finalsite/south-texas-page-pops-live-20260928.html`: Two page pops (enrollment and a career and technical education guide), not closings.
- `finalsite/volusia-home-20241014.html`: Volusia County Schools' homepage after Hurricane Milton: an older Finalsite template that carries its page pops in the page (#fsPagePopCollection), one pop 'Hurricane Milton Update'.
- `flathead/closures-20250427.html`: The older card layout in the 2024-25 school year ('UPDATED INFORMATION FOR Friday, April 25th, 2025'): every school 'Open'.
- `flathead/closures-20260119.html`: The older card layout, 'UPDATED INFORMATION FOR Wednesday, December 17th, 2025' (a storm day): Cayuse Prairie, Fair-Mont-Egan, Olney-Bissell, Pleasant Valley and West Glacier 'Closed'; Deer Park 'Open' with '2 hour delayed start due to power'.
- `flathead/closures-20260412.html`: The older card layout, 'UPDATED INFORMATION FOR Friday, March 13th, 2026' (a storm day): five schools 'Closed'; two private schools with a blank status.
- `flathead/closures-20260815.html`: The first archived capture of the current layout (www. host): 'Last Updated July 13, 26 10:55 AM', every school 'Open'.
- `flathead/closures-live-20260927.html`: Every Flathead County school with its status; West Valley Closed (No running water), the rest Open; Last Updated September 25, 26 8:11 AM.
- `flathead/closures-oldsite-20230103.html`: The old domain in January 2023: 'UPDATED INFORMATION FOR' and 'TUESDAY, JANUARY 3, 2023' on two lines, capitals; Somers/Lakeside and St. Matthew's 'CLOSED' ('WINTER BREAK, RETURNING ON 1/4/23').
- `flathead/closures-oldsite-20240209.html`: The old domain on a storm day, 'UPDATED INFORMATION FOR Friday, February 9th, 2024': Fair-Mont-Egan, Olney-Bissell, Pleasant Valley and West Valley 'Closed'.
- `flathead/closures-oldsite-20250227.html`: The old domain, 'UPDATED INFORMATION FOR Thursday, February 27th, 2025': Pleasant Valley 'Remote', comment 'Over half of students out sick and the teacher.'
- `gohsep/query-live-20260927.json`: The standing layer read live: 640 features (64 parishes x 10 date groups), 11 Closed, 1 Early Dismissal, 1 Planned Closure.
- `npg/kq2-closings-20190405.html`: KQ2's closings file with nothing posted in 2019 (captured 2019-04-05 15:49 UTC): the same empty sentence as today.
- `npg/kq2-closings-20200408.html`: KQ2's file on 2020-04-08 13:45 UTC: 63 postings (churches, businesses and organizations closed in the pandemic).
- `npg/kq2-closings-20210128.html`: KQ2's file on 2021-01-28 14:03 UTC: one school's two-hour delay (North Daviess R-III).
- `npg/kq2-closings-20231208.html`: KQ2's closings file with two postings (captured 2023-12-08 15:19 UTC): two churches' service changes, read by the NewsTicker reader.
- `npg/kq2-closings-live-20260928.html`: KQ2's closings file with nothing posted: its own sentence 'No currently active closings or delays to report.' under the update line.
- `npg/kq2-page-live-20260928.html`: KQ2's Closings and Delays page: it frames the ftp2 file.
- `schoolblocks/browning-live-20260928.html`: An empty alerts list: nothing up.
- `schoolblocks/grace-live-20260928.html`: A live alert (overlay): the district closed September 11-October 4 for the potato harvest break (a closing, though planned: proves the channel is used for closings).
- `schoolblocks/monroe-al-live-20260928.html`: Monroe County (AL) Board of Education's homepage: an empty alerts list.
- `schoolblocks/uinta-1-live-20260928.html`: An empty alerts list: nothing up.
- `smartsites/belgrade-popup-alerts-live-20260927.json`: One active alert (a special-education records notice, not weather), so the file is in use.
- `smartsites/coachella-valley-popup-alerts-live-20260928.json`: One pop-up alert, a menu app: not a closing.
- `smartsites/leon-home-20240805.html`: Leon County Schools' homepage the morning Tropical Storm Debby closed its schools (a Blackboard Web Community Manager page before its Smart Sites site): 'All LCS offices and schools will be closed, Monday, August 5th 2024 Due to TS Debby'.
- `smartsites/orange-popup-alerts-live-20260927.json`: No active alert: the empty answer.
- `smartsites/tuloso-midway-popup-alerts-live-20260928.json`: One active alert (a board meeting's public notice), not a closing.

## Bodies the adapters refuse (`errors/`)

Kept whole. Each must raise `ShapeError` in its adapter.

| File | Source | URL | Captured (UTC) | SHA-256 | Why it is refused |
|---|---|---|---|---|---|
| `errors/apptegy-twin-falls-20240327.html` | apptegy-twin-falls-id | https://www.tfsd.org/ ([capture](https://web.archive.org/web/20240327095124id_/https://www.tfsd.org/)) | 2024-03-27 09:51:24 | `0bb0f1a6d2912e10…` | Twin Falls' homepage before its move to Apptegy (the archive's nearest capture to 2024-01-09 is of 2024-03-27): a WordPress (Divi) page with no Nuxt state and no announcements region; refused, not read as empty. |
| `errors/finalsite-palm-beach-page-pops-20250105.txt` | finalsite-palm-beach-fl | https://www.palmbeachschools.org/fs/pages/2/page-pops ([capture](https://web.archive.org/web/20250105144407id_/https://www.palmbeachschools.org/fs/pages/2/page-pops)) | 2025-01-05 14:44:07 | `4e07408562bedb8b…` | The archive's capture of the page-pops address nearest Milton (2025-01-05) is the single character '3', neither the fragment nor its empty answer; refused, not read as empty. |
| `errors/finalsite-san-benito-home-20250121.html` | finalsite-san-benito-tx | https://www.sbcisd.net/ ([capture](https://web.archive.org/web/20250121221317id_/https://www.sbcisd.net/)) | 2025-01-21 22:13:17 | `d2f9fdb96e104d75…` | San Benito CISD's homepage of 2025-01-21, before the district moved to Finalsite: an Edlio page (no body data-pageid, no fsLiveMode class, no Web Community Manager announcements). Not a Finalsite page: refused, never read as an empty list. |
| `errors/nonstop-section-20201124.html` | cowles-kfbb | https://www.montanarightnow.com/schoolclosures/ ([capture](https://web.archive.org/web/20201124013259id_/https://www.montanarightnow.com/schoolclosures/)) | 2020-11-24 01:32:59 | `e3d04217738deb9e…` | The /schoolclosures/ page before it framed the ticker: a BLOX section of article cards (section-schoolclosures), not a list of schools. |

## Generator files (`generator/`)

Real list files of the same generator from another operator's station, used only to
test a populated form; not evidence for any source.

| File | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256 | Rows | Why |
|---|---|---|---|---|---:|---|
| `generator/wcyb-grid-20260223.html` | https://wcyb.com/resources/ftptransfer/wcyb/closings/Schools.html ([capture](https://web.archive.org/web/20260223051554id_/https://wcyb.com/resources/ftptransfer/wcyb/closings/Schools.html)) | 2026-02-23T05:15:54Z | 2026-09-27T07:46:40Z | `2c5b11fcbd14988c…` | 35 | A real populated file of the generator Cowles' ticker uses (the NewsTicker 'Closings Last Updated at' grid), Sinclair WCYB's schools file on a winter storm night; no capture of Cowles' own ticker exists. It tests the cowles adapter's populated grid reading only: it is not a Cowles list and is not evidence for any station. |
