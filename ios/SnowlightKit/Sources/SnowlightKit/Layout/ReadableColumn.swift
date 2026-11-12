// The readable column: the layout rules of SnowlightCore's ContentLayout, put on a view.
//
// A screen's content is laid out inside the safe area, so it stops where the system's own
// controls begin (on the closed iPhone Duo they stand in a column on the right), and it is
// held to the readable width at the leading edge of the room it is given. Nothing here
// reads the device, its idiom, its orientation or its screen, and nothing is sized for one
// phone: the room is whatever the window gives, and SwiftUI lays the view out again
// whenever that changes, a fold or an unfold of the Duo included (tools/check-ios.mjs,
// rule view.layout).
//
// On every iPhone and on the closed Duo the room is narrower than the readable limit, so
// this changes nothing there: the content keeps the place it had.

import SnowlightCore
import SwiftUI

extension View {
    /// Holds the content to the readable width, at the top leading corner of the room it
    /// is given. Where the room is narrower, the content takes the whole room, as before.
    func readableColumn() -> some View {
        frame(maxWidth: CGFloat(ContentLayout.readableLimit), alignment: .topLeading)
    }
}
