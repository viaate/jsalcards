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
