import XCTest
@testable import SnowlightCore

/// `format.delay` and `format.dismissal` give the site's words for every case of shift.json:
/// every shift from 1 to 720 minutes with no clock, a grid of shifts and clocks, and the
/// values the site refuses. A refusal is not "no detail": where the site returns null (no
/// shift and no clock) the app returns nil, and where it throws the app throws.
final class ShiftTests: XCTestCase {
    func testDelayAndDismissalAsTheSite() throws {
        let file = try GoldenFile.family("shift")
        let differences = Differences()
        var none = 0
        var refused = 0
        for value in file.cases {
            // [shift, clock, format.delay(shift, clock), format.dismissal(shift, clock)]
            guard let entries = value.entries, entries.count == 4 else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            let shift = inputNumber(entries[0])
            let clock = inputNumber(entries[1])
            if (shift == nil && entries[0] != .null) || (clock == nil && entries[1] != .null) {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine: [GoldenValue] = [
                shownAnswer { try SiteFormat.delay(shift: shift, clock: clock) },
                shownAnswer { try SiteFormat.dismissal(shift: shift, clock: clock) },
            ]
            if mine != [entries[2], entries[3]] {
                differences.note("\(entries[0]) \(entries[1]): the site \([entries[2], entries[3]]), the app \(mine)")
            }
            if entries[2] == .null {
                none += 1
            }
            if entries[2] == GoldenValue.throwsMark {
                refused += 1
            }
        }
        differences.report("shift")
        XCTAssertEqual(none, 1, "shift.json holds one case with neither a shift nor a clock.")
        XCTAssertGreaterThan(refused, 0, "shift.json holds no refused case.")
    }
}
