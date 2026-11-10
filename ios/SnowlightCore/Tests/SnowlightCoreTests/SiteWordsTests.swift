import XCTest
@testable import SnowlightCore

/// Each ported constant equals the site's string at its key path in web/src/copy.ts.
/// The site's strings are read from the golden file copy.json, which the generator writes
/// by loading the site's own module: nothing here is typed from memory.
final class SiteWordsTests: XCTestCase {
    /// The site's string at a key path of its `copy` object.
    private func siteCopy(_ path: [String]) throws -> String {
        let file = try GoldenFile.family("copy")
        let first = try XCTUnwrap(file.cases.first, "copy.json holds no case.")
        let value = try XCTUnwrap(first.at(["copy"] + path), "copy.json has nothing at \(path).")
        return try XCTUnwrap(value.text, "copy.json holds no string at \(path).")
    }

    func testAppName() throws {
        XCTAssertEqual(SiteWords.appName.drawnString, try siteCopy(["appName"]))
    }

    func testSearchPlaceholder() throws {
        XCTAssertEqual(SiteWords.searchPlaceholder.drawnString, try siteCopy(["search", "placeholder"]))
    }

    func testTheGoldenFileHoldsTheWholeOfTheSitesFixedWords() throws {
        let file = try GoldenFile.family("copy")
        let first = try XCTUnwrap(file.cases.first, "copy.json holds no case.")
        // The three parts the family is made of: the site's whole `copy` object, its
        // details sentences, and the chance section's one fixed line the app needs.
        XCTAssertNotNil(first.at(["copy", "status"]))
        XCTAssertNotNil(first.at(["detailsCopy"]))
        XCTAssertNotNil(first.at(["chanceCopy", "noSchool"])?.text)
    }
}
