import XCTest
@testable import SnowlightCore

/// `parseInstant` (web/src/state/instant.ts) gives the site's answer for every case of
/// instant.json: 30 good instants (the year 0000 and leap days among them), 12 bad shapes,
/// and the four text traps on two good values. The text traps are refused, as the site's
/// `\d` and `$` refuse them.
final class InstantTests: XCTestCase {
    func testParseInstantAsTheSite() throws {
        let file = try GoldenFile.family("instant")
        let differences = Differences()
        for value in file.cases {
            // [text, parseInstant(text)]
            guard let entries = value.entries, entries.count == 2, let text = entries[0].text else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine = golden(parseInstant(text))
            if mine != entries[1] {
                differences.note("\(text.debugDescription): the site \(entries[1]), the app \(mine)")
            }
        }
        differences.report("instant")
    }

    func testAValueThatIsNotTextIsNoInstant() throws {
        // The site's first check: `typeof value !== 'string'`. Its answer for a good text is
        // read from the golden file, so the same characters as a number or a list give none.
        let file = try GoldenFile.family("instant")
        var good: String?
        for value in file.cases {
            if let entries = value.entries, entries.count == 2, entries[1].numeric != nil {
                good = entries[0].text
                break
            }
        }
        let text = try XCTUnwrap(good, "instant.json holds no good instant.")
        XCTAssertNotNil(parseInstant(JSONValue.string(text)))
        XCTAssertNil(parseInstant(JSONValue.array([.string(text)])))
        XCTAssertNil(parseInstant(JSONValue.null))
        XCTAssertNil(parseInstant(nil as JSONValue?))
    }
}
