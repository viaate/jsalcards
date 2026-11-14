import XCTest
@testable import SnowlightCore

/// The panel's shape for each phone and pose, and its place on the two measured rooms: the
/// iPhone 17 Pro (874 high, a bottom inset of 83 where the tab bar runs, 402 wide) and the
/// closed iPhone Duo (678 high, a bottom inset of 34, a safe area 382 wide on the simulator
/// and 373 on the mock-up), as approved draft 3 and its Duo mock-ups draw them (build spec
/// 2.0 and geometry-r2.out). Written cases.
final class PanelPlaceTests: XCTestCase {
    func testTheShapeOfEachPhoneAndPose() {
        XCTAssertEqual(PanelShape.allCases, [.bottomBar, .outsideBeside, .outsideUnder])
        // An iPhone: no outside screen.
        XCTAssertEqual(panelShape(outsideScreen: nil, widthClass: .compact), .bottomBar)
        XCTAssertEqual(panelShape(outsideScreen: nil, widthClass: .regular), .bottomBar)
        // The closed Duo, each layout.
        XCTAssertEqual(panelShape(outsideScreen: .besideTheMap, widthClass: .compact), .outsideBeside)
        XCTAssertEqual(panelShape(outsideScreen: .underTheControls, widthClass: .compact), .outsideUnder)
        // The open Duo, whichever layout is kept.
        for kept in OutsideScreenChoice.allCases {
            XCTAssertEqual(panelShape(outsideScreen: kept, widthClass: .regular), .bottomBar, "\(kept)")
        }
    }

    func testTheIPhoneRestsWhereTheDraftDrawsIt() {
        // Status only: H:14 (260), H:156 with DY 4 (151); H:16 (20); CSS:221 (183 + 18); JS:183.
        XCTAssertEqual(
            panelPlace(shape: .bottomBar, details: false, windowHeight: 874, bottomInset: 83, safeWidth: 402),
            PanelPlace(rest: 260, markerX: 175, markerY: 151, margin: 20, trailing: 20, grabberCentre: 201,
                       calloutFrom: 16, calloutTo: 386)
        )
        // Details known: H:15 (240), H:156 with DY -7 (140).
        XCTAssertEqual(
            panelPlace(shape: .bottomBar, details: true, windowHeight: 874, bottomInset: 83, safeWidth: 402),
            PanelPlace(rest: 240, markerX: 175, markerY: 140, margin: 20, trailing: 20, grabberCentre: 201,
                       calloutFrom: 16, calloutTo: 386)
        )
    }

    func testTheClosedDuoRestsWhereTheMockUpsDrawIt() {
        // Beside the map, status only: DUO:68 (140), DUO:125 (87); DUO:76 (16); DCSS:18; DJS pinIn.
        XCTAssertEqual(
            panelPlace(shape: .outsideBeside, details: false, windowHeight: 678, bottomInset: 34, safeWidth: 382),
            PanelPlace(rest: 140, markerX: 175, markerY: 87, margin: 16, trailing: 16, grabberCentre: 191,
                       calloutFrom: 16, calloutTo: 366)
        )
        // Beside the map, details known: DUOD:77 (114), DUOD:131 (84).
        XCTAssertEqual(
            panelPlace(shape: .outsideBeside, details: true, windowHeight: 678, bottomInset: 34, safeWidth: 382),
            PanelPlace(rest: 114, markerX: 175, markerY: 84, margin: 16, trailing: 16, grabberCentre: 191,
                       calloutFrom: 16, calloutTo: 366)
        )
        // Under the controls, status only: DUOB:72 (134), DUOB:135 (85); DUOB:81, :82, :86.
        XCTAssertEqual(
            panelPlace(shape: .outsideUnder, details: false, windowHeight: 678, bottomInset: 34, safeWidth: 382),
            PanelPlace(rest: 134, markerX: 175, markerY: 85, margin: 16, trailing: 16, grabberCentre: 191,
                       calloutFrom: 16, calloutTo: 366)
        )
        // On the mock-up's 373 pt: the grabber 168.5 to 204.5 (DUOB:81), the callout kept to
        // 16 to 357 (pinIn(..., 0, 373)).
        let mockUp = panelPlace(shape: .outsideUnder, details: false, windowHeight: 678, bottomInset: 34, safeWidth: 373)
        XCTAssertEqual(mockUp?.grabberCentre, 186.5)
        XCTAssertEqual(mockUp?.calloutTo, 357)
    }

    func testUnderTheControlsWithDetailsHasNoPlace() {
        XCTAssertNil(panelPlace(shape: .outsideUnder, details: true, windowHeight: 678, bottomInset: 34, safeWidth: 382))
        XCTAssertNil(panelPlace(shape: .outsideUnder, details: true, windowHeight: 874, bottomInset: 83, safeWidth: 402))
        for shape in [PanelShape.bottomBar, .outsideBeside] {
            for details in [false, true] {
                XCTAssertNotNil(panelPlace(shape: shape, details: details, windowHeight: 678, bottomInset: 34, safeWidth: 382))
            }
        }
    }

    func testOnlyTheBottomBarsRoomEndsAtTheBottomInset() {
        // The tab bar's top moves the panel with it.
        let higher = panelPlace(shape: .bottomBar, details: false, windowHeight: 874, bottomInset: 93, safeWidth: 402)
        XCTAssertEqual(higher?.rest, 250)
        XCTAssertEqual(higher?.markerY, 141)
        // On the closed Duo the room ends at the window's bottom, whatever the inset.
        for inset in [0.0, 21, 34] {
            XCTAssertEqual(
                panelPlace(shape: .outsideBeside, details: false, windowHeight: 678, bottomInset: inset, safeWidth: 382)?.rest,
                140, "inset \(inset)"
            )
            XCTAssertEqual(
                panelPlace(shape: .outsideUnder, details: false, windowHeight: 678, bottomInset: inset, safeWidth: 382)?.rest,
                134, "inset \(inset)"
            )
        }
    }

    /// The season card M1 draws (no chance card, no strip) lands where the build spec
    /// measured it (2.0's table, geometry-r2.out), from the rest and the lengths of Bands.
    func testTheSeasonCardLandsWhereTheSpecMeasuredIt() throws {
        let above = [Band.contentTop, .topRow, .nameGap, .nameLine, .heroGap, .statusLine, .dayGap, .dayLine]
            .map { Bands.length($0) }
            .reduce(0, +)
        let details = Bands.length(.detailsGap) + Bands.length(.detailsLine)
        let card = [Band.cardTop, .keyLine, .countsGap, .countsLine, .cardBottom]
            .map { Bands.length($0) }
            .reduce(0, +)
        let rooms: [(PanelShape, Bool, Double, Double, Double, Double, Double)] = [
            (.bottomBar, false, 874, 83, 402, 475, 547),
            (.bottomBar, true, 874, 83, 402, 478, 550),
            (.outsideBeside, false, 678, 34, 382, 355, 427),
            (.outsideBeside, true, 678, 34, 382, 352, 424),
            (.outsideUnder, false, 678, 34, 382, 349, 421),
        ]
        for (shape, known, height, inset, width, top, bottom) in rooms {
            let place = try XCTUnwrap(panelPlace(shape: shape, details: known, windowHeight: height, bottomInset: inset,
                                                 safeWidth: width))
            let gap = known ? details + Bands.length(.cardGapAfterDetails) : Bands.length(.cardGap)
            XCTAssertEqual(place.rest + above + gap, top, "\(shape), details \(known)")
            XCTAssertEqual(place.rest + above + gap + card, bottom, "\(shape), details \(known)")
        }
    }
}
