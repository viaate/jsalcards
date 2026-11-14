import XCTest
@testable import SnowlightCore

/// Every length of My School's drawing is approved draft 3's, and the draft's content
/// heights are the sums of its bands.
final class BandsTests: XCTestCase {
    /// The design's lengths, written out a second time, each with the file and line it is
    /// read from (H: design/app/premium/d3t/myschool-closed-light.html; CSS and JS: d3t/
    /// app.css and app.js; DUO, DUOD, DUOB: design/app/duo/html/closed-myschool-light.html,
    /// closed-details-light.html, closed-myschool-under-light.html; DJS: duo.js; bands.out:
    /// the build spec's sums of the draft's bands).
    private let written: [(Band, Double)] = [
        (.topFade, 90), // CSS:219 .mapfade { height: 90px; }
        (.markerCore, 16), // CSS:226 .mk .core { width: 16px; height: 16px; }
        (.markerX, 175), // H:156 pin({ x: 175, ... }); DUO:174, DUOB:187 pinIn({ x: 175, ... })
        (.stemWidth, 1), // CSS:228 .mk .stem { width: 1px; }
        (.calloutLift, 30), // JS:158 lift: 30
        (.stemEndLight, 11.5), // JS:165 (DARK ? 11 : 11.5)
        (.stemEndDark, 11), // JS:165
        (.calloutHeight, 38), // CSS:240 height: 38px
        (.calloutRadius, 19), // CSS:240 border-radius: 19px
        (.calloutGap, 8), // CSS:240 gap: 8px
        (.calloutLeading, 14), // JS:178 paddingLeft = '14px'
        (.calloutTrailing, 5), // CSS:240 padding: 0 5px 0 5px
        (.calloutNameTrailing, 1), // CSS:243 .callout .nm { padding-right: 1px; }
        (.chipHeight, 26), // CSS:244 .chip { height: 26px; }
        (.chipRadius, 13), // CSS:244 border-radius: 13px
        (.chipPadding, 10), // CSS:244 padding: 0 10px
        (.calloutEdge, 16), // JS:183 Math.max(16, Math.min(402 - 16 - w, left)); DJS:155-164
        (.panelCorner, 38), // CSS:220 border-radius: 38px 38px 0 0
        (.sheetGradient, 120), // CSS:222 var(--sheet) 120px
        (.grabberWidth, 36), // CSS:221 width: 36px
        (.grabberHeight, 5), // CSS:221 height: 5px
        (.grabberRadius, 3), // CSS:221 border-radius: 3px
        (.grabberTop, 7), // CSS:221 top: 7px
        (.contentTop, 22), // H:16 .inner { padding: 22px 20px 0; }
        (.marginBottomBar, 20), // H:16
        (.marginOutside, 16), // DUO:76 .inner { padding-left: 16px; padding-right: 16px; }; DUOD:81; DUOB:82, :86
        (.topRow, 36), // H:17, CSS:292 .btn-round { height: 36px; }; DUO:71 .toprow { min-height: 36px; }
        (.districtLine, 20), // CSS:277 .meta { font: 400 15px/20px ... }
        (.nameGap, 9), // H:20 .schoolname { margin-top: 9px; }
        (.nameLine, 27), // CSS:276 .schoolname { font: 700 22px/27px ... }
        (.heroGap, 8), // H:21 .hero { ... margin-top: 8px; }
        (.statusLine, 66), // H:22 .status { font: 700 68px/66px ... }
        (.statusLeading, -3), // H:22 margin-left: -3px
        (.dayGap, 5), // H:27 .dayrow { ... margin-top: 5px; }
        (.dayLine, 25), // H:28 .day { font: 600 20px/25px ... }
        (.clock, 14), // H:30 .posted i { width: 14px; height: 14px; }
        (.postedGap, 5), // H:29 .posted { ... gap: 5px; }
        (.postedLine, 20), // H:29 font: 400 15px/20px
        (.postedBaseline, 7), // H:30, half of 14
        (.detailsGap, 6), // H:33 .details { margin-top: 6px; }
        (.detailsLine, 20), // H:33 font: 400 15px/20px
        (.cardGap, 17), // H:36 .mod { margin-top: 17px; }
        (.cardGapAfterDetails, 14), // H:38 body.known .details + .mod { margin-top: 14px; }
        (.cardRadius, 20), // H:36 border-radius: 20px
        (.cardTop, 13), // H:36 padding: 13px 16px 14px
        (.cardSide, 16), // H:36
        (.cardBottom, 14), // H:36
        (.keyLine, 15), // H:39 .mod .k { font: 600 12px/15px ... }
        (.countsGap, 8), // H:58 .yr { margin-top: 8px; }
        (.countsLine, 22), // H:58 font: 600 17px/22px
        (.draftChanceCard, 166), // bands.out chance: 166
        (.draftSeasonCard, 126), // bands.out season: 126
        (.draftCardToCard, 10), // H:37 .mod + .mod { margin-top: 10px; }
        (.draftContentStatusOnly, 517), // bands.out statusOnly: 517
        (.draftContentDetails, 540), // bands.out details: 540
        (.gapBottomBarStatusOnly, 14), // H:14 .sheet { top: 260px; }; bands.out gap 14
        (.gapBottomBarDetails, 11), // H:15 body.known .sheet { top: 240px; }; bands.out gap 11
        (.gapBesideStatusOnly, 21), // DUO:68 .sheet { top: 140px; }; bands.out 21
        (.gapBesideDetails, 24), // DUOD:77 body.known .sheet { top: 114px; }; bands.out 24
        (.gapUnderStatusOnly, 27), // DUOB:72 .sheet { top: 134px; }; bands.out 27
        (.markerAboveRestBottomBarStatusOnly, 109), // H:14 260; H:108 DY = 4, H:156 y: 147 + DY
        (.markerAboveRestBottomBarDetails, 100), // H:15 240; H:108 DY = -7, H:156
        (.markerAboveRestBesideStatusOnly, 53), // DUO:68 140; DUO:125 PY = 87
        (.markerAboveRestBesideDetails, 30), // DUOD:77 114; DUOD:131 PY = 84
        (.markerAboveRestUnderStatusOnly, 49), // DUOB:72 134; DUOB:135 PY = 85
    ]

    func testEveryBandIsInTheWrittenTableOnce() {
        XCTAssertEqual(written.map { $0.0 }, Band.allCases)
        XCTAssertEqual(written.count, 65)
    }

    func testEveryLengthIsTheDrafts() {
        for (band, length) in written {
            XCTAssertEqual(Bands.length(band), length, "\(band)")
        }
    }

    func testTheStemStopsWhereEachLookDrawsIt() {
        XCTAssertEqual(Bands.stemEnd(in: .light), 11.5)
        XCTAssertEqual(Bands.stemEnd(in: .dark), 11)
    }

    /// The build spec's sums (2.7, bands.out), from the lengths above: the bands above the
    /// cards, the draft's two contents, and the season card M1 draws (no strip).
    func testTheDraftsContentIsTheSumOfItsBands() {
        let above = [Band.contentTop, .topRow, .nameGap, .nameLine, .heroGap, .statusLine, .dayGap, .dayLine]
            .map { Bands.length($0) }
            .reduce(0, +)
        XCTAssertEqual(above, 198)
        let statusOnly = above + Bands.length(.cardGap) + Bands.length(.draftChanceCard)
            + Bands.length(.draftCardToCard) + Bands.length(.draftSeasonCard)
        XCTAssertEqual(statusOnly, Bands.length(.draftContentStatusOnly))
        let details = statusOnly + Bands.length(.detailsGap) + Bands.length(.detailsLine)
            - Bands.length(.cardGap) + Bands.length(.cardGapAfterDetails)
        XCTAssertEqual(details, Bands.length(.draftContentDetails))
        let seasonCard = [Band.cardTop, .keyLine, .countsGap, .countsLine, .cardBottom]
            .map { Bands.length($0) }
            .reduce(0, +)
        XCTAssertEqual(seasonCard, 72)
        // Without the chance card and the strip: 287 and 310 (2.7).
        XCTAssertEqual(above + Bands.length(.cardGap) + seasonCard, 287)
        XCTAssertEqual(above + Bands.length(.detailsGap) + Bands.length(.detailsLine)
            + Bands.length(.cardGapAfterDetails) + seasonCard, 310)
    }
}
