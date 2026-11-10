import XCTest
@testable import SnowlightCore

/// The shell's model: tab order and titles; "Follows your iPhone" only on System; and the
/// words of each of the five screens, read off the model, in order. Written cases.
final class ShellModelTests: XCTestCase {
    private let bar = ["My School", "Map", "Call it", "Settings"]

    private func words(of screen: ScreenID, appearance: AppearanceChoice) -> [String] {
        shownTexts(in: ShellModel(appearance: appearance).screen(screen)).map { $0.drawnString }
    }

    func testTheFiveScreensInOrder() {
        XCTAssertEqual(ScreenID.allCases, [.mySchool, .map, .callIt, .settings, .search])
    }

    func testTabOrderAndTitles() {
        for appearance in AppearanceChoice.allCases {
            let tabs = ShellModel(appearance: appearance).tabs.inOrder
            XCTAssertEqual(tabs.map { $0.id }, [.mySchool, .map, .callIt, .settings])
            XCTAssertEqual(tabs.map { $0.title.drawnString }, bar)
        }
    }

    func testTheTabTitlesAreTheApprovedAppWords() {
        let tabs = ShellModel(appearance: .system).tabs
        XCTAssertEqual(tabs.mySchool.title, AppWords.mySchool)
        XCTAssertEqual(tabs.map.title, AppWords.map)
        XCTAssertEqual(tabs.callIt.title, AppWords.callIt)
        XCTAssertEqual(tabs.settings.title, AppWords.settings)
    }

    func testFollowsYourPhoneShowsOnlyOnSystem() {
        XCTAssertEqual(ShellModel(appearance: .system).settings.followsPhone, AppWords.followsYourPhone)
        XCTAssertEqual(ShellModel(appearance: .system).settings.followsPhone?.drawnString, "Follows your iPhone")
        XCTAssertNil(ShellModel(appearance: .light).settings.followsPhone)
        XCTAssertNil(ShellModel(appearance: .dark).settings.followsPhone)
    }

    func testTheThreeOptionsAndTheChosenOne() {
        for appearance in AppearanceChoice.allCases {
            let settings = ShellModel(appearance: appearance).settings
            XCTAssertEqual(settings.chosen, appearance)
            XCTAssertEqual(settings.options.map { $0.choice }, [.system, .light, .dark])
            XCTAssertEqual(settings.options.map { $0.label.drawnString }, ["System", "Light", "Dark"])
            XCTAssertEqual(settings.options.filter { $0.isChosen }.map { $0.choice }, [appearance])
        }
    }

    func testTheSearchPromptIsTheSites() {
        XCTAssertEqual(ShellModel(appearance: .system).search.prompt, SiteWords.searchPlaceholder)
    }

    func testTheWordsOfTheThreePlainScreens() {
        for appearance in AppearanceChoice.allCases {
            XCTAssertEqual(words(of: .mySchool, appearance: appearance), bar + ["My School"])
            XCTAssertEqual(words(of: .map, appearance: appearance), bar + ["Map"])
            XCTAssertEqual(words(of: .callIt, appearance: appearance), bar + ["Call it"])
        }
    }

    func testTheWordsOfSettings() {
        XCTAssertEqual(
            words(of: .settings, appearance: .system),
            bar + ["Settings", "Appearance", "Follows your iPhone", "System", "Light", "Dark"]
        )
        XCTAssertEqual(
            words(of: .settings, appearance: .light),
            bar + ["Settings", "Appearance", "System", "Light", "Dark"]
        )
        XCTAssertEqual(
            words(of: .settings, appearance: .dark),
            bar + ["Settings", "Appearance", "System", "Light", "Dark"]
        )
    }

    func testTheWordsOfSearch() {
        for appearance in AppearanceChoice.allCases {
            XCTAssertEqual(words(of: .search, appearance: appearance), bar + ["Search a school, city, or ZIP"])
        }
    }

    func testWhatWasTypedIntoSearchIsNeverOneOfTheScreensWords() {
        var query = SearchQuery()
        XCTAssertEqual(query.typed, "")
        query.typed = "typed by a person"
        XCTAssertEqual(shownTexts(in: query), [])
    }
}
