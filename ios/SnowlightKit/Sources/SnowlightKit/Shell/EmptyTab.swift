// A tab that shows its name and nothing else yet.
//
// My School, Map and Call it are this until their screens are built: the page color and
// the tab's name as a page title. No placeholder sentence: the app says nothing it has
// not been given to say. The title keeps to the readable column
// (Layout/ReadableColumn.swift). The ground reads the Outside screen layout value
// (Layout/SideControls.swift): on the closed iPhone Duo with Beside the map chosen it stops
// where the system's side controls begin; everywhere else it runs under them. Under it, the
// page color runs to every edge, so that where the ground stops the page goes on under
// the side controls: a plain tab is one even page, as on every other phone, and only the
// debug tour's teal ground shows where Beside the map stops (without
// it the window's own black showed beside the dark page).

import SnowlightCore
import SwiftUI

struct EmptyTab: View {
    let model: PlainScreenModel

    /// The page color, but in the debug tour's pictures of where the ground stops.
    @Environment(\.placeholderGround) private var ground

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.token(.page)
                .ignoresSafeArea()
            PageGround(token: ground)
            PageTitle(model.title)
                .readableColumn()
        }
    }
}

/// A page's title, in the `title.page` style, on the 20 point side margin.
struct PageTitle: View {
    private let title: ShownText

    init(_ title: ShownText) {
        self.title = title
    }

    var body: some View {
        ShownLabel(title)
            .typeStyle(.titlePage)
            .foregroundStyle(Color.token(.ink))
            .accessibilityAddTraits(.isHeader)
            .padding(.horizontal, 20)
            .padding(.top, 8)
    }
}
