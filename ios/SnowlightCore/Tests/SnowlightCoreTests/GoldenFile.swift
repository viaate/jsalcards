import Foundation

/// A value read from a golden file, kept apart by kind: `true` is never a number and a
/// number is never a string.
indirect enum GoldenValue: Decodable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([GoldenValue])
    case object([String: GoldenValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([GoldenValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: GoldenValue].self))
        }
    }

    /// The value at a path of object keys, or nil where the path leaves the objects.
    func at(_ path: [String]) -> GoldenValue? {
        var here = self
        for key in path {
            guard case .object(let fields) = here, let next = fields[key] else {
                return nil
            }
            here = next
        }
        return here
    }

    var text: String? {
        if case .string(let value) = self {
            return value
        }
        return nil
    }
}

/// One site file a golden file was made from.
struct GoldenSource: Decodable, Equatable {
    let path: String
    let sha256: String
}

/// One golden file: the answers the site's own code gave, written by
/// ios/tools/gen-golden.mjs into Fixtures/golden/<family>.json. Never edited by hand.
struct GoldenFile: Decodable {
    let family: String
    let minCases: Int
    let madeFrom: [GoldenSource]
    let cases: [GoldenValue]

    private enum CodingKeys: String, CodingKey {
        case family
        case minCases = "min_cases"
        case madeFrom = "made_from"
        case cases
    }

    /// Where the golden files sit inside the test bundle, or nil if they were not copied.
    static func folder() -> URL? {
        // The Fixtures folder is copied whole into the test bundle. Where a bundle keeps
        // its resources differs between Linux and macOS, so both ways of asking are tried.
        var candidates: [URL] = []
        if let found = Bundle.module.url(forResource: "Fixtures", withExtension: nil) {
            candidates.append(found)
        }
        if let root = Bundle.module.resourceURL {
            candidates.append(root.appendingPathComponent("Fixtures", isDirectory: true))
        }
        for candidate in candidates {
            let golden = candidate.appendingPathComponent("golden", isDirectory: true)
            if FileManager.default.fileExists(atPath: golden.path) {
                return golden
            }
        }
        return nil
    }

    /// The names of the families in the test bundle, sorted.
    static func familyNames() throws -> [String] {
        guard let folder = folder() else {
            return []
        }
        let names = try FileManager.default.contentsOfDirectory(atPath: folder.path)
        var families: [String] = []
        for name in names where name.hasSuffix(".json") {
            families.append(String(name.dropLast(5)))
        }
        return families.sorted()
    }

    /// Loads one family by name. A test names its family with this call, written with
    /// the name in quotes, and a script (ios/tools/check-ios.mjs) reads those names: every
    /// golden file must be named by a test, and every name must be a golden file.
    static func family(_ name: String) throws -> GoldenFile {
        guard let folder = folder() else {
            throw GoldenError.noFixtures
        }
        let url = folder.appendingPathComponent(name + ".json", isDirectory: false)
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(GoldenFile.self, from: data)
    }
}

enum GoldenError: Error {
    case noFixtures
}
