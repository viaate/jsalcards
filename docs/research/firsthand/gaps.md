# First-hand check: the gap states (Montana first), for station adapters part 4 (s4d)

Round 1 checked 2026-09-27 between 11:09 and 12:10 UTC; round 2 between 14:45 and 18:40 UTC and, after a restart,
from 19:09 UTC (its second pass); round 3 on 2026-09-28 from 01:43 UTC (South Texas) and, after a restart, its second pass from 08:06 UTC; round 4 on 2026-09-28 from 14:23 UTC (Alabama and the Mobile - Pensacola market, then the rest of the ranking); round 5 on 2026-09-28 from 22:22 UTC (the Finalsite sources read through their homepages); all from this machine, with the scraper's own User-Agent `snowlight-pipeline/0.1.0 (+https://github.com/viaate/jsalcards)`.
Records: [`gaps.json`](gaps.json) (one per candidate source, in the shape of `others.json`, plus `gap_state`,
`verdict`, `built_as` and `wayback`; the district records of rounds 2 to 4 add `leaids`, `schools` and
`weighted_schools_by_county_weight`). The TV groups of parts 2, 3a and 3b (Gray, Hearst, Nexstar, TEGNA, Scripps,
the network-owned stations, Sinclair, Allen, Cox, Graham, Hubbard, the Emergency Closing Center, FlashAlert,
Spectrum, News 12, NJ 101.5 and the state systems) were not re-checked except where a gap county's candidate
belongs to one of them.

<!-- coverage gate (s4): written by `snowlight stations gate records`; edits are replaced -->
## The coverage gate (s4): states short of the proven target

From `gate.json` of 2026-10-13T22:20:52Z (coverage of 2026-10-13T22:12:01Z). A station counts toward the proven share only once its list has been seen with a row, live or in an archived capture, at its current address or a former address of its own list (the registry's `former_urls`, each with the evidence of the move). National: 85.3% of schools proven (97.0% closure-weighted); the target is 95% of both, 11378 schools (0.0 weighted) short. Each state's target is 90% of both. Every source touching a state below has its record in [`gaps.json`](gaps.json) (its `gate` block: verdict, proof, gain, and the archive census of every address it reads or read).

**The owner's gate** (decided 2026-10-13, replacing 90% in every state): "dig for 90%+ of Idaho and Wyoming and leave it there". It **passes**.

| Rule | State | Proven | Weighted | Meets |
|---|---|---|---|---|
| dig to 90% | ID | 99.1% | 98.6% | yes |
| dig to 90%; accepted: owner decision 2026-10-13 at 85.8% / 87.7% | WY | 85.8% | 87.7% | yes |
| national weighted at least 95.0% | US | - | 97.0% | yes |
| keep the others at 90% | 41 states | - | - | yes |
| not pursued: owner decision 2026-10-13 (rare-closure state) | AZ | 77.4% | 87.0% | no |
| not pursued: owner decision 2026-10-13 (rare-closure state) | CA | 16.0% | 63.9% | no |
| not pursued: owner decision 2026-10-13 (rare-closure state) | FL | 58.1% | 57.8% | no |
| not pursued: owner decision 2026-10-13 (rare-closure state) | LA | 28.2% | 29.0% | no |
| not pursued: owner decision 2026-10-13 (rare-closure state) | MS | 71.1% | 68.8% | no |
| not pursued: owner decision 2026-10-13 (rare-closure state) | NV | 34.6% | 87.1% | no |

- WY: accepted by the owner on 2026-10-13 ("yea call it done nw") at 85.8% proven plain and 87.7% closure-weighted, under the 90.0% target: it meets while its exact shares stay at least these and fails if either drops below them. Measured: 85.8% (334 of 389 schools), 87.7% closure-weighted.
- ID: counting a county across a state line only where the station's rows were seen naming a place in it, proven 76.7% (695 of 906 schools), 62.9% closure-weighted (the gate's measure, which credits a station with its whole market: 99.1%, 98.6%). Credited by market assumption only (no row of the station's ever named a place in the county):
  - `scripps-typed-kstu`: 16007, 16041, 16071 (20 schools)
  - `tegna-krem`: 16009, 16017, 16021, 16035, 16049, 16055, 16057, 16061, 16069, 16079 (183 schools)
- ID: without the proven lists never seen holding a closing but the pandemic's (`gray-kmvt`, `gray-wtap`: every populated read of the first wave, or every row a health closing), proven 85.9% (779 of 906 schools), 86.5% closure-weighted. Such a list counts: it lists closings only, and the districts entered these themselves (a district channel's pandemic notice proves nothing, the channel being for any news); it has yet to be seen on a weather day.
- WY: counting a county across a state line only where the station's rows were seen naming a place in it, proven 25.7% (100 of 389 schools), 29.0% closure-weighted (the gate's measure, which credits a station with its whole market: 85.8%, 87.7%). Credited by market assumption only (no row of the station's ever named a place in the county):
  - `cbs-owned-kcnc`: 56001, 56005, 56007, 56027, 56031 (72 schools)
  - `cowles-kulr`: 56003, 56029 (32 schools)
  - `gray-kota`: 56033 (23 schools)
  - `nexstar-kdvr`: 56001, 56005, 56007, 56027, 56031 (72 schools)
  - `scripps-kmgh`: 56001, 56005, 56007, 56027, 56031 (72 schools)
  - `scripps-typed-kstu`: 56035, 56037, 56041 (49 schools)
  - `weatherthreat-kneb`: 56015, 56021 (67 schools)
- National: with no county credited across a state line by a market alone, 93.6% closure-weighted (the gate's measure: 97.0%).
- Kept, thin: GA is proven 90.4% (90.7% closure-weighted), 13 schools above the 90.0% target (plain).
- Kept, thin: NM is proven 91.8% (99.3% closure-weighted), 18 schools above the 90.0% target (plain).
- Kept, thin: TX is proven 91.1% (94.9% closure-weighted), 120 schools above the 90.0% target (plain).
- Kept states that meet the target on the gate's measure but not when no county across a state line is credited by a market alone: GA 87.8% / 86.9%; MD 92.4% / 89.5%; MO 86.9% / 87.8%; MT 89.1% / 91.6%; NM 89.8% / 96.4%.
- AZ: 2738 schools; covered by a working source 2649 (96.7%, 100.0% closure-weighted); proven 2120 (77.4%, 87.0% closure-weighted); missing: 89 schools no working source covers and 529 covered by sources never seen holding a closing; not pursued: owner decision 2026-10-13 (rare-closure state).
- CA: 12448 schools; covered by a working source 11904 (95.6%, 98.0% closure-weighted); proven 2000 (16.0%, 63.9% closure-weighted); missing: 544 schools no working source covers and 9904 covered by sources never seen holding a closing; not pursued: owner decision 2026-10-13 (rare-closure state).
- FL: 6088 schools; covered by a working source 5343 (87.7%, 85.5% closure-weighted); proven 3538 (58.1%, 57.8% closure-weighted); missing: 745 schools no working source covers and 1805 covered by sources never seen holding a closing; not pursued: owner decision 2026-10-13 (rare-closure state).
- LA: 1585 schools; covered by a working source 1370 (86.4%, 86.4% closure-weighted); proven 447 (28.2%, 29.0% closure-weighted); missing: 215 schools no working source covers and 923 covered by sources never seen holding a closing; not pursued: owner decision 2026-10-13 (rare-closure state).
- MS: 1191 schools; covered by a working source 1160 (97.4%, 96.7% closure-weighted); proven 847 (71.1%, 68.8% closure-weighted); missing: 31 schools no working source covers and 313 covered by sources never seen holding a closing; not pursued: owner decision 2026-10-13 (rare-closure state).
- NV: 831 schools; covered by a working source 831 (100.0%, 100.0% closure-weighted); proven 288 (34.6%, 87.1% closure-weighted); missing: 0 schools no working source covers and 543 covered by sources never seen holding a closing; not pursued: owner decision 2026-10-13 (rare-closure state).

| State | Proven | Weighted | Short (schools / weighted) | Sources by verdict | Open |
|---|---|---|---|---|---|
| AZ | 77.4% | 87.0% | 345 / 13.5 | 5 proven, 1 storm-read, 1 all-read, 7 no-endpoint | none: settled |
| CA | 16.0% | 63.9% | 9204 / 527.7 | 6 proven, 20 unread, 12 storm-read, 2 unconfirmed, 3 all-read, 5 unreadable, 1 not-listed, 4 not-working, 15 no-endpoint | 21 sources, 1 records |
| FL | 58.1% | 57.8% | 1942 / 917.5 | 36 proven, 14 unread, 6 storm-read, 1 unconfirmed, 5 no-storm-capture, 2 all-read, 4 unreadable, 2 no-capture, 3 not-listed, 3 not-working, 22 no-endpoint | 13 sources |
| LA | 28.2% | 29.0% | 980 / 434.0 | 4 proven, 1 all-read, 1 unreadable, 1 no-capture, 1 not-listed, 3 not-working, 6 no-endpoint | 1 sources |
| MS | 71.1% | 68.8% | 225 / 108.1 | 9 proven, 11 unread, 3 storm-read, 1 no-storm-capture, 1 all-read, 3 unreadable, 2 not-working, 4 no-endpoint | 11 sources, 1 records |
| NV | 34.6% | 87.1% | 460 / 12.0 | 5 proven, 2 all-read, 1 no-capture, 5 no-endpoint | none: settled |
| WY | 85.8% | 87.7% | 17 / 21.4 | 18 proven, 2 unread, 11 storm-read, 8 unconfirmed, 1 all-read, 5 unreadable, 1 no-capture, 5 no-endpoint | none: settled |

42 of 49 states (with DC) meet the target; of the 7 short of it, 3 are settled: every source whose proof would add to the state has a verdict after which no archived capture left could prove it (`all-read`, `no-capture`, `no-endpoint`, `no-storm-capture`, `storm-read`, `unconfirmed`, `unreadable`). Settled is not met: a settled state is still short, and an `unconfirmed` source in it showed closings on or near its storm days that the proof rule does not accept. A source is open (the last column counts them) while captures of its list made in its closure window (its closure days and the 2 days either side) are unread or were misread (refused by its adapter, or showing a closing its rows do not hold: the closure-text check, `archive/closure-text.jsonl`), or an address of its list was never listed. A first-hand record of a source not built (a district or outlet the registry does not hold) keeps its states open too (the last column's records) while it says the site was not read, or was checked before 2026-10-01: only a check of today's site can say no reader here reads it (`open_records` in `gate.json`). The window is measured on the proven sources' own archived reads (`calibration` in `gate.json`). Verdicts: `proven`: proven: its list has been seen with a row (at its current or a former address, or as the list file another proven station reads too); `unread`: unproven: captures of its list are not read yet; `misread`: unproven, open: an archived capture of its list made in its closure window was refused by its adapter (a page form no reader knows) or showed a closing its rows do not hold (the closure-text check); no verdict is given until that form is read; `older-unread`: unproven: no unread capture of its list remains, at its current or a former address (none read held a row); only captures of other addresses it read before are unread, and they cannot prove it; `storm-read`: unproven: every archived capture of its list made in its closure window (a storm day, a day its counties' proven lists named closures, or a day within two days of one) was read, none with a row and none showing a closing its rows do not hold, and at least one of them showed the list (captures of other days may be unread); `unconfirmed`: unproven: every archived capture of its list made in its closure window that could be read was read, and at least one showed a closing, a delay or no school that its rows hold but that does not prove it: a district's notice or page text that names no weather or emergency (a calendar's planned day reads the same), or a story that is not a list's entry; the list may be in use; `no-storm-capture`: unproven: no archived capture of its list made in its closure window (a storm day, a day its counties' proven lists named closures, or a day within two days of one) shows the list: the archive holds none, or only page shells that show no closing; its other captures showed the list, empty (captures of other days may be unread); `all-read`: unproven: every archived capture of its list was read, none with a row; `unreadable`: unproven: no archived capture of its list that was read showed the list: each made in its closure window is a page that loads its list from an address the archive does not hold and shows no closing itself (others may be a form no adapter reads); `no-capture`: unproven: the archive holds no capture of its list; `not-listed`: unproven: an address of its list (its current page or data file, or a former address) was never listed, so what the archive holds of it is unknown; `not-working`: not working: its latest live read does not count; `no-endpoint`: no known closings endpoint.
<!-- end of the coverage gate's section -->

## Critics' second round (s4, 2026-10-13 evening)

The second critic panel found the gate still failing (Wyoming short), and three faults in what it counted. Each is
fixed as a class, with tests; figures below are from `coverage.json` of 2026-10-13T22:12:01Z and `gate.json` of
2026-10-13T22:20:52Z, every percentage cut, never rounded up.

**The gate decides on exact shares.** `coverage.json` rounds each share to four decimals, so a true 89.997% was stored
as 0.9 and passed. The owner's gate now decides on the integer counts (plain) and on the measure's own exact
`meets_target` (weighted, and the national 95%), and the rounded share must reach the target too
(`gate._at_least`; `tests/stations/test_gate_owner.py`: a share coverage rounds up to 90% or 95% fails).

**A district channel is proven only by a closing for weather or an emergency** (`notices.py`). A planned day never
proves, weather named or not: a testing day (Idaho Falls' "SAT Day is March 13 ... NO school for freshmen, sophomores and
seniors"), a teachers' planning or duty day (Sharyland's "this day is dedicated to planning and preparation for our
teachers and staff"), a student holiday (Volusia's post-Milton letter, whose one "no school" is "a Student
Holiday/Teacher Duty Day": a storm letter keeps only its sentences that name no planned day, and the sentence after one
that refers back to it). A bare "no school" or "no classes" (Hellgate's "No School Wednesday, November 22 - Friday,
November 24th", Thanksgiving; Florence-Carlton's "No School on January 27th.", six days old) is how a calendar writes its
days off: it proves only with a weather or emergency word, or when the NWS corroborates its day as a dated closing. A
pandemic's closing never proves, though it name no virus: one that cites a health order (Alvord's "ORDER OF THE HEALTH
OFFICER OF THE COUNTY OF RIVERSIDE") or, read in the 2020-21 shutdown, speaks of learning remotely "during school
closure" (`notices.pandemic`). A headline about closures is not one ("Potential Hurricane Helene: Closure Information
and Updates", Duval's only proof; the linked page was not read: Florida is not pursued). "No school closures or delays
today", "no school delay or closure" and "we are not cancelling school" keep the day. A status board's "Planned Closure"
is not a closing, and a status shown long after its own stamp is a leftover (`notices.stamp_current`: a row's update
time or closure date more than a week before the read): Shasta's "Black Butte Elementary | Closing at 12:45", stamped
"9/10 9:45" and read from 2026-09-27 to 2026-10-13, and GOHSEP's "Ascension | Closed" of 2026-06-18 (with "Planned
Closure" rows beside it) no longer prove. A gated station now records its earliest proof whose row names weather or an
emergency (Idaho Falls: "D91 is cancelling school on Monday, Jan. 30, because of extreme weather and cold", 2023-01-31;
Sublette #9 and West Jefferson: their first capture of the line). Real rows of each case are tests
(`tests/stations/test_gate_planned_days.py`). Effect: Texas 91.2% / 94.9% to 91.1% / 94.9% (9453 of 10370) (Sharyland), Florida 63.1% / 63.9%
to 58.1% / 57.8% (3538 of 6088) (Volusia, Duval, Walton, whose "No classes for students on 10/12 or 10/13" names no reason and a
federal holiday), Louisiana 77.5% / 78.3% to 28.2% / 29.0% (447 of 1585) (GOHSEP), California 17.1% / 70.0% to 16.0% / 63.9% (2000 of 12448) (Shasta,
Alvord); Montana's count does not change (KTMF covers Hellgate and Florence-Carlton).

**What a market alone credits** (`coverage.market_assumptions`, `proven.market_checked`). A list's county list is its
market's (`basis: dma`); across a state line that is an assumption: KNEB, a Scottsbluff (NE) radio list, is credited with
Goshen and Laramie counties, Wyoming, but its one populated capture named 22 Nebraska places and no Wyoming one. The
observed check now reads place names in a row's text and place fields (WeatherThreat's `location`, a typed line, the
row's own name) against the school directory's cities, district names and county names, a name counting only when it
is one county's within the station's states (`observed.PlaceIndex`); and the proven share is measured once more
counting a county over the station's home state's line only where a row of the station's named a place in it. The gate
is decided, as before, on the proven share as the coverage measure defines it (a station's whole market); the owner's
gate states the market-checked share beside it, and the credits it rests on, for the owner to weigh:

| Proven (plain / weighted) | The gate's measure | Market-checked | Without the pandemic-only lists |
|---|---|---|---|
| Idaho | 99.1% / 98.6% | 76.7% / 62.9% (695 of 906) | 85.9% / 86.5% (779 of 906) |
| Wyoming | 85.8% / 87.7% | 25.7% / 29.0% (100 of 389) | the same |
| National (weighted) | 97.0% | 93.6% | 96.8% |

Wyoming's credits by market alone: the Denver lists (KCNC, KDVR, KMGH) for Albany, Campbell, Carbon, Niobrara and
Platte (72 schools; their archived rows name Colorado places only, Colorado's Sheridan and Platte Canyon among them),
KULR (a Billings statewide article) for Big Horn and Park (32), KOTA for Sheridan (23), KSTU for Sublette, Sweetwater
and Uinta (49), KNEB for Goshen and Laramie (67). Idaho's: KSTU for Bear Lake, Franklin and Oneida (20) and KREM
(Spokane, two archived rows) for the ten northern counties (183). These lists take submissions from the schools of their
whole market, and a Wyoming school's closing would appear on them as a Colorado one's does; but none has been seen to,
so their Wyoming credit is the market's map, not a row. KIFI is different in kind: its "list" is a newsroom's articles,
and the counties it is credited with are the ones its articles named (`basis: observed`), which is why its Lincoln
County credit was dropped. KULR's proof (which KTMF shares) is a capture of 2019-08-20 of its statewide article of
2019-03-03 ("Statewide school delays and closures for Monday, March 4", "winter weather and bitterly cold
temperatures"): read later, but dated by the article itself, so it shows the list held closings on that storm's day; it
is not read as a closing current on the capture's day. Kept states that meet the gate's measure but not the market-checked one:
GA 87.8% / 86.9%; MD 92.4% / 89.5%; MO 86.9% / 87.8%; MT 89.1% / 91.6%; NM 89.8% / 96.4%.

**Idaho rests on KMVT, seen only with the pandemic's closings.** Twin Falls' Gray list (KMVT) is the only proven source
for 119 Idaho schools (Blaine, Cassia, Gooding, Jerome, Lincoln, Minidoka and Twin Falls counties). Every populated read
of it is the pandemic's: 86 rows of March 2020 and one of 2022-01-27, "North Valley Academy | Closed Through Monday",
its comment "Health Concerns" (`notices.pandemic_only_lists`: every read made in the first wave, March to June 2020,
or every row a health closing; Parkersburg's WTAP is the other such list). It counts: a TV list lists closings only,
and the districts entered these themselves, which shows that its schools report to it; a district channel's pandemic
notice shows nothing of the kind, the channel carrying any news. Without it Idaho is
85.9% / 86.5%.

**Georgia, the thinnest kept state**, is 90.4% plain (2652 of 2932),
90.7% weighted, 13
schools above 90%. Its counties proven by a single source are WALB's (Albany, 136 schools; its proof is the storm of
2025-01-22, 65 rows: "ABAC | Closed Wednesday") and WCTV's (Tallahassee, 74 schools in nine Georgia counties; its proof
is "Leon County Schools | Closed Wednesday" of 2025-01-19, a Florida row: its Georgia credit is the market's). Both proofs
are genuine closings of that storm; none of Georgia's proofs is a district channel's. The gate report now lists every
kept state under 92% with its margin (`owner_gate.kept.thin`).

**Records and the rest.** Each first-hand record's `proof` block in `gaps.json` is rewritten from today's coverage
whenever the gate writes its records (`gate.current_proof`, dated `as_of`): Palm Beach is unproven (its storm-information
link no longer counts), Volusia too, and a station now in error (Lake Elsinore) is not called working. Every table the
gate writes cuts its percentages (Wyoming's 334 of 389 is 85.8%, never 85.9%). A host whose robots.txt answers 401 or
403 is asked nothing more in the run, not even the page (`http.PoliteClient`). The builder's scratch fetcher of this day
read robots.txt under Python's default User-Agent (its page requests carried the project's); KIFI's record says so, and
the fetcher now reads robots.txt with the project's. BOCES 5 (Wyoming), the last Wyoming source never listed, was listed
(run 38471589165) and its closure-window captures read (run
38472989728): verdict `storm-read`, no closing. Wyoming's open sources:
none.

**The gate passes on the owner's acceptance of Wyoming.** Idaho meets the gate's measure (99.1% /
98.6%); Wyoming is 85.8% plain and 87.7% closure-weighted, under 90%, and the owner accepted it at
those figures on 2026-10-13 ("yea call it done nw"), stated honestly as 87.7% by the market credit the whole
measure uses and 29.0% counting only what rows have shown; national 97.0%; all 41 kept states at 90% or more.
The gate stores the accepted figures (`OwnerGate.accepted`: 85.8% plain, 87.7% weighted, with the date and the
owner's words) and fails if Wyoming drops below either. A storm-day read that proves Lincoln County #2 (28.5 weighted
schools) would take Wyoming past 90% weighted on its own.

## Final round of the coverage gate (s4, 2026-10-13): the owner's gate

**The gate.** On 2026-10-13 (about 7:45 AM Central) the project owner replaced "90% in every state" with: "dig for
90%+ of Idaho and Wyoming and leave it there". The gate (`gate.json`'s `owner_gate`, `snowlight.sources.stations.gate.OwnerGate`)
passes when Idaho is at least 90% proven, plain and closure-weighted, and Wyoming at least the 85.8% plain and 87.7%
closure-weighted the owner accepted (the owner called Wyoming done at its honest numbers, "yea call it done nw",
"accepted: owner decision 2026-10-13"; the gate stores these figures and fails if Wyoming drops below either); the
national closure-weighted proven share stays at least 95%; and every other state that was at 90% stays there (Utah and
Alabama at 100%, Texas at 91.3% on the morning of the decision). Arizona, California, Florida, Louisiana,
Mississippi and Nevada, the states short of 90% where closures are rare, were not dug further: each keeps a record of
what is covered, what is proven and what is missing, marked "not pursued: owner decision 2026-10-13 (rare-closure
state)" (`owner_gate.rare` in `gate.json`; `owner_decision` and `gate.owner_gate` on each of their records in
`gaps.json`). The CA and FL work of the stopped round-5 builder (St. Lucie, Corona-Norco, Desert Sands and the
`district-pages` homepages) is kept as built and live-read, but not continued.

**Result** (after the critics of the first builder round: live fetch of every source, 2026-10-13 13:38-15:10 UTC, and of
the district pages, feeds and KIFI again at 16:52 and 17:42 UTC, merged with the earlier fetches; archive parse of every
downloaded capture, including the 241 storm-day and closure-window captures of Lincoln County #2's homepage asked for in
runs 38442169734 and 38442644173; coverage of 20:02 UTC; `gate.json` of 20:09 UTC). The owner's gate **passes** on the owner's acceptance of Wyoming at these figures:
Wyoming's closure-weighted proven share is 87.7% (835.9 of 952.5 weighted schools, cut, never rounded up), 21.4 weighted schools under 90%.

| Proven share (plain / closure-weighted) | Round 4 (03:24 CT) | First builder round (15:21 UTC) | Final |
|---|---|---|---|
| Idaho (gate: 90% / 90%) | 81.0% / 75.6% | 100.0% / 100.0% | **99.1% / 98.6%** (898 of 906 schools): meets |
| Wyoming (gate: accepted at 85.8% / 87.7%, owner decision 2026-10-13) | 76.3% / 75.7% | 88.9% / 91.8% | 85.8% (334 of 389 schools) / **87.7%**: meets on the acceptance |
| Texas (kept) | 91.3% / 95.0% (rounded) | 91.3% / 95.0% (rounded) | 91.2% / 94.9% (9466 of 10370; 0.9499 weighted, cut) |
| Utah (kept) | 100.0% / 100.0% | 100.0% / 100.0% | 100.0% / 100.0% |
| Alabama (kept) | 100.0% / 100.0% | 100.0% / 100.0% | 100.0% / 100.0% |
| National | 86.5% / 97.3% | 86.7% / 97.7% | 86.4% / **97.5%** (target 95% weighted: met) |

Every other state outside the six rare-closure states stays at 90% or more, plain and weighted (41 states and DC).
What the critics changed: Lincoln County WY (13 schools, 41.1 weighted) is no longer credited to KIFI, whose closings
articles never named a Lincoln County school in four winters, and Lemhi County ID likewise; non-closing banners ("Schools
are OPEN", "school at regular time", storm-information links, a room closed while classes go on as normal) no longer
prove a district channel, nor a pandemic's closing that names COVID-19 or the coronavirus (one that cites a health order
instead, as Alvord's of March 2020 did, still proved until the critics' second round, below); a homepage line left up unchanged proves only by the capture that
first showed it. Wyoming's 55 unproven schools: Lincoln County #2 (Star Valley, 9 schools, 28.5 weighted: its homepage's
241 storm-day and closure-window captures from 2015 to 2026 show no closing, only a make-up day "for the school
closure yesterday" in January 2017, bus delays and cancelled games; it announces closings on Twitter, @LCSD2Bus) and
Lincoln #1 (Kemmerer, 3; its pop-up alerts file was never archived), Riverton #25 (7; its homepage banner was read on its
storm days, empty, and its live feed, which begins in October 2024, holds no closing), Washakie #1 (6; it announces
closings over KWOR radio and Infinite Campus, and its feed holds none), Dubois #2 and Fort Washakie #21 (3 each; 97
storm-day captures, none a closing), Arapahoe #38 (2), Hot Springs #1 (3), Ten Sleep (1), 16 schools no working source
covers (Natrona County's private schools, the Wyoming Behavioral Institute and Wyoming Classical Academy among them;
County 10, Fremont County's own list of closings, answers 403), and BOCES 5. What would close the gap: Lincoln #2 alone
(28.5 weighted) would, seen once announcing a closing (a live read on a storm day, or a source that carries its
closings: its Twitter is not read); otherwise a whole-county source for Casper - Riverton (KCWY's GSync export was last
written in 2022; County 10 blocks the project).

**Live today (2026-10-13).** Of the 71 lists whose latest live read came back with rows, 18 hold a row that announces a
closing by the notice gate's own test (`notices.row_qualifies` for district channels, `notices.announces_closing` for
the rest): Okaloosa's and Walton's (FL) notices (Walton's no longer, since the critics' second round: its "No classes
for students on 10/12 or 10/13" names no reason), Alabama's statewide list, Brewton (WALA), Beaver Local and
Lake Orion schools on the Ohio and Detroit lists, HCOE's Jack Norton School and others. The other 53 hold events,
news or open notices (the two new Wyoming feeds' food drive and picture retakes among them). North Gem's "all North
Gem schools are closed today", up since 2026-02-18, is dropped from the latest live read (17:42 UTC) as an old note
(`fetch.judge_page_text`), and so from every read the poller makes from now on. The day's three earlier reads (06:06,
09:31 and 14:52 UTC), made before that rule, still carry the line in the day's merged rows (`live-merged10/rows.jsonl`,
evidence of those reads); the fetch's default output (`out/internal/stations/health.json`, `reads.jsonl`, `rows.jsonl`)
is now written as today's live state, each source's latest read only, so it shows North Gem empty (corrected in the
critics' second round; it had held the 14:52 read's "ok, 1 row").

**Idaho: KIFI's closings articles.** Every unproven Idaho school was in the Idaho Falls - Pocatello market, which had no
whole-county source (KIFI's `/weather/closings/` answers 404, KPVI's one "School Closures" article was last changed on
2025-02-25, East Idaho News answers 403), and its district sites rarely close (Bonneville #93's own page: schools close
only for blizzards and dangerous cold) and were never seen closed in the archive. KIFI's newsroom types each storm day's
closings into an article titled for the day, which WordPress stamps with the times it was published and changed:
"School closures and delays for Wednesday, March 6" (2024; 19 entries, Aberdeen #58, Bonneville #93, Firth #59, Madison
#321, Teton #401, Sugar-Salem #322 ... "Teton County School District 1 - 2 hour late start") and 26 more list articles
from 2022-12 to 2025-02-25; and it gives a single school's or district's closing a story of its own ("Taylorview Middle
School closed Thursday due to down heat pumps", 2025-12-18; "Teton County Schools Closed Tomorrow due to Jackson Boil
Order", 2026-09-25; "School canceled for Chief Tahgee Elementary Academy", 2026-10-07). Built as `npg-articles-kifi`
(adapter `wp-closings`, platform `npg-articles`): the poller reads the site's REST list of posts searched for "school",
the AP, CNN and Stacker categories left out, newest first; it keeps only the station's own stories (a dateline crediting
another outlet is not: the AP's story of UK school closures of 2024-11-19, carried under KIFI's own `/news/` path, is
not read), keeps an article's rows while stamped within 36 hours, and takes the newest closings article's publication
as the list's own time, judged by the closure-season rule like any list's (2026-10-07 on 2026-10-13: in use). The poller
reads all 47 of KIFI's own closings articles of 2022-10 to 2026-10 as closings and none of the wire's or the stories
about closings that announce none (`tests/stations/test_wp_closings_kifi.py`). In the winter of 2025-26 KIFI wrote no
weather list, but it still wrote weather closings as stories: "SCHOOL CLOSURE" (2026-04-27, "Butte County Joint School
District is closed today due to snow and inclement weather"), beside an illness closing ("Classes Canceled: Rising
illnesses and absences force multi-day closure for Ririe School District", 2026-01-28); the list's current time is set
by a closing for no weather (Chief Tahgee's water line, 2026-10-07). The market's one closure event of that winter, 2025-12-05, was a Winter Storm Warning for the mountain zones (KIFI's
forecast: "mountain winter storm warnings posted"; no district page on record closed), and North Gem SD 149 (Caribou)
closed for weather on 2026-02-18 under a warning for its own zone without a KIFI story. Counties: only those whose schools
KIFI's closings articles named (`basis: observed`): 12 Idaho counties and Teton County WY; Lemhi ID (Salmon, Leadore)
and Lincoln WY (Star Valley, Kemmerer, Cokeville), never named in four winters, are not credited to it. KIFI's terms
(News-Press & Gazette's, as KQ2's) forbid automated means; the owner's decision of 2026-09-25 is recorded with the
platform.

**Wyoming: the districts' Apptegy live feeds.** An Apptegy district sends one post to its site's live feed, its app's push
notifications, texts and Facebook at once, and the feed keeps every post with the time the server stamped it
(`https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/<organization>/cms/live_feeds`, named in the homepage's own
state; no robots.txt on the host). Built as `apptegy-feed-*` for Johnson #1, Converse #2, Fremont #6, #14 and #24
(adapter `apptegy-feed`): the poller keeps a post only while it was published within 36 hours. Riverton #25's and
Washakie #1's feeds hold no weather closing since they began; Fremont #2's and #21's WordPress sites post none; County 10
(Fremont County) answered 403 to its REST list and its category pages (dropped, not worked around); Oil City News' closing
stories name Natrona County School District, not a list of the county's schools.

**History proofs** (`snowlight.sources.stations.history`). A channel's own server-dated post is the list seen populated on
that day, as surely as a capture the archive made that morning, so it proves its source when kept as a history fixture
(`pipeline/tests/stations/fixtures/history/`: a live read of the feed page or REST answer, sliced to that one post, with
the post's own time as `captured_at`). The rule is stricter than for a capture (`notices.history_row_proves`): a
district feed's post must announce a closing, a delay, an early dismissal, a remote day or no school, for weather or
an emergency (Johnson #1 is proven by a delay: "all Buffalo School are on a One Hour Delay today", 2024-02-27; Fremont
#6 by its Pavillion school's closing for a water main break, 2026-08-18, Crowheart staying open) (a track meet cancelled for the weather, a
fieldhouse closed for a holiday, "school as scheduled ... if the storm ... we will proceed with an early dismissal" do
not), every day it names must lie within the dated window of its publication (an old day is a leftover), and the NWS
must corroborate it: an advisory or warning over one of the source's counties on the school day it is about or the
school day before, or an emergency the NWS does not record (Wind River's water main break of 2026-08-18). Without the
NWS record no weather post proves.

**Leftovers never prove.** Round 5's live reads had proven Greenville (MS) by "GPSD closed on January 16, 2024 (Due to
inclement weather)", still on its homepage on 2026-10-13. A line of a homepage's text now proves only when no day it
names lies outside the dated window of the read, and, naming none, when an NWS advisory or warning covered the district
within two school days of the read and the page did not already show the same line on an earlier school day (a line
repeated unchanged is the news of the read that first showed it: North Gem's "all North Gem schools are closed today"
proves by its captures of its first school day, 2026-02-18, under a Winter Storm Warning, not by the copies kept through
April). A line that
heads a news card with a posting stamp is judged by the day it was posted: Gulf (FL)'s "SCHOOL CLOSURES: Hurricane
Isaias" is the card posted on 2026-10-07 for the hurricane of 8-10 October 2026 (Hurricane, Tropical Storm and Storm
Surge Warnings on the panhandle coast), not a leftover of 2020 as round 6 wrote; it is read with its stamp
(`homepage.text_rows`) and proves as a dated post corroborated by the NWS (`notices._text_current`).

**Records.** `gaps.json`'s KIFI record (round 5: "no list (articles)") now names `npg-articles-kifi`; County 10's says it
answered 403. The coverage gate's records (`gate records`) are rewritten for the states still short; the gate never
calls a state settled while a first-hand record of a source not built says "not read" or was checked before
2026-10-01 (`open_records`; round 5). The stale "not built" records of Lee, Polk and Marion (FL) that contradicted the
built and proven `sharpschool-*` sources were dropped in round 5.

## Round 4 of the coverage gate (s4, 2026-10-13)

**What the critic found.** Round 3 left Fox 13 Salt Lake (`scripps-typed-kstu`) out as not working, though a
real capture proves its list (2023-02-26T22:06:04Z, 41 rows of Utah districts, body SHA-256 `f6d037f5…`): its
page today holds one undated leftover row ("Provo City School District will operate on a Two Hour Late Start
schedule on Tuesday"), and the live reader called an undated typed page `stale`, so the station stopped
counting. Utah's settled verdict rested on that. It also called Gray list files stale only because their
`Last-Modified` was older than the last winter, in markets where weather seldom closes schools (WWSB, proven
during Milton in October 2024; WTOC, last written two days after the January 2025 snow).

**Typed rows judged against the page's earlier reads** (`typed_history.py`; `fetch.py` step 5). A row typed
into a page that says no time for itself is now judged on its own: `dated` when its heading, note or line names
a day near the read (kept, as on 2023-02-22, "WEDNESDAY, FEB. 22"); `past` when every day its words name is
gone (KSTU's page on Sunday 2023-02-26 still held its rows under "WEDNESDAY, FEB. 22" and "THURSDAY, FEB. 23");
`new` when a read of the page made within 36 hours did not hold it (kept); `old` when every read since the
last one without it held it and the first of them is more than 36 hours old; `unknown` otherwise. Two reads
hold the same row when they hold the same key (the row's name, status, time and context, whitespace and case
aside). The earlier reads are the archived captures the archive parse read (`archive/reads.jsonl` and
`rows.jsonl`) and every live read since, kept in `out/internal/stations/typed-history.json` (internal). A read
keeps its dated and new rows; with none kept it is `empty` when every row is old or past (the station counts
as working), and `stale` only when a row cannot be told from an old note. KSTU's Provo row (the same key in the
archived captures of 2025-05-20, 2025-09-16, 2025-12-17 and 2026-05-09 and in every live read since; the
capture of 2025-02-11 shows the empty page) is an old note, so the page reads `empty` today: "its 1 rows have
stood unchanged for more than 36 hours (…; the page has held 'Provo City School District' unchanged since the
archived capture of 2025-05-20T01:35:53Z, and the archived capture of 2025-02-11T13:09:45Z did not hold it)".
Two of those captures are now fixtures (`groups/scripps-typed/kstu-page-20250520013553.html`,
`kstu-page-20251217132420.html`). KSTU counts as working, and its 2023-02-26 capture proves it.

**Staleness per closure season** (`seasons.py`; `fetch.py` step 4; `snowlight stations seasons` writes
`out/internal/stations/closure-days.json`). A list last written before the last winter began (its file's
`Last-Modified`, or the time the list says it was updated) is `stale` only when weather that closes schools
came to its market after that and the list was not written for it; otherwise it is idle, its rows (any left
from its last closure) are old and not kept, and the read is `empty`. Closure weather is the NWS record the
closure weights count (IEM's archived warnings, school years 2015-16 to 2025-26 and the current one so far,
placed in counties by the zone-county correlation, a school day counting under the 6 AM rule): a school day on
which Winter Storm, Blizzard, Ice Storm, Lake Effect Snow, Hurricane or Tropical Storm Warnings covered
counties holding at least half the schools of the station's market (its county list, or its districts);
closure days at most three days apart are one event, and a list written the day before an event's first day
was written for it. A warning over part of a county counts for the whole county, as the weights count it, so
the rule errs toward `stale`. Counted through 2026-10-12 (the current school year's file was fetched on
2026-10-13; it holds the Hurricane Warnings of 8-9 October 2026 on the Mobile - Pensacola - Panama City
coast). The 18 lists the old rule called stale (KSTU was the 19th):

| Source | Market | Last written | Now | Why | Proof |
|---|---|---|---|---|---|
| `abc-owned-kabc` | Los Angeles | 2019-02-12 | `stale` | missed 2019-03-12 (WS.W over 75% of its schools), and 26 more to 2026-02-16 | - |
| `abc-owned-kfsn` | Fresno-Visalia | 2019-02-12 | `stale` | missed 2019-05-16 (WS.W over 78% of its schools), and 45 more to 2026-04-21 | - |
| `abc-owned-kgo` | San Francisco-Oakland-San Jose | 2019-02-12 | `stale` | missed 2023-02-24 (WS.W over 86% of its schools) | - |
| `gray-kgns` | Laredo | 2023-08-22 | `stale` | missed 2025-01-21 (WS.W over 100% of its schools) | - |
| `gray-kjct` | Grand Junction-Montrose | 2022-02-24 | `stale` | missed 2022-04-12 to 2022-04-13 (WS.W over 100% of its schools), and 19 more to 2026-02-17 | - |
| `gray-kkco` | Grand Junction-Montrose | 2022-02-24 | `stale` | missed 2022-04-12 to 2022-04-13 (WS.W over 100% of its schools), and 19 more to 2026-02-17 | - |
| `gray-kmvt` | Twin Falls | 2025-08-23 | `empty` | no closure event since; the last before: 2025-02-13 to 2025-02-14 (WS.W over 100% of its schools) | 2020-03-20, 18 rows |
| `gray-kplc` | Lake Charles LA | 2019-09-19 | `stale` | missed 2020-08-26 to 2020-08-27 (HU.W over 100% of its schools), and 4 more to 2025-01-21 | - |
| `gray-wafb` | Baton Rouge LA | 2024-05-17 | `stale` | missed 2024-09-11 (HU.W, TR.W over 100% of its schools), and 1 more to 2025-01-21 | - |
| `gray-wcjb` | Gainesville FL | 2019-09-19 | `stale` | missed 2020-11-11 to 2020-11-12 (TR.W over 93% of its schools), and 5 more to 2025-01-22 | - |
| `gray-wcsc` | Charleston SC | 2021-03-18 | `stale` | missed 2022-09-28 to 2022-09-30 (HU.W, TR.W over 100% of its schools), and 5 more to 2025-01-22 | - |
| `gray-wect` | Wilmington NC | 2022-01-21 | `stale` | missed 2022-09-29 to 2022-09-30 (HU.W, TR.W over 100% of its schools), and 4 more to 2025-01-22 | - |
| `gray-wflx` | West Palm Beach | 2023-08-24 | `stale` | missed 2024-09-25 to 2024-09-26 (TR.W over 100% of its schools), and 1 more to 2024-10-09 | - |
| `gray-wjhg` | Panama City | 2024-04-11 | `stale` | missed 2024-09-25 to 2024-09-26 (HU.W, TR.W over 100% of its schools), and 2 more to 2026-10-08 | - |
| `gray-wtoc` | Savannah | 2025-01-24 | `empty` | no closure event since; the last before: 2025-01-22 (WS.W over 100% of its schools) | 2025-01-22, 23 rows |
| `gray-wvue` | New Orleans LA | 2024-01-16 | `stale` | missed 2024-09-11 to 2024-09-12 (HU.W, TR.W over 100% of its schools), and 1 more to 2025-01-21 | 2024-01-15, 2 rows |
| `gray-wwsb` | Tampa Bay | 2024-10-12 | `empty` | no closure event since; the last before: 2024-10-08 to 2024-10-09 (HU.W over 100% of its schools) | 2024-10-07, 2 rows |
| `sinclair-ktxs` | Abilene - Sweetwater, TX | 2025-06-09 | `empty` | no closure event since; the last before: 2023-01-30 to 2023-02-01 (IS.W, WS.W over 100% of its schools) | - |

**Effect** (live reads merged as before, with a full fetch under the new rules, 2026-10-13 08:23 to 09:48 UTC:
944 sources, 76 ok, 706 empty, 14 stale, 6 error, 142 skipped; WRCB and KOAM/KXLY, refused with 429 in it, were
read again at 09:51 to 09:58, and KXXO's server did not answer): five sources became working (KSTU, WTOC, WWSB,
KMVT, KTXS), four of them proven (KTXS, Abilene, has no proof; Texas meets the target).

| Share (plain / closure-weighted) | Round 3 | Round 4 |
|---|---|---|
| National, covered by a working source | 97.8% / 99.0% | 97.9% / 99.1% |
| National, proven | 85.4% / 96.0% | 86.5% / 97.3% |
| UT, proven | 45.1% / 48.6% | 100.0% / 100.0% |
| NV, proven | 29.1% / 67.3% | 34.7% / 87.1% |
| WY, proven | 66.8% / 68.3% | 76.3% / 75.7% |
| ID, proven | 66.6% / 62.5% | 81.0% / 75.6% |
| FL, proven | 60.9% / 60.6% | 67.8% / 68.0% |

Utah meets the target and leaves the gate's table (and `gaps.json`'s records: only states short of the target
have records). Nevada, Wyoming and Idaho keep records, rewritten by `gate records`: KSTU is `proven` in
each, and the sources its counties overlap (KTVX's list among them) now add nothing. What is left: Nevada's Las Vegas market
(Clark, Nye and Lincoln counties, 543 schools; Scripps' KTNV `all-read`, no other list; weighted the state is at
87.1%), Wyoming's Fremont, Teton, Lincoln and Big Horn Basin districts (Teton's Finalsite page `unreadable`,
the Fremont and Washakie districts `storm-read` or `unconfirmed`), and Idaho's Idaho Falls - Pocatello
districts (Bonneville `unreadable`, Madison and Shelley `unconfirmed`, the rest `storm-read`).
The national plain share (86.5%) is still short of 95%, by 10,030 schools,
9,050 of them in California (17.3% proven, 70.2% weighted; settled: 10 of its sources are proven (KCRA
Sacramento, KGET Bakersfield, Reno's KOLO and Medford's FlashAlert at the edges, and six county-office and
district lists), and every other one is storm-read, unconfirmed, all-read, unreadable, not
working or without an endpoint; the ABC-owned lists of Los Angeles, San Francisco and Fresno have not been
written since February 2019 though warnings have come to all three markets since).

**Handoff (production fetch).** The live reader needs two internal files to apply these rules: `typed-history.json`
(kept from run to run; without it an undated typed page's rows are `unknown` and the read `stale` until 36
hours of reads accumulate) and `closure-days.json` (rebuilt by `snowlight stations seasons`, daily is enough;
without it every list last written before the last winter is `stale`, as before). The workflow that runs
`stations fetch` in GitHub Actions must keep the first and run the second first.

## Round 3 of the coverage gate (s4, 2026-10-05, resumed 2026-10-13)

**What the critic found.** Round 2 called all twelve short states settled, but several verdicts rested on
storm-day captures the adapters had not read: KULR's `/schoolclosures/` page of 2019, a closings article
listing 25 Montana schools, refused by the Cowles adapter; Orange County's homepage of Hurricane Ian
(2022-09-28), whose banner slide said "All Schools/District Offices Closed Wednesday, Thursday and Friday",
read as a page that loads its alerts elsewhere; Indian River's homepage of Tropical Storm Eta (2020-11-08),
whose news said "SDIRC Closed Monday Nov. 9", read the same way; Apptegy homepages from before Nuxt 3 logged
as errors ("no `__NUXT_DATA__` payload", 889 reads); Edlio and Apptegy headlines (Robstown, Victoria, West
Jefferson, Sweetwater #2, Juab, Murray and a dozen more) read as empty; and Granite, Jordan, Canyons,
Washington and Provo (277 Utah schools) had no source at all, though Granite's alerts come from a readable
WordPress REST file.

**The closure-text check** (`snowlight stations gate text-check`, `closure_text.py`). Every downloaded
capture of every working source the coverage result leaves unproven is read a second time, as text: the
text a visitor sees (scripts, styles, templates and a form's option lists removed; a menu's entries, its
lists, buttons and short links, removed but the rest of the navigation kept; `aria-hidden` sliders and
`noscript` fallbacks kept, since a visitor sees them; inline tags merged into their block, two inline runs
side by side kept two words; one line per block; for a JSON answer, its string values). Each line that
announces a closing (a closing, delay, dismissal, remote day, cancelled classes or no school, by the notice
gate's own patterns, not a planned day, naming weather, an emergency, a day or a date; a line about
procedures or policy needs a day) or states a district's weather status for a named day ("School will be
in session and follow regular schedules at all PCSD 25 schools today, Wednesday, January 5, 2022. Please
continue to expect winter driving conditions") is looked for in what the adapter read; a title and the
line under it are also read together when only the two together say it (Okaloosa's slide "Weather Alert:
Tropical Cyclone 16" over "Schools are in session Friday ..."), never a date or a posting stamp over a line
and never a link to a procedure. Each capture gets an outcome: `unrecognized` (its adapter refused it),
`missed` (it showed a closing or status line no row of its read holds), `shell` (a page that loads its list
from an address the archive does not hold, showing no closing itself), `cut` (the archive holds only the
first 1 MiB of the page and the part it holds shows nothing), `read` (it showed such lines and its rows
hold every one) or `clean`. The outcomes, with each capture's lines, are in `archive/closure-text.jsonl`,
summed in `archive/closure-text.json`, which records the SHA-256 of the coverage result whose sources were
checked; `gate report` refuses a check made against another coverage result. Two texts are excused as a
page's own furniture (`closure_text.BOILERPLATE`): the NBC stations' empty-state sentence and the Santa Cruz
COE page's heading and introduction.

**The audit: a wider net over the same captures.** Beside the check, `gate text-check` writes
`archive/closure-audit.json`: for every capture checked, the lines of its raw text (only scripts, styles,
templates and the head removed: menus, footers and hidden elements read) that hold any status word
(closed, cancelled, delay, late start, remote, no school, snow day, open, in session, ...) and any weather or
emergency word (weather, snow, ice, storm, hurricane, cold, roads, power, fire, conditions, ...), that the
check did not count and no row holds, by source, each with how many captures showed it and the first.
Nothing there changes a verdict; it is the list of what the check excused, for review by eye. Its last run
(2026-10-13, over the final coverage result's unproven sources) excused 143 distinct lines from 2,734 captures
of 39 sources touching the short states, and every one was read by eye in the capture it came from: menu and
quick links ("Emergency School Closure" in Soda Springs' quick links, "Snow Day Messaging" in Weber's menu, "Snow
Day - Remote Learning Lessons" in Cache's, "Emergency Closure or Delay Start" in Iron's), pages about procedures
and policies (Salt Lake City's "schools will be open on all regularly scheduled school days unless ..."), winter
and Christmas breaks, makeup days ("Snow Day Makeup Days set", Fremont #6, 2023-03-28), the NBC stations'
empty-state sentence, and TV stories about roads, fires and storms. Two of those stories show a list unused on
a storm's morning: KFMB's closings page of 2023-01-30 carried the story "Winter storm brewing over San Diego
County causes school closures and rain preparations" while its own list said "No delays or closings.", and
KNBC's of 2025-01-08 linked "List of LA County schools, districts closed due to brush fires" beside its empty
list. None was a closing or a status line the check should have counted.

**The gate's rule: a misread capture keeps its source open.** A source with a capture in its closure window
that its adapter refused (read state `error`, whatever the closure-text check said of it), that is
identical by digest to a capture the check found misread, or that the check found `missed`, gets the
verdict `misread`, which is not terminal: it can never be `storm-read`, `no-storm-capture`, `unreadable`
or `all-read`, and the states it touches stay open, until that capture's form is read (`misread` and
`window_misread` in each address's census). A page its adapter recognized as one that loads its list from
an address the archive does not hold is now its own read state (`shell`, no longer counted as `error`), and
is not misread unless it showed a closing or a status line itself. A page that took to loading its list by
script hides nothing of the file it loads: the time from which an address shows no list a read can see
(`blind_since`) is now taken per address, so the captures of the file stay due (Granite's homepage loads
its notifications from `wp-json/wp/v2/en` from 2023-03-10 on; the file's captures are asked for).

**The forms added**, each from a capture the check or the audit flagged (fixtures in
`pipeline/tests/stations/fixtures/gate/`, provenance in its `PROVENANCE.json`):

- Cowles: KULR's `/schoolclosures/` closings article of 2019-2021 (`cowles-closures-article`: each bulleted line
  a row, "Amsterdam School CANCELED", "Belgrade School District 2-HOUR DELAY", under "Statewide school delays
  and closures for Monday, March 4" (2019); the article's time is its rows' time and the listing is typed);
  NonStop Local Montana's section pages of 2019-2021 (`cowles-section-cards`: one row per story card; a card
  proves the list only when it announces a closing for weather or an emergency).
- SharpSchool: the banner rotator (`sharpschool-banner-slider`: Orange's "Hurricane Ian" slide of 2022-09-28).
- District homepages in any form, read as text beside their alert channel (`homepage.py`): a homepage read in
  a known form gets a `page-text` row for each closing or status line its text shows that no row holds
  (Indian River's "SDIRC Closed Monday Nov. 9 Due to Potential Storm Impacts From Tropical Storm Eta"); a
  homepage that loads its alerts from a file and shows such lines of its own is read as those lines, still
  following the file; a homepage in no form any reader knows (a district's site before its current platform)
  is read as text (`homepage-text`) instead of being refused. Only a reader's "none of my forms"
  (`NoFormError`) sends a page to its text; a malformed page in a known form is still an error.
- Older forms of the current platforms: Apptegy homepages that are SharpSchool or Edlio pages; Finalsite's
  2019 template; a Web Community Manager important-announcements region must be an element, not the class
  name in a theme script.
- TV pages: TEGNA's Liferay pages of 2017-2018 whose site settings name no closings system (KBMT) and its
  2019-2020 sub-index pages with no closings module (KFMB) are read as pages that hold no list; Sinclair's
  2020 shells that set `sinclairDigital.facade` without a site slug (KMPH) are followed to the list file.
- Finalsite's empty page-pops answer as the archive replays it (the brotli stream of an empty body).
- The second pass (the audit's first run, this afternoon) found what the check itself had not read:
  Seminole's homepage slider of 2022-11-10, marked `aria-hidden="true"` ("Tropical Storm Nicole Update:
  District & School Closures"); Okaloosa's newswire inside its `<nav>` ("Schools will be in session on
  Friday ... We will continue to monitor weather conditions", 2019-10-17); Madison's district news
  "Hurricane Debby Closure" (2024-08-04: a named storm's closing is a closing); Lander's "Lander Schools
  will not have school on Tuesday, January 3, 2023 to allow crews to clear routes" (clearing routes and
  "dangerously low wind temperatures" are now weather; "will not have school" a closing); and the weather
  status lines above (Pocatello, Okaloosa).

**What page text proves.** A homepage's text is whatever the page shows: news teasers, a calendar's entries,
pages about how closings are decided. A page-text line proves its district's channel only when it announces a
closing, a delay, a remote day, cancelled classes or no school **and names weather or an emergency**, is not a
planned day or a planning document, and is not a teaser or an explainer unless it names the day
(`notices.page_text_closing`); or when it states the schools' status (open, in session, a regular schedule,
an on-time start, or a closing) for a named day and names weather (`notices.page_text_status`: the
channel rule's weather notice, Bozeman's "Cold Weather Update: ALL BSD7 schools are OPEN", held to a named
day). A question is no status ("Why Do Schools Try to Stay Open in Bad Weather?", Murray's news of
2023-02-27), nor is a game postponed. A closing that names no reason does not prove by this rule, even on a
storm's day: RYSS's "RYSS schools will be closed on Jan 15, 2024 ... Enjoy your day off!" fell on one of its
storm days and was Martin Luther King Jr. Day.

**A dated closing on a warning day (resumed 2026-10-13).** The weather service can supply the reason a notice
leaves out (`notices.dated_closing`). A district's notice of a closing, a delay, a remote day, cancelled
classes or no school, naming no reason, proves its channel when it names its day (or two or three days, not
a run: "No School, April 4-8", "Dec. 20 - 31" and "through" never do) by date, each day between 5 days before
and 3 days after the capture's school day; no day it names is a weekend, a federal holiday, Thanksgiving's
Wednesday to Friday or the winter holidays (20 December to 2 January); it names no other reason (COVID-19, an
illness, a threat), no planned day, procedure, teaser or question, and does not say the day is ordinary ("no
early dismissal", "a regular school day"); and an NWS warning (Winter Storm, Blizzard, Ice Storm, Lake Effect
Snow, Extreme Cold or Wind Chill, Hurricane or Tropical Storm; a Winter Weather Advisory alone is not enough)
covered one of the district's counties on a day it names, by the closure weights' own record (the Iowa
Environmental Mesonet's archive, the 6 AM rule; `storms.warning_days`). The warning is recorded with the proof
in `coverage.json` (`district_notice_gate`, each kept proof's `warning`: day, weight, county). Granite's
"Distance Learning Day for Granite School District – Wednesday, February 22, 2023" (a Winter Storm Warning over
Salt Lake County that morning; the next day's "2-Hour Delayed Start", under an advisory only, would not have
done) and Canyons' "Remote-Learning Day Announced for all CSD Schools for Friday. Dec. 2" (2022, a Winter Storm
Warning) now prove their channels, which round 3 had called `unconfirmed`; so do Converse #1's "No School in
Converse 1-October 13, 2021" (a Winter Storm Warning that day; its page that week also said "In-person school is
cancelled in all buildings today ... a virtual learning day"), Putnam's "All Putnam County schools will be
closed on Friday, September 8th, and Monday, September 11th, 2017" (Irma's Hurricane Warning on the 11th),
Edinburg's "Delayed Start to Class on Jan 26, 2026", Rockport-Fulton's "January 26, Two-Hour Delay", Roma's
and Sinton's delayed starts of that Monday (an Extreme Cold Warning over each county). RYSS's MLK Day, Canyons'
"Schools, District Office Closed Feb. 21" (2022, Presidents' Day, under an advisory), Darby's "No School Friday,
February 15th and Monday, February 18th in observance of President's Day", Glendive's "No School All Day - Jan
2, 2018" (no warning) and San Benito's "CLOSED Thursday, January 20 and Friday, January 21, 2022 due to
COVID-related health and safety issues" (a warning that day, but another reason) do not. Every row the rule
accepts over the archive's and the live reads' rows was read by eye: 29 distinct rows of 20 sources, each a
storm's closing or delay (Hemet's, "Idyllwild and Hamilton Schools: Possible Delayed Start Time on 1/27/25", a
delay the storm might bring).

**Proofs dropped this round.** A standing description of how closings are announced or decided proves
nothing without a day (`notices._SERVICE`, in the channel rule and the page-text rule): Missoula's
announcements app's "Notifying students and staff about severe weather-related school closures or delays"
(which had proven Missoula on the morning of 2026-10-05) and Clark County's (Idaho) "Cold Weather Recess ... our recess
policy" of 2019-12-12 (which had proven it since round 2) no longer do; Clint ISD's notice of 2020
("postponing all evaluation activities ... due to COVID-19 closures as per Texas Education Agency
guidelines") no longer does either. Citrus' slide of 2020-11-13, read until now as one word run "Storm
Update: Hurricane EtaThe latest on school closures", is read as "... Hurricane Eta The latest on school
closures", a teaser, and proves nothing. Against round 2's result (2026-10-05T04:35Z), two proofs are
gone, both by these rules: Clark County, Idaho (2 schools no other proven source covers, 7.8 weighted; now
`storm-read`) and Clint ISD, Texas (14 schools, 1.0 weighted; now `unread`, Texas meeting its target). Every
other source proven then is proven now; 58 more of the sources round 2 recorded for the short states are,
among them the five Cowles stations, Orange, Indian River, Juab, Murray, West Jefferson, Sweetwater #2,
Robstown, Victoria and the rest of the critic's list. Against the restored round-1 evidence of 2026-09-29
(81.97% proven), nothing is lost.

**Verdicts.** `unconfirmed` (terminal): a source whose window captures were all read, one or more of them
showing a closing that its rows hold but that does not prove it (a notice or a page-text line that names no
weather or emergency and that no NWS warning corroborates, or a story card). Nothing left in the archive's window can settle it, but its list may
well be in use. In the short states 18 sources end `unconfirmed` (their gains, the schools each would add
that no proven source covers, sum to 243 schools and 257.9 weighted): Salt Lake City (35), Citrus (26), Box Elder (22), Twin Falls (18), Sweetwater #1 (15), Madison
(Idaho, 12), Uintah (12), Logan (9), Carbon (9), Uinta #1 (8), Shelley (7), Oroville (6), Durham, Fremont #14
and Hot Springs #1 (3 each), Washakie #2 (1), Weston #1 (0) and Washington County (54). What each showed is in
its record (`closure-text.jsonl`'s `read` captures): a COVID-19 closure (Box Elder, Durham, Sweetwater #1,
Fremont #14), a calendar's day off or break (Carbon's "NO SCHOOL on Monday, February 8th", read 12 days ahead;
Logan's "Offices closed Dec. 20 - 31"; Washington County's "no school tomorrow, Friday, April 3, or Monday, April
6 ... a fun and relaxing long weekend"), a weekly early out (Madison, Washakie #2), a closing of one building
(Uinta #1's "no school Monday 10/24 at Evanston High School only"), a hearing on closing schools for good (Salt
Lake City), a teaser (Citrus' "The Latest on Hurricane Eta and School Closures"), an e-learning reminder with
no warning that day (Shelley), and Weston #1's "2 hour late start February 18th and 19th", read a month after
(an advisory only on the 18th).

**Utah's five districts** (`district_homepage.py`, `district-homepage.yaml`; each read first-hand on
2026-10-05 with the project's User-Agent, robots and terms recorded): Granite (84 schools no other proven
source covers) loads its emergency notifications from `/wp-json/wp/v2/en?notification_type=district`, read
as a JSON list (`[]` live); Washington County (54) loads `alert.washk12.org/endpoint.php` (one alert live,
"NEW STUDENT REGISTRATION", which proves nothing); Provo (21) renders an alerts section into its homepage;
Jordan (69) and Canyons (49) render what they post into the page, read as text. Read over their archives
(runs 37269655553, 37298989093 to 37299069183, 37315173427 and, for Washington County's last ten
closure-window captures, 38351695086 of 2026-10-13): Jordan is proven by its homepage of 2023-02-25 ("Due to
adverse travel conditions, snowed-in buses, unplowed streets ... Thursday, February 23, will be a virtual
learning day for all students in Jordan School District", 7 rows), Provo by its alerts section of 2025-03-18 ("2 Hour Late Start
and Below Bench Bus Pickup Tomorrow 3/18", a Winter Storm Warning over Utah County that day), Granite by its
homepage of 2023-02-23 (its featured bulletin "Distance Learning Day for Granite School District – Wednesday,
February 22, 2023", corroborated by that day's Winter Storm Warning) and Canyons by its homepage of 2022-12-04
("Remote-Learning Day Announced for all CSD Schools for Friday. Dec. 2", a Winter Storm Warning that day).
Washington County's homepage captures read are pages that load `alert.washk12.org/endpoint.php` (240 of
253; 12 more the archive replayed as another capture), but one, of 2026-04-03, showing "A friendly reminder
that there will be no school tomorrow, Friday, April 3, or Monday, April 6 ... a fun and relaxing long
weekend"; the file's 388 captures read hold only "NEW STUDENT REGISTRATION" and a "CHRISTMAS BREAK" alert
(2020-12-27), so it ends `unconfirmed`. Utah's proven share rose from 22.9% (round 2) to 45.1% of schools (48.6% weighted);
what is left is KTVX's list (`all-read`: 763 schools, 1,162.7 weighted, every archived capture read and none
with a row), KSTU's typed page (`not-working`: its live page still shows the Provo late start of 2025-03-18, a
note no winter since has changed, as its archived captures of 2025-05-20, 2025-09-16, 2025-12-17 and
2026-05-09 show), Weber (`storm-read`, 53 schools), Iron (`storm-read`, 16), Cache (`unreadable`, 25) and the
six Utah districts among the `unconfirmed` above.

**Result.** From the final run of 2026-10-13 (coverage 06:36Z, gate 06:46Z, over the live fetch of that morning merged
with the earlier fetches and the restored evidence of 2026-09-29): 100,904 of 118,132 schools proven (85.4%),
96.0% closure-weighted, against round 2's 83.5% / 92.8% and the restored round 1's 81.97% / 91.7%; 490 of 780
working sources proven. The weighted national target is met; the plain one is not (11,322 schools short), and
40 of the 49 states (with DC) meet the state target. Alabama now does (100% / 100%: WALA's list file, `stale` on
2026-10-05 (last written 2025-10-27), held rows again in the morning's fetch, and Saraland's live notice of 2026-10-09 "Saraland City Schools will cancel school and
close all campuses on Friday, October 9, due to the impending severe weather forecast"), Montana does since the
Cowles list of 2019 (97.8% / 98.6%) and Texas does (91.3% / 95.0%). The nine short states, proven share plain /
weighted: Arizona 77.4% / 87.1%, California 17.3% / 70.2%, Florida 60.9% / 60.6%, Idaho 66.6% / 62.5%,
Louisiana 77.5% / 78.4%, Mississippi 71.1% / 68.8%, Nevada 29.1% / 67.3%, Utah 45.1% / 48.6% and Wyoming 66.8% /
68.3%. Every source touching them has a terminal verdict (the table above; none `misread`, `unread` or
`not-listed`), so each is settled, and the national target with them. The closure-text check of the final
coverage result read 12,127 captures of its unproven sources: 8,023 clean, 3,979 shells, 123 showing a closing
their rows hold that does not prove them, 1 cut by the archive (Frenchtown's Nuxt 2 homepage of 2023-12-02, its
text showing nothing) and 1 refused (WNTZ's page of 2025-09-11, a closings block holding only "Test Block per
Support", outside any of its closure windows); none `missed`.

**What was run.** `snowlight stations archive parse` over every downloaded artifact (twice: after the Washington County alert
fix, and after run 38351695086 brought its last ten closure-window captures; 20,456 reads, 118,945 rows);
`snowlight stations fetch` of every live source (2026-10-13 04:57 to 06:23 UTC: 944 sources, 76 ok, 702 empty,
19 stale, 5 errors, 142 skipped; 62 read although robots.txt disallows them, recorded), and again for the four
that failed (Canyons and KOLR read empty; WLS's file answered HTTP 403 and KXXO's host reset the connection,
both as before); `snowlight stations merge-live` of the restored 2026-09-29 evidence and every fetch since
(1,002 reads kept, 200 older populated reads of another body kept as proof beside a newer one);
`snowlight stations coverage` (with the NWS warning days); `snowlight stations gate text-check --jobs 3`;
`snowlight stations gate report`; `snowlight stations gate records`. One archive run was asked for this
resumption (commit 236b258, run 38351695086: ten captures of Washington County's homepage and alerts file, all
downloaded). Gates in the worktree: `ruff check`, `ruff format --check`, `mypy --strict snowlight tests` (only
the frozen status parser's two known errors) and `pytest`.


## Round 2 of the coverage gate (s4, 2026-10-04 to 05)

**What the critic asked.** Proven coverage stood at 82.3% of schools (91.8% closure-weighted) and twelve
states were under 90%, with 238 unproven sources still `unread` or `older-unread` and 6,637 storm-day
captures unread. The round was to keep reading storm-day captures in weighted-gain order until each short
state is at 90% proven or every source in it has a terminal verdict, and to decide whether a station's own
former closings address can prove it.

**Decisions this round.**

- *A station's own former address of its list proves it.* The proven share asks whether an outlet's
  closings channel is used at all, and a station that moved its own list on its own site still runs the
  same channel; the gate already took a capture of the current address in an earlier form of the page
  (Lee's 2022 hero slider at leeschools.net) as proof, so the two are now one rule. The registry names each
  such address in `former_urls`, with the evidence of the move (a redirect from the old address to the new
  one, or the station's own list on the same site, read by the station's own adapter), and `coverage.json`
  says which address each proof read (`address`: `current`, `former` or `earlier`; `proves`). Registered:
  KPAX Missoula (`/weather/school-closings-delays`, the Scripps closings module of kpax.com in 2019 to 2021,
  read as `scripps-closings-module`, the variant its current page reads; 404 live), Alachua County Public
  Schools (sbac.edu, which answers 301 to alachuaschools.net) and KENS San Antonio's two closings articles
  (below). Not registered, so they prove nothing: KGUN's and KTNV's `/weather/school-closings-delays` (no
  capture of either ever held the Scripps module; both answer 404 since 2019) and the files of another
  operator's closings system that a page once framed (WOWK's PSG files; WTVA's Allen Media files: its
  page loaded Allen's counter, which said 106 closings on 2026-01-26, and framed Allen's `ftp2.wtva.com`
  list until at least 2026-01-27, but by 2026-09-26 the same page loads a Gray export, a different
  operator's system, of which the archive holds no capture). KPAX's former
  address was then read in full: 500 captures, 492 empty, 8 the archive replays as 404; its verdict is
  `all-read`.
- *When a source is settled: its closure window.* Reading every archived capture of every source is not
  possible (the open sources' listings held about 150,000 unread captures, most of them district homepages
  captured daily), and most of them cannot show a list in use: a closings list holds rows on the days
  schools close. A source is settled once every capture of its list made in its *closure window* is read
  with no row. The window is its closure days (its storm days: school days with an NWS winter, cold or
  tropical warning or advisory over one of its counties, the days the critic counted; and the days a proven
  whole-county list sharing one of its counties held a row in an archived capture: fog, fire, power-cut and
  hurricane-eve closures the NWS codes miss) **and the two days either side of each**. `calibration` in
  `gate.json` (rebuilt with every report) checks the premise on the archive's own record: for each proven
  source, whether any read capture in its window showed its list in use, with its own rows left out of its
  closure days. Of the 233 proven whole-county lists
  with two or more captures read in their window, 231 showed their use in one of them (WDEL showed it only
  outside its window, in 3 window reads); of the 51 proven district channels with two or more, 49 did
  (Clint ISD and South San Antonio ISD showed it only outside). Without the two days either side, 2 of 152
  lists and 9 of 42 channels with two or more closure-day reads showed nothing on their closure days, so
  the near days were added. What this measures is where the evidence of a list's use falls (on or near
  the days schools close), which is why a source is settled on its window; it does not measure how often a
  list in use shows a row in any one capture, so a source settled on one or two window captures rests on
  less than one settled on many (`window_seen` in each record says how many).
- *Verdicts.* `storm-read`: every capture of the list in its closure window read, none with a row, at least
  one of them showing the list (`window_seen` in `gate.json` and in each `gaps.json` record counts them);
  `no-storm-capture`: the same, but no capture in the window shows the list (the archive holds none made
  there, or only page shells), while captures of other days did: no archived capture on or near a day its
  schools could have closed is left to read, which is the bar's "no storm-day capture exists anywhere".
  Both are terminal, beside `all-read`, `unreadable`, `no-capture` and `no-endpoint`. Fair-weather captures
  of a `storm-read` or `no-storm-capture` source stay counted as unread in its census.
- *Captures that cannot show the list are not due.* Captures from before a page took a form its adapter
  reads (`readable_since`) are not asked for; neither are those from after it became a shell
  (`blind_since`: at least three reads after the last one that saw the list, every one a page that loads its
  list by script, a redirect, a refusal or a 404). Each station's `readable_since` and `blind_since` are in
  `gate.json`.
- *The census.* A capture the archive replays as HTTP 404 or 410 counts as read (state `gone`); a capture
  the archive answered with a redirect to another address counts as read (`redirect`); a capture answered
  429 in three different hours by separate runs (each after the workflow's four tries with backoff) while
  those runs read hundreds of other captures counts as read (`refused`: ABC4's capture of 2025-02-12 07:58
  UTC, a revisit record of a 776-byte answer, was answered 429 by four runs between 06:50 and 15:59 UTC on
  2026-10-04); revisits of a 404 page or a redirect the listings hold are left out.
- *Every source touching a short state, not only those that could add a school.* A source whose schools
  another proven source already covers keeps no state open, but its verdict is recorded too: `gate plan
  --due --only` now plans such sources, and run 37247664710 asked for the closure-window captures of the 24
  that were still `unread` (KXTV Sacramento, Westby, Weston County 1 and 21 more) and listed Medicine Lake's
  homepage. Of the 24, 15 are now `storm-read`, 6 `unreadable` and 1 `no-storm-capture`; WMC
  Memphis is proven (its list held 6 rows on 2022-01-05, all of them in counties other proven lists cover);
  Medicine Lake's homepage, once listed (139 captures), had 27 captures in its window, read by run
  37262162443: its homepage's reads are 14 empty and 14 in an earlier form of its site, none with a row,
  so it is `storm-read` too.
  Every one of the 548 sources touching the twelve short states now has a final verdict.

**KENS' closings page linked to an article in 2022 and 2023.** Every capture of kens5.com/closings from
January 2022 to September 2023 (29 captures: one of 2022-01-23 and 28 from 2022-05-18 to 2023-09-22) held
no closings module, only a raw-HTML module: "For a list of closings in our area please click this link."
Round 1 counted those captures as read, but the TEGNA adapter refused them (`unrecognized shape`), so KENS'
`all-read` rested on 29 captures whose list was never read.
The adapter now reads that page as `tegna-closings-link` (deferred to the linked page) and the article as
`tegna-closings-article` (each heading followed by a statement is a row: the district, and its statement;
"No report." entries are not rows; the article's "Updated:" line is the rows' time), and run 37243433721
listed both articles and read their captures nearest KENS' storm days. "School closings due to winter
weather in San Antonio, Texas" listed 23 closures for 20 January 2022 (Northside, North East, San Antonio,
Southside ISD, ...) and 41 statements for 21 January; "FULL LIST: San Antonio and South Texas school
closings and delays" listed six closures for 3 February 2022 (Blanco, Boerne, Kerrville, Luling, San Marcos
CISD, Texas A&M-San Antonio), then held only "No current report." entries from 23 February 2022 (last
updated 25 February 2022) to its last capture of 24 March 2023. Both articles are KENS' own list at
another address on its own site, linked from its closings page as its list, so they are registered as
former addresses and KENS is proven (856 Texas schools that no other proven source covers). Its current
module was never seen holding a row: 311 captures from 2016 to 2024, in the page's three templates, read
empty, and the module that replaced the link in 2024 has three captures (May, July and November 2024), none
on a storm day; its `gaps.json` record keeps that census. No other station's captures were in that form (the other TEGNA captures the adapter
refuses are KFMB's pages of 2019-2020, before its `readable_since`; KBMT's 110 Liferay pages of June 2017
to January 2018, whose closings setting was `type:"None"`, no list; and two YouTube pages).

**More than the window, where it matters most.** For the largest whole-market lists of the short states,
every capture was asked for, not only the window's, so their verdicts rest on all of their captures:
ABC4 Salt Lake (KTVX): all 403 captures of its closings page (402 empty; the 403rd the archive refused
with HTTP 429 to four runs) and the 4 of its page's REST form, `all-read`. KPAX Missoula: all 500 captures
of its former address and the 10 of its current one, `all-read`. NBC 6 Miami (WTVJ): all 821 captures of
its page (791 empty, 30 answered with another capture) and the 6 of its list endpoint, `all-read`. CBS 8
San Diego (KFMB): all 112 (97 empty, 15 of its 2019-2020 template, before `readable_since`), `all-read`.
Spectrum News San Antonio: all 175 captures of its list file (one digest, empty) and 114 of its page,
`all-read`. NBC Los Angeles: 1,038 captures read (1,013 empty, 25 answered with another), one fair-weather
capture left that the archive did not serve, `storm-read`. KMPH Fresno: all but one of its page's 197
captures (187 load its list file) and all 12 of the file (empty), `storm-read`; KSEE Fresno: 263 of 268
(255 empty), `storm-read`; KBMT Beaumont: 267 read (150 empty; 110 of June 2017 to January 2018, whose template's closings
setting was `type:"None"`, no list), `storm-read`. NBC Bay Area (KNTV), NBC San Diego (KNSD) and KSBY San
Luis Obispo were read in their windows only (250 of 3,754, 140 of 889 and 63 of 675 captures; 175, 70 and
16 window captures saw the list, every one empty), `storm-read`.

**The four pages the critic could not confirm**, opened in Chromium on 2026-10-04 at 02:20 UTC with the
project's User-Agent (records kept outside the repository): NonStop Local Montana's closings page (the
Cowles stations KFBB, KULR, KTMF, KWYB, KHBB) loads its S3 ticker, which says "No Closings have been reported
at this time" (the ticker's own line: "Closings Last Updated at 9:13am on 4/16/2026"); NBC Los Angeles' page
says "Forecast: School's Open. But don't worry, we update this page regularly so you'll be the first to know
if your school is closing or will have delays due to bad weather." and its list endpoint
(`/wp-json/nbc/v1/school-closings`) answers `[]`; KOMO's page frames
`/resources/ftptransfer/komo/closings/komoclosings.html`, which says "UPDATED SATURDAY, OCT 3 AT 7:20 PM There
are no active records at this time."; Lee County's homepage shows no alert, and the alert service its script
posts to answers `{"d":[]}`. Each adapter's empty read matches what the page shows.

**The notice gate, tightened.** Beaumont Unified's homepage alert of 2023-01-15 ("Input Needed on Beaumont USD
Local Hazard Mitigation Plan ... flash flooding, high windstorms ...") had passed the district notice gate on
its hazard words and proved the source; a planning document or a call for feedback that names hazards no
longer counts as a weather notice (`notices._PLANNING`; a real-row test pins it). No other kept proof was a
planning notice. Beaumont is proven again, by its homepage alert of 2020-04-08 ("Update: School Campuses
Ordered to Close Until June 19, 2020"): the channel announced its schools' closing. The other proofs of this
round that rest on a weather notice rather than a closing word were read one by one (Bozeman's "Cold Weather
Update: ALL BSD7 schools are OPEN", Del Norte's "Schools to Remain Open if Buses Can Run - National Weather
Service Weather Warning", Woodsboro's "anticipates school beginning at the regularly scheduled time ...
continue to monitor local weather", Orange Grove's "Cold Weather Update" alert of 2026-01-26): each is a
district's weather status on the channel that would carry its closing. A SharpSchool hero slider's other
slides ("Bus Drivers WANTED") are kept as raw rows, as every adapter keeps what its list shows; they prove
nothing, since the notice gate keeps a district channel's proof only for a row that announces a closing.

**Result.** Proven: 98,627 of 118,132 schools (83.49%), closure-weighted 109,678.7 of 118,132.1 (92.84%);
round 1 ended at 97,217 (82.30%) and 91.83%. 427 of the 774 working sources are proven (398 of 771 in
round 1). The change, school by school (+1,410; each source's schools that no other proven source covers):
KENS +856 (Texas, through its closings articles); Utah +209 (Davis 95 and Alpine 91, whose earlier
WordPress homepages carried their February 2023 snow-day alerts, and Ogden 23); Texas +182 more (Brownsville
51, Ysleta 47, PSJA 42, Southwest ISD 18, Clint 14, Orange Grove 4, Santa Gertrudis 2, Agua Dulce 2,
Woodsboro 2); Montana +55 (Billings 34, Bozeman 13, Shelby 5, St. Regis 3); California +51 (Alvord 26,
Beaumont 14, Del Norte 11); Florida +43 (Hernando 32, Hardee 11); Idaho +32 (Idaho Falls 22, Blaine 8,
Clark County 2). WZDX Huntsville and WMC Memphis became proven too, adding no school no other proven list covers. No source proven in round 1
lost its proof. Area coverage (a working source, proven or not) is unchanged: 115,409 schools (97.69%),
closure-weighted 98.93%. Twelve states remain short of 90% (AL weighted only, and TX plain only), and every
one of them is now *settled*: every source whose proof would add a school to it has a terminal verdict
(`gate.json`: `settled` for each state and nationally; `open` is empty everywhere).

| State | Proven | Weighted | Round 1 | What keeps it short |
|---|---|---|---|---|
| AL | 90.7% | 81.7% | 90.7% / 81.7% | Mobile County's homepage (90 schools; the archive holds no capture of it in a closure window that shows its alerts: `no-storm-capture`) |
| AZ | 77.4% | 87.1% | 77.4% / 87.1% | KGUN Tucson's list (529 schools): all 6 captures of its page empty; its older address was never its list |
| CA | 17.1% | 70.2% | 16.7% / 69.8% | 2,305 private schools only a whole-market list can cover; NBC Los Angeles, Bay Area and San Diego, KMPH, KSEE, CBS 8 and KSBY read empty in every capture of their windows (CBS 8's in full; NBC Los Angeles' but one capture the archive did not serve); ABC7's and ABC30's lists stale since 2019 |
| FL | 49.7% | 47.3% | 49.0% / 46.5% | WTSP and First Coast News (TEGNA, 810 schools): the archive lists no capture of either page; NBC 6 Miami empty in all 821 captures; no capture of Orange's or Seminole's homepage in their windows is in a form that shows their alerts (`no-storm-capture`) |
| ID | 63.4% | 58.6% | 59.8% / 53.2% | Bonneville's and Pocatello's archived homepages are in forms no adapter reads or load their alerts by script (`unreadable`); ABC4's reach into Idaho read empty |
| LA | 77.5% | 78.4% | 77.5% / 78.4% | WGMB Baton Rouge's list (empty in every capture the archive serves; the rest replay a 404), KATC's never captured |
| MS | 70.6% | 68.3% | 70.6% / 68.3% | WTVA Tupelo (201 schools): its Gray list was never captured; its Allen-era files were another operator's |
| MT | 23.3% | 21.9% | 17.5% / 17.0% | the five Cowles stations (ticker never captured; their 2019-2021 pages were article cards) and KPAX (all 510 captures of its two addresses empty or a 404) |
| NV | 29.1% | 67.3% | 29.1% / 67.3% | KTNV Las Vegas' list (543 schools): all 5 captures empty |
| TX | 88.2% | 93.8% | 78.4% / 84.4% | 184 schools short (weighted met): KBMT Beaumont (169; every window capture empty) and South Texas district homepages read empty in their windows |
| UT | 22.9% | 24.9% | 5.6% / 5.9% | ABC4's list (927 Utah schools): all 403 captures empty; FOX 13's list stale since March 2025; Granite, Jordan, Canyons, Washington and Provo have no source (homepage alerts loaded by script, checked 2026-10-03) |
| WY | 51.7% | 57.6% | 51.7% / 57.6% | ABC4 and KULR's reach into Wyoming (above); Teton, Sweetwater 1 and Uinta 1 homepages unreadable in the archive |

**Markets.** All 206 markets have a working source, 182 a whole-county one and 183 a proven one. Of the 25
largest, eight lack two working whole-county sources or a proven one: Los Angeles, San Francisco - Oakland -
San Jose, Miami - Ft. Lauderdale, Tampa - St. Petersburg and Salt Lake City (one whole-county list each,
none proven), Orlando - Daytona Beach (district sources only), Phoenix and Sacramento - Stockton - Modesto
(two, one proven). What the markets' other stations publish is in the first-hand checks
(`docs/research/firsthand/`) and, for the short states, in each source's `gaps.json` record.

**What was run.** The live reads: a full fetch on 2026-10-05 from 00:42 to 02:05 UTC (939 sources: 49 ok,
725 empty, 20 stale, 3 errors, 142 skipped, 849 rows), merged with the reads of Sep 29, Oct 3 and Oct 4 as in
round 1 (`stations merge-live`: for each URL the newest read, and the newest populated one beside it). The
archive: 53 runs from 2026-10-04 01:58 to 2026-10-05 04:07 UTC (37169638112 to 37262162443), asking for 10,768 captures and 66 listings, every request and result recorded in `pipeline/config/sources/archive-wanted-s4.json`.
From `pipeline/`:

    uv run snowlight stations fetch --out-dir out/internal/stations/fetch-20261005
    uv run snowlight stations merge-live .cache/stations/evidence-20260929/stations/reads.jsonl \
        out/internal/stations/reads.jsonl out/internal/stations/fetch-sharpschool-20261003/reads.jsonl \
        out/internal/stations/fetch-20261004/reads.jsonl out/internal/stations/fetch-20261004b/reads.jsonl \
        out/internal/stations/fetch-20261005/reads.jsonl --health out/internal/stations/health.json \
        out/internal/stations/fetch-sharpschool-20261003/health.json \
        out/internal/stations/fetch-20261004/health.json out/internal/stations/fetch-20261004b/health.json \
        out/internal/stations/fetch-20261005/health.json --out-dir out/internal/stations/live-merged3
    uv run snowlight stations archive parse .cache/stations/artifacts
    uv run snowlight stations coverage --health out/internal/stations/live-merged3/health.json \
        --live-reads out/internal/stations/live-merged3/reads.jsonl
    uv run snowlight stations gate report && uv run snowlight stations gate records
    uv run snowlight stations gate plan --due    # empty: no capture keeps a short state open

## Round 1 of the coverage gate (s4, 2026-10-03, resumed after the pause)

**What was measured.** The machine was reset to an older snapshot during the pause, so this round rebuilt
what the measure reads: the closure weights (`snowlight.weights build`, 20:13 UTC), the archive's reads
(`stations archive parse` over the 126 downloaded artifacts: the restored Sep 29 captures, every run of
round 1 from 2829f15 to bfc9910, and run 37152148780: 4,348 capture reads, 113,999 rows), a full live
fetch (2026-10-03 20:10 to 21:34 UTC: 936 sources, 47 ok, 721 empty, 20 stale, 6 errors, 142 skipped)
and a live read of the three stations added this round (21:45 to 21:46 UTC). The live reads of Sep 29
(restored from the owner's data repository) were merged with today's by `stations merge-live`: for each
URL the newest read, and the newest populated read beside it when the newest is not populated, so the
lists seen populated on Sep 29 stay proven (20 such reads kept); today's two health files were merged the
same way (each source's last read). Only one proof rests on the Sep 29 reads alone: WLIO Lima's list (7 rows
on Sep 29; 48 Ohio schools that no other proven station covers). From `pipeline/`:

    uv run python -m snowlight.weights build
    uv run snowlight stations fetch
    uv run snowlight stations fetch --only sharpschool-lee-fl sharpschool-marion-fl sharpschool-polk-fl \
        --out-dir out/internal/stations/fetch-sharpschool-20261003
    uv run snowlight stations archive parse .cache/stations/artifacts
    uv run snowlight stations merge-live .cache/stations/evidence-20260929/stations/reads.jsonl \
        out/internal/stations/reads.jsonl out/internal/stations/fetch-sharpschool-20261003/reads.jsonl \
        --health out/internal/stations/health.json \
        out/internal/stations/fetch-sharpschool-20261003/health.json --out-dir out/internal/stations/live-merged
    uv run snowlight stations coverage --health out/internal/stations/live-merged/health.json \
        --live-reads out/internal/stations/live-merged/reads.jsonl
    uv run snowlight stations gate report && uv run snowlight stations gate records

**Result.** Proven: 97,217 of 118,132 schools (82.30%), closure-weighted 108,486.2 of 118,132.1 (91.83%);
on Sep 29 it was 96,837 (81.97%) and 91.66%. The change, school by school (+380): Florida +340 (the three
SharpSchool district sources below: Lee 118, Marion 61, Polk 161, each proven by its own homepage in the
archive), Texas +21 (South Texas ISD, 7, whose live page pop of 20:47 UTC today says "STISD Weather Update:
All STISD activities for Saturday, Oct. 3, have been canceled"; South San Antonio ISD, 14, whose Web Community
Manager homepage of 2021-01-16 23:43 UTC announced "SSAISD Update: District Closure"), Utah +18 (San Juan
School District, 11, whose homepage banner of 2026-02-17 cancelled school at La Sal Elementary for a power
outage; Park City, 7, whose homepage pop of 2024-05-06 announced a bus service interruption) and Arizona +1
(San Juan's school in Arizona). KCAU Sioux City, Erie and Warren County (Pennsylvania) became proven too,
in states already covered. Nothing was lost: WRCB Chattanooga answered HTTP 429 to every attempt today, so
it does not count as working, but every school it covers is covered by another proven station; Lake Elsinore
Unified (California, 24 schools, never proven) moved its homepage from Edlio to Finalsite, so its Edlio source
fails today (recorded in its health). Area coverage (a working source, proven or not): 115,409 schools
(97.69%), closure-weighted 98.93%. 37 of the 49 states (with DC) meet the 90% proven target; 398 of the 771
working sources are proven.

**New this round.**

- *SharpSchool district sites* (`sharpschool.yaml`, adapter `sharpschool`): the Lee, Marion and Polk county
  school districts' homepages load their emergency alerts by script from a service that answers only POST
  (round 2 of the gap-state part left them unbuilt for that reason). The registry now carries a station's
  `data_post` (the page script's own JSON body) and the poller posts it, with no conditional request and no
  redirect followed. The archive keeps no answer to a POST, but it kept the homepages' earlier forms, and
  run 37152148780 found the closures there: Lee's hero slider of 2022-10-04 03:52 UTC (Hurricane Ian: all
  schools and offices closed 3-7 October) and Marion's Web Community Manager announcements of 2022-09-27
  23:56 UTC (Ian) and 2023-08-28 18:07 UTC (Idalia), and Polk's WordPress homepage of 2022-09-28 10:03 UTC,
  whose Smart Slider storm slide said the county's public schools were closed 27-29 September (Ian).
- *robots.txt behind redirects*: the SharpSchool sites send `/robots.txt` on to `/robots.txt/Default.aspx`;
  the polite client asked for robots.txt again for each such hop (an endless loop). It now reads robots.txt
  and its redirect hops without consulting itself; a test covers the chain.
- *The gate's verdicts* separate `older-unread` (no unread capture of the station's current page or data file
  remains; only captures of addresses it read before are unread, and they cannot prove the current list) from
  `unread`, and every census entry says whether its address is the current one.
- *The map*: `coverage.png` draws a second map, of what the proven share counts (bright: a source seen with
  rows; dim gold: a district source seen with rows; violet: only working sources never seen with a row;
  grey: no working source), and `coverage.json`'s `proven` block holds the per-county proven numbers.
- *Archive requests*: five runs this round (records and results in
  `pipeline/config/sources/archive-wanted-s4.json`): 37151360115 (235 of 237 captures read: NBC Los Angeles,
  Bay Area, San Diego and Miami 40 each, ABC4 8, KREX 7, KSEE 7, KMPH and KENS, all empty or deferring to a
  list file the archive did not keep, on their markets' storm days and largest winter captures; the 46
  district captures the gate still wanted proved South San Antonio ISD), 37151594707 and 37156919678 (488 of
  500 storm-day captures of the unproven district homepages of Utah, Montana, Idaho, Wyoming, Florida and
  Texas: San Juan and Park City proven, the rest empty, notices that announce no closing, or Finalsite
  homepages that defer to page pops the archive does not hold), 37152148780 (the SharpSchool homepages) and
  37161083109 (250 more district storm days, still running when this was written; its artifact is kept 90
  days). The lesson of the second and third: a Finalsite homepage holds no list of its own (it loads its page
  pops by script) and the archive holds almost no page-pops capture near one (Bozeman's homepage: 3,179
  captures listed; its page pops: 6), so asking for more Finalsite homepages proves nothing.
- *The capture plan* (`stations gate plan`) leaves out captures from before the last one a station's adapter
  refused ahead of the first it read (`gate.readable_since`): a district that moved its homepage to the
  platform its adapter reads leaves captures of its older site that cannot prove it.

**Why the twelve states stay short.** The per-source evidence is in `gaps.json` (each record's `gate`
block); in short:

- *California* (16.7%; 2,305 of its 12,448 schools are private, so only a whole-market list can reach 90%):
  NBC Los Angeles' list read empty in every capture of the January 2025 fires read (23 captures from 6 to
  15 January) and of its storm days; ABC7 Los Angeles, ABC7 San Francisco and ABC30 Fresno say their lists were
  last updated on 2019-02-12 (stale); FOX, CBS and the other Los Angeles and Bay Area stations publish no
  list; Los Angeles Unified's homepage answered this project's User-Agent with HTTP 403 when checked on
  2026-10-03 (an active block, so it is not read).
- *Utah* (4.1%; 139 private schools): ABC4's list, the only whole-market list naming Utah's schools, read
  empty in 115 captures from 2021 to 2025, storm days included; FOX 13's typed list has held one undated
  Provo entry of March 2025 since then (stale), though it was the list Utah used in February 2023 (41 rows);
  KUTV publishes none, and KSL showed no closings page when checked on 2026-10-03. The districts' homepages are proven one by one
  (Nebo, San Juan and Park City so far); Granite, Jordan, Canyons, Washington and Provo have no source yet
  (WordPress sites; Granite's and Washington's homepage alerts load by script, checked 2026-10-03).
- *Montana* (17.5%): NonStop Local Montana's ticker (the Cowles stations) is read live, but the archive has
  never captured its file (the listing of its folder holds no capture), and the section pages captured in
  2019-2021 are an earlier form (cards linking to articles). KPAX's current page has 10 captures, all
  empty.
- *Florida* (46.3%; 1,974 private schools): no Florida TV station publishes a readable list today (WTSP's and
  First Coast News' pages were never captured; the rest publish none), so the private schools cannot be
  covered; the districts are proven one by one (21 district sources and WCTV so far).
- *Nevada, Arizona* (29.1%, 77.4%): every capture of KTNV Las Vegas' and KGUN Tucson's current pages (5 and
  6) read empty; the hundreds of captures of their earlier address cannot prove the current list; their
  markets rarely close for weather.
- *Texas, Louisiana, Mississippi, Alabama, Idaho, Wyoming*: the remaining whole-market lists (KENS and
  Spectrum San Antonio, KBMT, WGMB, WTVA, KTVX in Idaho and Wyoming) were read empty on every storm-day
  capture the archive holds or are not captured at all; the district sources there are proven one by one,
  and the runs above read more of their storm days.


## Round 5 (2026-09-28, from 22:22 UTC): Finalsite sources read through their homepages

The critic's finding on round 4: the Finalsite adapter could not tell an empty list from a broken read.
`/fs/pages/<id>/page-pops` answers HTTP 200 with an empty body for the right page ID, for a made-up one and for one
that is not a number, and the adapter read that body as an empty list (`finalsite-no-page-pops`) with no page check,
so all 82 Finalsite sources reported "working, empty" whatever page they pointed at, and coverage counted 984 schools
(502.8 closure-weighted) as covered by Finalsite alone.

### Confirmed first-hand

Read with the project's client (`gap_fixtures capture`: its User-Agent, robots.txt first) at 22:43 UTC: Billings'
`/fs/pages/999999/page-pops` and `/fs/pages/abc/page-pops`, and Chickasaw's `/fs/pages/999999/page-pops`, each HTTP 200
with 0 bytes (SHA-256 `e3b0c442…`, the empty string), while Chickasaw's page 2 holds a pop (1,089 bytes at 14:31 UTC).
The address proves nothing unless the page named it.

### The fix

- **Adapter** (`finalsite.py`): reads the homepage now. A published Finalsite page (`<body data-pageid="N"
  class="fsLiveMode ...">`) is a deferred listing (`finalsite-homepage`) that follows `/fs/pages/N/page-pops`, the
  address the page's own script builds. A page with `fsLiveMode` but no `data-pageid`, an empty one or one that is not
  a number (`abc`, `-2`), a `data-pageid` without `fsLiveMode`, and any page that is not a Finalsite page raise
  `ShapeError`. The page-pops fragment and its empty answer read as before.
- **Registry** (`finalsite.yaml`): every station registers no `data_url` now, so the poller reads its homepage
  (`page_url`) and follows it. Each station's `page_check` is a browser check of its homepage
  (`finalsite_pagecheck.cjs`, headless Chromium with the project's User-Agent, 22:37-22:44 UTC): all 82 homepages
  asked for exactly one page-pops address, of their own `data-pageid`, answering 200, each with the page ID
  registered before (as the critic's check found). The address is the station's list file (loaded by script) and archive URL,
  and `snowlight stations robots --update` records both URLs' verdicts (164, all allowed). Two homepages redirect now:
  `laramie2.org` to `www.laramie2.org` and `www.fpcvpaa.com` to `www.fpcarsonacademy.org` (the same academy, by its
  title); their pages are read at the new addresses, the old ones kept as archive URLs.
- **Framework** (small, additive; `fetch.py`, `cli.py`): `fetch.page_check_mismatch` holds a live read of a station
  polled at its page (no `data_url`) with a `page_check` to what the check saw: the page must name one of the checked
  files and is followed to it; a page that names another file, or none (an empty homepage, a page holding a list of
  its own), is an error, never an empty list. Only stations with no `data_url` and a `page_check` are affected (a test
  checks exactly that set); on 2026-09-28 they are the 82 Finalsite stations and no other part's. `stations robots` also records the checked
  files of such a station.
- **Tools** (`finalsite_check.py`): `targets` prints the homepages for the browser check, `apply` writes each
  station's page check, list file and archive URL and clears its `data_url`, and reports any homepage that redirected,
  asked for no page pops, several, or another ID than its body names.

Tests (`test_gaps_finalsite.py`, on real homepages): Billings', Chickasaw's and Baldwin County's live homepages
(IDs 2465, 2 and 10398) are followed to their own page pops, and end to end through the polite client to an empty
list (Billings) and to Chickasaw's pop; Gulf Shores' real homepage of 2020-11-01 names page 329 where the check saw
1994 today, and its live read is an error that never asks for page pops; San Benito's Edlio homepage of 2025-01-21 (the
district's site before it moved to Finalsite) is refused as not a Finalsite page, and so is an empty homepage; the
refusals of a missing, empty or non-numeric ID and of a page without `fsLiveMode`.

### Older homepages, read too (proof)

The archive holds the districts' homepages from before they moved to the current Finalsite template, and the adapter
now reads the two forms that carry an alert:

- an older Finalsite template that holds its page pops in the page (`finalsite-homepage-pops`): Volusia County
  Schools' homepage captured 2024-10-14 00:59 UTC holds one pop, "Hurricane Milton Update";
- the district's earlier Web Community Manager homepage (Schoolwires, a Finalsite product: the capture's footer reads
  "Copyright © 2024 Finalsite - all rights reserved."), read by its important announcements as the Apptegy and Smart
  Sites adapters read theirs: Palm Beach's homepage captured 2024-10-10 02:50 UTC announces "Learn more about the storm,
  including shelter information, by visiting the Palm Beach County Emergency Operations Center webpage ..." (Hurricane
  Milton), and that of 2024-09-27 "Schools and District Offices OPEN on Friday, September 27" (Helene; a reopening
  with no weather word, so the notice gate does not count it).

Both proving rows pass the notice gate (a weather or emergency notice for the district), so `finalsite-volusia-fl`
and `finalsite-palm-beach-fl` are proven by archived captures. The other Finalsite homepages the archive holds are
refused (Web Community Manager pages without the announcements app: Broward, Pinellas, Collier and Escambia FL in
October 2024, Great Falls in February 2022; other CMSs: the Alabama districts' sites before they moved, San Benito's
Edlio site)
or are current-template pages whose page pops were not captured near them (Gulf Shores, Pocatello, PSJA, Weslaco),
which the archive reader reports as pages it could not follow. Every re-read is in `gaps.json` (`captures_read`,
marked `reread`).

### The gap, recomputed (closure-weighted schools)

From `coverage.json` of 19:39 UTC (before) and this round's recount (after): the uncovered weight is unchanged, 1,339.7
(FL 581.9 · ID 261.2 · WY 109.0 · LA 96.9 · CA 81.0 · TX 74.2 · MS 59.8 · AL 29.4 · MT 22.4), since the Finalsite
sources were already counted as working; what changed is that each of them is now read the way its page reads it.
Not proven: 12,382.3 before, 12,227.7 after (MT 2,879.7 · FL 2,311.6 → 2,157.0 · UT 1,873.0 · TX 1,052.4 · PA 735.7 ·
ID 700.0).

### Live read after the fix (full fetch, 22:47 UTC to 00:08 UTC, every source)

896 sources: 55 ok, 676 empty, 20 stale, 3 errors (`abc-owned-wls` 403, `blox-wrcb` 429 after retries, `radio-kxxo` TLS
timeout; none of them this part's), 142 skipped. The 82 Finalsite sources: each read its homepage first (the read's `via` names the page,
variant `finalsite-homepage`, and the address it followed), then that page's pops: 70 empty (`finalsite-no-page-pops`),
12 with pops, 0 errors. None of the 12 announces a closing under the notice gate (Sharyland's "No classes - Friday,
October 2" is a planning day; Harmony's pops advertise a shop; the rest are events, a referendum, a bond election,
a trustee vacancy, a settlement notice, a clinic), so none proves its source. The schools only Finalsite reaches are
the same 984 (502.8 closure-weighted: FL 487 / 220.6, TX 196 / 50.4, CA 177 / 17.1, ID 59 / 134.1, WY 10 / 42.5,
AL 17 / 8.3, MS 19 / 11.3, OH 15 / 10.7, MT 4 / 7.9; measured by recounting with every Finalsite source set to error),
now read through a checked page; 319 of them (154.6) are proven through Palm Beach and Volusia.

### Shares before and after round 5 (plain / closure-weighted)

Before: `coverage.json` of 19:39 UTC (the critic's recount). After: this round's full live fetch and every downloaded
archive capture read again with the current adapters (3,682 reads, including run 36495159548). This is the
`coverage.json` and `coverage.png` written to `pipeline/out/internal/stations/`.

| Scope | Covered before | Covered after | Proven before | Proven after |
|---|---|---|---|---|
| national | 97.6% / 98.9% | 97.6% / 98.9% | 80.1% / 89.5% | 80.3% / 89.6% |
| MT | 99.0% / 99.3% | 99.0% / 99.3% | 15.5% / 14.0% | 15.5% / 14.0% |
| FL | 82.1% / 79.6% | 82.1% / 79.6% | 20.7% / 19.0% | 26.0% / 24.4% |
| ID | 83.3% / 82.5% | 83.3% / 82.5% | 59.8% / 53.2% | 59.8% / 53.2% |
| WY | 89.7% / 88.6% | 89.7% / 88.6% | 44.7% / 49.9% | 44.7% / 49.9% |
| TX | 97.3% / 98.8% | 97.3% / 98.8% | 76.5% / 82.3% | 76.5% / 82.3% |
| AL | 96.9% / 94.0% | 96.9% / 94.0% | 90.7% / 81.7% | 90.7% / 81.7% |
| CA | 94.1% / 96.0% | 94.1% / 96.0% | 16.7% / 69.8% | 16.7% / 69.8% |
| MS | 90.8% / 88.3% | 90.8% / 88.3% | 70.6% / 68.3% | 70.6% / 68.3% |
| OH | 99.7% / 99.8% | 99.7% / 99.8% | 98.1% / 98.7% | 98.1% / 98.7% |

Florida's proven share rises with Palm Beach (234 schools) and Volusia; the covered shares do not move, because the
Finalsite sources were counted before and are counted now, but now each count rests on a read that cannot come back
empty from a wrong page.

### Wayback (round 5): Montana's Finalsite districts

Run 36495159548 (commit 0cacc6a, 22:55 to 23:49 UTC): the 43 storm-day captures the planner picked from listings
already downloaded (`snowlight stations archive plan --per-season 3 --since 2022-09-01`: Great Falls', Havre's,
Hellgate's and Hobson's homepages, and Billings', Bozeman's, Kalispell's and East Helena's page pops) and 9 listings
(the Billings, Missoula, Bozeman, Kalispell, East Helena, Laurel, Lewistown, Thompson Falls and Baker homepages since
November 2018). 38 downloaded: Billings' and Bozeman's page pops empty; 24 current-template homepages (Great Falls'
among them on 2026-03-12 and 2026-03-13, the day NonStop's article lists closings for) that load their pops, which the
archive did not capture near them; 12 older homepages of the same districts on other CMSs, refused. No capture proves a
Montana Finalsite district yet; the new listings are in the cache for the next pick, and Montana's proven share stays
15.5% / 14.0%.

### Other things the critic's evidence exposed

- GOHSEP: the note that the layer was "seen with closures today" was misleading. Its live read keeps the statuses
  GOHSEP last entered, dated 2026-06-17 and 2026-06-18 (ten parishes closed, East Feliciana's early dismissal and planned
  closure) and 2026-09-01 (Cameron); the round 2 text in this file now says so. The proof stands (the rows are real
  closures on the standing layer), but it is a past incident's list, not that day's.
- Idaho's small uncovered districts the critic named, found by a web search (the LEA directory lists no Idaho
  website) and read once at 22:49-22:50 UTC: Aberdeen #58 (`asd58.us`, WordPress), Firth #59 (a Google Sites site;
  `firthschools.org` did not answer), Buhl #412 (`buhlschools.org`, Wix) and Ririe #252 (a Google Sites site). None has
  an alert or closings element to read: not built, recorded in `gaps.json`.

### Handoffs (round 5)

- **Part 1 (framework)**: two small hunks. `fetch.py`: `page_check_mismatch` and its call in `read_station` (and
  two docstring sentences); it applies only to a station with no `data_url` and a `page_check`, which today are the 82
  Finalsite stations. `cli.py` (`run_robots`): a station polled at its page also has the files its page check saw
  robots-checked. Commit them with this part (the tests are in `test_gaps_finalsite.py`).

## Round 4 (2026-09-28, from 14:23 UTC): Alabama and the Mobile - Pensacola market, then the rest of the ranking

The critic's finding on round 3: Alabama was third in uncovered closure-weighted schools (131.9) and had no
`gaps.json` record after three rounds. Mobile County (140 schools, 78.8 weight, the second-largest uncovered county in
the country) and Baldwin County (59 schools, 33.5) had no working source: their only one, `gray-wala` (part 1), is
stale because its list file was last written 2025-10-27. This round scouted every district of the Mobile - Pensacola
market's uncovered counties and the market's outlets, found and built Alabama's statewide closures list, built the
district sites as district-level sources, and asked the archive for their storm-day captures. It then went down the
rest of the ranking: the St. Joseph market (Missouri, all of it uncovered), and the district sites of the Glendive,
Alpena and Zanesville markets, the Mississippi Delta and coast, and California's Chico - Redding and Palm Springs
markets.

### The gap, recomputed at the start of round 4

From the critic's recount of 14:22 UTC (its full live fetch, 67 minutes, 846 sources; closure-weighted schools):

| Measure | Total | Top states |
|---|---:|---|
| Uncovered (no working source) | 1,680.8 | FL 600.4 · ID 261.2 · AL 132.0 · CA 112.3 · WY 109.0 · MO 101.5 · LA 96.9 · MS 76.4 · TX 74.3 · MT 45.4 · OH 26.3 · MI 24.9 |

Alabama's uncovered weight lay in seven counties, all in the Mobile - Pensacola market (Mobile 78.8, Baldwin 33.5,
Escambia 6.2, Clarke 4.7, Washington 3.2, Conecuh 3.0, Monroe 2.6), with Santa Rosa County, Florida (20.3) in the same
market. Every one of them was reached only by `gray-wala`.

### How it was scouted

1. Every school in those eight counties in the NCES CCD 2024-25 school directory: 301 (244 public, 57 private), in 17
   school districts (LEAIDs); the private schools belong to no district.
2. For each district, the website the NCES CCD 2024-25 LEA directory (`ccd_lea_029_2425_w_1a_073025.zip`, SHA-256
   `2745169e…`) lists: 17 sites, each homepage read once (14:27-14:42 UTC) with the scraper's User-Agent and robots.txt
   read first (`gap_fixtures capture`), fingerprinted by what it serves, and its alert file (Finalsite page pops, Smart
   Sites pop-up alerts) read once. Santa Rosa's listed website (`www.santarosa.k12.fl.us`, which round 2 could not
   read) no longer resolves; the district's site is `www.santarosaschools.org` (its title names the district).
3. The market's outlets (WALA, WKRG, WPMI, WEAR, WSRE, AL.com, Lagniappe, the Pensacola News Journal, Gulf Coast Media)
   and the state education department's homepage were read once the same way. The ALSDE homepage links a statewide
   "Weather Closure List".
4. Every district, outlet and agency is a record in `gaps.json` (`gap_state` AL, or FL for Santa Rosa, WSRE and the
   News Journal).

### Alabama's statewide list: built (`alsde-statewide`, new adapter `alsde`)

The Alabama State Department of Education's "Weather Closure List" page
(`https://www.alabamaachieves.org/weather-closure-list/`) frames its statewide "School Closures/Delays" list,
`https://schoolnotification.alsde.edu/SchoolClosuresPublic.aspx`: an ASP.NET page whose DevExpress grid is rendered on
the server with every report it shows (Date, System, School(s), Type of Closure, Opening or Closing Time, Reason,
activities cancelled, Superintendent Comments, Modified). Read live at 14:42 UTC it held four reports: Pike County's
early dismissal of 2026-09-25 at 1:00 PM (two schools, a water main break), Perry County's closings of 2026-09-16 and
2026-08-24 (a water-pressure failure, a threat) and Tallapoosa County's of 2026-09-14 (a septic failure). It is a
closings list, not a district's general channel, so any report proves it: **seen populated live, it is proven.**

- The new adapter (`pipeline/snowlight/sources/stations/alsde.py`) reads one row per school a report names (the
  school's name as written; the system, date, time, reason, comments, activities flag and school count in
  `raw_extra`), or one row named for the system when a report names no school; a grid with no data row is an empty
  list; a page without the grid, a grid without the System or Type of Closure column, or a row whose cells do not line
  up with the header raises. Real fixture: `alsde/closures-live-20260928.html` (sliced to the grid, reads the same).
- Archived captures (runs 36445058527 and 36470567011, below) are populated too, and each holds its school year's
  reports: 2022-06-05 (176 rows), 2023-08-30 (20), 2024-09-21 (29), 2025-01-21 17:26 UTC, in the Gulf Coast snowstorm
  (180 rows: 116 reports of 54 systems, most for "All Schools", the reason "Snow/Ice"), 2025-06-03 (387 rows: the whole
  2024-25 year, 67 systems) and 2026-05-17 (147). A report for "All Schools" is read as a
  row named for the system (`raw_extra["all_schools"]`), and a grid whose client state says it shows one page of
  several, or fewer reports than it holds, is refused (every capture read shows all its rows on one page). Real
  fixtures: `alsde/closures-20250121.html`, `alsde/closures-20250603.html`.
- The list names public school systems and their schools, not private schools, so the station is a district-level
  source, and it counts only **the systems it has been seen to name** (a real basis: the systems in its own lists):
  98 systems in the live read and the six archived captures (city, county and charter systems: Legacy Prep, i3
  Academy, LIFE Academy, Empower Schools, University Charter School), 841 schools in 60 counties, each name matched
  exactly to the district of that name in the LEA directory. **Mobile County is on none of them**, not even the
  captures of the January 2025 snow, when it was closed: it does not post there, so it is not counted through the list
  and is left to its own site. Baldwin County is (its closings of 2025-01-21 to 2025-01-24 are on the capture of
  2025-06-03, though not yet on that of 2025-01-21 17:26 UTC), and so are the market's smaller systems (Saraland,
  Escambia, Monroe, Conecuh and Thomasville for Hurricane Ida on 2021-08-30, Satsuma and Clarke for the snow of 2025,
  Orange Beach on 2025-01-22). More captures of the list would widen the set; the host's listing is in
  `archive-wanted-s4d.json`'s `still_wanted`.
- Terms: the ALSDE's Terms of Use make the site a public service where "the general public may use this system to
  review and retrieve publicly-available government information"; nothing about reading with software.
  `schoolnotification.alsde.edu` has no robots.txt (404). Recorded in `pipeline/config/sources/alsde.yaml`.

### The Mobile - Pensacola market's district sites: 15 built

| District (LEAID) | Schools | Weight | Site, platform | Live read, 2026-09-28 | Verdict |
|---|---:|---:|---|---|---|
| Mobile County (0102370) | 90 | 50.6 | mcpss.com, Apptegy | no banner | built (`apptegy-mobile-al`) |
| Baldwin County (0100270) | 44 | 25.0 | bcbe.org, Finalsite (page pops) | none | built (`finalsite-baldwin-al`) |
| Santa Rosa (1201650) | 39 | 18.0 | santarosaschools.org, Apptegy | a Title I survey banner | built (`apptegy-santa-rosa-fl`) |
| Escambia County (0101350) | 13 | 4.2 | escambiak12.net, Apptegy | no banner | built |
| Washington County (0103480) | 8 | 3.2 | wcbek12.org, Finalsite | none | built |
| Chickasaw City (0100188) | 5 | 2.8 | chickasawschools.com, Finalsite | "Parent University" (an event) | built |
| Conecuh County (0100870) | 9 | 2.7 | conecuh.k12.al.us, SchoolInSites | no alert element | not built |
| Monroe County (0102400) | 9 | 2.6 | monroe.k12.al.us, SchoolBlocks | empty alerts list | built |
| Clarke County (0100720) | 7 | 2.5 | clarkecountyschools.org, Finalsite | none | built |
| Saraland City (0100185) | 4 | 2.3 | saralandboe.org, Finalsite | none | built |
| Gulf Shores City (0100202) | 3 | 1.7 | gsboe.org, Finalsite | none | built |
| Orange Beach City (0103581) | 2 | 1.1 | orangebeachboe.org, Smart Sites | no alert | built |
| MAEF Public Charter Schools (0100197) | 2 | 1.1 | (the LEA directory's website field holds a street address) | - | not read |
| Satsuma City (0100189) | 2 | 1.1 | satsumaschools.com, Finalsite | none | built |
| Thomasville City (0103300) | 3 | 1.1 | thomasvilleschools.org, Apptegy | no banner | built |
| Brewton City (0100450) | 3 | 1.0 | brewtoncityschools.org, Apptegy | no banner | built |
| Floretta P. Carson VPA Academy (0103586) | 1 | 0.6 | fpcvpaa.com, Finalsite | none | built |
| Covenant Academy of Mobile (0103583) | 1 | 0.6 | camobile.us, Educational Networks | no alert element | not built |

No new adapter was needed for them: the Apptegy, Finalsite, Smart Sites and SchoolBlocks adapters read every page
and file (live fetch 14:34 UTC: 2 populated, 13 empty, 0 errors). Each names the LEAID the LEA directory lists with its
website and counts only that district's schools; robots.txt allows every URL polled (verdicts recorded with
`snowlight stations robots --update`). Real fixtures (live): Mobile County's homepage, Santa Rosa's homepage with its
survey banner, Chickasaw's and Baldwin County's page-pops answers, Monroe County's homepage; the two populated ones
are pinned as not proving under the notice gate. Baldwin County and the smaller Alabama systems seen on the ALSDE list
are proven through it; Mobile County (90 schools), Santa Rosa and the systems not seen there rest on their own
channels, which no capture has shown with a closing (below).

### The market's outlets (no other list)

- WALA FOX10 (part 1's `gray-wala`): its closings page still frames Gray's closings application, but the list file
  (`s3.amazonaws.com/grayfilestore-wala/closingsData/closings_WALA.json`) was last written 2025-10-27, so it stays
  stale. Handed to part 1.
- WKRG (part 2's `nexstar-wkrg`): `/closings/` answers 403 to the project's User-Agent (not worked around).
- WPMI NBC 15 and WEAR ABC 3 (part 3b's `sinclair-wpmi`, `sinclair-wear`): no closings link; `/weather/closings`
  redirects to `/error`.
- WSRE (now a Pensacola State College page), Lagniappe, the Pensacola News Journal and Gulf Coast Media: no closings
  list. AL.com answers 403 (dropped).

### The rest of the ranking: KQ2 (St. Joseph) and 33 more district sites

- **KQ2 (KQTV, St. Joseph, MO; News-Press & Gazette): built (`npg-kqtv`, new adapter `npg`).** The St. Joseph market
  (Buchanan, Nodaway, Andrew, DeKalb, Holt and Worth counties in Missouri, Doniphan in Kansas: all of Missouri's 101.5
  uncovered weight) had no registered source. KQ2's "Closings and Delays" page frames `https://ftp2.kq2.com/closings.html`,
  a NewsTicker-family export (schools post through schoolclosings.org's KNPN login) written this season
  (Last-Modified 2026-09-22) with its own empty sentence, "No currently active closings or delays to report.", which
  part 3b's NewsTicker reader does not know; the new adapter reads that sentence as an empty list, hands a file with
  postings to the NewsTicker reader, and follows the page to the file. Counties: the St. Joseph DMA. Its terms forbid
  automated means (the owner's decision of 2026-09-25 is recorded). Never seen with a posting yet: unproven, with its
  winter captures and listing asked in run 36445058527. The company's other stations (KESQ, KION, KIFI, KVIA, KRDO,
  KTVZ, KEYT, KMIZ) have no such file (their ftp2 hosts do not resolve) and no closings page.
- **33 district sites of the next gap counties** (the Glendive market in Montana, Alpena and Alcona in Michigan,
  Muskingum in Ohio, the Mississippi Delta and coast, Riverside, Butte and Del Norte in California), found the same way
  (68 sites of the LEA directory read 15:06-15:20 UTC): 10 Apptegy, 14 Finalsite, 4 Smart Sites, 2 SchoolBlocks and 3
  Edlio sites, live fetch 15:25 UTC: 4 populated (Alpena's meal-benefits banner, Durham's enrollment banner, Lake
  Elsinore's new-website alert, Coachella Valley's menu app: none a closing), 29 empty, 0 errors. Not built: the
  SchoolInSites (Connect Suite) sites of the Delta (Greenwood-Leflore, Sunflower, Greenville, West Bolivar, Western
  Line, East Tallahatchie, Carroll, Greene, Leland) and Richey (MT), and the Catapult CMS sites of the Chico - Redding
  market (Chico, Paradise, Corning, Evergreen, Red Bluff, Gridley, Palermo, Antelope, Los Molinos, Biggs, the Butte and
  Tehama offices), which carry no alert element; WordPress, Squarespace, Wix, Google Sites and SharePoint sites without
  one; and Corona-Norco and Desert Sands (no answer within 240 s), Picayune (its certificate did not verify), North
  Bolivar and West Tallahatchie (TLS handshake timeouts).
- The markets' stations: WHIZ (Zanesville) frames a BLOX closings block that reads "There are no closings at this
  time." (not built until a capture shows how a posting reads; asked in run 36445058527); WBKB (Alpena) answers 429 on
  every attempt; KXGN (Glendive), deltanews.tv (WABG/WXVT), Action News Now (KHSL), KRCR and NBC Palm Springs have no
  closings list.
- The other gap states' education departments (Idaho, Wyoming, Missouri, California, Montana) have no closings link on
  their homepages; Mississippi's and Michigan's answer 403.

### Wayback (round 4)

- Run 36409494144 (round 3's last request): its listings, still running when round 3 ended, were read (artifact
  `cdx-36409494144`, SHA-256 `998d1f19…`): 5 of 11 answered (Edinburg's and Los Fresnos' Edlio homepages, Livingston's
  and Uinta #1's homepages, Crossroads Today's closings addresses); the SchoolBlocks homepages', KRGV's, KVIA's, KZTV's
  and Telemundo 40's did not answer within the run.
- Run 36437310853 (commit 5f8dc25, listings only; artifact `cdx-36437310853`, SHA-256 `2edc77f4…`): 24 of 26 listings
  answered. Mobile County's homepage has 3,362 captures since 2017 (at most one per hour): real pages until May 2025,
  the archive's captures of Apptegy's bot challenge (about 1.7 kB) from June 2025 to March 2026, the present Apptegy site
  since April 2026; 29 lie in the storm-day windows. The other homepages have 25 to 931 captures, one or a few near each
  storm. The Finalsite page-pops files have at most three captures each (2025-2026, none on a storm day), Orange Beach's
  alert file none.
- Run 36445058527 (commit 78f659b, pushed 15:37 UTC; snapshots artifact `snapshots-36445058527`, SHA-256
  `a20f90d1…`, uploaded 18:53 UTC): 123 asked, 106 downloaded (93 distinct captures), 17 not (15 TLS handshake timeouts
  between the runner and the archive, WHIZ's block of 2025-01-10 answered 451, one 500). Read with the adapters:
  - **ALSDE: 11 populated** (four distinct captures, above): `alsde-statewide` is proven by the archive as well as live.
  - **KQ2: the capture of 2023-12-08 15:19 UTC holds two postings** (First Baptist Church, Savannah and St. Francis
    Baptist Temple: service changes), read by the NewsTicker reader: `npg-kqtv` is proven (a closings list proves itself
    with any entry). Its other captures (2019-2024) hold the same empty sentence as today. Fixtures
    `npg/kq2-closings-20231208.html`, `npg/kq2-closings-20190405.html`.
  - The Mobile - Pensacola district sites: 64 refused, 8 empty, none with a closing in the channel read. Mobile County's
    27 are its earlier SchoolInSites homepage (2022 to May 2025; on the snow days it shows only its calendar) and an
    older page (2018), with no alert element. Baldwin County's are Blackboard homepages (2018-2025): the Important
    Announcement app is empty on 2021-08-27; its District Announcements news list names the Zeta closure (2020-10-29) and
    its calendar a weather delay (2024-01-18), news and calendar, which are not read and prove nothing. Clarke's
    Blackboard page of 2020-10-30 has "ALL CLARKE COUNTY SCHOOLS ARE CLOSED FRIDAY, 10/30 DUE TO DAMAGE FROM HURRICANE
    ZETA" in its Announcements news list (the same). Santa Rosa's old WordPress homepage of 2020-09-19 carried the
    superintendent's Hurricane Sally closure message in its header, no alert channel either. The page-pops captures are
    empty (Baldwin's three, Satsuma's) or of other pages. So these district channels stay unproven: the archive holds
    no capture of the channels the adapters read on a storm day.
  - WHIZ's block: its one capture (2024-11-12) reads "There are no closings at this time." (not built).
  - The second batch's Apptegy homepages: Glendive, Plevna, Dawson County High School and Alcona in their Nuxt 2 form,
    empty on the winter-warning days; Alcona's banner of 2023-01-31 is a request for proposals; Alpena's, Maysville's and
    Dawson's other captures are earlier CMS pages or Apptegy's bot challenge (2025).
  Its listings (artifact `cdx-36445058527`, SHA-256 `3426bc6d…`): 4 of 6 answered. KQ2's ftp2 host: 43 captures of
  `closings.html` since 2018 (the April-May 2020 ones about five times the size of an empty file); WHIZ's block: 5
  (2024-2025); Escambia's and Orange Beach's homepages: 949 and 69. The ALSDE host's listing and the Weather Closure
  List page's did not answer within the run.
- Run 36470567011 (commit b682c8f, pushed 19:12 UTC after run 36445058527 ended; artifact `snapshots-36470567011`,
  SHA-256 `d00a4e46…`): 13 asked (the ALSDE list nearest nine more moments of 2022-2026, four unread captures of KQ2's
  file from its listing), 12 downloaded (one TLS timeout). The list's captures nearest those moments are two more:
  2024-09-21 (29 rows) and 2025-06-03 (387 rows, the whole 2024-25 year, 67 systems, Baldwin County's snow closings
  among them), which widen the station's systems from 94 to 98. KQ2's file: 2020-04-08 (63 postings, the pandemic),
  2021-01-28 (one school's delay: "NORTH DAVIESS R-III", "Classes delayed 2 hours"), 2021-10-27 (one posting); every
  form the NewsTicker reader reads. Fixtures `npg/kq2-closings-20200408.html`, `npg/kq2-closings-20210128.html`.


### Shares before and after round 4 (plain / closure-weighted)

Before: the critic's recount of 14:22 UTC (its full live fetch). After: the same fetch with this round's 49 new
sources added from their live fetches (14:34-15:25 UTC), and every downloaded archive capture read again with the
current registry (3,639 reads, including runs 36445058527 and 36470567011). This is the `coverage.json` and `coverage.png` written to
`pipeline/out/internal/stations/`.

| Scope | Covered before | Covered after | Proven before | Proven after |
|---|---|---|---|---|
| national | 96.9% / 98.6% | 97.6% / 98.9% | 79.9% / 89.4% | 80.1% / 89.5% |
| AL | 85.5% / 73.0% | 96.9% / 94.0% | 85.2% / 72.7% | 90.7% / 81.7% |
| FL | 81.5% / 79.0% | 82.1% / 79.6% | 20.7% / 19.0% | 20.7% / 19.0% |
| MO | 96.9% / 96.4% | 100.0% / 100.0% | 95.4% / 94.8% | 98.5% / 98.4% |
| KS | 99.4% / 99.4% | 100.0% / 100.0% | 99.4% / 99.4% | 100.0% / 100.0% |
| MT | 97.8% / 98.6% | 99.0% / 99.3% | 15.5% / 14.0% | 15.5% / 14.0% |
| MI | 99.7% / 99.6% | 100.0% / 100.0% | 99.7% / 99.6% | 99.7% / 99.6% |
| OH | 99.2% / 99.5% | 99.7% / 99.8% | 98.1% / 98.7% | 98.1% / 98.7% |
| MS | 88.2% / 85.0% | 90.8% / 88.3% | 70.6% / 68.3% | 70.6% / 68.3% |
| CA | 91.4% / 94.5% | 94.1% / 96.0% | 16.7% / 69.8% | 16.7% / 69.8% |

The counties (schools; schools covered; uncovered closure-weighted schools; before → after):

| County | Schools | Covered | Uncovered weight |
|---|---:|---:|---:|
| Mobile County (01097) | 140 | 0 → 102 | 78.8 → 21.4 |
| Baldwin County (01003) | 59 | 0 → 49 | 33.5 → 5.7 |
| Santa Rosa County, FL (12113) | 43 | 0 → 38 | 20.3 → 2.4 |
| Escambia County (01053) | 19 | 0 → 16 | 6.2 → 1.0 |
| Clarke County (01025) | 13 | 0 → 10 | 4.7 → 1.1 |
| Washington County (01129) | 8 | 0 → 8 | 3.2 → 0.0 |
| Conecuh County (01035) | 10 | 0 → 9 | 3.0 → 0.3 |
| Monroe County (01099) | 9 | 0 → 9 | 2.6 → 0.0 |
| Buchanan County, MO (29021) | 40 | 0 → 40 | 41.7 → 0.0 |
| Nodaway County, MO (29147) | 20 | 0 → 20 | 25.0 → 0.0 |
| Muskingum County, OH (39119) | 37 | 0 → 23 | 26.3 → 9.9 |
| Riverside County, CA (06065) | 593 | 0 → 309 | 44.5 → 21.3 |
| Butte County, CA (06007) | 99 | 0 → 13 | 35.9 → 31.1 |
| Alpena County, MI (26007) | 12 | 0 → 10 | 21.9 → 3.6 |
| Dawson County, MT (30021) | 11 | 0 → 4 | 25.2 → 16.0 |
| Fallon County, MT (30025) | 7 | 0 → 7 | 13.8 → 0.0 |
| Washington County, MS (28151) | 31 | 0 → 4 | 18.8 → 16.4 |
| Hancock County, MS (28045) | 14 | 0 → 11 | 6.8 → 1.5 |

What is left uncovered in the Mobile market is its private schools (57 in the eight counties; no district source can
count them) and MAEF's and Covenant Academy's charter schools. The ranking after round 4 (uncovered, closure-weighted):
FL 582 · ID 261 · WY 109 · LA 97 · CA 81 · TX 74 · MS 60 · AL 29 · MT 23 · OH 10 (total 1,340, from 1,681). Not proven
(uncovered, or covered only by lists never seen populated): MT 2,880 · FL 2,312 · UT 1,873 · TX 1,052 · PA 736 · ID 700
· CA 610 · WY 478 (total 12,382, from 12,538). Proven this round: the ALSDE list (live and six captures; 98 systems,
Baldwin County among them) and KQ2's file (its captures of 2020, 2021 and 2023). Mobile County's 90 public schools are
covered but not proven: its own channel has no capture with a closing, and it does not post to the ALSDE list.


### Handoffs (round 4)

- **Part 1 (s4a, Gray)**: `gray-wala` (WALA FOX10, Mobile) is stale: its list file was last written 2025-10-27, and the
  closings page's site settings now carry an empty `"closings_code":""` (read 2026-09-28T14:37:45Z), so the station may
  have stopped using Gray's closings system. Mobile and Baldwin counties are now reached by the ALSDE list and the
  district sites; the Florida side of the market (Escambia, Santa Rosa, Okaloosa) by the district sites only.
- **Part 3b (s4c2, NewsTicker)**: KQ2's ftp2 file (a NewsTicker-family export) writes "No currently active closings or
  delays to report." when nothing is posted, a sentence `newsticker.read_file` does not know; this part's `npg` adapter
  reads it and hands files with postings to `newsticker.read_file`. If another generator writes the same sentence,
  `newsticker` may want it too.
- **Part 1 (s4a, the framework)**: unchanged from round 3: the SharpSchool district sites (Lee, Polk and Marion, FL)
  serve alerts only to a POST.

## Round 3 (2026-09-28, from 01:43 UTC): South Texas

The critic's finding on round 2: Texas was skipped without first-hand proof that nothing readable exists there,
though it held 327 uncovered closure-weighted schools and three counties with no source at all (Hidalgo, Nueces,
Cameron), and the biggest districts there run platforms this part already reads. This round scouted every district
of Texas' uncovered counties, built the readable ones as district-level sources, and asked the archive for their
storm-day captures.

Second pass (from 08:06 UTC, after a container restart): the South Texas storm-day captures (run 36383349206) were
read; one, Mission CISD's Edlio homepage on the January 2025 snow day, showed how an Edlio homepage carries a closing,
so a new `edlio` adapter was built and all 18 Edlio district sites registered; a live SchoolBlocks alert (Grace,
ID) did the same for a new `schoolblocks` adapter (9 sites); the South Texas and Florida stations and newspapers
outside the groups were read first-hand; six unscouted Idaho and two Wyoming districts were read (four more
sources); and the next storm-day request (run 36409494144) was pushed and read, which proved Hidalgo ISD (Edlio)
and, through a new reader of Hardin's earlier Campus Suite homepage, Hardin (MT). Proven this round: Mission and
Hidalgo in Texas, Hardin in Montana (Grace's alert, a planned harvest break, does not prove). Texas' uncovered
closure-weighted schools fall from 327.5 to 74.3 over the round, Wyoming's from 195.1 to 109.0, Idaho's from 319.6 to
261.2 (see "Shares before and after round 3").

### The gap, recomputed at the start of round 3

From the critic's recount of 01:38 UTC (its full live fetch of 00:41-01:37 UTC; closure-weighted schools):

| Measure | Total | Top states |
|---|---:|---|
| Uncovered (no working source) | 2,192 | FL 600 · TX 327 · ID 320 · WY 195 · AL 132 · CA 112 · MO 101 · LA 97 |
| Not proven (uncovered, or covered only by lists never seen populated) | 12,564 | MT 2,900 · FL 2,312 · UT 1,873 · TX 1,059 · PA 736 · ID 700 · CA 610 · WY 478 |

Texas' uncovered weight lay in 22 counties, all in South and far West Texas: Hidalgo 85.2, Nueces 59.0, Cameron
49.2, Victoria 23.6, Webb 22.0, El Paso 19.5, San Patricio 15.2 and 15 smaller ones. The TV stations there were
checked by other parts and have no list (KIII's `/closings` redirects home, TEGNA, part 2; KVEO/KGBT, KTSM, Nexstar,
part 2; KRIS, Scripps, part 2, no closings page), so district sites are what reaches them.

### How it was scouted

1. Every school in those 22 counties in the NCES CCD 2024-25 school directory (1,250: 1,140 public, 110 private):
   128 school districts (LEAIDs), 296.6 of the 327.4 weight; the 110 private schools (30.9) belong to no district
   and no district source can count them.
2. For each district, the website the NCES CCD 2024-25 LEA directory (`ccd_lea_029_2425_w_1a_073025.zip`, SHA-256
   `2745169e…`) lists: 124 distinct sites. Each homepage read once, 01:43-02:15 UTC, with the scraper's User-Agent
   and robots.txt read first (`gap_fixtures capture`); La Feria ISD's host held the connection without answering
   (twice, 150 s and 200 s; not retried around).
3. Each page fingerprinted by what it serves (Apptegy's `__NUXT_DATA__` state, Finalsite's `data-pageid` and `/fs/`
   assets, Smart Sites' `PopUpAlertsComponent`, Edlio's `/apps/js/common/`, WordPress, SchoolBlocks, SchoolInSites
   and others) and its title checked against the district's name. The Apptegy pages were parsed as served; each
   Finalsite page's `/fs/pages/<data-pageid>/page-pops` and each Smart Sites page's `/api/popup-alerts` was read
   once (02:03-02:16 UTC): every one answered 200 and parsed.
4. Every district is a record in `gaps.json` (124 records, `gap_state` TX): its LEAIDs, school count, weight, site,
   platform, robots verdict, what the page showed, and the verdict.

### Built in round 3: 79 district-level sources (33 Apptegy, 29 Finalsite, 17 Smart Sites); second pass: 30 more (18 Edlio, 9 SchoolBlocks, 3 others)

First pass: no new adapter and no framework change; the three platforms' adapters read every one of these pages and files.
Each station names its LEAIDs (the ones the LEA directory lists with its website) and counts only those
districts' schools; robots.txt allows every URL polled (125 verdicts recorded with `snowlight stations robots
--update`). Live fetch of this part's 225 sources, 02:30-02:42 UTC: the 79 Texas sources read 11 populated, 68 empty,
0 errors. None of the 11 populated reads is a closing (Corpus Christi's mobile-app banner, Brownsville's three hiring
light boxes, Rio Grande City Grulla's, Aransas Pass', Rio Hondo's and Horizon Montessori's enrollment banners, Tuloso-Midway's board-meeting
notice, South Texas ISD's, Weslaco's, Driscoll's and Harmony's page pops), so the notice gate keeps them unproven
until a storm-day capture shows a closing. New real fixtures (live, 2026-09-28): Corpus Christi's and Brownsville's
homepages, Tuloso-Midway's alert file, South Texas ISD's and PSJA's page-pops answers, each pinned to its rows and
to its notice verdict.

Not built in the first pass (45 sites; reasons per record in `gaps.json`):

- **Edlio, 11 districts, 32.3 weight in Texas** (Edinburg CISD 10.9, Mission CISD 5.1, Los Fresnos CISD 3.7,
  Kingsville, Robstown, Rockport-Fulton, Orange Grove, Hidalgo ISD, Jim Hogg, Santa Gertrudis, Promesa): no alert
  element on any homepage then, so how an Edlio homepage shows a closing was unknown. **Built in the second pass**
  (below, "Edlio"), once run 36383349206 brought Mission CISD's homepage of the January 2025 snow day with its alert.
- **IDEA Public Schools** (125 schools, 61 in the gap counties, 13.4 of their weight): a WordPress site with no alert,
  announcement-bar or closings element in the homepage's markup.
- WordPress (Flour Bluff, West Oso, ResponsiveEd's Premier and Texas College Prep, Triumph, SST, Burnham Wood, El
  Paso Leadership), SchoolBlocks (Alice, Skidmore-Tynan, Industrial: built in the second pass, below), SchoolInSites (Freer, Odem-Edroy, Por Vida,
  La Gloria), Educational Networks (George West), Squarespace (Jubilee: an empty announcement-bar slot), GoDaddy
  and Wix one-page sites, three unidentified static sites, and the Texas Juvenile Justice Department's education
  page: no alert or closings element.
- Harmony Public Schools - West Texas: its LEA directory website is one school's page in Midland (Harmony Science
  Academy - Midland), which need not speak for the district's El Paso schools.
- The regional and state level, checked for a list that would reach the districts not built: the homepages of the
  Region One (Edinburg), Region 2 (Corpus Christi) and Region 3 (Victoria) education service centers and of the Texas
  Education Agency, read once at 02:59 UTC, have no link or element naming closings, weather, emergencies or
  alerts (four `gaps.json` records, verdict "no list").
- Not read: Vanguard Academy, Seashore Charter and Santa Maria ISD (the proxy's 502 after four attempts), Ben
  Bolt-Palito Blanco (TLS handshake timeout), El Paso Academy (the server's certificate did not verify; TLS
  verification is never disabled), Brillante Academy and La Feria ISD (no answer). Read again once in the second
  pass (08:49-08:58 UTC, each host on its own): the same answers (502 three times, the handshake timeout, the
  expired certificate, no answer twice within 8 minutes); not retried further.

| District (LEAIDs) | Schools (in the gap counties) | Weight of all its schools | Site, platform | Live read, 2026-09-28 | Verdict |
|---|---:|---:|---|---|---|
| IDEA Public Schools (4800211) | 125 (61) | 55.8 | ideapublicschools.org, WordPress | no alert element | not built |
| Premier High Schools (4800207) | 48 (10) | 26.7 | responsiveed.com, WordPress | no alert element | not built |
| Texas College Preparatory Academies (4800163) | 40 (1) | 24.7 | responsiveed.com, WordPress | no alert element | not built |
| Corpus Christi ISD (4815270) | 53 (53) | 24.4 | www.ccisd.us, Apptegy (Thrillshare CMS) | populated, 1 row(s) | built as `apptegy-corpus-christi-tx` |
| Victoria ISD (4844150) | 24 (24) | 14.2 | www.visd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-victoria-tx` |
| Brownsville ISD (4811680) | 51 (51) | 13.6 | www.bisd.us, Apptegy (Thrillshare CMS) | populated, 3 row(s) | built as `apptegy-brownsville-tx` |
| United ISD (4843650) | 51 (51) | 11.6 | www.uisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-united-tx` |
| Edinburg CISD (4818180) | 45 (45) | 10.9 | www.ecisd.us, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-edinburg-tx` (second pass) |
| Pharr-San Juan-Alamo ISD (4834860) | 42 (42) | 10.2 | www.psjaisd.us, Finalsite | empty, 0 row(s) | built as `finalsite-psja-tx` |
| School Of Science And Technology And School Of Science And Technology Discovery (4800258, 4801400) | 15 (1) | 8.8 | www.sstschools.org, WordPress | no alert element | not built |
| La Joya ISD (4826130) | 36 (36) | 8.7 | www.lajoyaisd.com, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-la-joya-tx` |
| Harlingen CISD (4822530) | 30 (30) | 8.0 | www.hcisd.org, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-harlingen-tx` |
| McAllen ISD (4829670) | 31 (31) | 7.5 | www.mcallenisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-mcallen-tx` |
| Laredo ISD (4826790) | 30 (30) | 6.8 | www.laredoisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-laredo-tx` |
| San Benito CISD (4838790) | 23 (23) | 6.1 | www.sbcisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-san-benito-tx` |
| Richard Milburn Alter High School (Killeen) (4800075) | 9 (1) | 5.6 | www.rmaschools.org, Finalsite | empty, 0 row(s) | built as `finalsite-rma-tx` |
| El Paso ISD (4818300) | 77 (77) | 5.4 | www.episd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-el-paso-tx` |
| Mission CISD (4831040) | 21 (21) | 5.1 | www.mcisd.net, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-mission-tx` (second pass) |
| Weslaco ISD (4844960) | 21 (21) | 5.1 | www.wisd.us, Finalsite | populated, 1 row(s) | built as `finalsite-weslaco-tx` |
| Donna ISD (4817390) | 21 (21) | 5.1 | www.donnaisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-donna-tx` |
| Jubilee Academies (4800179) | 10 (5) | 4.8 | www.jubileeacademies.org, Squarespace | no alert element | not built |
| Rio Grande City Grulla ISD (4837140) | 15 (15) | 4.1 | www.myrgcgisd.org, Apptegy (Thrillshare CMS) | populated, 1 row(s) | built as `apptegy-rio-grande-city-grulla-tx` |
| Raul Yzaguirre Schools For Success (4800022) | 8 (2) | 3.8 | www.ryss.org, Finalsite | empty, 0 row(s) | built as `finalsite-ryss-tx` |
| Los Fresnos CISD (4828290) | 14 (14) | 3.7 | www.lfcisd.net, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-los-fresnos-tx` (second pass) |
| Socorro ISD (4840710) | 52 (52) | 3.7 | www.sisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-socorro-tx` |
| Triumph Public High Schools-West Texas And Triumph Public High Schools-Rio Grande Valley And Triumph Public High Schools-Lubbock And Triumph Public High Schools Central Texas (4800106, 4800133, 4800142, 4800174) | 11 (8) | 3.7 | www.triumphpublicschools.org, WordPress | no alert element | not built |
| Ysleta ISD (4846680) | 47 (47) | 3.3 | www.yisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-ysleta-tx` |
| Flour Bluff ISD (4819380) | 7 (7) | 3.2 | flourbluffschools.net, WordPress | no alert element | not built |
| Gregory-Portland ISD (4821780) | 7 (7) | 3.2 | www.g-pisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-gregory-portland-tx` |
| Harmony Public Schools - South Texas (4800266) | 8 (5) | 3.2 | www.harmonytx.org/schools/south-texas, Finalsite | populated, 3 row(s) | built as `finalsite-harmony-south-texas-tx` |
| Sharyland ISD (4839930) | 13 (13) | 3.1 | www.sharylandisd.org, Finalsite | empty, 0 row(s) | built as `finalsite-sharyland-tx` |
| Calallen ISD (4812420) | 6 (6) | 2.8 | www.calallen.org, Finalsite | empty, 0 row(s) | built as `finalsite-calallen-tx` |
| Alice ISD (4807800) | 6 (6) | 2.8 | www.aliceisd.net/en-US, SchoolBlocks | empty alerts list (live, 10:45 UTC) | built as `schoolblocks-alice-tx` (second pass) |
| Lone Star School District (4801432) | 5 (1) | 2.8 | www.tjjd.texas.gov/state-programs/education-services, Texas Juvenile Justice Department (WordPress) | no alert element | not built |
| Roma ISD (4837740) | 10 (10) | 2.7 | www.romaisd.com, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-roma-tx` |
| Mercedes ISD (4830250) | 11 (11) | 2.7 | www.misdtx.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-mercedes-tx` |
| Beeville ISD (4809720) | 5 (5) | 2.7 | www.beevilleisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-beeville-tx` |
| Kingsville ISD (4825680) | 5 (5) | 2.4 | www.kingsvilleisd.com, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-kingsville-tx` (second pass) |
| Bloomington ISD (4810500) | 4 (4) | 2.4 | www.bisd-tx.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-bloomington-tx` |
| West Oso ISD (4845120) | 5 (5) | 2.3 | www.westosoisd.net, WordPress | no alert element | not built |
| Robstown ISD (4837440) | 5 (5) | 2.3 | www.robstownisd.org, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-robstown-tx` (second pass) |
| Tuloso-Midway ISD (4843350) | 5 (5) | 2.3 | www.tmisd.us, ParentSquare Smart Sites (Gabbart SchoolSites) | populated, 1 row(s) | built as `smartsites-tuloso-midway-tx` |
| Bishop CISD (4810260) | 5 (5) | 2.3 | www.bishopcisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-bishop-tx` |
| Sinton ISD (4840350) | 5 (5) | 2.3 | www.sintonisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-sinton-tx` |
| Valere Public Schools (4801414) | 4 (2) | 2.2 | www.promesapublicschools.org, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-valere-tx` (second pass) |
| Industrial ISD (4824150) | 4 (1) | 2.2 | www.industrialisd.org/en-US, SchoolBlocks | empty alerts list (live, 10:45 UTC) | built as `schoolblocks-industrial-tx` (second pass) |
| Harmony Public Schools - West Texas (4800272) | 7 (4) | 2.2 | hsamidland.harmonytx.org, Finalsite | no alert element | not built |
| George West ISD (4820550) | 4 (4) | 2.1 | www.gwisd.us, Educational Networks (SchoolSitePro) | no alert element | not built |
| Brooks County ISD (4811580) | 5 (5) | 2.0 | www.bcisd.us, Finalsite | empty, 0 row(s) | built as `finalsite-brooks-county-tx` |
| Rockport-Fulton ISD (4808550) | 4 (4) | 2.0 | www.rfisd.us, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-rockport-fulton-tx` (second pass) |
| Edcouch-Elsa ISD (4818060) | 8 (8) | 1.9 | www.eeisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-edcouch-elsa-tx` |
| Zapata County ISD (4846710) | 6 (6) | 1.9 | www.zcisd.org, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-zapata-county-tx` |
| La Feria ISD (4826040) | 7 (?) | 1.9 | www.laferiaisd.org, unknown (unreachable) | no answer | not read |
| London ISD (4827990) | 4 (4) | 1.8 | www.londonisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-london-tx` |
| Mathis ISD (4829400) | 4 (4) | 1.8 | www.mathisisd.org, Finalsite | empty, 0 row(s) | built as `finalsite-mathis-tx` |
| Aransas Pass ISD (4808580) | 4 (4) | 1.8 | www.apisd.org, Apptegy (Thrillshare CMS) | populated, 1 row(s) | built as `apptegy-aransas-pass-tx` |
| Ingleside ISD (4824180) | 4 (4) | 1.8 | www.inglesideisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-ingleside-tx` |
| Odem-Edroy ISD (4833360) | 4 (4) | 1.8 | www.oeisd.org, SchoolInSites | no alert element | not built |
| Orange Grove ISD (4833720) | 4 (4) | 1.8 | www.ogisd.net, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-orange-grove-tx` (second pass) |
| South Texas ISD (4837150) | 7 (7) | 1.7 | www.stisd.net, Finalsite | populated, 2 row(s) | built as `finalsite-south-texas-tx` |
| Skidmore-Tynan ISD (4840410) | 3 (3) | 1.6 | www.stbobcats.net/en-US, SchoolBlocks | empty alerts list (live, 10:45 UTC) | built as `schoolblocks-skidmore-tynan-tx` (second pass) |
| Driscoll ISD (4817550) | 3 (2) | 1.6 | www.driscollisd.us, Finalsite | populated, 1 row(s) | built as `finalsite-driscoll-tx` |
| Raymondville ISD (4836540) | 5 (5) | 1.5 | www.raymondvilleisd.org, Finalsite | empty, 0 row(s) | built as `finalsite-raymondville-tx` |
| Refugio ISD (4836780) | 3 (3) | 1.5 | www.refugioisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-refugio-tx` |
| Vanguard Academy (4800195) | 6 (6) | 1.5 | vanguardacademy.edu, unknown (unreachable) | no answer | not read |
| Hidalgo ISD (4823100) | 6 (6) | 1.5 | www.hidalgo-isd.org, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-hidalgo-tx` (second pass) |
| Valley View ISD (4843800) | 6 (6) | 1.5 | www.vviewisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-valley-view-tx` |
| Riviera ISD (4837320) | 3 (3) | 1.4 | www.rivieraisd.us, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-riviera-tx` |
| Banquete ISD (4809410) | 3 (3) | 1.4 | www.banqueteisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-banquete-tx` |
| Premont ISD (4835760) | 3 (3) | 1.4 | www.premontisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-premont-tx` |
| Port Aransas ISD (4835370) | 3 (3) | 1.4 | www.paisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-port-aransas-tx` |
| Taft ISD (4842060) | 3 (3) | 1.4 | www.taftisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-taft-tx` |
| Point Isabel ISD (4835250) | 5 (5) | 1.3 | www.pi-isd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-point-isabel-tx` |
| Horizon Montessori Public Schools (4800065) | 4 (3) | 1.2 | www.hmps.net, Apptegy (Thrillshare CMS) | populated, 1 row(s) | built as `apptegy-horizon-montessori-tx` |
| Rio Hondo ISD (4837170) | 4 (4) | 1.1 | www.rhisd.net, Apptegy (Thrillshare CMS) | populated, 1 row(s) | built as `apptegy-rio-hondo-tx` |
| Pettus ISD (4834770) | 2 (2) | 1.1 | www.pettusisd.org, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-pettus-tx` |
| Erath Excels Academy Inc (4800159) | 2 (1) | 1.1 | www.hustonacademy.com, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-huston-academy-tx` |
| Por Vida Academy (4800004) | 2 (1) | 1.1 | www.pvacharter.org, SchoolInSites | no alert element | not built |
| Three Rivers ISD (4842690) | 2 (2) | 1.0 | www.trisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-three-rivers-tx` |
| Freer ISD (4819820) | 3 (3) | 1.0 | www.freerisd.org, SchoolInSites | no alert element | not built |
| San Diego ISD (4838820) | 3 (3) | 1.0 | www.sdisd.us, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-san-diego-tx` |
| Woodsboro ISD (4846380) | 2 (2) | 1.0 | www.wisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-woodsboro-tx` |
| Austwell-Tivoli ISD (4809000) | 2 (2) | 1.0 | www.atisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-austwell-tivoli-tx` |
| Clint ISD (4814430) | 14 (14) | 1.0 | www.clintweb.net, Finalsite | empty, 0 row(s) | built as `finalsite-clint-tx` |
| Jim Hogg County ISD (4824750) | 3 (3) | 1.0 | www.jhcisdpk12.org, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-jim-hogg-county-tx` (second pass) |
| Progreso ISD (4835910) | 4 (4) | 1.0 | www.progresoedu.net, Wix | no alert element | not built |
| Ricardo ISD (4836930) | 2 (2) | 0.9 | www.ricardoisd.us, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-ricardo-tx` |
| Santa Gertrudis ISD (4839300) | 2 (2) | 0.9 | www.sgisd.net, Edlio | no alert up (live, 09:31 UTC) | built as `edlio-santa-gertrudis-tx` (second pass) |
| San Perlita ISD (4839000) | 3 (3) | 0.9 | www.spisd.org, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-san-perlita-tx` |
| Lyford CISD (4828620) | 3 (3) | 0.9 | www.lyfordcisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-lyford-tx` |
| Seashore Charter Schools (4800289) | 2 (2) | 0.9 | www.islandfoundation.esc2.net, unknown (unreachable) | no answer | not read |
| Agua Dulce ISD (4807530) | 2 (2) | 0.9 | www.adisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-agua-dulce-tx` |
| Ben Bolt-Palito Blanco ISD (4809870) | 2 (2) | 0.9 | bbpbschools.net, unknown (unreachable) | no answer | not read |
| Santa Rosa ISD (4839360) | 3 (3) | 0.8 | www.srtx.org, Finalsite | empty, 0 row(s) | built as `finalsite-santa-rosa-tx` |
| Santa Maria ISD (4839330) | 3 (3) | 0.8 | www2.smisd.net, unknown (unreachable) | no answer | not read |
| La Villa ISD (4826340) | 3 (3) | 0.7 | www.lavillaisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-la-villa-tx` |
| Monte Alto ISD (4831230) | 3 (3) | 0.7 | www.montealtoisd.org, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-monte-alto-tx` |
| Canutillo ISD (4812780) | 10 (10) | 0.7 | www.canutillo-isd.org, Finalsite | empty, 0 row(s) | built as `finalsite-canutillo-tx` |
| Webb CISD (4844810) | 3 (3) | 0.7 | www.webbcisd.org, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-webb-tx` |
| Benavides ISD (4899130) | 2 (2) | 0.7 | www.benavidesisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-benavides-tx` |
| Lasara ISD (4826850) | 2 (2) | 0.6 | www.lasaraisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-lasara-tx` |
| Culberson County-Allamoore ISD (4815990) | 1 (1) | 0.6 | www.ccaisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-culberson-allamoore-tx` |
| Nursery ISD (4833270) | 1 (1) | 0.6 | www.nurseryisd.org, Finalsite | empty, 0 row(s) | built as `finalsite-nursery-tx` |
| San Isidro ISD (4838910) | 2 (2) | 0.5 | www.sanisidroisd.org, unidentified CMS | no alert element | not built |
| Pawnee ISD (4834410) | 1 (1) | 0.5 | www.pawneeisd.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-pawnee-tx` |
| St Mary'S Academy Charter School (4800177) | 1 (1) | 0.5 | smacs.net, GoDaddy Website Builder | no alert element | not built |
| Dr M L Garza-Gonzalez Charter School (4800025) | 1 (1) | 0.5 | gcclr.org, GoDaddy Website Builder | no alert element | not built |
| Corpus Christi Montessori School (4800279) | 1 (1) | 0.5 | www.cc-montessori.com, Wix | no alert element | not built |
| La Gloria ISD (4826070) | 1 (1) | 0.5 | www.lagloriaisd.net, SchoolInSites | no alert element | not built |
| San Elizario ISD (4838850) | 5 (5) | 0.4 | www.seisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-san-elizario-tx` |
| Kenedy County Wide CSD (4825410) | 1 (1) | 0.3 | www.saritaschool.net, ParentSquare Smart Sites (Gabbart SchoolSites) | empty, 0 row(s) | built as `smartsites-kenedy-county-tx` |
| Ramirez CSD (4836420) | 1 (1) | 0.3 | www.ramirezcsd.net, Finalsite | empty, 0 row(s) | built as `finalsite-ramirez-tx` |
| Fabens ISD (4818900) | 4 (4) | 0.3 | www.fabensisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-fabens-tx` |
| Ft Hancock ISD (4820130) | 2 (2) | 0.3 | www.fhisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-ft-hancock-tx` |
| Burnham Wood Charter School District And Vista Del Futuro Charter School (4800037, 4801394) | 4 (4) | 0.3 | www.burnhamwood.org, WordPress | no alert element | not built |
| Excellence In Leadership Academy (4801433) | 1 (1) | 0.2 | www.elacharterschool.com, Finalsite | empty, 0 row(s) | built as `finalsite-ela-tx` |
| Brillante Academy (4801475) | 1 (1) | 0.2 | brillanteacademy.org, unknown (unreachable) | no answer | not read |
| El Paso Leadership Academy (4801439) | 3 (3) | 0.2 | epla.org, WordPress | no alert element | not built |
| Anthony ISD (4808430) | 3 (3) | 0.2 | www.anthonyisd.net, unidentified CMS | no alert element | not built |
| Tornillo ISD (4842990) | 3 (3) | 0.2 | www.tisd.us, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-tornillo-tx` |
| El Paso Academy (4800205) | 2 (2) | 0.1 | www.elpacademy.com, unknown (unreachable) | no answer | not read |
| Sierra Blanca ISD (4840200) | 1 (1) | 0.1 | www.sierrablancaisd.net, Finalsite | empty, 0 row(s) | built as `finalsite-sierra-blanca-tx` |
| Dell City ISD (4816650) | 1 (1) | 0.1 | www.dellcityisd.net, Apptegy (Thrillshare CMS) | empty, 0 row(s) | built as `apptegy-dell-city-tx` |
| La Fe Preparatory School (4800286) | 1 (1) | 0.1 | www.lafeprep.org, unidentified CMS | no alert element | not built |

### The stations and newspapers of South Texas' markets (round 3, 08:10-08:13 UTC)

A whole-county list would also reach the private schools (30.9 of Texas' uncovered weight) and the charter
networks that no district source counts, so the main newsrooms of the five markets (McAllen-Brownsville, Corpus
Christi, El Paso, Laredo, and Victoria) not owned by a group of parts 1 to 3b were read, first-hand, with the
scraper's User-Agent and robots.txt read first (ten `gaps.json` records; round 1 had only one line on three of
them). The Spanish-language Univision and Entravision stations and the radio groups there were not read this
round.

| Outlet (market) | What it serves | Verdict |
|---|---|---|
| KRGV Channel 5 (McAllen-Brownsville) | `https://www.krgv.com/` answers 301 to `http://…/home/` (not followed: the client never leaves HTTPS); `/home/` over HTTPS: no closings link, menu item or element; closures only as per-event articles ("School cancellations announced due to severe weather", read 11:02 UTC: UTRGV, South Texas ISD, IDEA ... on a March 28) | no list (articles) |
| KVIA ABC-7, News-Press & Gazette (El Paso) | WordPress; no closings link; `/closings/` and `/weather/closings/` 404; closures as per-event articles ("Friday weather delays of schools and agencies", 2025-01-09), as at its sister station KIFI | no list (articles) |
| KZTV Action 10 (Corpus Christi) | Brightspot; no closings link; `/closings` and `/weather/closings` 404 | no list |
| Crossroads Today, KAVU (Victoria) | BLOX; the homepage's alert carousel has a closings reader, but its file address is empty (`xmlhttp.open("GET", "", true)`) and nothing calls it; it only counts weather alerts | no list |
| Telemundo 40 McAllen, KTLM | the NBC-owned stations' WordPress platform: `/wp-json/nbc/v1/school-closings` answers `[]`; `/el-tiempo/cierres-de-escuelas/` redirects to `/el-tiempo/` | part 3a's platform: listed for s4c1, not built here |
| The Monitor, myrgv.com (McAllen) | HTTP 403 to the project's User-Agent | blocked; dropped (not retried) |
| Caller-Times (Corpus Christi), El Paso Times, Laredo Morning Times, Victoria Advocate | no link or element naming school closings | no list |

The group stations there are other parts' and were not re-read: KIII (TEGNA), KRIS (Scripps), KVEO and KGBT
(Nexstar; valleycentral.com answered 403 today), KTSM (Nexstar), KFOX and KDBC (Sinclair) are registered by parts 2
and 3b without an endpoint, and KGNS (Gray, part 1) serves Gray's closings file for Laredo, last written
2023-08-22 (stale). So in South Texas the district sites are the only readable closings sources. The archive's
listings of KRGV's, KVIA's and KZTV's closings addresses and of KTLM's closings route are in this round's next
request, to learn whether any of them kept a list in past winters.

### Florida's stations outside the groups (round 3, 08:50 UTC)

Florida is the largest uncovered state after Texas (600 closure-weighted schools), and two of its three largest
uncovered counties have no source at all: Lee (151 schools, 62.6) and St. Lucie (82, 49.9). Round 2 read the
state agencies and the county districts; this round read the stations there that no part owns, once each, the
same way (four `gaps.json` records): **WINK News** (Fort Myers; BLOX): no closings link or element; **WBBH NBC2 and
WZVN ABC7**: nbc-2.com and abc-7.com now redirect to gulfcoastnewsnow.com, Hearst Television's platform, whose site
settings read `"closings":{"enabled":false}` (part 1's `hearst-wbbh`); **WSVN 7** (Miami; WordPress) and **WPLG
Local 10** (Arc XP): no closings link or element. Lee's, Polk's and Marion's districts announce alerts only
through SharpSchool's POST-only alert service (round 2), which the live poller cannot send and the archive never
keeps; that needs a POST read in the framework (part 1's), noted as a handoff.

### Edlio: built in the second pass, from Mission's snow-day capture (09:10-09:45 UTC)

Round 2 and the first pass of round 3 left every Edlio district unbuilt (Natrona County 73.6 weighted schools,
Soda Springs 15.7, Livingston 13.8, Sublette #9 9.5, Weston #1, Hot Springs #1 and eleven South Texas districts
with 32.3): no homepage read so far, live or archived, had shown an alert, so an adapter would have been a guess.
Run 36383349206 brought one. **Mission CISD's homepage archived on 2025-01-21 at 11:10 UTC** (the January 2025
snow) carries Edlio's homepage alert, rendered on the server: `article#homepage_news_alert_modal` with the headline
"Weather Advisory", the summary "No School - Jan 21, 2025 / Delayed Start - Jan 22, 2025", a "Read full story" link
to the news story (`/apps/news/article/2020301`) and, in the script that opens the dialog, the story's id and the
alert's expiry (`2025/01/23 01:00:00`). A live read of all seventeen Edlio homepages at 09:31 UTC then found a
second one up: **Sublette #9's "School Picture Days"** (with a picture, linking to a page); the other sixteen have
no such element, and every other archived Edlio capture read (Natrona 2024-03-01 and 03-19, Soda Springs
2023-12-04, Weston #1 2024-03-02 and 04-19, Hot Springs #1 2023-12-11, Edinburg 2021-02-25 and 2025-01-21) has
none either (Edinburg's snow-day page of 2025-01-21 19:33 UTC announced "Delayed Start to Class Wednesday Jan. 22"
only as a news story in its carousel, not as the alert).

- New adapter `snowlight.sources.stations.edlio` (variant `edlio-homepage-alert`): one row per alert (headline as
  the name, summary as the status, the story id, expiry, link and, for a picture-only alert, the picture's alt
  text); an Edlio homepage (generator "Edlio CMS") without the element is an empty list; any other body is refused.
  Slicer `edlio-v1` for fixtures; real fixtures: Mission's snow-day capture (proves: "No School"), Sublette #9's live
  alert (does not prove: picture day), Natrona's and Edinburg's live homepages (empty). The notice gate treats the
  alert as a general district channel (`notices.GENERAL_CHANNEL_ADAPTERS`), reading the headline as the notice's
  title.
- New registry file `pipeline/config/sources/edlio.yaml`: 17 district-level sources (Natrona County, Sublette #9,
  Hot Springs #1 and Weston #1 in Wyoming, Soda Springs in Idaho, Livingston in Montana, and Edinburg, Mission, Los
  Fresnos, Kingsville, Robstown, Rockport-Fulton, Orange Grove, Hidalgo, Jim Hogg County, Santa Gertrudis and Valere
  (Promesa) in Texas; Washakie #2, WY, joined it below), each with the LEAIDs the NCES LEA directory lists with its website (Soda Springs: by the
  district the page names, since Idaho's LEA records list no website), robots.txt verdicts (allowed, or absent) and
  the terms read (Edinburg's footer "Terms of Use" page holds its title and no text).
- Correction: `gaps.json` had Weston #1's site under LEAID 5606090, which is Weston County School District #7
  (Upton, weston7.org); the LEA directory lists wcsd1.org for Weston #1, LEAID 5604830 (Newcastle, 4 schools), now
  recorded and registered.
- Live fetch of the 17, 09:39-09:41 UTC: 1 populated (Sublette #9's picture days), 16 empty, 0 errors. **Mission CISD
  is proven** by its snow-day alert under the notice gate (the first proven South Texas district). Run 36409494144
  (below) then brought **Hidalgo ISD's** homepage of 2025-01-20 12:33 UTC with the alert "Delayed Start at Hidalgo
  ISD" ("... the delayed start coming up this week; January 21-23, 2025"), which proves `edlio-hidalgo-tx`, and Los
  Fresnos CISD's of 2025-01-21 23:08 UTC with a headline-only alert over a picture, "Weather Notice - Monday,
  January, 20", which names no closing the gate reads (the status reader reads it as "other" too), so it does not
  prove. Real fixtures: `edlio/hidalgo-20250120.html` (proves) and `edlio/los-fresnos-20250121.html` (does not).

### SchoolBlocks: built in the second pass, from Grace's live alert (10:28-10:53 UTC)

SchoolBlocks (Browning 35.7 closure-weighted schools, Uinta #1 20.3, North Gem 11.8, Sublette #1 10.5, Salmon 10.2
and Alice, Industrial and Skidmore-Tynan in Texas) waited for the same reason as Edlio: the homepage carries the
district's organization record in its React Server Components payload (`self.__next_f.push`), and that record's
`alerts` list had been empty on every site read. Checking the Idaho districts no round had scouted (below) found
one filled, live: **Grace School District #148** (sd148.org, 10:28 and 10:45 UTC), `"alerts":[{"id":28295,
"message":"<p>Grace School District will be closed from September 11-October 4 for potato harvest break. We will
return to school on October 5. ...</p>","type":"overlay"}]`: the shape the site's notification component shows
(`id`, `message`, `type` overlay or banner).

- New adapter `snowlight.sources.stations.schoolblocks` (variant `schoolblocks-org-alerts`): joins the payload's
  string chunks, reads every `"alerts":` value, and gives one row per alert (the site's name from the page title,
  the message as text, the alert's id and type); an empty list is an empty list; a page without the payload or the
  list is refused. Slicer `schoolblocks-v1`; real fixtures: Grace's live page (populated), Browning's and Uinta
  #1's (empty). The gate reads the message only (the row is named by the district, as for Apptegy).
- New registry file `pipeline/config/sources/schoolblocks.yaml`: 9 district-level sources (Browning, with both its
  elementary and high school LEAIDs, which the LEA directory lists with bps.k12.mt.us, where `gaps.json` had had
  only the first; Uinta #1; Sublette #1; Salmon; North Gem; Grace; Alice; Skidmore-Tynan; Industrial). Terms: the
  sites' footers link only SchoolBlocks' privacy policy (read 10:46 UTC), which says nothing on reading the sites
  with software; robots.txt reads `Allow: /` on every site.
- Live reads of the nine (10:45 UTC, and the poller's fetch of 10:52-10:53 UTC): Grace populated (the harvest
  break), eight empty. **Grace's alert does not prove the source**: it is a planned break (the potato harvest
  break), and the notice gate treats a planned break as a calendar day, not a closing (the gate's list of planned
  breaks now names harvest breaks, with a test; before that change it would have passed on "will be closed").
  So no SchoolBlocks district is proven yet. The storm-day captures of Browning's, Uinta #1's, Sublette #1's and
  North Gem's homepages in run 36409494144 turned out to be of the sites' earlier CMSs (Uinta #1's was an Edlio
  site until 2025, whose alerts that winter were "No School - Feb. 17th, 2025 Presidents' Day" and "Spring Break
  April 1-5, 2024": planned days).

### Campus Suite: Hardin's closing before its Apptegy site (second pass, 12:25 UTC)

Run 36409494144's capture of Hardin's (MT) homepage on 2022-12-21 10:30 UTC is a Campus Suite page (the site
before its Apptegy one), and its alert banner widget (`div[data-cms-widget="widgets/AlertBanner/AlertBanner"]`,
items `div.cs-alert-banner__item`, dialogs `div.cs-alert-modal`) carries "School Closure Wednesday, Dec. 21st
2022: ... Due to the potential of extreme cold temperatures, snowfall and frigid wind chills that could easily
exceed -30 degrees below zero ...". As for the Blackboard (Schoolwires) pages before, the Apptegy and Smart Sites
adapters now read such an earlier Campus Suite homepage (new module `snowlight.sources.stations.campussuite`,
variant `campussuite-alert-banner`, slicer `campussuite-v1`; the empty widget, as on Hardin's page of 2023-03-27
and Hernando's (FL) of 2023 and 2024, is an empty list). The closing passes the gate, so **`apptegy-hardin-mt` is
proven**: Montana's first proven district besides Flathead County's board (fixtures `apptegy/hardin-20221221.html`,
`apptegy/hardin-20230327.html`).

### Idaho's and Wyoming's unscouted districts (second pass, 10:28-10:35 UTC)

Idaho is the second-largest uncovered state after Florida (304 closure-weighted schools after the Edlio sources).
Six Idaho districts of its uncovered counties had no `gaps.json` record: the LEA directory lists no website for
Idaho's districts, and round 2's search had not reached them. Their sites, found by a web search and each read
once (and two Wyoming districts' sites the LEA directory lists): **South Lemhi** (leadoreschool.org, Apptegy: built
as `apptegy-south-lemhi-id`), **Clark County 161** (Finalsite, page pops at `/fs/pages/2/page-pops`, empty: built as
`finalsite-clark-county-id`), **Grace** (SchoolBlocks, above), **Fremont County #38, WY** (arapahoeschools.com,
Smart Sites, `/api/popup-alerts` empty: built as `smartsites-fremont-38-wy`), **Washakie County #2, WY**
(wsh2.k12.wy.us, Edlio: built as `edlio-washakie-2-wy`); not built: **Jerome** (a Wix site) and **Shoshone** (a
WordPress site), no alert element; **Butte County** (butteschooldistrict.org) did not answer within 400 s, twice.

### Shares before and after round 3 (plain / closure-weighted)

Before: the critic's recount of 01:38 UTC. First pass: the same full fetch with this part's 225 sources replaced by
the fetch of 02:42 UTC (with the archive reads of 04:57 UTC). Second pass: the shared health of 09:56 UTC (other
parts' newer reads, so the national figures also move with their work) with this part's 225 earlier sources
replaced by the fetch of 08:39-09:00 UTC and the second pass's 30 new sources (18 Edlio, 9 SchoolBlocks, South
Lemhi, Clark County, Fremont #38) by the fetches of 09:39-09:41 and 10:52-10:53 UTC, and every downloaded archive capture
read again with the current registry (3,438 reads, including run 36383349206). This is the `coverage.json` and
`coverage.png` written to `pipeline/out/internal/stations/`.

| Scope | Covered before | First pass | Second pass | Proven before | First pass | Second pass |
|---|---|---|---|---|---|---|
| national | 95.2% / 98.1% | 95.9% / 98.3% | 96.9% / 98.6% | 79.9% / 89.4% | 79.9% / 89.4% | 79.9% / 89.4% |
| TX | 87.9% / 94.5% | 96.2% / 98.1% | 97.3% / 98.8% | 76.3% / 82.2% | 76.3% / 82.2% | 76.5% / 82.3% |
| FL | 81.5% / 79.0% | 81.5% / 79.0% | 81.5% / 79.0% | 20.7% / 19.0% | 20.7% / 19.0% | 20.7% / 19.0% |
| MT | 97.8% / 98.6% | 97.8% / 98.6% | 97.8% / 98.6% | 14.9% / 13.4% | 14.9% / 13.4% | 15.5% / 14.0% |
| ID | 81.5% / 78.6% | 81.5% / 78.6% | 83.3% / 82.5% | 59.8% / 53.2% | 59.8% / 53.2% | 59.8% / 53.2% |
| WY | 81.0% / 79.5% | 81.0% / 79.5% | 89.7% / 88.6% | 44.7% / 49.9% | 44.7% / 49.9% | 44.7% / 49.9% |
| LA | 86.4% / 86.4% | 86.4% / 86.4% | 86.4% / 86.4% | 77.5% / 78.4% | 77.5% / 78.4% | 77.5% / 78.4% |
| CA | 91.4% / 94.5% | 91.4% / 94.5% | 91.4% / 94.5% | 16.7% / 69.8% | 16.7% / 69.8% | 16.7% / 69.8% |

Texas' counties (schools, schools covered, uncovered closure-weighted schools, district sources; before → first
pass → second pass):

| County | Schools | Covered | Uncovered weight | District sources |
|---|---:|---:|---:|---:|
| Hidalgo County (48215) | 352 | 0 → 203 → 275 | 85.2 → 36.1 → 18.6 | 14 → 17 |
| Nueces County (48355) | 128 | 0 → 84 → 90 | 59.0 → 20.3 → 17.5 | 10 → 12 |
| Cameron County (48061) | 185 | 0 → 123 → 138 | 49.2 → 16.5 → 12.5 | 10 → 12 |
| Victoria County (48469) | 40 | 0 → 29 → 30 | 23.6 → 6.5 → 5.9 | 3 → 4 |
| Webb County (48479) | 97 | 0 → 87 → 87 | 22.0 → 2.3 → 2.3 | 4 → 4 |
| El Paso County (48141) | 277 | 0 → 212 → 212 | 19.5 → 4.6 → 4.6 | 8 → 8 |
| San Patricio County (48409) | 33 | 0 → 28 → 28 | 15.2 → 2.3 → 2.3 | 7 → 7 |
| Jim Wells County (48249) | 18 | 0 → 3 → 13 | 8.2 → 6.9 → 2.3 | 1 → 3 |
| Starr County (48427) | 30 | 0 → 25 → 25 | 8.2 → 1.4 → 1.4 | 2 → 2 |
| Bee County (48025) | 14 | 0 → 8 → 11 | 7.4 → 3.2 → 1.6 | 3 → 4 |
| Kleberg County (48273) | 15 | 0 → 5 → 12 | 7.1 → 4.7 → 1.4 | 2 → 4 |
| Aransas County (48007) | 5 | 0 → 0 → 4 | 2.5 → 2.5 → 0.5 | 0 → 1 |
| Jim Hogg County (48247) | 3 | 0 → 0 → 3 | 1.0 → 1.0 → 0.0 | 0 → 1 |

Texas' uncovered weight falls from 327.5 to 111.5 in the first pass and 74.3 in the second; what is
left is IDEA's schools (no alert element), the private schools (no district source counts them) and the districts
without a readable site (see the table). Wyoming's falls from 195.1 to 109.0 (Natrona County, Uinta #1, Sublette
#1, Fremont #38, Washakie #2) and Idaho's from 319.6 to 261.2 (Soda Springs, Salmon, North Gem, Grace, South Lemhi,
Clark County). The ranking after the second pass (uncovered, closure-weighted): FL 600 · ID 261 · AL 132 · CA 112 · WY 109 · MO 101 · LA 97 · MS 76 · TX 74 (total 1,681).
Not proven (uncovered, or covered only by lists never seen populated): MT 2,880 · FL 2,312 · UT 1,873 · TX 1,052 · PA 736 · ID 700 · CA 610 · WY 478 (total 12,538);
Texas gains Mission CISD's 21 schools and Hidalgo ISD's 6, Montana Hardin's 6 (a Campus Suite capture, below).

### The notice gate reads Spanish

South Texas' districts (like Miami-Dade's) post their notices in English and Spanish, sometimes only in Spanish. The
gate (`notices.announces_closing`) now also reads Spanish weather words (huracán, tormenta invernal, mal tiempo,
helada, nieve, frío extremo, inundación, apagón), closings (escuelas cerradas, clases canceladas or suspendidas,
salida temprana, horario retrasado, inicio tardío) and planned days (vacaciones, día festivo, Acción de Gracias,
desarrollo profesional), with tests (synthetic sentences, and the Spanish half of Rio Grande City Grulla's live enrollment banner,
which does not prove).

### Wayback (round 3)

- Run 36361209861 (round 2's last request, commit f4fa734): its snapshots were read this round (artifact
  `snapshots-36361209861`, uploaded 04:50 UTC): 122 asked, 109 downloaded (108 distinct captures), 11 not attempted
  (the 280-minute budget), 2 answered 403. Read with the adapters: 9 populated, 48 empty, 50 refused. Fifteen of the
  refused are the archive's own captures of Apptegy's bot challenge page ("Client Challenge", 3,101 bytes) in place of
  the district's page, from 2025 on (Hillsborough, Duval, Alachua, Corvallis, Frenchtown, Marsh Valley, Victor,
  Geraldine, Hays-Lodge Pole, Townsend, Lander, Sunburst): the archive cannot prove those sites for 2025-26. The rest
  are other CMSs from before a district moved (Blackboard pages without an announcements region, SharpSchool,
  Edlio, Finalsite, unidentified pages), and Okaloosa's 2023-09-24 capture, cut at 1 MiB. One capture proves its
  source under the notice gate: **Leon County's Blackboard homepage of 2024-08-05 11:41 UTC**, "All LCS offices and
  schools will be closed, Monday, August 5th 2024 Due to TS Debby" (`smartsites-leon-fl`, now proven; fixture
  `smartsites/leon-home-20240805.html`). The other populated captures are not closings (Hamilton's phone-carrier
  notice, now a fixture pinned as not proving; Superior's trustee election; Three Forks' T-shirt order; Sweetwater
  #2's registration; Putnam's and Fremont #6's hiring), so no Montana, Wyoming or Idaho district became proven, and
  Montana's proven share stays 14.9% (13.4% weighted).
- Run 36383349206 (commit a490abb, pushed 05:46 UTC; the South Texas request): its snapshots were read this round
  (artifact `snapshots-36383349206`, uploaded 09:20 UTC, SHA-256 `9b85fc9d…`): 93 asked (the Apptegy homepages of
  Corpus Christi, Victoria, Brownsville, McAllen, Laredo, El Paso and nine smaller districts, the Smart Sites and
  Finalsite alert files and homepages of United, La Joya, Harlingen, PSJA, San Benito and Weslaco, and the Edlio
  homepages of Edinburg, Mission and Los Fresnos, on the February 2021 and January 2024 freezes, Hurricanes Hanna
  and Beryl, Tropical Storm Harold, the January 2025 snow, the January 2026 cold and older storms). 66 downloaded;
  27 not (19 TLS handshake timeouts between the runner and the archive, 7 answered 404, no capture of those alert
  files near the day, and 1 answered 500). Read with the adapters: 3 populated, 18 empty, 42 refused, 3 not then
  registered (the Edlio homepages). None of the three populated reads is a closing (Corpus Christi's mobile-app banner of 2026-01-29,
  Victoria's survey banner of 2025-01-19, El Paso's COVID page link of 2022-02-03). The refused are the archive's
  captures of Apptegy's bot challenge (2,964 or 3,101 bytes) from 2025 on, and the districts' pages from before
  they moved to their present CMS (Blackboard, Finalsite, SharpSchool, Edlio). Those older homepages do show the
  storms, but as news stories, not in an alert channel the adapters read: Brownsville's Finalsite page of
  2024-01-16 ("Inclement Weather Update for Tuesday, January 16, 2024", "UPDATE - Inclement Weather – Late Start
  for Wednesday"), El Paso's Blackboard page of 2022-02-03 ("EPISD schools to close due to winter weather ...
  canceled on Thursday, Feb. 3"), Socorro's of 2022-02-03 ("Socorro ISD delayed start Feb. 4 due to inclement
  weather"), PSJA's Finalsite homepage of 2025-01-21 ("Weather Update: Classes Cancelled for Tuesday, January 21")
  and Edinburg's Edlio carousel of 2025-01-21 ("Delayed Start to Class Wednesday Jan. 22"). They show these
  districts announce weather closings on their homepages, but they do not prove the channels built (news lists are
  not closings lists, and are not read). The one alert-channel closing: **Mission CISD's Edlio homepage alert of
  2025-01-21** ("Weather Advisory: No School - Jan 21, 2025"), which led to the Edlio adapter (above) and proves
  `edlio-mission-tx`. Its listings (artifact `cdx-36383349206`, 19 of 25 answered): the smaller sites' homepages
  have 85 to 562 daily captures since mid-2020, 16 of them on the storm days; the Finalsite page-pops and Smart
  Sites alert files at most one capture each, or none.
- Run 36409494144 (commit dc727fa, pushed 10:24 UTC, after run 36383349206 ended): 87 captures (the Edlio
  districts' homepages on their storm days, now that the adapter reads the alert: Natrona, Sublette #9, Soda
  Springs, Livingston, Mission, Edinburg, Los Fresnos, Kingsville, Robstown, Rockport-Fulton and five smaller South
  Texas districts; the 35 Montana and Wyoming Apptegy captures on NWS winter-warning school days picked from run
  36361209861's listings; the SchoolBlocks and IDEA homepages on storm days; the 16 South Texas storm-day captures
  of the last listings) and 11 listings (the Edlio and SchoolBlocks homepages; KRGV's, KVIA's, KZTV's and Crossroads
  Today's addresses naming closings; Telemundo 40's closings route). Recorded in `archive-wanted-s4d.json`. Its
  snapshots were read at 12:10 UTC (artifact `snapshots-36409494144`, uploaded 11:35 UTC, SHA-256 `7fadcb50…`): 87
  asked, 85 downloaded (2 TLS handshake timeouts). Read with the adapters (and the new Campus Suite reader): 7
  populated, 47 empty, 29 refused, 2 IDEA homepages (no station). The populated reads that pass the gate: **Hidalgo
  ISD's "Delayed Start" alert (2025-01-20)** and **Hardin's "School Closure ... extreme cold" banner
  (2022-12-21)**. Those that do not: Los Fresnos' headline-only "Weather Notice", Big Sky's (MT) notice of an EMS
  training exercise at the school (2023-03-24), Frenchtown's (MT) "Winter Break Early out" (2022-12-23, planned) and
  Three Forks' (MT) T-shirt and adult-education notices. No Montana or Wyoming Apptegy capture on a winter-warning
  day held a closing; 19 of the refused are the Apptegy districts' earlier CMSs (Joomla, SharpSchool,
  unidentified), 3 Laramie #1's homepage read as a Smart Sites alert file, 2 Edlio districts' pages of other CMSs,
  and 5 the SchoolBlocks districts' earlier sites (Edlio at Uinta #1, whose alerts were
  planned days). IDEA's homepages of 2024-01-16 and 2025-01-21 show no alert element. Natrona's (2025-03-07) and
  Robstown's (2025-01-21) Edlio homepages had no alert up, though Robstown's news list read "Robstown ISD Schools
  Closed Tuesday Due to Inclement Weather" and Mission's and Edinburg's of 2026-01-26 "Weather Alert" and "Delayed
  Start to Class on Jan 26, 2026" as news stories (not the alert channel, not read). Its listings were still
  running when this round ended.

### Handoffs (round 3)

- **Part 3a (s4c1, the NBC-owned platform)**: Telemundo 40 McAllen (KTLM, telemundo40.com) answers the NBC
  platform's closings route, `https://www.telemundo40.com/wp-json/nbc/v1/school-closings`, with `[]`; it would cover
  the McAllen-Brownsville market's counties (Hidalgo, Cameron, Willacy, Starr) whole, private schools included. Not
  registered here (the nbc-owned adapter reads it as it is); the archive's listing of the route is in this part's
  next request, to learn whether the station ever filled it.
- **Part 1 (s4a, the framework)**: SharpSchool district sites (Florida's Lee, Polk and Marion, 159.5 closure-weighted
  schools, none covered) serve their alerts only to a POST (`/WebServices/UnifiedPublishing/UnifiedPublishingService.asmx/GetActiveAlerts`,
  body `{"returnDummyAlerts":false}`); the live poller sends only GET, so these stay unbuilt until the poller can
  send that one POST. The archive keeps no POST answers, so they could only ever be proven live.
- **Part 1 (s4a, Hearst)**: WBBH NBC2 and WZVN ABC7 now live at gulfcoastnewsnow.com, whose site settings read
  `"closings":{"enabled":false}` (no list; `hearst-wbbh`'s registry note may want it).

## Round 2 (2026-09-27, 14:45-18:40 UTC): district-level sources

The critic's finding on round 1: Montana's gain rested on the Cowles ticker, never
seen with a row, and district-level sources were not built, so Florida, Louisiana,
Idaho and Wyoming gained nothing. Round 2 adds district-level coverage to the
framework and reads the state list and the district sites that reach those gaps.

### The gap, recomputed at the start of round 2

From `coverage.json` of 14:31 UTC (health of 12:47 UTC; round 1's eight sources
included) and, for the proven share, its `proven` part:

| Measure | Total | Top states |
|---|---:|---|
| Uncovered weight (no working source) | 3,856 | FL 1,365 · ID 653 · WY 346 · TX 327 · LA 269 · CA 216 · AL 132 · MO 101 |
| Unproven weight (no source seen populated) | 22,091 | MN 4,657 · MT 2,900 · FL 2,744 · UT 1,873 · TX 1,610 · PA 1,334 · CA 852 · OR 824 · ID 700 · WY 669 · NY 623 · LA 505 |

Worked down it within this part's states, in the critic's order: Louisiana's state
list, Florida's districts, then Montana's, Idaho's and Wyoming's largest districts.
(Minnesota, Utah, Pennsylvania and Oregon are other parts' stations.)

### The framework change (small, additive)

- `Station.leaids` (registry.py): an optional list of NCES district IDs (LEAIDs,
  seven digits), with a new county basis `district`: a source that names LEAIDs
  covers exactly those districts' schools; its `counties` are the counties those
  schools stand in (from the NCES directory), and the two go together (validated).
  Empty `leaids` are not written to the YAML, so no other part's file changes.
- `coverage.district_cover()` (coverage.py): counts the directory's schools whose
  `district_id` a working district-level source names; `measure()` adds them to a
  county that no whole-county source covers (never the whole county), per state
  and nationally, plain and closure-weighted (each school's own weight via
  `Weights.by_school`). A district-level source is never a market's source in the
  DMA table. `coverage.json` gains per county `districts`, `districts_not_working`
  and `covered`, per district station `leaids`, and a `districts` summary
  (`schools_added`, `weighted_added`); `coverage.png` draws counties partly
  covered by district sources in dim gold. The proven share (proof.py, another
  part's) calls `measure()`, so it counts district sources the same way.
- `stations coverage` reads the directory's `district_id` and `index` too (only
  when the file has them).
- The proof gate (`notices.py`, its own module; the critic's round-2 finding): `gate_proofs` drops a proof of a
  district alert channel (Apptegy, Finalsite, Smart Sites, Pasco, Miami-Dade) whose rows announce no closing,
  delay, early dismissal, remote day, cancelled classes, weather or emergency, and a proof of a status board
  (Flathead County's page, the Shasta and Trinity sheets, GOHSEP's parish layer) whose rows are all "Open" (see
  "Shares before and after" below). It is called from `stations coverage` between `proof.gather` and
  `proof.add_proven` (two lines in the proof block of `cli.py`, which belongs to the proof share's part) and
  records `district_notice_gate` in `coverage.json` (kept proofs with the row that proved each, dropped ones with
  the reason) and, for each unproven gated station, `checked.notice_gate`. Tests: `test_gaps_notices.py` (every
  populated fixture of a gated source is pinned to its verdict).
- Tests: `pipeline/tests/stations/test_gaps_districts.py` (15), and one branch in
  `test_stations_registry.py` for the `district` basis.

The change touches files other parts are also editing (uncommitted). It is kept
as exact edits applied the same way to HEAD and to the working tree, so it can be
committed alone: the patch against HEAD is the four files' part-4 hunks only.

### Built in round 2 (54 district-level sources, four platforms)

Each is a district-level source: it counts only its own districts' schools (its
`leaids`), never a whole county. Schools and closure-weighted schools are the
coverage measure's own counts (`coverage.json`, stations table).

| Source | Platform | State | Schools / weighted | Live 2026-09-27 | Proof |
|---|---|---|---:|---|---|
| `gohsep-parish-schools` | gohsep | LA | 1137 / 515.9 | populated | live 2026-09-27, 640 row(s): 11 Closed, dated 2026-06-17/18 and (Cameron) 2026-09-01, kept on the standing layer |
| `finalsite-palm-beach-fl` | finalsite | FL | 234 / 107.5 | empty | unproven |
| `finalsite-broward-fl` | finalsite | FL | 319 / 100.7 | populated (a referendum notice) | unproven (no closing notice seen) |
| `finalsite-great-falls-mt` | finalsite | MT | 19 / 98.7 | populated (a settlement notice) | unproven (no closing notice seen) |
| `finalsite-billings-mt` | finalsite | MT | 34 / 77.8 | empty | unproven |
| `finalsite-pinellas-fl` | finalsite | FL | 153 / 76.4 | empty | unproven |
| `finalsite-missoula-mt` | finalsite | MT | 19 / 69.6 | empty | unproven |
| `finalsite-bozeman-mt` | finalsite | MT | 13 / 56.8 | empty | unproven |
| `finalsite-volusia-fl` | finalsite | FL | 85 / 47.1 | empty | unproven |
| `finalsite-pocatello-id` | finalsite | ID | 24 / 46.9 | empty | unproven |
| `finalsite-teton-wy` | finalsite | WY | 10 / 42.6 | empty | unproven |
| `finalsite-escambia-fl` | finalsite | FL | 67 / 33.1 | empty | unproven |
| `finalsite-blaine-id` | finalsite | ID | 8 / 32.7 | empty | unproven |
| `finalsite-east-helena-mt` | finalsite | MT | 7 / 30.0 | empty | unproven |
| `finalsite-kalispell-mt` | finalsite | MT | 7 / 25.9 | empty | unproven |
| `finalsite-collier-fl` | finalsite | FL | 74 / 20.8 | empty | unproven |
| `apptegy-hillsborough-fl` | apptegy | FL | 289 / 144.1 | empty | unproven |
| `apptegy-duval-fl` | apptegy | FL | 201 / 118.7 | empty | unproven |
| `apptegy-brevard-fl` | apptegy | FL | 108 / 73.0 | empty | archived 2024-10-11: Milton closure |
| `apptegy-manatee-fl` | apptegy | FL | 80 / 41.1 | empty | archived 2024-09-24, 2024-10-09: Helene, Milton closures |
| `apptegy-lake-fl` | apptegy | FL | 60 / 36.5 | populated (a superintendent notice) | archived 2024-10-10: Milton closure |
| `apptegy-clay-fl` | apptegy | FL | 55 / 31.6 | empty | unproven |
| `apptegy-alachua-fl` | apptegy | FL | 61 / 29.8 | empty | unproven |
| `apptegy-fremont-id` | apptegy | ID | 8 / 28.0 | empty | unproven |
| `apptegy-sarasota-fl` | apptegy | FL | 59 / 27.4 | empty | archived 2024-09-24: Helene closure |
| `apptegy-cassia-id` | apptegy | ID | 17 / 27.0 | empty | unproven |
| `apptegy-okaloosa-fl` | apptegy | FL | 49 / 24.8 | empty | unproven |
| `apptegy-bay-fl` | apptegy | FL | 49 / 23.8 | empty | unproven |
| `apptegy-madison-id` | apptegy | ID | 12 / 21.6 | empty | unproven |
| `apptegy-martin-fl` | apptegy | FL | 33 / 18.6 | empty | archived 2022-09-28, 2024-10-09: Ian, Milton closures |
| `apptegy-twin-falls-id` | apptegy | ID | 18 / 18.3 | empty | unproven |
| `apptegy-indian-river-fl` | apptegy | FL | 28 / 17.0 | empty | unproven |
| `apptegy-minidoka-id` | apptegy | ID | 10 / 14.4 | empty | unproven |
| `apptegy-johnson1-wy` | apptegy | WY | 6 / 13.8 | empty | unproven |
| `apptegy-nassau-fl` | apptegy | FL | 22 / 13.4 | empty | unproven |
| `apptegy-fremont25-wy` | apptegy | WY | 7 / 12.2 | empty | unproven |
| `apptegy-putnam-fl` | apptegy | FL | 18 / 10.1 | empty | unproven |
| `apptegy-converse2-wy` | apptegy | WY | 3 / 9.6 | empty | unproven |
| `apptegy-american-falls-id` | apptegy | ID | 5 / 9.1 | empty | unproven |
| `apptegy-walton-fl` | apptegy | FL | 19 / 8.5 | empty | unproven |
| `apptegy-monroe-fl` | apptegy | FL | 25 / 7.1 | empty | archived 2024-10-07: Milton notice |
| `smartsites-orange-fl` | smartsites | FL | 273 / 166.1 | empty | unproven |
| `smartsites-osceola-fl` | smartsites | FL | 85 / 51.7 | empty | archived 2022-09-28: Ian closure |
| `smartsites-bonneville-id` | smartsites | ID | 26 / 48.1 | empty | unproven |
| `smartsites-seminole-fl` | smartsites | FL | 74 / 45.0 | empty | unproven |
| `smartsites-leon-fl` | smartsites | FL | 54 / 34.3 | empty | unproven |
| `smartsites-belgrade-mt` | smartsites | MT | 5 / 21.9 | populated (a records notice) | unproven (no closing notice seen) |
| `smartsites-hernando-fl` | smartsites | FL | 32 / 17.5 | empty | unproven |
| `smartsites-citrus-fl` | smartsites | FL | 26 / 15.4 | empty | unproven |
| `smartsites-shelley-id` | smartsites | ID | 7 / 10.7 | empty | unproven |
| `smartsites-charlotte-fl` | smartsites | FL | 24 / 10.2 | empty | unproven |
| `smartsites-jackson-fl` | smartsites | FL | 20 / 8.3 | empty | unproven |
| `smartsites-flagler-fl` | smartsites | FL | 13 / 7.7 | empty | unproven |
| `smartsites-sumter-fl` | smartsites | FL | 14 / 7.6 | empty | unproven |

- **Louisiana GOHSEP** (`gohsep`): the standing ArcGIS layer
  `Parish_School_Closures_Public_View_Layer` (item e9ca4b01…, owner
  Andy.Venuto_GOHSEP, created 2025-05-19), drawn by the "Parish Emergency School
  Closures Dashboard" (item 183276b0…, modified 2026-09-01, "the school system
  closures for Incident 26-020 - Tropical Storm Edouard"). Read through its query
  endpoint (JSON): 640 features, the 64 parishes over ten date groups. Each GEOID was
  matched to the one directory district in that parish named "<parish> Parish"
  (64 LEAIDs, 1,137 schools); city systems (Monroe, Bogalusa, Baker, Zachary,
  Central), charter districts and private schools are not counted. Before May 2025
  GOHSEP made one layer per incident (24-004 to 25-007, found in its ArcGIS
  organization); those are other lists, not proof of this one.
- **Apptegy** (`apptegy`, 25 sites: 16 Florida county districts; Twin Falls,
  Cassia, Madison, Fremont, Minidoka and American Falls in Idaho; Fremont #25,
  Johnson #1 and Converse #2 in Wyoming): the
  homepage is rendered with the site's state (`__NUXT_DATA__`, devalue's flat form);
  the adapter unflattens it and reads the banners the site's own code shows
  (published banners when the separate-banner flag is on, else the single banner if
  enabled). Drafts and archived banners are never rows, though they show the
  channel is used for weather: Martin's "HURRICANE MILTON UPDATE: All
  MCSD-operated schools and offices will be closed Wednesday, O[ctober 9]",
  Nassau's "School is closed due to Ice!", Sarasota's "MONDAY, AUGUST 5 - SCHOOLS
  & DISTRICT OFFICES CLOSED" (Debby), Walton's closure citing the National Weather
  Service, Lake's reopening after Milton.
- **ParentSquare Smart Sites** (`smartsites`, 13 sites: Orange, Osceola, Seminole,
  Leon, Hernando, Citrus, Charlotte, Jackson, Flagler, Sumter; Bonneville D93 in
  Idaho Falls and Shelley in Idaho; Belgrade, MT): each page's `PopUpAlertsComponent` script reads the
  site's `/api/popup-alerts` (JSON, schema-checked by the script); the poller reads
  that file. ParentSquare's terms forbid copying text from its public pages without
  consent; recorded, with the owner's decision of 2026-09-25.
- **Finalsite** (`finalsite`, 15 sites: Billings, Great Falls, Missoula, Bozeman,
  Kalispell, East Helena; Pocatello-Chubbuck, Blaine County; Teton County WY;
  Broward, Palm Beach, Pinellas, Volusia, Escambia, Collier): the page's page-pops
  module asks `/fs/pages/<body data-pageid>/page-pops` for its alerts (an HTML
  fragment of `article.fsPagePop`, or an empty body when there is none). Since round
  5 the poller reads the homepage and follows its own `data-pageid` to that fragment,
  held to the address a browser check saw the page ask for (the address alone answers
  an empty 200 for any ID; see round 5).

The rows of these sources name no school (a banner, an alert or a pop is the
district's own): `raw_name` is the banner's organization name (Apptegy) or the
alert's title (Smart Sites, Finalsite), and the matcher attributes them to the
source's `leaids`.

### Scouted and not built (round 2)

| District | State | Schools / weight (county weights) | Site | Why not |
|---|---|---:|---|---|
| Miami-Dade County Public Schools | FL | 526 / 118.5 | Angular app; alerts at `mainapi.dadeschools.net/api/v1/alerts/` (public, read 2026-09-27: 3 items, none visible, the newest "Hurricane Elsa" of 2021) | built in the second pass as `dadeschools-miami-dade-fl`: the capture of 2024-10-09 holds a visible "Hurricane Milton" closure |
| Polk, Lee, Marion | FL | 161, 118, 61 | SharpSchool: `unifiedPublishingAlertComponent`, a React portlet loading its alerts after the page | second pass: its endpoint is `POST /WebServices/UnifiedPublishing/UnifiedPublishingService.asmx/GetActiveAlerts` (body `{"returnDummyAlerts":false}`; `{"d":[]}` on all three today; a GET answers 500). Not built: the poller reads GET URLs only, and the Wayback Machine keeps no POST answers, so no capture could ever prove it |
| Pasco County Schools | FL | 106 / 59.2 | custom site with a server-rendered emergency banner slot (`div.pcs_emergency_banner_red` / `_yellow`, "storm-icon"), empty today | built in the second pass as `pasco-county-fl`: its captures of Helene and Milton hold the closures |
| St. Johns, St. Lucie | FL | 54, 56 | WordPress | no alert or closings element on the homepage |
| Santa Rosa | FL | 38 | santarosa.k12.fl.us | proxy 502 (CONNECT refused), twice |
| Helena Public Schools | MT | 20 / 85.7 | helenaschools.org | www.helenaschools.org: TLS certificate expired (CERTIFICATE_VERIFY_FAILED); verification is never disabled. Second pass: the apex helenaschools.org answers, a WordPress page with no alert element |
| Butte School District 1 | MT | 8 / 37.7 | bsd1.org | server omits its intermediate certificate (CERTIFICATE_VERIFY_FAILED) |
| Browning Public Schools | MT | 7 / 35.7 | SchoolBlocks (Next.js) | no alert element found |
| ~~Idaho Falls District 91~~ | ID | 22 / 40.7 | ~~d91.net, Weebly~~ | wrong site: d91.net is Milne-Kelvin Grove District 91 (Illinois). Corrected in the second pass: the district's site is ifschools.org (Finalsite), built as `finalsite-idaho-falls-id` |
| Blackfoot District 55 | ID | 11 / 16.8 | Wix | no alert element |
| Teton School District 401 | ID | 7 / 30.6 | a Smore newsletter page | no alerts |
| Natrona County School District #1 | WY | 27 / 73.6 | Edlio | no alert element today; how Edlio shows alerts waits for a storm-day capture |
| Lincoln County School District #2 | WY | 9 / 28.5 | WordPress | no alert element |
| Florida DOE | FL | statewide | fldoe.org | 403 to the project's User-Agent (Akamai), again on 2026-09-27 15:49 UTC; not worked around |

### Second pass (19:09 UTC on, after a restart): 84 more district sources, older page forms, and two corrections

The restart left round 2's work in the tree and its archive request (commit 6ceebb5, run 36341776194) running.
While it ran, this pass went down every unbuilt district of the gap counties instead of the largest only:

- **How the sites were found.** For Montana and Wyoming, the website the NCES CCD 2024-25 LEA directory
  (`https://nces.ed.gov/ccd/Data/zip/ccd_lea_029_2425_w_1a_073025.zip`, SHA-256 `2745169e4bc7cd53…`, read
  2026-09-27) lists for each district with schools in a county no proven source covers (Montana: every district of
  8.5 or more closure-weighted schools outside Flathead County; Wyoming: every one of 4.5 or more), and the same
  for Florida's 30 county districts not scouted in the first pass. Each homepage was read once through the
  repository's `PoliteClient` (robots.txt first, verdict recorded), its platform identified, and its title checked
  against the district. A source's `leaids` are the LEAIDs the directory lists with that website (a Montana town's
  elementary and high school districts share one: Hardin Elem and Hardin H S); Idaho's LEA records list no website,
  so Idaho's district sites were found by a web search and matched by name to their sites' titles (Idaho Falls
  District 91, Marsh Valley #21, West Jefferson #253, Sugar-Salem #322, Challis #181).
- **Built: 82 district-level sources** on the three platforms already built (no new adapter): 48 in Montana, 15 in
  Florida, 14 in Wyoming and 5 in Idaho; 496 schools, 1,087.2 closure-weighted. Seven were populated when read:
  Lewistown's, Hellgate's and Havre's page pops (Hellgate's "September 28, 2026- Staff Development- NO SCHOOL FOR
  STUDENTS"), St. Ignatius', Sweetwater #2's and Fremont #6's Apptegy banners, and Hendry County's three page pops;
  their live bodies are fixtures. None of these rows announces a closing, so none proves its source (see the
  district proof gate below).
- **Corrections to the first pass.** (1) Idaho Falls District 91: the first pass read `https://www.d91.net/` and
  recorded "Weebly, no alert"; that site is Milne-Kelvin Grove District 91 in Illinois (its title). Idaho Falls
  District 91's site is `https://www.ifschools.org/` (`https://www.d91.k12.id.us/` redirects there), a Finalsite site,
  now built as `finalsite-idaho-falls-id`; the d91.net listing of run 36329076920 is not this district's. (2)
  `https://www.wcsd1.org/` was recorded and requested from the archive as Washakie County School District #1's Edlio
  site; it is Weston County School District #1's (title "Weston Co School District 1", the NCES directory's website
  for LEAID 5606090). Washakie #1's site is `https://www.wsh1.k12.wy.us/`, an Apptegy site, built as
  `apptegy-washakie-1-wy`. Every other round-2 district site's title was checked against its district: all match.
- **Florida's SharpSchool districts** (Polk, Lee, Marion): the alert component's endpoint was found in its bundle and
  answers, but only to POST (see the table above); not built.
- **Not built** (58 more sites, each recorded in `gaps.json` with the reason): WordPress, Google Sites, Weebly, Wix,
  Drupal and SchoolBlocks sites with no alert element (in Montana, Wyoming, Florida and Idaho); Helena's (the apex
  answers, WordPress, no alert element); Livingston's and Sublette #9's Edlio pages (no alert element today, the same
  as Natrona's); sites that could not be read (TLS verification failing at Butte, Polson, Ronan, Trout Creek,
  Anderson and Gulf; the proxy's 502 at West Yellowstone, Drummond, Manhattan, Santa Rosa, Columbia, Gadsden, Liberty,
  Jefferson and Lafayette; HTTP 202 bot checks at Monforton and Heart Butte, not worked around); and Geyser's listed
  domain, which now serves an unrelated casino site. Gilchrist's listed address (`gilchristfl.apptegy.us`) did not
  answer, but its own (`gilchristschools.org`) did and is built; Highlands' listed address is a refresh to
  `www2.highlands.k12.fl.us`, built. North Gem's SchoolBlocks homepage shows its news posts, and one is a weather
  closure ("School Closure", Feb 18, 2026: "Due to current weather conditions, all North Gem schools are closed
  today."): districts do post weather closures on their own sites, but a feed of dated posts is not an alert list
  (a feed always holds posts, so reading it would count as "seen populated" whether or not anything is closed); not
  built.
- **Older page forms, read from the archive.** Run 36341776194's captures showed that most Florida district homepages
  of 2022-2024 were not today's pages: Apptegy's sites were Nuxt 2 (the state in a `window.__NUXT__` script, with
  the same banner store), and Manatee's, Monroe's, Alachua's and Osceola's were Blackboard Web Community Manager
  (Schoolwires) sites whose "Important Announcement" app held the district's notice. The Apptegy adapter now reads
  the Nuxt 2 state (`apptegy-nuxt2-state`, through a new reader of the script's literals, `nuxt2.py`, which never
  runs it) and the 2025 layout of the Nuxt 3 state (the banners in the main store); the Apptegy and Smart Sites
  adapters read a Schoolwires homepage's announcements (`schoolwires.py`). Their captures on Ian, Helene and
  Milton hold the closures (Martin, Brevard, Sarasota, Manatee, Monroe, Osceola). Pages of other CMSs without an
  alert region (Hillsborough's and Duval's Blackboard pages, Clay's Google Sites page, Twin Falls' WordPress page)
  are refused, never read as empty.
- **Built from the archive's evidence: Pasco and Miami-Dade.** Pasco's own homepage keeps a banner slot (empty
  today); its captures of 2024-09-26, 2024-10-09 and 2024-10-10 hold the Helene and Milton closures, and its 2022
  form (a red rectangle) the reopening after Ian: built as `pasco-county-fl` (adapter `pasco`, 106 schools).
  Miami-Dade's homepage draws the visible items of `https://mainapi.dadeschools.net/api/v1/alerts/` (its bundle's
  `API_1_ALERTS`, template `ngIf: 1==e.visible`); three hidden items today, and in the capture of 2024-10-09 14:41
  UTC one visible item, "Hurricane Milton: All M-DCPS schools, as well as Region and District offices will be CLOSED
  on Wednesday, October 9 and Thursday, October 10.": built as `dadeschools-miami-dade-fl` (adapter
  `dadeschools`, 526 schools).
- **Miami-Dade** also runs a storm microsite, `storms.dadeschools.net` (an Angular app over `api.dadeschools.net`'s
  website-management API: announcement pages, found by a POST of the host name); pages, not a list; not built.

| Source | Platform | State | Schools / weighted | Live 2026-09-27 |
|---|---|---|---:|---|
| `dadeschools-miami-dade-fl` | dadeschools | FL | 526 / 118.5 | empty (proven: capture of 2024-10-09) |
| `pasco-county-fl` | pasco | FL | 106 / 59.2 | empty (proven: captures of 2024-09-26, 2024-10-09 and 10-10) |
| `apptegy-corvallis-mt` | apptegy | MT | 10 / 31.8 | empty |
| `apptegy-centerville-mt` | apptegy | MT | 6 / 31.2 | empty |
| `apptegy-belt-mt` | apptegy | MT | 4 / 20.8 | empty |
| `finalsite-lewistown-mt` | finalsite | MT | 5 / 20.6 | populated |
| `apptegy-hardin-mt` | apptegy | MT | 6 / 19.9 | empty |
| `apptegy-hamilton-mt` | apptegy | MT | 6 / 19.1 | empty |
| `apptegy-anaconda-mt` | apptegy | MT | 4 / 18.8 | empty |
| `apptegy-frenchtown-mt` | apptegy | MT | 5 / 18.3 | empty |
| `apptegy-st-regis-mt` | apptegy | MT | 3 / 17.3 | empty |
| `apptegy-superior-mt` | apptegy | MT | 3 / 17.3 | empty |
| `apptegy-conrad-mt` | apptegy | MT | 4 / 16.8 | empty |
| `apptegy-dutton-brady-mt` | apptegy | MT | 4 / 16.2 | empty |
| `apptegy-hot-springs-mt` | apptegy | MT | 3 / 15.7 | empty |
| `apptegy-noxon-mt` | apptegy | MT | 3 / 15.7 | empty |
| `finalsite-thompson-falls-mt` | finalsite | MT | 3 / 15.7 | empty |
| `apptegy-stanford-mt` | apptegy | MT | 3 / 15.6 | empty |
| `finalsite-hobson-mt` | finalsite | MT | 3 / 15.6 | empty |
| `finalsite-havre-mt` | finalsite | MT | 5 / 14.9 | populated |
| `finalsite-hellgate-mt` | finalsite | MT | 4 / 14.7 | populated |
| `apptegy-shelby-mt` | apptegy | MT | 5 / 14.4 | empty |
| `apptegy-philipsburg-mt` | apptegy | MT | 3 / 14.1 | empty |
| `apptegy-cji-mt` | apptegy | MT | 5 / 13.4 | empty |
| `apptegy-big-sky-mt` | apptegy | MT | 3 / 13.1 | empty |
| `apptegy-three-forks-mt` | apptegy | MT | 3 / 13.1 | empty |
| `apptegy-willow-creek-mt` | apptegy | MT | 3 / 13.1 | empty |
| `apptegy-white-sulphur-springs-mt` | apptegy | MT | 3 / 13.1 | empty |
| `apptegy-winifred-mt` | apptegy | MT | 3 / 12.4 | empty |
| `apptegy-chinook-mt` | apptegy | MT | 4 / 12.2 | empty |
| `finalsite-laurel-mt` | finalsite | MT | 5 / 11.4 | empty |
| `apptegy-st-ignatius-mt` | apptegy | MT | 3 / 11.3 | populated |
| `smartsites-libby-mt` | smartsites | MT | 3 / 10.7 | empty |
| `apptegy-ennis-mt` | apptegy | MT | 3 / 10.2 | empty |
| `apptegy-twin-bridges-mt` | apptegy | MT | 3 / 10.2 | empty |
| `apptegy-malta-mt` | apptegy | MT | 4 / 9.9 | empty |
| `apptegy-lima-mt` | apptegy | MT | 3 / 9.8 | empty |
| `apptegy-darby-mt` | apptegy | MT | 3 / 9.5 | empty |
| `apptegy-florence-carlton-mt` | apptegy | MT | 3 / 9.5 | empty |
| `apptegy-victor-mt` | apptegy | MT | 3 / 9.5 | empty |
| `apptegy-big-sandy-mt` | apptegy | MT | 3 / 9.5 | empty |
| `apptegy-geraldine-mt` | apptegy | MT | 3 / 9.5 | empty |
| `apptegy-deer-lodge-mt` | apptegy | MT | 2 / 9.4 | empty |
| `apptegy-hays-lodge-pole-mt` | apptegy | MT | 3 / 9.1 | empty |
| `apptegy-medicine-lake-mt` | apptegy | MT | 3 / 9.0 | empty |
| `apptegy-plentywood-mt` | apptegy | MT | 3 / 9.0 | empty |
| `apptegy-westby-mt` | apptegy | MT | 3 / 9.0 | empty |
| `apptegy-harlowton-mt` | apptegy | MT | 3 / 8.9 | empty |
| `apptegy-townsend-mt` | apptegy | MT | 3 / 8.7 | empty |
| `apptegy-sunburst-mt` | apptegy | MT | 3 / 8.7 | empty |
| `apptegy-highlands-fl` | apptegy | FL | 22 / 9.4 | empty |
| `apptegy-wakulla-fl` | apptegy | FL | 13 / 8.7 | empty |
| `apptegy-madison-fl` | apptegy | FL | 11 / 6.5 | empty |
| `apptegy-okeechobee-fl` | apptegy | FL | 11 / 6.4 | empty |
| `apptegy-suwannee-fl` | apptegy | FL | 13 / 6.2 | empty |
| `finalsite-hendry-fl` | finalsite | FL | 15 / 5.3 | populated |
| `apptegy-hardee-fl` | apptegy | FL | 11 / 4.7 | empty |
| `finalsite-franklin-fl` | finalsite | FL | 6 / 4.7 | empty |
| `finalsite-baker-fl` | finalsite | FL | 10 / 4.5 | empty |
| `finalsite-bradford-fl` | finalsite | FL | 10 / 4.4 | empty |
| `apptegy-gilchrist-fl` | apptegy | FL | 6 / 3.4 | empty |
| `finalsite-desoto-fl` | finalsite | FL | 7 / 2.7 | empty |
| `smartsites-calhoun-fl` | smartsites | FL | 6 / 2.6 | empty |
| `apptegy-glades-fl` | apptegy | FL | 7 / 2.5 | empty |
| `smartsites-hamilton-fl` | smartsites | FL | 5 / 2.0 | empty |
| `finalsite-idaho-falls-id` | finalsite | ID | 22 / 40.7 | empty |
| `apptegy-marsh-valley-id` | apptegy | ID | 6 / 11.7 | empty |
| `smartsites-sugar-salem-id` | smartsites | ID | 6 / 10.8 | empty |
| `apptegy-west-jefferson-id` | apptegy | ID | 4 / 7.2 | empty |
| `finalsite-challis-id` | finalsite | ID | 3 / 5.9 | empty |
| `smartsites-laramie-1-wy` | smartsites | WY | 39 / 115.7 | empty |
| `apptegy-converse-1-wy` | apptegy | WY | 9 / 28.8 | empty |
| `finalsite-sweetwater-1-wy` | finalsite | WY | 15 / 20.4 | empty |
| `finalsite-laramie-2-wy` | finalsite | WY | 6 / 17.8 | empty |
| `apptegy-park-6-wy` | apptegy | WY | 8 / 13.2 | empty |
| `apptegy-sweetwater-2-wy` | apptegy | WY | 9 / 12.2 | populated |
| `apptegy-park-1-wy` | apptegy | WY | 7 / 11.5 | empty |
| `smartsites-lincoln-1-wy` | smartsites | WY | 3 / 9.5 | empty |
| `apptegy-fremont-1-wy` | apptegy | WY | 5 / 8.7 | empty |
| `apptegy-fremont-6-wy` | apptegy | WY | 5 / 8.7 | populated |
| `apptegy-washakie-1-wy` | apptegy | WY | 6 / 6.4 | empty |
| `apptegy-big-horn-1-wy` | apptegy | WY | 6 / 5.7 | empty |
| `apptegy-fremont-14-wy` | apptegy | WY | 3 / 5.2 | empty |
| `apptegy-fremont-24-wy` | apptegy | WY | 3 / 5.2 | empty |

### Shares before and after this part (plain / closure-weighted)

Recounted 2026-09-28 at 00:34 UTC (`coverage.json` and `coverage.png` in `pipeline/out/internal/stations/`) on
one health: the shared full fetch of 2026-09-27 22:0x-23:05 UTC for every other part's station, with this part's
146 sources replaced by a fresh read of all of them (2026-09-28 00:12-00:26 UTC: 15 lists held rows, 131 were
empty, none failed); every earlier read of this part's sources (19:54 to 23:22 UTC, 1,146 reads in all, each
with its rows) kept as evidence; archived reads of every capture downloaded through run 36341776194; and the
committed fixtures. The merged `health.json`, `reads.jsonl`, `rows.jsonl` and `manifest.json` are the ones in that
folder. "Before" is the same measure with every source of this part's nine platforms left out.

**The proof gate** (the critic's round-2 finding: district banners that are not closings had been counted as
proof). A TV station's closings list proves itself with any row. Two kinds of this part's sources do not:

- A district's general alert channel (Apptegy banners, Finalsite page pops, Smart Sites pop-up alerts, Pasco's
  banner, Miami-Dade's alerts file) is proven only by a row that announced a closing, a delay, an early
  dismissal, a remote or e-learning day, cancelled classes, or weather or an emergency for the district. The
  rule (`notices.announces_closing`) is word patterns: weather and emergency words qualify on their own
  ("Hurricane Milton", "due to inclement weather", "power outage", "water main break"); closing, delay,
  dismissal and remote-day phrases ("all schools will be closed", "2-hour delay") qualify unless the
  notice is a planned day (a holiday, a break, staff development, a calendar early release day) or the "closes" is a deadline's, a closed
  session's or a closed campus's. A district's own name is never read as the notice ("Storm Lake" proves
  nothing). It agrees with the f5 status reader on every real row in the tests (the status reader itself is
  not committed yet, so the gate does not import it; the agreement test skips without it).
- A status board (Flathead County's closures page, the Shasta and Trinity county offices' sheets, GOHSEP's
  parish layer) lists every school or system every day, most of them "Open", so it is proven only by a read
  in which a row's status is other than open (`notices.board_status_announces`: "Closed", "CLOSED", "Remote",
  "Early Dismissal", "Planned Closure", "Closing at 12:45", a delay). An all-open read proves nothing.

`gate_proofs` applies both before the proven share is counted; `coverage.json`'s `district_notice_gate` lists,
per gated station, each kept proof with the row that proved it and each dropped one with its first row and the
reason, and each unproven gated station's `checked.notice_gate` gives the number of its populated reads the gate
dropped. `test_gaps_notices.py` pins the verdict of every populated fixture of a gated source (35 files) and
tests the superintendent, hiring, referendum, bond, settlement, trustee, enrollment, registration, clinic,
records, fingerprinting and staff-development banners (none proves) against the hurricane closure banners of
Martin, Manatee, Brevard, Sarasota, Lake, Monroe, Pasco, Osceola and Miami-Dade (each proves).

| | Covered before | Covered after | Proven before | Proven after |
|---|---:|---:|---:|---:|
| National | 92.6% / 94.1% | 95.2% / 98.1% | 78.2% / 88.4% | 79.9% / 89.4% |
| MT | 8.9% / 7.1% | 97.8% / 98.6% | 8.9% / 7.1% | 14.9% / 13.4% |
| FL | 58.0% / 52.2% | 81.5% / 79.0% | 3.0% / 3.8% | 20.7% / 19.0% |
| ID | 62.0% / 56.4% | 81.5% / 78.6% | 59.8% / 53.2% | 59.8% / 53.2% |
| WY | 57.3% / 59.2% | 81.0% / 79.5% | 44.7% / 49.9% | 44.7% / 49.9% |
| LA | 63.0% / 62.2% | 86.4% / 86.4% | 28.2% / 29.1% | 77.5% / 78.4% |
| CA | 90.4% / 84.3% | 91.4% / 94.5% | 15.8% / 63.8% | 16.7% / 69.8% |

This part adds 3,038 covered schools (4,733.7 closure-weighted) and 2,024 proven ones (1,116.6 weighted)
nationally. Proven among its 146 sources (12), each by a row that passes the gate:

- Status boards: GOHSEP's parish layer (read live 2026-09-27, it keeps the statuses GOHSEP last entered, not that day's: 10 parishes "Closed" on 2026-06-17 or 2026-06-18 and East Feliciana "Early Dismissal" on 2026-06-17, and Cameron "Closed" on 2026-09-01), Flathead
  County (live: West Valley "Closed" on September 25-26, comment "No running water"; archived storm updates such
  as Fair-Mont-Egan "Closed" on 2024-02-09 and Pleasant Valley "Remote" on 2025-02-27) and the Shasta office's
  sheet (live: Black Butte Elementary and Jr. High "Closing at 12:45").
- District channels, by archived storm-day banners: Martin (Ian 2022-09-28, Milton 2024-10-09), Brevard (Milton,
  "Schools/offices will remain closed ... Friday, 10/11"), Sarasota (Helene, "closed ... due to the storm"), Lake
  (Milton, "we are required to close schools on Tuesday, Oct. 8"), Manatee (Helene and Milton, "All SDMC schools
  are closed"), Monroe (Milton, "monitoring the progress of Hurricane Milton"), Osceola (Ian, "Schools To Be
  Closed September 27 ..."), Pasco (Helene, Milton, and Ian's reopening after the storm's power losses) and
  Miami-Dade (Milton, "All M-DCPS schools ... will be CLOSED").

Dropped by the gate, so unproven: every live read of a district channel (2026-09-27/28: Lake's superintendent
appointment, Fremont #6's hiring call, St. Ignatius' homeschool enrollment, Sweetwater #2's registration, Broward's
referendum, Lewistown's bond election, Great Falls' settlement notice, Havre's trustee vacancy, Hellgate's
staff-development day, Hendry's clinic and health pop-ups, Belgrade's special-education records notice), Alachua's
archived "NOW HIRING SUBSTITUTE TEACHERS!" (five captures), Belgrade's archived records and fingerprinting notices,
Brevard's "OPEN tomorrow" of 2024-09-27 and Monroe's "OPEN Friday" of 2024-09-26 (other captures prove those two);
and the Trinity office's sheet, whose four reads list every school "Open" (California's proven weighted share falls
from 74.0% to 69.8% with it).

Weight still unproven after this part (closure-weighted schools a working source covers but no proven source
does): Montana 2,854 (the Cowles ticker, never captured, covers most of it; no Montana district channel has yet
been seen with a closing notice), Florida 1,711, California 498, Idaho 380, Wyoming 282, Louisiana 57. Counting
the weight no source covers at all as well (the measure of round 1's critique, weighted schools minus proven
ones): Montana 2,900, Florida 2,312, Idaho 700, California 610, Wyoming 478, Louisiana 154. Run 36361209861 (below) asks for the Montana, Wyoming and Idaho Apptegy homepages on
their counties' strongest winter-warning school days and the Florida homepages on the storm days not yet read;
its captures count only where a banner passes the gate.

### Wayback (round 2)

- Run 36329076920 (commit 05fe1a1, pushed 15:18 UTC): 57 CDX listings, no captures: the homepages of the 33
  Florida county districts scouted, filtered to the school days of Ian, Nicole, Idalia, Debby, Helene and Milton;
  22 Montana, Idaho and Wyoming district homepages over the winters 2016-17 to 2025-26; GOHSEP's standing layer
  and dashboard. It answered 18 of the 57 listings in 3 h 23 min (15:18 to 18:42 UTC); the other 39 failed after retries (the timestamp-pattern filters over busy homepages), and are kept in `still_wanted`. Answered: Florida's Orange (80 captures on the storm days), Alachua's old `sbac.edu` (63), Palm Beach (22), Brevard (17), Osceola (12), Marion (11), Pasco (118) and Walton (2); the winter captures of Pocatello (801), Great Falls (617), Helena (407), Blackfoot (270), Cassia (82), Fremont #25 (67), Butte (49), `d91.net` (44; not Idaho Falls D91's site after all, see the second pass) and Fremont ID (43). GOHSEP's layer and dashboard have no capture at all.
- The district sites' alert files are read by the pages' scripts, so their homepage captures do not show them
  (Finalsite's page pops, Smart Sites' pop-up alerts); only captures of the files themselves (`/fs/pages/<id>/page-pops`,
  `/api/popup-alerts`) can prove those sources. Apptegy's banners are in the homepage's state, so its homepage
  captures can. The next request, pushed as commit 6ceebb5 (run 36341776194): 133 storm-day captures (the
  exact listed ones where a listing answered, else the nearest the archive holds to 14:00 UTC on each day) of the Apptegy homepages on Milton, Helene and Ian (Florida)
  and on each Idaho and Wyoming district's two strongest NWS winter-warning school days since November 2023, of the
  Finalsite page-pops and Smart Sites alert files on the same days, of Pasco's and the Edlio districts' (Natrona,
  Soda Springs, Hot Springs #1, and wcsd1.org, which round 2 took for Washakie #1's but is Weston County School
  District #1's) homepages, and of Miami-Dade's public alerts file; then 29 listings of
  the alert files' addresses across all years.
- GOHSEP needs no capture: its live read is populated.
- Run 36341776194 (commit 6ceebb5, 18:44 UTC to 00:09 UTC): 119 of 133 captures downloaded (106 distinct); read with
  the adapters as this pass extended them: 23 populated, 40 empty, 48 refused (other CMSs without an alert region,
  homepages of Finalsite and Smart Sites districts, three one-character page-pops captures), 8 Edlio homepages with no
  alert element. The storm-day closings they hold prove Martin, Brevard, Sarasota, Lake, Manatee, Monroe, Osceola,
  Pasco and Miami-Dade (see the second pass). Its 29 listings show the Finalsite page-pops and Smart Sites pop-up
  alert files first captured in 2025 (at most six captures each, none on a storm day, nine never), so those channels
  can be proven only by live reads; Miami-Dade's alerts file has 91 captures (2021-06-03 to 2026-09-17).
- Run 36361209861 (commit f4fa734, pushed 00:10 UTC on 2026-09-28, still in progress at 00:30 UTC when round 2
  ended; not read): 122 captures
  (the Florida Apptegy and Smart Sites homepages not yet seen with a closing notice, on Idalia, Debby, Nicole, Helene
  or Milton; Hillsborough's and Duval's after their move to Apptegy; each Montana, Wyoming and Idaho Apptegy district
  of the second pass on its county's strongest NWS winter-warning school days) and 30 listings of the heaviest new
  district sites. Recorded in `archive-wanted-s4d.json`.

### Montana's Cowles ticker (the critic's note)

The listing of run 36315417698 holds a NonStop Local Montana article, "Montana School Closures for March 12, 2026"
(`montanarightnow.com/montana-school-closures-for-march-12-2026/article_e17217db-…html`, published 2026-03-11 17:38
MDT, captured 20260313115733; read live here 2026-09-27T15:38:40Z, SHA-256 1f399b70f147390f…): "The following schools
have reported they will be closed or delayed on March 12, 2026:" over an iframe of the same S3 ticker file. So the
ticker is the list the stations use on storm days. It is not proof: the article holds no rows of its own and the S3
file itself has never been captured, so the five Cowles stations stay unproven (recorded in `cowles.yaml`'s notes)
until a live read in a winter shows a row. Montana's proven share rises instead through its district sources.

### Handoffs (round 2)

- **Part 1 (framework)**: the district-level coverage change above sits in `registry.py`, `coverage.py`, `cli.py`
  and `test_stations_registry.py`, files other parts also have uncommitted changes in. Commit it alone as the exact
  hunks against HEAD.
- **Proof share's part** (`proof.py` and the proof block of `cli.py`, uncommitted): keep the two `notices` lines
  (`notices.gate_proofs` between `proof.gather` and `proof.add_proven`, then `notices.annotate_unproven`) and the
  `notices` import when committing that block, and commit it with or after this part's `notices.py`; without them
  the proven share counts district banners that are not closings and all-open status boards.
- **Other parts with district-level alert channels**: `hcoe-alerts` (Humboldt COE alerts, adapter `hcoe`) names
  LEAIDs and reads an alerts channel; if its rows are not only closings, its adapter belongs in
  `notices.GENERAL_CHANNEL_ADAPTERS` so the same gate applies (`santacruzcoe-closures` is a closures list and
  needs no gate). Not changed here: those adapters are not this part's.
- **Weights piece** (`snowlight/weights/registered.py`, station priority): it reads each station's `counties` as
  whole counties; a district-level source (`counties.basis: district`) covers only its `leaids`' schools and should
  be counted that way there too.

## Round 1 (11:09-12:10 UTC)

### The gap, recomputed

Uncovered closure-weighted schools by state, from `coverage.json` (counties with no working source):

| Health file used | Total uncovered weight | Top states |
|---|---:|---|
| 07:21 UTC fetch (the ranking this part was given) | 9,551 | MT 3,110 · FL 1,365 · MI 929 · ID 653 · WY 580 · NY 504 · CA 422 · MO 367 · TX 327 · LA 269 |
| 11:50 UTC fetch (other parts' stations read since) | 7,170 | MT 3,110 · FL 1,365 · ID 653 · CA 422 · WY 388 · TX 327 · LA 269 · AL 132 · MO 101 · GA 98 |
| 11:50 fetch plus this part's eight sources | 3,856 | FL 1,365 · ID 653 · WY 346 · TX 327 · LA 269 · CA 216 · AL 132 · MO 101 · GA 98 · MS 76 |

Michigan's gap (Traverse City-Cadillac) and New York's closed once part 3b's 9&10 News, Up North Live and New
York stations were read; the Traverse City ISD's own page (Northwest Education Services) points parents to exactly
those two lists.

### How it was checked

- robots.txt read first for every host (the repo's RFC 9309 reader, `snowlight.sources.stations.robots`, through
  `PoliteClient`), its verdict recorded; at least 5 s between requests to one host, and a host's Crawl-delay as a
  floor (5 s at shastacoe.org and tcoek12.org, 1 s at docs.google.com).
- TownNews BLOX sites (kulr8.com, montanarightnow.com, kpvi.com) answer 429 to pages their cache does not hold when
  asked in quick succession; each 429'd URL was left alone (not retried around). The pages that matter were read
  once each, minutes apart, and answered 200.
- Where a list was not linked from a homepage, it was found by web search and then read first-hand here.
- Wayback: listings from the archive-captures workflow (runs 36315417698 and 36317448357; this container cannot
  reach web.archive.org).

### Built (eight sources, three new platforms)

| Source | Platform / adapter | Counties (basis) | Schools / weighted gained | Live 2026-09-27 |
|---|---|---|---:|---|
| KULR-8 "Montana School Closures" (`kulr8.com/schoolclosures/`) | `cowles` | Billings DMA, 18 incl. Big Horn and Park WY (dma) | 264 / 651 | empty grid, "Closings Last Updated at 9:13am on 4/16/2026" |
| NonStop Local Montana "School Closures Around Montana" (`montanarightnow.com/schoolclosures/`) for KFBB, KHBB, KTMF, KWYB | `cowles` | Great Falls 13, Helena 1, Missoula 7, Butte-Bozeman 8 (dma) | 616 / 2,456 | the same file |
| Flathead County Superintendent of Schools | `flathead` | Flathead County (observed; also in KTMF's market) | 57 / 211 | populated: 35 schools, West Valley "Closed" (No running water) |
| Shasta County Office of Education closure sheet | `coesheet` | Shasta County (observed) | 103 / 122 | populated: 95 schools, two "Closing at 12:45" |
| Trinity County Office of Education closure sheet | `coesheet` | Trinity County (observed) | 20 / 84 | populated: 17 schools, all "Open", updated 01/05/2026 |

Together they cover 1,003 schools (3,313 closure-weighted) that no working source reached (measured against the
11:50 UTC health file; Flathead County is counted once).

The two Cowles pages frame one file,
`https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html`, a NewsTicker-style
"Closings Last Updated at" grid written by the company's ticker system (Last-Modified 2026-04-16, so written
during the last winter). Each Cowles call sign is its own station counting its own market, and all five read
that file. The Flathead, Shasta and Trinity lists are official county pages that list every school with its status
all year, so they always hold rows.

Montana: 8.9% of schools covered (7.2% weighted) → 97.8% (98.6% weighted) once these are read; only the Glendive
market (Dawson, Prairie, Wibaux; KXGN's site was unreachable) is left.

### Candidates by gap state

#### Montana

- **Cowles Montana Media** (KULR, KFBB/KHBB, KTMF, KWYB; montanarightnow.com is NonStop Local Montana, and
  kfbb.com and abcfoxmontana.com redirect to it): built. The pages' HTML assets
  (`/montana-school-closures/html_….html` on both sites) answered 429 and were not asked again; the
  `/schoolclosures/` pages answered 200 and frame the ticker. NBC Montana (KECI, KCFW, KTVM, also Cowles) has no
  closings link, only articles.
- **Montana Television Network** (Scripps: KTVQ, KRTV, KPAX, KXLF, KBZK, KTVH): the indexed
  `/school-closings-delays` pages answer 404; part 2 found `/weather/closings` an empty page on all six. Part 2's.
- **Flathead County Superintendent of Schools**: built (the county's 23 districts report to it; it relays to Bee
  Broadcasting and KOFI). The site warns its old domain `flathead.mt.gov` will be deactivated.
- **Radio**: Townsquare's KGVO (Missoula) and KBUL (Billings) keep tag pages of articles; KOFI (Kalispell) was
  unreachable (proxy 502). No list.
- No other Montana county superintendent keeps a status page that a search finds; OPI has no statewide list.

#### Florida

- **Florida Department of Education, storm information (K-12 closures)**: every fldoe.org URL, robots.txt
  included, answered 403 "Access Denied" (Akamai) to the project's User-Agent. An active block: dropped, not
  worked around. It is the statewide table of district closures in a hurricane (each Florida county is one
  district), so it would close most of Florida's gap if it could be read.
- **Florida Division of Emergency Management**: storm pages send readers to 2-1-1 for closures; none listed.
- **Orlando market** (738 of Florida's 1,365): WESH (Hearst, part 1), WOFL (FOX, part 3a), WFTV (Cox, part 3b)
  and WKMG (Graham, part 3b) have no closings page. Spectrum News 13's page (`mynews13.com/fl/orlando/weather/closings`)
  answers 404 but its region file `https://mynews13.com/services/closings.57cd92df9e0990af3e840362.json` answers
  `[ ]`: part 3b's Spectrum platform.
- Fort Myers (WINK: no link; nbc-2.com redirects to Hearst's gulfcoastnewsnow.com), West Palm Beach (WPBF,
  WPTV, WPEC, WFLX stale): nothing outside the other parts.

#### Idaho

- **Idaho Falls - Pocatello** (472): KIFI Local News 8 (News-Press & Gazette) has no list page
  (`/weather/closings/` 404) and posts daily articles; NPG's FlashAlert copy exists for KRDO only. KPVI's
  "School Closures" is one BLOX article rewritten as prose. East Idaho News answered 403 (blocked; dropped).
- **Twin Falls** (181): KEZJ (Townsquare) moved its closures to a category of posts; KMVT's Gray file is stale
  (part 1). FlashAlert's Boise region is named "Boise, Southern Idaho" on flashalert.net; part 3a maps it to the
  Boise market only, and its archived reports could show whether Magic Valley organizations post there.

#### California

- **Shasta** and **Trinity** county offices of education: built (Google Sheets published to the web, framed by
  the offices' Finalsite pages). Shasta's frame is the script-drawn widget view, so the poller follows the
  widget to the tab page it loads (`/pubhtml/sheet?headers=false&gid=…`), a server-written table on
  docs.google.com (robots `Allow: /spreadsheet`). The sheet's CSV output holds the same rows but redirects to a
  googleusercontent.com host whose robots.txt answered both 404 and `Disallow: /`, so it is not polled.
- Humboldt County Office of Education posts closures as news items (headlines), not a list; not built.
  Tehama and Butte county offices have no closures page; Siskiyou's embeds a sheet but the county is in a
  covered market.

#### Wyoming, Texas, Louisiana

- **Casper - Riverton**: K2 Radio and KGAB (Townsquare) keep tag pages of posts; County 10 (Fremont County) has
  no closings link. No list.
- **South Texas**: KIII's `/closings` redirects home (TEGNA, part 2); KRGV and KRIS have no closings link.
- **Louisiana** (269): the Governor's Office of Homeland Security and Emergency Preparedness keeps a standing
  public ArcGIS layer, `Parish_School_Closures_Public_View_Layer`
  (`services1.arcgis.com/fXHQyq63u0UsTeSM/.../FeatureServer/0`), with each of the 64 parish school systems'
  STATUS by CLOSURE_DATE (640 rows today; 11 "Closed", Cameron Parish on 2026-09-01), besides a dashboard and
  layer per incident (24-006 and 25-007 Winter Weather among them). It lists school systems (districts), so it
  should count only those districts' schools: it waits for the district-level coverage change below.

### Wayback

See each record's `wayback` field. Runs 36315417698 (listings) and 36317448357 (captures):

- **Cowles**: the ticker file has **no** capture. `abcfoxmontana.com/schoolclosures/` (2019-11-20) and
  `montanarightnow.com/schoolclosures/` (2020-11-24, 2021-03-06) were captured before the pages framed the ticker:
  they were BLOX sections of article cards (the 2021 one a single COVID-19 closure story), not lists, so the
  adapter refuses them and the five Cowles stations stay **unproven** until a live read or a capture shows a row.
  The S3 bucket's only other captures are other Cowles tickers (KHQ's school results, 2024-11-11, empty grid; the
  election results).
- **Flathead County**: nine captures on `flatheadcounty.gov` (2025-04-27 to 2026-08-15) and 40 on the county's old
  domain `flathead.mt.gov` (2022-10-02 to 2025-08-15, run 36323496096), every one populated (34 or 35 schools):
  48 archived reads with rows. All but the newest are an older layout (cards with plain tables, "UPDATED
  INFORMATION FOR ..."; in January 2023 the date stood on the next line), which the adapter reads as
  `flathead-card-tables`. They include storm days: "Friday, February 9th, 2024" (four schools Closed),
  "Wednesday, December 17th, 2025" (five Closed, Deer Park a 2-hour delay "due to power") and "Friday, March 13th,
  2026" (five Closed). Proven.
- **Shasta and Trinity**: the county offices' pages were captured (Shasta 2024-10-21, 2024-12-12, 2026-01-10;
  Trinity 2026-05-16), and Shasta's widget view twice (2023-06-17, 2024-08-22), all framing the same sheets; the
  tab page and Trinity's sheet view have no capture (404). Both are proven by live reads (the sheets list every
  school); Shasta's showed two early dismissals.
- Exact-prefix listings (run 36317448357): `kulr8.com/schoolclosures/` has six captures (2019-07-16 to
  2021-09-17; downloaded in run 36323496096: all six are the same pre-ticker section of article cards); the
  Flathead page on the county's old domain, `flathead.mt.gov`, has 40 (2022-10-02 to 2025-08-15, winters 2022-23 to
  2024-25; all downloaded and read in run 36323496096); `fldoe.org/em-response/*` has 1,852 (the blocked Florida list is well archived, but cannot be read
  live); `localnews8.com/weather/closings*`, `kpvi.com/weather/closings*`, `kfbb.com/schoolclosures*` and
  `kulr8.com/montana-school-closures/*` have none.
- The first run's host-wide listing of kulr8.com failed, and the reader stopped on `flathead.mt.gov/*` (it does
  not catch `http.client.IncompleteRead`), so the Idaho, Wyoming and Florida host listings were not made; the
  second run listed exact prefixes instead.

### Handoffs to other parts

- **Part 1 (framework, Gray)**: the archive reader in `.github/workflows/archive-captures.yml` dies on
  `http.client.IncompleteRead` during a CDX listing (run 36315417698, `flathead.mt.gov/*`), losing every listing
  after it; it should be caught like the other read errors. Gray's KMVT (Twin Falls) and WFLX (West Palm Beach)
  exports are stale.
- **Part 2 (Scripps)**: the six MTN sites have no list today (`/school-closings-delays` 404).
- **Part 3a (FlashAlert)**: the Boise region is "Boise, Southern Idaho"; archived reports naming Magic Valley
  organizations would support adding the Twin Falls market's counties on an observed basis.
- **Part 3b (Spectrum)**: Spectrum News 13 Orlando's region file
  `https://mynews13.com/services/closings.57cd92df9e0990af3e840362.json` answers `[ ]` (page 404); Bay News 9
  (Tampa) likely has one too.

### Not built in round 1, and why (weighted schools still uncovered after round 1: 3,856; see round 2 for what changed)

- Florida (1,365): the one statewide list blocks the project (403).
- Idaho (653) and Wyoming (346): no outlet in the Idaho Falls, Pocatello, Twin Falls or Casper markets publishes a
  list with rows; closures appear as articles.
- Louisiana (269): the state's parish school closures layer is a district-level list (see above).
- District-level sources (a district's own alert feed) were not built this round: counting a district's schools
  needs the coverage measure to take NCES district IDs, a change to `registry.py`, `coverage.py`, `proof.py` and
  `cli.py`, which other parts are editing in the working tree right now (uncommitted), so it could not be made as a
  separate, additive commit.
