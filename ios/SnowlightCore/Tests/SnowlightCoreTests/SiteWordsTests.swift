import XCTest
@testable import SnowlightCore

/// Each ported constant equals the site's string at its key path in web/src/copy.ts.
/// The site's value is typed here for now; it is read from the golden `copy.json` once
/// the generator that makes that file exists.
final class SiteWordsTests: XCTestCase {
    func testAppName() {
        XCTAssertEqual(SiteWords.appName, "Snowlight")
    }
}
