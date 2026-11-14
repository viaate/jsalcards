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
    /// all, and for a `since` that is not a calendar day. It is the three parts of `parts`,
    /// one after the other.
    static func line(_ days: SeasonDays, since: String?) throws -> ShownText {
        let cut = try parts(days, since: since)
        return ShownText(cut.key.drawnString + cut.joiner.drawnString + cut.rest.drawnString)
    }

    /// The season line in the three parts the site builds it from (copy-season.ts `line`):
    /// its key "This school year"; the joiner, ", " when a since is named and ": " when not;
    /// and the rest, "since Oct 27: closed 2 days, delayed 1." or "closed 2 days, delayed
    /// 1.". The cut is where the site joins them, not a search of the text. It throws where
    /// `line` throws.
    static func parts(_ days: SeasonDays, since: String?) throws -> (key: ShownText, joiner: ShownText, rest: ShownText) {
        let counts: [(count: Int, word: String)] = [
            (count: days.closed, word: "closed"),
            (count: days.delayed, word: "delayed"),
            (count: days.remote, word: "remote"),
            (count: days.earlyDismissal, word: "dismissed early"),
        ]
        var said: [String] = []
        var unit: Int?
        for entry in counts {
            // `whole`: a count of days is a whole number of 0 or more.
            guard entry.count >= 0 else {
                throw SiteRefusal()
            }
            if entry.count > 0 {
                let number = try SiteFormat.number(Double(entry.count))
                said.append(entry.word + " " + number.drawnString)
                if unit == nil {
                    unit = entry.count
                }
            }
        }
        guard let first = said.first, let firstCount = unit else {
            throw SiteRefusal()
        }
        var named = [first + (firstCount == 1 ? " day" : " days")]
        named.append(contentsOf: said.dropFirst())
        let list = named.joined(separator: ", ") + "."
        let key = ShownText("This school year")
        guard let day = since else {
            return (key: key, joiner: ShownText(": "), rest: ShownText(list))
        }
        let from = try SiteFormat.monthDay(day)
        return (key: key, joiner: ShownText(", "), rest: ShownText("since " + from.drawnString + ": " + list))
    }
}
