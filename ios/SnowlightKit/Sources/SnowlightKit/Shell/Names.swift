// The names file: the only file in SnowlightKit or the app, outside the debug tour, that
// may hold text in quotes.
//
// It holds names that are never shown: system symbol names, and the asset names of the
// app's own glyphs (Glyphs.xcassets). Each sits inside a small type whose string cannot be
// read from outside this file, and which hands out only what the name is for: a symbol or
// a glyph gives its image. Nothing in this file hands out a string, so no name here can
// reach the screen as a word. A script (ios/tools/check-ios.mjs) keeps every name here to
// lower-case letters, digits and dots.
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

    /// The tick beside the chosen appearance.
    static let tick = SymbolName(name: "checkmark")
}

/// One of the app's own glyphs: approved draft 3's drawings, each one flat filled path in
/// Glyphs.xcassets, drawn as a template in the color around it. It gives its image and
/// nothing else.
struct GlyphName {
    fileprivate let name: String

    /// The image for a tab's icon, inside the tab's Label: the tab's spoken name is the
    /// Label's title, so the asset name is never read.
    var tabImage: Image {
        Image(name, bundle: .module)
    }

    /// The image with no accessibility label, for a drawing beside words: VoiceOver
    /// never reads its asset name.
    var decorative: Image {
        Image(decorative: name, bundle: .module)
    }

    // The four tabs: filled when the tab is chosen, line when it is not.
    static let schoolFill = GlyphName(name: "glyph.school.fill")
    static let schoolLine = GlyphName(name: "glyph.school.line")
    static let mapFill = GlyphName(name: "glyph.map.fill")
    static let mapLine = GlyphName(name: "glyph.map.line")
    static let pickFill = GlyphName(name: "glyph.pick.fill")
    static let pickLine = GlyphName(name: "glyph.pick.line")
    static let gearFill = GlyphName(name: "glyph.gear.fill")
    static let gearLine = GlyphName(name: "glyph.gear.line")

    /// The clock beside the posted time on My School.
    static let clock = GlyphName(name: "glyph.clock")
}
