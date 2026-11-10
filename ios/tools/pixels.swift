// pixels.swift <folder>
//
// Reads the color at one named point in each picture of the tour and prints it, so that
// whoever can read the job's log can tell a light screen from a dark one without opening
// a picture. A plain script for the Mac runner: CoreGraphics and ImageIO only.
//
// For every PNG under the folder it prints one line:
//
//     <picture> <x%> <y%> #rrggbb <what it should be> ok|WRONG
//
// with x from the left and y from the top. It ends with status 1 if any line says WRONG,
// if a picture cannot be read or has no named point, or if there is no picture at all.
// The one exception is the Metal probe: its line ends in yes or no and never fails the
// run, because it reports a fact about the machine.
//
// This samples a handful of named points and nothing more. It does not compare pictures,
// and it cannot judge glass: that stays for a person's eyes.

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

    /// A color matches within 8 per channel.
    func isNear(_ other: Shade) -> Bool {
        let redNear = abs(red - other.red) <= 8
        let greenNear = abs(green - other.green) <= 8
        let blueNear = abs(blue - other.blue) <= 8
        return redNear && greenNear && blueNear
    }
}

struct NamedPoint {
    /// Percent from the left.
    let x: Int
    /// Percent from the top.
    let y: Int
    let want: Shade
    let what: String
    /// False for the probe: printed as yes or no, never a failure.
    let judged: Bool
}

/// The colors the named points are held to. The two page colors are the app's `page`
/// token, light and dark; the teal is what the Metal probe clears its view to.
enum Wanted {
    static let pageLight = Shade(red: 0xff, green: 0xff, blue: 0xff)
    static let pageDark = Shade(red: 0x13, green: 0x14, blue: 0x18)
    static let probeTeal = Shade(red: 0x12, green: 0xa5, blue: 0x94)
}

func lightPage() -> NamedPoint {
    NamedPoint(x: 50, y: 60, want: Wanted.pageLight, what: "page light " + Wanted.pageLight.hex, judged: true)
}

func darkPage() -> NamedPoint {
    NamedPoint(x: 50, y: 60, want: Wanted.pageDark, what: "page dark " + Wanted.pageDark.hex, judged: true)
}

func probePoint() -> NamedPoint {
    NamedPoint(x: 10, y: 25, want: Wanted.probeTeal, what: "the Metal view's teal " + Wanted.probeTeal.hex, judged: false)
}

/// The point to read in a picture, by the picture's name. The exact names come first:
/// they are the pictures whose look is not the one their name begins with.
func namedPoint(for picture: String) -> NamedPoint? {
    if picture == "light-settings-forced-dark" {
        return darkPage()
    }
    if picture == "dark-settings-forced-light" {
        return lightPage()
    }
    if picture == "light-settings-dark-then-system" {
        return lightPage()
    }
    if picture == "dark-probe" {
        return probePoint()
    }
    if picture.hasPrefix("light-") {
        return lightPage()
    }
    if picture.hasPrefix("dark-") {
        return darkPage()
    }
    return nil
}

func loadPicture(atPath path: String) -> CGImage? {
    let url = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else {
        return nil
    }
    return CGImageSourceCreateImageAtIndex(source, 0, nil)
}

/// The color at a point of a picture, after drawing the picture into an 8-bit sRGB
/// bitmap. In that bitmap the first row of bytes is the top row of the picture, and each
/// pixel is four bytes: red, green, blue, alpha.
func shade(in picture: CGImage, xPercent: Int, yPercent: Int) -> Shade? {
    let width = picture.width
    let height = picture.height
    guard width > 0, height > 0 else {
        return nil
    }
    guard let space = CGColorSpace(name: CGColorSpace.sRGB) else {
        return nil
    }
    let alphaLast: UInt32 = CGImageAlphaInfo.premultipliedLast.rawValue
    guard let bitmap = CGContext(
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
    bitmap.draw(picture, in: CGRect(x: 0, y: 0, width: width, height: height))
    guard let memory = bitmap.data else {
        return nil
    }
    let column = min(width - 1, max(0, width * xPercent / 100))
    let row = min(height - 1, max(0, height * yPercent / 100))
    let bytes = memory.assumingMemoryBound(to: UInt8.self)
    let offset = row * bitmap.bytesPerRow + column * 4
    return Shade(red: Int(bytes[offset]), green: Int(bytes[offset + 1]), blue: Int(bytes[offset + 2]))
}

/// Reads every picture under the folder. Returns the status to end with.
func readPictures(under folder: String) -> Int32 {
    let found = (try? FileManager.default.subpathsOfDirectory(atPath: folder)) ?? []
    let pictures = found.filter { $0.hasSuffix(".png") }.sorted()
    if pictures.isEmpty {
        print("no picture under " + folder)
        return 1
    }
    var wrong = 0
    for relative in pictures {
        let path = folder + "/" + relative
        let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        guard let point = namedPoint(for: name) else {
            print(name + " has no named point WRONG")
            wrong += 1
            continue
        }
        let place = String(point.x) + "% " + String(point.y) + "%"
        guard let picture = loadPicture(atPath: path),
              let seen = shade(in: picture, xPercent: point.x, yPercent: point.y) else {
            print([name, place, "could not be read", "WRONG"].joined(separator: " "))
            wrong += 1
            continue
        }
        let matches = seen.isNear(point.want)
        var verdict = matches ? "ok" : "WRONG"
        if !point.judged {
            verdict = matches ? "yes" : "no"
        } else if !matches {
            wrong += 1
        }
        print([name, place, seen.hex, point.what, verdict].joined(separator: " "))
    }
    return wrong == 0 ? 0 : 1
}

let arguments = CommandLine.arguments
if arguments.count != 2 {
    print("usage: pixels <folder of pictures>")
    exit(3)
}
exit(readPictures(under: arguments[1]))
