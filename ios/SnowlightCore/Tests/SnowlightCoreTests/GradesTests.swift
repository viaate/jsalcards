import XCTest
@testable import SnowlightCore

/// `format.grades` and `format.number` give the site's words for every case of grades.json:
/// all pairs of the codes PK, TK, KG and 01 to 13, the codes the site refuses (00, 14, K and
/// the text traps on 01), and counts with and without thousands separators, a negative one
/// and one that is not whole (refused).
final class GradesTests: XCTestCase {
    func testGradesAndNumbersAsTheSite() throws {
        let file = try GoldenFile.family("grades")
        let differences = Differences()
        var grades = 0
        var numbers = 0
        for value in file.cases {
            guard let read = kindOf(value) else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            let entries = read.entries
            if read.kind == "grades", entries.count == 4, let low = entries[1].text, let high = entries[2].text {
                // ["grades", low, high, format.grades(low, high)]
                differences.compared()
                grades += 1
                let mine = shownAnswer { try SiteFormat.grades(low, high) }
                if mine != entries[3] {
                    differences.note("\(low.debugDescription) \(high.debugDescription): the site \(entries[3]), the app \(mine)")
                }
            } else if read.kind == "number", entries.count == 3, let n = inputNumber(entries[1]) {
                // ["number", n, format.number(n)]
                differences.compared()
                numbers += 1
                let mine = shownAnswer { try SiteFormat.number(n) }
                if mine != entries[2] {
                    differences.note("\(entries[1]): the site \(entries[2]), the app \(mine)")
                }
            } else {
                differences.note("a case this test cannot read: \(value)")
            }
        }
        differences.report("grades")
        XCTAssertEqual(grades, 16 * 16 + 7)
        XCTAssertEqual(numbers, 11)
    }
}
