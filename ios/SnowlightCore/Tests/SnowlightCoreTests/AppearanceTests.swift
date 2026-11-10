import XCTest
@testable import SnowlightCore

/// The appearance choice's stored values, with anything unknown read as System; and the
/// map that goes with each look, for both pairings. Written cases.
final class AppearanceTests: XCTestCase {
    func testTheThreeChoicesInTheOrderSettingsShowsThem() {
        XCTAssertEqual(AppearanceChoice.allCases, [.system, .light, .dark])
    }

    func testTheStoredValues() {
        XCTAssertEqual(AppearanceChoice.system.stored, "system")
        XCTAssertEqual(AppearanceChoice.light.stored, "light")
        XCTAssertEqual(AppearanceChoice.dark.stored, "dark")
    }

    func testAStoredValueReadsBackAsItsChoice() {
        for choice in AppearanceChoice.allCases {
            XCTAssertEqual(AppearanceChoice(stored: choice.stored), choice)
        }
    }

    func testNothingStoredAndAnythingUnknownReadAsSystem() {
        XCTAssertEqual(AppearanceChoice.standard, .system)
        XCTAssertEqual(AppearanceChoice(stored: nil), .system)
        for unknown in ["", "auto", "automatic", "Dark", "DARK", " dark", "dark ", "dark\n", "night", "0", "true"] {
            XCTAssertEqual(AppearanceChoice(stored: unknown), .system, "'\(unknown)' must read as System.")
        }
    }

    func testTheLookEachChoiceGives() {
        XCTAssertEqual(AppearanceChoice.system.resolved(phoneIsDark: false), .light)
        XCTAssertEqual(AppearanceChoice.system.resolved(phoneIsDark: true), .dark)
        XCTAssertEqual(AppearanceChoice.light.resolved(phoneIsDark: false), .light)
        XCTAssertEqual(AppearanceChoice.light.resolved(phoneIsDark: true), .light)
        XCTAssertEqual(AppearanceChoice.dark.resolved(phoneIsDark: false), .dark)
        XCTAssertEqual(AppearanceChoice.dark.resolved(phoneIsDark: true), .dark)

        XCTAssertEqual(AppearanceChoice.system.looks, [.light, .dark])
        XCTAssertEqual(AppearanceChoice.light.looks, [.light])
        XCTAssertEqual(AppearanceChoice.dark.looks, [.dark])
    }

    func testTheMatchedPairingIsTheStandardOne() {
        XCTAssertEqual(Pairing.standard, .matched)
    }

    func testTheMapForBothPairings() {
        XCTAssertEqual(mapLook(for: .light, pairing: .matched), .pale)
        XCTAssertEqual(mapLook(for: .dark, pairing: .matched), .dark)
        XCTAssertEqual(mapLook(for: .light, pairing: .alwaysDarkMap), .dark)
        XCTAssertEqual(mapLook(for: .dark, pairing: .alwaysDarkMap), .dark)
    }
}
