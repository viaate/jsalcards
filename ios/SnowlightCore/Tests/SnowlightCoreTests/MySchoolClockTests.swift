import Foundation
import XCTest
@testable import SnowlightCore

/// The My School model's two clocks (M1 4.5): the status day turns at 3:30 PM on the school's
/// clock, and not at midnight or 7:30 AM; Posted is told on the viewer's clock; `nextChange` is
/// the school's next turn. In five school zones, the viewer in another zone each time, over
/// tour-tomorrow's file (the school closed on Wednesday, January 13, posted at 21:10 UTC on
/// the 12th). And a viewer zone handed to `decode` takes the fixture's place, or refuses it.
final class MySchoolClockTests: XCTestCase {
    /// Each school zone, its offset from UTC in January (hours), the viewer's zone, and the
    /// posted time on the viewer's clock.
    private let pairs: [(school: String, offset: Int64, viewer: String, posted: String)] = [
        ("America/New_York", -5, "America/Chicago", "3:10\u{00A0}PM"),
        ("America/Chicago", -6, "America/Denver", "2:10\u{00A0}PM"),
        ("America/Denver", -7, "America/Phoenix", "2:10\u{00A0}PM"),
        ("America/Phoenix", -7, "America/Los_Angeles", "1:10\u{00A0}PM"),
        ("America/Los_Angeles", -8, "America/Anchorage", "12:10\u{00A0}PM"),
    ]

    private func fixture(_ name: String) throws -> MySchoolInput {
        let data = try FixtureFile.data("tour/\(name).json")
        return try XCTUnwrap(MySchoolInput.decode(data, viewerZone: nil), "tour/\(name).json does not decode.")
    }

    /// The instant of a wall time in January on a clock `offset` hours from UTC: `day` 12 or
    /// 13, `minute` after midnight.
    private func at(_ day: Int64, _ minute: Int64, offset: Int64) throws -> Int64 {
        let midnight = try XCTUnwrap(parseInstant("2027-01-12T00:00:00Z"))
        return midnight + (day - 12) * 86_400_000 + (minute - offset * 60) * 60_000
    }

    private func model(_ base: MySchoolInput, school: String, viewer: String, now: Int64) -> MySchoolModel {
        let input = MySchoolInput(closings: base.closings, season: base.season, school: base.school, record: base.record, schoolZone: school, viewerZone: viewer, now: now)
        return mySchoolModel(input)
    }

    func testTheStatusDayTurnsAtHalfPastThree() throws {
        let base = try fixture("tour-tomorrow")
        for pair in pairs {
            let before: [(Int64, Int64)] = [(12, 7 * 60 + 29), (12, 7 * 60 + 31), (12, 15 * 60 + 29)]
            for (day, minute) in before {
                let shown = model(base, school: pair.school, viewer: pair.viewer, now: try at(day, minute, offset: pair.offset))
                XCTAssertEqual(shown.lead, .held(.otherDayOnly), "\(pair.school) Jan \(day) minute \(minute)")
                XCTAssertEqual(shown.held, [.otherDay(.closed)], "\(pair.school) Jan \(day) minute \(minute)")
            }
            let after: [(Int64, Int64, String)] = [
                (12, 15 * 60 + 30, "Closed tomorrow"),
                (12, 23 * 60 + 59, "Closed tomorrow"),
                (13, 0, "Closed today"),
                (13, 7 * 60 + 29, "Closed today"),
                (13, 7 * 60 + 31, "Closed today"),
                (13, 15 * 60 + 29, "Closed today"),
            ]
            for (day, minute, spoken) in after {
                let shown = model(base, school: pair.school, viewer: pair.viewer, now: try at(day, minute, offset: pair.offset))
                guard case .posted(let status) = shown.lead else {
                    XCTFail("\(pair.school) Jan \(day) minute \(minute): the status is not drawn")
                    continue
                }
                // The status day is Wednesday from 3:30 PM on the 12th, through midnight.
                XCTAssertEqual(status.day.drawnString, "Wednesday, January 13", "\(pair.school) Jan \(day) minute \(minute)")
                XCTAssertEqual(status.spoken.drawnString, spoken, "\(pair.school) Jan \(day) minute \(minute)")
                XCTAssertEqual(shown.held, [], "\(pair.school) Jan \(day) minute \(minute)")
            }
            let next = model(base, school: pair.school, viewer: pair.viewer, now: try at(13, 15 * 60 + 30, offset: pair.offset))
            XCTAssertEqual(next.lead, .held(.otherDayOnly), "\(pair.school): Thursday is the status day at 3:30 PM on the 13th")
            // Nothing changes at 7:30 AM.
            for day: Int64 in [12, 13] {
                let early = model(base, school: pair.school, viewer: pair.viewer, now: try at(day, 7 * 60 + 29, offset: pair.offset))
                let late = model(base, school: pair.school, viewer: pair.viewer, now: try at(day, 7 * 60 + 31, offset: pair.offset))
                XCTAssertEqual(early, late, "\(pair.school) Jan \(day): the model changed at 7:30 AM")
            }
        }
    }

    func testPostedIsToldOnTheViewersClock() throws {
        let base = try fixture("tour-tomorrow")
        for pair in pairs {
            let sameDay = model(base, school: pair.school, viewer: pair.viewer, now: try at(12, 15 * 60 + 30, offset: pair.offset))
            XCTAssertEqual(sameDay.posted?.posted?.drawnString, "Posted " + pair.posted, pair.school)
            let nextDay = model(base, school: pair.school, viewer: pair.viewer, now: try at(13, 7 * 60 + 31, offset: pair.offset))
            XCTAssertEqual(nextDay.posted?.posted?.drawnString, "Posted Tue, Jan 12, " + pair.posted, pair.school)
        }
    }

    func testNextChangeIsTheNextTurn() throws {
        let base = try fixture("tour-tomorrow")
        for pair in pairs {
            let turns: [((Int64, Int64), (Int64, Int64))] = [
                ((12, 7 * 60 + 29), (12, 15 * 60 + 30)),
                ((12, 15 * 60 + 29), (12, 15 * 60 + 30)),
                ((12, 15 * 60 + 30), (13, 0)),
                ((12, 23 * 60 + 59), (13, 0)),
                ((13, 0), (13, 15 * 60 + 30)),
                ((13, 7 * 60 + 31), (13, 15 * 60 + 30)),
            ]
            for (now, next) in turns {
                let shown = model(base, school: pair.school, viewer: pair.viewer, now: try at(now.0, now.1, offset: pair.offset))
                XCTAssertEqual(shown.nextChange, try at(next.0, next.1, offset: pair.offset), "\(pair.school) Jan \(now.0) minute \(now.1)")
            }
        }
    }

    func testAViewerZoneGivenToDecode() throws {
        let data = try FixtureFile.data("tour/tour-closed.json")
        let own = try XCTUnwrap(MySchoolInput.decode(data, viewerZone: nil))
        XCTAssertEqual(mySchoolModel(own).posted?.posted?.drawnString, "Posted 5:42\u{00A0}AM")
        let west = try XCTUnwrap(MySchoolInput.decode(data, viewerZone: Data("America/Los_Angeles".utf8)))
        XCTAssertEqual(mySchoolModel(west).posted?.posted?.drawnString, "Posted 2:42\u{00A0}AM")
        // The day is the school's: still Tuesday on its own clock.
        XCTAssertEqual(mySchoolModel(west).posted?.day.drawnString, "Tuesday, January 12")
        XCTAssertNil(MySchoolInput.decode(data, viewerZone: Data("America/Nowhere".utf8)), "a name off the app's list")
        XCTAssertNil(MySchoolInput.decode(data, viewerZone: Data("*".utf8)), "the unread mark is no clock")
        XCTAssertNil(MySchoolInput.decode(data, viewerZone: Data([0xFF, 0xFE])), "bytes that are not UTF-8")
        XCTAssertNil(MySchoolInput.decode(Data("{}".utf8), viewerZone: nil), "a fixture with none of its keys")
    }
}
