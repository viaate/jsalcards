import XCTest
@testable import SnowlightCore

/// Every token has a light and a dark value that parse, and the table is the design's.
final class TokensTests: XCTestCase {
    /// The design's table, written out: token, light, dark.
    private let written: [(Token, String, String)] = [
        (.ink, "#0d0e12", "#f4f5f7"),
        (.ink2, "#5b5e67", "#a8abb5"),
        (.ink3, "#6f727b", "#8b8e99"),
        (.fill, "#f2f3f5", "#2a2b31"),
        (.fill2, "#e7e8ec", "#393a42"),
        (.page, "#ffffff", "#131418"),
        (.sheet, "#ffffff", "#1b1c21"),
        (.solid, "#0d0e12", "#f4f5f7"),
        (.onSolid, "#ffffff", "#0d0e12"),
        (.chance, "#12a594", "#36c9b3"),
    ]

    func testEveryTokenIsInTheWrittenTableOnce() {
        XCTAssertEqual(written.map { $0.0 }, Token.allCases)
    }

    func testEveryTokenHasALightAndADarkValueThatParse() throws {
        for (token, light, dark) in written {
            let lightColor = try XCTUnwrap(TokenColor(hex: light), "\(light) does not parse.")
            let darkColor = try XCTUnwrap(TokenColor(hex: dark), "\(dark) does not parse.")
            XCTAssertEqual(Tokens.pair(token).light, lightColor, "\(token), light")
            XCTAssertEqual(Tokens.pair(token).dark, darkColor, "\(token), dark")
            XCTAssertEqual(Tokens.color(token, in: .light).hex, light, "\(token), light")
            XCTAssertEqual(Tokens.color(token, in: .dark).hex, dark, "\(token), dark")
        }
    }

    func testEachChannelIsAByte() {
        for token in Token.allCases {
            for look in ResolvedAppearance.allCases {
                let color = Tokens.color(token, in: look)
                for part in [color.red, color.green, color.blue] {
                    XCTAssertTrue((0...255).contains(part), "\(token) in \(look): \(part)")
                }
            }
        }
    }

    func testAColorIsReadByHand() throws {
        let teal = try XCTUnwrap(TokenColor(hex: "#12a594"))
        XCTAssertEqual([teal.red, teal.green, teal.blue], [0x12, 0xA5, 0x94])
        XCTAssertEqual(TokenColor(hex: "#12A594"), teal)
        XCTAssertEqual(teal.hex, "#12a594")
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
}
