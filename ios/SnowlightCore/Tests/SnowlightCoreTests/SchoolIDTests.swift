import XCTest
@testable import SnowlightCore

/// School ids (web/src/state/ids.ts `isSchoolId`, `parseSchoolId`) are read as the site
/// reads them for every case of ids.json: good public and private ids, lower-case private
/// ones, spaces, lengths either side, and the traps (other scripts' digits, a trailing
/// newline, a leading U+FEFF, no-break spaces and tabs, padding to 16 and 17 UTF-16 units,
/// an astral character, and the two letters whose upper case is not one letter).
final class SchoolIDTests: XCTestCase {
    func testIdsAsTheSite() throws {
        let file = try GoldenFile.family("ids")
        let differences = Differences()
        for value in file.cases {
            // [text, isSchoolId(text), parseSchoolId(text)]
            guard let entries = value.entries, entries.count == 3, let text = entries[0].text, let isID = entries[1].flag else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            if isSchoolId(text) != isID {
                differences.note("\(text.debugDescription): the site's isSchoolId \(isID), the app's \(isSchoolId(text))")
            }
            let mine = golden(parseSchoolId(text))
            if mine != entries[2] {
                differences.note("\(text.debugDescription): the site's parseSchoolId \(entries[2]), the app's \(mine)")
            }
        }
        differences.report("ids")
        XCTAssertNil(parseSchoolId(nil))
    }
}
