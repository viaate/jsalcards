import Foundation

// The directory stamp every published file carries: which edition of the school directory
// its positions point into (web/src/data/map-day.ts `parseStamp`, school-day.ts
// `sameStamp`). A school is its position in that directory alone, so a file stamped for
// another directory says nothing about any school.

/// A directory's stamp: the day it was made and how many schools and districts it holds.
struct DirectoryStamp: Equatable {
    /// `generated_on`, a LocalDate (by its shape; map-day.ts checks no more).
    let generatedOn: String
    let schools: Int
    let districts: Int
}

/// A stamp, checked as map-day.ts `parseStamp` checks it; nil for anything else.
func parseStamp(_ value: JSONValue?) -> DirectoryStamp? {
    guard let fields = value?.fields,
          let day = fields["generated_on"]?.text, isLocalDateText(day),
          let schools = indexValue(fields["schools"]),
          let districts = indexValue(fields["districts"]) else {
        return nil
    }
    return DirectoryStamp(generatedOn: day, schools: schools, districts: districts)
}

/// Whether two stamps name the same directory (school-day.ts `sameStamp`).
func sameStamp(_ a: DirectoryStamp, _ b: DirectoryStamp) -> Bool {
    return a.generatedOn == b.generatedOn && a.schools == b.schools && a.districts == b.districts
}
