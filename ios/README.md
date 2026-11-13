# The Snowlight iPhone app

The native iPhone app of Snowlight (snowlightmap.com): the same closings map and the same
chance of no school as the site, in SwiftUI. This folder holds all of it. Nothing here is
part of the site or the data pipeline, and nothing here changes them.

It is built and tested on GitHub's standard hosted machines, which are free for this public
repository. No Mac, no Apple account, no signing identity and no secret is needed for any
of it.

| Folder | What it is |
|---|---|
| `SnowlightCore/` | A pure Swift package: the data shapes, the day rules, the words, the screen models. Foundation only, so it builds and tests on Linux too. |
| `SnowlightKit/` | The SwiftUI package: the views. It draws only what a screen model of SnowlightCore hands it. |
| `App/` | The app's entry point, five lines. |
| `project.yml` | The XcodeGen spec. The `.xcodeproj` is made from it on the Mac runner and never committed. |
| `tools/` | The scripts the workflows run, and the files they compare against. |

## The rules

Each rule is held by a script, a test or the compiler, named beside it.

1. **No signing material, no secret, no billed machine.** No certificate, key, profile, team
   value or token anywhere in the repository; builds pass `CODE_SIGNING_ALLOWED=NO`. The iOS
   workflows read no secret, have `permissions: contents: read`, run only on
   `ubuntu-24.04`, `macos-26` or `xcode-27`, and use only `actions/checkout@v7`,
   `actions/setup-node@v7` and `actions/upload-artifact@v7`. (`tools/check-ios.mjs`, rules
   `signing.*`, `workflow.*`, `runner.label`.) `ios/Local.xcconfig` is git-ignored: it
   exists only on the borrowed Mac.
2. **The app says nothing the site would not.** Every shown string is a `ShownText`. Only
   `SnowlightCore/Sources/SnowlightCore/Words/` can make one: the initializer is not public
   (the compiler holds that for the kit), and `check-ios` refuses every other way to make
   one in the rest of SnowlightCore. The kit and the app may not import SnowlightCore with
   `@testable` or an underscored attribute, which would see past what it makes public
   (`view.import`), and neither they nor SnowlightCore may use an unchecked cast, raw
   memory or a symbol looked up by name (`code.unsafe`). `Words/` is the site's words,
   ported and proven against the site's own code (the golden files), plus the short list
   of words only the app has (`tools/app-words.txt`, each marked approved or pending with
   who said so).
3. **A view draws only what its screen model hands it.** No string literal in a view (but
   symbol names in `Shell/Names.swift` and the two names of `Shell/ThisPhone.swift`, rule
   11); `Text(` only in `Shell/Shown.swift`, and there
   only as `Text(verbatim:)` from a `ShownText`; no word table named; no system formatter;
   no value turned into words; nothing of the device read (its clock, zone, language,
   files, settings). SnowlightCore's public surface holds no text at all but two things:
   a `ShownText`'s characters (`drawnString`, read only in `Shell/Shown.swift`) and what a
   person typed into search (`SearchQuery.typed`, reachable in a view only as the binding
   `$query.typed`). So SnowlightCore hands a view no other text; what the system itself
   could hand a view as text (a number spelled out, a name, an identifier, the device's
   own words) is refused by the lists of `words.value` and `view.device`. (`check-ios`,
   rules `words.*`, `view.*`, `core.publicstring`.)
4. **No read of the device's clock or zone, of the process's environment or of the
   phone's own settings store, in SnowlightCore or in a test.** The clock, the zones and
   the settings store are always parameters. The one test that may read the clock, the
   zone and the environment is `ThisMachineTests.swift`: it proves the odd test zone took
   hold. From M5, one allow-listed file (`Net/DeviceClock.swift`) will read the clock and
   the phone's zone to hand them to the models; none exists yet. SnowlightCore reads
   nothing else of the machine either (its files, the app's bundle, a process, a random
   value, a path such as the zone file), and no test starts a process or names a path of
   the machine: the fixtures come from the tests' own bundle. (`core.device`,
   `tests.device`.)
5. **No network in a test, in SnowlightCore or in a view.** M0 makes no request at all.
   (`core.network`, `tests.network`, `view.network`.)
6. **Every Swift test runs in CI under a zone that is not UTC**, the same tests on every
   machine, none skipped. Both hosted machines' own zone is UTC, where code that leans on
   the device's zone by mistake gives right answers. Each `swift test` step sets `TZ` and
   `SNOWLIGHT_EXPECT_ZONE` to the same odd zone (`workflow.zone`); no test may be skipped
   or kept from a platform (`tests.skip`); the count of tests in the source is the number
   in `tools/test-count.txt` (`tests.count`, 67 today).
7. **Made-up schools only.** Fixtures are the pipeline's synthetic ones; no school crest or
   logo is ever committed.
8. **The picture tour is debug code.** Everything under `Tour/` is inside one `#if DEBUG`
   (`tour.debug`), and the Mac job builds Release too and looks for the tour's launch keys
   in the release app (`tools/build.sh`).
9. **English only.** No `.lproj` folder and no strings file (`language.file`).
10. **Laid out from the room the window gives, never for one phone.** The same app runs on
   an iPhone 17 Pro (402 x 874 pt), on the iPhone Duo closed (466 x 678 pt, of which the
   system's own controls take an 84 pt column on the right; both measured by the app on the
   simulator) and open (951 x 669 pt on its side: the device profile's figure, 2007 x 2853 px
   at 3x, NOT measured, since the simulator never showed the app on the inner screen), and a
   fold or an unfold changes the room while it runs (not proven: no simulator here folds). So a view never reads the
   device's screen, idiom or orientation and writes no length of 300 pt or more
   (`view.layout`); content sits inside the safe area, so it stops where the system's
   controls begin; and every screen's content keeps to the readable column
   (`Layout/ReadableColumn.swift`, at most `ContentLayout.readableLimit`, 672 pt, the
   width of the system's readable content guide at the standard text size). The width
   class alone picks one column (an iPhone, the closed Duo) or two (the open Duo, the
   owner's two panes, not drawn yet): `SnowlightCore/State/ContentLayout.swift`, tested as
   a pure function of the room (`ContentLayoutTests`: the two measured rooms and the open
   Duo's profile figure; a test of a function, not a proof of a live fold). Only the system's own
   tab bar, navigation bars, toolbars and sheets carry the app's controls, so the system
   moves them to the side on the Duo; no custom bar is ever drawn. `Tour/` is measurement
   only, debug code outside this rule: `TourGeometry` reads and logs the window's
   orientation and the bars' places so the pictures can be judged, and nothing it reads
   reaches a layout.
11. **One file knows the phone, and only whether it has an outside screen.** The Outside
   screen row of Settings exists only on an iPhone Duo, and no documented call of the iOS
   27.1 SDK says whether a phone has an outside screen (UIKit's hinge interaction, iOS 27.1,
   says whether a phone has a hinge and reports Closed on the closed Duo simulator; whether
   to use it is the lead's ruling, open). So `Shell/ThisPhone.swift` reads the
   phone's model name (on the simulator, the simulated phone's, which the simulator hands
   the app as `SIMULATOR_MODEL_IDENTIFIER`; on a phone, the system's `hw.machine`) as bytes,
   and SnowlightCore's `PhoneModel` says whether it is a Duo (`iPhone19,4`, tested; the name
   is the simulator's device profile's, not yet confirmed on a real iPhone Duo). The file
   hands out one Bool. It alone may hold those two names and read `ProcessInfo`; every
   other rule holds in it (`words.literal`, `view.device`, with samples).

`check-ios.mjs` reads code, not comments, and skips itself and this file, which both name
what is banned. It tests itself on every run first: a list of samples, at least one for
every rule and one for every entry of its lists of the clock, the zone, the environment,
the network, the device, the machine and the ways around the type system (each planted
wherever its list applies: in SnowlightCore, in a test, in a view), each of which must be
refused.
Its lists are lists: a spelling a list leaves out passes it. The locks that need no list
are the compiler's (the word tables, `ShownText`'s initializer and every text form of
SnowlightCore are not public, and `view.import` keeps the kit from seeing past that) and
the public-surface rule. A lock the compiler would hold for the system's own plain-string
controls is still to come (for example, the kit declaring their `StringProtocol` forms
unavailable, proven on the Mac). The screen itself is read from M1 on, by a UI test with
the first real screen.

## The workflows

Three workflows, all in `.github/workflows/`. Logic lives in `tools/` so the workflow files
change rarely.

- **`ios-core.yml`, iOS core** (Linux, about a minute). On every push or pull request that
  changes `ios/**` or the file itself. Runs `tools/check-ios.mjs`, the fixture check
  (`tools/sync-fixtures.mjs --check`), the golden check under two odd zones
  (`America/St_Johns`, `Pacific/Kiritimati`), a syntax-only parse of the kit and the app
  (`swiftc -frontend -parse`), and the core tests under each of the two zones.
- **`ios-app.yml`, iOS app** (macOS: about 10 minutes on macos-26, up to 26 on xcode-27,
  which also tours the iPhone Duo; the two run side by side). On the same changes. Two jobs:
  `app (macos-26, Xcode 26.6)`, the one that counts, with Xcode pinned by its path; and
  `app (xcode-27, may fail)`, the same steps on the newer image with its default Xcode and
  an iOS 27 simulator, allowed to fail while that image is marked a preview. Each runs the
  core tests on Apple's Foundation, fetches XcodeGen (pinned by version and checksum),
  generates the project, builds Debug and Release unsigned for the simulator, takes the
  picture tour, prints the colors at named points, and uploads the small pictures:
  `ios-shots` (and `ios-shots-27`), 14 days.
- **`ios-words-watch.yml`, iOS words watch** (Linux, under a minute). On a push that
  changes the site's code (`web/src/**`, `web/scripts/check-copy.mjs`), the pipeline's
  shared fixtures or the file itself: `sync-fixtures.mjs --check` and `gen-golden.mjs
  --check`. **A warning only, until testers hold the app** (LEAD-RULINGS R6): the job never
  fails. It writes one of two warnings on the run's page: "iPhone app words" when an answer
  of the site or a shared fixture changed (the next iOS push then fails until the golden
  files and the Swift port are brought up to date), or "iPhone app generator" when the
  generator could not load the site's code (no word is known to have changed). It watches
  all of `web/src`, and the generator refuses to load a site file from anywhere else (its
  exit 4), so the watch cannot fall behind what the generator reads.

**A change to any file under `.github/workflows/` runs the normal CI**, because the
pipeline and web tests read every workflow file. Before pushing one, run these locally:

```
cd pipeline && uv run pytest -q -p no:cacheprovider --no-cov tests/test_preview_workflow.py tests/predict/test_workflow.py
cd web && npx vitest run src/pwa/tests/config.test.ts
```

A push whose changed files are all under `ios/` starts iOS core and iOS app and nothing
else: `CI` ignores `ios/**`, and `Preview` ignores `ios/**` and the iOS workflow files.

On the `xcode-27` job only, the tour also runs on the **iPhone Duo** (`tools/duo.sh`,
FIRST, with 1000 s of its own; the iPhone 18 Pro's tour then has what is left of 1450 s of
the tour's clock, and a picture it has no time for is said and skipped: the iPhone tour
that counts is the macos-26 job's): the five screens closed,
light and dark (10 pictures, `duo-closed-<look>-<screen>`, from the outer screen,
`--display=1`), with the Outside screen setting on Beside the map; then Settings with Under
the controls chosen (`duo-closed-<look>-settings-under`) and My School with its ground in
the chance teal under each layout (`duo-closed-<look>-myschool-proof-beside` and
`-proof-under`); then Under the controls chosen in code through the tiles' own call
(`duo-closed-light-settings-chose-under`) and, after the app is stopped and started again
without the tour touching the kept layout, Settings once more (`duo-closed-light-settings-kept`,
which must show Under the controls chosen): 18 pictures. Their words are compared with `tools/tour-words/duo/` where
there is a file (Settings, with the Outside screen row), else with the iPhone's
`tools/tour-words/` files; the app must say it is on a phone with an outside screen; and
the app's own geometry line must show the system's tab bar standing upright on the right on
the four tab screens. A screen that never comes up or cannot be pictured, a changed word,
the app not knowing it is on a Duo or a tab bar elsewhere fails the job; so do, once the
image has the Duo's device type and a runtime that makes it, a Duo that does not boot, an
app that cannot be installed, and fewer than 18 pictures (out of time included). After each
picture the tour counts the black pixels where the Dynamic Island is (above the time): run
43204344211 caught a black disc there, drawn by the system in three light pictures in a
row and gone 4 s later; such a picture is kept aside (`ios/out/duo/<name>-island.png`) and
taken again, up to twice. The job is still `may fail` (`continue-on-error` in
`ios-app.yml`), so a failure of the Duo's turns that job red but not the run: whether to
make it count is the lead's decision (changing `ios-app.yml` starts the site's CI once). The job also
prints what the iOS SDK's UIKit and SwiftUI say about an outer display, a fold, a posture
or a hinge (rule 11): the 27.1 SDK has UIKit's `UIHingeInteraction` (`UIHinge.h`,
`UIHingeInteraction.h`), and on a build with that SDK the tour puts one on the window and
writes what it reports (`hinge:` lines, `Tour/TourGeometry.swift`), on the iPhone and on
the Duo. The pictures stay in `ios-shots-27`
and are also printed into the log as colour grids (`tools/grid.swift`, 96 columns), with
the band of the Settings pictures that holds the Outside screen row (y 200 to 352 pt) at
one cell per point (`grid <picture>-band`). The
Duo cannot be opened on GitHub's image (no fold command in simctl and no Simulator.app
there), so there is no open picture yet; the inner screen (`--display=3`) is pictured
once and stays black.

What the Mac job checks: the pinned Xcode exists; the core tests; XcodeGen's checksum; the
two unsigned builds for the simulator and, on the macos-26 job, one unsigned Release build
for a generic iPhone (`generic/platform=iOS`, `CODE_SIGNING_ALLOWED=NO`, no team), so the
code only a real phone runs (`ThisPhone`'s `hw.machine`) is compiled; every tour screen says
it is ready; the words of 15 pictures equal
`tools/tour-words/`; the pixel lines. The words file of a picture is **the words its
screen model offers the view**, read off the model in the app; it is not a reading of the
screen. `tools/tour-words/system/` lists by hand the words iOS itself draws on each screen
(none yet); M1's on-screen read compares both.

The pixel lines (`tools/pixels.swift`), one per named point, x and y in percent from the
left and the top:

| Pictures | Point | Must be |
|---|---|---|
| all but the probe | 50%, 60% | the `page` color of the look the screen is in: `#ffffff` light, `#131418` dark (the two forced pictures are in the opposite look; Dark-then-System is light) |
| the four tab screens | 94% from the top, at x 10%, 28%, 45%, 61% (My School, Map, Call it, Settings), inside each tab's capsule and clear of its symbol and name | the chosen tab's point at least 12 away from the page color (the system's capsule); the other three within 10 of it (the bar's glass) |
| settings | 40%, 22% and 72%, 22% | the Light tile `#ffffff` and the Dark tile `#131418`, in either look |
| settings | x 10%, every point from 33% to 47% | the `page` color: no Outside screen row on an iPhone |
| `light-settings-forced-row` | the same run | must FAIL: the tour shows the row on this iPhone for this one picture (`-tour.row shown`), the negative sample that shows the run can find a row |
| `dark-probe` | 10%, 25% | `#12a594`, printed yes or no and never a failure |
| `duo-closed-*` (the Duo, closed) | 40%, 60%; on the four tab screens also 25%, 94% | the `page` color: the content left of the system's side controls, and no tab bar along the bottom; 90%, 66% (the side tab platter's glass) printed yes or no |
| `duo-closed-*-settings*` | x 10%, some point from 31% to 50% | at least 60 from the `page` color: the Outside screen row (its heading and its first tile's bold bar) under Appearance |
| `duo-closed-*-myschool-proof-*` | 40%, 60% and 25%, 94%; 90%, 40% | the `chance` teal (`#12a594` light, `#36c9b3` dark); at 90%, 40%, in the side column under the status cluster and above the tab platter: the teal with Under the controls, at least 40 from it with Beside the map |
| every `duo-closed-*` | x 90%, some point from 58% to 96% | at least 60 from the ground (the page, or the teal): the system's side controls drawn (tab icons, search glyph) |
| every `duo-closed-*` but search | across y 4%, some point from x 4% to 40% | at least 60 from the ground: the page title drawn |
| `duo-closed-*-settings*` | across y 42%: x 2% to 4%, and x 41% to 42% | the chosen tile's ring (at least 60 from the page) at the first place with Beside the map, at the second with Under the controls (`-under`, `-chose-under`, `-kept`); the other place the page (within 12) |

The tab and tile places were measured on the small iPhone 17 Pro pictures of iOS app run
42914332720 (iOS 26.5), and hold the same in run 42898061415: the chosen capsule 20 away
from the page in light and 37 in dark, the bar 2 and 4. On another device, as on the
xcode-27 job, those lines are printed and not judged until their places are measured
there.

## The iPhone Duo

The owner's own phone is an iPhone Duo (iOS 27.1), so the app is made for it as well as
for an ordinary iPhone (the DUO LEG, Nov 11 and 12, 2026). Everything below was read from
the `xcode-27` job's log unless it says otherwise.

### Its sizes

| Shape | Points | Where the number comes from |
|---|---|---|
| iPhone 17 Pro | 402 x 874 pt, tab bar along the bottom (y 791, 83 pt high) | the app's own geometry line, macos-26 job, iOS 26.5 |
| Duo closed (outer screen) | **466 x 678 pt** at 3x (1398 x 2034 px), compact width and regular height, portrait; safe area top 0, left 0, bottom 34, right 84 | the app's own geometry line on the Duo simulator, iOS 27.1 runtime, first in run 43129256570 and in every Duo run since |
| Duo closed, the system's side controls | the tab bar stands upright on the right (x 397, 69 pt wide, the full 678 pt high); the four tabs sit in a bottom-aligned column 48 pt wide (x 394, y 392 to 654), icons only, with the search glyph at its foot (x 415, y 606, 48 x 48) | the same line: the system's own views and their frames |
| Duo open (inner screen) | **669 x 951 pt** at 3x upright (2007 x 2853 px), so 951 x 669 pt on its side | the simulator's device profile only: **not measured**, the app was never shown on the inner screen (below) |

Apple's spec page gives the panels as 1398 x 2034 px outside (the same as the simulator)
and 1878 x 2670 px inside; the simulator's inner screen is 2007 x 2853 px, the App Store
Connect picture size. The owner's own screenshots of the closed phone are 457 pt wide, not
466: which width a real phone gives is open until the app runs on it. The content beside
the side controls is 382 pt wide on the simulator; with draft 3's 20 pt margins the column
is 342 pt.

### How the simulator shows each screen

- **One device type for both poses:** "iPhone Duo"
  (`com.apple.CoreSimulator.SimDeviceType.iPhone-Duo`, model `iPhone19,4`, product class
  V68, at least iOS 27.1). On the `xcode-27` image only two runtimes make it: iOS 27.1
  (24A94425) and the device-only iOS 27.2-iPhone19-4 (24B91016s); the tour boots 27.1
  first. The app is built with Xcode 27.1 (27A9275) and the iOS 27.1 SDK
  (`iphonesimulator27.1`, 24A94232; Swift 6.4); the deployment target stays iOS 26.0.
- **Two screens:** `--display=1` "LCD" (primary), the outer screen, 1398 x 2034 px, and
  `--display=3` "LCD-1" (primary-1), the inner screen, 2007 x 2853 px. A `simctl io
  screenshot` that names no display is refused ("Cannot choose between 2 displays");
  `internal` and `main` are refused the same way, `inner`, `outer`, `cover` and
  `secondary` do not exist, and `external` hangs.
- **It cannot be opened on GitHub's image.** simctl, CoreSimulator, SimulatorKit and the
  device profile have no fold, hinge or posture command; Simulator.app (whose Device menu
  may have one) is not on the image; switching the screens' power on and off does not open
  the phone (the outer screen goes to the Home Screen, the app keeps its 466 x 678 pt
  window, the inner screen stays black); and a landscape mode for the inner screen is
  refused ("No mode found"). So the inner screen is pictured once per run and is black,
  and the open Duo, upright or on its side, has no picture yet. It can be measured on the
  borrowed Mac's Simulator.app or on the owner's phone.
- **The hinge:** the iOS 27.1 SDK has UIKit's `UIHingeInteraction` (`UIHinge.h`,
  `UIHingeInteraction.h`; status unknown 0, closed 1, partly open 2, fully open 3, and an
  angle in radians). On the closed Duo simulator it reports "status 1 (Closed), angle 0.0
  radians" at every launch; on an iPhone 18 Pro it reports nothing. The SDK has no call
  that says a phone has an outside screen. The runtime's only fold file is
  `SpringBoardFoundation.framework/hinge-samples.csv`, recorded hinge angles, not a
  control.
- **The Dynamic Island** now and then shows as a black disc above the time in a picture
  (run 43204344211, three pictures in a row, gone 4 s later); the tour retakes such a
  picture (above).

### The Outside screen setting

On the Duo only, Settings has a second row directly under Appearance, drawn the same way:
the heading "Outside screen", the grey aside "When your iPhone is closed", and two picture
tiles, "Beside the map" and "Under the controls", the chosen one ringed and its name
ticked, as Appearance does. The words are the owner's (approved Nov 12, 2026: "I like the
wording") and live in the words file like every other word.

- **A, Beside the map, is the default:** the content stops where the system's side
  controls begin, and the map (from M1) runs on under them. **B, Under the controls:** the
  content runs on under them to the right edge.
- The choice is kept across launches (`OutsideScreenStore`, the key `outsideScreen`,
  `beside` or `under`; anything else reads as A).
- **On any other iPhone the row does not exist**, and Settings is M0a's (the `settings`
  pixel line above, with a forced-row negative sample that proves the line can fail).
- The tiles are the approved mock-up's two small map pictures (ground, lake, roads, school
  dot, sheet, time bar and glass circle), drawn from tokens.
- Its effect is one layout value, `SideControls` (`SnowlightCore/State/OutsideScreen.swift`):
  on a Duo, in compact width, with A, the content stops beside the controls; in every other
  case it runs under them, as on M0a. The kit reads it through `Layout/SideControls.swift`
  (`PageGround`). In this piece only the placeholder tabs use it, proven by the tour's
  teal ground stopping at x 382 pt with A and running to the edge with B
  (`duo-closed-*-myschool-proof-*`).
- How the app knows it is on a Duo: rule 11.

### Approved Duo rulings for later pieces

The owner's rulings on the iPhone Duo (LEAD-RULINGS R14 to R17, design/app/duo/ROUND7-BRIEF.md
and the DUO LEG spec), with the piece that builds each:

- **The system's own controls, on the right** (R15): only the system's tab view, navigation
  bars, toolbars and sheets carry the app's controls, so on the Duo the system moves them
  to the right side; no custom bar anywhere; content keeps to the safe area and the layout
  margins. Every piece.
- **The Outside screen setting** (built, the DUO LEG; above). **M1 and every later screen
  with a sheet over the map** (My School and its states, Why, Call it, Map, Pick a school)
  applies its layout value.
- **Continue on Pick a school is the phone's own 48 pt glass circle** with draft 3's
  chevron (owner's choice 1: "the iphones button is better than continue by far"). The word
  in a capsule is dropped everywhere. Built with Pick a school in **M4**; nothing for it
  exists yet.
- **The open Duo shows two panes** (R16): My School beside the map, on regular width, with
  the system's split or column containers; the inner screen in portrait is the one pose
  with bars along the bottom. Not built yet, and not picturable on GitHub's image.
- **Band for band** (R17): every Duo screen, closed and open, is built only from mock-ups
  the owner has seen and approved, drawn from draft 3, and every later screen's proof
  pictures come in three shapes: iPhone 17 Pro, Duo closed, Duo open.
- **Open for the lead:** whether the `xcode-27` job stops being `may fail` (green in run
  43237329408, red in 43217555420 and 43226985119 when the Duo ran out of time on a slow
  runner); whether `ThisPhone` moves from the model name to the hinge; the width a real
  closed Duo gives (466 or 457 pt); and the ruled differences between the Duo pictures and
  the mock-ups (in the DUO LEG report).

## Making the golden files again

The golden files (`SnowlightCore/Tests/SnowlightCoreTests/Fixtures/golden/<family>.json`)
are the site's own answers, made by running the site's TypeScript modules in plain Node
(22.18 or newer; no `npm ci`). The generator never writes a sentence or an answer of its
own: every answer in a case is what a site function returned (`{"throws": true}` where it
threw a RangeError, apart from `null`, where it said nothing). `tools/gen-golden.mjs` says,
family by family, which site functions a case holds and in which order; a case is one line,
a list of its inputs and then the answers (instants as milliseconds since 1970, UTC; a number
JSON cannot hold, such as NaN, as the text `"NaN"`). `GoldenShapeTests` holds each family's
shape.

| Family | Site functions | Cases |
|---|---|---|
| `copy` | the `copy` object, `detailsCopy`, `chanceCopy.noSchool` | 1 |
| `clock` | `format.clock` | 1,443 |
| `time` | `format.time` | 2,810 |
| `instant` | `parseInstant` | 50 |
| `days` | `format.day`, `format.dayWithYear`, `chanceFormat.weekday`, `chanceFormat.chanceOn` | 373 |
| `stamps` | `format.liveAt`, `updatedAt`, `offline`, `posted` | 600 |
| `status-on` | `format.statusOn` | 403 |
| `shift` | `format.delay`, `format.dismissal` | 894 |
| `chance` | `format.chance`, `chanceFormat.chanceNumber`, `chanceFormat.delayInstead` | 209 |
| `grades` | `format.grades`, `format.number` | 274 |
| `details` | `detailsFormat.said` | 326 |
| `season-line` | `seasonFormat.line` | 1,021 |
| `season-file` | `parseSeason`, `schoolSeason`, `lastDayOver` | 224 |
| `map-day` | `mapDay`, `nextMapTurn`, `localDay`, `todayEverywhere`, `clockToday`, `schoolToday` | 5,839 |
| `zones` | `isTimeZone`, `regionOf` | 449 |
| `closings` | `parseClosings`, `rowOn`, `schoolStatus` (no covered file), `litStatus` | 4,493 |
| `predictions` | `parsePredictions`, `zonesOf` and `zoneOf`, `schoolOutlook`, `headlineDay`, `underWay` | 2,359 |
| `freshness` | `updateState` | 532 |
| `ids` | `isSchoolId`, `parseSchoolId` | 60 |

The generator also writes `SnowlightCore/Sources/SnowlightCore/Files/ZoneNames.swift`, the
app's list of time zone names (421 today): Node's own names, `UTC` and the long US
spellings Node leaves out, each kept only where the site's `isTimeZone` accepts it, so the
list is never wider than the site. It stops unless exactly 28 names on the list have a region
in the site's `regionOf` table. Where the site accepts a zone name the list does not hold
(`america/chicago`, `US/Central`, `EST`), a case says `narrower`, and there the app must
refuse.

The files the closings, predictions and season cases read are copies of the pipeline's
synthetic test files, in `SnowlightCore/Tests/SnowlightCoreTests/Fixtures/site/` under their
names in `pipeline/tests/` (`tools/sync-fixtures.mjs`, byte for byte; `--check` fails on any
difference). Copy them first, then make the golden files. After a change to the site's words
or rules, or to a shared fixture:

```
node ios/tools/sync-fixtures.mjs                                  # copy the fixtures
node ios/tools/gen-golden.mjs                                     # write the golden files
node ios/tools/gen-golden.mjs                                     # again: git status shows no change
TZ=Pacific/Kiritimati node ios/tools/gen-golden.mjs               # in another zone: still no change
TZ=America/St_Johns node ios/tools/gen-golden.mjs --check         # what CI runs
TZ=Pacific/Kiritimati node ios/tools/gen-golden.mjs --check
node ios/tools/sync-fixtures.mjs --check
```

`--check` compares answers, not bytes: a site file whose comment changed is printed as a
note and fails nothing; the zone list is compared whole. Exit codes: 0 all match; 1 an
answer differs (it prints the family, the first differing case and the changed site files);
2 the site's code could not be loaded; 3 Node too old or wrong usage; 4 a site file outside
what the words watch covers. Then update the Swift port until its tests pass, and commit
both together. The golden folder is about 2.3 MB (at most 3 MB, no file over 700 KB), and
making it takes about 4 seconds.

## Bumping the pinned Xcode

The `app` job pins Xcode by its path: `DEVELOPER_DIR` in `.github/workflows/ios-app.yml`.
When the `macos-26` image drops that Xcode, the job's first step fails with "The pinned
Xcode is gone from this image" and lists the Xcodes it has.

1. Read the image's README in `actions/runner-images` (macOS 26, arm64) for the Xcode
   versions, their paths and the simulator runtimes each one carries.
2. Set `DEVELOPER_DIR` to the new `/Applications/Xcode_<version>.app/Contents/Developer`,
   change the job's name to say which, and check that `SIM_OS_PREFIX` ("iOS 26.") still
   matches a runtime and `SIM_DEVICE` ("iPhone 17 Pro") still exists there.
3. It is a workflow change: run the three workflow-reading tests above, then push. It
   starts the normal CI once, which must be green.
4. The tab and tile places of `tools/pixels.swift` were measured on iPhone 17 Pro: if the
   device changes, measure them again on the first pictures and change `measuredOn`.

## Bumping XcodeGen

XcodeGen is fetched as the release's `xcodegen.zip`, pinned by version and checksum
(`XCODEGEN_VERSION` and `XCODEGEN_SHA256` in `ios-app.yml`; `tools/get-xcodegen.sh` checks
it). To move to a new version, on any machine:

```
curl -fsSL -o xcodegen.zip https://github.com/yonaskolb/XcodeGen/releases/download/<version>/xcodegen.zip
sha256sum xcodegen.zip            # compare with the digest on the release page
unzip -l xcodegen.zip             # must show xcodegen/bin/xcodegen
rm xcodegen.zip
```

Put the version and the digest you computed in `ios-app.yml`. Read the release notes for
changes to `project.yml`'s keys. It is a workflow change, as above.

## What the first runs proved

M0a's answers to what nobody could confirm without a Mac, each with the run it was read
from (Nov 10 and 11, 2026; all runs are on `viaate/jsalcards`). The last runs read here
are those of commit 66549a8, both green on the first attempt: iOS core 42946510117 and
iOS app 42946510032.

- **P1, Liquid Glass in the pictures:** for the lead's eyes. The tab bar reads as the
  system's own floating bar: a rounded pill with a soft shadow, a darker capsule on the
  chosen tab, and a round search button apart at the right. Over the plain page the
  bar's glass is only a faint tint (`#fdfdfd` over `#ffffff`, `#17181b` over `#131418`),
  so those pictures cannot show glass bending what lies behind it. Over the probe's
  Metal teal, the glass button and the glass label take on a darker teal of their own,
  with a light rim and a soft shadow. Best seen in `light-myschool.jpg`,
  `dark-settings.jpg` and `dark-probe.jpg` of `ios-shots` from iOS app run 42946510032.
- **P2, the status bar time override:** yes on the iOS 26.5 simulator: 9:41, full bars, a
  charging battery (run 42880463735, and every picture since, last in run 42946510032).
  On the xcode-27 job's iOS 27.2 simulator the override was accepted with no refusal; its
  pictures are in `ios-shots-27`, for the lead.
- **P3, does a Metal view draw in a simulator picture:** yes on both jobs (run
  42914332720, again in run 42946510032): "dark-probe 10% 25% #12a594 ... yes" on
  `macos-26` and on `xcode-27`, the exact teal; the probe's file said "metal device:
  Apple iOS simulator GPU" and "drawable presented: yes", and the app's own log "one
  drawable of 1206 x 1311 pixels was sent to be presented" and "the frame's commands
  completed".
- **P4, minutes,** whole job and its main steps, in seconds:

  | Job | First run | The last run |
  |---|---|---|
  | `core (Linux)` | 54 (run 42862198695, two tests: versions 17, tests 32) | 64 (run 42946510117: versions 19, guards 0, golden check 1, parse 1, tests 36 and 2 in the second zone) |
  | `app (macos-26, Xcode 26.6)` | 83, build only (run 42870517150: machine facts 11, core tests 32, XcodeGen 1, build 27); 359 with the first picture (run 42880463735, tour 244) | 633 (run 42946510032: machine facts 43, core tests 33, XcodeGen 1, Debug and Release builds 48, tour 462, colors 18, small pictures 4, uploads 6) |
  | `app (xcode-27, may fail)` | 728 (run 42914332720: machine facts 15, core tests 58, build 34, tour 588, colors 16) | 575 (run 42946510032: machine facts 7, core tests 34, both builds 34, tour 465, colors 20, uploads 4) |

  The two macOS jobs run side by side: the whole iOS app run took 10 min 33 s
  (42946510032). In the tour, a cold hosted simulator takes about 1.5 to 2.5 minutes to
  boot and 1 to 2 more to install the app; then a picture every 5 to 30 seconds, with
  now and then one picture that takes one to two minutes.
- **P6, can a lane fetch the pictures:** yes (run 42880463735): `ios-shots` came by plain
  `curl` of the artifact's zip, with no token, its sha256 equal to the upload's digest;
  again for runs 42898061415, 42914332720 and 42946510032, once each. No fallback is in
  use.
- **P7, does `simctl ui appearance` reach the app:** yes for both looks (run 42898061415,
  and every run since): the light pictures read `#ffffff` and the dark ones `#131418` at
  50%, 60%, the `page` token exactly.
- **P8, the xcode-27 leg:** green in its first run (job 130172715589 of run 42914332720,
  728 s) and in the last (job 130280510033 of run 42946510032, 575 s): image
  xcode-27-arm64 20261104.0337.1, macOS 27.0.1, Xcode 27.1 (27A9275), Apple Swift 6.4,
  the iOS 27.2 runtime with iPhone 18 Pro; 36 tests with the St. John's line; Debug and
  Release built with no warning and the Release app clean; the page line of all 14 shell
  pictures ok and the words of 14 pictures equal; the probe's teal read back exactly. In
  run 42939935001 it stopped before the first picture: that image has two iOS 27.2
  runtimes, one of them made for one new phone only, and the tour took that one
  ("Incompatible device"). `tools/tour.sh` now makes the device on each matching
  runtime in turn, newest first, and keeps the first that accepts it. In run 42946510032
  the ordinary runtime came first, so that fallback has been walked only on Linux, with
  stand-ins for `xcrun`. The tab and tile points, measured on iPhone 17 Pro, are printed
  there and not judged: all 10 tile lines say yes, and 20 of the 44 tab lines say no. On
  iPhone 18 Pro with iOS 27.2 the chosen tab's point and the point of the tab to its
  right read alike (`#ebebeb` light, `#191a20` dark), and in dark the rest of the bar
  reads `#323338`, lighter than the chosen tab: the reverse of iOS 26.5 (bar `#17181b`,
  capsule `#38393d`). Both the places and the rule must be measured on that device
  before they are judged.
- **P9, does XcodeGen 2.46.0's project build:** yes with Xcode 26.6 (run 42870517150) and
  with Xcode 27.1 (run 42914332720), with no warning, and again in run 42946510032.
  **Xcode 26.6 printed Swift 6.3.3** ("Apple Swift version 6.3.3 (swiftlang-6.3.3.1.3
  clang-2100.1.1.101)"); Linux has Swift 6.4.2; the same source compiles on both.
- **P10, the zones:** both machines' own zone is UTC (`date +%Z`). The odd test zone took
  hold through `TZ` alone, no fallback: "ThisMachineTests: this machine's zone is
  America/St_Johns, -12600 seconds from GMT on 2027-01-15" and "ThisMachineTests: this
  machine's zone is Pacific/Kiritimati, 50400 seconds from GMT on 2027-01-15" on Linux
  (run 42946510117), and the St. John's line on macOS (run 42946510032, both jobs).
- **P11, the Spanish picture:** no change: `light-search-es` is byte for byte
  `light-search` (run 42898061415, and again in run 42946510032). That proves nothing
  yet: the search screen at rest shows no word of iOS's own (the bar's search button is a
  symbol), so iOS had nothing to translate. A picture that would show such a word needs
  the field in use or another system control.
- **P12, Dark back to System at once:** yes, no fallback (run 42898061415, and every run
  since): started on a stored Dark with the simulator light and switched to System in
  code after the first frame, the picture is light ("light-settings-dark-then-system
  50% 60% #ffffff ... ok"), System is chosen, and its words have "Follows your iPhone"
  back.
- **P13, `simctl launch --stdout --stderr`:** yes on Xcode 26.6 (run 42880463735): the two
  files landed at exactly the host paths given, and the app's own lines were in the
  stderr file.
- **P14, the standard runners:** GitHub's table of standard runners for public
  repositories was re-read on Nov 10, 2026 at 21:34 UTC
  (docs.github.com, actions/reference/runners/github-hosted-runners): it lists `xcode-27`
  beside `macos-26` ("free and unlimited on public repositories"); the image list still
  marks Xcode 27 a preview, so `continue-on-error` stays. **For the lead:** look at the
  account's billing page once; the first xcode-27 run was 42914332720.
- **P15, the Linux parse step:** yes (run 42898061484, and every run since):
  `swiftc -frontend -parse` read every kit and app source without resolving its imports,
  in about a second.

Also measured, in the last runs: 36 XCTest tests pass in each of the three required runs
(Linux under two zones, macOS under one) and on the xcode-27 job, none skipped. The
guard's self-test refused 349 samples across 43 rules. On the `app` job all 68 judged
pixel lines are ok and none is WRONG. `ios-shots` is 482,467 bytes with 15 pictures and
15 words files, kept 14 days, against a budget of 4 MB; `ios-shots-27` is 509,295 bytes.
