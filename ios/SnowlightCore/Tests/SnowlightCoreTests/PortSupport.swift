import Foundation
import XCTest
@testable import SnowlightCore

// What the port's tests share: reading a golden case's entries, turning a file a case
// carries inline into the app's own JSONValue, reading the copies of the pipeline's
// synthetic files, writing the app's answers in the golden files' encoding, and reporting
// differences a few at a time.

extension GoldenValue {
    /// The same value as the app's JSONValue: a file a golden case carries inline.
    var json: JSONValue {
        switch self {
        case .null:
            return .null
        case .bool(let value):
            return .bool(value)
        case .number(let value):
            return .number(value)
        case .string(let value):
            return .string(value)
        case .array(let items):
            return .array(items.map { $0.json })
        case .object(let fields):
            return .object(fields.mapValues { $0.json })
        }
    }

    /// The entries of a case (a list); nil for any other kind.
    var entries: [GoldenValue]? {
        if case .array(let items) = self {
            return items
        }
        return nil
    }

    var numeric: Double? {
        if case .number(let value) = self {
            return value
        }
        return nil
    }

    var flag: Bool? {
        if case .bool(let value) = self {
            return value
        }
        return nil
    }

    /// The mark the generator writes where the site threw: {"throws": true}.
    var isThrowsMark: Bool {
        return self == .object(["throws": .bool(true)])
    }

    /// The site's answer for a refusal.
    static let throwsMark = GoldenValue.object(["throws": .bool(true)])
}

/// An instant in the golden files' encoding: whole milliseconds, or null.
func golden(_ instant: Int64?) -> GoldenValue {
    guard let value = instant else {
        return .null
    }
    return .number(Double(value))
}

/// A whole number in the golden files' encoding, or null.
func golden(_ whole: Int?) -> GoldenValue {
    guard let value = whole else {
        return .null
    }
    return .number(Double(value))
}

/// A text in the golden files' encoding, or null.
func golden(_ text: String?) -> GoldenValue {
    guard let value = text else {
        return .null
    }
    return .string(value)
}

/// The copies of the pipeline's synthetic files (Fixtures/site/, by sync-fixtures.mjs),
/// read from the test bundle.
enum SiteFixture {
    static func data(_ path: String) throws -> Data {
        guard let golden = GoldenFile.folder() else {
            throw GoldenError.noFixtures
        }
        var url = golden.deletingLastPathComponent().appendingPathComponent("site", isDirectory: true)
        for part in path.split(separator: "/") {
            url = url.appendingPathComponent(String(part), isDirectory: false)
        }
        return try Data(contentsOf: url)
    }

    /// A copy read as JSON by the app's own reader, as the app reads a published file.
    static func json(_ path: String) throws -> JSONValue {
        return try XCTUnwrap(JSONValue.read(try data(path)), "site/\(path) does not read as JSON.")
    }
}

/// The input of a golden "file" case: the copy at `path`, or the file the case carries.
func caseFile(path: GoldenValue, inline: GoldenValue) throws -> JSONValue {
    if let named = path.text {
        return try SiteFixture.json(named)
    }
    return inline.json
}

/// Differences between the app's answers and the site's, counted, with the first few kept
/// to show: a family holds thousands of cases.
final class Differences {
    private(set) var count = 0
    private(set) var checked = 0
    private var shown: [String] = []

    /// One case compared.
    func compared() {
        checked += 1
    }

    func note(_ what: String) {
        count += 1
        if shown.count < 12 {
            shown.append(what)
        }
    }

    /// Fails the test if any case differed, or if no case was compared at all.
    func report(_ what: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertGreaterThan(checked, 0, "\(what): no case was compared.", file: file, line: line)
        if count > 0 {
            XCTFail("\(what): \(count) of \(checked) cases differ from the site's answers. The first:\n" + shown.joined(separator: "\n"), file: file, line: line)
        }
    }
}

/// The kind of a golden case (its first entry) and its entries; nil for a case that is not
/// a list starting with text.
func kindOf(_ value: GoldenValue) -> (kind: String, entries: [GoldenValue])? {
    guard let entries = value.entries, let kind = entries.first?.text else {
        return nil
    }
    return (kind, entries)
}

/// A closings row in the golden files' encoding:
/// [status, reason, announcedAt, shiftMinutes, clockMinute, manual, details], or null.
func goldenRow(_ row: StatusRow?) -> GoldenValue {
    guard let found = row else {
        return .null
    }
    return .array([
        .number(Double(found.status.rawValue)),
        golden(found.reason),
        golden(found.announcedAt),
        golden(found.shiftMinutes),
        golden(found.clockMinute),
        .bool(found.manual),
        .array(found.details.map { GoldenValue.number(Double($0)) }),
    ])
}

/// The app's words in the golden files' encoding: the text, null for none, or the refusal
/// mark where the app's function threw.
func shownAnswer(_ call: () throws -> ShownText?) -> GoldenValue {
    do {
        guard let text = try call() else {
            return .null
        }
        return .string(text.drawnString)
    } catch {
        return GoldenValue.throwsMark
    }
}

/// A number input: a JSON number, or the text the generator writes for a number JSON cannot
/// hold ("NaN", "Infinity", "-Infinity"); nil for anything else.
func inputNumber(_ value: GoldenValue) -> Double? {
    switch value {
    case .number(let number):
        return number
    case .string("NaN"):
        return Double.nan
    case .string("Infinity"):
        return Double.infinity
    case .string("-Infinity"):
        return -Double.infinity
    default:
        return nil
    }
}

/// An instant input as whole milliseconds; nil for the generator's "NaN" (the site's
/// invalid date, which an instant of the app cannot be) and anything else.
func inputInstant(_ value: GoldenValue) -> Int64? {
    guard let number = value.numeric else {
        return nil
    }
    return Int64(exactly: number)
}

/// A zone input: nil for null (no zone), else its name; `known` is false for anything that
/// is neither.
func inputZone(_ value: GoldenValue) -> (zone: String?, known: Bool) {
    switch value {
    case .null:
        return (nil, true)
    case .string(let name):
        return (name, true)
    default:
        return (nil, false)
    }
}

/// Whether a zone name is one the site may accept and the app does not hold: off the app's
/// list, or on it but unknown to this machine's Foundation. There the app reads no clock.
func appReadsNoClock(_ zone: String?) -> Bool {
    guard let name = zone, name != unreadZone, name != unknownZone else {
        return false
    }
    return !isTimeZone(name)
}

/// One "status" case of closings.json, with the file it reads:
/// ["status", name, directory, school, zone, now, schoolStatus, litStatus].
struct ClosingsStatusCase {
    let name: String
    let file: ClosingsFile
    /// The directory the school is from: the file's own stamp where the case gives null.
    let directory: DirectoryStamp
    let school: Int
    let zone: String?
    let now: Int64
    /// The site's `schoolStatus` as [today, tomorrow, later], or the refusal mark.
    let status: GoldenValue
    /// The site's `litStatus`: a status code, or null.
    let lit: GoldenValue
}

/// Every "status" case of closings.json, each with its file read by the app's own reader
/// (the copies by their path, a mutation from the file its case carries).
func closingsStatusCases(file: StaticString = #filePath, line: UInt = #line) throws -> [ClosingsStatusCase] {
    let golden = try GoldenFile.family("closings")
    var files: [String: ClosingsFile] = [:]
    for value in golden.cases {
        guard let read = kindOf(value), read.kind == "file", read.entries.count == 6, let name = read.entries[1].text else {
            continue
        }
        if let found = parseClosings(try caseFile(path: read.entries[2], inline: read.entries[3])) {
            files[name] = found
        }
    }
    var cases: [ClosingsStatusCase] = []
    for value in golden.cases {
        guard let read = kindOf(value), read.kind == "status" else {
            continue
        }
        let entries = read.entries
        guard entries.count == 8, let name = entries[1].text, let closings = files[name],
              let position = entries[3].numeric, let school = Int(exactly: position),
              let now = inputInstant(entries[5]) else {
            XCTFail("closings: a status case this test cannot read: \(value)", file: file, line: line)
            continue
        }
        let told = inputZone(entries[4])
        var directory = closings.directory
        if entries[2] != .null {
            guard let stamp = parseStamp(entries[2].json) else {
                XCTFail("closings: a status case's directory does not read: \(value)", file: file, line: line)
                continue
            }
            directory = stamp
        }
        guard told.known else {
            XCTFail("closings: a status case's zone does not read: \(value)", file: file, line: line)
            continue
        }
        cases.append(ClosingsStatusCase(
            name: name,
            file: closings,
            directory: directory,
            school: school,
            zone: told.zone,
            now: now,
            status: entries[6],
            lit: entries[7]
        ))
    }
    // The three copies and the mutation of three days, each school, zone and moment.
    XCTAssertGreaterThanOrEqual(cases.count, 3000, file: file, line: line)
    return cases
}

/// The app's `schoolStatus` in the golden files' encoding: [today, tomorrow, later], with
/// later as [[day, row]...].
func goldenStatus(_ status: SchoolStatus) -> GoldenValue {
    return .array([
        goldenRow(status.today),
        goldenRow(status.tomorrow),
        .array(status.later.map { GoldenValue.array([.string($0.day), goldenRow($0.row)]) }),
    ])
}
