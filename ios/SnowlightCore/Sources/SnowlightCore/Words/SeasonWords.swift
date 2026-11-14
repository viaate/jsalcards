// The school panel's season line (web/src/copy-season.ts `seasonFormat.line`): how many days
// the school has been closed, delayed, remote or dismissed early this school year, from
// live/season.json (Files/SeasonFile.swift). It says only what the file counts, and names
// the day counting began whenever that is later than the school year's first day.
//
// Not public: no code outside SnowlightCore can name this table.

enum SeasonWords {
    /// "This school year: closed 2 days, delayed 1.", or "This school year, since Oct 27:
    /// closed 1 day." Each status with a day, in the order closed, delayed, remote,
    /// dismissed early; the first carries its unit. `since` is nil when counting began with
    /// the school year. It throws where the site's does: for a negative count, for no day at
    /// all, and for a `since` that is not a calendar day.
    static func line(_ days: SeasonDays, since: String?) throws -> ShownText {
        let counts: [(count: Int, word: String)] = [
            (count: days.closed, word: "closed"),
            (count: days.delayed, word: "delayed"),
            (count: days.remote, word: "remote"),
            (count: days.earlyDismissal, word: "dismissed early"),
        ]
        var parts: [String] = []
        var unit: Int?
        for entry in counts {
            // `whole`: a count of days is a whole number of 0 or more.
            guard entry.count >= 0 else {
                throw SiteRefusal()
            }
            if entry.count > 0 {
                let said = try SiteFormat.number(Double(entry.count))
                parts.append(entry.word + " " + said.drawnString)
                if unit == nil {
                    unit = entry.count
                }
            }
        }
        guard let first = parts.first, let firstCount = unit else {
            throw SiteRefusal()
        }
        var said = [first + (firstCount == 1 ? " day" : " days")]
        said.append(contentsOf: parts.dropFirst())
        var when = "This school year"
        if let day = since {
            let named = try SiteFormat.monthDay(day)
            when += ", since " + named.drawnString
        }
        return ShownText(when + ": " + said.joined(separator: ", ") + ".")
    }
}
