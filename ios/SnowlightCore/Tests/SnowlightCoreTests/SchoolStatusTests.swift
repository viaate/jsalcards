import XCTest
@testable import SnowlightCore

/// What the closings file says about a school today and tomorrow (web/src/data/school-day.ts
/// `schoolStatus`, read with no covered file) is the site's, for every "status" case of
/// closings.json: the three copied files and the mutation of three days, every school
/// position (one past the end included), each zone of ten (no zone, the unread and the
/// unknown zone among them) and fourteen moments across the files' days, with the file's
/// own directory and another. The rows themselves (`rowOn`) are the site's for every school
/// and day of every accepted file (ClosingsFileTests); here, which of them are today's,
/// tomorrow's and later.
final class SchoolStatusTests: XCTestCase {
    func testSchoolStatusAsTheSite() throws {
        let differences = Differences()
        var rows = 0
        for found in try closingsStatusCases() {
            differences.compared()
            let status = schoolStatus(school: found.school, directory: found.directory, closings: found.file, now: found.now, zone: found.zone)
            let mine = goldenStatus(status)
            if mine != found.status {
                differences.note("\(found.name), school \(found.school), \(String(describing: found.zone)) at \(found.now): the site \(found.status), the app \(mine)")
            }
            if status.today != nil || status.tomorrow != nil {
                rows += 1
            }
        }
        differences.report("closings, schoolStatus")
        XCTAssertGreaterThan(rows, 0, "no status case has a row.")
    }

    func testTheSiteSaysNoOpenHere() throws {
        // With no covered file, the site's today is a row or null, never "open"; the app has
        // no way to say it at all.
        for found in try closingsStatusCases() {
            XCTAssertNotEqual(found.status.entries?.first, GoldenValue.string("open"))
        }
        let none = schoolStatus(school: 0, directory: DirectoryStamp(generatedOn: "2026-09-24", schools: 1, districts: 1), closings: nil, now: 0, zone: nil)
        XCTAssertEqual(none, SchoolStatus.nothing)
    }
}
