// pixels.swift <folder>
//
// Reads the color at a few named points in each picture of the tour and prints them, so
// that whoever can read the job's log can tell a light screen from a dark one, see which
// tab is chosen, and see that the Settings tiles are drawn, without opening a picture. A
// plain script for the Mac runner: CoreGraphics and ImageIO only.
//
// For every PNG under the folder it prints one line per point:
//
//     <picture> <x%> <y%> #rrggbb <what it should be> ok|WRONG
//
// with x from the left and y from the top. It ends with status 1 if any judged line says
// WRONG, if a picture cannot be read or has no named point, or if there is no picture at
// all. Lines that are not judged end in yes or no and never fail the run: the Metal
// probe's (a fact about the machine), and the tab bar's and the tiles' on a device other
// than the one their places were measured on.
//
// The points, by the screen a picture shows (its name is <look>-<screen>[-more]):
//   - every picture but the probe: 50%, 60% is the page color of the look the screen is in
//     (the light or dark `page` token);
//   - the four tab screens (myschool, map, callit, settings): on the tab bar, at 94% from
//     the top, a point inside each tab's capsule and clear of its symbol and its name
//     (x 10%, 28%, 45%, 61%). The chosen tab's point is the system's capsule, at least 12
//     away from the page color in some channel; the other three are the bar's glass, within
//     10 of it. So a picture with no tab bar, or with the wrong tab chosen, fails;
//   - settings: a point on the Light tile (40%, 22%), white in either look, and one on the
//     Dark tile (72%, 22%), the dark page color in either look; and a run down x 10% from
//     33% to 47%, all the page color: no Outside screen row, which only the Duo has;
//   - search: the page point only (iOS folds the bar into one button there);
//   - the probe: 10%, 25% is the teal the Metal view is cleared to.
//   - My School drawn from a tour fixture (<look>-myschool-closed, M1 5.4): the panel's
//     ground in place of the page, at 50%, 75% (201, 655.5 pt: the empty panel below the
//     season card, which ends at 547, and above the tab bar at 791), `sheet` within 8; the
//     tab bar's points as above, held to `sheet` (the bar floats over the panel, which runs
//     to the bottom edge; in light `sheet` is the page's white); the map's ground at 5%,
//     23% (20.1, 201.0 pt: below the marker's halo, above the panel's shadow), `mapBg`
//     within 8; the marker's core at 43%, 17% (172.9, 148.6 pt, inside the 8 pt core round
//     the dot at 175, 151), `closed` within 12; the season card at 8%, 56% (32.2, 489.4 pt:
//     left of its text, inside its corner), `fill` within 8; and the grabber at 50%, 31%
//     (201.0, 270.9 pt; it is 183 to 219 by 267 to 272), `grab` within 16. Each is judged
//     only on the device the places were measured on (the build spec's geometry-r2.out).
//     And four ink lines (lead ruling R21, B1), so the letter spacing cannot drift: the
//     district line, the day line, Posted's words and the season card's line. Each is read
//     in a box of the picture, in points, as the first and the last column whose ink covers
//     at least half (between the box's middle shade, its ground, and its farthest shade,
//     its ink), to a fraction of a pixel. Each is held to the draft's own ink, drawn from
//     its HTML with the fixture's words through its renderer (premium/render.cjs, 3x, in
//     Playwright 1.63.0's Chromium, which draws draft 3's pictures pixel for pixel): the
//     edge the line is aligned by within 1 pt, the other within 1 pt or 1% of the line's
//     width, whichever is larger. Posted is aligned by its right edge, the others by their
//     left. Judged on the device the places were measured on.
//     The same on <look>-myschool-details (details known: the panel at 240, the dot at 140)
//     and <look>-myschool-tomorrow (the closed screen with tomorrow's words), but: on
//     -details the marker's point is 43%, 16% (172.9, 139.8 pt), there is no grabber point
//     (no whole percent lands on its 5 pt, 247 to 252), the ink lines' boxes move with the
//     panel, and the details line's ink is printed only; on -tomorrow the day line and
//     Posted are held to the draft's ink with tomorrow's words.
//   - the iPhone Duo's closed pictures (duo-closed-<look>-<screen>[-<variant>]): their own
//     points, measured on the Duo, with the Outside screen row and the two layouts, and My
//     School drawn from a tour fixture in both layouts (see duoPoints below).
//
// A run is a line of points down one column, printed as one line with the shade that
// tells (the farthest from the color it is held to).
//
// The tab and tile places were measured on the pictures of iPhone 17 Pro on iOS 26.5 (iOS
// app run 42914332720). On another device (SIM_DEVICE in the job's environment) those lines
// are printed and not judged, until their places are measured there.
//
// This samples named points and nothing more. It does not compare pictures, it does not
// read words, and it cannot judge glass: that stays for a person's eyes.

import CoreGraphics
import Foundation
import ImageIO

func twoHexDigits(_ value: Int) -> String {
    let digits = Array("0123456789abcdef")
    let clamped = min(255, max(0, value))
    return String(digits[clamped / 16]) + String(digits[clamped % 16])
}

struct Shade {
    let red: Int
    let green: Int
    let blue: Int

    var hex: String {
        "#" + twoHexDigits(red) + twoHexDigits(green) + twoHexDigits(blue)
    }

    /// The largest difference in any one channel.
    func distance(to other: Shade) -> Int {
        max(abs(red - other.red), max(abs(green - other.green), abs(blue - other.blue)))
    }
}

/// What a point must show.
enum Expect {
    /// This color, within a tolerance per channel.
    case near(Shade, Int)
    /// Not this color: more than the given difference in at least one channel.
    case awayFrom(Shade, Int)

    func holds(for seen: Shade) -> Bool {
        switch self {
        case .near(let want, let tolerance):
            return seen.distance(to: want) <= tolerance
        case .awayFrom(let other, let least):
            return seen.distance(to: other) >= least
        }
    }
}

/// What a run of points down a picture must show, from one height to another.
enum Run {
    /// At least one point at least this far from the color: something is drawn there.
    case someAwayFrom(Shade, Int)
    /// Every point within this tolerance of the color: nothing is drawn there.
    case allNear(Shade, Int)
}

struct NamedPoint {
    /// Percent from the left.
    let x: Int
    /// Percent from the top. For a run, where it starts.
    let y: Int
    let expect: Expect
    let what: String
    /// False: printed as yes or no, never a failure.
    let judged: Bool
    /// For a run down the picture: where it ends, in percent from the top, and what it
    /// must show. Nil for a single point.
    var runTo: Int? = nil
    var run: Run? = nil
    /// For a run across the picture instead, or a box: where it ends, in percent from the
    /// left (a run across has runTo equal to y). Nil for a run down one column.
    var runAcrossTo: Int? = nil
    /// True for a negative sample: a picture known to be wrong for this run, on which the
    /// run must NOT hold (ok when it fails, WRONG when it holds).
    var mustFail: Bool = false
}

/// The colors the named points are held to. The two page colors are the app's `page`
/// token, light and dark; the teal is what the Metal probe clears its view to.
enum Wanted {
    static let pageLight = Shade(red: 0xff, green: 0xff, blue: 0xff)
    static let pageDark = Shade(red: 0x13, green: 0x14, blue: 0x18)
    static let probeTeal = Shade(red: 0x12, green: 0xa5, blue: 0x94)

    // My School's colors, the tokens of SnowlightCore's State/Tokens.swift (approved draft 3,
    // d3t/app.css), light and dark.
    /// `sheet`, the panel's ground: CSS:17, :71.
    static let sheetLight = Shade(red: 0xff, green: 0xff, blue: 0xff)
    static let sheetDark = Shade(red: 0x1b, green: 0x1c, blue: 0x21)
    /// `mapBg`, the map's ground: CSS:50, :102.
    static let mapBgLight = Shade(red: 0xe6, green: 0xeb, blue: 0xf2)
    static let mapBgDark = Shade(red: 0x00, green: 0x00, blue: 0x00)
    /// The closed marker's core: `closed` by day (CSS:234), #7fd4ff at night (CSS:230).
    static let markerLight = Shade(red: 0x1d, green: 0x9b, blue: 0xe6)
    static let markerDark = Shade(red: 0x7f, green: 0xd4, blue: 0xff)
    /// `fill`, the season card: CSS:15, :69.
    static let fillLight = Shade(red: 0xf2, green: 0xf3, blue: 0xf5)
    static let fillDark = Shade(red: 0x2a, green: 0x2b, blue: 0x31)
    /// `grab`, the grabber: CSS:20, :74.
    static let grabLight = Shade(red: 0xd4, green: 0xd5, blue: 0xda)
    static let grabDark = Shade(red: 0x55, green: 0x57, blue: 0x5f)
}

/// The device the tab and tile places were measured on.
let measuredOn = "iPhone 17 Pro"
let device = ProcessInfo.processInfo.environment["SIM_DEVICE"] ?? measuredOn
let placesMeasuredHere = device == measuredOn

/// The four tabs in the order of the bar, each with the x of its point.
let tabs: [(screen: String, x: Int)] = [("myschool", 10), ("map", 28), ("callit", 45), ("settings", 61)]
let tabBarY = 94

/// The points of a My School picture drawn from a tour fixture, <look>-myschool-<variant>
/// (M1 5.4), in its look; empty for a variant whose places are not written here.
func mySchoolPoints(look dark: Bool, variant: String) -> [NamedPoint] {
    guard ["closed", "details", "tomorrow"].contains(variant) else {
        return []
    }
    // With details known the panel rests at 240 and the dot sits at 140, not 260 and 151
    // (myschool-closed-details-light.html:15, :108): the marker's point moves to 43%, 16%
    // (172.9, 139.8 pt), and no whole percent lands on the grabber's 5 pt (247 to 252).
    // For tomorrow the drawing is the closed screen's (M1 2.4).
    let details = variant == "details"
    let pick = { (light: Shade, darkShade: Shade) -> Shade in dark ? darkShade : light }
    let sheet = pick(Wanted.sheetLight, Wanted.sheetDark)
    let mapBg = pick(Wanted.mapBgLight, Wanted.mapBgDark)
    let marker = pick(Wanted.markerLight, Wanted.markerDark)
    let fill = pick(Wanted.fillLight, Wanted.fillDark)
    let grab = pick(Wanted.grabLight, Wanted.grabDark)
    var points = [
        NamedPoint(x: 50, y: 75, expect: .near(sheet, 8), what: "the panel's ground, sheet " + sheet.hex, judged: placesMeasuredHere),
    ]
    for tab in tabs {
        if tab.screen == "myschool" {
            let what = "the chosen tab's capsule (" + tab.screen + "), at least 12 from the panel's sheet"
            points.append(NamedPoint(x: tab.x, y: tabBarY, expect: .awayFrom(sheet, 12), what: what, judged: placesMeasuredHere))
        } else {
            let what = "the bar's glass over " + tab.screen + ", within 10 of the panel's sheet"
            points.append(NamedPoint(x: tab.x, y: tabBarY, expect: .near(sheet, 10), what: what, judged: placesMeasuredHere))
        }
    }
    points += [
        NamedPoint(x: 5, y: 23, expect: .near(mapBg, 8), what: "the map's ground, mapBg " + mapBg.hex, judged: placesMeasuredHere),
        NamedPoint(x: 43, y: details ? 16 : 17, expect: .near(marker, 12), what: "the closed marker's core " + marker.hex, judged: placesMeasuredHere),
        NamedPoint(x: 8, y: 56, expect: .near(fill, 8), what: "the season card, fill " + fill.hex, judged: placesMeasuredHere),
    ]
    if !details {
        points.append(NamedPoint(x: 50, y: 31, expect: .near(grab, 16), what: "the grabber, grab " + grab.hex, judged: placesMeasuredHere))
    }
    return points
}

/// A line of text whose ink is read across a box of the picture (lead ruling R21, B1).
struct InkLine {
    let what: String
    /// The box, in points from the window's top leading corner.
    let top: Double
    let bottom: Double
    let left: Double
    let right: Double
    /// The draft's first and last ink, in points, and how far each may be from it.
    let first: Double
    let firstWithin: Double
    let last: Double
    let lastWithin: Double
    /// False: printed as yes or no, never a failure (a line measured for the report only).
    var judged: Bool = true
}

/// The window the My School places were measured in, in points across (iPhone 17 Pro).
let windowPointsAcross = 402.0

/// The ink lines of a My School picture, <look>-myschool-<variant>; empty for a variant
/// whose lines are not written here. The draft's ink: the probe of the draft's own HTML
/// with the fixture's words, at 3x, in either look (the same to 0.01 pt).
func mySchoolInkLines(variant: String) -> [InkLine] {
    switch variant {
    case "closed":
        return [
            // "Synthetic District One · Grades 6–8", 242.53 wide: left aligned.
            InkLine(what: "the district line", top: 290, bottom: 310, left: 15, right: 330, first: 20.74, firstWithin: 1, last: 263.27, lastWithin: 2.43),
            // "Tuesday, January 12", 171.89 wide (the approved picture's own line): left aligned; the clock is right of 240.
            InkLine(what: "the day line", top: 435, bottom: 457, left: 15, right: 240, first: 20.29, firstWithin: 1, last: 192.18, lastWithin: 1.72),
            // "Posted 5:42 AM", 107.68 wide: right aligned; the clock's ink ends left of 268.5.
            InkLine(what: "Posted's words", top: 435, bottom: 457, left: 268.5, right: 392, first: 273.02, firstWithin: 1.08, last: 380.70, lastWithin: 1),
            // "2 closed · 1 delayed since Oct 27", 253.27 wide (the approved picture's own line): left aligned, inside the card.
            InkLine(what: "the season card's line", top: 512, bottom: 534, left: 30, right: 345, first: 37.00, firstWithin: 1, last: 290.27, lastWithin: 2.53),
        ]
    case "details":
        // The draft's details form (myschool-closed-details-light.html) with the fixture's
        // words, through the same renderer: the same words at the same x as on the closed
        // screen; the panel 20 higher (rest 240, :15) and the season card 3 lower (the
        // details line's 6 + 20, then 14 to the card, :33, :38).
        return [
            InkLine(what: "the district line", top: 270, bottom: 290, left: 15, right: 330, first: 20.74, firstWithin: 1, last: 263.27, lastWithin: 2.43),
            InkLine(what: "the day line", top: 415, bottom: 437, left: 15, right: 240, first: 20.29, firstWithin: 1, last: 192.18, lastWithin: 1.72),
            InkLine(what: "Posted's words", top: 415, bottom: 437, left: 268.5, right: 392, first: 273.02, firstWithin: 1.08, last: 380.70, lastWithin: 1),
            InkLine(what: "the season card's line", top: 515, bottom: 537, left: 30, right: 345, first: 37.00, firstWithin: 1, last: 290.27, lastWithin: 2.53),
            // "No buses. After-school activities cancelled.", 295.97 wide in the draft's
            // renderer: printed for the report, not judged (not one of R21's four lines).
            InkLine(what: "the details line", top: 444, bottom: 464, left: 15, right: 392, first: 21.17, firstWithin: 1, last: 317.14, lastWithin: 2.96, judged: false),
        ]
    case "tomorrow":
        // The closed screen's drawing with tomorrow's words (M1 2.4), the draft's HTML with
        // them through the same renderer: the day and Posted change, the rest is closed's.
        return [
            InkLine(what: "the district line", top: 290, bottom: 310, left: 15, right: 330, first: 20.74, firstWithin: 1, last: 263.27, lastWithin: 2.43),
            // "Wednesday, January 13", 201.81 wide: left aligned; the clock is right of 250.
            InkLine(what: "the day line", top: 435, bottom: 457, left: 15, right: 250, first: 20.32, firstWithin: 1, last: 222.13, lastWithin: 2.02),
            // "Posted 4:10 PM", 105.34 wide: right aligned; the clock's ink ends left of 271.
            InkLine(what: "Posted's words", top: 435, bottom: 457, left: 271, right: 392, first: 275.35, firstWithin: 1.05, last: 380.70, lastWithin: 1),
            InkLine(what: "the season card's line", top: 512, bottom: 534, left: 30, right: 345, first: 37.00, firstWithin: 1, last: 290.27, lastWithin: 2.53),
        ]
    default:
        return []
    }
}

/// The ink lines of a picture: My School's drawn from a tour fixture only.
func inkLines(for picture: String) -> [InkLine] {
    let parts = picture.split(separator: "-").map { String($0) }
    guard parts.count > 2, parts[0] == "light" || parts[0] == "dark", parts[1] == "myschool" else {
        return []
    }
    return mySchoolInkLines(variant: parts[2...].joined(separator: "-"))
}

/// Two decimals, for the log.
func twoDecimals(_ value: Double) -> String {
    String(format: "%.2f", value)
}

/// The page color a picture's screen is in: the forced pictures are in the look opposite
/// to the one their name begins with.
func pageShade(for picture: String) -> (shade: Shade, name: String)? {
    let light: (shade: Shade, name: String) = (Wanted.pageLight, "page light " + Wanted.pageLight.hex)
    let dark: (shade: Shade, name: String) = (Wanted.pageDark, "page dark " + Wanted.pageDark.hex)
    if picture == "light-settings-forced-dark" {
        return dark
    }
    if picture == "dark-settings-forced-light" || picture == "light-settings-dark-then-system" {
        return light
    }
    if picture.hasPrefix("light-") {
        return light
    }
    if picture.hasPrefix("dark-") {
        return dark
    }
    return nil
}

/// The iPhone Duo's closed pictures (tools/duo.sh, on the iOS 27 job) are named
/// duo-closed-<look>-<screen>. Their places were measured by the app itself on the Duo
/// simulator (iOS app run 43137086885): a window of 466 x 678 pt whose right 84 pt are the
/// system's own column of controls, its tab bar there (x 397, 69 wide, the full height)
/// with the four tabs in a platter at x 394 to 442, y 392 to 654, and nothing along the
/// bottom. So, in percent of the picture:
///   - 40%, 60% is the page color, in the content left of that column (judged);
///   - on the four tab screens, 25%, 94% is the page color too: no tab bar runs along the
///     bottom, as it does on an iPhone (judged; printed on search, which iOS lays out
///     differently);
///   - 90%, 66% is in the side platter, between two of its tabs: its glass, printed and
///     not judged until its color is measured.
/// The Outside screen setting (the Duo only): settings, with either layout chosen: down x
/// 10% from 31% to 50% of the height, at least one point drawn in ink (at least 60 from the
/// page): the Outside screen row, its heading and the first tile's bold bar, below the
/// Appearance row, which ends at about 30% (judged).
/// Something drawn, so that a blank picture fails (judged on every Duo picture):
///   - the system's side controls: down x 90% (419 pt, the middle of the platter at x 394
///     to 442) from 58% to 96% (393 to 651 pt), some point at least 60 from the page: the
///     tab icons and the search glyph, which only the system draws there;
///   - the page title, on every screen but search and My School (which draws none): across
///     y 4% (27 pt) from x 4% to 40%, some point at least 60 from the page.
/// Which Outside screen tile is ringed, on the Duo's Settings pictures (judged): across y
/// 42% (285 pt, the middle of the tiles), from x 2% to 4% (9 to 18.6 pt) the first tile's
/// ring when Beside the map is chosen, and from x 41% to 42% (191 to 195.7 pt), between the
/// two tiles, the second tile's ring when Under the controls is chosen (settings-under, and
/// settings-chose-under and settings-kept, where it was chosen in code and then kept across
/// a launch); the other place the page all along. Measured on run 43204344211's grids: the
/// first ring's left side near 15.5 to 18 pt, the second's near 192.5 to 197 pt.
/// My School drawn from a tour fixture (M1 5.4; places in points from the build spec's
/// geometry-r2.out): see duoMySchoolPoints.
let duoClosed = "duo-closed-"

/// The points of the Duo's My School pictures drawn from a tour fixture (M1 5.4):
/// duo-closed-<look>-myschool-closed (S1 Beside the map, A: the panel at 140, the dot at
/// 175, 87), -myschool-details (S2 in A: the panel at 114, the dot at 175, 84) and
/// -myschool-closed-under (S1 Under the controls, B: the panel at 134, the dot at 175, 85);
/// empty for a variant whose places are not written here. Besides the side controls' run:
///   - 40%, 75% (186.4, 508.5 pt: the empty panel below the season card, which ends at 427,
///     424 or 421, and left of the column at 382): `sheet` within 8;
///   - 25%, 94% (116.5, 637.3 pt): no tab bar along the bottom, `sheet` within 8;
///   - 90%, 66%: the side platter's glass, printed, as on the other screens;
///   - 90%, 40% (419.4, 271.2 pt, in the column between the status cluster and the tabs):
///     the column's ground, `mapBg` within 16 in A (the map runs under the column,
///     duo.css:16), `sheet` within 16 in B (the panel runs under it,
///     closed-myschool-under-light.html:80);
///   - the marker's core at 38%, 13% (177.1, 88.1 pt) in A and B, 38%, 12% (177.1, 81.4 pt)
///     with details: `closed` within 12;
///   - the season card at 6%, 54% (28.0, 366.1 pt: left of its text at 32, inside its
///     corner): `fill` within 8;
///   - the grabber (36 x 5, 7 below the panel's top, 173 to 209 across) at 41%, 22% in A
///     (191.1, 149.2 pt; 147 to 152), 41%, 18% with details (122.0 pt; 121 to 126) and
///     41%, 21% in B (142.4 pt; 141 to 146): `grab` within 16;
///   - in B only, 50%, 21% (233.0, 142.4 pt), where a grabber centred on the whole 466 pt
///     panel would be (215 to 251): `sheet` within 8 (in dark the panel's top gradient
///     there is within 6 of `sheet`).
/// Every line is judged: the places were measured on the Duo.
func duoMySchoolPoints(look dark: Bool, variant: String, page: Shade) -> [NamedPoint] {
    guard ["closed", "details", "closed-under"].contains(variant) else {
        return []
    }
    let details = variant == "details"
    let under = variant == "closed-under"
    let pick = { (light: Shade, darkShade: Shade) -> Shade in dark ? darkShade : light }
    let sheet = pick(Wanted.sheetLight, Wanted.sheetDark)
    let mapBg = pick(Wanted.mapBgLight, Wanted.mapBgDark)
    let marker = pick(Wanted.markerLight, Wanted.markerDark)
    let fill = pick(Wanted.fillLight, Wanted.fillDark)
    let grab = pick(Wanted.grabLight, Wanted.grabDark)
    var points = [
        NamedPoint(x: 40, y: 75, expect: .near(sheet, 8), what: "the panel's ground, sheet " + sheet.hex + ", left of the side controls", judged: true),
        NamedPoint(x: 25, y: 94, expect: .near(sheet, 8), what: "no tab bar along the bottom: the panel's sheet " + sheet.hex, judged: true),
        NamedPoint(x: 90, y: 66, expect: .awayFrom(page, 3), what: "the side tab platter's glass, at least 3 from the page", judged: false),
        under
            ? NamedPoint(x: 90, y: 40, expect: .near(sheet, 16), what: "Under the controls: the panel's sheet " + sheet.hex + " runs on under the side column", judged: true)
            : NamedPoint(x: 90, y: 40, expect: .near(mapBg, 16), what: "Beside the map: the map's ground, mapBg " + mapBg.hex + ", runs on under the side column", judged: true),
        NamedPoint(x: 38, y: details ? 12 : 13, expect: .near(marker, 12), what: "the closed marker's core " + marker.hex, judged: true),
        NamedPoint(x: 6, y: 54, expect: .near(fill, 8), what: "the season card, fill " + fill.hex, judged: true),
        NamedPoint(x: 41, y: details ? 18 : (under ? 21 : 22), expect: .near(grab, 16), what: "the grabber, grab " + grab.hex, judged: true),
    ]
    if under {
        points.append(NamedPoint(x: 50, y: 21, expect: .near(sheet, 8), what: "no grabber centred on the whole panel: the sheet " + sheet.hex, judged: true))
    }
    return points
}

func duoPoints(for rest: String) -> [NamedPoint] {
    guard let page = pageShade(for: rest) else {
        return []
    }
    let parts = rest.split(separator: "-").map { String($0) }
    let screen = parts.count > 1 ? parts[1] : ""
    let variant = parts.count > 2 ? parts[2...].joined(separator: "-") : ""
    let tabScreen = tabs.contains(where: { $0.screen == screen })
    var drawn = [NamedPoint(
        x: 90, y: 58, expect: .awayFrom(page.shade, 60),
        what: "the system's side controls drawn: an icon or the search glyph somewhere down to 96%", judged: true,
        runTo: 96, run: .someAwayFrom(page.shade, 60)
    )]
    if screen == "myschool" {
        let points = duoMySchoolPoints(look: page.shade.hex == Wanted.pageDark.hex, variant: variant, page: page.shade)
        return points.isEmpty ? [] : drawn + points
    }
    if screen != "search" {
        drawn.append(NamedPoint(
            x: 4, y: 4, expect: .awayFrom(page.shade, 60),
            what: "the page title drawn: ink somewhere across to x 40%", judged: true,
            runTo: 4, run: .someAwayFrom(page.shade, 60), runAcrossTo: 40
        ))
    }
    var points = [
        NamedPoint(x: 40, y: 60, expect: .near(page.shade, 8), what: page.name + ", the content left of the side controls", judged: true),
        NamedPoint(x: 25, y: 94, expect: .near(page.shade, 8), what: "no tab bar along the bottom: " + page.name, judged: tabScreen),
        NamedPoint(x: 90, y: 66, expect: .awayFrom(page.shade, 3), what: "the side tab platter's glass, at least 3 from the page", judged: false),
    ]
    if screen == "settings" {
        points.append(NamedPoint(
            x: 10, y: 31, expect: .awayFrom(page.shade, 60),
            what: "the Outside screen row: ink somewhere down to 50%", judged: true,
            runTo: 50, run: .someAwayFrom(page.shade, 60)
        ))
        let underChosen = variant == "under" || variant == "chose-under" || variant == "kept"
        let ringed = NamedPoint(
            x: underChosen ? 41 : 2, y: 42, expect: .awayFrom(page.shade, 60),
            what: (underChosen ? "Under the controls" : "Beside the map") + " chosen: its tile's ring", judged: true,
            runTo: 42, run: .someAwayFrom(page.shade, 60), runAcrossTo: underChosen ? 42 : 4
        )
        let plain = NamedPoint(
            x: underChosen ? 2 : 41, y: 42, expect: .near(page.shade, 12),
            what: (underChosen ? "Beside the map" : "Under the controls") + " not chosen: no ring, the page", judged: true,
            runTo: 42, run: .allNear(page.shade, 12), runAcrossTo: underChosen ? 4 : 42
        )
        points += [ringed, plain]
    }
    return drawn + points
}

/// The points to read in a picture, by the picture's name.
func namedPoints(for picture: String) -> [NamedPoint] {
    if picture.hasPrefix(duoClosed) {
        return duoPoints(for: String(picture.dropFirst(duoClosed.count)))
    }
    if picture == "dark-probe" {
        return [NamedPoint(x: 10, y: 25, expect: .near(Wanted.probeTeal, 8), what: "the Metal view's teal " + Wanted.probeTeal.hex, judged: false)]
    }
    guard let page = pageShade(for: picture) else {
        return []
    }
    let parts = picture.split(separator: "-").map { String($0) }
    let screen = parts.count > 1 ? parts[1] : ""
    if screen == "myschool" && parts.count > 2 {
        return mySchoolPoints(look: page.shade.hex == Wanted.pageDark.hex, variant: parts[2...].joined(separator: "-"))
    }
    var points = [NamedPoint(x: 50, y: 60, expect: .near(page.shade, 8), what: page.name, judged: true)]
    if tabs.contains(where: { $0.screen == screen }) {
        for tab in tabs {
            if tab.screen == screen {
                let what = "the chosen tab's capsule (" + tab.screen + "), at least 12 from the page"
                points.append(NamedPoint(x: tab.x, y: tabBarY, expect: .awayFrom(page.shade, 12), what: what, judged: placesMeasuredHere))
            } else {
                let what = "the bar's glass over " + tab.screen + ", within 10 of the page"
                points.append(NamedPoint(x: tab.x, y: tabBarY, expect: .near(page.shade, 10), what: what, judged: placesMeasuredHere))
            }
        }
    }
    if screen == "settings" {
        points.append(NamedPoint(x: 40, y: 22, expect: .near(Wanted.pageLight, 8), what: "the Light tile " + Wanted.pageLight.hex, judged: placesMeasuredHere))
        points.append(NamedPoint(x: 72, y: 22, expect: .near(Wanted.pageDark, 8), what: "the Dark tile " + Wanted.pageDark.hex, judged: placesMeasuredHere))
        // No Outside screen row on an iPhone: under the Appearance row, which ends at about
        // 30%, the page down x 10% to 47%, where the row's heading and tiles would be. On
        // light-settings-forced-row, where the tour shows the row on this iPhone, the same
        // run must fail: the negative sample that shows it can.
        let forced = picture == "light-settings-forced-row"
        points.append(NamedPoint(
            x: 10, y: 33, expect: .near(page.shade, 8),
            what: forced
                ? "the row forced on (a negative sample): the 'no Outside screen row' run must fail here"
                : "no Outside screen row: the page all the way down to 47%",
            judged: placesMeasuredHere,
            runTo: 47, run: .allNear(page.shade, 8), mustFail: forced
        ))
    }
    return points
}

func loadPicture(atPath path: String) -> CGImage? {
    let url = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else {
        return nil
    }
    return CGImageSourceCreateImageAtIndex(source, 0, nil)
}

/// A picture drawn once into an 8-bit sRGB bitmap, to read colors from. In that bitmap the
/// first row of bytes is the top row of the picture, and each pixel is four bytes: red,
/// green, blue, alpha.
struct Bitmap {
    let context: CGContext
    let width: Int
    let height: Int

    init?(_ picture: CGImage) {
        width = picture.width
        height = picture.height
        guard width > 0, height > 0 else {
            return nil
        }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else {
            return nil
        }
        let alphaLast: UInt32 = CGImageAlphaInfo.premultipliedLast.rawValue
        guard let made = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: space,
            bitmapInfo: alphaLast
        ) else {
            return nil
        }
        made.draw(picture, in: CGRect(x: 0, y: 0, width: width, height: height))
        context = made
    }

    func shade(xPercent: Int, yPercent: Int) -> Shade? {
        guard let memory = context.data else {
            return nil
        }
        let column = min(width - 1, max(0, width * xPercent / 100))
        let row = min(height - 1, max(0, height * yPercent / 100))
        let bytes = memory.assumingMemoryBound(to: UInt8.self)
        let offset = row * context.bytesPerRow + column * 4
        return Shade(red: Int(bytes[offset]), green: Int(bytes[offset + 1]), blue: Int(bytes[offset + 2]))
    }

    /// Reads every row of one column from one height to another (in percent of the
    /// picture). Says whether the run holds, and the shade that tells: the one farthest
    /// from the color.
    /// With `xToPercent`, every pixel of the box from x to that x as well (a run across
    /// when the two heights are one).
    func run(xPercent: Int, fromPercent: Int, toPercent: Int, run: Run, xToPercent: Int? = nil) -> (holds: Bool, telling: Shade)? {
        guard let memory = context.data else {
            return nil
        }
        let column = min(width - 1, max(0, width * xPercent / 100))
        let lastColumn = min(width - 1, max(0, width * (xToPercent ?? xPercent) / 100))
        let first = min(height - 1, max(0, height * fromPercent / 100))
        let last = min(height - 1, max(0, height * toPercent / 100))
        if last < first || lastColumn < column {
            return nil
        }
        let bytes = memory.assumingMemoryBound(to: UInt8.self)
        let color: Shade
        let tolerance: Int
        switch run {
        case .someAwayFrom(let other, let least):
            color = other
            tolerance = least
        case .allNear(let want, let most):
            color = want
            tolerance = most
        }
        var farthest = color
        var farthestDistance = -1
        for row in first...last {
            for across in column...lastColumn {
                let offset = row * context.bytesPerRow + across * 4
                let seen = Shade(red: Int(bytes[offset]), green: Int(bytes[offset + 1]), blue: Int(bytes[offset + 2]))
                let distance = seen.distance(to: color)
                if distance > farthestDistance {
                    farthestDistance = distance
                    farthest = seen
                }
            }
        }
        switch run {
        case .someAwayFrom:
            return (farthestDistance >= tolerance, farthest)
        case .allNear:
            return (farthestDistance <= tolerance, farthest)
        }
    }
}

extension Bitmap {
    /// The lightness of one pixel, as the eye weighs red, green and blue.
    func lightness(column: Int, row: Int) -> Double? {
        guard let memory = context.data, column >= 0, column < width, row >= 0, row < height else {
            return nil
        }
        let bytes = memory.assumingMemoryBound(to: UInt8.self)
        let offset = row * context.bytesPerRow + column * 4
        return 0.2126 * Double(bytes[offset]) + 0.7152 * Double(bytes[offset + 1]) + 0.0722 * Double(bytes[offset + 2])
    }

    /// The first and the last ink of a line of text in a box, in points: the columns whose
    /// ink covers at least half, between the box's ground (its middle shade) and its ink
    /// (its farthest shade from the ground), each edge found to a fraction of a pixel where
    /// the cover crosses one half. Nil when the box holds no ink or leaves the picture.
    func inkExtent(_ line: InkLine) -> (first: Double, last: Double)? {
        let scale = Double(width) / windowPointsAcross
        let top = Int((line.top * scale).rounded())
        let bottom = Int((line.bottom * scale).rounded())
        let left = Int((line.left * scale).rounded())
        let right = Int((line.right * scale).rounded())
        guard top >= 0, bottom <= height, top < bottom, left >= 1, right < width - 1, left < right else {
            return nil
        }
        var shades: [Double] = []
        for row in top..<bottom {
            for column in left..<right {
                if let seen = lightness(column: column, row: row) {
                    shades.append(seen)
                }
            }
        }
        shades.sort()
        guard !shades.isEmpty else {
            return nil
        }
        let ground = shades[shades.count / 2]
        let ink = ground > 128 ? shades[0] : shades[shades.count - 1]
        if abs(ground - ink) < 1 {
            return nil
        }
        // How much of a column the ink covers at its most, 0 to 1.
        func cover(_ column: Int) -> Double {
            var most = 0.0
            for row in top..<bottom {
                if let seen = lightness(column: column, row: row) {
                    most = max(most, (ground - seen) / (ground - ink))
                }
            }
            return most
        }
        var firstColumn: Int?
        var lastColumn: Int?
        for column in left..<right where cover(column) >= 0.5 {
            if firstColumn == nil {
                firstColumn = column
            }
            lastColumn = column
        }
        guard let firstInk = firstColumn, let lastInk = lastColumn else {
            return nil
        }
        let inside = cover(firstInk)
        let before = cover(firstInk - 1)
        let firstEdge = Double(firstInk) - (inside - 0.5) / max(0.000001, inside - before)
        let lastInside = cover(lastInk)
        let after = cover(lastInk + 1)
        let lastEdge = Double(lastInk + 1) - (0.5 - after) / max(0.000001, lastInside - after)
        return (firstEdge / scale, lastEdge / scale)
    }
}

/// Reads every picture under the folder. Returns the status to end with.
func readPictures(under folder: String) -> Int32 {
    let found = (try? FileManager.default.subpathsOfDirectory(atPath: folder)) ?? []
    let pictures = found.filter { $0.hasSuffix(".png") }.sorted()
    if pictures.isEmpty {
        print("no picture under " + folder)
        return 1
    }
    if placesMeasuredHere {
        print("the tab bar's and the tiles' places were measured on " + measuredOn + ": judged here")
    } else {
        print("the tab bar's and the tiles' places were measured on " + measuredOn + ", not on " + device + ": printed, not judged")
    }
    var wrong = 0
    for relative in pictures {
        let path = folder + "/" + relative
        let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        let points = namedPoints(for: name)
        if points.isEmpty {
            print(name + " has no named point WRONG")
            wrong += 1
            continue
        }
        guard let picture = loadPicture(atPath: path), let bitmap = Bitmap(picture) else {
            print(name + " could not be read WRONG")
            wrong += 1
            continue
        }
        for point in points {
            if let end = point.runTo, let run = point.run {
                var place = String(point.x) + "% " + String(point.y) + "-" + String(end) + "%"
                if let across = point.runAcrossTo {
                    place = "x " + String(point.x) + "-" + String(across) + "% y " + String(point.y) + "-" + String(end) + "%"
                }
                guard let found = bitmap.run(xPercent: point.x, fromPercent: point.y, toPercent: end, run: run, xToPercent: point.runAcrossTo) else {
                    print([name, place, "could not be read", "WRONG"].joined(separator: " "))
                    wrong += 1
                    continue
                }
                // A negative sample is right when the run does not hold.
                let right = point.mustFail ? !found.holds : found.holds
                var verdict = right ? "ok" : "WRONG"
                if !point.judged {
                    verdict = right ? "yes" : "no"
                } else if !right {
                    wrong += 1
                }
                print([name, place, found.telling.hex, point.what, verdict].joined(separator: " "))
                continue
            }
            let place = String(point.x) + "% " + String(point.y) + "%"
            guard let seen = bitmap.shade(xPercent: point.x, yPercent: point.y) else {
                print([name, place, "could not be read", "WRONG"].joined(separator: " "))
                wrong += 1
                continue
            }
            let holds = point.expect.holds(for: seen)
            var verdict = holds ? "ok" : "WRONG"
            if !point.judged {
                verdict = holds ? "yes" : "no"
            } else if !holds {
                wrong += 1
            }
            print([name, place, seen.hex, point.what, verdict].joined(separator: " "))
        }
        for line in inkLines(for: name) {
            let box = "ink x " + twoDecimals(line.left) + "-" + twoDecimals(line.right) + " y " + twoDecimals(line.top) + "-" + twoDecimals(line.bottom) + " pt"
            let judgedHere = placesMeasuredHere && line.judged
            guard let found = bitmap.inkExtent(line) else {
                print([name, box, "no ink found", line.what, judgedHere ? "WRONG" : "no"].joined(separator: " "))
                if judgedHere {
                    wrong += 1
                }
                continue
            }
            let holds = abs(found.first - line.first) <= line.firstWithin && abs(found.last - line.last) <= line.lastWithin
            var verdict = holds ? "ok" : "WRONG"
            if !judgedHere {
                verdict = holds ? "yes" : "no"
            } else if !holds {
                wrong += 1
            }
            let seen = twoDecimals(found.first) + " to " + twoDecimals(found.last) + " (" + twoDecimals(found.last - found.first) + " wide)"
            let want = "draft " + twoDecimals(line.first) + " to " + twoDecimals(line.last) + " within " + twoDecimals(line.firstWithin) + " and " + twoDecimals(line.lastWithin)
            print([name, box, seen, line.what + ",", want, verdict].joined(separator: " "))
        }
    }
    return wrong == 0 ? 0 : 1
}

let arguments = CommandLine.arguments
if arguments.count != 2 {
    print("usage: pixels <folder of pictures>")
    exit(3)
}
exit(readPictures(under: arguments[1]))
