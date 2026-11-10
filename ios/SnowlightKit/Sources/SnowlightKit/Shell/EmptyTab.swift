// A tab that shows its name and nothing else yet.
//
// My School, Map and Call it are this until their screens are built: the page color and
// the tab's name as a page title. No placeholder sentence: the app says nothing it has
// not been given to say.

import SnowlightCore
import SwiftUI

struct EmptyTab: View {
    let model: PlainScreenModel

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.token(.page)
                .ignoresSafeArea()
            PageTitle(model.title)
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
