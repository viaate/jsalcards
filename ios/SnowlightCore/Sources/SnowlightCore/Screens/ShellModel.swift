// The model of the app's shell: everything the shell may show, as values.
//
// A screen model arranges words; it cannot type one. This folder holds no text in
// quotes: every word here is a `ShownText` handed over by `Words/`. SwiftUI draws the
// model and nothing else, and the words of the screen are read off the model itself
// with `shownTexts(in:)`.

/// What the app's shell shows. For now one field: the app's name.
public struct ShellModel: Equatable, Sendable {
    /// The app's name, as the site spells it.
    public let appName: ShownText

    public init() {
        appName = SiteWords.appName
    }
}
