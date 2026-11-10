// The names file: the only file in SnowlightKit or the app, outside the debug tour, that
// may hold text in quotes.
//
// It holds names that are never shown: system symbol names and settings keys. Each sits
// inside a small type whose string cannot be read from outside this file, and which hands
// out only what the name is for: a symbol gives its image, a settings key reads and
// writes a stored value. Nothing in this file hands out a string, so no name here can
// reach the screen as a word. A script (ios/tools/check-ios.mjs) keeps every name here to
// lower-case letters, digits and dots.

import Foundation
import SnowlightCore
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

/// A key in the app's settings store. It reads and writes the stored value and nothing else.
struct DefaultsKey {
    fileprivate let key: String

    /// Where the appearance choice is kept.
    static let appearance = DefaultsKey(key: "appearance")

    /// The appearance kept under this key. Nothing kept, or a value this build does not
    /// know, reads as System.
    func readAppearance(in store: UserDefaults) -> AppearanceChoice {
        AppearanceChoice(stored: store.string(forKey: key))
    }

    /// Keeps an appearance choice under this key.
    func keep(_ choice: AppearanceChoice, in store: UserDefaults) {
        store.set(choice.stored, forKey: key)
    }

    /// Forgets what is kept under this key.
    func forget(in store: UserDefaults) {
        store.removeObject(forKey: key)
    }
}
