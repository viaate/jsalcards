import XCTest
@testable import SnowlightCore

/// The Outside screen choice: its stored values, with anything unknown read as Beside the
/// map; the layout value each phone and pose gets; and which model names have an outside
/// screen. Written cases.
final class OutsideScreenTests: XCTestCase {
    func testTheTwoChoicesInTheOrderSettingsShowsThem() {
        XCTAssertEqual(OutsideScreenChoice.allCases, [.besideTheMap, .underTheControls])
    }

    func testTheStoredValuesAndTheKey() {
        XCTAssertEqual(OutsideScreenChoice.besideTheMap.stored, "beside")
        XCTAssertEqual(OutsideScreenChoice.underTheControls.stored, "under")
        XCTAssertEqual(OutsideScreenChoice.storeKey, "outsideScreen")
        XCTAssertNotEqual(OutsideScreenChoice.storeKey, AppearanceChoice.storeKey)
        for choice in OutsideScreenChoice.allCases {
            XCTAssertEqual(OutsideScreenChoice(stored: choice.stored), choice)
        }
    }

    func testNothingStoredAndAnythingUnknownReadAsBesideTheMap() {
        XCTAssertEqual(OutsideScreenChoice.standard, .besideTheMap)
        XCTAssertEqual(OutsideScreenChoice(stored: nil), .besideTheMap)
        for unknown in ["", "a", "b", "Under", "UNDER", " under", "under ", "under\n", "system", "dark", "0", "true"] {
            XCTAssertEqual(OutsideScreenChoice(stored: unknown), .besideTheMap, "'\(unknown)' must read as Beside the map.")
        }
    }

    func testAChoiceKeptInASettingsStoreReadsBackAndAnUnknownOneReadsAsBesideTheMap() throws {
        // A store of the tests' own, never the phone's, emptied before and after.
        let name = "snowlight.tests.outsideScreen"
        let store = try XCTUnwrap(UserDefaults(suiteName: name))
        store.removePersistentDomain(forName: name)
        defer { store.removePersistentDomain(forName: name) }
        // Nothing kept yet: Beside the map.
        XCTAssertEqual(OutsideScreenChoice.kept(in: store), .besideTheMap)
        // Under the controls, kept and read back, also through a second handle on the same
        // store, as the next launch of the app opens it.
        OutsideScreenChoice.underTheControls.keep(in: store)
        XCTAssertEqual(store.string(forKey: OutsideScreenChoice.storeKey), "under")
        XCTAssertEqual(OutsideScreenChoice.kept(in: store), .underTheControls)
        let again = try XCTUnwrap(UserDefaults(suiteName: name))
        XCTAssertEqual(OutsideScreenChoice.kept(in: again), .underTheControls)
        // Back to Beside the map.
        OutsideScreenChoice.besideTheMap.keep(in: store)
        XCTAssertEqual(OutsideScreenChoice.kept(in: store), .besideTheMap)
        // A value this build does not know, as a later or an earlier build might leave it.
        store.set("sideways", forKey: OutsideScreenChoice.storeKey)
        XCTAssertEqual(OutsideScreenChoice.kept(in: store), .besideTheMap)
        store.set(7, forKey: OutsideScreenChoice.storeKey)
        XCTAssertEqual(OutsideScreenChoice.kept(in: store), .besideTheMap)
        // Forgotten: Beside the map again.
        OutsideScreenChoice.underTheControls.keep(in: store)
        OutsideScreenChoice.forget(in: store)
        XCTAssertNil(store.object(forKey: OutsideScreenChoice.storeKey))
        XCTAssertEqual(OutsideScreenChoice.kept(in: store), .besideTheMap)
    }

    func testTheLayoutValueOfEachPhoneAndPose() {
        // Any other phone: the content runs under the system's controls, as it always has.
        XCTAssertEqual(sideControls(outsideScreen: nil, widthClass: .compact), .contentRunsUnder)
        XCTAssertEqual(sideControls(outsideScreen: nil, widthClass: .regular), .contentRunsUnder)
        // The closed Duo: A stops beside the side controls, B runs under them.
        XCTAssertEqual(sideControls(outsideScreen: .besideTheMap, widthClass: .compact), .contentStopsBeside)
        XCTAssertEqual(sideControls(outsideScreen: .underTheControls, widthClass: .compact), .contentRunsUnder)
        // The open Duo: the choice is about the outside screen and does not apply.
        XCTAssertEqual(sideControls(outsideScreen: .besideTheMap, widthClass: .regular), .contentRunsUnder)
        XCTAssertEqual(sideControls(outsideScreen: .underTheControls, widthClass: .regular), .contentRunsUnder)
    }

    func testOnlyTheDuoModelHasAnOuterScreen() {
        XCTAssertTrue(PhoneModel.hasOuterScreen(machine: Array("iPhone19,4".utf8)))
        // As the system hands it over, a C string with its zero byte, or more than one.
        XCTAssertTrue(PhoneModel.hasOuterScreen(machine: Array("iPhone19,4".utf8) + [0]))
        XCTAssertTrue(PhoneModel.hasOuterScreen(machine: Array("iPhone19,4".utf8) + [0, 0, 0]))
        let others = ["", "iPhone18,1", "iPhone19,3", "iPhone19,5", "iPhone19,40", "iphone19,4", "iPhone19,4 ", " iPhone19,4", "iPhone19.4", "arm64", "x86_64", "iPad16,3"]
        for other in others {
            XCTAssertFalse(PhoneModel.hasOuterScreen(machine: Array(other.utf8)), "'\(other)' has no outer screen.")
        }
        XCTAssertFalse(PhoneModel.hasOuterScreen(machine: []))
        XCTAssertFalse(PhoneModel.hasOuterScreen(machine: [0]))
        XCTAssertFalse(PhoneModel.hasOuterScreen(machine: [0] + Array("iPhone19,4".utf8)))
    }
}
