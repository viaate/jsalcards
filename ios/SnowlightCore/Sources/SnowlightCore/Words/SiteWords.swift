// The site's fixed words, each beside its key path in web/src/copy.ts.
//
// Not public: no code outside SnowlightCore can name this table, so a view can never
// reach past its screen model for a word. Tests reach it with `@testable import`.

enum SiteWords {
    /// `copy.appName`
    static let appName = ShownText("Snowlight")
}
