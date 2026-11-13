import Foundation
import XCTest

/// Every golden family's cases have the shape the generator writes: each case a list, of the
/// length its kind gives (ios/tools/gen-golden.mjs says, family by family, what each entry of
/// a case is). The port's own tests, family by family, read the answers; this one holds the
/// shape they read, so a change to the generator's way of writing a case shows here first.
/// A kind is the case's first entry where a family holds more than one kind of case; "" is
/// a family of one kind.
final class GoldenShapeTests: XCTestCase {
    func testClock() throws {
        try checkShape(GoldenFile.family("clock"), ["": 2])
    }

    func testTime() throws {
        try checkShape(GoldenFile.family("time"), ["": 3])
    }

    func testInstant() throws {
        try checkShape(GoldenFile.family("instant"), ["": 2])
    }

    func testDays() throws {
        try checkShape(GoldenFile.family("days"), ["": 5])
    }

    func testStamps() throws {
        try checkShape(GoldenFile.family("stamps"), ["": 7])
    }

    func testStatusOn() throws {
        try checkShape(GoldenFile.family("status-on"), ["": 5])
    }

    func testShift() throws {
        try checkShape(GoldenFile.family("shift"), ["": 4])
    }

    func testChance() throws {
        try checkShape(GoldenFile.family("chance"), ["": 4])
    }

    func testGrades() throws {
        try checkShape(GoldenFile.family("grades"), ["grades": 4, "number": 3])
    }

    func testDetails() throws {
        try checkShape(GoldenFile.family("details"), ["": 2])
    }

    func testSeasonLine() throws {
        try checkShape(GoldenFile.family("season-line"), ["": 6])
    }

    func testSeasonFile() throws {
        try checkShape(GoldenFile.family("season-file"), ["file": 5, "school": 5, "lastDayOver": 3])
    }

    func testMapDay() throws {
        try checkShape(GoldenFile.family("map-day"), ["": 9])
    }

    func testZones() throws {
        try checkShape(GoldenFile.family("zones"), ["": 4])
    }

    func testClosings() throws {
        try checkShape(GoldenFile.family("closings"), ["file": 6, "status": 8])
    }

    func testPredictions() throws {
        try checkShape(GoldenFile.family("predictions"), ["file": 7, "outlook": 9, "underWay": 6])
    }

    func testFreshness() throws {
        try checkShape(GoldenFile.family("freshness"), ["": 6])
    }

    func testIDs() throws {
        try checkShape(GoldenFile.family("ids"), ["": 3])
    }

    /// Each case is a list whose length is its kind's; every kind named is met at least once.
    private func checkShape(_ golden: GoldenFile, _ lengths: [String: Int]) {
        XCTAssertGreaterThanOrEqual(golden.cases.count, golden.minCases, "\(golden.family): fewer cases than its minimum.")
        let kinded = lengths[""] == nil
        var met: Set<String> = []
        for (index, value) in golden.cases.enumerated() {
            guard case .array(let entries) = value else {
                XCTFail("\(golden.family): case \(index) is not a list.")
                return
            }
            var kind = ""
            if kinded {
                guard let first = entries.first, case .string(let named) = first else {
                    XCTFail("\(golden.family): case \(index) does not start with its kind.")
                    return
                }
                kind = named
            }
            guard let length = lengths[kind] else {
                XCTFail("\(golden.family): case \(index) is of a kind this test does not know: \(kind).")
                return
            }
            if entries.count != length {
                XCTFail("\(golden.family): case \(index) has \(entries.count) entries, not \(length).")
                return
            }
            met.insert(kind)
        }
        XCTAssertEqual(met, Set(lengths.keys), "\(golden.family): not every kind of case is there.")
    }
}
