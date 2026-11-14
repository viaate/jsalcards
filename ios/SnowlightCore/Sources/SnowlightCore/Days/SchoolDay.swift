import Foundation

// What the closings file says about a school today and tomorrow, as the site's school panel
// reads it (web/src/data/school-day.ts `schoolToday`, `schoolStatus`; PLAN section 4,
// rule B): its row on its own today and its row on the day after, each a row or nothing.
//
// There is no "open" in M0 at all. The site says "open" only where live/covered.json says
// the school's closings were checked that same day, and that file is not published: the
// site's answer is read here as `schoolStatus({..., covered: null})`, whose today is never
// "open".

/// The school's today at a moment (school-day.ts `schoolToday`): the calendar day on its
/// clock, or without a zone, or with `unreadZone`, the day that is today everywhere (nil
/// overnight); nil for `unknownZone` and any clock not known.
func schoolToday(_ now: Int64, _ zone: String?) -> String? {
    guard let named = zone, named != unreadZone else {
        return todayEverywhere(now)
    }
    return localDay(now, named)
}

/// A row announced for a day after tomorrow, and its day (school-day.ts `LaterRow`).
struct LaterRow: Equatable {
    let day: String
    let row: StatusRow
}

/// What the closings file says about a school (school-day.ts `SchoolStatus`, read with no
/// covered file): today's row and tomorrow's, each nil when the file has none, and the rows
/// announced for the days after tomorrow, earliest first.
struct SchoolStatus: Equatable {
    let today: StatusRow?
    let tomorrow: StatusRow?
    let later: [LaterRow]

    /// Nothing known (`NO_STATUS`).
    static let nothing = SchoolStatus(today: nil, tomorrow: nil, later: [])
}

/// What the closings file says about a school today and tomorrow, and after
/// (school-day.ts `schoolStatus` with `covered: null`): nothing when the school has no
/// today at `now`, when there is no file, or when the file is for another directory.
func schoolStatus(school: Int, directory: DirectoryStamp, closings: ClosingsFile?, now: Int64, zone: String?) -> SchoolStatus {
    guard let today = schoolToday(now, zone),
          let file = closings,
          sameStamp(file.directory, directory),
          let tomorrowDay = siteNextDay(today) else {
        return SchoolStatus.nothing
    }
    let todayRow = rowOn(file, day: today, school: school)
    let tomorrowRow = rowOn(file, day: tomorrowDay, school: school)
    var later: [LaterRow] = []
    for group in file.days where group.day > tomorrowDay {
        if let row = rowOn(file, day: group.day, school: school) {
            later.append(LaterRow(day: group.day, row: row))
        }
    }
    later.sort { $0.day < $1.day }
    return SchoolStatus(today: todayRow, tomorrow: tomorrowRow, later: later)
}
