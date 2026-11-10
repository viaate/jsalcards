import Foundation
import XCTest

/// The one test file that may read this machine's zone or its environment.
///
/// CI runs every core test under a zone that is not UTC, because on a UTC machine code
/// that leans on the device's zone by mistake gives right answers. This test proves the
/// odd zone really took hold: with `SNOWLIGHT_EXPECT_ZONE` set, the zone Foundation
/// reports must be that one. Without the variable it prints the zone and returns.
final class ThisMachineTests: XCTestCase {
    func testTheExpectedZoneTookHold() {
        let zone = TimeZone.current
        // A fixed moment, 2027-01-15T08:00:00Z, so the printed offset is the same on every run.
        let moment = Date(timeIntervalSince1970: 1_800_000_000)
        let offset = zone.secondsFromGMT(for: moment)
        print("ThisMachineTests: this machine's zone is \(zone.identifier), \(offset) seconds from GMT on 2027-01-15")

        guard let expected = ProcessInfo.processInfo.environment["SNOWLIGHT_EXPECT_ZONE"] else {
            print("ThisMachineTests: SNOWLIGHT_EXPECT_ZONE is not set, nothing to compare")
            return
        }
        print("ThisMachineTests: expected zone \(expected)")
        XCTAssertEqual(zone.identifier, expected, "The test zone did not take hold on this machine.")
        XCTAssertNotEqual(offset, 0, "The tests must never run on a UTC clock.")
    }
}
