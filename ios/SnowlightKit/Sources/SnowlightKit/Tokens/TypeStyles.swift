// The type styles of the design, as numbers.
//
// Each style is a size, a weight and, at 20 points and above and for `meta`, a tracking set
// by hand, the draft's own: the design is tighter than the system at display sizes. Every style grows with the reader's
// text size setting, anchored to one of the system's text styles.
//
// The My School styles (M1) are approved draft 3's, each with its line: the size, weight
// and tracking of its CSS rule, and its CSS line box. A line box is laid out as a browser
// lays it out: the line is that high at the standard text size, and the font's own height
// (its ascender to its descender) sits in its middle, so the baseline falls where the
// draft's does. The box grows with the text, in proportion. Text that wraps keeps the box
// between its lines. The figures are the draft's own: every My School line sets the CSS
// `font` shorthand, which resets the page's tabular-nums (CSS:117), so the draft's renderer
// computes font-variant-numeric `normal` for each of them and draws proportional figures
// (lead ruling R22, F1), and so does the app. The system font
// turns to its display cut at 20 points and up by itself, as the draft's two families do
// (CSS:59-60). Each style grows with the system style the build spec anchors it to (M1 6.2).
//
// The tracking of My School's styles is measured, not the CSS's number (lead ruling R21, B1).
// The draft was drawn in the static SF Pro Text and Display files through Chromium, which adds
// no tracking of its own, so there the CSS letter-spacing is the whole of it. iOS's system
// font adds its own tracking and optical size for each size, and .tracking() goes on top. So
// each style's tracking is the one value that makes its lines' ink as wide as the draft's: the
// draft's width from its own HTML rendered with the same words through the same renderer
// (premium/render.cjs, 402 x 874 at 3x, in Playwright 1.63.0's Chromium, the build that draws
// draft 3's pictures pixel for pixel), the app's from the simulator (iOS app run 43666798391,
// iPhone 17 Pro), measured on the fixture's words and on two more strings each, and the
// value that makes the worst width error smallest taken. The CSS value stays beside
// each one. The three styles whose lines carry figures (day, panelLine, counts) were fitted
// again with proportional figures (R22, F1): the simulator's lines of iOS app runs
// 43671333560 and 43675526799, the R21 strings and R22's own ("Posted 5:42 AM", "Posted
// 4:10 PM", "Tuesday, January 12", "Wednesday, January 13", "2 closed · 1 delayed ",
// "since Oct 27", and two-digit counts); the other five carry no figure and keep R21's
// values. At 20 and 22 points the letters, spaces and figures of the system font still
// differ one by one from the static Display cut once the whole line matches: the system's
// font, a ruled difference (R21).

import SwiftUI
import UIKit

/// The styles the shell uses. More arrive with the screens that need them.
enum TypeStyle {
    /// A page's title: 34 points, bold, tracking -0.45.
    case titlePage
    /// A section's heading: 20 points, bold, tracking -0.3.
    case titleSection
    /// Small supporting text: 15 points, regular, tracking -0.2 (draft 3's `.meta` and its
    /// section heading's grey line).
    case meta
    /// A row's second line, and a tile's label: 14 points, regular.
    case sub
    /// The same, stronger: 14 points, semibold.
    case subStrong

    // My School (M1): approved draft 3's styles, each with its line.

    /// The big status word: 68 points, bold, CSS tracking -2.6, line box 66 (H:22).
    case statusWord
    /// The school's name in the panel: 22 points, bold, CSS tracking -0.3, line box 27 (CSS:276).
    case schoolName
    /// The status day: 20 points, semibold, CSS tracking -0.25, line box 25 (H:28).
    case day
    /// A grey line of the panel: the district line (CSS:277), Posted (H:29) and the details
    /// line (H:33), each 15 points, regular, CSS tracking -0.2, line box 20.
    case panelLine
    /// A card's key, shown in capitals: 12 points, semibold, CSS tracking 0.6, line box 15 (H:39).
    case cardKey
    /// The season card's line: 17 points, semibold, CSS tracking -0.41, line box 22 (H:58).
    case counts
    /// The school's name in the callout over the map: 15 points, semibold, CSS tracking -0.24
    /// (CSS:240); its line box is the capsule's.
    case calloutName
    /// The callout's status chip: 13.5 points, bold, CSS tracking -0.1 (CSS:244); its line box
    /// is the chip's.
    case chip

    var size: CGFloat {
        switch self {
        case .titlePage:
            return 34
        case .titleSection:
            return 20
        case .meta:
            return 15
        case .sub, .subStrong:
            return 14
        case .statusWord:
            return 68 // H:22 font: 700 68px/66px
        case .schoolName:
            return 22 // CSS:276 font: 700 22px/27px
        case .day:
            return 20 // H:28 font: 600 20px/25px
        case .panelLine:
            return 15 // CSS:277, H:29, H:33 font: 400 15px/20px
        case .cardKey:
            return 12 // H:39 font: 600 12px/15px
        case .counts:
            return 17 // H:58 font: 600 17px/22px
        case .calloutName:
            return 15 // CSS:240 font: 600 15px/1
        case .chip:
            return 13.5 // CSS:244 font: 700 13.5px/1
        }
    }

    var weight: Font.Weight {
        switch self {
        case .titlePage, .titleSection:
            return .bold
        case .meta, .sub:
            return .regular
        case .subStrong:
            return .semibold
        case .statusWord, .schoolName, .chip:
            return .bold
        case .day, .cardKey, .counts, .calloutName:
            return .semibold
        case .panelLine:
            return .regular
        }
    }

    /// Tracking set by hand, or zero to leave it to the system. My School's are measured
    /// (R21, B1; R22, F1 for the three with figures): the CSS's value is written beside each.
    var tracking: CGFloat {
        switch self {
        case .titlePage:
            return -0.45
        case .titleSection:
            return -0.3
        case .meta:
            return -0.2
        case .sub, .subStrong:
            return 0
        case .statusWord:
            return -2.72 // R21 measured; CSS -2.6 (H:22 letter-spacing: -2.6px)
        case .schoolName:
            return -0.56 // R21 measured; CSS -0.3 (CSS:276)
        case .day:
            return -0.69 // R22 measured, proportional figures (R21: -0.85); CSS -0.25 (H:28)
        case .panelLine:
            return 0.05 // R22 measured, proportional figures (R21: 0.04); CSS -0.2 (CSS:277, H:29, H:33)
        case .cardKey:
            return 0.61 // R21 measured; CSS 0.6 (H:39)
        case .counts:
            return 0.04 // R22 measured, proportional figures (R21: -0.12); CSS -0.41 (H:58)
        case .calloutName:
            return 0.00 // R21 measured; CSS -0.24 (CSS:240)
        case .chip:
            return -0.04 // R21 measured; CSS -0.1 (CSS:244)
        }
    }

    /// The system text style this one grows with.
    var growsWith: Font.TextStyle {
        switch self {
        case .titlePage:
            return .largeTitle
        case .titleSection:
            return .title3
        case .meta:
            return .subheadline
        case .sub, .subStrong:
            return .footnote
        case .statusWord:
            return .largeTitle
        case .schoolName:
            return .title2
        case .day:
            return .title3
        case .panelLine, .calloutName:
            return .subheadline
        case .cardKey:
            return .caption
        case .counts:
            return .headline
        case .chip:
            return .footnote
        }
    }

    /// The CSS line box at the standard text size, or nil where the style sets none of its
    /// own (the shell's styles, and the callout's two, whose capsule sets the height).
    var lineBox: CGFloat? {
        switch self {
        case .titlePage, .titleSection, .meta, .sub, .subStrong, .calloutName, .chip:
            return nil
        case .statusWord:
            return 66 // H:22
        case .schoolName:
            return 27 // CSS:276
        case .day:
            return 25 // H:28
        case .panelLine:
            return 20 // CSS:277, H:29, H:33
        case .cardKey:
            return 15 // H:39
        case .counts:
            return 22 // H:58
        }
    }

    /// The same weight, as UIKit names it, to read the font's height.
    var fontWeight: UIFont.Weight {
        switch weight {
        case .bold:
            return UIFont.Weight.bold
        case .semibold:
            return UIFont.Weight.semibold
        default:
            return UIFont.Weight.regular
        }
    }
}

/// Sets a type style on whatever text is inside.
struct TypeStyleModifier: ViewModifier {
    private let style: TypeStyle
    @ScaledMetric private var size: CGFloat

    init(_ style: TypeStyle) {
        self.style = style
        _size = ScaledMetric(wrappedValue: style.size, relativeTo: style.growsWith)
    }

    func body(content: Content) -> some View {
        if let box = style.lineBox {
            // The line box of the draft at this size: half of what the box has over the
            // font's own height above the line, half below, and the same between lines.
            let font = UIFont.systemFont(ofSize: size, weight: style.fontWeight)
            let extra = box * size / style.size - (font.ascender - font.descender)
            content
                .font(.system(size: size, weight: style.weight))
                .tracking(style.tracking)
                .lineSpacing(max(0, extra))
                .padding(.vertical, extra / 2)
        } else if style.tracking == 0 {
            content.font(.system(size: size, weight: style.weight))
        } else {
            content
                .font(.system(size: size, weight: style.weight))
                .tracking(style.tracking)
        }
    }
}

extension View {
    /// Draws the text inside in one of the design's type styles.
    func typeStyle(_ style: TypeStyle) -> some View {
        modifier(TypeStyleModifier(style))
    }
}
