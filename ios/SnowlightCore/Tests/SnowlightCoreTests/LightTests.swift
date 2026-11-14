import XCTest
@testable import SnowlightCore

/// The status a school's light shows on the site's map (web/src/data/closings.ts
/// `litStatus`) is the site's for every "status" case of closings.json: its row on its map
/// day, by its zone's clock; none for a file of another directory or a day it cannot tell.
final class LightTests: XCTestCase {
    func testLitStatusAsTheSite() throws {
        let differences = Differences()
        var lit = 0
        for found in try closingsStatusCases() {
            differences.compared()
            let status = litStatus(found.file, directory: found.directory, school: found.school, zone: found.zone, now: found.now)
            let mine = golden(status.map { $0.rawValue })
            if mine != found.lit {
                differences.note("\(found.name), school \(found.school), \(String(describing: found.zone)) at \(found.now): the site \(found.lit), the app \(mine)")
            }
            if status != nil {
                lit += 1
            }
        }
        differences.report("closings, litStatus")
        XCTAssertGreaterThan(lit, 0, "no status case is lit.")
    }

    func testNoLightWithoutAFile() throws {
        let stamp = DirectoryStamp(generatedOn: "2026-09-24", schools: 1, districts: 1)
        XCTAssertNil(litStatus(nil, directory: stamp, school: 0, zone: "America/Chicago", now: 0))
    }
}
