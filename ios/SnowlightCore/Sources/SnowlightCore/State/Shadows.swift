// The draft's colors that are not tokens, and the shadows they are drawn in.
//
// Approved draft 3 (design/app/premium/d3t/app.css) writes these colors into its rules
// rather than as named colors: the sheet's shadow (:19 light, :73 dark), the dark sheet's
// top (:222), the closed school marker's core, ring, halos and glows (:230 dark, :234
// light), the marker's stem (:232 dark, :238 light) and the crest's tile (:288 light, :290
// dark). Each value is written here once, with its line beside it, and nowhere else.
//
// A shadow is kept as the CSS writes it, `[inset] x y blur spread color`, in points; the
// views decide how to draw it (a layer with a spread is drawn as a shape of its own). An
// alpha is the CSS alpha times 255, rounded to the nearest whole number, a half up, as in
// Tokens.swift.

/// One layer of a CSS box-shadow.
public struct ShadowLayer: Equatable, Hashable, Sendable {
    /// Moved right by this many points.
    public let x: Double
    /// Moved down by this many points.
    public let y: Double
    /// The CSS blur radius. A browser blurs with a Gaussian whose standard deviation is
    /// half of it (CSS Backgrounds and Borders 3, box-shadow).
    public let blur: Double
    /// How far the shadow's shape grows past the box on every side, before the blur.
    public let spread: Double
    public let color: TokenColor
    /// Drawn inside the box, not outside it.
    public let inset: Bool

    init(x: Double, y: Double, blur: Double, spread: Double, color: TokenColor, inset: Bool = false) {
        self.x = x
        self.y = y
        self.blur = blur
        self.spread = spread
        self.color = color
        self.inset = inset
    }
}

/// A gradient drawn from the top down: its first color and its last.
public struct GradientEnds: Equatable, Hashable, Sendable {
    public let top: TokenColor
    public let bottom: TokenColor
}

/// The table.
public enum Shadows {
    /// The shadow of a sheet over the map (`--sheet-shadow`), its layers in the CSS's
    /// order, the first on top.
    public static func sheet(in look: ResolvedAppearance) -> [ShadowLayer] {
        switch look {
        case .light:
            // CSS:19: 0 -6px 24px rgba(38, 58, 88, 0.13), 0 -1px 3px rgba(38, 58, 88, 0.06),
            // 0 -0.5px 0 rgba(38, 58, 88, 0.08)
            return [
                ShadowLayer(x: 0, y: -6, blur: 24, spread: 0, color: TokenColor(0x263A58, alpha: 33)),
                ShadowLayer(x: 0, y: -1, blur: 3, spread: 0, color: TokenColor(0x263A58, alpha: 15)),
                ShadowLayer(x: 0, y: -0.5, blur: 0, spread: 0, color: TokenColor(0x263A58, alpha: 20)),
            ]
        case .dark:
            // CSS:73: 0 -14px 40px rgba(0, 0, 0, 0.62), inset 0 0.5px 0 rgba(255, 255, 255, 0.17),
            // inset 0 1.5px 0 rgba(255, 255, 255, 0.04)
            return [
                ShadowLayer(x: 0, y: -14, blur: 40, spread: 0, color: TokenColor(0x000000, alpha: 158)),
                ShadowLayer(x: 0, y: 0.5, blur: 0, spread: 0, color: TokenColor(0xFFFFFF, alpha: 43), inset: true),
                ShadowLayer(x: 0, y: 1.5, blur: 0, spread: 0, color: TokenColor(0xFFFFFF, alpha: 10), inset: true),
            ]
        }
    }

    /// The color at the top edge of a sheet over the map. The dark sheet's ground is a
    /// gradient from it down to the token `sheet` (CSS:222: linear-gradient(180deg,
    /// #202127 0, var(--sheet) 120px)); the light sheet is `sheet` all through, so nil.
    public static func sheetTop(in look: ResolvedAppearance) -> TokenColor? {
        switch look {
        case .light:
            return nil
        case .dark:
            return TokenColor(0x202127) // CSS:222
        }
    }

    /// The closed school marker's core. In the light look it is the token `closed`
    /// (CSS:234, background: var(--closed)); in the dark look the CSS writes it (CSS:230).
    public static func closedMarkerCore(in look: ResolvedAppearance) -> TokenColor {
        switch look {
        case .light:
            return Tokens.color(.closed, in: .light) // CSS:234
        case .dark:
            return TokenColor(0x7FD4FF) // CSS:230: background: #7fd4ff
        }
    }

    /// The closed school marker's ring, halos, glows and shadow, laid on its 16 point
    /// core, in the CSS's order, the first on top.
    public static func closedMarker(in look: ResolvedAppearance) -> [ShadowLayer] {
        switch look {
        case .light:
            // CSS:234: 0 0 0 3px #fff, 0 0 0 10px rgba(29,155,230,0.20),
            // 0 0 0 10.5px rgba(29,155,230,0.16), 0 3px 8px 3px rgba(20,60,110,0.22)
            return [
                ShadowLayer(x: 0, y: 0, blur: 0, spread: 3, color: TokenColor(0xFFFFFF)),
                ShadowLayer(x: 0, y: 0, blur: 0, spread: 10, color: TokenColor(0x1D9BE6, alpha: 51)),
                ShadowLayer(x: 0, y: 0, blur: 0, spread: 10.5, color: TokenColor(0x1D9BE6, alpha: 41)),
                ShadowLayer(x: 0, y: 3, blur: 8, spread: 3, color: TokenColor(0x143C6E, alpha: 56)),
            ]
        case .dark:
            // CSS:230: 0 0 0 2.5px rgba(255,255,255,0.95), 0 0 16px 7px rgba(127,212,255,0.55),
            // 0 0 44px 16px rgba(127,212,255,0.22)
            return [
                ShadowLayer(x: 0, y: 0, blur: 0, spread: 2.5, color: TokenColor(0xFFFFFF, alpha: 242)),
                ShadowLayer(x: 0, y: 0, blur: 16, spread: 7, color: TokenColor(0x7FD4FF, alpha: 140)),
                ShadowLayer(x: 0, y: 0, blur: 44, spread: 16, color: TokenColor(0x7FD4FF, alpha: 56)),
            ]
        }
    }

    /// The marker's stem, a gradient from its top down.
    public static func stem(in look: ResolvedAppearance) -> GradientEnds {
        switch look {
        case .light:
            // CSS:238: linear-gradient(rgba(13,14,18,0.50), rgba(13,14,18,0.30))
            return GradientEnds(top: TokenColor(0x0D0E12, alpha: 128), bottom: TokenColor(0x0D0E12, alpha: 77))
        case .dark:
            // CSS:232: linear-gradient(rgba(255,255,255,0.75), rgba(255,255,255,0.25))
            return GradientEnds(top: TokenColor(0xFFFFFF, alpha: 191), bottom: TokenColor(0xFFFFFF, alpha: 64))
        }
    }

    /// The crest's round tile: always light, so a school's own colors stay true at night.
    public static func crestTile(in look: ResolvedAppearance) -> TokenColor {
        switch look {
        case .light:
            return TokenColor(0xFFFFFF) // CSS:288: background: #fff
        case .dark:
            return TokenColor(0xF3F4F6) // CSS:290: background: #f3f4f6
        }
    }

    /// The crest's hairline and shadow, in the CSS's order, the first on top.
    public static func crest(in look: ResolvedAppearance) -> [ShadowLayer] {
        switch look {
        case .light:
            // CSS:288: 0 0 0 0.5px rgba(0,0,0,0.16), 0 1px 2px rgba(0,0,0,0.06)
            return [
                ShadowLayer(x: 0, y: 0, blur: 0, spread: 0.5, color: TokenColor(0x000000, alpha: 41)),
                ShadowLayer(x: 0, y: 1, blur: 2, spread: 0, color: TokenColor(0x000000, alpha: 15)),
            ]
        case .dark:
            // CSS:290: 0 0 0 0.5px rgba(255,255,255,0.35), 0 1px 3px rgba(0,0,0,0.5)
            return [
                ShadowLayer(x: 0, y: 0, blur: 0, spread: 0.5, color: TokenColor(0xFFFFFF, alpha: 89)),
                ShadowLayer(x: 0, y: 1, blur: 3, spread: 0, color: TokenColor(0x000000, alpha: 128)),
            ]
        }
    }
}
