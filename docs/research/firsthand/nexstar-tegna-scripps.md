# Nexstar, TEGNA and Scripps closings pages: first-hand check

Checked 2026-09-26 between 17:30 and 17:56 UTC from this machine, with the pipeline's own User-Agent `snowlight-pipeline/0.1.0 (+https://github.com/viaate/jsalcards)` (version from `pipeline/pyproject.toml`, string from `snowlight/sources/stations/http.py`). Every host's robots.txt was read first and a URL was fetched only when both the rules for `snowlight-pipeline` and the `*` rules allowed it (the pipeline's own `robots.py` decided). One request per 2 s per host at most (longer when a Crawl-delay applied), 20 s timeout, no retries. 1637 requests in all, including robots.txt files. The machine-readable records are in `nexstar-tegna-scripps.json` (one record per station website; `call_signs` lists every full-power station the site serves).

It is September, so almost every list was empty. Five lists did hold rows, which pins down the populated markup for each main platform: WTNH and WPRI (Nexstar page and app JSON), KOIN (Nexstar app JSON only), FOX61 (TEGNA) and WTKR (Scripps). Those rows will disappear; they are quoted in the JSON records (`populated_sample`, `companion_endpoints[].observed_sample`).

## Where the station list came from

- **Nexstar**: the table on https://www.nexstar.tv/stations/ (read 2026-09-26; 269 station rows, status O&O or MSA per row; MSA rows are the stations Nexstar runs for Mission Broadcasting, White Knight and others). Rows marked `*` are 'Owned and operated by TEGNA Inc., a subsidiary of Nexstar' and are filed under TEGNA here. Left out: 4 Honolulu stations and 13 low-power/Class A rows (-LD, -CD, -LP). That leaves 188 full-power Nexstar call signs in the 48 states plus DC. WJMN (Marquette, a sources.json lead) is not on the Nexstar list and is kept as a separate record.
- **TEGNA**: https://www.tegna.com/brands/ ('64 Local News Brands in 51 Markets'), cross-checked with the 64 `*` rows on nexstar.tv. WTIC, WCCT (Hartford) and WFMY (Greensboro) are on tegna.com but not on nexstar.tv; they are included. KMSB/KTTU (Tucson) are listed with the web site kold.com, a Gray station site.
- **Scripps**: https://scripps.com/our-brands/local-media/ (68 entries). The list now includes KKTV, KKCO, KJCT and KMVT (their sites are still Gray's Arc XP pages) and WTVQ. WRTV, KATC and WFTX are not on it: wrtv.com's footer reads '© 2026 CIRCLE CITY BROADCASTING I, LLC' and katc.com redirects to acadiananewsfirst.com, so they were not checked as Scripps stations. Not checked as separate sources: the ION/'The Spot' and similar entries whose scripps.com links go to thespottv.com (WMYD, WXMI.2, WNPX, WSFL, WHDT, KMCC via vegas34.com, KUPX via utah16.com, WXPX via tampabay66.com, KWBA via arizona58.com, KIVI.2/KSAW.2 via idaho6.com, and mtnmontana.com), KZCO (courttv.com), KAJA (telemundocc.com, Spanish), KCDO (a section of denver7.com) and KAJ.
- Secondary domains that redirect into a section of the main station site were folded into the parent record (e.g. cw23.com goes to wivb.com/cw23, kwbq.com to krqe.com/new-mexicos-cw/, foxprovidence.com to wpri.com/fox-providence/). Whole-site redirects were merged the same way (kusi.com to fox5sandiego.com, cbs4indy.com to fox59.com, kwgn.com to kdvr.com, siouxlandproud.com to kcau9.com, pahomepage.com to 2822news.com).

## Counts

| Group | Websites checked | Full-power call signs covered | Closings list found | Structured list (page or feed) | No list found |
|---|---|---|---|---|---|
| Nexstar | 115 | 189 | 75 | 71 | 40 |
| TEGNA | 50 | 67 | 48 | 48 | 2 |
| Scripps | 41 | 49 | 27 | 25 | 14 |

'Closings list found' counts any page that is meant to show closings, including hand-edited pages and one frame whose host could not be reached. 'Structured list' counts the ones a scraper can parse row by row.

## Page shapes (variants)

Names follow the `variant` style of `gray.py` and `hearst.py`.

- **`nexstar-wp-closings`** (68 sites). Nexstar WordPress (Lakana 'nxs') page. The HTML page itself returns 403 with a PerimeterX captcha to this User-Agent (93 of 93 requests), but the same page is served by the WordPress REST API, allowed by robots.txt: `GET {origin}/wp-json/wp/v2/pages?slug={slug}` returns a JSON array whose `content.rendered` is the server-rendered list: `<article class="closings-page" data-component="closingsPage">`, an A-Z nav (`span.closings-nav__item--empty` or `a.closings-nav__item--filled href=#letter-x`) and `<div class="closings-list">`. Rows (seen at WTNH and WPRI): `<div class="closing">` with `h3.closing__title` (name), `p.closing__details` > `span.closing__locality` (city) and `span.closing__category`, and `div.closing__status`, grouped under `h2.closings-list__heading` letters. Empty state: `<p>Most recent closings and delays are listed here when there are active closures.</p>`. On several sites the same slug returns two pages (an older one without the article), so pick the element with the closings article. Every Nexstar site also answers `GET {origin}/wp-json/nxd_app/v1/closings_alerts` (the app feed): a JSON array of `{content, category, status, county, city, comments_line1, url, uuid}`, `[]` when empty; it held 2 rows at WTNH, 21 at WPRI and 1 at KOIN (where the page showed none). The lakana/v1/navigation-bar endpoint gives the site menu.
  Stations: KAMR, KARK, KCAU, KDVR, KELO, KETK, KFDX, KFOR, KIAH, KLRT, KLST, KNWA, KOIN, KREX, KRQE, KSEE, KSNF, KSNT, KTAB, KTAL, KTVI, KTVX, KXMB, KXRM, WATE, WAVY, WBOY, WCIA, WCMH, WDCW, WDKY, WDTN, WEHT, WETM, WFFF, WFRV, WFXR, WGHP, WGMB, WHO, WHTM, WIVB, WIVT, WJET, WJHL, WJTV, WJW, WKBN, WKRN, WLNS, WMBD, WNTZ, WOOD, WOWK, WPRI, WQRF, WREG, WROC, WSPA, WSYR, WTAJ, WTEN, WTNH, WTRF, WTWO, WWLP, WWTI, WYTV.
- **`tegna-closings-module`** (46 sites). TEGNA page `https://www.{domain}/closings`, HTTP 200, list rendered in the HTML: `<div data-module="closings" class="closings">`. Rows (seen at FOX61): `<ul class="closings__list"><li class="closings__item"><span class="closings__title">NAME</span><span class="closings__body">STATUS</span></li>`. Empty state: `<p class="closings__error">No delays or closings.</p>`. The sidebar repeats the count as 'Closures/Delays (N)'. No data request is needed and no vendor was visible. The `/feeds/syndication/rss/weather/closings` feed lists stories, not closings.
  Stations: KAGS, KARE, KBMT, KCEN, KENS, KFMB, KFSM, KHOU, KIDY, KING, KPNX, KREM, KSDK, KTHV, KTVB, KUSA, KVUE, KWES, KXTV, KYTX, WATN, WBIR, WBNS, WCNC, WCSH, WFAA, WFMY, WGRZ, WHAS, WKYC, WLTX, WMAZ, WNEP, WOI, WPMT, WQAD, WTHR, WTIC, WTLV, WTOL, WTSP, WUSA, WVEC, WXIA, WZDX, WZZM.
- **`scripps-closings-module`** (20 sites). Scripps Brightspot page `https://www.{domain}/weather/school-closings-delays`, HTTP 200, list in the HTML: `<article class="module module--closings js-filter">`. Rows (seen at WTKR): `<article class="closing js-block"><p class="text--primary js-sort-value">NAME</p><p class="text--secondary">STATUS</p><p class="text--secondary">2026-09-27T03:59:59.999999Z</p>` inside `div.blocks.js-filter__targets`. Empty state: 'There are currently no active closings or delays.' Several pages link a Newsroom Solutions 'Add Closing' form.
  Stations: KIVI, KJRH, KMGH, KMTV, KOAA, KSBY, KSHB, KXXV, WCPO, WEWS, WGBA, WKBW, WLEX, WMAR, WTKR, WTMJ, WTVF, WTVR, WXMI, WXYZ.
- **`ecc-psg-json`** (1 site). WGN only. The page frames the Emergency Closing Center React app (wgnr-closings.emergencyclosingcenter.com/index.html). Headless Chromium (honest User-Agent, only that host allowed) showed the app's one data request: `GET https://media.psg.nexstardigital.net/WGNR/closings/closings.json?timestamp={ms}`. Fetched plainly it returned `{"$":{"Time":"09/26/2026 12:40:32 PM"}}` (an XML-to-JSON object; the populated form was not seen).
- **`gray-fusion-count`** (5 sites). Gray Arc XP `/weather/closings/` page, already read by `gray.py` (it parsed all five as `gray-fusion-count`, empty). The rows come from the Gray S3 export `https://s3.amazonaws.com/grayfilestore-{call}/closingsData/closings_{CALL}.json`, which returned the empty export for all five. Stations: KKTV, KKCO, KJCT, KMVT (Scripps) and KMSB/KTTU (TEGNA, via kold.com).
- **`tegna-flashalert-frame`** (1 site). KGW only. `/closings` holds only a raw-HTML frame of `https://content.kgw.com/station/flashalert/allclosures.html`, a FlashAlert `cwcReport` file (the same markup as `gray_files.py`'s `gray-file-flashalert`). On 2026-09-26 it listed one Transportation item and no schools, with no empty sentence.
- **`wtvq-snowatch-frame`** (1 site). WTVQ only (WordPress, not Brightspot). `/closings/` frames `https://www.wtvq.com/content/uploads/weather-images/SnoWatch.html`, a static file: 'Closings Last Updated at 8:27am on 3/20/2026 No Closings have been reported at this time'.
- **`nexstar-psg-frame`** (1 site). KSN only. The WordPress page frames the static file `https://media.psg.nexstardigital.net/ksnw/weather/ksnwx-closings-nwt.html` (S3, meta refresh 180 s). Empty state: 'No closings to report'. (WOWK has a similar PSG file on an older secondary page: `media.psg.nexstardigital.net/wowtv/closings/closings_page.html`, with a NAME/STATUS header and no rows.)
- **`schoolclosingsnet-frame`** (1 site). KOLR only. The page `/school-closings/` frames `https://www.schoolclosingsnet.com/report.php?type=html&code=c81e720002`, a server-rendered table (School Name, Closing Start, Through, Status, Notes); header only today.
- **`nexstar-manual-page`** (3 sites). WordPress pages where staff type closings as prose (WHNT /weather-closings/, WRBL /weather/closings-and-delays/, WDHN /severe-weather-closings-and-delays/). Readable through wp-json, but there is no row markup.
- **`nexstar-media-frame`** (1 site). WVNS only. The current nav link /weather/closings/ is a story category; the 2021 page /weather/closings-and-delays/ frames a file on media.wvnstv.com, whose robots.txt could not be fetched (proxy 502), so it was not requested.
- **`scripps-manual-text`** (1 site). KSTU only: `/weather/closings` holds hand-typed RichText (a Provo City School District late start).
- **`scripps-empty-page`** (5 sites). Montana MTN sites KTVQ, KXLF, KRTV, KTVH, KXLH: `/weather/school-closings-delays` is 404, `/weather/closings` is a page with the heading 'Closings' and an empty body.
- **`vendor-frame`** (1 site). KERO only: `/weather/school-closings-delays` frames `//alertline.kern.org/`. That host's robots.txt failed TLS verification, so the frame was not requested.

That is 9 parseable shapes plus 5 non-list or unreachable shapes; `none-found` covers the other 51 sites.

## No closings page found

- **Nexstar** (40): WPIX (pix11.com), WPHL (phl17.com), KDAF (cw33.com), KTXL (fox40.com), KAZT (cw7az.com), WFLA (wfla.com), KSWB (fox5sandiego.com), KXAN (kxan.com), WJZY (qcnews.com), WXIN (fox59.com), WDAF (fox4kc.com), WNCN (cbs17.com), WBRE (2822news.com), WANE (wane.com), WIAT (alabamas42.com), WGNO (wgno.com), WRIC (wric.com), KLAS (8newsnow.com), WBTW (wbtw.com), WKRG (wkrg.com), WNCT (wnct.com), KWKT (fox44news.com), WHBF (ourquadcities.com), WUTR (cnyhomepage.com), WLAX (wiproud.com), WJBF (wjbf.com), WCBD (counton2.com), WSAV (wsav.com), KLBK (everythinglubbock.com), WMBB (mypanhandle.com), KARD (myarklamiss.com), KMID (yourbasin.com), WJMN (upmatters.com), KTLA (ktla.com), KRON (kron4.com), KVEO (valleycentral.com), KTSM (ktsm.com), KGET (kget.com), KLFY (klfy.com), KSVI (yourbigsky.com).
- **TEGNA** (2): WWL (wwltv.com), KIII (kiiitv.com).
- **Scripps** (9): KNXV (abc15.com), WFTS (abcactionnews.com), KGTV (10news.com), KTNV (ktnv.com), KGUN (kgun9.com), WTXL (wtxl.com), KRIS (kristv.com), KPAX (kpax.com), WPTV (wptv.com). Also without a list, but with a page: the five Montana MTN sites (KTVQ, KXLF, KRTV, KTVH, KXLH), whose `/weather/closings` page is empty (`scripps-empty-page`).

For the Nexstar sites this means: no WordPress page among the known slugs has the closings article or a closings frame, and the menu has no working closings link. Several menus do link `/weather/closings/`, but the Lakana page-data API reports that path as a 404 (FOX59/CBS4, WRIC, WIAT, WLAX, KLBK, WHBF) or as a story category (WANE, KARD). What a browser sees there could not be checked, because the HTML is behind PerimeterX. Some sites still have old pages (modified 2019 to 2024) with the fixed text 'There are no current closings for schools in this range. Please check other tabs above for possible closings.' (WANE, KWKT, KMID, WBRE; also secondary pages at KOIN and KETK), and those are not live lists. WDAF's /weather/closings/ is a 2023 page showing an unrendered shortcode `[localtv_vendor_embed src="https://cdn.trb.tv/wdaf-ftp/closings/allactive.html"]`. The `nxd_app/v1/closings_alerts` feed answers 200 `[]` on all of these sites, so it may be the only route for them in winter; that is not verified. KIII's `/closings` redirects to its homepage. WWL's redirects to a January 2026 article that answered 403. The Scripps sites without a page are mostly in the Sun Belt (KNXV, KGTV, WTXL, WFTS, KGUN, WPTV, KRIS, KTNV) plus KPAX (Missoula).

## Robots, 403s and hosts that could not be reached

- **robots.txt disallows**: none. No closings page and no data endpoint in this set is disallowed for `snowlight-pipeline` or `*`. Nexstar robots.txt files disallow only paths such as `/wp-content/themes/nexstar/client/build/js/`, `/tag/` and `/page/`, so the closings page JavaScript was not read. tegna.com (the corporate site, not the stations) sets Crawl-delay 10, which was honoured.
- **403 from bot protection**: all 93 batch requests for Nexstar HTML closings pages returned PerimeterX 'Access to this page has been denied', and so did the three other Nexstar HTML requests made (the abc27.com homepage, an earlier abc27.com closings request and a mytwintiers.com page opened as a frame). This affects every Nexstar record's `status`; the wp-json and app-feed routes returned 200 on every Nexstar site. WWL's redirect target, a TEGNA `/article/` page, returned an Akamai 'Access Denied' 403, and so did two other TEGNA article pages opened while following menu links. Nothing was retried.
- **Hosts whose robots.txt could not be read, so nothing was fetched from them**: media.wpri.com, media.wvnstv.com and media.rochesterfirst.com (proxy 502, old frames on secondary Nexstar pages), alertline.kern.org (TLS verify failure; KERO's frame and KGET's menu link) and upmatters.com (WJMN; TLS handshake failure; plain-HTTP robots.txt returned 402).
- Frame hosts that answered robots.txt with a 4xx, which RFC 9309 treats as no restrictions: media.psg.nexstardigital.net (403), content.kgw.com (404), schoolclosingsnet.com (404), wgnr-closings.emergencyclosingcenter.com (403), secure1.newsroomsolutions.com (404).

## Terms of use (read first-hand; the owner decided to proceed anyway)

- Nexstar Terms of Use (https://www.nexstar.tv/terms-of-use/, 'UPDATED: September 16, 2026', linked from station footers) forbid using 'any robot, spider ... for any purpose' and to 'Scrape, data-mine or data-crawl the Properties'.
- TEGNA Terms of Service (wusa9.com/terms, 'Last Updated: June 26, 2025') forbid using 'software or automated agents or scripts ... to strip, scrape, or mine data from' the Services, with a revocable exception for search engines.
- Scripps Terms of Use (wtvr.com/terms-of-use, 'Last Modified & Effective April 1, 2015') forbid using 'an automatic device (such as a robot or spider) ... to copy or "scrape"' without written permission.
- The Gray-built Arc sites (KKTV, KKCO, KJCT, KMVT, KOLD) and the vendor hosts: terms not read in this pass.

## Recommended build order (by schools within 60 miles)

Reach numbers are `reach_schools_60mi` from sources.json. Where a station had no record of its own, the figure is borrowed from another record in the same market (marked `*`; the median when there were several). Figures overlap between stations in one market, so the totals are upper bounds, not unique schools. The table counts only structured lists that were actually found.

| Order | Adapter (variant) | Sites | Sum of reach (overlapping) | Stations by reach |
|---|---|---|---|---|
| 1 | `nexstar-wp-closings` | 68 | 51423 | WDCW 3324, WTNH 2963, WPRI 2378, KIAH 2158*, WWLP 1814, WKBN 1664, WYTV 1664*, WQRF 1507, WJW 1441, KDVR 1354, WLNS 1347, WHTM 1285, WDTN 1285, KTVI 1189, WCMH 1080, KOIN 1046, WTRF 1039, WOOD 1006, WGHP 947, KTVX 891, WSPA 867, WKRN 802, KXRM 781, KFOR 654, KSNT 633, WTEN 574, WGMB 574*, WFRV 561, WTAJ 557, WREG 555, WAVY 554, WROC 541, WSYR 537, WIVB 518, WDKY 517*, WATE 516, WMBD 502, WJHL 499, WIVT 466, KNWA 450, WCIA 445, WTWO 440, WOWK 433, KARK 424, KLRT 424*, KRQE 408, KETK 398*, KSNF 397, WHO 393, WETM 379, WFXR 374, WEHT 369, WJET 360, KELO 356, WBOY 322, WJTV 307*, WFFF 291, KTAL 285*, KCAU 251, KTAB 213*, WNTZ 209*, KXMB 185, KFDX 180*, WWTI 176*, KAMR 170, KREX 103, KLST 91, KSEE n/a |
| 2 | `tegna-closings-module` | 46 | 45265 | WUSA 2815, WFAA 2715, KHOU 2158, WPMT 2092, KARE 1829, WTIC 1782, WXIA 1731, KXTV 1627, KING 1609, KPNX 1579, WKYC 1441, WTOL 1418, KUSA 1354, WTSP 1288, KSDK 1189, KFMB 1109, WBNS 1080, KVUE 1027, WCNC 1024, WTHR 1015, WZZM 1006, KENS 996, WFMY 947, WNEP 737, WCSH 669, WHAS 666, WTLV 601, WATN 555, WVEC 554, WGRZ 518, WBIR 516, WZDX 510*, WLTX 495, KCEN 431, KTHV 424, WQAD 415, WMAZ 415, KYTX 398, WOI 393, KREM 388, KTVB 356, KBMT 353, KFSM 347, KAGS 311, KIDY 213, KWES 169 |
| 3 | `scripps-closings-module` | 20 | 18107 | WMAR 3120, WXYZ 1955, WEWS 1441*, KMGH 1354, WTMJ 1338*, WCPO 1138*, KSHB 1014*, WXMI 1006*, KOAA 809, WTVF 802, KMTV 635*, WGBA 561*, WTVR 558, WTKR 554, WKBW 518*, WLEX 517, KXXV 431*, KIVI 356*, KSBY n/a, KJRH n/a |
| 4 | `ecc-psg-json` | 1 | 3314 | WGN 3314 |
| 5 | `gray-fusion-count` | 5 | 1589 | KKTV 781, KMSB 487, KMVT 115, KKCO 103, KJCT 103 |
| 6 | `tegna-flashalert-frame` | 1 | 1046 | KGW 1046 |
| 7 | `wtvq-snowatch-frame` | 1 | 517 | WTVQ 517* |
| 8 | `nexstar-psg-frame` | 1 | 390 | KSNW 390 |
| 9 | `schoolclosingsnet-frame` | 1 | 390 | KOLR 390 |

Suggested sequence:

1. `nexstar-wp-closings`, with the `nxd_app/v1/closings_alerts` JSON alongside. It has the most sites and the most reach, one parser, and the populated markup is already known from WTNH and WPRI. Build the app-feed reader in the same adapter: it is JSON, it exists on all 114 reachable Nexstar sites, and it is the only candidate route for the 40 Nexstar sites without a page.
2. `tegna-closings-module`: 46 sites, one parser, plain HTML with the populated shape seen at FOX61.
3. `scripps-closings-module`: 20 sites, one parser, populated shape seen at WTKR.
4. The one-offs by reach: WGN's ECC/PSG JSON (Chicago, 3314), then KGW's FlashAlert file (reuse the `gray-file-flashalert` parser) and the five Gray-export stations (already covered by the Gray adapter once their call signs are registered). WTVQ, KSN and KOLR are small single-site frames.

## Wayback patterns to request later (GitHub Actions)

Each record's `wayback_patterns` lists its own. The templates are:

- Nexstar: `{origin}{closings_path}*` (the HTML page; captures from before PerimeterX may exist), `{origin}/wp-json/wp/v2/pages?slug={slug}*` and `{origin}/wp-json/nxd_app/v1/closings_alerts*`. Frames: `media.psg.nexstardigital.net/ksnw/weather/ksnwx-closings-nwt.html*`, `media.psg.nexstardigital.net/WGNR/closings/closings.json*`, `wgnr-closings.emergencyclosingcenter.com/*`, `www.schoolclosingsnet.com/report.php?type=html&code=c81e720002*`. Legacy frames worth a CDX count: `cdn.trb.tv/wdaf-ftp/closings/allactive.html*`, `s3.amazonaws.com/wjwclosings/wjw.html*` (bucket gone now), `media.wpri.com/nxs-wpritv-media-us-east-1/html/toolbox/closings/WPRI_closings.html*`, `media.psg.nexstardigital.net/wowtv/closings/closings_page.html*`.
- TEGNA: `https://www.{domain}/closings*`, and `content.kgw.com/station/flashalert/allclosures.html*`.
- Scripps: `https://www.{domain}/weather/school-closings-delays*` (denver7.com for KMGH, tampabay28.com for WFTS).
- Gray-platform sites: `{origin}/weather/closings/*` and the S3 export URL.

Query them with the CDX API over the storm windows already listed in sources.json (`storm_windows`), for example `https://web.archive.org/cdx/search/cdx?url=www.wtnh.com/wp-json/nxd_app/v1/closings_alerts*&from=20260101&to=20260131&output=json&filter=statuscode:200`.

## What could not be checked

- The rendered Nexstar HTML pages (PerimeterX), and so the page JavaScript. The page markup was read through wp-json. Whether the live page adds anything by script was not seen.
- The populated form of the WGN PSG JSON, the ECC app, the schoolclosingsnet table, the KSN/WOWK PSG files and the WTVQ SnoWatch file. All were empty today.
- Which counties each list covers: empty pages list no counties. Coverage in the records is the market name plus the page's own title, heading or `data-market`.
- Whether `nxd_app/v1/closings_alerts` carries the same rows as the page at every station. It matched at WTNH and WPRI, but KOIN's feed had one row (blank name, status '2 Hours Late, AM buses on snow routes.') while its page was empty.
- Ownership changes not reflected on the owner pages (for example why WTIC/WFMY are missing from nexstar.tv).

