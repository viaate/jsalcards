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
//     Dark tile (72%, 22%), the dark page color in either look;
//   - search: the page point only (iOS folds the bar into one button there);
//   - the probe: 10%, 25% is the teal the Metal view is cleared to.
//   - the iPhone Duo's closed pictures (duo-closed-<look>-<screen>): their own points,
//     measured on the Duo (see duoPoints below).
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

struct NamedPoint {
    /// Percent from the left.
    let x: Int
    /// Percent from the top.
    let y: Int
    let expect: Expect
    let what: String
    /// False: printed as yes or no, never a failure.
    let judged: Bool
}

/// The colors the named points are held to. The two page colors are the app's `page`
/// token, light and dark; the teal is what the Metal probe clears its view to.
enum Wanted {
    static let pageLight = Shade(red: 0xff, green: 0xff, blue: 0xff)
    static let pageDark = Shade(red: 0x13, green: 0x14, blue: 0x18)
    static let probeTeal = Shade(red: 0x12, green: 0xa5, blue: 0x94)
}

/// The device the tab and tile places were measured on.
let measuredOn = "iPhone 17 Pro"
let device = ProcessInfo.processInfo.environment["SIM_DEVICE"] ?? measuredOn
let placesMeasuredHere = device == measuredOn

/// The four tabs in the order of the bar, each with the x of its point.
let tabs: [(screen: String, x: Int)] = [("myschool", 10), ("map", 28), ("callit", 45), ("settings", 61)]
let tabBarY = 94

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
let duoClosed = "duo-closed-"

func duoPoints(for rest: String) -> [NamedPoint] {
    guard let page = pageShade(for: rest) else {
        return []
    }
    let parts = rest.split(separator: "-").map { String($0) }
    let screen = parts.count > 1 ? parts[1] : ""
    let tabScreen = tabs.contains(where: { $0.screen == screen })
    return [
        NamedPoint(x: 40, y: 60, expect: .near(page.shade, 8), what: page.name + ", the content left of the side controls", judged: true),
        NamedPoint(x: 25, y: 94, expect: .near(page.shade, 8), what: "no tab bar along the bottom: " + page.name, judged: tabScreen),
        NamedPoint(x: 90, y: 66, expect: .awayFrom(page.shade, 3), what: "the side tab platter's glass, at least 3 from the page", judged: false),
    ]
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
    var points = [NamedPoint(x: 50, y: 60, expect: .near(page.shade, 8), what: page.name, judged: true)]
    let parts = picture.split(separator: "-").map { String($0) }
    let screen = parts.count > 1 ? parts[1] : ""
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
    }
    return wrong == 0 ? 0 : 1
}

let arguments = CommandLine.arguments
if arguments.count != 2 {
    print("usage: pixels <folder of pictures>")
    exit(3)
}
exit(readPictures(under: arguments[1]))
