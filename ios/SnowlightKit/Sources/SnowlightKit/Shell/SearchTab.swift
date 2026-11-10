// The search tab: the system's search field with the site's prompt, and nothing else yet.
//
// The system draws the field, its glass and its button. The prompt reaches this view as a
// field of the screen's model, never from a word table.

import SnowlightCore
import SwiftUI

struct SearchTab: View {
    let model: SearchModel

    /// What has been typed. Nothing reads it yet: search itself comes later.
    @State private var query = SearchQuery()

    var body: some View {
        NavigationStack {
            Color.token(.page)
                .ignoresSafeArea()
                .searchable(text: $query.typed, prompt: model.prompt.text)
        }
    }
}
