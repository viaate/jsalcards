import Foundation
import XCTest
@testable import SnowlightCore

/// A file of the test bundle's Fixtures folder, by its path there ("tour/tour-closed.json",
/// "site/schemas/examples/synthetic-closings.json"), read as the app reads a file.
enum FixtureFile {
    static func data(_ path: String) throws -> Data {
        guard let golden = GoldenFile.folder() else {
            throw GoldenError.noFixtures
        }
        var url = golden.deletingLastPathComponent()
        for part in path.split(separator: "/") {
            url = url.appendingPathComponent(String(part), isDirectory: false)
        }
        return try Data(contentsOf: url)
    }

    static func json(_ path: String) throws -> JSONValue {
        return try XCTUnwrap(JSONValue.read(try data(path)), "Fixtures/\(path) does not read as JSON.")
    }
}

/// The school panel's lines as the site's own view gives them (web/src/app/school.ts
/// `schoolView`), for every case of school-view.json: the status lines (Words/SchoolLines.swift
/// `statusLines` over the app's `schoolStatus`), what the school is (`kindOf`), its season
/// line (`seasonLine`), its map day (`mapDay`) and its light (`litStatus`), string for string,
/// over four blocks of inputs: every school of six closings files at six school zones and
/// twelve times, 30 mutations of one row, five season files, and 20 record forms.
final class SchoolViewTests: XCTestCase {
    /// The family, read: its files and records by key, its answers by index, its cases.
    private struct Family {
        var closings: [String: JSONValue] = [:]
        var seasons: [String: JSONValue?] = [:]
        var records: [String: JSONValue] = [:]
        var answers: [Int: GoldenValue] = [:]
        var cases: [[GoldenValue]] = []
    }

    /// A file a case names, [kind, key, path, part, json]: a fixture by its path (and the part
    /// of it, for a tour fixture), or the file the case carries; nil for none.
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
                guard entries.count == 5, let key = entries[1].text, let file = try named(entries) else {
                    XCTFail("school-view: a closings file this test cannot read: \(value)")
                    continue
                }
                read.closings[key] = file
            case "season":
                guard entries.count == 5, let key = entries[1].text else {
                    XCTFail("school-view: a season file this test cannot read: \(value)")
                    continue
                }
                let file = try named(entries)
                read.seasons[key] = .some(file)
            case "record":
                guard entries.count == 3, let key = entries[1].text else {
                    XCTFail("school-view: a record this test cannot read: \(value)")
                    continue
                }
                read.records[key] = entries[2].json
            case "answer":
                guard entries.count == 3, let number = entries[1].numeric, let index = Int(exactly: number) else {
                    XCTFail("school-view: an answer this test cannot read: \(value)")
                    continue
                }
                read.answers[index] = entries[2]
            case "case":
                guard entries.count == 9 else {
                    XCTFail("school-view: a case of \(entries.count) entries: \(value)")
                    continue
                }
                read.cases.append(entries)
            default:
                XCTFail("school-view: a case of a kind this test does not know: \(found.kind)")
            }
        }
        return read
    }

    /// A status's key, as the site's lines name their tone.
    private func toneKey(_ status: ClosingStatus) -> String {
        switch status {
        case .closed:
            return "closed"
        case .delayed:
            return "delayed"
        case .remote:
            return "remote"
        case .earlyDismissal:
            return "earlyDismissal"
        }
    }

    /// A line in the family's encoding: [tone, headline, detail, note, said, later, dated].
    private func goldenLine(_ line: SchoolStatusLine) -> GoldenValue {
        return .array([
            .string(toneKey(line.tone)),
            .string(line.headline.drawnString),
            golden(line.detail?.drawnString),
            golden(line.note?.drawnString),
            golden(line.said?.drawnString),
            .bool(line.later),
            .bool(line.dated),
        ])
    }

    func testEveryCaseAsTheSite() throws {
        let read = try family()
        var files: [String: ClosingsFile?] = [:]
        for (key, json) in read.closings {
            files[key] = .some(parseClosings(json))
        }
        var seasons: [String: SeasonFile?] = [:]
        for (key, json) in read.seasons {
            seasons[key] = .some(json.flatMap { parseSeason($0) })
        }
        let differences = Differences()
        // ["case", closings, school, schoolZone, viewerZone, now, season, record, answer]
        for entries in read.cases {
            differences.compared()
            guard let fileKey = entries[1].text, let accepted = files[fileKey],
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
            guard let file = accepted else {
                if want != GoldenValue.string("refused") {
                    differences.note("\(entries): the app refuses the closings file, the site reads it")
                }
                continue
            }
            guard let record = recordOf(row, index: school, directory: file.directory, shown: nil, districtShown: nil) else {
                differences.note("\(entries): the record's row does not read")
                continue
            }
            let status = schoolStatus(school: school, directory: file.directory, closings: file, now: now, zone: zone)
            // Where a formatter refuses a line, the site shows no status line at all.
            let lines = (try? SchoolLines.statusLines(status, now: now, zone: viewer, today: schoolToday(now, zone), shown: mapDay(now, zone))) ?? []
            var seasonText: String?
            do {
                seasonText = try SchoolLines.seasonLine(season, record: record, now: now)?.drawnString
            } catch {
                differences.note("\(entries): the app's season line throws")
                continue
            }
            var light = GoldenValue.null
            if let lit = litStatus(file, directory: file.directory, school: school, zone: zone, now: now) {
                light = .number(Double(lit.rawValue))
            }
            let mine = GoldenValue.array([
                .array(lines.map { goldenLine($0) }),
                .string(SchoolLines.kindOf(record).drawnString),
                golden(seasonText),
                golden(mapDay(now, zone)),
                light,
            ])
            if mine != want {
                differences.note("\(entries): the site \(want), the app \(mine)")
            }
        }
        differences.report("school-view")
    }

    func testTheFamilyHoldsItsFourBlocks() throws {
        let read = try family()
        XCTAssertGreaterThanOrEqual(read.cases.count, 4000, "school-view: fewer than 4,000 cases.")
        XCTAssertEqual(read.closings.count, 36, "the three copies, the three tour fixtures and 30 mutations")
        XCTAssertEqual(read.seasons.count, 7, "the synthetic file, the tour's, none and four more")
        XCTAssertEqual(read.records.count, 21, "the directory's row and 4 kinds x 5 grade forms")
        var tones: Set<String> = []
        var refused = 0
        for entries in read.cases {
            guard let number = entries[8].numeric, let index = Int(exactly: number), let answer = read.answers[index] else {
                XCTFail("school-view: a case names no answer: \(entries)")
                continue
            }
            guard let parts = answer.entries, let lines = parts.first?.entries else {
                if answer == GoldenValue.string("refused") {
                    refused += 1
                }
                continue
            }
            for line in lines {
                if let tone = line.entries?.first?.text {
                    tones.insert(tone)
                }
            }
        }
        XCTAssertEqual(tones, ["closed", "delayed", "remote", "earlyDismissal"], "every status the site's lines tell")
        XCTAssertGreaterThan(refused, 0, "a closings file the site refuses")
    }

    /// The site's words the lines use, each equal to its string in copy.json.
    func testTheSiteWordsOfTheLines() throws {
        let copy = try GoldenFile.family("copy")
        let first = try XCTUnwrap(copy.cases.first, "copy.json holds no case.")
        let kinds: [(ShownText, String)] = [
            (SchoolLines.publicSchool, "publicSchool"),
            (SchoolLines.privateSchool, "privateSchool"),
            (SchoolLines.charterSchool, "charterSchool"),
            (SchoolLines.virtualSchool, "virtualSchool"),
        ]
        for (word, key) in kinds {
            XCTAssertEqual(word.drawnString, first.at(["copy", "detail", key])?.text, "copy.detail.\(key)")
        }
        let reasonKeys = ["winterStorm", "ice", "extremeCold", "flooding", "hurricane", "severeStorms", "heat", "powerOutage"]
        XCTAssertEqual(SchoolLines.reasonNames.count, reasonKeys.count, "one name for each reason code")
        for (code, key) in reasonKeys.enumerated() {
            XCTAssertEqual(SchoolLines.reasonName(code)?.drawnString, first.at(["copy", "reason", key])?.text, "copy.reason.\(key)")
        }
        guard case .object(let reasons) = try XCTUnwrap(first.at(["copy", "reason"])) else {
            XCTFail("copy.json holds no copy.reason.")
            return
        }
        XCTAssertEqual(Set(reasons.keys), Set(reasonKeys), "the site names exactly these reasons")
        XCTAssertNil(SchoolLines.reasonName(reasonKeys.count), "a code past the names has no words")
    }
}
