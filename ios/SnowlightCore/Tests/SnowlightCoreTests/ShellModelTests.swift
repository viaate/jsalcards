import XCTest
@testable import SnowlightCore

/// The shell's model: what it holds, and the words read off it, in order.
final class ShellModelTests: XCTestCase {
    func testTheAppNameIsTheSites() {
        XCTAssertEqual(ShellModel().appName, SiteWords.appName)
    }

    func testTheWordsOfTheModelInOrder() {
        let words = shownTexts(in: ShellModel()).map { $0.drawnString }
        XCTAssertEqual(words, ["Snowlight"])
    }
}
