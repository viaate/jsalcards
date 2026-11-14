import XCTest
import Foundation
@testable import SnowlightCore

/// The app reads a file's JSON keeping its kinds apart as the site's checks do: `true` is
/// never a number and a number is never text; a whole number is what `Number.isInteger`
/// says; a position is 0 to 4,294,967,294; and a zone is a name on the app's list, letter
/// for letter, that this machine knows.
final class JSONValueTests: XCTestCase {
    func testKindsAreKeptApart() throws {
        let bytes = Data("[true, 1, 0, false, 1.0, \"1\", null, [], {}]".utf8)
        let value = try XCTUnwrap(JSONValue.read(bytes))
        XCTAssertEqual(value, .array([
            .bool(true), .number(1), .number(0), .bool(false), .number(1), .string("1"), .null, .array([]), .object([:]),
        ]))
        XCTAssertNil(JSONValue.read(Data("{\"a\": 1".utf8)), "a file cut short is no JSON.")
        // An absent key and a null are two things.
        let object = try XCTUnwrap(JSONValue.read(Data("{\"a\": null}".utf8))?.fields)
        XCTAssertEqual(object["a"], JSONValue.null)
        XCTAssertNil(object["b"])
    }

    func testWholeNumbersAndPositions() {
        XCTAssertEqual(wholeValue(.number(3), 0, 3), 3)
        XCTAssertEqual(wholeValue(.number(-0.0), 0, 3), 0)
        XCTAssertNil(wholeValue(.number(3.5), 0, 10))
        XCTAssertNil(wholeValue(.number(4), 0, 3))
        XCTAssertNil(wholeValue(.number(-1), 0, 3))
        XCTAssertNil(wholeValue(.bool(true), 0, 3))
        XCTAssertNil(wholeValue(.string("1"), 0, 3))
        XCTAssertNil(wholeValue(.null, 0, 3))
        XCTAssertNil(wholeValue(nil, 0, 3))
        XCTAssertFalse(isInteger(Double.nan))
        XCTAssertFalse(isInteger(Double.infinity))
        XCTAssertTrue(isIndex(.number(4_294_967_294)))
        XCTAssertFalse(isIndex(.number(4_294_967_295)))
        XCTAssertEqual(element([1, 2], 1), 2)
        XCTAssertNil(element([1, 2], 2))
        XCTAssertNil(element([1, 2], -1))
    }

    func testAZoneIsANameOnTheListThisMachineKnows() {
        XCTAssertTrue(isTimeZone("America/Chicago"))
        XCTAssertTrue(isTimeZone(JSONValue.string("America/Chicago")))
        XCTAssertFalse(isTimeZone(JSONValue.number(1)))
        XCTAssertFalse(isTimeZone(nil as JSONValue?))
        for special in ["*", "?", "", "america/chicago", "America/Chicago ", "US/Central", "GMT", "EST"] {
            XCTAssertFalse(isTimeZone(special), "\(special.debugDescription) is not on the app's list.")
        }
        XCTAssertTrue(isASCII("America/Chicago"))
        XCTAssertFalse(isASCII("Am\u{00E9}rica"))
    }
}
