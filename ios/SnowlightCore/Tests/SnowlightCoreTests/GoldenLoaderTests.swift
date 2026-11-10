import Foundation
import XCTest

/// Every file in Fixtures/golden loads, has its header, and holds at least `min_cases`
/// cases. That every family is read by a test of its own is checked by a script
/// (ios/tools/check-ios.mjs), not here: test order differs between Linux and macOS.
final class GoldenLoaderTests: XCTestCase {
    func testThereIsAtLeastOneFamily() throws {
        let families = try GoldenFile.familyNames()
        XCTAssertFalse(families.isEmpty, "No golden file reached the test bundle.")
    }

    func testEveryFamilyLoadsWithItsHeaderAndItsCases() throws {
        for name in try GoldenFile.familyNames() {
            let file = try GoldenFile.family(name)
            XCTAssertEqual(file.family, name, "The file \(name).json names another family.")
            XCTAssertGreaterThanOrEqual(file.minCases, 1, "\(name): min_cases must be at least 1.")
            XCTAssertGreaterThanOrEqual(
                file.cases.count,
                file.minCases,
                "\(name): fewer cases than its own min_cases."
            )
            XCTAssertFalse(file.madeFrom.isEmpty, "\(name): no site file is named in made_from.")
            for source in file.madeFrom {
                XCTAssertTrue(source.path.hasPrefix("web/"), "\(name): \(source.path) is not a site file.")
                XCTAssertEqual(source.sha256.utf8.count, 64, "\(name): \(source.path) has no SHA-256.")
            }
        }
    }
}
