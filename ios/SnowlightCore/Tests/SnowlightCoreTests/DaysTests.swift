import XCTest
@testable import SnowlightCore

/// `format.day`, `format.dayWithYear`, `chanceFormat.weekday` and `chanceFormat.chanceOn`
/// give the site's words for every case of days.json: every day from 2026-07-01 to
/// 2027-06-30, and the bad dates (February 30, month 13, a short year, letters, and the four
/// text traps), which the site refuses.
final class DaysTests: XCTestCase {
    func testDaysAsTheSite() throws {
        let file = try GoldenFile.family("days")
        let differences = Differences()
        var refused = 0
        for value in file.cases {
            // [text, format.day, format.dayWithYear, chanceFormat.weekday, chanceFormat.chanceOn]
            guard let entries = value.entries, entries.count == 5, let text = entries[0].text else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine: [GoldenValue] = [
                shownAnswer { try SiteFormat.day(text) },
                shownAnswer { try SiteFormat.dayWithYear(text) },
                shownAnswer { try SiteFormat.weekday(text) },
                shownAnswer { try SiteFormat.chanceOn(text) },
            ]
            if mine != Array(entries[1...]) {
                differences.note("\(text.debugDescription): the site \(Array(entries[1...])), the app \(mine)")
            }
            if entries[1] == GoldenValue.throwsMark {
                refused += 1
            }
        }
        differences.report("days")
        XCTAssertEqual(refused, 8, "days.json holds eight bad dates, each refused.")
    }

    func testTheDayIsReadByHand() throws {
        // `parseLocalDate` reads only ASCII digits, refuses a day that does not exist, and
        // refuses the years 0000 to 0099, which the site's Date.UTC reads as 1900 to 1999.
        XCTAssertEqual(try parseLocalDate("2027-01-12"), 1_799_712_000_000)
        XCTAssertThrowsError(try parseLocalDate("2027-02-29"))
        XCTAssertNoThrow(try parseLocalDate("2028-02-29"))
        XCTAssertThrowsError(try parseLocalDate("0099-01-01"))
        XCTAssertThrowsError(try parseLocalDate("2027-01-12 "))
        XCTAssertEqual(siteDayStart("2027-02-30"), siteDayStart("2027-03-02"))
        XCTAssertNil(siteDayStart("2027-02-32"))
    }
}
