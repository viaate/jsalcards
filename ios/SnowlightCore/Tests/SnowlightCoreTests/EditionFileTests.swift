import XCTest
@testable import SnowlightCore

/// schools/edition.json is read as its schema states it (schemas/directory-edition.schema.json:
/// every key required, no other key, a real day, whole counts, a lower-case SHA-256 digest),
/// and its stamp names the same directory as the published files written against it. The
/// site has no check of this file to follow, so these are written cases; each refusal is
/// one change to the copied file.
final class EditionFileTests: XCTestCase {
    private func fixture() throws -> [String: JSONValue] {
        let value = try SiteFixture.json("schemas/examples/synthetic-directory-edition.json")
        return try XCTUnwrap(value.fields, "the copied edition file is not an object.")
    }

    func testTheCopiedFileReadsAndNamesTheFilesDirectory() throws {
        let edition = try XCTUnwrap(parseEdition(.object(try fixture())), "the copied edition file is refused.")
        let fields = try fixture()
        XCTAssertEqual(edition.contentSha256, fields["content_sha256"]?.text)
        XCTAssertEqual(edition.stamp, parseStamp(.object(fields)))
        // The synthetic closings and season files are written against the same directory.
        let closings = try XCTUnwrap(parseClosings(try SiteFixture.json("schemas/examples/synthetic-closings.json")))
        XCTAssertTrue(sameStamp(edition.stamp, closings.directory))
        let season = try XCTUnwrap(parseSeason(try SiteFixture.json("schemas/examples/synthetic-live-season.json")))
        XCTAssertTrue(sameStamp(edition.stamp, season.directory))
        // A stamp that differs in any one part names another directory.
        let stamp = edition.stamp
        XCTAssertFalse(sameStamp(stamp, DirectoryStamp(generatedOn: stamp.generatedOn, schools: stamp.schools + 1, districts: stamp.districts)))
        XCTAssertFalse(sameStamp(stamp, DirectoryStamp(generatedOn: stamp.generatedOn, schools: stamp.schools, districts: stamp.districts + 1)))
        XCTAssertFalse(sameStamp(stamp, DirectoryStamp(generatedOn: "2026-09-25", schools: stamp.schools, districts: stamp.districts)))
    }

    func testEveryOneChangeThatBreaksTheSchemaIsRefused() throws {
        let base = try fixture()
        var changes: [(String, [String: JSONValue])] = []
        func with(_ key: String, _ value: JSONValue?) -> [String: JSONValue] {
            var copy = base
            copy[key] = value
            return copy
        }
        changes.append(("schema 2", with("schema_version", .number(2))))
        changes.append(("schema as text", with("schema_version", .string("1"))))
        changes.append(("schema true", with("schema_version", .bool(true))))
        changes.append(("an unknown key", with("note", .string("x"))))
        for key in ["schema_version", "generated_on", "schools", "districts", "content_sha256"] {
            changes.append(("no \(key)", with(key, nil)))
        }
        changes.append(("day Feb 30", with("generated_on", .string("2026-02-30"))))
        changes.append(("day short", with("generated_on", .string("2026-9-24"))))
        changes.append(("day full-width", with("generated_on", .string("\u{FF12}026-09-24"))))
        changes.append(("day with a newline", with("generated_on", .string("2026-09-24\n"))))
        changes.append(("schools not whole", with("schools", .number(6.5))))
        changes.append(("schools negative", with("schools", .number(-1))))
        changes.append(("schools true", with("schools", .bool(true))))
        changes.append(("districts past the limit", with("districts", .number(4_294_967_295))))
        changes.append(("digest upper case", with("content_sha256", .string(String(repeating: "A", count: 64)))))
        changes.append(("digest short", with("content_sha256", .string(String(repeating: "0", count: 63)))))
        changes.append(("digest null", with("content_sha256", .null)))
        for (name, fields) in changes {
            XCTAssertNil(parseEdition(.object(fields)), "\(name): the app reads a file its schema refuses.")
        }
        XCTAssertNil(parseEdition(.array([.object(base)])))
        XCTAssertNil(parseEdition(nil))
        // And the largest counts the schema allows still read.
        XCTAssertNotNil(parseEdition(.object(with("schools", .number(4_294_967_294)))))
    }
}
