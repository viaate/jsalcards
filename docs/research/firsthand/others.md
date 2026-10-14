# First-hand check: Sinclair, FOX/CBS/NBC/ABC O&Os, Cox, Graham, Allen, independents and regional systems

Checked 2026-09-26 between 17:30 and 18:09 UTC, from this machine, with the scraper's own User-Agent
`snowlight-pipeline/0.1.0 (+https://github.com/viaate/jsalcards)` (version read from `pipeline/pyproject.toml`
through `snowlight.__version__`). Records: [`others.json`](others.json) (291 sources, one per station web domain
or system). It is September, so almost every list was empty; a few were populated by a nor'easter (NBC Boston,
NBC Connecticut, NBC New York, WHDH, News 12, RIBA, Coast TV).

## How it was checked

- robots.txt was read first for every host (339 hosts) and evaluated with the repo's own RFC 9309 reader
  (`pipeline/snowlight/sources/stations/robots.py`). A URL was fetched only if both the `snowlight-pipeline`
  group and the `*` group allowed it. A robots.txt answering 4xx counts as "unavailable" (unrestricted), as the
  repo's reader does; a 5xx, TLS failure or proxy refusal counts as "unreachable" and nothing on that host was fetched.
- At least 2 s between requests to one host (Crawl-delay honoured), 20 s timeout, no retries, TLS always verified.
  About 530 page/data requests in total. No request was retried after a 403 or 429.
- TownNews BLOX sites share infrastructure: requesting several in parallel produced 429s on first contact
  (10 source pages and one data file). After that, BLOX hosts were read one at a time, 5-8 s apart; the 429'd URLs were not requested again.
- No headless browser was needed: every script-loaded list was traced statically from the page's own JavaScript
  (ECC, WRAL, Spectrum, KATV, WeatherThreat, Delaware, Cox/Graham Arc, NBC wp-json).
- Terms: the main groups' terms pages were fetched once and searched for robot/spider/scrape/crawl/data-mining/automated
  clauses; each record's `terms_note` says what was found. Blockers on their face: FOX (foxlocal.com terms ban
  "FRAMING, SCRAPING"), CBS/Paramount ("unauthorized spidering, scraping, data mining"), WHDH/Sunbeam ("any robot,
  spider ... to monitor or copy our web pages"). No clause found: Sinclair, NBCU (page may render more by script),
  Graham, Allen, Hubbard/WTOP, Townsquare. Not read: Disney (script-rendered), Cox (no terms URL found), most small sites.
  FlashAlert's feed page says stations may pull reports every 5-15 minutes but must cache and not hotlink.

### Where the source list came from

- Sinclair: its own station map JSON, `https://sbgi.net/wp-json/sbg/v1/station-map` (behind sbgi.net/tv-stations/):
  140 station web domains, including 40-odd secondary CW/MyTV/Telemundo sites and partner (JSA/MSA/LMA) stations.
- FOX, CBS, NBC, ABC, Cox, Graham, Allen, Hubbard, Griffin: Wikipedia owner pages' "currently owned" tables
  (Fox Television Stations, CBS News and Stations, NBC Owned Television Stations, ABC Owned Television Stations,
  Cox Media Group, Graham Media Group, Allen Media Group, Hubbard Broadcasting, Griffin Media), read 2026-09-26.
  Allen's table lists 15 stations (with low-power and satellite licences) as sold in 2026; the 9 with news sites now redirect to,
  or are, Gray Arc sites and are recorded as `moved-to-gray`.
- Independents and systems: every lead in `sources.json` for my 22 platforms (all 79 leads are covered by a record;
  `lead_id` links them), plus new sources found in station navigation and by web search for the weak states.

## Counts by group

"Data readable" means the list (or the data file the page loads) can be fetched within robots.txt today.

| Group | Checked | Page found | Data readable | Data robots-blocked | Page robots-blocked/unreachable | 403/429/challenge | No page / moved |
|---|---|---|---|---|---|---|---|
| Sinclair | 140 | 60 | 15 | 41 | 2 | 5 | 77 |
| FOX Television Stations | 17 | 11 | 10 | 0 | 0 | 0 | 7 |
| CBS News and Stations | 15 | 9 | 2 | 7 | 0 | 0 | 6 |
| NBCUniversal Local | 11 | 11 | 11 | 0 | 0 | 0 | 0 |
| ABC Owned Television Stations | 8 | 8 | 8 | 0 | 0 | 0 | 0 |
| Cox Media Group | 9 | 6 | 6 | 0 | 0 | 0 | 3 |
| Graham Media Group | 6 | 2 | 2 | 0 | 0 | 0 | 4 |
| Allen Media (current + sold 2026) | 21 | 11 | 2 | 6 | 0 | 4 | 9 |
| Hubbard Broadcasting | 6 | 6 | 6 | 0 | 0 | 0 | 0 |
| Independents & smaller groups (incl. WTOP) | 36 | 31 | 30 | 0 | 1 | 4 | 1 |
| Griffin Media | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| Vendors, aggregators, statewide | 12 | 5 | 8 | 0 | 2 | 0 | 2 |
| New regional systems | 8 | 4 | 4 | 0 | 3 | 0 | 1 |
| **Total** | 291 | 164 | 104 | 54 | 8 | 13 | 112 |

Sinclair's 77 "no page" domains are 37 secondary sites (their news station's record covers the market) and 34 news
sites whose navigation has no closings entry at all (mostly Sun Belt and Mountain West: KUTV/KJZZ Utah, KEYE/WOAI/KABB/KFOX/KDBC/KFDM/KSCC Texas,
KSNV/KRNV/KRXI Nevada, KECI Montana, Florida, Georgia, Alabama; also WPGH Pittsburgh, WUTV Buffalo, KDSM Des Moines,
KBOI Boise, KPTM Omaha), plus 6 redirects or empty embeds. The "page found" counts include 41 Sinclair and 7 CBS
pages whose list sits in a robots-disallowed file.

## Page variants (vocabulary as in gray.py / hearst.py)

| Variant | Shape | Sources |
|---|---|---|
| `sinclair-next-ftptransfer` | Next.js page; RSC `NewsCustomPage_htmlEmbed` frames `/resources/ftptransfer/{call}/closings/{file}` (cache-busted `?`+Date.now()). **robots.txt on all 128 Sinclair Next.js hosts checked (identical file): `Disallow: /resources/ftptransfer/` for `*`.** File not read; presumably a NewsTicker export. | 41 Sinclair station sites (WJLA, KOMO, WSET, WSTM, WLOS, KTUL, WKRC, WHP, WSYX, WWMT, WGME, WJAC, WCYB, KMPH, WNWO ...) |
| `newsticker-export` | Static HTML: `TD.timestamp` "UPDATED SATURDAY, SEP 26 AT 1:35 PM", rows `TD.orgname` group headers + `FONT.orgname`/`FONT.status`; empty `TD.status` "There are no active records at this time." | FOX WJBK, WNYW, WTXF, KDFW, KCPQ (media.foxtv.com); CBS KCNC (static.cbslocal.com); Sinclair WBFF (ftptransfer.sinclairstoryline.com, `sinclair-next-external-newsticker`); Allen WKOW (ftp2.wkow.com) |
| `newsticker-county-select` | Same generator with a county SELECT; empty `TD.none` "There are no closings or cancellations at this time." | FOX KMSP, WITI |
| `riba-newsticker` | Server-rendered NewsTicker table, populated today (RI PUBLIC SCHOOLS > Pawtucket ...) | RIBA; WJAR frames it |
| `closings-table-currently-no` | Header-row table: time row, then "THERE ARE CURRENTLY NO CLOSINGS OR CANCELLATIONS"; meta refresh (WTTG's points at a leftover wbng.net URL) | FOX WTTG; Allen KIMT (ftp2) |
| `fox-bti-plain` | "Last Updated at ... <P>No Closings Reported</P>" | FOX WAGA |
| `cbs-widget-feed` | Page div `data-school-closings-options='{"provider":"newsroom"/"bti","feed":"https://assets1.cbsnewsstatic.com/Integrations/SchoolClosings/PRODUCTION/CBS/{call}/..."}'`, loaded by script. **assets1.cbsnewsstatic.com robots.txt: `Disallow: /` (Allow only /fly/, /hub/, /i/).** | CBS WJZ, WBZ, WWJ, WCCO, KYW (bti), KDKA, KTVT |
| `nbc-wp-closings` | Server-rendered `.closings__listings > .listing > h4.listing__org + p.listing__notice` (+ state tabs); JSON `/wp-json/nbc/v1/school-closings` = `[{category, datetime, organization, status, state}]`, empty `[]`. Empty text "Forecast: School's Open ..." | 10 NBC O&Os |
| `abc-otv-school-list` | Server-rendered `section.school-list > div.meta` "Last updated: ..." `> li.school-closing > span.school-closing-name`; empty "No Closings at this time." | 7 ABC O&Os |
| `cox-arc-closing` | Arc Fusion: `Fusion.contentCache["closing"]` = `{"totalClosings":0,"closings":[]}`; API `/pf/api/v3/content/fetch/closing?_website=cmg-tv-100x0`; table `.closing-list`, empty "No results found" | 6 Cox |
| `graham-arc-school-closings` | Arc Fusion: `contentCache["school-closings"]` = `{"schools":[],"timestamp":...}`; API `/pf/api/v3/content/fetch/school-closings?_website={site}`; empty "There are currently no active closings or delays." | WDIV, WSLS |
| `arc-fusion-schoolclosings` | `/pf/api/v3/content/fetch/weather-school-closings` (empty `{"lastUpdated":...}`) | WWTV/WWUP (Heritage) |
| `hubbard-schoolalert-asset` | Page jQuery-loads `/wp-content/uploads/dynamic-assets/schoolalert.html`; empty "There are currently no reported closings." | KSTP, WDIO, WNYT, KAAL, KOB, WHEC |
| `allen-blox-ftp2-frame` | BLOX page frames `ftp2.{station}.com/closings.html`; **ftp2 robots `Disallow: /` at KWWL, WXOW, WQOW, WAOW, WKTV, WJRT**; allowed at KIMT, WKOW. Count-only `amb-feeds.s3.amazonaws.com/{CALL}_closings.json` readable for all but KVOA. | 8 Allen |
| `blox-weather-closings-table` | BLOX: rows server-rendered into hidden `table.weather-closings`, copied into `#weatherClosingsCopy`; empty "There are no closings at this time" | Sinclair partners WRSP (foxillinois), WICS (newschannel20), KHQA |
| `blox-closings-xml` / `blox-app-closings` / `blox-closings-assets` | BLOX closings app: `/app/closings/{NAME}-closingsC.xml` (`<File Time=...><Closing>...`), `/app/closings/closings.xml`, `/app/closings/closings.html` frame, or closings as article cards | KOAM, KXLY / WRCB (429) / Coast TV |
| `ecc-react` | Emergency Closing Center React app; data `https://media.psg.nexstardigital.net/WGNR/closings/closings.json` (xml2js JSON: empty `{"$":{"Time":...}}`, rows `Closing[].{Name1[],City[],EntityType[]...}`) | ECC; used by CBS 2, FOX 32, NBC 5, ABC7 (dead S3 frame) Chicago |
| `flashalert-cwc-closures` / `flashalert-emergency-xml` | `cwc-closures.php?RegionID={1,2,5,7,10,12,13,15,25}` HTML (`#cwcReportHeader`, `.cwcReportCat`, `.cwcReport`; empty "No information reported."); `flashnews_xml_emergency.php?RegionID=` XML with `schoolrelated` and operating codes | FlashAlert; Sinclair KATU/KUNP/KVAL/KPIC/KCBY/KMTR; KRDO (NPG copy) |
| `spectrum-raven-json` | `/services/closings.{ravenid}.json`: `[{orgType, closings:[{accountName, status}]}]`, empty `[ ]` | Spectrum News 1: 5 NY regions, 4 NC, Austin, San Antonio |
| `news12-jsp` | `itv.news12.com/school_closings/closings.jsp?region={LI,NJ,WC,HV,CT,BX,BK}`, Today/Tomorrow tables Name/City/Status | News 12 |
| `wral-closings-api` | `https://api.wral.com/closings/v1/` → `{"count":0,"closings":[]}` (+ /summary, /counties, /statuses) | WRAL |
| `gsync-style-json` | `[{"record":[],"num_closings":0,"run_date":...}]` (Gray GSync envelope) | WCAV (Lockwood) |
| `sinclair-chameleon-json` | sbgcg.com page → `ticker.news.sinclairinc.cloud/chameleon/blade/query/28/CLOSINGS/?format=json&...` → `{"bladeQueryItem": []}` | KATV |
| `weatherthreat-js` | `wt{1-3}.weatherthreat.com/wt_list/viewClosings.php?media_id=...` returns JavaScript filling `var closings` | KNEB, KHGI, KFXL (broken embed) |
| `eventdelay-widget` | `eventdelay.com/new/widget/channel/114/page`, per-day sections; empty "There are no closings to display at this time." | WDEL |
| `townsquare-njclosings` | `nj1015.com/wp-content/uploads/njclosings/ByCountyclosings.html`, `table#closings-table`; empty "No Closings have been reported at this time" | NJ 101.5 |
| `delaware-jqgrid-xml` | `schoolclosings.delaware.gov/XML/PortalFeed` jqGrid XML; empty `<rows><records>0</records></rows>` | Delaware |
| others | `whdh-closure-notice` (WHDH, server), `wtop-stormdesk` (WTOP, server), CBS6 Albany SchoolWatch county pages (WRGB), county-office pages (Sonoma, Santa Cruz Google Sheet, Humboldt posts), `opm-json` (DC federal status) | see JSON |

## Blocked sources

- **robots.txt blocks the data** (page readable, list not): 41 Sinclair ftptransfer stations; 7 CBS stations (assets1.cbsnewsstatic.com);
  6 Allen ftp2 files (KWWL, WXOW, WQOW, WAOW/WMOW, WKTV, WJRT). The CBS and Sinclair pages carry the exact data URLs, so a
  permission request can name them. Not tried: reading Sinclair files from ftptransfer.sinclairstoryline.com (WBFF's
  frame points there; its robots.txt answers 403, so RFC 9309 treats it as unrestricted) or CBS files from static.cbslocal.com for other stations; that would sidestep
  the stations' own robots rules, so it is left to the owner.
- **robots.txt blocks the page**: WVEIS (West Virginia statewide, `Disallow: /`), WFRD, North Country Public Radio storm list.
- **Unreachable**: WVAH (expired certificate), vab.org (egress proxy refused CONNECT, 502), 03edb93.netsolhost.com (WCTI frames, 502),
  Kern County AlertLine (TLS chain not verifiable), closings.wsls.com and foreverdigitalmedia.com (robots.txt unreadable), KXXO (reset).
- **403 / 429 / challenge**: 429 on first contact (TownNews): WVTV/cw18milwaukee, KEPR/KIMA/KUNW (triyaknews), KVOA, KEZI,
  KDRV, KHSL/KNVN, nwitimes /app/closings/, WRCB's /app/closings/closings.html, WBOC; 403: wpb3.itmwpb.com, amb-feeds KVOA counter,
  ECC complete.html, wgnr-closings.s3.amazonaws.com; Sucuri JS challenge: fox11digital.com (WLUK).

## No closings page found

FOX: KSAZ Phoenix, KTTV Los Angeles, KTVU San Francisco, WOFL Orlando, WTVT Tampa, KTBC Austin (404 at /closings and
/school-closings, nothing in nav); KRIV Houston has a page with no list. CBS: Los Angeles, Sacramento, San Francisco,
Miami, New York (WCBS), Atlanta (404). Cox: WFTV Orlando, WJAX/WFOX Jacksonville, KLSR Eugene. Graham: WJXT, WKMG, KPRC,
KSAT. Griffin: KWTV, KOTV (Brightspot sites, no closings link, /weather/closings 404). Sinclair: the 34 news sites listed above.
Moved to Gray (Gray scout's list): WAAY, WSIL, WREX, WEVV, WFFT, KADN, WLFI, WTHI, WTVA, WDRB.

## New regional systems and vendors (not in sources.json)

| Source | Region | State | Readable? |
|---|---|---|---|
| Spectrum News 1 closings JSON (11 regions) | Albany, Syracuse, Rochester, Buffalo, Hudson Valley; Charlotte, Raleigh, Triad, Coastal NC; Austin, San Antonio | NY, NC, TX | yes |
| News 12 regions NJ, WC, HV, CT, BX, BK (only LI was a lead) | NYC suburbs, NJ, Fairfield CT | NY, NJ, CT | yes (HV/BX/BK codes guessed) |
| NJ 101.5 (Townsquare) by-county file | New Jersey statewide | NJ | yes |
| CBS6 Albany SchoolWatch (closings.cbs6albany.com) | 34 counties NY/VT/MA/CT | NY | yes |
| WDEL SnoWatch via EventDelay (new vendor) | Wilmington / Delaware | DE | yes |
| Coast TV closings (BLOX) | Delmarva beaches | DE, MD | yes |
| KRDO (FlashAlert copy on npg-inc.com) and FlashAlert regions 7, 10, 12, 13, 15, 25 | Colorado Springs; Spokane, Bend, Seattle, Tri-Cities, Boise, Medford | CO, WA, OR, ID | yes |
| KXLY school closures (BLOX) | Spokane | WA | page yes, XML not fetched |
| Kern County AlertLine (framed by KBAK) | Kern County | CA | no (TLS) |
| Sonoma, Santa Cruz, Humboldt County Offices of Education | 3 CA counties | CA | yes (all empty) |
| KATV Chameleon ticker JSON, WeatherThreat media ids, WRAL closings API, Lockwood (WCAV) JSON | Little Rock; Nebraska; Raleigh; Charlottesville | AR, NE, NC, VA | yes |
| OPM operating status JSON (federal, not K-12) | Washington DC area | DC | yes |
| North Country Public Radio, KXXO | northern NY; Olympia | NY, WA | no (robots) |

## Recommended build order

Greedy by schools newly covered (market-level `reach_schools_60mi`, taken from sources.json markets; a market counts once,
overlap between neighbouring markets is not removed, so the cumulative figure is an upper bound). Only adapters whose data
is readable today are ranked.

| # | Adapter (variant) | Sources | New schools | Cumulative |
|---|---|---|---|---|
| 1 | `nbc-wp-closings` (JSON endpoint) | 10 | 22,226 | 22,226 |
| 2 | `spectrum-raven-json` | 11 | 7,162 | 29,388 |
| 3 | `cox-arc-closing` | 6 | 5,821 | 35,209 |
| 4 | `flashalert-cwc-closures` | 8 | 3,654 | 38,863 |
| 5 | `hubbard-schoolalert-asset` | 6 | 3,594 | 42,457 |
| 6 | `ecc-react` (one JSON file for Chicago) | 5 | 3,314 | 45,771 |
| 7 | `newsticker-export` (FOX media.foxtv.com files, KCNC, WKOW) | 6 | 3,309 | 49,080 |
| 8 | `abc-otv-school-list` | 7 | 3,156 | 52,236 |
| 9 | `sinclair-next-external-newsticker` (WBFF Baltimore) | 1 | 3,120 | 55,356 |
| 10 | `news12-jsp` | 7 | 3,048 | 58,404 |
| 11 | `riba-newsticker` | 2 | 2,768 | 61,172 |
| 12 | `newsticker-county-select` (KMSP, WITI) | 2 | 1,338 | 62,510 |
| 13 | `flashalert-emergency-xml` | 1 | 1,046 | 63,556 |
| 14 | `weatherthreat-js` | 4 | 900 | 64,456 |
| 15 | `allen-blox-ftp2-frame` (readable: KIMT, WKOW) | 2 | 814 | 65,270 |
| 16 | `blox-closings-xml` (KOAM, KXLY) | 2 | 785 | 66,055 |
| 17 | `blox-weather-closings-table` | 3 | 660 | 66,715 |
| 18 | WCAV JSON, KATV JSON, Graham Arc, 9&10 Arc, Delaware XML | 6 | 1,846 | 68,561 |
| — | overlapping or unmeasured one-offs (WTTG, WAGA, WTOP, WRAL, WHDH, WRGB SchoolWatch, NJ 101.5, WDEL/EventDelay, Coast TV, CA counties) | 13 | 0 or no figure | |

Rows 7, 9, 11 and 12 (and KIMT/WTTG's header-table variant) are one parser family: NewsTicker-style static HTML. Built
together they add 10,535 schools and would also read the robots-blocked Sinclair and Allen files if permission comes.

NBC first is clear: one JSON route per site, allowed by robots, no terms clause found, covering NY, Philadelphia, DC, Boston,
Hartford, Dallas, LA, SF, San Diego and Miami. FOX and CBS carry terms blockers on their
face; the owner decided to proceed, but CBS's data is also robots-blocked. Largest blocked prize: Sinclair's 41 ftptransfer
stations (DC, Seattle, Cincinnati, Columbus, Harrisburg, Syracuse, Rochester, Portland ME, Grand Rapids, Asheville/Greenville ...)
and WVEIS (all of West Virginia) — both worth a permission request.

## Weakest-covered states (per sources.json) and what this pass adds

- **Utah** (0% of schools near a lead without a known terms blocker): nothing found. Sinclair's KUTV/KJZZ/KMYU have no closings
  page; FOX 13 (Scripps) and ABC4 (Nexstar) belong to the other scout.
- **Montana** (3.8%): nothing found. KECI/NBC Montana has no page (only 'Snow Report'); KULR has no closings link.
- **California** (22%): NBC LA/SD/Bay Area and ABC LA/SF/Fresno pages are readable but have not listed a closing since
  2019 (ABC "Last updated 02/12/2019"). New county-level sources: Kern AlertLine (unreadable, TLS), Sonoma, Santa Cruz,
  Humboldt COEs. CBS LA/SF/Sacramento have no page.
- **Washington** (7.8% near a verified endpoint): KIRO (Cox) and KCPQ (FOX file) readable; KOMO blocked by robots; FlashAlert
  regions 7, 12, 13 cover Spokane, Seattle and Tri-Cities; KXLY found.
- **New Jersey, Delaware, DC** (0% verified): NJ gets NJ 101.5 statewide, News 12 NJ, and the NYC/Philadelphia NBC, ABC, FOX
  files; Delaware gets the state XML feed, WDEL/EventDelay and Coast TV; DC gets NBC4, FOX 5 (file), WTOP and OPM, while WJLA
  (Sinclair) is robots-blocked.
- **New York** (10% verified): Spectrum (5 regions), News 12 (LI, WC, HV, BX, BK), CBS6 SchoolWatch, WNYT, WHEC, NBC/ABC/FOX NY;
  blocked: WSTM, WHAM/WUHF (Sinclair ftptransfer), WKTV (Allen ftp2), NCPR.
- **Texas** (34% verified): NBC DFW, ABC13 Houston, FOX 4 Dallas file, Spectrum Austin/San Antonio; blocked: CBS Texas feed,
  KVII/KTXS (Sinclair); none at FOX Austin/Houston, Graham KPRC/KSAT, Sinclair San Antonio/El Paso/Austin/Beaumont.
- **Colorado**: CBS Colorado (static.cbslocal.com file), FlashAlert region 5 and KRDO.
- **Rhode Island**: RIBA (populated today), also framed by WJAR.

## Wayback patterns for a later GitHub Actions request

Every record lists its own `wayback_patterns`. The most useful storm-day prefixes:
`{sinclair origin}/resources/ftptransfer/{call}/closings/*` (Sinclair robots name ia_archiver with only /news/, /sports/,
/features/ disallowed, so captures may exist); `media.foxtv.com/{call}/closings/*` (note FOX station robots disallow
ia_archiver/archive.org_bot on the station hosts); `assets1.cbsnewsstatic.com/Integrations/SchoolClosings/PRODUCTION/CBS/*`
and `static.cbslocal.com/Integrations/SchoolClosings/PRODUCTION/CBS/*`; `www.{nbc site}/weather/school-closings/*` and
`/wp-json/nbc/v1/school-closings*`; `{abc site}/community/schoolclosings/*`; `www.{cox site}/weather/school-closings/*`;
`www.clickondetroit.com/school_closings/*`; `{hubbard site}/wp-content/uploads/dynamic-assets/schoolalert.html`;
`ftp2.{allen station}.com/*` and `amb-feeds.s3.amazonaws.com/*_closings.json`; `media.psg.nexstardigital.net/WGNR/closings/*`;
`www.flashalertnewswire.net/IIN/reportsX/cwc-closures.php?RegionID=*`; `www.ribroadcasters.com/news_and_events/closings_delays/*`;
`schoolclosings.delaware.gov/XML/PortalFeed*`; `wveis.k12.wv.us/closings/rss.php*`; `itv.news12.com/school_closings/closings.jsp?region=*`;
`spectrumlocalnews.com/services/closings.*.json`; `api.wral.com/closings/v1/*`; `nj1015.com/wp-content/uploads/njclosings/*`;
`closings.cbs6albany.com/community/schoolwatch/*`; `wt1.weatherthreat.com/wt_list/viewClosings.php?media_id=*`.

## Caveats

- Populated row markup was seen only where something was listed (NBC, WHDH, News 12, RIBA, Coast TV, SchoolWatch's
  org registry); elsewhere the row format is inferred from scripts or empty files and says so in the record.
- Endpoints tested at one station and assumed elsewhere: NBC wp-json (tested NY, DFW), Cox Arc API (WPXI), Graham Arc API (WDIV).
- News 12 region codes HV, BX and BK returned the normal template but are not confirmed by any News 12 page; NJ is confirmed.
- Sinclair's ftptransfer file format is inferred from WBFF's file on a different host.
- `reach_schools_60mi` is copied from sources.json by market name; new markets without a figure are null.
