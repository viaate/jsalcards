// Every color the app draws, as a named token with a light and a dark value.
//
// This table is the only place a color value is written. SnowlightKit turns each token
// into a color that follows the look; no view holds a color of its own.
//
// The values are approved draft 3's (design/app/premium/d3t/app.css): every color of its
// light block (:10-58) and its dark block (:64-110), each named in camel case after its CSS
// name, in the CSS order, with the line of each value beside it. A value written with an
// alpha in the CSS keeps it. The draft's other literal colors (the sheet's shadow, the
// school marker, its stem, the crest) are in Shadows.swift.

/// The names of the colors.
public enum Token: Equatable, Hashable, Sendable, CaseIterable {
    /// Main text. `--ink`, CSS:10 (light), :64 (dark).
    case ink
    /// Second-level text. `--ink2`, CSS:11 (light), :65 (dark).
    case ink2
    /// Third-level text, the smallest. `--ink3`, CSS:12 (light), :66 (dark).
    case ink3
    /// Not for text: rails and hollow nodes. `--ink4`, CSS:13 (light), :67 (dark).
    case ink4
    /// `--line`, CSS:14 (light), :68 (dark).
    case line
    /// A card or a flat control on the page. `--fill`, CSS:15 (light), :69 (dark).
    case fill
    /// One step stronger than `fill`. `--fill2`, CSS:16 (light), :70 (dark).
    case fill2
    /// The ground of a panel over the map. `--sheet`, CSS:17 (light), :71 (dark).
    case sheet
    /// The ground of a full page. `--page`, CSS:18 (light), :72 (dark).
    case page
    /// `--grab`, CSS:20 (light), :74 (dark).
    case grab
    /// An ink-filled control. `--solid`, CSS:21 (light), :75 (dark).
    case solid
    /// What is drawn on `solid`. `--on-solid`, CSS:22 (light), :76 (dark).
    case onSolid
    /// `--solid-2`, CSS:23 (light), :77 (dark).
    case solid2
    /// `--rail`, CSS:24 (light), :78 (dark).
    case rail
    /// Empty radio rings and grips. `--ring`, CSS:25 (light), :79 (dark).
    case ring
    /// Quiet marks in the season strip. `--tick`, CSS:26 (light), :80 (dark).
    case tick
    /// `--month`, CSS:27 (light), :81 (dark).
    case month
    /// `--base`, CSS:28 (light), :82 (dark).
    case base
    /// Closed: dots, bars and arcs. `--closed`, CSS:30 (light), :84 (dark).
    case closed
    /// Closed: text up to 20 points. `--closed-ink`, CSS:31 (light), :85 (dark).
    case closedInk
    /// Closed: display text of 40 points and more. `--closed-hero`, CSS:32 (light), :86 (dark).
    case closedHero
    /// Closed: the solid chip over the map. `--closed-chip`, CSS:33 (light), :87 (dark).
    case closedChip
    /// Closed: text on the chip. `--closed-on`, CSS:34 (light), :88 (dark).
    case closedOn
    /// `--delayed`, CSS:35 (light), :89 (dark).
    case delayed
    /// `--delayed-ink`, CSS:36 (light), :90 (dark).
    case delayedInk
    /// `--remote`, CSS:37 (light), :91 (dark).
    case remote
    /// `--remote-ink`, CSS:38 (light), :92 (dark).
    case remoteInk
    /// `--early`, CSS:39 (light), :93 (dark).
    case early
    /// `--early-ink`, CSS:40 (light), :94 (dark).
    case earlyInk
    /// The chance color: bars, arcs and pies. `--chance`, CSS:42 (light), :95 (dark).
    case chance
    /// The chance color: text. `--chance-ink`, CSS:43 (light), :96 (dark).
    case chanceInk
    /// The chance color: pills and soft fills. `--chance-tint`, CSS:44 (light), :97 (dark).
    case chanceTint
    /// The chance color: the lightest bar in a ramp. `--chance-lo`, CSS:45 (light), :98 (dark).
    case chanceLo
    /// `--alert`, CSS:46 (light), :99 (dark).
    case alert
    /// `--alert-ink`, CSS:47 (light), :100 (dark).
    case alertInk
    /// `--flame`, CSS:48 (light), :101 (dark).
    case flame
    /// `--map-bg`, CSS:50 (light), :102 (dark).
    case mapBg
    /// `--map-ink`, CSS:51 (light), :103 (dark).
    case mapInk
    /// `--map-ink2`, CSS:52 (light), :104 (dark).
    case mapInk2
    /// `--map-fade`, CSS:53 (light), :105 (dark).
    case mapFade
    /// `--map-fade0`, CSS:54 (light), :106 (dark).
    case mapFade0
    /// `--lbl`, CSS:55 (light), :107 (dark).
    case lbl
    /// `--lbl-halo`, CSS:56 (light), :108 (dark).
    case lblHalo
    /// `--lbl-halo-water`, CSS:57 (light), :109 (dark).
    case lblHaloWater
    /// `--lbl-water`, CSS:58 (light), :110 (dark).
    case lblWater
    /// The small map pictures of Settings' Outside screen tiles, in draft 3's colors (the
    /// approved mock-up's tile, design/app/duo duo.js layoutThumb, which keeps draft 3's
    /// thumb colors): the map's ground,
    case thumbGround
    /// its lake and the lake's shore,
    case thumbWater
    case thumbShore
    /// a road (in the light look a white line on a darker edge; in the dark look one line),
    case thumbRoad
    case thumbRoadEdge
    /// the school's dot and its core,
    case thumbDot
    case thumbDotCore
    /// the sheet over the map, its bold title bar and its two grey lines.
    case thumbSheet
    case thumbTitle
    case thumbLine
    case thumbLine2
}

/// One color: red, green and blue, each from 0 to 255, and how much of what lies under it
/// the color covers, its alpha, from 0 (none) to 255 (all).
public struct TokenColor: Equatable, Hashable, Sendable {
    public let red: Int
    public let green: Int
    public let blue: Int
    /// The CSS alpha times 255, rounded to the nearest whole number, a half up
    /// (rgba(13, 14, 18, 0.09) is 22.95, so 23); 255 where the CSS gives none.
    public let alpha: Int

    /// From a six-digit value written as 0xRRGGBB, covering all that lies under it.
    init(_ value: UInt32) {
        self.init(value, alpha: 255)
    }

    /// From a six-digit value written as 0xRRGGBB and an alpha from 0 to 255; an alpha
    /// outside that range is held to its nearer end.
    init(_ value: UInt32, alpha: Int) {
        red = Int((value >> 16) & 0xFF)
        green = Int((value >> 8) & 0xFF)
        blue = Int(value & 0xFF)
        self.alpha = min(255, max(0, alpha))
    }

    /// Reads "#rrggbb": a number sign and exactly six hexadecimal digits, checked by hand
    /// over ASCII, as a color that covers all that lies under it. Anything else is not a
    /// color. Not public: no string crosses from this package into SnowlightKit, so the kit
    /// reads a color as its four numbers.
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

    /// The color's red, green and blue as "#rrggbb", in lower case; the alpha is not in it.
    /// Not public, for the same reason.
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

    /// Two values that cover all that lies under them.
    init(light: UInt32, dark: UInt32) {
        self.light = TokenColor(light)
        self.dark = TokenColor(dark)
    }

    /// Two values, either of which may carry an alpha.
    init(light: TokenColor, dark: TokenColor) {
        self.light = light
        self.dark = dark
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
        case .ink4:
            return TokenPair(light: 0xA3A6AE, dark: 0x5D606B)
        case .line:
            return TokenPair(light: TokenColor(0x0D0E12, alpha: 23), dark: TokenColor(0xFFFFFF, alpha: 27))
        case .fill:
            return TokenPair(light: 0xF2F3F5, dark: 0x2A2B31)
        case .fill2:
            return TokenPair(light: 0xE7E8EC, dark: 0x393A42)
        case .sheet:
            return TokenPair(light: 0xFFFFFF, dark: 0x1B1C21)
        case .page:
            return TokenPair(light: 0xFFFFFF, dark: 0x131418)
        case .grab:
            return TokenPair(light: 0xD4D5DA, dark: 0x55575F)
        case .solid:
            return TokenPair(light: 0x0D0E12, dark: 0xF4F5F7)
        case .onSolid:
            return TokenPair(light: 0xFFFFFF, dark: 0x0D0E12)
        case .solid2:
            return TokenPair(light: TokenColor(0xFFFFFF, alpha: 199), dark: TokenColor(0x0D0E12, alpha: 173))
        case .rail:
            return TokenPair(light: 0xE2E4E9, dark: 0x3A3B43)
        case .ring:
            return TokenPair(light: 0xC9CCD2, dark: 0x5A5C66)
        case .tick:
            return TokenPair(light: 0xD9DBE0, dark: 0x40424A)
        case .month:
            return TokenPair(light: TokenColor(0x0D0E12, alpha: 46), dark: TokenColor(0xFFFFFF, alpha: 56))
        case .base:
            return TokenPair(light: TokenColor(0x0D0E12, alpha: 51), dark: TokenColor(0xFFFFFF, alpha: 61))
        case .closed:
            return TokenPair(light: 0x1D9BE6, dark: 0x7FD4FF)
        case .closedInk:
            return TokenPair(light: 0x0A74B8, dark: 0x7FD4FF)
        case .closedHero:
            return TokenPair(light: 0x0B84CC, dark: 0x7FD4FF)
        case .closedChip:
            return TokenPair(light: 0x1791DC, dark: 0x7FD4FF)
        case .closedOn:
            return TokenPair(light: 0xFFFFFF, dark: 0x04263D)
        case .delayed:
            return TokenPair(light: 0xF0A020, dark: 0xF6B84A)
        case .delayedInk:
            return TokenPair(light: 0x9A6200, dark: 0xF6B84A)
        case .remote:
            return TokenPair(light: 0x8F72F7, dark: 0xB79CFF)
        case .remoteInk:
            return TokenPair(light: 0x6A4AD8, dark: 0xB79CFF)
        case .early:
            return TokenPair(light: 0x22B46D, dark: 0x45C987)
        case .earlyInk:
            return TokenPair(light: 0x0F7A49, dark: 0x5AD497)
        case .chance:
            return TokenPair(light: 0x12A594, dark: 0x36C9B3)
        case .chanceInk:
            return TokenPair(light: 0x0A7C6F, dark: 0x5FE3CC)
        case .chanceTint:
            return TokenPair(light: TokenColor(0xDCF3EF), dark: TokenColor(0x5FE3CC, alpha: 38))
        case .chanceLo:
            return TokenPair(light: 0xB5E6DE, dark: 0x1F5D57)
        case .alert:
            return TokenPair(light: 0xE0262D, dark: 0xFF5D62)
        case .alertInk:
            return TokenPair(light: 0xC81E26, dark: 0xFF6B70)
        case .flame:
            return TokenPair(light: 0xF2690F, dark: 0xFF8A3C)
        case .mapBg:
            return TokenPair(light: 0xE6EBF2, dark: 0x000000)
        case .mapInk:
            return TokenPair(light: 0x0D0E12, dark: 0xFFFFFF)
        case .mapInk2:
            return TokenPair(light: TokenColor(0x0D0E12, alpha: 148), dark: TokenColor(0xFFFFFF, alpha: 158))
        case .mapFade:
            return TokenPair(light: TokenColor(0xECF1F7, alpha: 184), dark: TokenColor(0x000000, alpha: 179))
        case .mapFade0:
            return TokenPair(light: TokenColor(0xECF1F7, alpha: 0), dark: TokenColor(0x000000, alpha: 0))
        case .lbl:
            return TokenPair(light: TokenColor(0x5A6779), dark: TokenColor(0xE2E8F0, alpha: 153))
        case .lblHalo:
            return TokenPair(light: 0xE2E8F0, dark: 0x000000)
        case .lblHaloWater:
            return TokenPair(light: 0xBCD6EE, dark: 0x0D1826)
        case .lblWater:
            return TokenPair(light: 0x3F73A3, dark: 0x7F9FC4)
        case .thumbGround:
            return TokenPair(light: 0xE4EAF1, dark: 0x06070A)
        case .thumbWater:
            return TokenPair(light: 0xBBD5EE, dark: 0x0F1C2C)
        case .thumbShore:
            return TokenPair(light: 0x7DA7CF, dark: 0x35506E)
        case .thumbRoad:
            return TokenPair(light: 0xFFFFFF, dark: 0x7D8088)
        case .thumbRoadEdge:
            return TokenPair(light: 0x8F9DB0, dark: 0x7D8088)
        case .thumbDot:
            return TokenPair(light: 0x1D9BE6, dark: 0x7FD4FF)
        case .thumbDotCore:
            return TokenPair(light: 0xFFFFFF, dark: 0xD8F2FF)
        case .thumbSheet:
            return TokenPair(light: 0xFFFFFF, dark: 0x1C1D22)
        case .thumbTitle:
            return TokenPair(light: 0x0D0E12, dark: 0xE9EAEE)
        case .thumbLine:
            return TokenPair(light: 0xD6D9DE, dark: 0x3C3E46)
        case .thumbLine2:
            return TokenPair(light: 0xE7E9ED, dark: 0x2E3036)
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
