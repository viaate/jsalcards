import XCTest
@testable import SnowlightCore

/// `format.clock` and `format.time` (web/src/copy-format.ts) give the site's words for every
/// case of clock.json (each minute of the day, and three it refuses) and time.json (every 37
/// minutes over the three windows in eight zones, an invalid instant and a zone no clock
/// knows). The no-break space between the time and AM or PM is the site's.
final class ClockAndTimeTests: XCTestCase {
    func testClockAsTheSite() throws {
        let file = try GoldenFile.family("clock")
        let differences = Differences()
        for value in file.cases {
            // [minute, format.clock(minute)]
            guard let entries = value.entries, entries.count == 2, let minute = inputNumber(entries[0]) else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine = shownAnswer { try SiteFormat.clock(minute) }
            if mine != entries[1] {
                differences.note("\(entries[0]): the site \(entries[1]), the app \(mine)")
            }
        }
        differences.report("clock")
    }

    func testTimeAsTheSite() throws {
        let file = try GoldenFile.family("time")
        let differences = Differences()
        var invalid = 0
        for value in file.cases {
            // [instant, zone, format.time(instant, zone)]
            guard let entries = value.entries, entries.count == 3, let zone = entries[1].text else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            guard let instant = inputInstant(entries[0]) else {
                // The site's invalid date, which no instant of the app is: the site refuses it.
                invalid += 1
                XCTAssertEqual(entries[2], GoldenValue.throwsMark, "the site said a time for an invalid date.")
                continue
            }
            differences.compared()
            let mine = shownAnswer { try SiteFormat.time(instant, zone: zone) }
            if mine != entries[2] {
                differences.note("\(instant) \(zone): the site \(entries[2]), the app \(mine)")
            }
        }
        differences.report("time")
        XCTAssertEqual(invalid, 1, "time.json holds one invalid instant.")
    }
}
