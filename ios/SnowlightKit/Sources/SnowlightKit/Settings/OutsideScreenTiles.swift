// The two Outside screen tiles: Beside the map, Under the controls. Shown only on an
// iPhone Duo (the owner's ruling of Nov 11, 2026; the words approved on Nov 12).
//
// Drawn as the appearance tiles are (the same `SettingsTile`: frame, ring, tick, label).
// Each picture is the closed Duo seen whole, after the approved mock-up's tile (duo.js,
// layoutThumb): a ground, the school's sheet with its bold title bar and two grey lines,
// and on the right the system's column of controls, the time as a short bold bar and one
// round control. A, Beside the map: the sheet stops at the column, with a rounded corner,
// and the ground runs on down the column beside it. B, Under the controls: the sheet runs
// on to the right edge, and the round control sits on it. The pictures follow the app's
// look, and every color is a token.
//
// The mock-up's tile is drawn in the units of draft 3's appearance tile (110 x 68, filled
// across and cut top and bottom), at the scale of the appearance row above, so both rows
// are drawn at one scale: the same here. Lengths across are kept as fractions of the
// whole closed display, so nothing here names the display's size.

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

    /// Where the system's column begins, across the closed display (the mock-up's 373 of
    /// 457 points), and the line its controls stand on (408.8 of 457).
    private static let columnStart: CGFloat = 0.8162
    private static let controlLine: CGFloat = 0.8945

    var body: some View {
        GeometryReader { box in
            picture(in: box.size)
        }
    }

    private func picture(in size: CGSize) -> some View {
        let wide = size.width
        // The appearance tiles' width, in this row's room: three tiles and two gaps of 12
        // across the same column as these two tiles and their one gap.
        let appearanceTile = (2 * wide - 12) / 3
        let unit = max(appearanceTile / 110, size.height / 68)
        let cut = (68 * unit - size.height) / 2
        let down = { (units: CGFloat) -> CGFloat in units * unit - cut }
        let isBeside = choice == OutsideScreenChoice.besideTheMap
        let sheetWide = isBeside ? wide * LayoutSwatch.columnStart : wide
        let line = wide * LayoutSwatch.controlLine
        let isDark = scheme == .dark
        let ground = isDark ? Color.token(.page, in: .dark) : Color.token(.fill2, in: .light)

        return ZStack(alignment: .topLeading) {
            ground
            // The sheet: top at 24 units, corners of 10, running off the bottom.
            RoundedRectangle(cornerRadius: 10 * unit, style: .continuous)
                .fill(Color.token(.sheet))
                .frame(width: sheetWide, height: 48 * unit)
                .offset(x: 0, y: down(24))
            if isDark {
                // In the dark look, the sheet's faint rim: along its top and, where it stops
                // at the column, round its corner and down its side.
                SheetRim(top: down(24), right: sheetWide, radius: 10 * unit, downTheSide: isBeside)
                    .stroke(Color.token(.ink).opacity(isBeside ? 0.3 : 0.16), lineWidth: 0.7 * unit)
            }
            // The sheet's bold title bar and its two grey lines.
            bar(Color.token(.ink), x: 10 * unit, y: down(33), wide: 34 * unit, high: 7 * unit)
            bar(Color.token(.fill2), x: 10 * unit, y: down(46), wide: 58 * unit, high: 4 * unit)
            bar(Color.token(.fill), x: 10 * unit, y: down(55), wide: 44 * unit, high: 4 * unit)
            // The column: the time as a short bold bar, and one round control.
            bar(Color.token(.ink), x: line - 7 * unit, y: down(8), wide: 14 * unit, high: 6 * unit)
            Circle()
                .fill(isDark ? Color.token(.ink).opacity(0.12) : Color.token(.sheet))
                .overlay {
                    Circle().stroke(Color.token(.ink).opacity(isDark ? 0.22 : 0.13), lineWidth: 0.7 * unit)
                }
                .frame(width: 18 * unit, height: 18 * unit)
                .offset(x: line - 9 * unit, y: down(33))
        }
        .frame(width: wide, height: size.height, alignment: .topLeading)
    }

    /// A rounded bar.
    private func bar(_ color: Color, x: CGFloat, y: CGFloat, wide: CGFloat, high: CGFloat) -> some View {
        Capsule()
            .fill(color)
            .frame(width: wide, height: high)
            .offset(x: x, y: y)
    }
}

/// The top edge of a sheet, rounded at both ends, and, when asked, down its right side.
struct SheetRim: Shape {
    let top: CGFloat
    let right: CGFloat
    let radius: CGFloat
    let downTheSide: Bool

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: 0, y: top + radius))
        path.addArc(tangent1End: CGPoint(x: 0, y: top), tangent2End: CGPoint(x: radius, y: top), radius: radius)
        path.addLine(to: CGPoint(x: right - radius, y: top))
        path.addArc(tangent1End: CGPoint(x: right, y: top), tangent2End: CGPoint(x: right, y: top + radius), radius: radius)
        if downTheSide {
            path.addLine(to: CGPoint(x: right, y: rect.maxY + 2))
        }
        return path
    }
}
