// The site's fixed words, each beside its key path in web/src/copy.ts.
//
// Not public: no code outside SnowlightCore can name this table, so a view can never
// reach past its screen model for a word. Tests reach it with `@testable import` and
// compare each word with the site's own, read from the golden file copy.json.

enum SiteWords {
    /// `copy.appName`
    static let appName = ShownText("Snowlight")

    /// `copy.search.placeholder`
    static let searchPlaceholder = ShownText("Search a school, city, or ZIP")
}
