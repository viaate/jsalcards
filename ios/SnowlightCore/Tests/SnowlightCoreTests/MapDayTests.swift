import XCTest
@testable import SnowlightCore

/// The map day and the days beside it (web/src/data/map-day.ts `mapDay`, `nextMapTurn`,
/// `localDay`, `todayEverywhere`, `clockToday`; web/src/data/school-day.ts `schoolToday`)
/// give the site's answers for every case of map-day.json: every 30 minutes over the three
/// windows (two US clock changes and the design's week) in each zone, no zone, the unread
/// zone and the unknown zone, every minute within two of each 3:30 PM, midnight and 7:30 AM
/// and of each clock change, and each odd zone name. Where the site accepted a zone name the
/// app's list does not hold (`narrower`), the app reads no clock: no day, no turn.
final class MapDayTests: XCTestCase {
    /// The app's answers in the golden order: mapDay, nextMapTurn, localDay, todayEverywhere,
    /// clockToday, schoolToday.
    private func answers(_ now: Int64, _ zone: String?) -> [GoldenValue] {
        var day: GoldenValue = .null
        if let named = zone {
            day = golden(localDay(now, named))
        }
        return [
            golden(mapDay(now, zone)),
            golden(nextMapTurn(now, zone)),
            day,
            golden(todayEverywhere(now)),
            golden(clockToday(now, zone)),
            golden(schoolToday(now, zone)),
        ]
    }

    func testMapDayAsTheSite() throws {
        let file = try GoldenFile.family("map-day")
        let differences = Differences()
        var invalid = 0
        var narrower = 0
        var unknownHere: Set<String> = []
        for value in file.cases {
            // [now, zone, mapDay, nextMapTurn, localDay, todayEverywhere, clockToday, schoolToday, narrower]
            guard let entries = value.entries, entries.count == 9, let flag = entries[8].flag else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            let told = inputZone(entries[1])
            guard told.known else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            let theirs = Array(entries[2..<8])
            guard let now = inputInstant(entries[0]) else {
                // The site's invalid date, which no instant of the app is: the site has no day.
                invalid += 1
                XCTAssertEqual(theirs, Array(repeating: GoldenValue.null, count: 6), "the site told a day of an invalid date.")
                continue
            }
            differences.compared()
            let mine = answers(now, told.zone)
            if flag || (appReadsNoClock(told.zone) && theirs[2] != .null) {
                // The app reads no clock for this name: only the day that is today everywhere,
                // which no zone tells, is said.
                if flag {
                    narrower += 1
                } else if let name = told.zone, isListedButUnknownHere(name) {
                    unknownHere.insert(name)
                } else {
                    differences.note("\(now) \(String(describing: told.zone)): the site reads a clock the app does not hold, and the case is not marked narrower")
                }
                let refused: [GoldenValue] = [.null, .null, .null, theirs[3], .null, .null]
                if mine != refused {
                    differences.note("\(now) \(String(describing: told.zone)): a name the app does not hold, and the app says \(mine)")
                }
                continue
            }
            if mine != theirs {
                differences.note("\(now) \(String(describing: told.zone)): the site \(theirs), the app \(mine)")
            }
        }
        differences.report("map-day")
        XCTAssertEqual(invalid, 3, "map-day.json holds three invalid dates.")
        XCTAssertGreaterThan(narrower, 0, "map-day.json holds no narrower case.")
        if !unknownHere.isEmpty {
            print("map-day: zones on the app's list this machine does not know: \(unknownHere.sorted().joined(separator: ", "))")
        }
    }

    func testTheTurnIsAtHalfPastThreeOnTheSchoolsClock() throws {
        // A written check beside the vectors: in Chicago on Jan 12, 2027 (UTC-6), 3:29 PM is
        // still the 12th and 3:30 PM is the 13th; midnight changes nothing.
        let before = try XCTUnwrap(parseInstant("2027-01-12T21:29:00Z"))
        let at = try XCTUnwrap(parseInstant("2027-01-12T21:30:00Z"))
        let midnight = try XCTUnwrap(parseInstant("2027-01-13T06:00:00Z"))
        XCTAssertEqual(mapDay(before, "America/Chicago"), "2027-01-12")
        XCTAssertEqual(mapDay(at, "America/Chicago"), "2027-01-13")
        XCTAssertEqual(mapDay(midnight, "America/Chicago"), "2027-01-13")
        XCTAssertEqual(nextMapTurn(before, "America/Chicago"), at)
        XCTAssertEqual(nextMapTurn(at, "America/Chicago"), midnight)
        // The unread and unknown zones, and the states.
        XCTAssertNil(mapDay(at, unknownZone))
        XCTAssertEqual(unreadZoneOf("KS"), unreadZone)
        XCTAssertEqual(unreadZoneOf("AK"), unknownZone)
        XCTAssertEqual(unreadZoneOf("HI"), unknownZone)
        XCTAssertEqual(unreadZoneOf("ks"), unknownZone)
        XCTAssertEqual(nextTurnOf(before, ["America/Chicago", "America/New_York"]), nextMapTurn(before, "America/Chicago"))
        XCTAssertNil(nextTurnOf(before, [unknownZone]))
    }
}
