import XCTest
@testable import SnowlightCore

/// The saved schools: ids only, at most five, each once, the first the home school; add,
/// remove and move, each refusing what would break those rules and changing nothing then.
final class SavedSchoolsTests: XCTestCase {
    private let ids = ["170993000713", "A1B2C3D4", "010000500870", "K9100314", "999999999999", "ZZZZZZZZ"]

    func testAtMostFiveEachOnceHomeFirst() throws {
        var saved = SavedSchools()
        XCTAssertNil(saved.home)
        for id in ids.prefix(5) {
            let done1 = saved.add(id)
            XCTAssertTrue(done1)
        }
        XCTAssertEqual(saved.ids, Array(ids.prefix(5)))
        XCTAssertEqual(saved.home, ids[0])
        // A sixth, a second copy and a text that is no id are refused.
        let done2 = saved.add(ids[5])
        XCTAssertFalse(done2)
        let done3 = saved.add(ids[1])
        XCTAssertFalse(done3)
        XCTAssertEqual(saved.ids, Array(ids.prefix(5)))
        var fresh = SavedSchools()
        let done4 = fresh.add("a1b2c3d4")
        XCTAssertFalse(done4)
        let done5 = fresh.add(" 170993000713")
        XCTAssertFalse(done5)
        XCTAssertEqual(fresh.ids, [])
        XCTAssertTrue(saved.holds(ids[2]))
        XCTAssertFalse(saved.holds(ids[5]))
    }

    func testRemoveAndMove() throws {
        var saved = SavedSchools(kept: Array(ids.prefix(4)))
        let done6 = saved.move(ids[2], to: 0)
        XCTAssertTrue(done6)
        XCTAssertEqual(saved.ids, [ids[2], ids[0], ids[1], ids[3]])
        XCTAssertEqual(saved.home, ids[2])
        let done7 = saved.move(ids[2], to: 3)
        XCTAssertTrue(done7)
        XCTAssertEqual(saved.ids, [ids[0], ids[1], ids[3], ids[2]])
        let done8 = saved.move(ids[2], to: 4)
        XCTAssertFalse(done8)
        let done9 = saved.move(ids[2], to: -1)
        XCTAssertFalse(done9)
        let done10 = saved.move(ids[5], to: 0)
        XCTAssertFalse(done10)
        let done11 = saved.makeHome(ids[3])
        XCTAssertTrue(done11)
        XCTAssertEqual(saved.ids, [ids[3], ids[0], ids[1], ids[2]])
        // Removing the home school makes the next one home.
        let done12 = saved.remove(ids[3])
        XCTAssertTrue(done12)
        XCTAssertEqual(saved.home, ids[0])
        let done13 = saved.remove(ids[3])
        XCTAssertFalse(done13)
        XCTAssertEqual(saved.ids, [ids[0], ids[1], ids[2]])
    }

    func testAKeptListIsReadByTheSameRules() throws {
        let kept = [ids[0], "not an id", ids[0], ids[1], ids[2], ids[3], ids[4], ids[5]]
        let saved = SavedSchools(kept: kept)
        XCTAssertEqual(saved.ids, Array(ids.prefix(5)))
    }
}
