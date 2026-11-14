import XCTest
@testable import SnowlightCore

/// live/closings.json is accepted or refused as the site does it, and every row a school
/// has on each day of an accepted file is the site's `rowOn` row, details included, for
/// every "file" case of closings.json: the three copied files and the one-change mutations
/// of the first. And the rows decoded from the pipeline's own golden files are the rows the
/// pipeline wrote beside them (`*.rows.json`). The "status" cases are read by the day rules'
/// tests.
final class ClosingsFileTests: XCTestCase {
    /// A row in the golden files' encoding:
    /// [status, reason, announcedAt, shiftMinutes, clockMinute, manual, details].
    private func encoded(_ row: StatusRow?) -> GoldenValue {
        guard let row = row else {
            return .null
        }
        return .array([
            .number(Double(row.status.rawValue)),
            golden(row.reason),
            golden(row.announcedAt),
            golden(row.shiftMinutes),
            golden(row.clockMinute),
            .bool(row.manual),
            .array(row.details.map { GoldenValue.number(Double($0)) }),
        ])
    }

    /// For each of a file's days in order, [day, [rowOn(file, day, school) for school 0 ...
    /// schools]], one past the end included.
    private func rowsOf(_ file: ClosingsFile) -> GoldenValue {
        var days: [GoldenValue] = []
        for group in file.days {
            var rows: [GoldenValue] = []
            for school in 0...file.directory.schools {
                rows.append(encoded(rowOn(file, day: group.day, school: school)))
            }
            days.append(.array([.string(group.day), .array(rows)]))
        }
        return .array(days)
    }

    /// A whole number as JSON, or null.
    private func number(_ value: Int?) -> JSONValue {
        guard let whole = value else {
            return .null
        }
        return .number(Double(whole))
    }

    /// ["file", name, path, json, parseClosings accepts, rows]
    private func fileCases() throws -> [[GoldenValue]] {
        let golden = try GoldenFile.family("closings")
        var cases: [[GoldenValue]] = []
        for value in golden.cases {
            guard let found = kindOf(value) else {
                XCTFail("closings: a case this test cannot read: \(value)")
                continue
            }
            if found.kind == "file" {
                XCTAssertEqual(found.entries.count, 6)
                cases.append(found.entries)
            }
        }
        // The three copies and at least 40 mutations.
        XCTAssertGreaterThanOrEqual(cases.count, 43)
        return cases
    }

    func testAcceptOrRefuseAsTheSite() throws {
        let differences = Differences()
        var accepted = 0
        var refused = 0
        for entries in try fileCases() where entries.count == 6 {
            differences.compared()
            let mine = parseClosings(try caseFile(path: entries[2], inline: entries[3])) != nil
            if mine != entries[4].flag {
                differences.note("\(entries[1]): the site accepts \(entries[4]), the app \(mine)")
            }
            if mine {
                accepted += 1
            } else {
                refused += 1
            }
        }
        differences.report("closings, accept or refuse")
        XCTAssertGreaterThan(accepted, 0)
        XCTAssertGreaterThan(refused, 0)
    }

    func testRowsAsTheSite() throws {
        let differences = Differences()
        for entries in try fileCases() where entries.count == 6 {
            differences.compared()
            let file = parseClosings(try caseFile(path: entries[2], inline: entries[3]))
            let mine = file.map { rowsOf($0) } ?? .null
            if mine != entries[5] {
                differences.note("\(entries[1]): the site's rows \(entries[5]), the app's \(mine)")
            }
        }
        differences.report("closings, rows")
    }

    func testRowsAreThePipelinesOwn() throws {
        for name in ["synthetic_closings", "synthetic_manual_closings"] {
            let file = try XCTUnwrap(parseClosings(try SiteFixture.json("live/golden/\(name).json")), "\(name) is refused.")
            let expected = try XCTUnwrap(try SiteFixture.json("live/golden/\(name).rows.json").items, "\(name).rows.json is not a list.")
            var mine: [JSONValue] = []
            for group in file.days {
                for position in decodeDay(group).schools {
                    let school = Int(position)
                    guard let row = rowOn(file, day: group.day, school: school) else {
                        XCTFail("\(name): no row for school \(school) on \(group.day), which the day lists.")
                        continue
                    }
                    mine.append(.object([
                        "day": .string(group.day),
                        "school": .number(Double(school)),
                        "status": .number(Double(row.status.rawValue)),
                        "reason": number(row.reason),
                        "announced_at": number(row.announcedAt.map { Int($0) }),
                        "shift_minutes": number(row.shiftMinutes),
                        "clock_minute": number(row.clockMinute),
                        "manual": .bool(row.manual),
                    ]))
                }
            }
            // The pipeline writes each posting time as a UtcInstant: read it as one.
            var theirs: [JSONValue] = []
            for row in expected {
                var fields = try XCTUnwrap(row.fields, "\(name).rows.json holds a row that is not an object.")
                if let text = fields["announced_at"]?.text {
                    let instant = try XCTUnwrap(parseInstant(text), "\(name).rows.json: \(text) is not an instant.")
                    fields["announced_at"] = .number(Double(instant))
                }
                theirs.append(.object(fields))
            }
            XCTAssertEqual(mine.count, theirs.count, "\(name): a different number of rows.")
            XCTAssertEqual(mine, theirs, "\(name): the decoded rows differ from the pipeline's.")
        }
    }
}
