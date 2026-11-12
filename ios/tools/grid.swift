// grid.swift <columns> <picture.png>...
// grid.swift band <x0> <y0> <x1> <y1> <step> <picture.png>...
// grid.swift black <x0> <y0> <x1> <y1> <picture.png>
//
// Prints each picture as a coarse grid of colors, one line per row of cells, so that a
// picture which stays on the runner can still be looked at from the job's log alone:
//
//     grid <picture> <width> x <height> px, <columns> x <rows> cells
//     grid <picture> <row>: rrggbb rrggbb ...
//
// With band, it prints one part of each picture, from pixel x0, y0 up to x1, y1, one cell
// every step pixels (on a 3x screen a step of 3 is one cell per point), under the name
// <picture>-band, in the same lines: a close look at one part of a picture, at the
// picture's own scale.
//
// With black, it prints how many pixels of that part of the picture are black (no channel
// above 8): "black <picture> <count> of <pixels>". The Duo's tour uses it to see whether
// the system drew something black where the Dynamic Island is.
//
// Each cell's color is the one pixel at its centre (no blending, so a thin line can fall
// between two cells). The rows are as many as keep the cells square. Rows count from the
// top, columns from the left. It judges nothing: it ends with status 1 only when a picture
// cannot be read. A plain script for the Mac runner: CoreGraphics and ImageIO only.

import CoreGraphics
import Foundation
import ImageIO

func twoHexDigits(_ value: UInt8) -> String {
    let digits = Array("0123456789abcdef")
    return String(digits[Int(value) / 16]) + String(digits[Int(value) % 16])
}

/// A picture drawn once into an 8-bit sRGB bitmap. In that bitmap the first row of bytes
/// is the top row of the picture, and each pixel is four bytes: red, green, blue, alpha.
struct Bitmap {
    let context: CGContext
    let width: Int
    let height: Int

    init?(path: String) {
        let url = URL(fileURLWithPath: path)
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let picture = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            return nil
        }
        width = picture.width
        height = picture.height
        guard width > 0, height > 0, let space = CGColorSpace(name: CGColorSpace.sRGB) else {
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
}

func printGrid(of path: String, columns: Int) -> Bool {
    let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
    guard let bitmap = Bitmap(path: path), let memory = bitmap.context.data else {
        print("grid \(name) could not be read")
        return false
    }
    let width = bitmap.width
    let height = bitmap.height
    let rows = max(1, Int((Double(columns) * Double(height) / Double(width)).rounded()))
    print("grid \(name) \(width) x \(height) px, \(columns) x \(rows) cells")
    let bytes = memory.assumingMemoryBound(to: UInt8.self)
    let rowBytes = bitmap.context.bytesPerRow
    for row in 0..<rows {
        let y = min(height - 1, (2 * row + 1) * height / (2 * rows))
        var line = "grid \(name) \(row):"
        for column in 0..<columns {
            let x = min(width - 1, (2 * column + 1) * width / (2 * columns))
            let offset = y * rowBytes + x * 4
            let red = twoHexDigits(bytes[offset])
            let green = twoHexDigits(bytes[offset + 1])
            let blue = twoHexDigits(bytes[offset + 2])
            line += " \(red)\(green)\(blue)"
        }
        print(line)
    }
    return true
}

func printBand(of path: String, from: (x: Int, y: Int), to: (x: Int, y: Int), step: Int) -> Bool {
    let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent + "-band"
    guard let bitmap = Bitmap(path: path), let memory = bitmap.context.data else {
        print("grid \(name) could not be read")
        return false
    }
    let left = max(0, min(bitmap.width - 1, from.x))
    let top = max(0, min(bitmap.height - 1, from.y))
    let right = max(left + 1, min(bitmap.width, to.x))
    let bottom = max(top + 1, min(bitmap.height, to.y))
    let columns = (right - left + step - 1) / step
    let rows = (bottom - top + step - 1) / step
    print("grid \(name) \(bitmap.width) x \(bitmap.height) px, from \(left), \(top) to \(right), \(bottom), one cell every \(step) px, \(columns) x \(rows) cells")
    let bytes = memory.assumingMemoryBound(to: UInt8.self)
    let rowBytes = bitmap.context.bytesPerRow
    for row in 0..<rows {
        let y = min(bottom - 1, top + row * step + step / 2)
        var line = "grid \(name) \(row):"
        for column in 0..<columns {
            let x = min(right - 1, left + column * step + step / 2)
            let offset = y * rowBytes + x * 4
            line += " " + twoHexDigits(bytes[offset]) + twoHexDigits(bytes[offset + 1]) + twoHexDigits(bytes[offset + 2])
        }
        print(line)
    }
    return true
}

func countBlack(in path: String, from: (x: Int, y: Int), to: (x: Int, y: Int)) -> Bool {
    let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
    guard let bitmap = Bitmap(path: path), let memory = bitmap.context.data else {
        print("black \(name) could not be read")
        return false
    }
    let left = max(0, min(bitmap.width, from.x))
    let top = max(0, min(bitmap.height, from.y))
    let right = max(left, min(bitmap.width, to.x))
    let bottom = max(top, min(bitmap.height, to.y))
    let bytes = memory.assumingMemoryBound(to: UInt8.self)
    let rowBytes = bitmap.context.bytesPerRow
    var count = 0
    for y in top..<bottom {
        for x in left..<right {
            let offset = y * rowBytes + x * 4
            if bytes[offset] <= 8 && bytes[offset + 1] <= 8 && bytes[offset + 2] <= 8 {
                count += 1
            }
        }
    }
    print("black \(name) \(count) of \((right - left) * (bottom - top))")
    return true
}

let arguments = CommandLine.arguments
if arguments.count >= 7, arguments[1] == "black" || arguments[1] == "band" {
    let numbers = arguments[2..<(arguments[1] == "band" ? 7 : 6)].compactMap { Int($0) }
    let wanted = arguments[1] == "band" ? 5 : 4
    guard numbers.count == wanted, numbers.allSatisfy({ $0 >= 0 }), arguments.count > wanted + 2 else {
        print("usage: grid band <x0> <y0> <x1> <y1> <step> <picture.png>... | grid black <x0> <y0> <x1> <y1> <picture.png>")
        exit(3)
    }
    let from = (x: numbers[0], y: numbers[1])
    let to = (x: numbers[2], y: numbers[3])
    var read = true
    for path in arguments.dropFirst(wanted + 2) {
        let done = arguments[1] == "band"
            ? printBand(of: path, from: from, to: to, step: max(1, numbers[4]))
            : countBlack(in: path, from: from, to: to)
        if !done {
            read = false
        }
    }
    exit(read ? 0 : 1)
}
guard arguments.count >= 3, let columns = Int(arguments[1]), columns > 0, columns <= 200 else {
    print("usage: grid <columns, 1 to 200> <picture.png>...")
    exit(3)
}
var allRead = true
for path in arguments.dropFirst(2) {
    if !printGrid(of: path, columns: columns) {
        allRead = false
    }
}
exit(allRead ? 0 : 1)
