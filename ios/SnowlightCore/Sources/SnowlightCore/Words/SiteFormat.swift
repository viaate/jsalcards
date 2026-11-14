// The site's formatters: the words that carry a live value, counts, times, days, delays and
// chances (web/src/copy-format.ts `format`; web/src/copy-chance.ts `chanceFormat` for
// `weekday`, `chanceOn`, `chanceNumber` and `delayInstead`). Each is written by hand: month
// and weekday names come from the small English tables below, with no formatter of the
// system's, so the app's characters are the site's whatever the phone's language, region or
// 24-hour setting.
//
// Where the site's function throws, this one throws (`SiteRefusal`); where it returns null,
// this one returns nil; `delay` and `dismissal` can do both and keep the two apart. The site
// relies on the difference: no detail is not a refusal.
//
// Not public: no code outside SnowlightCore can name this table.

enum SiteFormat {
    /// Between a time and AM or PM, so "6:42 AM" never breaks across lines (`NBSP`).
    static let noBreakSpace = "\u{00A0}"
    /// Between two parts of one line: "Live · 6:42 AM" (`DOT`).
    static let dot = " \u{00B7} "
    /// The largest whole number a count may be (`Number.MAX_SAFE_INTEGER`).
    private static let maxSafeInteger: Double = 9_007_199_254_740_991

    private static let shortMonths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    private static let shortWeekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    private static let longWeekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    // Joining --------------------------------------------------------------------------

    /// Parts of one line with the site's dot between them, as school.ts does with
    /// `join(DOT)`; nil for no part.
    static func dotted(_ parts: [ShownText]) -> ShownText? {
        guard !parts.isEmpty else {
            return nil
        }
        return ShownText(parts.map { $0.drawnString }.joined(separator: dot))
    }

    // Numbers --------------------------------------------------------------------------

    /// A whole number with thousands separators: "1,284" (copy.ts `number`). It throws for
    /// anything but a whole number from 0 to `Number.MAX_SAFE_INTEGER` (`checkCount`).
    static func number(_ n: Double) throws -> ShownText {
        return ShownText(try numberText(n))
    }

    private static func numberText(_ n: Double) throws -> String {
        guard isInteger(n), n >= 0, n <= maxSafeInteger, let whole = Int64(exactly: n) else {
            throw SiteRefusal()
        }
        // Intl writes the negative zero with its sign.
        let sign = (n == 0 && n.sign == .minus) ? "-" : ""
        let digits = Array("\(whole)")
        var text = ""
        for (index, digit) in digits.enumerated() {
            if index > 0 && (digits.count - index) % 3 == 0 {
                text += ","
            }
            text.append(digit)
        }
        return sign + text
    }

    /// "1 minute", "2 hours": a count and its noun (`plural`).
    private static func plural(_ n: Int, _ one: String, _ other: String) throws -> String {
        return try numberText(Double(n)) + " " + (n == 1 ? one : other)
    }

    // Times ----------------------------------------------------------------------------

    /// "6:42 AM" from an hour (0 to 23) and a minute (`clockText`).
    static func clockText(_ hour24: Int, _ minute: Int) -> ShownText {
        return ShownText(clockString(hour24, minute))
    }

    private static func clockString(_ hour24: Int, _ minute: Int) -> String {
        let hour = hour24 % 12 == 0 ? 12 : hour24 % 12
        let minuteText = minute < 10 ? "0\(minute)" : "\(minute)"
        let half = hour24 < 12 ? "AM" : "PM"
        return "\(hour):\(minuteText)\(noBreakSpace)\(half)"
    }

    /// A local wall-clock time from minutes after midnight: 630 is "10:30 AM" (`clock`). It
    /// throws for anything but a whole number from 0 to 1439.
    static func clock(_ minuteOfDay: Double) throws -> ShownText {
        return ShownText(try clockOf(minuteOfDay))
    }

    private static func clockOf(_ minuteOfDay: Double) throws -> String {
        guard isInteger(minuteOfDay), minuteOfDay >= 0, minuteOfDay < 1440 else {
            throw SiteRefusal()
        }
        let minute = Int(minuteOfDay)
        return clockString(minute / 60, minute % 60)
    }

    /// An instant as a time of day on a zone's clock: "6:42 AM" (`time`). It throws for a
    /// clock not known.
    static func time(_ instant: Int64, zone: String) throws -> ShownText {
        return ShownText(try timeOf(instant, zone))
    }

    private static func timeOf(_ instant: Int64, _ zone: String) throws -> String {
        guard let wall = wallTime(instant, zone) else {
            throw SiteRefusal()
        }
        return clockString(wall.minute / 60, wall.minute % 60)
    }

    /// The calendar day of an instant on a zone's clock, or the site's refusal
    /// (copy-format.ts `localDay`).
    private static func localDayOf(_ instant: Int64, _ zone: String) throws -> String {
        guard let day = localDay(instant, zone) else {
            throw SiteRefusal()
        }
        return day
    }

    // Days -----------------------------------------------------------------------------

    /// The year, month (1 to 12), day and weekday (0 Sunday) of a calendar day, read as
    /// `parseLocalDate` reads it.
    private static func partsOf(_ localDate: String) throws -> (year: Int64, month: Int, day: Int64, weekday: Int) {
        let ms = try parseLocalDate(localDate)
        let days = floorDivide(ms, dayMs)
        let civil = civilFromDays(days)
        return (civil.year, Int(civil.month), civil.day, weekdayIndex(days))
    }

    private static func monthName(_ month: Int) throws -> String {
        guard let name = element(shortMonths, month - 1) else {
            throw SiteRefusal()
        }
        return name
    }

    /// A calendar day: "Mon, Jan 12" (`day`).
    static func day(_ localDate: String) throws -> ShownText {
        return ShownText(try dayOf(localDate))
    }

    private static func dayOf(_ localDate: String) throws -> String {
        let parts = try partsOf(localDate)
        guard let weekday = element(shortWeekdays, parts.weekday) else {
            throw SiteRefusal()
        }
        let month = try monthName(parts.month)
        return "\(weekday), \(month) \(parts.day)"
    }

    /// A calendar day without its weekday: "Jan 12" (`monthDay`).
    static func monthDay(_ localDate: String) throws -> ShownText {
        let parts = try partsOf(localDate)
        let month = try monthName(parts.month)
        return ShownText("\(month) \(parts.day)")
    }

    /// A calendar day with its year: "Jan 12, 2026" (`dayWithYear`).
    static func dayWithYear(_ localDate: String) throws -> ShownText {
        let parts = try partsOf(localDate)
        let month = try monthName(parts.month)
        return ShownText("\(month) \(parts.day), \(parts.year)")
    }

    /// A calendar day as its weekday: "Tuesday" (copy-chance.ts `weekday`).
    static func weekday(_ localDate: String) throws -> ShownText {
        return ShownText(try weekdayOf(localDate))
    }

    private static func weekdayOf(_ localDate: String) throws -> String {
        let parts = try partsOf(localDate)
        guard let name = element(longWeekdays, parts.weekday) else {
            throw SiteRefusal()
        }
        return name
    }

    /// "Chance of no school Tuesday", for a calendar day (copy-chance.ts `chanceOn`).
    static func chanceOn(_ localDate: String) throws -> ShownText {
        let weekday = try weekdayOf(localDate)
        return ShownText(SiteWords.chanceNoSchool.drawnString + " " + weekday)
    }

    // Stamps ---------------------------------------------------------------------------

    /// The time alone when `instant` falls on the same day as `now` on the zone's clock, else
    /// the day and the time (`stamp`).
    private static func stamp(_ instant: Int64, _ zone: String, _ now: Int64) throws -> String {
        let when = try timeOf(instant, zone)
        let localDate = try localDayOf(instant, zone)
        let today = try localDayOf(now, zone)
        if localDate == today {
            return when
        }
        let dated = try dayOf(localDate)
        return dated + ", " + when
    }

    /// The live update time on the viewer's clock: "Live · 6:42 AM" (`liveAt`).
    static func liveAt(_ instant: Int64, zone: String) throws -> ShownText {
        let when = try timeOf(instant, zone)
        return ShownText(SiteWords.navLive.drawnString + dot + when)
    }

    private static func updatedText(_ instant: Int64, _ zone: String, _ now: Int64) throws -> String {
        let when = try stamp(instant, zone, now)
        return SiteWords.liveUpdated.drawnString + " " + when
    }

    /// An older update: "Updated 6:42 AM", or "Updated Mon, Jan 12, 6:42 AM" on another day
    /// (`updatedAt`).
    static func updatedAt(_ instant: Int64, zone: String, now: Int64) throws -> ShownText {
        return ShownText(try updatedText(instant, zone, now))
    }

    /// No connection: "Offline · Updated 6:42 AM" (`offline`).
    static func offline(_ instant: Int64, zone: String, now: Int64) throws -> ShownText {
        let updated = try updatedText(instant, zone, now)
        return ShownText(SiteWords.liveOffline.drawnString + dot + updated)
    }

    /// When a school posted its status: "Posted 5:12 AM", or "Posted Sun, Jan 11, 8:30 PM"
    /// (`posted`).
    static func posted(_ instant: Int64, zone: String, now: Int64) throws -> ShownText {
        let when = try stamp(instant, zone, now)
        return ShownText(SiteWords.detailPosted.drawnString + " " + when)
    }

    /// A school's status line for its day, measured against today on the school's clock:
    /// "Closed today", "Delayed start tomorrow", "Closed Mon, Jan 12" (`statusOn`).
    static func statusOn(_ status: ClosingStatus, day localDate: String, now: Int64, zone: String) throws -> ShownText {
        let dayStart = try parseLocalDate(localDate)
        let today = try localDayOf(now, zone)
        let todayStart = try parseLocalDate(today)
        // Both are UTC midnights, so the division is exact (the site rounds it).
        let offset = (dayStart - todayStart) / dayMs
        let line = SiteWords.statusLine(status)
        if offset == 0 {
            return line.today
        }
        if offset == 1 {
            return line.tomorrow
        }
        let dated = try dayOf(localDate)
        return ShownText(line.on.drawnString + " " + dated)
    }

    // Delays ---------------------------------------------------------------------------

    /// A shift of 1 to 720 whole minutes, or the site's refusal (`checkShift`).
    private static func checkShift(_ minutes: Double) throws -> Int {
        guard isInteger(minutes), minutes >= 1, minutes <= 720 else {
            throw SiteRefusal()
        }
        return Int(minutes)
    }

    /// A shift as a noun: "1 hour", "90 minutes", "2½ hours" (`durationNoun`).
    private static func durationNoun(_ minutes: Int) throws -> String {
        let hours = minutes / 60
        if minutes < 60 {
            return try plural(minutes, "minute", "minutes")
        }
        if minutes % 60 == 0 {
            return try plural(hours, "hour", "hours")
        }
        if minutes > 120 && minutes % 60 == 30 {
            return "\(hours)\u{00BD} hours"
        }
        return try plural(minutes, "minute", "minutes")
    }

    /// A shift as an adjective: "1-hour", "90-minute", "2½-hour" (`durationAdjective`).
    private static func durationAdjective(_ minutes: Int) throws -> String {
        let hours = minutes / 60
        if minutes >= 60 && minutes % 60 == 0 {
            return "\(hours)-hour"
        }
        if minutes > 120 && minutes % 60 == 30 {
            return "\(hours)\u{00BD}-hour"
        }
        return try numberText(Double(minutes)) + "-minute"
    }

    /// The detail of a delayed start: "2-hour delay", "Starts at 10:00 AM",
    /// "2-hour delay · Starts at 10:00 AM"; nil when neither is known (`delay`). It throws
    /// for a shift or a clock the site refuses.
    static func delay(shift: Double?, clock: Double?) throws -> ShownText? {
        var parts: [String] = []
        if let minutes = shift {
            parts.append(try durationAdjective(try checkShift(minutes)) + " delay")
        }
        if let minute = clock {
            let at = try clockOf(minute)
            parts.append("Starts at " + at)
        }
        return parts.isEmpty ? nil : ShownText(parts.joined(separator: dot))
    }

    /// The detail of an early dismissal: "2 hours early", "Dismissal at 12:30 PM",
    /// "Dismissal at 12:30 PM · 2 hours early"; nil when neither is known (`dismissal`). It
    /// throws for a shift or a clock the site refuses.
    static func dismissal(shift: Double?, clock: Double?) throws -> ShownText? {
        var parts: [String] = []
        if let minute = clock {
            let at = try clockOf(minute)
            parts.append("Dismissal at " + at)
        }
        if let minutes = shift {
            parts.append(try durationNoun(try checkShift(minutes)) + " early")
        }
        return parts.isEmpty ? nil : ShownText(parts.joined(separator: dot))
    }

    // Chances --------------------------------------------------------------------------

    /// A probability from 0 to 1 as a whole percentage: "34%", "<1%", ">99%" (`chance`). It
    /// throws for anything but a finite number from 0 to 1.
    static func chance(_ probability: Double) throws -> ShownText {
        return ShownText(try chanceText(probability))
    }

    private static func chanceText(_ probability: Double) throws -> String {
        guard probability.isFinite, probability >= 0, probability <= 1 else {
            throw SiteRefusal()
        }
        // Math.round of the product the site computes; for a number of 0 or more its tie goes up.
        let percent = (probability * 100).rounded(.toNearestOrAwayFromZero)
        if percent < 1 {
            return "<1%"
        }
        if percent > 99 {
            return ">99%"
        }
        return "\(Int(percent))%"
    }

    /// The headline number without its sign: "64", or "<1" and ">99" at the ends
    /// (copy-chance.ts `chanceNumber`).
    static func chanceNumber(_ probability: Double) throws -> ShownText {
        let text = try chanceText(probability)
        return ShownText(String(text.dropLast()))
    }

    /// The delayed start, as one plain line: "18% chance of a delayed start instead"
    /// (copy-chance.ts `delayInstead`).
    static func delayInstead(_ probability: Double) throws -> ShownText {
        let text = try chanceText(probability)
        return ShownText(text + " chance of a delayed start instead")
    }

    // Grades ---------------------------------------------------------------------------

    /// How a grade code reads (NCES codes: PK, TK, KG, 01 to 13), letter for letter as the
    /// site's table and pattern read it (`gradeName`).
    private static func gradeName(_ code: String) throws -> String {
        let units = Array(code.utf16)
        if units == Array("PK".utf16) {
            return "PK"
        }
        if units == Array("TK".utf16) {
            return "TK"
        }
        if units == Array("KG".utf16) {
            return "K"
        }
        // `^(?:0[1-9]|1[0-3])$`, then the number it writes.
        guard units.count == 2, let tens = element(units, 0), let ones = element(units, 1) else {
            throw SiteRefusal()
        }
        if tens == 0x30 && ones >= 0x31 && ones <= 0x39 {
            return "\(ones - 0x30)"
        }
        if tens == 0x31 && ones >= 0x30 && ones <= 0x33 {
            return "1\(ones - 0x30)"
        }
        throw SiteRefusal()
    }

    /// A school's grades from its lowest and highest, as NCES codes: "PK–12", "K–5", "K"
    /// (`grades`).
    static func grades(_ low: String, _ high: String) throws -> ShownText {
        let first = try gradeName(low)
        let last = try gradeName(high)
        return ShownText(first == last ? first : first + "\u{2013}" + last)
    }
}
