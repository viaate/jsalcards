// What the My School screen is made from (M1 4.1): the two live files, the school, its
// record, the two clocks and the moment. Nothing of it is public: the kit makes one only
// through `MySchoolInput.decode` (Files/MySchoolFixture.swift), bytes in, never text, and
// hands it to `mySchoolModel` (Screens/MySchoolModel.swift).
//
// Rule of every screen model that shows a time or a day (Screens/ShellModel.swift): days are
// told on the school's clock (`schoolZone`), times a person reads on the viewer's
// (`viewerZone`). The moment is always a parameter (README rule 4).

/// The input of the My School model.
public struct MySchoolInput {
    /// live/closings.json, checked; nil while no file the site accepts is had.
    let closings: ClosingsFile?
    /// live/season.json, checked; nil for none.
    let season: SeasonFile?
    /// The school's position in the directory.
    let school: Int
    /// The school's record and S3's two shown names (Files/SchoolRecord.swift).
    let record: SchoolRecord
    /// The school's clock: a name `isTimeZone` accepts, `unreadZone`, `unknownZone`, or nil
    /// for none known (Days/MapDay.swift). From M5 the predictions file's; in M1 the
    /// fixture's.
    let schoolZone: String?
    /// The phone's zone, a name `isTimeZone` accepts: from M5 the device clock's; in M1 the
    /// fixture's, or the tour's `tour.zone`.
    let viewerZone: String
    /// The moment, as whole milliseconds since 1970 UTC.
    let now: Int64
}
