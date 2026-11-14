import XCTest
@testable import SnowlightCore

/// live/season.json as the site reads it (web/src/data/season.ts), for every case of
/// season-file.json: the copied file and its one-change mutations accepted or refused;
/// `schoolSeason` for each school position of the copy's directory (one past the end
/// included), at 12 values of `now`, with the file's own stamp and another; `lastDayOver`
/// at each hour of one UTC day. (The season line's words are read with the words.)
final class SeasonTests: XCTestCase {
    private func cases(_ kind: String) throws -> [[GoldenValue]] {
        let file = try GoldenFile.family("season-file")
        var found: [[GoldenValue]] = []
        for value in file.cases {
            guard let read = kindOf(value) else {
                XCTFail("season-file: a case this test cannot read: \(value)")
                continue
            }
            if read.kind == kind {
                found.append(read.entries)
            }
        }
        XCTAssertFalse(found.isEmpty, "season-file holds no \(kind) case.")
        return found
    }

    /// The copied season file, read as the app reads it.
    private func fixture() throws -> SeasonFile {
        let value = try SiteFixture.json("schemas/examples/synthetic-live-season.json")
        return try XCTUnwrap(parseSeason(value), "the copied season file is refused.")
    }

    /// The app's `schoolSeason` in the golden files' encoding: null, the refusal mark, or
    /// [closed, delayed, remote, earlyDismissal, since].
    private func seasonAnswer(_ file: SeasonFile, school: Int, directory: DirectoryStamp, now: Int64) -> GoldenValue {
        do {
            guard let found = try schoolSeason(file, school: school, directory: directory, now: now) else {
                return .null
            }
            return .array([
                GoldenValue.number(Double(found.days.closed)),
                GoldenValue.number(Double(found.days.delayed)),
                GoldenValue.number(Double(found.days.remote)),
                GoldenValue.number(Double(found.days.earlyDismissal)),
                golden(found.since),
            ])
        } catch {
            return GoldenValue.throwsMark
        }
    }

    /// The app's `lastDayOver` in the golden files' encoding: the day, or the refusal mark.
    private func lastDayAnswer(_ now: Int64) -> GoldenValue {
        do {
            return .string(try lastDayOver(now))
        } catch {
            return GoldenValue.throwsMark
        }
    }

    func testParseSeasonAsTheSite() throws {
        let differences = Differences()
        // ["file", name, path, json, parseSeason accepts]
        for entries in try cases("file") where entries.count == 5 {
            differences.compared()
            let mine = parseSeason(try caseFile(path: entries[2], inline: entries[3])) != nil
            if mine != entries[4].flag {
                differences.note("\(entries[1]): the site accepts \(entries[4]), the app \(mine)")
            }
        }
        differences.report("season-file, accept or refuse")
    }

    func testSchoolSeasonAsTheSite() throws {
        let file = try fixture()
        let differences = Differences()
        var invalidClocks = 0
        // ["school", school, directory, now, null or [closed, delayed, remote, earlyDismissal, since]]
        for entries in try cases("school") where entries.count == 5 {
            differences.compared()
            guard let position = entries[1].numeric, let school = Int(exactly: position),
                  let directory = parseStamp(entries[2].json) else {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            guard let at = entries[3].numeric, let now = Int64(exactly: at) else {
                // A `now` that is no instant (the text "NaN"): an instant inside the app is
                // whole milliseconds and cannot be one, and the site says nothing there.
                invalidClocks += 1
                if entries[4] != .null {
                    differences.note("school \(school) at \(entries[3]): the site says \(entries[4]) for an invalid clock")
                }
                continue
            }
            let mine = seasonAnswer(file, school: school, directory: directory, now: now)
            if mine != entries[4] {
                differences.note("school \(school), \(entries[2]), now \(now): the site \(entries[4]), the app \(mine)")
            }
        }
        differences.report("season-file, schoolSeason")
        XCTAssertGreaterThan(invalidClocks, 0, "season-file holds no invalid clock.")
    }

    func testLastDayOverAsTheSite() throws {
        let differences = Differences()
        // ["lastDayOver", now, lastDayOver(now)]
        for entries in try cases("lastDayOver") where entries.count == 3 {
            differences.compared()
            guard let at = entries[1].numeric, let now = Int64(exactly: at) else {
                differences.note("a case this test cannot read: \(entries)")
                continue
            }
            let mine = lastDayAnswer(now)
            if mine != entries[2] {
                differences.note("now \(now): the site \(entries[2]), the app \(mine)")
            }
        }
        differences.report("season-file, lastDayOver")
    }

    func testSeasonLineAsTheSite() throws {
        let file = try GoldenFile.family("season-line")
        let differences = Differences()
        var refused = 0
        for value in file.cases {
            // [closed, delayed, remote, earlyDismissal, since, seasonFormat.line(days, since)]
            guard let entries = value.entries, entries.count == 6 else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            var counts: [Int] = []
            for entry in entries[0..<4] {
                if let number = entry.numeric, let whole = Int(exactly: number) {
                    counts.append(whole)
                }
            }
            let since = entries[4].text
            guard counts.count == 4, since != nil || entries[4] == .null else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let days = SeasonDays(closed: counts[0], delayed: counts[1], remote: counts[2], earlyDismissal: counts[3])
            let mine = shownAnswer { try SeasonWords.line(days, since: since) }
            if mine != entries[5] {
                differences.note("\(counts) since \(entries[4]): the site \(entries[5]), the app \(mine)")
            }
            if entries[5] == GoldenValue.throwsMark {
                refused += 1
            }
        }
        differences.report("season-line")
        XCTAssertEqual(refused, 1, "season-line.json holds one line of no day at all, which the site refuses.")
    }
}
