// The words only the app has: the site has no tab bar, no appearance setting and no Outside
// screen setting, and My School writes its day line, district line and season card as the
// approved draft 3 draws them.
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

    // The Outside screen setting, shown only on an iPhone Duo.

    /// Approved: owner, Nov 12 2026, on the drawn Settings row: "I like the wording".
    static let outsideScreen = ShownText("Outside screen")
    /// Approved: owner, Nov 12 2026, on the drawn Settings row.
    static let whenYourIPhoneIsClosed = ShownText("When your iPhone is closed")
    /// Approved: owner, Nov 12 2026, on the drawn Settings row (layout A, the default).
    static let besideTheMap = ShownText("Beside the map")
    /// Approved: owner, Nov 12 2026, on the drawn Settings row (layout B, the owner's own phrase).
    static let underTheControls = ShownText("Under the controls")

    // My School: the pieces of its day line, district line and season card (M1 4.2a). Each
    // is in the owner-approved draft-3 picture, or is the punctuation between its words, and
    // is joined to the site's own words only by Words/AppFormat.swift.

    /// Approved: lead rulings of Nov 14 on SPEC r3 and r4, RD-7 (a): the 12 English month names, through the
    /// owner-approved draft-3 picture. One name a line, in calendar order: check-ios lets "May" pass only as the
    /// fifth line of this table.
    static let months: [ShownText] = [
        ShownText("January"),
        ShownText("February"),
        ShownText("March"),
        ShownText("April"),
        ShownText("May"),
        ShownText("June"),
        ShownText("July"),
        ShownText("August"),
        ShownText("September"),
        ShownText("October"),
        ShownText("November"),
        ShownText("December"),
    ]
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-7 (a), as drawn (H:85): after the weekday.
    static let dayComma = ShownText(", ")
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-6 (a), RD-7 (a) and RD-10, as drawn.
    static let space = ShownText(" ")
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-6 (a) and RD-10: the site's dot (`DOT`),
    /// typed as its raw characters.
    static let dot = ShownText(" · ")
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-6 (a): "Grades" is approved.
    static let grades = ShownText("Grades")
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-10, as drawn (H:100).
    static let closed = ShownText("closed")
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-10, as drawn (H:100).
    static let delayed = ShownText("delayed")
    /// Approved: lead ruling of Nov 14 on SPEC r3, RD-10, as drawn (H:100).
    static let since = ShownText("since")
}
