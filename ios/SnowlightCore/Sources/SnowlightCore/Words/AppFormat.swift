// The app's own formats for My School (M1 4.2a, as the lead ruled): the day line, the
// district line and the season card as the approved draft 3 draws them. Each joins the
// site's own pieces (the weekday, a number, a short month and day, the grades) with the app
// words of Words/AppWords.swift, and nothing else: this file holds no text in quotes, and
// ios/tools/check-ios.mjs refuses one here (`appformat.literal`).
//
// Not public: no code outside SnowlightCore can name this table.

enum AppFormat {
    /// A calendar day as the draft's day line: "Tuesday, January 12". The weekday is the
    /// site's (`SiteFormat.weekday`), the month the app's table, the day the site's number.
    /// It throws where the site's weekday throws: for a text that is not a calendar day.
    static func dayLine(_ localDate: String) throws -> ShownText {
        let weekday = try SiteFormat.weekday(localDate)
        guard let parts = localDateParts(localDate),
              let month = element(AppWords.months, Int(parts.month) - 1) else {
            throw SiteRefusal()
        }
        let day = try SiteFormat.number(Double(parts.day))
        return joined([weekday, AppWords.dayComma, month, AppWords.space, day])
    }

    /// A public school's district and grades: "Synthetic District One · Grades 6–8".
    /// `grades` is the site's own (`SiteFormat.grades`).
    static func districtLine(district: ShownText, grades: ShownText) -> ShownText {
        return joined([district, AppWords.dot, AppWords.grades, AppWords.space, grades])
    }

    /// The counts of the season card: "2 closed · 1 delayed ", or with one count above 0
    /// "2 closed ". Closed and delayed, each above 0, in that order (the site's order, which
    /// leaves out a 0), joined by the dot, and one space after them, which the draft draws
    /// in the counts' own weight. It throws for a count the site's number refuses, and for
    /// no count above 0.
    static func seasonCounts(_ days: SeasonDays) throws -> ShownText {
        let counts: [(count: Int, word: ShownText)] = [
            (count: days.closed, word: AppWords.closed),
            (count: days.delayed, word: AppWords.delayed),
        ]
        var parts: [ShownText] = []
        for entry in counts where entry.count != 0 {
            let number = try SiteFormat.number(Double(entry.count))
            parts.append(joined([number, AppWords.space, entry.word]))
        }
        guard parts.isEmpty == false else {
            throw SiteRefusal()
        }
        let said = parts.map { $0.drawnString }.joined(separator: AppWords.dot.drawnString)
        return ShownText(said + AppWords.space.drawnString)
    }

    /// The day counting began, as the season card says it: "since Oct 27". The day is the
    /// site's `monthDay`; it throws where that throws.
    static func seasonSince(_ since: String) throws -> ShownText {
        let day = try SiteFormat.monthDay(since)
        return joined([AppWords.since, AppWords.space, day])
    }

    /// Pieces of words, one after the other.
    private static func joined(_ pieces: [ShownText]) -> ShownText {
        var characters = String()
        for piece in pieces {
            characters += piece.drawnString
        }
        return ShownText(characters)
    }
}
