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

    func testStatusNames() throws {
        let names: [(ClosingStatus, String)] = [(.closed, "closed"), (.delayed, "delayed"), (.remote, "remote"), (.earlyDismissal, "earlyDismissal")]
        for (status, key) in names {
            XCTAssertEqual(SiteWords.status(status).drawnString, try siteCopy(["status", key]), "copy.status.\(key)")
        }
    }

    func testStatusLines() throws {
        let lines: [(ClosingStatus, String)] = [(.closed, "closed"), (.delayed, "delayed"), (.remote, "remote"), (.earlyDismissal, "earlyDismissal")]
        for (status, key) in lines {
            let words = SiteWords.statusLine(status)
            XCTAssertEqual(words.today.drawnString, try siteCopy(["statusLine", key, "today"]), "copy.statusLine.\(key).today")
            XCTAssertEqual(words.tomorrow.drawnString, try siteCopy(["statusLine", key, "tomorrow"]), "copy.statusLine.\(key).tomorrow")
            XCTAssertEqual(words.on.drawnString, try siteCopy(["statusLine", key, "on"]), "copy.statusLine.\(key).on")
        }
    }

    func testDaysLiveNavAndDetail() throws {
        let words: [(ShownText, [String])] = [
            (SiteWords.daysToday, ["days", "today"]),
            (SiteWords.daysTomorrow, ["days", "tomorrow"]),
            (SiteWords.liveUpdated, ["live", "updated"]),
            (SiteWords.liveOffline, ["live", "offline"]),
            (SiteWords.navLive, ["nav", "live"]),
            (SiteWords.detailPosted, ["detail", "posted"]),
            (SiteWords.detailConfirmed, ["detail", "confirmed"]),
        ]
        for (word, path) in words {
            XCTAssertEqual(word.drawnString, try siteCopy(path), "copy.\(path.joined(separator: "."))")
        }
    }

    func testChanceOfNoSchool() throws {
        let file = try GoldenFile.family("copy")
        let first = try XCTUnwrap(file.cases.first, "copy.json holds no case.")
        let value = try XCTUnwrap(first.at(["chanceCopy", "noSchool"])?.text, "copy.json holds no chanceCopy.noSchool.")
        XCTAssertEqual(SiteWords.chanceNoSchool.drawnString, value)
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
