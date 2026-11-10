// The app's root view: the system's tab bar with the four tabs, then the search tab.
//
// The system draws the bar, its glass and the search button; none of that is drawn here.
// Every word on screen is a field of the shell's model: a view never names a word table
// (they are not public, so the compiler refuses) and holds no text in quotes.

import SnowlightCore
import SwiftUI

/// The root of the app.
public struct RootView: View {
    @StateObject private var appearance: AppearanceStore
    @State private var selection: ScreenID

    public init() {
        #if DEBUG
        // A launch of the picture tour first puts the look it asks for where the app
        // keeps its own choice, so that the app then reads it as it would on any launch.
        Tour.prepare()
        #endif
        _appearance = StateObject(wrappedValue: AppearanceStore())
        _selection = State(initialValue: RootView.firstScreen())
    }

    public var body: some View {
        // In debug builds the picture tour (Tour/) watches the shell appear, so that it
        // can write the words of the screen's model for the picture being taken; on the
        // one tour launch that asks for the machine probe, it shows the probe in place
        // of the shell. A release build holds none of it.
        #if DEBUG
        shell.modifier(TourStage(appearance: appearance))
        #else
        shell
        #endif
    }

    /// The screen the app opens to: My School, or the screen a tour launch names.
    private static func firstScreen() -> ScreenID {
        #if DEBUG
        if let screen = TourPlan.ofThisLaunch?.screen {
            return screen
        }
        #endif
        return ScreenID.mySchool
    }

    /// What the shell shows, for the appearance now chosen.
    private var model: ShellModel {
        ShellModel(appearance: appearance.choice)
    }

    private var shell: some View {
        TabView(selection: $selection) {
            Tab(value: ScreenID.mySchool) {
                EmptyTab(model: model.mySchool)
            } label: {
                tabLabel(model.tabs.mySchool, SymbolName.mySchool)
            }
            Tab(value: ScreenID.map) {
                EmptyTab(model: model.map)
            } label: {
                tabLabel(model.tabs.map, SymbolName.map)
            }
            Tab(value: ScreenID.callIt) {
                EmptyTab(model: model.callIt)
            } label: {
                tabLabel(model.tabs.callIt, SymbolName.callIt)
            }
            Tab(value: ScreenID.settings) {
                SettingsScreen(
                    model: model.settings,
                    choose: { choice in
                        appearance.choose(choice)
                    }
                )
            } label: {
                tabLabel(model.tabs.settings, SymbolName.settings)
            }
            // The system gives this tab its own place beside the bar, and its symbol.
            Tab(value: ScreenID.search, role: .search) {
                SearchTab(model: model.search)
            }
        }
        .tint(Color.token(.ink))
        .background {
            WindowStyle(choice: appearance.choice)
                .frame(width: 0, height: 0)
                .accessibilityHidden(true)
        }
    }

    /// A tab's label: its name from the model, and its symbol.
    private func tabLabel(_ tab: TabModel, _ symbol: SymbolName) -> some View {
        Label {
            ShownLabel(tab.title)
        } icon: {
            symbol.image
        }
    }
}
