// The two Outside screen tiles: Beside the map, Under the controls. Shown only on an
// iPhone Duo (the owner's ruling of Nov 11, 2026; the words approved on Nov 12).
//
// Drawn as the appearance tiles are (the same `SettingsTile`: frame, ring, tick, label).
// Each picture is the approved mock-up's tile, band for band (design/app/duo, duo.js
// layoutThumb, which keeps draft 3's thumb colors): the closed Duo seen whole, a map (its
// ground, a lake with its shore at the top right running down the side column, two roads,
// the school's dot), the school's sheet with its bold title bar and two grey lines, and on
// the right the system's column of controls, the time as a short bold bar and one round
// glass control. A, Beside the map: the sheet stops at the column, and the map runs on
// down the column beside it. B, Under the controls: the sheet runs on to the right edge,
// and the round control sits on it. Every color is a token (the thumb tokens hold the
// mock-up's colors); the pictures follow the app's look.
//
// The mock-up draws its tile in units: 68 high and as wide as the tile is in the units of
// draft 3's appearance tile (110 x 68, filled across and cut evenly top and bottom), so
// both rows are drawn at one scale. The same here. Lengths across are fractions of the
// whole closed display (the column begins at 373 and the controls stand on 408.8 of the
// mock-up's 457 points), so nothing here names the display's size.

import SnowlightCore
import SwiftUI

struct OutsideScreenTiles: View {
    let options: [OutsideScreenOption]
    /// Called with the tile that was tapped.
    let choose: (OutsideScreenChoice) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ForEach(options, id: \.choice) { option in
                Button {
                    choose(option.choice)
                } label: {
                    SettingsTile(label: option.label, isChosen: option.isChosen) {
                        LayoutSwatch(choice: option.choice)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(option.isChosen ? .isSelected : [])
            }
        }
    }
}

/// A small picture of the closed Duo in one layout.
struct LayoutSwatch: View {
    let choice: OutsideScreenChoice

    @Environment(\.colorScheme) private var scheme

    /// Where the system's column begins, across the closed display, and the line its
    /// controls stand on.
    private static let columnStart: CGFloat = 0.81619
    private static let controlLine: CGFloat = 0.89453

    var body: some View {
        GeometryReader { box in
            picture(in: box.size)
        }
    }

    private func picture(in size: CGSize) -> some View {
        // The appearance tiles' width, in this row's room: three tiles and two gaps of 12
        // across the same column as these two tiles and their one gap.
        let appearanceTile = (2 * size.width - 12) / 3
        // Never zero, so a first pass with no room yet draws nothing rather than dividing by it.
        let unit = max(appearanceTile / 110, size.height / 68, 0.01)
        let cut = (68 * unit - size.height) / 2
        let units = ThumbUnits(wide: size.width / unit, toPoints: CGAffineTransform(a: unit, b: 0, c: 0, d: unit, tx: 0, ty: -cut))
        let isBeside = choice == OutsideScreenChoice.besideTheMap
        let isDark = scheme == .dark
        let sx = units.wide * LayoutSwatch.columnStart
        let cx = units.wide * LayoutSwatch.controlLine
        let sheetWide = isBeside ? sx : units.wide
        let white = Color.token(.page, in: .light)

        return ZStack(alignment: .topLeading) {
            // The map: its ground, the lake, two roads and the school's dot.
            ZStack(alignment: .topLeading) {
                Color.token(.thumbGround)
                units.lake(sx: sx, cx: cx).fill(Color.token(.thumbWater))
                units.lake(sx: sx, cx: cx).stroke(Color.token(.thumbShore), lineWidth: 0.7 * unit)
                ThumbRoad(path: units.firstRoad(), unit: unit, isDark: isDark)
                ThumbRoad(path: units.secondRoad(sx: sx), unit: unit, isDark: isDark)
                if isDark {
                    units.circle(x: 52, y: 13, radius: 9).fill(Color.token(.thumbDot).opacity(0.22))
                    units.circle(x: 52, y: 13, radius: 5).fill(Color.token(.thumbDot).opacity(0.35))
                    units.circle(x: 52, y: 13, radius: 2.6).fill(Color.token(.thumbDotCore))
                } else {
                    units.circle(x: 52, y: 13, radius: 6.5).fill(Color.token(.thumbDot).opacity(0.22))
                    units.circle(x: 52, y: 13, radius: 4.1).fill(Color.token(.thumbDotCore))
                    units.circle(x: 52, y: 13, radius: 2.8).fill(Color.token(.thumbDot))
                }
            }
            // The sheet: top at 24, corners of 10, running off the bottom; A stops at the
            // column, B runs to the edge. In the dark look its faint rim: along its top and,
            // where it stops at the column, round its corner and down its side. Then its
            // bold title bar and its two grey lines.
            ZStack(alignment: .topLeading) {
                units.rounded(x: 0, y: 24, wide: sheetWide, high: 48, radius: 10).fill(Color.token(.thumbSheet))
                if isDark {
                    units.rim(right: sheetWide, downTheSide: isBeside)
                        .stroke(white.opacity(isBeside ? 0.3 : 0.16), lineWidth: 0.7 * unit)
                }
                units.rounded(x: 10, y: 33, wide: 34, high: 7, radius: 3.5).fill(Color.token(.thumbTitle))
                units.rounded(x: 10, y: 46, wide: 58, high: 4, radius: 2).fill(Color.token(.thumbLine))
                units.rounded(x: 10, y: 55, wide: 44, high: 4, radius: 2).fill(Color.token(.thumbLine2))
            }
            // The column: the time as a short bold bar, and one plain glass circle.
            ZStack(alignment: .topLeading) {
                units.rounded(x: cx - 7, y: 8, wide: 14, high: 6, radius: 3).fill(Color.token(.thumbTitle))
                if isDark {
                    units.circle(x: cx, y: 42, radius: 9).fill(white.opacity(0.12))
                    units.circle(x: cx, y: 42, radius: 9).stroke(white.opacity(0.22), lineWidth: 0.7 * unit)
                } else {
                    units.circle(x: cx, y: 42, radius: 9).fill(white.opacity(isBeside ? 0.9 : 1))
                    units.circle(x: cx, y: 42, radius: 9).stroke(Color.token(.ink, in: .light).opacity(0.13), lineWidth: 0.7 * unit)
                }
            }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
    }
}

/// A road of the map picture: in the light look a white line on a darker edge, in the
/// dark look one grey line.
struct ThumbRoad: View {
    let path: Path
    let unit: CGFloat
    let isDark: Bool

    var body: some View {
        if isDark {
            path.stroke(Color.token(.thumbRoad), lineWidth: 1.5 * unit)
        } else {
            ZStack {
                path.stroke(Color.token(.thumbRoadEdge), lineWidth: 3 * unit)
                path.stroke(Color.token(.thumbRoad), lineWidth: 1.9 * unit)
            }
        }
    }
}

/// The mock-up tile's units: 68 high and `wide` across, turned into the tile's points.
/// Each call gives a path already in points.
struct ThumbUnits {
    let wide: CGFloat
    let toPoints: CGAffineTransform

    /// The lake: draft 3's shore at the top right, then down the right half of the column.
    func lake(sx: CGFloat, cx: CGFloat) -> Path {
        let lx = sx - 26
        var path = Path()
        path.move(to: CGPoint(x: lx, y: -2))
        path.addCurve(to: CGPoint(x: lx + 12, y: 9), control1: CGPoint(x: lx + 2, y: 3), control2: CGPoint(x: lx + 11, y: 3))
        path.addCurve(to: CGPoint(x: lx + 12, y: 20), control1: CGPoint(x: lx + 13, y: 15), control2: CGPoint(x: lx + 7, y: 16))
        path.addCurve(to: CGPoint(x: cx + 1, y: 32), control1: CGPoint(x: sx - 6, y: 24), control2: CGPoint(x: cx - 1, y: 24))
        path.addCurve(to: CGPoint(x: cx + 2, y: 50), control1: CGPoint(x: cx + 3, y: 40), control2: CGPoint(x: cx - 3, y: 44))
        path.addCurve(to: CGPoint(x: cx + 2, y: 70), control1: CGPoint(x: cx + 7, y: 56), control2: CGPoint(x: cx + 5, y: 62))
        path.addLine(to: CGPoint(x: wide + 2, y: 70))
        path.addLine(to: CGPoint(x: wide + 2, y: -2))
        path.closeSubpath()
        return path.applying(toPoints)
    }

    /// The road across the top, under the school's dot.
    func firstRoad() -> Path {
        var path = Path()
        path.move(to: CGPoint(x: -4, y: 16))
        path.addCurve(to: CGPoint(x: 52, y: 14), control1: CGPoint(x: 18, y: 12), control2: CGPoint(x: 30, y: 22))
        path.addCurve(to: CGPoint(x: wide + 4, y: 9), control1: CGPoint(x: 74, y: 6), control2: CGPoint(x: wide * 0.72, y: 4))
        return path.applying(toPoints)
    }

    /// The road that turns down the column's left edge.
    func secondRoad(sx: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: sx - 12, y: 15))
        path.addCurve(to: CGPoint(x: sx + 4.5, y: 46), control1: CGPoint(x: sx - 2, y: 24), control2: CGPoint(x: sx + 4, y: 34))
        path.addCurve(to: CGPoint(x: sx + 6, y: 72), control1: CGPoint(x: sx + 5, y: 58), control2: CGPoint(x: sx + 3, y: 62))
        return path.applying(toPoints)
    }

    func circle(x: CGFloat, y: CGFloat, radius: CGFloat) -> Path {
        Path(ellipseIn: CGRect(x: x - radius, y: y - radius, width: 2 * radius, height: 2 * radius)).applying(toPoints)
    }

    func rounded(x: CGFloat, y: CGFloat, wide: CGFloat, high: CGFloat, radius: CGFloat) -> Path {
        Path(roundedRect: CGRect(x: x, y: y, width: wide, height: high), cornerRadius: radius, style: .circular).applying(toPoints)
    }

    /// The dark sheet's rim: from 34 up round a corner of 10 to the top at 24, along it,
    /// round the far corner and, when asked, down the sheet's side to the bottom.
    func rim(right: CGFloat, downTheSide: Bool) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: 0, y: 34))
        path.addArc(tangent1End: CGPoint(x: 0, y: 24), tangent2End: CGPoint(x: 10, y: 24), radius: 10)
        path.addLine(to: CGPoint(x: right - 10, y: 24))
        path.addArc(tangent1End: CGPoint(x: right, y: 24), tangent2End: CGPoint(x: right, y: 34), radius: 10)
        if downTheSide {
            path.addLine(to: CGPoint(x: right, y: 70))
        }
        return path.applying(toPoints)
    }
}
