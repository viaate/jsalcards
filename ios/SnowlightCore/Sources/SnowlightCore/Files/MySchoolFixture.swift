import Foundation

// A My School fixture of the picture tour (M1 5.1), read into the screen's input: one JSON
// object with these keys, as ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/tour/ holds
// them:
//
//   now            the moment, a UtcInstant ("2027-01-12T11:55:00Z");
//   school         the school's position in the directory;
//   school_zone    the school's clock: a zone name, or null for none known;
//   viewer_zone    the phone's zone: a zone name;
//   record         { row: the details row in recordOf's order, shown: S3's shown name,
//                    district_shown: S3's district name } (either name may be null or left out);
//   closings       live/closings.json as an object (its directory stamp is the record's);
//   season         live/season.json as an object, or null for none.
//
// Every zone is checked as every zone of the app is (`isTimeZone`): a name off the app's list
// makes the whole fixture refused, so the tour fails rather than show a guessed clock. A
// closings or season file the site would refuse is had as none, as the site has it.

extension MySchoolInput {
    /// The input a fixture holds, or nil where it does not read. `viewerZone`, when given,
    /// is the UTF-8 bytes of a zone name that takes the fixture's `viewer_zone`'s place.
    public static func decode(_ fixture: Data, viewerZone: Data?) -> MySchoolInput? {
        guard let fields = JSONValue.read(fixture)?.fields,
              let now = parseInstant(fields["now"]),
              let school = indexValue(fields["school"]),
              let record = fields["record"]?.fields,
              let shown = nameOrNone(record["shown"]),
              let districtShown = nameOrNone(record["district_shown"]),
              let closings = fields["closings"],
              let directory = parseStamp(closings.fields?["directory"]),
              let season = fields["season"],
              let schoolZone = zoneOrNone(fields["school_zone"]),
              let row = recordOf(record["row"], index: school, directory: directory, shown: shown, districtShown: districtShown) else {
            return nil
        }
        var viewer = fields["viewer_zone"]?.text
        if let bytes = viewerZone {
            viewer = String(data: bytes, encoding: .utf8)
        }
        guard let viewerName = viewer, isTimeZone(viewerName) else {
            return nil
        }
        var seasonFile: SeasonFile?
        if season != JSONValue.null {
            seasonFile = parseSeason(season)
        }
        return MySchoolInput(
            closings: parseClosings(closings),
            season: seasonFile,
            school: school,
            record: row,
            schoolZone: schoolZone,
            viewerZone: viewerName,
            now: now
        )
    }

    /// A shown name: the text, or nil for null or no entry, wrapped; nil itself for any other
    /// kind.
    private static func nameOrNone(_ value: JSONValue?) -> String?? {
        guard let found = value, found != JSONValue.null else {
            return .some(nil)
        }
        guard let text = found.text else {
            return nil
        }
        return .some(text)
    }

    /// The school's clock: a zone name `isTimeZone` accepts, or nil for null, wrapped; nil
    /// itself for anything else.
    private static func zoneOrNone(_ value: JSONValue?) -> String?? {
        if value == JSONValue.null {
            return .some(nil)
        }
        guard let name = value?.text, isTimeZone(name) else {
            return nil
        }
        return .some(name)
    }
}
