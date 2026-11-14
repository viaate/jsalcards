import Foundation
import XCTest
@testable import SnowlightCore

/// The app's rules version (State/RulesVersion.swift) is the one ios/tools/gen-golden.mjs
/// wrote beside the golden families, in Fixtures/rules-version.json: a whole number from 1
/// and the sha256 over every family's cases, which `gen-golden.mjs --check` makes again on
/// every run. The file sits beside golden/, not in it, so no family test reads it.
final class RulesVersionTests: XCTestCase {
    func testTheNumberIsTheCommittedOne() throws {
        let file = try XCTUnwrap(FixtureFile.json("rules-version.json").fields, "rules-version.json is not an object.")
        XCTAssertEqual(Set(file.keys), ["number", "sha256"])
        let number = try XCTUnwrap(file["number"]?.numeric, "rules-version.json has no number.")
        XCTAssertGreaterThanOrEqual(number, 1)
        XCTAssertEqual(number, Double(RulesVersion.number), "RulesVersion.number is not the committed rules version.")
        let digest = try XCTUnwrap(file["sha256"]?.text, "rules-version.json has no sha256.")
        XCTAssertEqual(digest.utf8.count, 64)
        XCTAssertTrue(digest.utf8.allSatisfy { ($0 >= 0x30 && $0 <= 0x39) || ($0 >= 0x61 && $0 <= 0x66) }, "the sha256 is not 64 lower-case hex digits.")
    }

    func testTheFileIsNoFamily() throws {
        XCTAssertFalse(try GoldenFile.familyNames().contains("rules-version"), "rules-version.json must not be in golden/.")
        XCTAssertTrue(try GoldenFile.familyNames().contains("school-view"))
    }
}
