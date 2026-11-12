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
