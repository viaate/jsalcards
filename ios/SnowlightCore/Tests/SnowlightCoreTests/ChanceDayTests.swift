import XCTest
@testable import SnowlightCore

/// The chance's day (PLAN section 4, rule C) is the site's: the light outlook
/// (web/src/data/school-day.ts `schoolOutlook`) with its gates (the same directory, at most
/// 90 minutes old, at most 15 minutes ahead, the school's own today in the file) and its bus
/// times read as the site reads them, and `headlineDay` (web/src/app/chance.ts) for the four
/// ways today and tomorrow can be decided, for every "outlook" case of predictions.json; and
/// `underWay` for every "underWay" case, around 7:30 AM on each clock with and without bus
/// times. Where the site accepted a zone name the app's list does not hold (`narrower`), the
/// app reads no clock and the day is under way: it is not said.
final class ChanceDayTests: XCTestCase {
    /// The files the "outlook" cases read, by name: the copies and the two late mutations.
    private func files() throws -> [String: PredictionsFile] {
        let golden = try GoldenFile.family("predictions")
        var files: [String: PredictionsFile] = [:]
        for value in golden.cases {
            guard let read = kindOf(value), read.kind == "file", read.entries.count == 7, let name = read.entries[1].text else {
                continue
            }
            if let found = parsePredictions(try caseFile(path: read.entries[2], inline: read.entries[3])) {
                files[name] = found
            }
        }
        return files
    }

    /// The cases of one kind.
    private func cases(_ kind: String) throws -> [[GoldenValue]] {
        let golden = try GoldenFile.family("predictions")
        var found: [[GoldenValue]] = []
        for value in golden.cases {
            if let read = kindOf(value), read.kind == kind {
                found.append(read.entries)
            }
        }
        XCTAssertFalse(found.isEmpty, "predictions.json holds no \(kind) case.")
        return found
    }

    /// A day of an outlook in the golden files' encoding: ["forecast", noSchool, delay, day,
    /// busesAt, reasons] or ["no_threat"].
    private func encoded(_ day: DayOutlook?) -> GoldenValue {
        switch day {
        case .none:
            return .null
        case .some(.noThreat):
            return .array([.string("no_threat")])
        case .some(.forecast(let forecast)):
            let reasons = GoldenValue.array(forecast.reasons.map { GoldenValue.number(Double($0)) })
            return .array([.string("forecast"), .number(forecast.noSchool), .number(forecast.delay), .string(forecast.day), golden(forecast.busesAt), reasons])
        }
    }

    /// The four ways today and tomorrow can be decided, in the generator's order.
    private let decided: [(today: Bool, tomorrow: Bool)] = [(false, false), (true, false), (false, true), (true, true)]

    func testOutlookAndHeadlineAsTheSite() throws {
        let files = try files()
        let differences = Differences()
        var said = 0
        for entries in try cases("outlook") {
            // ["outlook", name, directory, shipped, district, school, now, outlook, headline]
            guard entries.count == 9, let name = entries[1].text, let file = files[name],
                  let shipped = entries[3].flag, let now = inputInstant(entries[6]) else {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            var directory = file.directory
            if entries[2] != .null {
                guard let stamp = parseStamp(entries[2].json) else {
                    differences.note("a case whose directory does not read: \(entries)")
                    continue
                }
                directory = stamp
            }
            let district = entries[4].numeric.flatMap { Int(exactly: $0) }
            let school = entries[5].numeric.flatMap { Int(exactly: $0) }
            if (district == nil && entries[4] != .null) || (school == nil && entries[5] != .null) {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            differences.compared()
            let outlook = schoolOutlook(district: district, school: school, directory: directory, shipped: shipped, predictions: file, now: now)
            var mine: GoldenValue = .null
            if let found = outlook {
                said += 1
                mine = .array([.string(found.timeZone), encoded(found.today), encoded(found.tomorrow)])
            }
            if mine != entries[7] {
                differences.note("\(name) district \(entries[4]) school \(entries[5]) at \(now): the site \(entries[7]), the app \(mine)")
            }
            var headlines: [GoldenValue] = []
            for ways in decided {
                let day = headlineDay(outlook, decidedToday: ways.today, decidedTomorrow: ways.tomorrow, now: now)
                headlines.append(golden(day?.day))
            }
            if GoldenValue.array(headlines) != entries[8] {
                differences.note("\(name) district \(entries[4]) school \(entries[5]) at \(now): the site's headline days \(entries[8]), the app's \(headlines)")
            }
        }
        differences.report("predictions, outlook and headline")
        XCTAssertGreaterThan(said, 0, "no outlook case says an outlook.")
    }

    func testUnderWayAsTheSite() throws {
        let differences = Differences()
        var narrower = 0
        for entries in try cases("underWay") {
            // ["underWay", day, now, zone, buses, underWay(day, now, zone, buses), narrower]
            guard entries.count == 7, let day = entries[1].text, let now = inputInstant(entries[2]),
                  let zone = entries[3].text, let theirs = entries[5].flag, let flag = entries[6].flag else {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            let buses = inputInstant(entries[4])
            if buses == nil && entries[4] != .null {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            differences.compared()
            let mine = underWay(day, now: now, zone: zone, buses: buses)
            if flag || (appReadsNoClock(zone) && isListedButUnknownHere(zone)) {
                // The app reads no clock for this name: the day is under way, not said.
                narrower += flag ? 1 : 0
                if !mine {
                    differences.note("\(day) \(zone) at \(now): a name the app does not hold, and the day is not under way")
                }
                continue
            }
            if mine != theirs {
                differences.note("\(day) \(zone) at \(now), buses \(entries[4]): the site \(theirs), the app \(mine)")
            }
        }
        differences.report("predictions, underWay")
        XCTAssertGreaterThan(narrower, 0, "predictions.json holds no narrower underWay case.")
    }
}
