import XCTest
@testable import SnowlightCore

/// `format.liveAt`, `updatedAt`, `offline` and `posted` give the site's words for every case
/// of stamps.json: five viewer zones, four values of now (each side of local midnight and on
/// the two days the clocks change), each with instants on now's day, the day before and the
/// day after. A stamp on another day than now's, on the viewer's clock, carries its day.
final class StampsTests: XCTestCase {
    func testStampsAsTheSite() throws {
        let file = try GoldenFile.family("stamps")
        let differences = Differences()
        var dated = 0
        for value in file.cases {
            // [instant, zone, now, liveAt, updatedAt, offline, posted]
            guard let entries = value.entries, entries.count == 7,
                  let instant = inputInstant(entries[0]),
                  let zone = entries[1].text,
                  let now = inputInstant(entries[2]) else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine: [GoldenValue] = [
                shownAnswer { try SiteFormat.liveAt(instant, zone: zone) },
                shownAnswer { try SiteFormat.updatedAt(instant, zone: zone, now: now) },
                shownAnswer { try SiteFormat.offline(instant, zone: zone, now: now) },
                shownAnswer { try SiteFormat.posted(instant, zone: zone, now: now) },
            ]
            if mine != Array(entries[3...]) {
                differences.note("\(instant) \(zone) at \(now): the site \(Array(entries[3...])), the app \(mine)")
            }
            if let posted = entries[6].text, posted.contains(",") {
                dated += 1
            }
        }
        differences.report("stamps")
        XCTAssertGreaterThan(dated, 0, "stamps.json holds no stamp on another day.")
    }
}
