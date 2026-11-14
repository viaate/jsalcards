import XCTest
@testable import SnowlightCore

/// The app's one new rule (PLAN section 4, rules A and B2): the big status is the school's
/// row on its map day, and every other row the site's `schoolStatus` gives is one of the
/// other posted days, never dropped. Proved for every "status" case of closings.json, and by
/// a written table of the three clock bands and the four ways a school's two days can be
/// posted.
final class MySchoolDayTests: XCTestCase {
    func testTheBigStatusIsTheSchoolsLight() throws {
        let differences = Differences()
        for found in try closingsStatusCases() {
            differences.compared()
            let days = mySchoolDays(closings: found.file, directory: found.directory, school: found.school, zone: found.zone, now: found.now)
            let mine = golden(days.hero.map { $0.status.rawValue })
            if mine != found.lit {
                differences.note("\(found.name), school \(found.school), \(String(describing: found.zone)) at \(found.now): the light \(found.lit), the big status \(mine)")
            }
        }
        differences.report("my school, the big status")
    }

    func testTheBigStatusAndTheOtherDaysAreExactlyTheSitesRows() throws {
        let differences = Differences()
        var kept = 0
        for found in try closingsStatusCases() {
            differences.compared()
            let days = mySchoolDays(closings: found.file, directory: found.directory, school: found.school, zone: found.zone, now: found.now)
            // Put each row back on the site's day for it: today's, tomorrow's, later.
            var today: StatusRow?
            var tomorrow: StatusRow?
            let heroDay = schoolToday(found.now, found.zone) == days.statusDay ? PostedDay.today : PostedDay.tomorrow
            if let hero = days.hero {
                if heroDay == .today {
                    today = hero
                } else {
                    tomorrow = hero
                }
            }
            var order: [PostedDay] = []
            for other in days.others {
                order.append(other.which)
                switch other.which {
                case .today:
                    if today != nil {
                        differences.note("\(found.name), school \(found.school): today's row twice")
                    }
                    today = other.row
                case .tomorrow:
                    if tomorrow != nil {
                        differences.note("\(found.name), school \(found.school): tomorrow's row twice")
                    }
                    tomorrow = other.row
                }
                if other.day == days.statusDay {
                    differences.note("\(found.name), school \(found.school): an other posted day on the status day")
                }
            }
            if order == [.tomorrow, .today] {
                differences.note("\(found.name), school \(found.school): tomorrow before today")
            }
            let mine = goldenStatus(SchoolStatus(today: today, tomorrow: tomorrow, later: days.later))
            if mine != found.status {
                differences.note("\(found.name), school \(found.school), \(String(describing: found.zone)) at \(found.now): the site's rows \(found.status), the app's \(mine)")
            }
            if days.hero == nil && !days.others.isEmpty {
                kept += 1
            }
        }
        differences.report("my school, every row kept")
        XCTAssertGreaterThan(kept, 0, "no case has a posted day beside no big status.")
    }

    // The written table ---------------------------------------------------------------

    /// A directory of one school, and a file that posts it closed today (Jan 12, 2027),
    /// remote tomorrow, both, or neither.
    private let stamp = DirectoryStamp(generatedOn: "2026-09-24", schools: 1, districts: 1)

    private func day(_ day: String, _ status: ClosingStatus) -> ClosingsDay {
        return ClosingsDay(day: day, gaps: [0], statuses: [status], announced: [nil], reasons: [nil], shifts: [], clocks: [], manual: [], details: nil)
    }

    private func file(today: Bool, tomorrow: Bool) throws -> ClosingsFile {
        var days: [ClosingsDay] = []
        if today {
            days.append(day("2027-01-12", .closed))
        }
        if tomorrow {
            days.append(day("2027-01-13", .remote))
        }
        let generatedAt = "2027-01-12T11:00:00Z"
        return ClosingsFile(generatedAt: generatedAt, generatedAtMs: try XCTUnwrap(parseInstant(generatedAt)), directory: stamp, days: days)
    }

    private let closedToday = StatusRow(status: .closed, reason: nil, announcedAt: nil, shiftMinutes: nil, clockMinute: nil, manual: false, details: [])
    private let remoteTomorrow = StatusRow(status: .remote, reason: nil, announcedAt: nil, shiftMinutes: nil, clockMinute: nil, manual: false, details: [])

    func testTheWrittenTable() throws {
        // Chicago, Jan 12, 2027 (UTC-6): 6:00 AM, 10:00 AM and 5:00 PM on the school's clock.
        let bands: [(name: String, now: String, statusDay: String)] = [
            (name: "midnight to 7:30 AM", now: "2027-01-12T12:00:00Z", statusDay: "2027-01-12"),
            (name: "7:30 AM to 3:30 PM", now: "2027-01-12T16:00:00Z", statusDay: "2027-01-12"),
            (name: "3:30 PM to midnight", now: "2027-01-12T23:00:00Z", statusDay: "2027-01-13"),
        ]
        let today = OtherPostedDay(which: .today, day: "2027-01-12", row: closedToday)
        let tomorrow = OtherPostedDay(which: .tomorrow, day: "2027-01-13", row: remoteTomorrow)
        // Each band and posting, with its expected big status and other posted days.
        let table: [(band: Int, today: Bool, tomorrow: Bool, hero: StatusRow?, others: [OtherPostedDay])] = [
            (band: 0, today: true, tomorrow: false, hero: closedToday, others: []),
            (band: 0, today: false, tomorrow: true, hero: nil, others: [tomorrow]),
            (band: 0, today: true, tomorrow: true, hero: closedToday, others: [tomorrow]),
            (band: 0, today: false, tomorrow: false, hero: nil, others: []),
            (band: 1, today: true, tomorrow: false, hero: closedToday, others: []),
            // The row the first draft lost: tomorrow posted before 3:30 PM is kept.
            (band: 1, today: false, tomorrow: true, hero: nil, others: [tomorrow]),
            (band: 1, today: true, tomorrow: true, hero: closedToday, others: [tomorrow]),
            (band: 1, today: false, tomorrow: false, hero: nil, others: []),
            (band: 2, today: true, tomorrow: false, hero: nil, others: [today]),
            (band: 2, today: false, tomorrow: true, hero: remoteTomorrow, others: []),
            (band: 2, today: true, tomorrow: true, hero: remoteTomorrow, others: [today]),
            (band: 2, today: false, tomorrow: false, hero: nil, others: []),
        ]
        XCTAssertEqual(table.count, 12)
        for row in table {
            let band = bands[row.band]
            let now = try XCTUnwrap(parseInstant(band.now))
            let closings = try file(today: row.today, tomorrow: row.tomorrow)
            let days = mySchoolDays(closings: closings, directory: stamp, school: 0, zone: "America/Chicago", now: now)
            let what = "\(band.name), today \(row.today), tomorrow \(row.tomorrow)"
            XCTAssertEqual(days.statusDay, band.statusDay, what)
            XCTAssertEqual(days.hero, row.hero, what)
            XCTAssertEqual(days.others, row.others, what)
            XCTAssertEqual(days.later, [], what)
            // The big status is the light, in every row of the table.
            XCTAssertEqual(days.hero?.status, litStatus(closings, directory: stamp, school: 0, zone: "America/Chicago", now: now), what)
        }
    }

    func testNothingFromAFileOfAnotherDirectory() throws {
        let closings = try file(today: true, tomorrow: true)
        let other = DirectoryStamp(generatedOn: "2026-09-25", schools: 1, districts: 1)
        let now = try XCTUnwrap(parseInstant("2027-01-12T16:00:00Z"))
        let days = mySchoolDays(closings: closings, directory: other, school: 0, zone: "America/Chicago", now: now)
        XCTAssertNil(days.hero)
        XCTAssertEqual(days.others, [])
        XCTAssertNil(mySchoolDays(closings: nil, directory: stamp, school: 0, zone: "America/Chicago", now: now).hero)
    }
}
