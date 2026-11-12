import XCTest
@testable import SnowlightCore

/// The layout rules: one column or two by the width class alone, a readable width from the
/// room alone, and the same answer for the same room however the room was reached (a fold
/// or an unfold while the app runs). The rooms are the ones the simulators reported.
final class ContentLayoutTests: XCTestCase {
    func testTheWidthClassAloneChoosesTheColumns() {
        for room in [0.0, 382, 402, 466, 951, 2000] {
            XCTAssertEqual(ContentLayout(room: room, widthClass: .compact).columns, .one, "room \(room)")
            XCTAssertEqual(ContentLayout(room: room, widthClass: .regular).columns, .two, "room \(room)")
        }
    }

    func testTheReadableWidthOnTheRoomsTheSimulatorsGave() {
        // iPhone 17 Pro: the whole 402 pt window.
        XCTAssertEqual(ContentLayout(room: 402, widthClass: .compact).readableWidth, 362)
        // iPhone Duo closed: 466 pt less the system's 84 pt column of controls.
        XCTAssertEqual(ContentLayout(room: 382, widthClass: .compact).readableWidth, 342)
        // iPhone Duo open, on its side: 951 pt, held to the readable limit.
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

    func testAFoldAndAnUnfoldGiveBackTheSameLayout() {
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
