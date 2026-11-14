import Foundation
import XCTest
@testable import SnowlightCore

/// The My School model (Screens/MySchoolModel.swift) against the site's own school panel, for
/// every case of school-view.json and for each tour fixture (M1 4.5):
///   (1) every word the model offers is the site's word for the case, a status's name, a tab
///       title, the record's shown name, or an app format of the case's own inputs, and nothing
///       else;
///   (2) the callout's chip and the big status are the school's light on the site's map;
///   (3) the drawn status and the held parts are exactly the site's lines;
///   (4) the model draws nothing where the site's panel has no line;
///   (5) the season card and the district line take the form the lead ruled.
/// The family's records carry no shown names (S3's), so each case's record is given its row's
/// own name and district name as its shown names, as the tour fixtures carry them.
final class MySchoolModelTests: XCTestCase {
    /// The family, read: its files and records by key, its answers by index, its cases.
    private struct Family {
        var closings: [String: JSONValue] = [:]
        var seasons: [String: JSONValue?] = [:]
        var records: [String: JSONValue] = [:]
        var answers: [Int: GoldenValue] = [:]
        var cases: [[GoldenValue]] = []
    }

    /// A file a case names, [kind, key, path, part, json]; nil for none.
    private func named(_ entries: [GoldenValue]) throws -> JSONValue? {
        if let path = entries[2].text {
            let whole = try FixtureFile.json(path)
            guard let part = entries[3].text else {
                return whole
            }
            return try XCTUnwrap(whole.fields?[part], "Fixtures/\(path) has no \(part).")
        }
        if entries[4] == GoldenValue.null {
            return nil
        }
        return entries[4].json
    }

    private func family() throws -> Family {
        let golden = try GoldenFile.family("school-view")
        var read = Family()
        for value in golden.cases {
            guard let found = kindOf(value) else {
                XCTFail("school-view: a case this test cannot read: \(value)")
                continue
            }
            let entries = found.entries
            switch found.kind {
            case "closings":
                if entries.count == 5, let key = entries[1].text, let file = try named(entries) {
                    read.closings[key] = file
                }
            case "season":
                if entries.count == 5, let key = entries[1].text {
                    let file = try named(entries)
                    read.seasons[key] = .some(file)
                }
            case "record":
                if entries.count == 3, let key = entries[1].text {
                    read.records[key] = entries[2].json
                }
            case "answer":
                if entries.count == 3, let number = entries[1].numeric, let index = Int(exactly: number) {
                    read.answers[index] = entries[2]
                }
            case "case":
                read.cases.append(entries)
            default:
                XCTFail("school-view: a case of a kind this test does not know: \(found.kind)")
            }
        }
        return read
    }

    private func key(_ status: ClosingStatus) -> StatusKey {
        switch status {
        case .closed:
            return .closed
        case .delayed:
            return .delayed
        case .remote:
            return .remote
        case .earlyDismissal:
            return .earlyDismissal
        }
    }

    /// A tone as the site's lines name it.
    private func tone(_ text: String?) -> StatusKey? {
        switch text {
        case "closed":
            return .closed
        case "delayed":
            return .delayed
        case "remote":
            return .remote
        case "earlyDismissal":
            return .earlyDismissal
        default:
            return nil
        }
    }

    /// The site's season line cut at its key: the key and the rest after its joiner.
    private func cutSeason(_ line: String) -> (key: String, rest: String)? {
        let key = "This school year"
        for joiner in [", ", ": "] where line.hasPrefix(key + joiner) {
            return (key, String(line.dropFirst((key + joiner).count)))
        }
        return nil
    }

    /// The record's row with its own name and district name as S3's shown names.
    private func record(_ row: JSONValue, school: Int, directory: DirectoryStamp) -> SchoolRecord? {
        let items = row.items ?? []
        return recordOf(row, index: school, directory: directory, shown: element(items, 1)?.text, districtShown: element(items, 5)?.text)
    }

    func testEveryCaseAsTheSite() throws {
        let read = try family()
        var files: [String: ClosingsFile?] = [:]
        var stamps: [String: DirectoryStamp] = [:]
        for (key, json) in read.closings {
            files[key] = .some(parseClosings(json))
            stamps[key] = parseStamp(json.fields?["directory"])
        }
        var seasons: [String: SeasonFile?] = [:]
        for (key, json) in read.seasons {
            seasons[key] = .some(json.flatMap { parseSeason($0) })
        }
        let tourStamp = try XCTUnwrap(stamps["tour-closed"], "the tour's closings have no stamp.")
        let differences = Differences()
        var posted = 0
        var drawnSeasons = 0
        // ["case", closings, school, schoolZone, viewerZone, now, season, record, answer]
        for entries in read.cases {
            differences.compared()
            guard entries.count == 9, let fileKey = entries[1].text, let accepted = files[fileKey],
                  let position = entries[2].numeric, let school = Int(exactly: position),
                  let viewer = entries[4].text,
                  let now = inputInstant(entries[5]),
                  let seasonKey = entries[6].text, let season = seasons[seasonKey],
                  let recordKey = entries[7].text, let row = read.records[recordKey],
                  let number = entries[8].numeric, let index = Int(exactly: number),
                  let want = read.answers[index] else {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            let told = inputZone(entries[3])
            guard told.known else {
                differences.note("a case whose zone does not read: \(entries)")
                continue
            }
            let zone = told.zone
            let directory = accepted?.directory ?? stamps[fileKey] ?? tourStamp
            guard let made = record(row, school: school, directory: directory) else {
                differences.note("\(entries): the record's row does not read")
                continue
            }
            let input = MySchoolInput(closings: accepted, season: season, school: school, record: made, schoolZone: zone, viewerZone: viewer, now: now)
            let model = mySchoolModel(input)
            let words = shownTexts(in: model).map { $0.drawnString }
            let here = "\(entries)"

            guard accepted != nil else {
                // The site refuses the closings file: nothing is posted, nothing lights.
                if want != GoldenValue.string("refused") {
                    differences.note("\(here): the app refuses the closings file, the site reads it")
                }
                if model.lead != MySchoolModel.Lead.held(.loading) || model.callout != nil {
                    differences.note("\(here): a refused file must give the loading lead and no callout")
                }
                continue
            }
            guard let answer = want.entries, answer.count == 5, let siteLines = answer[0].entries, let kind = answer[1].text else {
                differences.note("\(here): an answer this test cannot read: \(want)")
                continue
            }
            let siteSeason = answer[2].text
            let siteDay = answer[3].text
            var light: StatusKey?
            if let code = answer[4].numeric, let status = ClosingStatus(rawValue: Int(code)) {
                light = key(status)
            }

            // (1) Every word is one of these, and nothing else passes.
            var allowed: Set<String> = []
            for entry in siteLines {
                guard let line = entry.entries, line.count == 7 else {
                    differences.note("\(here): a site line this test cannot read")
                    continue
                }
                for part in [line[1], line[2], line[4]] {
                    if let text = part.text {
                        allowed.insert(text)
                    }
                }
                if let note = line[3].text {
                    for part in note.components(separatedBy: SiteFormat.dot) {
                        allowed.insert(part)
                    }
                }
            }
            allowed.insert(kind)
            if let line = siteSeason, let cut = cutSeason(line) {
                allowed.insert(cut.key)
                allowed.insert(cut.rest)
            }
            for status in [ClosingStatus.closed, .delayed, .remote, .earlyDismissal] {
                allowed.insert(SiteWords.status(status).drawnString)
            }
            for tab in [AppWords.mySchool, AppWords.map, AppWords.callIt, AppWords.settings] {
                allowed.insert(tab.drawnString)
            }
            let rowItems = row.items ?? []
            if let shown = element(rowItems, 1)?.text {
                allowed.insert(SchoolLines.splitName(shown).name)
            }
            let districtShown = element(rowItems, 5)?.text
            if let district = districtShown {
                allowed.insert(district)
                if let grades = made.grades, let said = try? SiteFormat.grades(grades.low, grades.high) {
                    allowed.insert(AppFormat.districtLine(district: ShownText(district), grades: said).drawnString)
                }
            }
            if let day = siteDay, let line = try? AppFormat.dayLine(day) {
                allowed.insert(line.drawnString)
            }
            var caseDays: SchoolSeason?
            if let file = season {
                caseDays = try? schoolSeason(file, school: school, directory: made.directory, now: now)
            }
            if let found = caseDays {
                if let counts = try? AppFormat.seasonCounts(found.days) {
                    allowed.insert(counts.drawnString)
                }
                if let since = found.since, let from = try? AppFormat.seasonSince(since) {
                    allowed.insert(from.drawnString)
                }
            }
            for word in words where allowed.contains(word) == false {
                differences.note("\(here): the model offers a word that is not the site's, a status's, a tab's, a name or an app format's: '\(word)'")
            }

            // (2) The chip and the big status are the map's light.
            if let callout = model.callout {
                if light == nil || callout.chip.drawnString != light.map({ SiteWords.status(status(of: $0)).drawnString }) {
                    differences.note("\(here): the callout's chip is not the map's light \(String(describing: light))")
                }
                if callout.name != model.header.name {
                    differences.note("\(here): the callout's name is not the header's")
                }
            } else if light != nil {
                differences.note("\(here): the map lights the school and there is no callout")
            }

            // (3) The drawn status and the held parts are exactly the site's lines.
            var mine: [String] = []
            var heroLine: [GoldenValue]?
            switch model.lead {
            case .posted(let shown):
                posted += 1
                if shown.status != light {
                    differences.note("\(here): the posted status is not the map's light")
                }
                mine.append("\(shown.status) today-or-tomorrow")
                heroLine = siteLines.compactMap { $0.entries }.first { $0.count == 7 && $0[6] == .bool(false) && $0[1].text == shown.spoken.drawnString }
                if let line = heroLine {
                    // The hero's note parts: confirmed, reason, posted, in the site's order.
                    let parts = line[3].text?.components(separatedBy: SiteFormat.dot) ?? []
                    var expected: [String] = []
                    if model.held.contains(.confirmed) {
                        expected.append(SiteWords.detailConfirmed.drawnString)
                    }
                    let reasons = parts.filter { $0 != SiteWords.detailConfirmed.drawnString && $0.hasPrefix(SiteWords.detailPosted.drawnString + " ") == false }
                    if model.held.contains(.reason) {
                        expected.append(contentsOf: reasons)
                    }
                    if let at = shown.posted {
                        expected.append(at.drawnString)
                    }
                    if parts != expected || (reasons.isEmpty == false) != model.held.contains(.reason) {
                        differences.note("\(here): the note \(parts), the app's parts \(expected)")
                    }
                    if line[4].text != shown.details?.drawnString || line[0].text != "closed" || line[2] != .null {
                        differences.note("\(here): the posted status's details or tone differ from the site's line")
                    }
                } else {
                    differences.note("\(here): the posted status is no line of the site's")
                }
                if shown.day.drawnString != siteDay.flatMap({ try? AppFormat.dayLine($0).drawnString }) {
                    differences.note("\(here): the posted day is not the map's day")
                }
            case .held(.status(let status)):
                if status != light || status == .closed {
                    differences.note("\(here): a held status that is not the map's light, or is closed")
                }
                mine.append("\(status) today-or-tomorrow")
            case .held(.otherDayOnly):
                if siteLines.isEmpty {
                    differences.note("\(here): only the other day, where the site has no line")
                }
            case .held(.quiet):
                if siteLines.contains(where: { element($0.entries ?? [], 6) == .bool(false) }) {
                    differences.note("\(here): quiet, where the site has a line for today or tomorrow")
                }
            case .held(.loading):
                differences.note("\(here): loading, with a file the site reads")
            }
            for part in model.held {
                switch part {
                case .otherDay(let status):
                    mine.append("\(status) today-or-tomorrow")
                case .laterDay(let status):
                    mine.append("\(status) later")
                case .reason, .confirmed, .campus, .name:
                    break
                }
            }
            var theirs: [String] = []
            for entry in siteLines {
                guard let line = entry.entries, line.count == 7, let status = tone(line[0].text) else {
                    continue
                }
                theirs.append("\(status) " + (line[6] == .bool(true) ? "later" : "today-or-tomorrow"))
            }
            if mine.sorted() != theirs.sorted() {
                differences.note("\(here): the app's lines \(mine), the site's \(theirs)")
            }

            // (4) Nothing drawn where the site's panel has no line; a season card exactly where it has one.
            if siteLines.isEmpty, case .posted = model.lead {
                differences.note("\(here): a posted status where the site has no line")
            }
            if (model.season == nil) != (siteSeason == nil) {
                differences.note("\(here): the season card \(String(describing: model.season)), the site's line \(String(describing: siteSeason))")
            }
            let rest = model.posted?.details == nil ? MySchoolModel.PanelRest.statusOnly : MySchoolModel.PanelRest.details
            if model.rest != rest {
                differences.note("\(here): the rest does not follow the details")
            }

            // (5) The ruled forms of the season card and the district line.
            if let card = model.season, let found = caseDays, let line = siteSeason, let cut = cutSeason(line) {
                let days = found.days
                let draftForm = days.remote == 0 && days.earlyDismissal == 0 && (days.closed > 0 || days.delayed > 0) && found.since != nil
                switch card {
                case .drawn(let cardKey, _, _):
                    drawnSeasons += 1
                    if draftForm == false || cardKey.drawnString != cut.key {
                        differences.note("\(here): the draft's season form outside its case")
                    }
                case .site(let cardKey, let rest):
                    if draftForm || cardKey.drawnString != cut.key || rest.drawnString != cut.rest {
                        differences.note("\(here): the site's season form, wrongly cut or in the draft's case")
                    }
                }
            }
            let isPublic = made.isPrivate == false && made.charter == false && made.virtual == false
            var district = kind
            if isPublic, let name = districtShown {
                district = name
                let grades = kind.components(separatedBy: SiteFormat.dot)
                if grades.count == 2 {
                    district = name + " · Grades " + grades[1]
                }
            }
            if model.header.districtLine.drawnString != district {
                differences.note("\(here): the district line '\(model.header.districtLine.drawnString)', the ruled '\(district)'")
            }
        }
        differences.report("school-view, the My School model")
        XCTAssertGreaterThan(posted, 100, "the model draws a posted status in many cases")
        XCTAssertGreaterThan(drawnSeasons, 100, "the model draws the draft's season form in many cases")
    }

    private func status(of key: StatusKey) -> ClosingStatus {
        switch key {
        case .closed:
            return .closed
        case .delayed:
            return .delayed
        case .remote:
            return .remote
        case .earlyDismissal:
            return .earlyDismissal
        }
    }

    private func tour(_ name: String, change: ((inout [String: JSONValue]) -> Void)? = nil) throws -> MySchoolModel {
        var data = try FixtureFile.data("tour/\(name).json")
        if let edit = change {
            var fields = try XCTUnwrap(JSONValue.read(data)?.fields)
            edit(&fields)
            data = try JSONEncoder().encode(EncodableJSON(.object(fields)))
        }
        let input = try XCTUnwrap(MySchoolInput.decode(data, viewerZone: nil), "tour/\(name).json does not decode.")
        return mySchoolModel(input)
    }

    /// Each tour fixture's words, in `shownTexts(in:)`'s order, as M1 5.4 writes them.
    func testTheTourFixturesWords() throws {
        let start = ["My School", "Map", "Call it", "Settings", "Synthetic Middle School B", "Closed", "Synthetic District One · Grades 6–8", "Synthetic Middle School B", "Closed"]
        let season = ["This school year", "2 closed · 1 delayed ", "since Oct 27"]
        let closed = try tour("tour-closed")
        XCTAssertEqual(shownTexts(in: closed).map { $0.drawnString }, start + ["Tuesday, January 12", "Posted 5:42\u{00A0}AM", "Closed today"] + season)
        XCTAssertEqual(closed.rest, .statusOnly)
        XCTAssertEqual(closed.held, [])
        let details = try tour("tour-details")
        XCTAssertEqual(shownTexts(in: details).map { $0.drawnString }, start + ["Tuesday, January 12", "Posted 5:42\u{00A0}AM", "No buses. After-school activities cancelled.", "Closed today"] + season)
        XCTAssertEqual(details.rest, .details)
        let tomorrow = try tour("tour-tomorrow")
        XCTAssertEqual(shownTexts(in: tomorrow).map { $0.drawnString }, start + ["Wednesday, January 13", "Posted 4:10\u{00A0}PM", "Closed tomorrow"] + season)
        XCTAssertEqual(tomorrow.rest, .statusOnly)
        for model in [closed, details, tomorrow] {
            guard case .posted(let shown) = model.lead else {
                XCTFail("a tour fixture's status is not drawn")
                continue
            }
            XCTAssertEqual(shown.status, .closed)
            guard case .drawn = model.season else {
                XCTFail("a tour fixture's season card is not in the draft's form")
                continue
            }
        }
    }

    /// A public school with no S3 district name takes the site's kind line; a school with no
    /// shown name shows none, has no callout, and holds the name.
    func testNoShownNames() throws {
        let noDistrict = try tour("tour-closed") { fields in
            if var record = fields["record"]?.fields {
                record["district_shown"] = nil
                fields["record"] = .object(record)
            }
        }
        XCTAssertEqual(noDistrict.header.districtLine.drawnString, "Public school · 6–8")
        XCTAssertNotNil(noDistrict.callout)
        let noName = try tour("tour-closed") { fields in
            if var record = fields["record"]?.fields {
                record["shown"] = .null
                fields["record"] = .object(record)
            }
        }
        XCTAssertNil(noName.header.name)
        XCTAssertNil(noName.callout)
        XCTAssertEqual(noName.held, [.name])
        XCTAssertEqual(noName.header.districtLine.drawnString, "Synthetic District One · Grades 6–8")
    }

    /// A campus is cut off the name and held; with no closings file the site reads, the lead
    /// is loading and nothing lights.
    func testCampusAndLoading() throws {
        let campus = try tour("tour-closed") { fields in
            if var record = fields["record"]?.fields {
                record["shown"] = .string("Synthetic Middle School B - North Campus")
                fields["record"] = .object(record)
            }
        }
        XCTAssertEqual(campus.header.name?.drawnString, "Synthetic Middle School B")
        XCTAssertEqual(campus.callout?.name.drawnString, "Synthetic Middle School B")
        XCTAssertEqual(campus.held, [.campus])
        let refused = try tour("tour-closed") { fields in
            if var closings = fields["closings"]?.fields {
                closings["schema_version"] = .number(2)
                fields["closings"] = .object(closings)
            }
        }
        XCTAssertEqual(refused.lead, .held(.loading))
        XCTAssertNil(refused.callout)
        XCTAssertEqual(refused.rest, .statusOnly)
        guard case .drawn = refused.season else {
            XCTFail("the season file stands on its own")
            return
        }
    }
}

extension MySchoolModel {
    /// The drawn status, or nil.
    var posted: Posted? {
        if case .posted(let shown) = lead {
            return shown
        }
        return nil
    }
}

/// A JSONValue written back out, for a fixture changed in a test.
struct EncodableJSON: Encodable {
    let value: JSONValue

    init(_ value: JSONValue) {
        self.value = value
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case .null:
            try container.encodeNil()
        case .bool(let flag):
            try container.encode(flag)
        case .number(let number):
            try container.encode(number)
        case .string(let text):
            try container.encode(text)
        case .array(let items):
            try container.encode(items.map { EncodableJSON($0) })
        case .object(let fields):
            try container.encode(fields.mapValues { EncodableJSON($0) })
        }
    }
}
