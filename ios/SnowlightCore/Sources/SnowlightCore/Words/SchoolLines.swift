// The site's school panel lines (web/src/app/school.ts), ported for the app's My School
// model: a status line and the lines of a school's days (`statusLine`, `statusLines`), what
// the school is (`kindOf`), its season line (`seasonLine`), and its shown name cut where the
// site cuts it (`splitName`); and the two lines the lead ruled for the draft's own form, the
// district line (`districtLine`) and the season card (`seasonCard`, M1 4.2a). `schoolName`
// and `districtName` are the only makers of a school's or a district's name as words. Held to
// the site, string for string, by the golden families school-view.json (SchoolViewTests,
// MySchoolModelTests) and school-names.json (SchoolNameTests).
//
// M1 has no outlook, so no line names what districts nearby said: the site's view gives
// nothing there without one (school.ts `nearbySaid`). That comes with the predictions port.
// Nor is there an "Open today" line: the site says it only where live/covered.json says the
// school's closings were checked, and that file is not published (Days/SchoolDay.swift).
//
// Not public: no code outside SnowlightCore can name this table.

/// One status line of the school panel (school.ts `StatusLineView`).
struct SchoolStatusLine: Equatable {
    /// The row's status (the line's `tone`).
    let tone: ClosingStatus
    let headline: ShownText
    /// The delay or the dismissal, for a delayed start or an early dismissal.
    let detail: ShownText?
    /// "Confirmed by our team", the reason and when it was posted, with the site's dot.
    let note: ShownText?
    /// The plain details its listings state.
    let said: ShownText?
    /// The day the line is about (YYYY-MM-DD), where the site names one.
    let day: String?
    /// The row's reason in words: a part of the note; nil for none or a code with no name.
    let reason: ShownText?
    /// A day after the map's day, which the map draws as a ring (`later`).
    let later: Bool
    /// Told with its date, "Closed Fri, Nov 13" (`dated`).
    let dated: Bool
}

enum SchoolLines {
    // The site's words these lines use, each beside its key path in web/src/copy.ts.
    // SchoolViewTests holds each to copy.json.

    /// `copy.detail.publicSchool`
    static let publicSchool = ShownText("Public school")
    /// `copy.detail.privateSchool`
    static let privateSchool = ShownText("Private school")
    /// `copy.detail.charterSchool`
    static let charterSchool = ShownText("Charter school")
    /// `copy.detail.virtualSchool`
    static let virtualSchool = ShownText("Virtual school")

    /// `copy.reason.*`, one name for each reason code, in code order (`REASON_KEYS`).
    static let reasonNames: [ShownText] = [
        // 0 winterStorm
        ShownText("Winter storm"),
        // 1 ice
        ShownText("Ice"),
        // 2 extremeCold
        ShownText("Extreme cold"),
        // 3 flooding
        ShownText("Flooding"),
        // 4 hurricane
        ShownText("Hurricane"),
        // 5 severeStorms
        ShownText("Severe storms"),
        // 6 heat
        ShownText("Heat"),
        // 7 powerOutage
        ShownText("Power outage"),
    ]

    /// Where a shown name's campus starts: after a spaced dash (`CAMPUS_MARK`).
    static let campusMark = " - "

    /// The scalars JavaScript's `trim()` removes from either end, all 25 of them, written
    /// out: U+0009 to U+000D, U+0020, U+00A0, U+1680, U+2000 to U+200A, U+2028, U+2029,
    /// U+202F, U+205F, U+3000 and U+FEFF. U+0085 and U+180E are not among them.
    static let trimmed: Set<UInt32> = [
        0x0009, 0x000A, 0x000B, 0x000C, 0x000D,
        0x0020,
        0x00A0,
        0x1680,
        0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200A,
        0x2028, 0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xFEFF,
    ]

    // Status lines ---------------------------------------------------------------------

    /// The name of a row's reason; nil for a code the site has no name for (`reasonName`).
    static func reasonName(_ code: Int) -> ShownText? {
        return element(reasonNames, code)
    }

    /// A school's line for one of its days (school.ts `statusLine`, with no nearby reason):
    /// the status's line for today or tomorrow, the delay or dismissal, and the note of
    /// "Confirmed by our team", the reason and "Posted ..." on the viewer's clock (`zone`).
    /// It throws where a formatter of the site's throws.
    static func statusLine(_ row: StatusRow, on which: PostedDay, now: Int64, zone: String, date: String?) throws -> SchoolStatusLine {
        let words = SiteWords.statusLine(row.status)
        let shift = row.shiftMinutes.map { Double($0) }
        let clock = row.clockMinute.map { Double($0) }
        var detail: ShownText?
        switch row.status {
        case .delayed:
            detail = try SiteFormat.delay(shift: shift, clock: clock)
        case .earlyDismissal:
            detail = try SiteFormat.dismissal(shift: shift, clock: clock)
        case .closed, .remote:
            detail = nil
        }
        var reason: ShownText?
        if let code = row.reason {
            reason = reasonName(code)
        }
        var notes: [ShownText] = []
        if row.manual {
            notes.append(SiteWords.detailConfirmed)
        }
        if let named = reason {
            notes.append(named)
        }
        if let posted = row.announcedAt {
            notes.append(try SiteFormat.posted(posted, zone: zone, now: now))
        }
        return SchoolStatusLine(
            tone: row.status,
            headline: which == PostedDay.today ? words.today : words.tomorrow,
            detail: detail,
            note: SiteFormat.dotted(notes),
            said: DetailsWords.said(row.details),
            day: date,
            reason: reason,
            later: false,
            dated: false
        )
    }

    /// The same line, as a later day on the map.
    private static func asLater(_ line: SchoolStatusLine) -> SchoolStatusLine {
        return SchoolStatusLine(
            tone: line.tone,
            headline: line.headline,
            detail: line.detail,
            note: line.note,
            said: line.said,
            day: line.day,
            reason: line.reason,
            later: true,
            dated: line.dated
        )
    }

    /// A school's lines (school.ts `statusLines`, with no nearby reason): today's row, then
    /// tomorrow's (a later day, a ring, while the map's day `shown` is before it), then each
    /// day after tomorrow, dated in the site's words ("Closed Fri, Nov 13"). `today` is the
    /// school's today on its own clock, `zone` the viewer's clock. It throws where a
    /// formatter of the site's throws; the site then shows no status line at all.
    static func statusLines(_ status: SchoolStatus, now: Int64, zone: String, today: String?, shown: String?) throws -> [SchoolStatusLine] {
        var lines: [SchoolStatusLine] = []
        if let row = status.today {
            lines.append(try statusLine(row, on: PostedDay.today, now: now, zone: zone, date: today))
        }
        if let row = status.tomorrow {
            var next: String?
            if let day = today {
                next = siteNextDay(day)
            }
            let line = try statusLine(row, on: PostedDay.tomorrow, now: now, zone: zone, date: next)
            if let day = next, let onTheMap = shown, day > onTheMap {
                lines.append(asLater(line))
            } else {
                lines.append(line)
            }
        }
        for entry in status.later {
            let line = try statusLine(entry.row, on: PostedDay.tomorrow, now: now, zone: zone, date: entry.day)
            // `format.statusDated`: the status's word for a dated day, then the day.
            let dated = try SiteFormat.day(entry.day)
            let headline = ShownText(SiteWords.statusLine(entry.row.status).on.drawnString + " " + dated.drawnString)
            lines.append(SchoolStatusLine(
                tone: line.tone,
                headline: headline,
                detail: line.detail,
                note: line.note,
                said: line.said,
                day: line.day,
                reason: line.reason,
                later: true,
                dated: true
            ))
        }
        return lines
    }

    // What the school is -----------------------------------------------------------------

    /// What the school is, and its grades: "Private school · PK–12" (school.ts `kindOf`).
    /// Grades the site cannot say leave the kind alone.
    static func kindOf(_ record: SchoolRecord) -> ShownText {
        var kind = publicSchool
        if record.isPrivate {
            kind = privateSchool
        } else if record.virtual {
            kind = virtualSchool
        } else if record.charter {
            kind = charterSchool
        }
        guard let grades = record.grades, let said = try? SiteFormat.grades(grades.low, grades.high) else {
            return kind
        }
        return ShownText(kind.drawnString + SiteFormat.dot + said.drawnString)
    }

    /// The line under the school's name (M1 4.2a, RD-6 as the lead ruled): for a public
    /// school with S3's district name, the district and its grades as the draft writes them
    /// ("Synthetic District One · Grades 6–8"), or the district alone where the site cannot
    /// say the grades; for a private, charter or virtual school, whatever district its record
    /// names, and for a public school with no S3 district name, the site's own kind line
    /// (`kindOf`).
    static func districtLine(_ record: SchoolRecord) -> ShownText {
        let isPublic = record.isPrivate == false && record.virtual == false && record.charter == false
        guard isPublic, let district = districtName(record) else {
            return kindOf(record)
        }
        guard let grades = record.grades, let said = try? SiteFormat.grades(grades.low, grades.high) else {
            return district
        }
        return AppFormat.districtLine(district: district, grades: said)
    }

    // The season line ------------------------------------------------------------------

    /// The school's season line, or nil where the file says nothing that holds now
    /// (school.ts `seasonLine`): no file, no row for the school, or counts the site's
    /// formatter refuses. It throws where the site's `schoolSeason` throws.
    static func seasonLine(_ file: SeasonFile?, record: SchoolRecord, now: Int64) throws -> ShownText? {
        guard let season = file,
              let found = try schoolSeason(season, school: record.index, directory: record.directory, now: now) else {
            return nil
        }
        return try? SeasonWords.line(found.days, since: found.since)
    }

    /// The school's season card, or nil exactly where the site has no season line
    /// (`seasonLine`). It throws where `seasonLine` throws.
    static func seasonCard(_ file: SeasonFile?, record: SchoolRecord, now: Int64) throws -> MySchoolModel.Season? {
        guard let season = file,
              let found = try schoolSeason(season, school: record.index, directory: record.directory, now: now) else {
            return nil
        }
        return seasonCard(found.days, since: found.since)
    }

    /// The season card for a school's days (M1 4.2a, RD-10 as the lead ruled): the draft's
    /// form, "2 closed · 1 delayed " and "since Oct 27", when the school has closed or
    /// delayed days, no remote and no early-dismissal day, and a since; for every other count
    /// the site's own line, cut after its key "This school year"; nil where the site's
    /// formatter refuses the counts, which gives the site no line.
    static func seasonCard(_ days: SeasonDays, since: String?) -> MySchoolModel.Season? {
        guard let cut = try? SeasonWords.parts(days, since: since) else {
            return nil
        }
        if days.remote == 0, days.earlyDismissal == 0, days.closed > 0 || days.delayed > 0, let day = since,
           let counts = try? AppFormat.seasonCounts(days), let from = try? AppFormat.seasonSince(day) {
            return MySchoolModel.Season.drawn(key: cut.key, counts: counts, since: from)
        }
        return MySchoolModel.Season.site(key: cut.key, rest: cut.rest)
    }

    // Names ----------------------------------------------------------------------------

    /// A text with the scalars of `trimmed` dropped from both ends, as JavaScript's `trim()`.
    static func trimmedText(_ text: String) -> String {
        let scalars = Array(text.unicodeScalars)
        var start = 0
        var end = scalars.count
        while start < end, let first = element(scalars, start), trimmed.contains(first.value) {
            start += 1
        }
        while end > start, let last = element(scalars, end - 1), trimmed.contains(last.value) {
            end -= 1
        }
        var kept = String.UnicodeScalarView()
        kept.append(contentsOf: scalars.dropFirst(start).prefix(end - start))
        return String(kept)
    }

    /// Where the campus mark first stands in a list of scalars, or nil.
    private static func markAt(_ scalars: [Unicode.Scalar]) -> Int? {
        let mark = Array(campusMark.unicodeScalars)
        guard scalars.count >= mark.count else {
            return nil
        }
        for start in 0...(scalars.count - mark.count) {
            var same = true
            for (offset, want) in mark.enumerated() where element(scalars, start + offset) != want {
                same = false
                break
            }
            if same {
                return start
            }
        }
        return nil
    }

    /// A shown name and its campus, cut where the map's label breaks it (school.ts
    /// `splitName`): at the first spaced dash, unless it stands first or nothing but the
    /// trimmed set follows it. The campus is trimmed; the name is not.
    static func splitName(_ shown: String) -> (name: String, campus: String?) {
        let scalars = Array(shown.unicodeScalars)
        guard let cut = markAt(scalars), cut > 0 else {
            return (name: shown, campus: nil)
        }
        var after = String.UnicodeScalarView()
        after.append(contentsOf: scalars.dropFirst(cut + campusMark.unicodeScalars.count))
        let campus = trimmedText(String(after))
        if campus.isEmpty {
            return (name: shown, campus: nil)
        }
        var before = String.UnicodeScalarView()
        before.append(contentsOf: scalars.prefix(cut))
        return (name: String(before), campus: campus)
    }

    /// The school's name and campus as the site's panel shows them, from S3's shown name;
    /// nil where the record carries none.
    static func schoolName(_ record: SchoolRecord) -> (name: ShownText, campus: ShownText?)? {
        guard let shown = record.shown else {
            return nil
        }
        let cut = splitName(shown)
        var campus: ShownText?
        if let part = cut.campus {
            campus = ShownText(part)
        }
        return (name: ShownText(cut.name), campus: campus)
    }

    /// The district's name as the site shows it whole, from S3's shown name; nil where the
    /// record carries none.
    static func districtName(_ record: SchoolRecord) -> ShownText? {
        guard let shown = record.districtShown else {
            return nil
        }
        return ShownText(shown)
    }
}
