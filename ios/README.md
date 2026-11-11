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
   symbol names in `Shell/Names.swift`); `Text(` only in `Shell/Shown.swift`, and there
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
   in `tools/test-count.txt` (`tests.count`, 36 today).
7. **Made-up schools only.** Fixtures are the pipeline's synthetic ones; no school crest or
   logo is ever committed.
8. **The picture tour is debug code.** Everything under `Tour/` is inside one `#if DEBUG`
   (`tour.debug`), and the Mac job builds Release too and looks for the tour's launch keys
   in the release app (`tools/build.sh`).
9. **English only.** No `.lproj` folder and no strings file (`language.file`).

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
  changes `ios/**` or the file itself. Runs `tools/check-ios.mjs`, the golden check under
  two odd zones (`America/St_Johns`, `Pacific/Kiritimati`), a syntax-only parse of the kit
  and the app (`swiftc -frontend -parse`), and the core tests under each of the two zones.
- **`ios-app.yml`, iOS app** (macOS, about 10 to 12 minutes). On the same changes. Two jobs:
  `app (macos-26, Xcode 26.6)`, the one that counts, with Xcode pinned by its path; and
  `app (xcode-27, may fail)`, the same steps on the newer image with its default Xcode and
  an iOS 27 simulator, allowed to fail while that image is marked a preview. Each runs the
  core tests on Apple's Foundation, fetches XcodeGen (pinned by version and checksum),
  generates the project, builds Debug and Release unsigned for the simulator, takes the
  picture tour, prints the colors at named points, and uploads the small pictures:
  `ios-shots` (and `ios-shots-27`), 14 days.
- **`ios-words-watch.yml`, iOS words watch** (comes with M0b). On a change to the site's
  code or the shared fixtures: do the app's golden answers still match? A warning only,
  until testers hold the app.

**A change to any file under `.github/workflows/` runs the normal CI**, because the
pipeline and web tests read every workflow file. Before pushing one, run these locally:

```
cd pipeline && uv run pytest -q -p no:cacheprovider --no-cov tests/test_preview_workflow.py tests/predict/test_workflow.py
cd web && npx vitest run src/pwa/tests/config.test.ts
```

A push whose changed files are all under `ios/` starts iOS core and iOS app and nothing
else: `CI` ignores `ios/**`, and `Preview` ignores `ios/**` and the iOS workflow files.

What the Mac job checks: the pinned Xcode exists; the core tests; XcodeGen's checksum; the
two unsigned builds; every tour screen says it is ready; the words of 14 pictures equal
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
| `dark-probe` | 10%, 25% | `#12a594`, printed yes or no and never a failure |

The tab and tile places were measured on the small iPhone 17 Pro pictures of iOS app run
42914332720 (iOS 26.5), and hold the same in run 42898061415: the chosen capsule 20 away
from the page in light and 37 in dark, the bar 2 and 4. On another device, as on the
xcode-27 job, those lines are printed and not judged until their places are measured
there.

## Making the golden files again

The golden files (`SnowlightCore/Tests/SnowlightCoreTests/Fixtures/golden/<family>.json`)
are the site's own answers, made by running the site's TypeScript modules in plain Node
(22.18 or newer; no `npm ci`). After a change to the site's words or rules:

```
node ios/tools/gen-golden.mjs                                     # write them
node ios/tools/gen-golden.mjs                                     # again: git status shows no change
TZ=Pacific/Kiritimati node ios/tools/gen-golden.mjs               # in another zone: still no change
TZ=America/St_Johns node ios/tools/gen-golden.mjs --check         # what CI runs
TZ=Pacific/Kiritimati node ios/tools/gen-golden.mjs --check
```

`--check` compares answers, not bytes: a site file whose comment changed is printed as a
note and fails nothing. Exit codes: 0 all match; 1 an answer differs (it prints the
family, the first differing case and the changed site files); 2 the site's code could not
be loaded; 3 Node too old or wrong usage; 4 a site file outside what the words watch
covers. Then update the Swift port until its tests pass, and commit both together.

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
from (Nov 10, 2026; all runs are on `viaate/jsalcards`).

- **P1, Liquid Glass in the pictures:** for the lead's eyes. The tab bar reads as the
  system's own floating bar with a darker capsule on the chosen tab and a round search
  button apart at the right; the probe's glass button and glass label show translucent,
  rimmed and shadowed over the Metal teal. Best seen in `light-myschool.jpg`,
  `dark-settings.jpg` and `dark-probe.jpg` of `ios-shots` from iOS app run 42914332720.
- **P2, the status bar time override:** yes on the iOS 26.5 simulator: 9:41, full bars, a
  charging battery (run 42880463735, and every picture since).
- **P3, does a Metal view draw in a simulator picture:** yes on both jobs (run
  42914332720): "dark-probe 10% 25% #12a594 ... yes" on `macos-26` and on `xcode-27`, the
  exact teal; the probe's file said "metal device: Apple iOS simulator GPU" and "drawable
  presented: yes".
- **P4, minutes:** Linux 25 to 95 seconds a run (first 54 s in run 42862198695; 62 s in run
  42914332788 with the guards, the golden check, the parse and two test runs). macOS 83 s
  for the first build-only run (42870517150) up to 689 s with 15 pictures (42914332720:
  machine facts 86 s, core tests 43 s, build 40 s, tour 484 s, colors 14 s); the xcode-27
  job 728 s in the same run. A cold hosted simulator takes about 2 minutes to boot and 1.5
  to 2 to install the app; then a picture every 7 to 18 seconds.
- **P6, can a lane fetch the pictures:** yes (run 42880463735): `ios-shots` came by plain
  `curl` of the artifact's zip, with no token, its sha256 equal to the upload's digest. No
  fallback is in use.
- **P7, does `simctl ui appearance` reach the app:** yes for both looks (run 42898061415):
  the light pictures read `#ffffff` and the dark ones `#131418` at 50%, 60%, the `page`
  token exactly.
- **P8, the xcode-27 leg:** green (job 130172715589 of run 42914332720), 728 s: Xcode 27.1
  (27A9275), Apple Swift 6.4, the iOS 27.2 runtime with iPhone 18 Pro, 36 tests, every
  shell pixel line ok, the words of 14 pictures equal. In run 42939935001 it stopped before
  the first picture: that image has two iOS 27.2 runtimes, one of them made for one new
  phone only, and the tour took that one ("Incompatible device"). `tools/tour.sh` now
  makes the device on each runtime in turn, newest first, and keeps the first that
  accepts it.
- **P9, does XcodeGen 2.46.0's project build:** yes with Xcode 26.6 (run 42870517150) and
  with Xcode 27.1 (run 42914332720), with no warning. **Xcode 26.6 printed Swift 6.3.3**
  ("Apple Swift version 6.3.3 (swiftlang-6.3.3.1.3 clang-2100.1.1.101)"); Linux has Swift
  6.4.2; the same source compiles on both.
- **P10, the zones:** both machines' own zone is UTC (`date +%Z`). The odd test zone took
  hold through `TZ` alone, no fallback: "ThisMachineTests: this machine's zone is
  America/St_Johns, -12600 seconds from GMT on 2027-01-15" and "... Pacific/Kiritimati,
  50400 seconds from GMT on 2027-01-15" on Linux (run 42914332788), and the St. John's line
  on macOS (run 42914332720, both jobs).
- **P11, the Spanish picture:** no change: `light-search-es` is byte for byte
  `light-search` (run 42898061415). That proves nothing yet: the search screen at rest
  shows no word of iOS's own (the bar's search button is a symbol), so iOS had nothing to
  translate. A picture that would show such a word needs the field in use or another
  system control.
- **P12, Dark back to System at once:** yes, no fallback (run 42898061415): started on a
  stored Dark with the simulator light and switched to System in code after the first
  frame, the picture is light ("light-settings-dark-then-system 50% 60% #ffffff ... ok")
  and its words have "Follows your iPhone" back.
- **P13, `simctl launch --stdout --stderr`:** yes on Xcode 26.6 (run 42880463735): the two
  files landed at exactly the host paths given, and the app's own lines were in the
  stderr file.
- **P14, the standard runners:** GitHub's table of standard runners for public
  repositories was re-read on Nov 10, 2026 at 21:34 UTC
  (docs.github.com, actions/reference/runners/github-hosted-runners): it lists `xcode-27`
  beside `macos-26` ("free and unlimited on public repositories"); the image list still
  marks Xcode 27 a preview, so `continue-on-error` stays. **For the lead:** look at the
  account's billing page once; the first xcode-27 run was 42914332720.
- **P15, the Linux parse step:** yes (run 42898061484): `swiftc -frontend -parse` read
  every kit and app source without resolving its imports, in about a second.

Also measured: 36 XCTest tests pass in each of the three required runs (Linux under two
zones, macOS under one), none skipped; `ios-shots` is 482 KB with 15 pictures and 15 words
files (run 42914332720), against a budget of 4 MB.
