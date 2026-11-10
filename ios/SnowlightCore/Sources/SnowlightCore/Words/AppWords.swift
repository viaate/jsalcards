// The words only the app has: the site has no tab bar and no appearance setting.
//
// Each is also a line of ios/tools/app-words.txt, which says whether the owner has
// approved it and where that was said. A script (ios/tools/check-ios.mjs) fails the build
// when the two lists differ, and holds every word here to the site's own list of banned
// words. A word comes into this file only after the owner has seen it, or marked pending.
//
// Not public: no code outside SnowlightCore can name this table.

enum AppWords {
    // The four tabs, in the order the owner ruled.

    /// Approved: owner ruling, the four tabs.
    static let mySchool = ShownText("My School")
    /// Approved: owner ruling, the four tabs.
    static let map = ShownText("Map")
    /// Approved: owner ruling, the four tabs.
    static let callIt = ShownText("Call it")
    /// Approved: owner ruling, the four tabs.
    static let settings = ShownText("Settings")

    // The appearance setting.

    /// Approved: owner request of Nov 10, 2026, the look can be changed in Settings.
    static let appearance = ShownText("Appearance")
    /// Approved: owner request of Nov 10, 2026.
    static let system = ShownText("System")
    /// Approved: owner request of Nov 10, 2026.
    static let light = ShownText("Light")
    /// Approved: owner request of Nov 10, 2026.
    static let dark = ShownText("Dark")
    /// PENDING OWNER: from the unfinished light and dark pictures, not yet approved.
    static let followsYourPhone = ShownText("Follows your iPhone")
}
