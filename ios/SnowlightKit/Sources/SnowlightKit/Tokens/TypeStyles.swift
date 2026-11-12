// The type styles of the design, as numbers.
//
// Each style is a size, a weight and, at 20 points and above and for `meta`, a tracking set
// by hand, the draft's own: the design is tighter than the system at display sizes. Every style grows with the reader's
// text size setting, anchored to one of the system's text styles.

import SwiftUI

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
        }
    }

    /// Tracking set by hand, or zero to leave it to the system.
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
        if style.tracking == 0 {
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
