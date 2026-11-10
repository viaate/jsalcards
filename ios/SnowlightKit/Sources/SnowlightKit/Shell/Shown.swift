// The one place that turns a ShownText into drawn text.
//
// Every string the app draws goes through one of the two things in this file. It is the
// only file in SnowlightKit or the app that makes a text view, and the only one that
// reads a ShownText's characters, so no other view can draw words of its own or hand
// characters to a control that takes a plain string: controls are given the text view
// below, or a label built from ShownLabel.

import SnowlightCore
import SwiftUI

/// Draws one `ShownText`.
struct ShownLabel: View {
    private let shown: ShownText

    init(_ text: ShownText) {
        shown = text
    }

    var body: some View {
        shown.text
    }
}

extension ShownText {
    /// For the system calls that want a text view: a search prompt, a navigation title,
    /// a tab's label, an accessibility label, value or hint.
    var text: Text {
        Text(verbatim: drawnString)
    }
}
