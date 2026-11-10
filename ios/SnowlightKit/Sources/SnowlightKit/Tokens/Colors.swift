// Colors come only from tokens.
//
// The table of values lives in SnowlightCore (State/Tokens.swift). This file turns a
// token into a color that follows the look of the window it is drawn in, so that one tap
// in Settings changes every color at once. No view holds a color value of its own.

import SnowlightCore
import SwiftUI
import UIKit

extension UIColor {
    /// A token as a color that follows the look: its light value in the light look, its
    /// dark value in the dark look.
    static func token(_ token: Token) -> UIColor {
        let light = UIColor.fixed(Tokens.color(token, in: .light))
        let dark = UIColor.fixed(Tokens.color(token, in: .dark))
        return UIColor { traits in
            traits.userInterfaceStyle == .dark ? dark : light
        }
    }

    /// One value of the table as a color that never changes.
    static func fixed(_ color: TokenColor) -> UIColor {
        UIColor(
            red: CGFloat(color.red) / 255,
            green: CGFloat(color.green) / 255,
            blue: CGFloat(color.blue) / 255,
            alpha: 1
        )
    }
}

extension Color {
    /// A token as a color that follows the look.
    static func token(_ token: Token) -> Color {
        Color(uiColor: UIColor.token(token))
    }

    /// A token's value in one look, whatever look the app is in. For the appearance
    /// tiles, each of which is a small picture of a look.
    static func token(_ token: Token, in look: ResolvedAppearance) -> Color {
        Color(uiColor: UIColor.fixed(Tokens.color(token, in: look)))
    }
}
