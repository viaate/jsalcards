import XCTest
@testable import SnowlightCore

/// predictions/latest.json as the site reads it (web/src/data/map-day.ts), for every "file"
/// case of predictions.json: the two copied files, their mutations, and one mutation for
/// each odd zone name in a district's `time_zone` and in the private schools' `zones`.
/// Accepted or refused as the site does it, except where the site accepted a zone name the
/// app's list does not hold (`narrower`): there the app refuses. And each school's zone,
/// by district and by private school (`zonesOf`, `zoneOf`). The "outlook" and "underWay"
/// cases are read by the day rules' tests.
final class PredictionsFileTests: XCTestCase {
    /// ["file", name, path, json, parsePredictions accepts, narrower, zones]
    private func fileCases() throws -> [[GoldenValue]] {
        let golden = try GoldenFile.family("predictions")
        var cases: [[GoldenValue]] = []
        for value in golden.cases {
            guard let read = kindOf(value) else {
                XCTFail("predictions: a case this test cannot read: \(value)")
                continue
            }
            if read.kind == "file" {
                XCTAssertEqual(read.entries.count, 7)
                cases.append(read.entries)
            }
        }
        // The two copies, at least 30 mutations, and two for each odd zone name.
        XCTAssertGreaterThanOrEqual(cases.count, 32)
        return cases
    }

    /// The zone names a file names: its districts' and its private schools'.
    private func zoneNames(_ value: JSONValue) -> [String] {
        var names: [String] = []
        for district in value.fields?["districts"]?.items ?? [] {
            if let name = district.fields?["time_zone"]?.text {
                names.append(name)
            }
        }
        for zone in value.fields?["zones"]?.items ?? [] {
            if let name = zone.text {
                names.append(name)
            }
        }
        return names
    }

    func testAcceptOrRefuseAsTheSite() throws {
        let differences = Differences()
        var unknownHere: Set<String> = []
        for entries in try fileCases() where entries.count == 7 {
            differences.compared()
            let value = try caseFile(path: entries[2], inline: entries[3])
            let mine = parsePredictions(value) != nil
            let siteAccepts = entries[4].flag ?? false
            let narrower = entries[5].flag ?? false
            if narrower {
                if mine {
                    differences.note("\(entries[1]): the site read a zone the app's list does not hold, and the app accepts the file")
                }
                if !siteAccepts {
                    differences.note("\(entries[1]): a narrower case the site refuses")
                }
                continue
            }
            if mine && !siteAccepts {
                differences.note("\(entries[1]): the app accepts a file the site refuses")
            } else if !mine && siteAccepts {
                // Narrower on this machine alone: a name on the list this machine's
                // Foundation does not know reads as unknown here.
                let missing = zoneNames(value).filter { isListedButUnknownHere($0) }
                if missing.isEmpty {
                    differences.note("\(entries[1]): the app refuses a file the site accepts")
                } else {
                    unknownHere.formUnion(missing)
                }
            }
        }
        differences.report("predictions, accept or refuse")
        if !unknownHere.isEmpty {
            print("predictions files refused because this machine does not know: \(unknownHere.sorted().joined(separator: ", "))")
        }
    }

    func testTheNarrowerCasesAreRefused() throws {
        var narrower = 0
        for entries in try fileCases() where entries.count == 7 && entries[5].flag == true {
            narrower += 1
            let value = try caseFile(path: entries[2], inline: entries[3])
            XCTAssertNil(parsePredictions(value), "\(entries[1]): the app must refuse a zone that is not on its list.")
        }
        XCTAssertGreaterThan(narrower, 0, "predictions.json holds no narrower case.")
    }

    func testZonesAsTheSite() throws {
        let differences = Differences()
        for entries in try fileCases() where entries.count == 7 {
            guard let file = parsePredictions(try caseFile(path: entries[2], inline: entries[3])) else {
                continue
            }
            differences.compared()
            // [[zoneOf(z, -1, d) for d in 0 ... districts], [zoneOf(z, s, -1) for s in 0 ... schools]]
            let zones = zonesOf(file)
            var districts: [GoldenValue] = []
            for district in 0...file.directory.districts {
                districts.append(golden(zoneOf(zones, school: -1, district: district)))
            }
            var schools: [GoldenValue] = []
            for school in 0...file.directory.schools {
                schools.append(golden(zoneOf(zones, school: school, district: -1)))
            }
            let mine = GoldenValue.array([.array(districts), .array(schools)])
            if mine != entries[6] {
                differences.note("\(entries[1]): the site's zones \(entries[6]), the app's \(mine)")
            }
        }
        differences.report("predictions, zones")
    }

    func testPrivateSchoolEntriesAndTheToldZones() throws {
        let value = try SiteFixture.json("schemas/examples/synthetic-predictions.json")
        let file = try XCTUnwrap(parsePredictions(value), "the copied predictions file is refused.")
        XCTAssertFalse(file.schools.isEmpty, "the copied file has no private school.")
        // The binary search finds each private school's own entry, and none for any other
        // position (one past the end included).
        let listed = Set(file.schools.map { $0.school })
        for school in -1...(file.directory.schools + 1) {
            let found = schoolEntry(file, school: school)
            if listed.contains(school) {
                XCTAssertEqual(found, file.schools.first(where: { $0.school == school }))
            } else {
                XCTAssertNil(found, "school \(school) is no private school of the file.")
            }
        }
        // The clock a school's day is told by: none with no file shipped; the file's own
        // zone when its zones are read; the unread zone while they cannot be had, in the
        // contiguous US by place, and the unknown zone outside it.
        let zones = zonesOf(file)
        XCTAssertTrue(zonesFor(zones, file.directory))
        for school in 0...file.directory.schools {
            for district in -1...file.directory.districts {
                XCTAssertNil(schoolZone(.noFile, school: school, district: district, lon: -90, lat: 40))
                XCTAssertEqual(
                    schoolZone(.zones(zones), school: school, district: district, lon: -90, lat: 40),
                    zoneOf(zones, school: school, district: district)
                )
            }
        }
        XCTAssertEqual(schoolZone(.unread, school: 0, district: 0, lon: -90, lat: 40), unreadZone)
        XCTAssertEqual(schoolZone(.unread, school: 0, district: 0, lon: -157.8, lat: 21.3), unknownZone)
        XCTAssertEqual(schoolZone(.unread, school: 0, district: 0, lon: -149.9, lat: 61.2), unknownZone)
    }
}
