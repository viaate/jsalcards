import Foundation
import XCTest
@testable import SnowlightCore

/// The school's and the district's names as the site shows them (web/src/app/school.ts
/// `shownName`, `districtShown`, and the panel's `splitName`), for every case of
/// school-names.json: the app takes S3's shown names and cuts only the campus off, as the site
/// does (Words/SchoolLines.swift `schoolName`, `districtName`). Every tour fixture carries the
/// names the site itself shows for its school, and the trim of a campus is JavaScript's own.
final class SchoolNameTests: XCTestCase {
    private func cases(_ kind: String) throws -> [[GoldenValue]] {
        let file = try GoldenFile.family("school-names")
        var found: [[GoldenValue]] = []
        for value in file.cases {
            guard let read = kindOf(value) else {
                XCTFail("school-names: a case this test cannot read: \(value)")
                continue
            }
            if read.kind == kind {
                found.append(read.entries)
            }
        }
        XCTAssertFalse(found.isEmpty, "school-names holds no \(kind) case.")
        return found
    }

    /// The tour's details row (M1 5.1), with the shown names given.
    private func record(shown: String?, districtShown: String?) throws -> SchoolRecord {
        let fixture = try FixtureFile.json("tour/tour-closed.json")
        let row = fixture.fields?["record"]?.fields?["row"]
        let stamp = try XCTUnwrap(parseStamp(fixture.fields?["closings"]?.fields?["directory"]), "the tour fixture's closings have no stamp.")
        return try XCTUnwrap(recordOf(row, index: 1, directory: stamp, shown: shown, districtShown: districtShown), "the tour fixture's row does not read.")
    }

    func testSchoolAndDistrictNamesAsTheSite() throws {
        let differences = Differences()
        // ["school", id, raw, shownName, name, campus]
        for entries in try cases("school") {
            differences.compared()
            guard entries.count == 6, let shown = entries[3].text else {
                differences.note("a school case this test cannot read: \(entries)")
                continue
            }
            let cut = SchoolLines.schoolName(try record(shown: shown, districtShown: nil))
            let mine = GoldenValue.array([golden(cut?.name.drawnString), golden(cut?.campus?.drawnString)])
            let want = GoldenValue.array([entries[4], entries[5]])
            if mine != want {
                differences.note("\(entries[2]): the site \(want), the app \(mine)")
            }
        }
        // ["district", id, raw, districtShown]
        for entries in try cases("district") {
            differences.compared()
            guard entries.count == 4, let shown = entries[3].text else {
                differences.note("a district case this test cannot read: \(entries)")
                continue
            }
            let named = SchoolLines.districtName(try record(shown: nil, districtShown: shown))
            if named?.drawnString != shown {
                differences.note("\(entries[2]): the site \(shown), the app \(String(describing: named?.drawnString))")
            }
        }
        differences.report("school-names")
        // A record with no shown name shows none.
        let bare = try record(shown: nil, districtShown: nil)
        XCTAssertNil(SchoolLines.schoolName(bare))
        XCTAssertNil(SchoolLines.districtName(bare))
    }

    func testTheTourFixturesCarryTheSitesNames() throws {
        var schools: [String: String] = [:]
        for entries in try cases("school") where entries.count == 6 {
            if let id = entries[1].text, let raw = entries[2].text, let shown = entries[3].text {
                schools[id + "\n" + raw] = shown
            }
        }
        var districts: [String: String] = [:]
        for entries in try cases("district") where entries.count == 4 {
            if let id = entries[1].text, let raw = entries[2].text, let shown = entries[3].text {
                districts[id + "\n" + raw] = shown
            }
        }
        for name in ["tour-closed", "tour-details", "tour-tomorrow"] {
            let fixture = try FixtureFile.json("tour/\(name).json")
            let record = try XCTUnwrap(fixture.fields?["record"]?.fields, "\(name): no record.")
            let row = try XCTUnwrap(record["row"]?.items, "\(name): no row.")
            let id = try XCTUnwrap(element(row, 0)?.text, "\(name): no id.")
            let raw = try XCTUnwrap(element(row, 1)?.text, "\(name): no name.")
            let districtId = try XCTUnwrap(element(row, 4)?.text, "\(name): no district id.")
            let districtRaw = try XCTUnwrap(element(row, 5)?.text, "\(name): no district name.")
            let shown = try XCTUnwrap(schools[id + "\n" + raw], "\(name): the family has no case for its school.")
            let districtShown = try XCTUnwrap(districts[districtId + "\n" + districtRaw], "\(name): the family has no case for its district.")
            XCTAssertEqual(record["shown"]?.text, shown, "\(name): the school's shown name is not the site's.")
            XCTAssertEqual(record["district_shown"]?.text, districtShown, "\(name): the district's shown name is not the site's.")
        }
    }

    func testTheTrimIsJavaScripts() throws {
        XCTAssertEqual(SchoolLines.trimmed.count, 25, "the 25 scalars JavaScript's trim() removes")
        for value in SchoolLines.trimmed.sorted() {
            let scalar = try XCTUnwrap(Unicode.Scalar(value), "U+\(String(value, radix: 16)) is not a scalar.")
            let around = String(Character(scalar))
            let cut = SchoolLines.splitName("Synthetic Middle School B - " + around + "North Campus" + around)
            XCTAssertEqual(cut.name, "Synthetic Middle School B", "U+\(String(value, radix: 16))")
            XCTAssertEqual(cut.campus, "North Campus", "U+\(String(value, radix: 16)) is trimmed from both ends of a campus.")
        }
        // JavaScript's trim() keeps these two, so the campus keeps them too.
        for value: UInt32 in [0x0085, 0x180E] {
            let scalar = try XCTUnwrap(Unicode.Scalar(value), "U+\(String(value, radix: 16)) is not a scalar.")
            let around = String(Character(scalar))
            let cut = SchoolLines.splitName("Synthetic Middle School B - " + around + "North Campus" + around)
            XCTAssertEqual(cut.campus, around + "North Campus" + around, "U+\(String(value, radix: 16)) is kept.")
        }
        // A mark at the start, a mark with nothing after it, and no mark: no cut.
        XCTAssertNil(SchoolLines.splitName(" - Synthetic Middle School B").campus)
        XCTAssertNil(SchoolLines.splitName("Synthetic Middle School B - \u{00A0}").campus)
        XCTAssertNil(SchoolLines.splitName("Synthetic Middle School B").campus)
        // The name before the mark is not trimmed.
        XCTAssertEqual(SchoolLines.splitName("Synthetic Middle School B  - North Campus").name, "Synthetic Middle School B ")
    }
}
