import XCTest
@testable import SnowlightCore

/// Every token has the light and the dark value of approved draft 3's CSS, alpha included,
/// and the draft's other literal colors and shadows are its own.
final class TokensTests: XCTestCase {
    /// The design's table, written out a second time: token, light, dark, each value exactly
    /// as design/app/premium/d3t/app.css writes it (light block :10-58, dark block :64-110),
    /// with its lines. The Duo leg's thumb colors come last; they are the approved Duo
    /// mock-up's (design/app/duo duo.js layoutThumb).
    private let written: [(Token, String, String)] = [
        (.ink, "#0d0e12", "#f4f5f7"), // --ink: CSS:10, :64
        (.ink2, "#5b5e67", "#a8abb5"), // --ink2: CSS:11, :65
        (.ink3, "#6f727b", "#8b8e99"), // --ink3: CSS:12, :66
        (.ink4, "#a3a6ae", "#5d606b"), // --ink4: CSS:13, :67
        (.line, "rgba(13, 14, 18, 0.09)", "rgba(255, 255, 255, 0.105)"), // --line: CSS:14, :68
        (.fill, "#f2f3f5", "#2a2b31"), // --fill: CSS:15, :69
        (.fill2, "#e7e8ec", "#393a42"), // --fill2: CSS:16, :70
        (.sheet, "#fff", "#1b1c21"), // --sheet: CSS:17, :71
        (.page, "#fff", "#131418"), // --page: CSS:18, :72
        (.grab, "#d4d5da", "#55575f"), // --grab: CSS:20, :74
        (.solid, "#0d0e12", "#f4f5f7"), // --solid: CSS:21, :75
        (.onSolid, "#fff", "#0d0e12"), // --on-solid: CSS:22, :76
        (.solid2, "rgba(255,255,255,0.78)", "rgba(13,14,18,0.68)"), // --solid-2: CSS:23, :77
        (.rail, "#e2e4e9", "#3a3b43"), // --rail: CSS:24, :78
        (.ring, "#c9ccd2", "#5a5c66"), // --ring: CSS:25, :79
        (.tick, "#d9dbe0", "#40424a"), // --tick: CSS:26, :80
        (.month, "rgba(13,14,18,0.18)", "rgba(255,255,255,0.22)"), // --month: CSS:27, :81
        (.base, "rgba(13,14,18,0.2)", "rgba(255,255,255,0.24)"), // --base: CSS:28, :82
        (.closed, "#1d9be6", "#7fd4ff"), // --closed: CSS:30, :84
        (.closedInk, "#0a74b8", "#7fd4ff"), // --closed-ink: CSS:31, :85
        (.closedHero, "#0b84cc", "#7fd4ff"), // --closed-hero: CSS:32, :86
        (.closedChip, "#1791dc", "#7fd4ff"), // --closed-chip: CSS:33, :87
        (.closedOn, "#fff", "#04263d"), // --closed-on: CSS:34, :88
        (.delayed, "#f0a020", "#f6b84a"), // --delayed: CSS:35, :89
        (.delayedInk, "#9a6200", "#f6b84a"), // --delayed-ink: CSS:36, :90
        (.remote, "#8f72f7", "#b79cff"), // --remote: CSS:37, :91
        (.remoteInk, "#6a4ad8", "#b79cff"), // --remote-ink: CSS:38, :92
        (.early, "#22b46d", "#45c987"), // --early: CSS:39, :93
        (.earlyInk, "#0f7a49", "#5ad497"), // --early-ink: CSS:40, :94
        (.chance, "#12a594", "#36c9b3"), // --chance: CSS:42, :95
        (.chanceInk, "#0a7c6f", "#5fe3cc"), // --chance-ink: CSS:43, :96
        (.chanceTint, "#dcf3ef", "rgba(95, 227, 204, 0.15)"), // --chance-tint: CSS:44, :97
        (.chanceLo, "#b5e6de", "#1f5d57"), // --chance-lo: CSS:45, :98
        (.alert, "#e0262d", "#ff5d62"), // --alert: CSS:46, :99
        (.alertInk, "#c81e26", "#ff6b70"), // --alert-ink: CSS:47, :100
        (.flame, "#f2690f", "#ff8a3c"), // --flame: CSS:48, :101
        (.mapBg, "#e6ebf2", "#000"), // --map-bg: CSS:50, :102
        (.mapInk, "#0d0e12", "#fff"), // --map-ink: CSS:51, :103
        (.mapInk2, "rgba(13,14,18,0.58)", "rgba(255,255,255,0.62)"), // --map-ink2: CSS:52, :104
        (.mapFade, "rgba(236,241,247,0.72)", "rgba(0,0,0,0.7)"), // --map-fade: CSS:53, :105
        (.mapFade0, "rgba(236,241,247,0)", "rgba(0,0,0,0)"), // --map-fade0: CSS:54, :106
        (.lbl, "#5a6779", "rgba(226,232,240,0.60)"), // --lbl: CSS:55, :107
        (.lblHalo, "#e2e8f0", "#000"), // --lbl-halo: CSS:56, :108
        (.lblHaloWater, "#bcd6ee", "#0d1826"), // --lbl-halo-water: CSS:57, :109
        (.lblWater, "#3f73a3", "#7f9fc4"), // --lbl-water: CSS:58, :110
        (.thumbGround, "#e4eaf1", "#06070a"),
        (.thumbWater, "#bbd5ee", "#0f1c2c"),
        (.thumbShore, "#7da7cf", "#35506e"),
        (.thumbRoad, "#ffffff", "#7d8088"),
        (.thumbRoadEdge, "#8f9db0", "#7d8088"),
        (.thumbDot, "#1d9be6", "#7fd4ff"),
        (.thumbDotCore, "#ffffff", "#d8f2ff"),
        (.thumbSheet, "#ffffff", "#1c1d22"),
        (.thumbTitle, "#0d0e12", "#e9eaee"),
        (.thumbLine, "#d6d9de", "#3c3e46"),
        (.thumbLine2, "#e7e9ed", "#2e3036"),
    ]

    func testEveryTokenIsInTheWrittenTableOnce() {
        XCTAssertEqual(written.map { $0.0 }, Token.allCases)
        // The draft's 45 colors (its 46 names less the sheet's shadow) and the 11 thumbs.
        XCTAssertEqual(written.count, 56)
    }

    func testEveryTokenHasALightAndADarkValueThatParse() throws {
        for (token, light, dark) in written {
            let lightColor = try XCTUnwrap(cssColor(light), "\(light) does not parse.")
            let darkColor = try XCTUnwrap(cssColor(dark), "\(dark) does not parse.")
            XCTAssertEqual(Tokens.pair(token).light, lightColor, "\(token), light")
            XCTAssertEqual(Tokens.pair(token).dark, darkColor, "\(token), dark")
            XCTAssertEqual(Tokens.color(token, in: .light), lightColor, "\(token), light")
            XCTAssertEqual(Tokens.color(token, in: .dark), darkColor, "\(token), dark")
        }
    }

    func testEachChannelIsAByte() {
        for token in Token.allCases {
            for look in ResolvedAppearance.allCases {
                let color = Tokens.color(token, in: look)
                for part in [color.red, color.green, color.blue, color.alpha] {
                    XCTAssertTrue((0...255).contains(part), "\(token) in \(look): \(part)")
                }
            }
        }
    }

    /// The CSS alpha times 255, rounded to the nearest whole number, a half up; 255 where
    /// the CSS gives none. Written by hand, apart from the reader below.
    func testAnAlphaIsTheCssAlphaTimes255Rounded() {
        let alphas: [(Token, ResolvedAppearance, Int)] = [
            (.line, .light, 23), // 0.09 x 255 = 22.95
            (.line, .dark, 27), // 0.105 x 255 = 26.775
            (.solid2, .light, 199), // 0.78 x 255 = 198.9
            (.solid2, .dark, 173), // 0.68 x 255 = 173.4
            (.month, .light, 46), // 0.18 x 255 = 45.9
            (.month, .dark, 56), // 0.22 x 255 = 56.1
            (.base, .light, 51), // 0.2 x 255 = 51
            (.base, .dark, 61), // 0.24 x 255 = 61.2
            (.chanceTint, .light, 255), // #dcf3ef: no alpha
            (.chanceTint, .dark, 38), // 0.15 x 255 = 38.25
            (.mapInk2, .light, 148), // 0.58 x 255 = 147.9
            (.mapInk2, .dark, 158), // 0.62 x 255 = 158.1
            (.mapFade, .light, 184), // 0.72 x 255 = 183.6
            (.mapFade, .dark, 179), // 0.7 x 255 = 178.5, a half, so up
            (.mapFade0, .light, 0),
            (.mapFade0, .dark, 0),
            (.lbl, .light, 255), // #5a6779: no alpha
            (.lbl, .dark, 153), // 0.60 x 255 = 153
            (.ink, .light, 255),
            (.mapBg, .dark, 255), // #000
        ]
        for (token, look, alpha) in alphas {
            XCTAssertEqual(Tokens.color(token, in: look).alpha, alpha, "\(token) in \(look)")
        }
        let withAlpha = Token.allCases.filter { token in
            ResolvedAppearance.allCases.contains { look in Tokens.color(token, in: look).alpha != 255 }
        }
        XCTAssertEqual(withAlpha, [.line, .solid2, .month, .base, .chanceTint, .mapInk2, .mapFade, .mapFade0, .lbl])
    }

    func testAColorIsReadByHand() throws {
        let teal = try XCTUnwrap(TokenColor(hex: "#12a594"))
        XCTAssertEqual([teal.red, teal.green, teal.blue, teal.alpha], [0x12, 0xA5, 0x94, 255])
        XCTAssertEqual(TokenColor(hex: "#12A594"), teal)
        XCTAssertEqual(teal.hex, "#12a594")
        let faded = TokenColor(0x12A594, alpha: 23)
        XCTAssertEqual(faded.hex, "#12a594")
        XCTAssertNotEqual(faded, teal)
        XCTAssertEqual(TokenColor(0x12A594, alpha: 300).alpha, 255)
        XCTAssertEqual(TokenColor(0x12A594, alpha: -1).alpha, 0)
    }

    func testWhatIsNotAColorIsRefused() {
        let refused = [
            "", "#", "12a594", "#12a59", "#12a5940", "#12a59g", "# 12a594", "#12a594 ", "#12a594\n",
            "0x12a594", "#12-594", "#+2a594",
            // Digits of other scripts are not hexadecimal digits.
            "#\u{FF11}\u{FF12}a594", "#\u{0661}\u{0662}a594",
        ]
        for text in refused {
            XCTAssertNil(TokenColor(hex: text), "'\(text)' must not parse.")
        }
    }

    // The draft's other literal colors and its shadows (State/Shadows.swift), each written
    // out a second time exactly as the CSS writes it.

    func testTheSheetIsTheDrafts() throws {
        // CSS:19, --sheet-shadow in the light block.
        try assertShadow(
            Shadows.sheet(in: .light),
            "0 -6px 24px rgba(38, 58, 88, 0.13), 0 -1px 3px rgba(38, 58, 88, 0.06), 0 -0.5px 0 rgba(38, 58, 88, 0.08)"
        )
        // CSS:73, --sheet-shadow in the dark block.
        try assertShadow(
            Shadows.sheet(in: .dark),
            "0 -14px 40px rgba(0, 0, 0, 0.62), inset 0 0.5px 0 rgba(255, 255, 255, 0.17), inset 0 1.5px 0 rgba(255, 255, 255, 0.04)"
        )
        // CSS:222: html[data-theme="dark"] .sheet { background: linear-gradient(180deg, #202127 0, var(--sheet) 120px) }
        XCTAssertEqual(Shadows.sheetTop(in: .dark), cssColor("#202127"))
        XCTAssertNil(Shadows.sheetTop(in: .light))
    }

    func testTheClosedMarkerIsTheDrafts() throws {
        // CSS:234: html[data-theme="light"] .mk.closed .core
        XCTAssertEqual(Shadows.closedMarkerCore(in: .light), Tokens.color(.closed, in: .light))
        try assertShadow(
            Shadows.closedMarker(in: .light),
            "0 0 0 3px #fff, 0 0 0 10px rgba(29,155,230,0.20), 0 0 0 10.5px rgba(29,155,230,0.16), 0 3px 8px 3px rgba(20,60,110,0.22)"
        )
        // CSS:230: html[data-theme="dark"] .mk.closed .core
        XCTAssertEqual(Shadows.closedMarkerCore(in: .dark), cssColor("#7fd4ff"))
        try assertShadow(
            Shadows.closedMarker(in: .dark),
            "0 0 0 2.5px rgba(255,255,255,0.95), 0 0 16px 7px rgba(127,212,255,0.55), 0 0 44px 16px rgba(127,212,255,0.22)"
        )
        // CSS:238 (light) and :232 (dark): .mk .stem
        XCTAssertEqual(Shadows.stem(in: .light).top, cssColor("rgba(13,14,18,0.50)"))
        XCTAssertEqual(Shadows.stem(in: .light).bottom, cssColor("rgba(13,14,18,0.30)"))
        XCTAssertEqual(Shadows.stem(in: .dark).top, cssColor("rgba(255,255,255,0.75)"))
        XCTAssertEqual(Shadows.stem(in: .dark).bottom, cssColor("rgba(255,255,255,0.25)"))
        XCTAssertEqual(Shadows.stem(in: .light).top.alpha, 128) // 127.5, a half, so up
        XCTAssertEqual(Shadows.stem(in: .light).bottom.alpha, 77) // 76.5, a half, so up
    }

    func testTheCrestIsTheDrafts() throws {
        // CSS:288: .crest
        XCTAssertEqual(Shadows.crestTile(in: .light), cssColor("#fff"))
        try assertShadow(Shadows.crest(in: .light), "0 0 0 0.5px rgba(0,0,0,0.16), 0 1px 2px rgba(0,0,0,0.06)")
        // CSS:290: html[data-theme="dark"] .crest
        XCTAssertEqual(Shadows.crestTile(in: .dark), cssColor("#f3f4f6"))
        try assertShadow(Shadows.crest(in: .dark), "0 0 0 0.5px rgba(255,255,255,0.35), 0 1px 3px rgba(0,0,0,0.5)")
    }

    /// The reader the tables above lean on reads the draft's three forms and nothing else.
    func testTheCssReaderReadsTheDraftsForms() throws {
        XCTAssertEqual(cssColor("#fff"), TokenColor(0xFFFFFF))
        XCTAssertEqual(cssColor("#000"), TokenColor(0x000000))
        XCTAssertEqual(cssColor("#1D9BE6"), TokenColor(0x1D9BE6))
        XCTAssertEqual(cssColor("rgba(13, 14, 18, 0.09)"), TokenColor(0x0D0E12, alpha: 23))
        XCTAssertEqual(cssColor("rgba(255,255,255,0.105)"), TokenColor(0xFFFFFF, alpha: 27))
        XCTAssertEqual(cssColor("rgba(0,0,0,0)"), TokenColor(0x000000, alpha: 0))
        XCTAssertEqual(cssColor("rgba(0,0,0,1)"), TokenColor(0x000000))
        for text in ["", "#ff", "#ffff", "rgb(1, 2, 3)", "rgba(1, 2, 3)", "rgba(256, 0, 0, 0.5)", "rgba(0, 0, 0, 1.5)", "rgba(0, 0, 0, .5)", "rgba(0, 0, 0, 0.1234)", "var(--sheet)"] {
            XCTAssertNil(cssColor(text), "'\(text)' must not parse.")
        }
        let layers = try XCTUnwrap(boxShadow("inset 0 0.5px 0 rgba(255, 255, 255, 0.17), 0 3px 8px 3px #fff"))
        XCTAssertEqual(layers.count, 2)
        XCTAssertEqual(layers.first?.inset, true)
        XCTAssertEqual(layers.first?.y, 0.5)
        XCTAssertEqual(layers.first?.blur, 0)
        XCTAssertEqual(layers.last?.inset, false)
        XCTAssertEqual(layers.last?.spread, 3)
        XCTAssertNil(boxShadow("0 rgba(0,0,0,0.5)"))
        XCTAssertNil(boxShadow("0 0 0 0 0 #fff"))
        XCTAssertNil(boxShadow("0 0 8px"))
    }

    // Reading the CSS's own words ---------------------------------------------------------

    private func assertShadow(_ shadow: [ShadowLayer], _ css: String, line: UInt = #line) throws {
        let layers = try XCTUnwrap(boxShadow(css), "'\(css)' does not parse.", line: line)
        XCTAssertEqual(shadow.count, layers.count, css, line: line)
        for (made, read) in zip(shadow, layers) {
            XCTAssertEqual(made, read, css, line: line)
        }
    }

    /// A CSS box-shadow as the draft writes one: layers parted by commas, each
    /// `[inset] x y [blur [spread]] color`, the lengths in px or a bare 0.
    private func boxShadow(_ text: String) -> [ShadowLayer]? {
        var layers: [ShadowLayer] = []
        for layer in parts(of: text, by: ",") {
            var inset = false
            var lengths: [Double] = []
            var color: TokenColor?
            for word in parts(of: layer, by: " ") {
                if word == "inset" {
                    inset = true
                } else if let length = cssLength(word) {
                    guard color == nil else { return nil }
                    lengths.append(length)
                } else if color == nil, let read = cssColor(word) {
                    color = read
                } else {
                    return nil
                }
            }
            guard let found = color, (2...4).contains(lengths.count) else { return nil }
            let blur = lengths.count > 2 ? lengths[2] : 0
            let spread = lengths.count > 3 ? lengths[3] : 0
            layers.append(ShadowLayer(x: lengths[0], y: lengths[1], blur: blur, spread: spread, color: found, inset: inset))
        }
        return layers.isEmpty ? nil : layers
    }

    /// "12px", "-0.5px" or a bare "0".
    private func cssLength(_ word: String) -> Double? {
        if word == "0" {
            return 0
        }
        guard word.hasSuffix("px") else { return nil }
        return Double(String(word.dropLast(2)))
    }

    /// A color as the draft writes one: "#rgb", "#rrggbb", or "rgba(r, g, b, a)" with the
    /// alpha a decimal from 0 to 1 of at most three places, turned into 0 to 255 as the
    /// table does: times 255, rounded to the nearest whole number, a half up.
    private func cssColor(_ text: String) -> TokenColor? {
        if text.hasPrefix("#") {
            let digits = Array(text.dropFirst())
            if digits.count == 3 {
                return TokenColor(hex: "#" + digits.map { "\($0)\($0)" }.joined())
            }
            return digits.count == 6 ? TokenColor(hex: text) : nil
        }
        guard text.hasPrefix("rgba("), text.hasSuffix(")") else { return nil }
        let inside = String(text.dropFirst(5).dropLast())
        let numbers = parts(of: inside, by: ",").map { part in String(part.filter { $0 != " " }) }
        guard numbers.count == 4 else { return nil }
        var value: UInt32 = 0
        for number in numbers.prefix(3) {
            guard let channel = UInt32(number), channel <= 255 else { return nil }
            value = value * 256 + channel
        }
        guard let alphaThousandths = thousandths(numbers[3]), alphaThousandths <= 1000 else { return nil }
        return TokenColor(value, alpha: (alphaThousandths * 255 + 500) / 1000)
    }

    /// "0.105" is 105 thousandths, "0.7" 700 and "1" 1000; a bare fraction or a fourth
    /// place is not the draft's.
    private func thousandths(_ number: String) -> Int? {
        let pieces = number.split(separator: ".", omittingEmptySubsequences: false).map { String($0) }
        guard let whole = pieces.first, let units = Int(whole), units >= 0, pieces.count <= 2 else { return nil }
        var fraction = pieces.count == 2 ? pieces[1] : ""
        guard fraction.count <= 3, fraction.allSatisfy({ $0 >= "0" && $0 <= "9" }), !(pieces.count == 2 && fraction.isEmpty) else {
            return nil
        }
        while fraction.count < 3 {
            fraction += "0"
        }
        guard let part = Int(fraction) else { return nil }
        return units * 1000 + part
    }

    /// The pieces of a text parted by one character, outside parentheses only, with the
    /// pieces' own spaces at either end taken off and empty pieces left out.
    private func parts(of text: String, by separator: Character) -> [String] {
        var pieces: [String] = []
        var piece = ""
        var depth = 0
        for character in text {
            if character == "(" {
                depth += 1
            } else if character == ")" {
                depth -= 1
            }
            if character == separator && depth == 0 {
                pieces.append(piece)
                piece = ""
            } else {
                piece.append(character)
            }
        }
        pieces.append(piece)
        return pieces.map { trimmedSpaces($0) }.filter { !$0.isEmpty }
    }

    private func trimmedSpaces(_ text: String) -> String {
        var characters = Substring(text)
        while characters.first == " " {
            characters = characters.dropFirst()
        }
        while characters.last == " " {
            characters = characters.dropLast()
        }
        return String(characters)
    }
}
