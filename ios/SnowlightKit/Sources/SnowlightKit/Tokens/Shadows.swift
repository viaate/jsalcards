// The draft's shadows, and its colors that are not tokens, in the units SwiftUI draws with.
//
// The values live in SnowlightCore (State/Shadows.swift), each beside its line of approved
// draft 3's CSS. This file only carries them over: a color becomes a Color, a length a
// CGFloat. How a shadow is drawn is the view's to say: SwiftUI's shadows have no spread, so
// a layer with a spread is drawn as a shape of its own.

import SnowlightCore
import SwiftUI
import UIKit

extension Color {
    /// One of the draft's literal colors, in one look: a color that never changes.
    static func fixed(_ color: TokenColor) -> Color {
        Color(uiColor: UIColor.fixed(color))
    }

    /// Two of the draft's literal colors, one for each look, as a color that follows the
    /// look of the window it is drawn in, as a token does.
    static func following(light: TokenColor, dark: TokenColor) -> Color {
        let lightColor = UIColor.fixed(light)
        let darkColor = UIColor.fixed(dark)
        return Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? darkColor : lightColor
        })
    }
}

/// One layer of one of the draft's box-shadows, in SwiftUI's units.
struct DrawnShadow {
    /// Moved right by this many points.
    let x: CGFloat
    /// Moved down by this many points.
    let y: CGFloat
    /// The CSS blur radius.
    let blur: CGFloat
    /// The standard deviation of the Gaussian a browser blurs with: half the CSS blur
    /// (CSS Backgrounds and Borders 3, box-shadow).
    let deviation: CGFloat
    /// How far the shape grows past the box on every side, before the blur.
    let spread: CGFloat
    let color: Color
    /// Drawn inside the box, not outside it.
    let inset: Bool

    init(_ layer: ShadowLayer) {
        x = CGFloat(layer.x)
        y = CGFloat(layer.y)
        blur = CGFloat(layer.blur)
        deviation = CGFloat(layer.blur) / 2
        spread = CGFloat(layer.spread)
        color = Color.fixed(layer.color)
        inset = layer.inset
    }

    /// A shadow's layers, in the CSS's order, the first on top.
    static func layers(_ shadow: [ShadowLayer]) -> [DrawnShadow] {
        shadow.map { layer in DrawnShadow(layer) }
    }
}
