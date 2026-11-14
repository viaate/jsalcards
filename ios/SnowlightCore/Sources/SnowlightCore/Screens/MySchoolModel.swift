// The model of the My School screen (M1 4.2): everything the screen may show, as values,
// in the order the approved draft 3 stacks it: the tabs, the callout over the map, the
// school's header, its status, its season card. Every site line, note part or name part the
// screen does not draw is listed in `held`, so nothing the site says is lost without a trace.
//
// The rule (PLAN section 4; M0 item 40): the big status is the school's MAP DAY's row
// (`mySchoolDays`), so it is always the school's light on the site's map (`litStatus`). In M1
// only a closed status is drawn; the others, and every day but the status day, are held.
//
// A screen model arranges words; it cannot type one. This file holds no text in quotes and
// makes no ShownText: every word comes from Words/ (the site's words and lines, and the app
// words and formats of the lead's rulings).

/// A status, as a view may know it (the file's codes 0 to 3).
public enum StatusKey: Equatable, Hashable, Sendable, CaseIterable {
    case closed
    case delayed
    case remote
    case earlyDismissal
}

/// What the My School screen shows.
public struct MySchoolModel: Equatable, Sendable {
    /// The four tab titles, first to last.
    public let tabs: [ShownText]
    /// The name over the school's marker on the map, and its status chip; nil where the
    /// record has no shown name or the map lights the school with nothing.
    public let callout: Callout?
    public let header: Header
    /// The big status, or why it is not drawn.
    public let lead: Lead
    /// The season card; nil exactly where the site's panel has no season line.
    public let season: Season?
    /// Which of the draft's two rests the panel takes.
    public let rest: PanelRest
    /// Every site line, note part or name part the screen does not draw.
    public let held: [HeldPart]
    /// The next instant the model can change on its own: the school's next 3:30 PM or
    /// midnight (`nextMapTurn`); nil where no clock can be read. Wired to a clock in M5.
    let nextChange: Int64?

    /// The callout over the marker: the school's name, as the header gives it, and the
    /// site's word for the status the map lights it with (`copy.status.<key>`).
    public struct Callout: Equatable, Sendable {
        public let name: ShownText
        public let chip: ShownText
    }

    /// The panel's header: the line under the school's name, then the name.
    public struct Header: Equatable, Sendable {
        /// "Synthetic District One · Grades 6–8", the district alone, or the site's kind
        /// line (M1 4.2a, RD-6).
        public let districtLine: ShownText
        /// S3's shown name, its campus cut off; nil where the record has none (held: name).
        public let name: ShownText?
    }

    /// The big status of the panel, or why it is not drawn.
    public enum Lead: Equatable, Sendable {
        case posted(Posted)
        case held(HeldLead)
    }

    /// A posted status on the status day, drawn.
    public struct Posted: Equatable, Sendable {
        public let status: StatusKey
        /// The status's word, "Closed" (`copy.status.<key>`).
        public let word: ShownText
        /// The status day, "Tuesday, January 12" (the app's day line).
        public let day: ShownText
        /// "Posted 5:42 AM" on the viewer's clock (the site's `format.posted`); nil when the
        /// row has no time.
        public let posted: ShownText?
        /// The plain details its listings state (the site's `said`), or nil.
        public let details: ShownText?
        /// The site's own line for it, "Closed today": read by VoiceOver, not drawn.
        public let spoken: ShownText
    }

    /// The season card: the draft's form, or the site's own line cut after its key.
    public enum Season: Equatable, Sendable {
        /// "This school year", "2 closed · 1 delayed ", "since Oct 27".
        case drawn(key: ShownText, counts: ShownText, since: ShownText)
        /// "This school year", then the rest of the site's line.
        case site(key: ShownText, rest: ShownText)
    }

    /// Why the big status is not drawn.
    public enum HeldLead: Equatable, Sendable {
        /// A status M1 has no drawing for: delayed, remote, early dismissal.
        case status(StatusKey)
        /// Only the other posted day has a line.
        case otherDayOnly
        /// The site's panel has no line for either day, and the file is accepted.
        case quiet
        /// No closings file the site accepts is had.
        case loading
    }

    /// A part of what the site says that the screen does not draw.
    public enum HeldPart: Equatable, Sendable {
        /// The line of the other posted day (today or tomorrow), and its status.
        case otherDay(StatusKey)
        /// The line of a day after tomorrow, and its status.
        case laterDay(StatusKey)
        /// The reason in the drawn status's note.
        case reason
        /// "Confirmed by our team" in the drawn status's note.
        case confirmed
        /// The campus cut off the school's name.
        case campus
        /// The school's name: the record has no shown name.
        case name
    }

    /// The panel's rest (State/PanelPlace.swift): with the status alone, or with details.
    public enum PanelRest: Equatable, Sendable {
        case statusOnly
        case details
    }
}

/// The status of a row, as a view may know it.
private func statusKey(_ status: ClosingStatus) -> StatusKey {
    switch status {
    case .closed:
        return StatusKey.closed
    case .delayed:
        return StatusKey.delayed
    case .remote:
        return StatusKey.remote
    case .earlyDismissal:
        return StatusKey.earlyDismissal
    }
}

/// The drawn status: the hero row's word, day, posted time, details and the site's line.
/// It throws where a formatter of the site's throws.
private func postedOf(_ line: SchoolStatusLine, row: StatusRow, day: String, input: MySchoolInput) throws -> MySchoolModel.Posted {
    var posted: ShownText?
    if let at = row.announcedAt {
        posted = try SiteFormat.posted(at, zone: input.viewerZone, now: input.now)
    }
    let dayLine = try AppFormat.dayLine(day)
    return MySchoolModel.Posted(
        status: statusKey(row.status),
        word: SiteWords.status(row.status),
        day: dayLine,
        posted: posted,
        details: line.said,
        spoken: line.headline
    )
}

/// The My School model for an input.
public func mySchoolModel(_ input: MySchoolInput) -> MySchoolModel {
    let record = input.record
    let zone = input.schoolZone
    let tabs = [AppWords.mySchool, AppWords.map, AppWords.callIt, AppWords.settings]

    var held: [MySchoolModel.HeldPart] = []
    let named = SchoolLines.schoolName(record)
    if named == nil {
        held.append(MySchoolModel.HeldPart.name)
    } else if named?.campus != nil {
        held.append(MySchoolModel.HeldPart.campus)
    }
    let header = MySchoolModel.Header(districtLine: SchoolLines.districtLine(record), name: named?.name)

    var callout: MySchoolModel.Callout?
    let lit = litStatus(input.closings, directory: record.directory, school: input.school, zone: zone, now: input.now)
    if let name = named?.name, let light = lit {
        callout = MySchoolModel.Callout(name: name, chip: SiteWords.status(light))
    }

    var lead = MySchoolModel.Lead.held(MySchoolModel.HeldLead.loading)
    if let closings = input.closings {
        let days = mySchoolDays(closings: closings, directory: record.directory, school: input.school, zone: zone, now: input.now)
        let status = schoolStatus(school: input.school, directory: record.directory, closings: closings, now: input.now, zone: zone)
        // Where a formatter of the site's refuses a line, the site shows no status line at all.
        let lines = (try? SchoolLines.statusLines(status, now: input.now, zone: input.viewerZone, today: schoolToday(input.now, zone), shown: mapDay(input.now, zone))) ?? []
        var heroAt: Int?
        if let statusDay = days.statusDay, days.hero != nil {
            heroAt = lines.firstIndex(where: { $0.dated == false && $0.day == statusDay })
        }
        lead = MySchoolModel.Lead.held(MySchoolModel.HeldLead.quiet)
        if lines.contains(where: { $0.dated == false }) {
            lead = MySchoolModel.Lead.held(MySchoolModel.HeldLead.otherDayOnly)
        }
        for (at, line) in lines.enumerated() {
            if at == heroAt {
                if line.tone == ClosingStatus.closed, let row = days.hero, let statusDay = days.statusDay,
                   let posted = try? postedOf(line, row: row, day: statusDay, input: input) {
                    lead = MySchoolModel.Lead.posted(posted)
                    if row.manual {
                        held.append(MySchoolModel.HeldPart.confirmed)
                    }
                    if line.reason != nil {
                        held.append(MySchoolModel.HeldPart.reason)
                    }
                } else {
                    lead = MySchoolModel.Lead.held(MySchoolModel.HeldLead.status(statusKey(line.tone)))
                }
            } else if line.dated {
                held.append(MySchoolModel.HeldPart.laterDay(statusKey(line.tone)))
            } else {
                held.append(MySchoolModel.HeldPart.otherDay(statusKey(line.tone)))
            }
        }
    }

    // A season file the site's reader throws on gives no card, as it gives the site no line.
    let season = try? SchoolLines.seasonCard(input.season, record: record, now: input.now)

    var rest = MySchoolModel.PanelRest.statusOnly
    if case .posted(let posted) = lead, posted.details != nil {
        rest = MySchoolModel.PanelRest.details
    }

    return MySchoolModel(
        tabs: tabs,
        callout: callout,
        header: header,
        lead: lead,
        season: season,
        rest: rest,
        held: held,
        nextChange: nextMapTurn(input.now, zone)
    )
}
