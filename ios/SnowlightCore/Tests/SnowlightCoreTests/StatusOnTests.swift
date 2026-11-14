import XCTest
@testable import SnowlightCore

/// `format.statusOn` gives the site's line for every case of status-on.json: each status,
/// the days -1, 0, 1, 2 and 7 from now's day on the school's clock, five zones, four values
/// of now. A status key the site does not have is refused by the site; the app's statuses
/// are a closed set, so no such key can be given to it at all.
final class StatusOnTests: XCTestCase {
    /// The site's status keys in code order (copy.ts `STATUS_KEYS`), as the app's statuses.
    private let statuses: [String: ClosingStatus] = [
        "closed": .closed,
        "delayed": .delayed,
        "remote": .remote,
        "earlyDismissal": .earlyDismissal,
    ]

    func testStatusOnAsTheSite() throws {
        let file = try GoldenFile.family("status-on")
        let differences = Differences()
        var unknownKeys = 0
        for value in file.cases {
            // [status, day, now, zone, format.statusOn(status, day, now, zone)]
            guard let entries = value.entries, entries.count == 5,
                  let key = entries[0].text,
                  let day = entries[1].text,
                  let now = inputInstant(entries[2]),
                  let zone = entries[3].text else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            guard let status = statuses[key] else {
                unknownKeys += 1
                XCTAssertEqual(entries[4], GoldenValue.throwsMark, "the site said a line for the key \(key).")
                continue
            }
            differences.compared()
            let mine = shownAnswer { try SiteFormat.statusOn(status, day: day, now: now, zone: zone) }
            if mine != entries[4] {
                differences.note("\(key) \(day) \(zone) at \(now): the site \(entries[4]), the app \(mine)")
            }
        }
        differences.report("status-on")
        XCTAssertEqual(unknownKeys, 3, "status-on.json holds three keys the site does not have.")
    }
}
