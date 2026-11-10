// Every color the app draws, as a named token with a light and a dark value.
//
// This table is the only place a color value is written. SnowlightKit turns each token
// into a color that follows the look; no view holds a color of its own.
//
// The dark values are a snapshot of unfinished design work, which is why they all live
// in this one table.

/// The names of the colors.
public enum Token: Equatable, Hashable, Sendable, CaseIterable {
    /// Main text.
    case ink
    /// Second-level text.
    case ink2
    /// Third-level text.
    case ink3
    /// A card or a flat control on the page.
    case fill
    /// One step stronger than `fill`.
    case fill2
    /// The ground of a full page.
    case page
    /// The ground of a panel over the map.
    case sheet
    /// An ink-filled control.
    case solid
    /// What is drawn on `solid`.
    case onSolid
    /// The chance color.
    case chance
}

/// One color: red, green and blue, each from 0 to 255.
public struct TokenColor: Equatable, Hashable, Sendable {
    public let red: Int
    public let green: Int
    public let blue: Int

    /// From a six-digit value written as 0xRRGGBB.
    init(_ value: UInt32) {
        red = Int((value >> 16) & 0xFF)
        green = Int((value >> 8) & 0xFF)
        blue = Int(value & 0xFF)
    }

    /// Reads "#rrggbb": a number sign and exactly six hexadecimal digits, checked by hand
    /// over ASCII. Anything else is not a color. Not public: no string crosses from this
    /// package into SnowlightKit, so the kit reads a color as its three numbers.
    init?(hex: String) {
        let bytes = Array(hex.utf8)
        guard bytes.count == 7, bytes[0] == 0x23 else {
            return nil
        }
        var value: UInt32 = 0
        for byte in bytes.dropFirst() {
            guard let digit = TokenColor.hexDigit(byte) else {
                return nil
            }
            value = value * 16 + digit
        }
        self.init(value)
    }

    /// The color as "#rrggbb", in lower case. Not public, for the same reason.
    var hex: String {
        var text = "#"
        for part in [red, green, blue] {
            text += TokenColor.twoDigits(part)
        }
        return text
    }

    private static func hexDigit(_ byte: UInt8) -> UInt32? {
        if byte >= 0x30 && byte <= 0x39 {
            return UInt32(byte - 0x30)
        }
        if byte >= 0x61 && byte <= 0x66 {
            return UInt32(byte - 0x61) + 10
        }
        if byte >= 0x41 && byte <= 0x46 {
            return UInt32(byte - 0x41) + 10
        }
        return nil
    }

    private static func twoDigits(_ value: Int) -> String {
        let digits = Array("0123456789abcdef")
        let held = min(255, max(0, value))
        var text = ""
        text.append(digits[held / 16])
        text.append(digits[held % 16])
        return text
    }
}

/// A token's two values.
public struct TokenPair: Equatable, Hashable, Sendable {
    public let light: TokenColor
    public let dark: TokenColor

    init(light: UInt32, dark: UInt32) {
        self.light = TokenColor(light)
        self.dark = TokenColor(dark)
    }
}

/// The table.
public enum Tokens {
    /// A token's light and dark values.
    public static func pair(_ token: Token) -> TokenPair {
        switch token {
        case .ink:
            return TokenPair(light: 0x0D0E12, dark: 0xF4F5F7)
        case .ink2:
            return TokenPair(light: 0x5B5E67, dark: 0xA8ABB5)
        case .ink3:
            return TokenPair(light: 0x6F727B, dark: 0x8B8E99)
        case .fill:
            return TokenPair(light: 0xF2F3F5, dark: 0x2A2B31)
        case .fill2:
            return TokenPair(light: 0xE7E8EC, dark: 0x393A42)
        case .page:
            return TokenPair(light: 0xFFFFFF, dark: 0x131418)
        case .sheet:
            return TokenPair(light: 0xFFFFFF, dark: 0x1B1C21)
        case .solid:
            return TokenPair(light: 0x0D0E12, dark: 0xF4F5F7)
        case .onSolid:
            return TokenPair(light: 0xFFFFFF, dark: 0x0D0E12)
        case .chance:
            return TokenPair(light: 0x12A594, dark: 0x36C9B3)
        }
    }

    /// A token's value in one look.
    public static func color(_ token: Token, in look: ResolvedAppearance) -> TokenColor {
        let both = pair(token)
        switch look {
        case .light:
            return both.light
        case .dark:
            return both.dark
        }
    }
}
