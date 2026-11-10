// The names file: the only file in SnowlightKit or the app, outside the debug tour, that
// may hold text in quotes.
//
// It holds names that are never shown: today, system symbol names. Each sits inside a
// small type whose string cannot be read from outside this file, and which hands out only
// what the name is for: a symbol gives its image. Nothing in this file hands out a
// string, so no name here can reach the screen as a word. A script
// (ios/tools/check-ios.mjs) keeps every name here to lower-case letters, digits and dots.
//
// The key the appearance choice is kept under is not here: SnowlightCore keeps the choice
// itself (AppearanceChoice.kept, keep and forget), so its stored word never crosses into
// this package.

import SwiftUI

/// One of Apple's system symbols. It gives its image and nothing else.
struct SymbolName {
    fileprivate let name: String

    var image: Image {
        Image(systemName: name)
    }

    // The four tabs. These are stand-ins: the app's own glyphs come with its icon.
    static let mySchool = SymbolName(name: "house")
    static let map = SymbolName(name: "map")
    static let callIt = SymbolName(name: "checkmark.square")
    static let settings = SymbolName(name: "gearshape")

    /// The tick beside the chosen appearance.
    static let tick = SymbolName(name: "checkmark")
}
