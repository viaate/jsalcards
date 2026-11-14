import XCTest
@testable import SnowlightCore

/// The update line (web/src/state/freshness.ts `updateState`) is the site's for every case
/// of freshness.json: ages from three minutes ahead to 25 hours old (dense about 0, 2 and 20
/// minutes), how long the app has held the file (0, 19, 20 and 21 minutes), online and
/// offline, three viewer zones; and the generated_at values that are not instants, for
/// which nothing is said.
final class FreshnessTests: XCTestCase {
    /// The app's update line in the golden files' encoding: [text, live], null for none, or
    /// the refusal mark where it threw.
    private func answer(generatedAt: String, online: Bool, zone: String, now: Int64, heldMs: Int64) -> GoldenValue {
        do {
            guard let state = try updateState(generatedAt: generatedAt, online: online, zone: zone, now: now, heldMs: heldMs) else {
                return .null
            }
            return .array([.string(state.text.drawnString), .bool(state.live)])
        } catch {
            return GoldenValue.throwsMark
        }
    }

    func testUpdateStateAsTheSite() throws {
        let file = try GoldenFile.family("freshness")
        let differences = Differences()
        var live = 0
        for value in file.cases {
            // [generatedAt, now, heldMs, online, zone, [text, live] or null]
            guard let entries = value.entries, entries.count == 6,
                  let generatedAt = entries[0].text,
                  let now = inputInstant(entries[1]),
                  let held = inputInstant(entries[2]),
                  let online = entries[3].flag,
                  let zone = entries[4].text else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine = answer(generatedAt: generatedAt, online: online, zone: zone, now: now, heldMs: held)
            if mine.entries?.last == GoldenValue.bool(true) {
                live += 1
            }
            if mine != entries[5] {
                differences.note("\(generatedAt.debugDescription) at \(now), held \(held), online \(online), \(zone): the site \(entries[5]), the app \(mine)")
            }
        }
        differences.report("freshness")
        XCTAssertGreaterThan(live, 0, "no freshness case is live.")
    }

    func testTheThresholds() throws {
        XCTAssertEqual(liveFreshMs, 20 * 60_000)
        XCTAssertEqual(liveLeadMs, 2 * 60_000)
    }
}
