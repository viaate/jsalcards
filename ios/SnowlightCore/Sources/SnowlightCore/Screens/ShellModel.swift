// The model of the app's shell: everything the shell may show, as values.
//
// A screen model arranges words; it cannot type one. This folder holds no text in
// quotes: every word here is a `ShownText` handed over by `Words/`. SwiftUI draws the
// model and nothing else, and the words of a screen are read off its model with
// `shownTexts(in:)`, in declaration order: the four tab titles, then the screen's own
// fields. Nobody keeps that list by hand, so it cannot fall behind the model.
//
// Rule for every later screen model, stated now: a model that shows a time or a day takes
// the school's zone and the viewer's zone as two parameters. Times a person reads are
// told on the viewer's clock, days on the school's. The shell shows neither.

/// The five screens of the shell: the four tabs in the order the owner ruled, then search.
public enum ScreenID: Equatable, Hashable, Sendable, CaseIterable {
    case mySchool
    case map
    case callIt
    case settings
    case search
}

/// One tab of the bar: which screen it opens, and its name.
public struct TabModel: Equatable, Sendable {
    public let id: ScreenID
    public let title: ShownText
}

/// The four tabs of the bar, declared in the order they are shown. The search button
/// beside them is the system's and has no word of ours.
public struct TabsModel: Equatable, Sendable {
    public let mySchool: TabModel
    public let map: TabModel
    public let callIt: TabModel
    public let settings: TabModel

    /// The four tabs, first to last.
    public var inOrder: [TabModel] {
        [mySchool, map, callIt, settings]
    }
}

/// A screen that shows its name and nothing else yet.
public struct PlainScreenModel: Equatable, Sendable {
    public let title: ShownText
}

/// The search screen: the prompt in its empty field.
public struct SearchModel: Equatable, Sendable {
    public let prompt: ShownText
}

/// What a person has typed into the search field. It starts empty. It is input, not one
/// of the app's words: no screen model shows it, and `shownTexts(in:)` never reports it.
public struct SearchQuery: Equatable, Sendable {
    public var typed: String

    public init() {
        typed = String()
    }
}

/// One of the three appearance tiles.
public struct AppearanceOption: Equatable, Sendable {
    public let choice: AppearanceChoice
    public let label: ShownText
    public let isChosen: Bool
}

/// The Settings screen: its title and its one section, Appearance.
public struct SettingsModel: Equatable, Sendable {
    public let title: ShownText
    public let heading: ShownText
    /// The line beside the heading. Present only while System is chosen.
    public let followsPhone: ShownText?
    /// System, Light, Dark, in that order.
    public let options: [AppearanceOption]
    public let chosen: AppearanceChoice
}

/// What one screen shows below the bar.
public enum ScreenContent: Equatable, Sendable {
    case plain(PlainScreenModel)
    case settings(SettingsModel)
    case search(SearchModel)
}

/// Everything one screen shows: the bar's four tabs, then the screen's own fields.
public struct ScreenModel: Equatable, Sendable {
    public let tabs: TabsModel
    public let content: ScreenContent
}

/// What the app's shell shows, for one appearance choice.
public struct ShellModel: Equatable, Sendable {
    public let tabs: TabsModel
    public let mySchool: PlainScreenModel
    public let map: PlainScreenModel
    public let callIt: PlainScreenModel
    public let settings: SettingsModel
    public let search: SearchModel

    public init(appearance: AppearanceChoice) {
        tabs = TabsModel(
            mySchool: TabModel(id: .mySchool, title: AppWords.mySchool),
            map: TabModel(id: .map, title: AppWords.map),
            callIt: TabModel(id: .callIt, title: AppWords.callIt),
            settings: TabModel(id: .settings, title: AppWords.settings)
        )
        mySchool = PlainScreenModel(title: AppWords.mySchool)
        map = PlainScreenModel(title: AppWords.map)
        callIt = PlainScreenModel(title: AppWords.callIt)
        var options: [AppearanceOption] = []
        for choice in AppearanceChoice.allCases {
            options.append(
                AppearanceOption(
                    choice: choice,
                    label: ShellModel.label(of: choice),
                    isChosen: choice == appearance
                )
            )
        }
        settings = SettingsModel(
            title: AppWords.settings,
            heading: AppWords.appearance,
            followsPhone: appearance == .system ? AppWords.followsYourPhone : nil,
            options: options,
            chosen: appearance
        )
        search = SearchModel(prompt: SiteWords.searchPlaceholder)
    }

    /// One screen of the shell, as it is shown: the bar and the screen's own fields.
    public func screen(_ id: ScreenID) -> ScreenModel {
        switch id {
        case .mySchool:
            return ScreenModel(tabs: tabs, content: .plain(mySchool))
        case .map:
            return ScreenModel(tabs: tabs, content: .plain(map))
        case .callIt:
            return ScreenModel(tabs: tabs, content: .plain(callIt))
        case .settings:
            return ScreenModel(tabs: tabs, content: .settings(settings))
        case .search:
            return ScreenModel(tabs: tabs, content: .search(search))
        }
    }

    private static func label(of choice: AppearanceChoice) -> ShownText {
        switch choice {
        case .system:
            return AppWords.system
        case .light:
            return AppWords.light
        case .dark:
            return AppWords.dark
        }
    }
}
