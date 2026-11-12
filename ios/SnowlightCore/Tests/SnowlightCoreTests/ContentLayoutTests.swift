import XCTest
@testable import SnowlightCore

/// The layout rules: one column or two by the width class alone, a readable width from the
/// room alone, and the same answer for the same room each time it is asked. The rooms of
/// the iPhone 17 Pro (402 pt) and of the closed Duo (466 pt less its 84 pt side column) are
/// the ones the app measured on the simulators. The open Duo's 951 pt is NOT measured: the
/// simulator never showed the app on the inner screen (it stayed black), so it is the
/// device profile's figure (2853 px at 3x, the inner screen on its side). Nothing here
/// proves that the app lays itself out again when the phone folds or unfolds: the xcode-27
/// image has no way to fold the simulator, so that stays unproven.
final class ContentLayoutTests: XCTestCase {
    func testTheWidthClassAloneChoosesTheColumns() {
        for room in [0.0, 382, 402, 466, 951, 2000] {
            XCTAssertEqual(ContentLayout(room: room, widthClass: .compact).columns, .one, "room \(room)")
            XCTAssertEqual(ContentLayout(room: room, widthClass: .regular).columns, .two, "room \(room)")
        }
    }

    func testTheReadableWidthOnTheRoomsOfThePhones() {
        // iPhone 17 Pro: the whole 402 pt window (measured by the app on the simulator).
        XCTAssertEqual(ContentLayout(room: 402, widthClass: .compact).readableWidth, 362)
        // iPhone Duo closed: 466 pt less the system's 84 pt column of controls (measured by
        // the app on the simulator).
        XCTAssertEqual(ContentLayout(room: 382, widthClass: .compact).readableWidth, 342)
        // iPhone Duo open, on its side: 951 pt (the device profile's figure, not measured),
        // held to the readable limit.
        XCTAssertEqual(ContentLayout(room: 951, widthClass: .regular).readableWidth, 672)
    }

    func testTheReadableWidthStaysBetweenZeroAndTheLimit() {
        XCTAssertEqual(ContentLayout.readableLimit, 672)
        XCTAssertEqual(ContentLayout.sideMargin, 20)
        XCTAssertEqual(ContentLayout(room: 0, widthClass: .compact).readableWidth, 0)
        XCTAssertEqual(ContentLayout(room: 30, widthClass: .compact).readableWidth, 0)
        XCTAssertEqual(ContentLayout(room: 712, widthClass: .regular).readableWidth, 672)
        XCTAssertEqual(ContentLayout(room: 711, widthClass: .regular).readableWidth, 671)
        XCTAssertEqual(ContentLayout(room: 5000, widthClass: .regular).readableWidth, 672)
    }

    /// The same rooms asked for in turn give the same layouts in turn: the layout is a pure
    /// function of the room. Not a proof of a live fold, which no simulator here can make.
    func testTheSameRoomAskedAgainGivesTheSameLayout() {
        let closed = ContentLayout(room: 382, widthClass: .compact)
        let unfolded = ContentLayout(room: 951, widthClass: .regular)
        XCTAssertNotEqual(closed, unfolded)
        let rooms: [(Double, WidthClass)] = [(382, .compact), (951, .regular), (382, .compact), (951, .regular)]
        var seen: [ContentLayout] = []
        for (room, widthClass) in rooms {
            seen.append(ContentLayout(room: room, widthClass: widthClass))
        }
        XCTAssertEqual(seen, [closed, unfolded, closed, unfolded])
    }
}
