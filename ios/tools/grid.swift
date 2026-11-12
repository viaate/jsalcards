// grid.swift <columns> <picture.png>...
//
// Prints each picture as a coarse grid of colors, one line per row of cells, so that a
// picture which stays on the runner can still be looked at from the job's log alone:
//
//     grid <picture> <width> x <height> px, <columns> x <rows> cells
//     grid <picture> <row>: rrggbb rrggbb ...
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

let arguments = CommandLine.arguments
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
