import XCTest
@testable import SnowlightCore

/// The app's zone check is narrower than the site's, never wider (item 27). For every case
/// of zones.json, `[name, the site's isTimeZone, the site's regionOf, on the app's list]`:
/// where the app accepts a name the site accepts it; the list is the one the generator
/// wrote; every US name (a region other than `other`) is accepted on this machine; and the
/// region is the site's.
final class ZoneNamesTests: XCTestCase {
    private struct ZoneCase {
        let name: String
        let siteAccepts: Bool
        let region: String
        let onList: Bool
    }

    private func zoneCases() throws -> [ZoneCase] {
        let file = try GoldenFile.family("zones")
        var cases: [ZoneCase] = []
        for value in file.cases {
            guard let entries = value.entries, entries.count == 4,
                  let name = entries[0].text, let accepts = entries[1].flag,
                  let region = entries[2].text, let onList = entries[3].flag else {
                XCTFail("zones: a case this test cannot read: \(value)")
                continue
            }
            cases.append(ZoneCase(name: name, siteAccepts: accepts, region: region, onList: onList))
        }
        XCTAssertGreaterThanOrEqual(cases.count, file.minCases)
        return cases
    }

    func testNeverWiderThanTheSite() throws {
        let differences = Differences()
        for zone in try zoneCases() {
            differences.compared()
            if isTimeZone(zone.name) && !zone.siteAccepts {
                differences.note("\(zone.name.debugDescription): the app accepts a name the site refuses")
            }
            if isTimeZone(zone.name) && !zone.onList {
                differences.note("\(zone.name.debugDescription): the app accepts a name that is not on its list")
            }
            if isTimeZone(JSONValue.string(zone.name)) != isTimeZone(zone.name) {
                differences.note("\(zone.name.debugDescription): the two ways of asking differ")
            }
        }
        differences.report("zones, never wider")
    }

    func testTheListIsTheGeneratorsList() throws {
        let differences = Differences()
        var listed = 0
        for zone in try zoneCases() {
            differences.compared()
            if zone.onList {
                listed += 1
            }
            if ZoneNames.all.contains(zone.name) != zone.onList {
                differences.note("\(zone.name.debugDescription): on the list \(ZoneNames.all.contains(zone.name)), the generator says \(zone.onList)")
            }
        }
        differences.report("zones, the list")
        XCTAssertEqual(listed, ZoneNames.all.count, "zones.json does not name every name on the list.")
    }

    func testEveryUSZoneIsKnownHereAndOthersArePrinted() throws {
        var unknownHere: [String] = []
        var regioned = 0
        for zone in try zoneCases() where zone.onList {
            if zone.region != "other" {
                regioned += 1
                XCTAssertTrue(isTimeZone(zone.name), "\(zone.name): a US zone this machine does not accept.")
            } else if !isTimeZone(zone.name) {
                XCTAssertTrue(isListedButUnknownHere(zone.name))
                unknownHere.append(zone.name)
            }
        }
        XCTAssertEqual(regioned, 28, "the list should hold the site's 28 US zones.")
        let named = unknownHere.joined(separator: ", ")
        print("zones on the app's list this machine does not know: \(unknownHere.count) [\(named)]")
    }

    func testRegionsAsTheSite() throws {
        let differences = Differences()
        for zone in try zoneCases() {
            differences.compared()
            let mine = regionOf(zone.name).rawValue
            if mine != zone.region {
                differences.note("\(zone.name.debugDescription): the site \(zone.region), the app \(mine)")
            }
        }
        differences.report("zones, regions")
        XCTAssertEqual(regionOf(nil), .other)
        // Letter for letter: the Kelvin sign is not the letter K, though Swift's own `==`
        // calls the two texts equal.
        XCTAssertEqual(regionOf("America/\u{212A}entucky/Louisville"), .other)
        XCTAssertFalse(isTimeZone("America/\u{212A}entucky/Louisville"))
        XCTAssertTrue(isTimeZone("America/Kentucky/Louisville"))
    }
}
