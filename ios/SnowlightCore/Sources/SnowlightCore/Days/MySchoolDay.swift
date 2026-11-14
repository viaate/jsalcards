import Foundation

// The one new rule of the app's school screen (PLAN section 4, rules A and B2): which of a
// school's posted rows is the big status, and which are the other posted days.
//
// The big status is about the school's map day (rule A): its today until 3:30 PM on its
// clock, its tomorrow from then. Its row is the row of the site's `schoolStatus` for that
// day, so it is always the school's light on the site's map (`litStatus`). Every other row
// of the site's `schoolStatus` is kept, never dropped: a closing posted for tomorrow before
// 3:30 PM is one of the other posted days, and the rows announced for the days after
// tomorrow are kept as the site keeps them. How the screen arranges them is M1's.

/// Which of the site's two days a posted row is for: the site's own words for them are
/// "today" and "tomorrow" (`copy.statusLine.*.today`, `.tomorrow`).
enum PostedDay: Equatable {
    case today
    case tomorrow
}

/// A posted row that is not the big status: which of the two days it is, its day, its row.
struct OtherPostedDay: Equatable {
    let which: PostedDay
    /// YYYY-MM-DD.
    let day: String
    let row: StatusRow
}

/// A school's posted days, arranged for its screen.
struct MySchoolDays: Equatable {
    /// The day the big status is about: the school's map day (`mapDay`), or nil where it has
    /// none.
    let statusDay: String?
    /// The row of the site's `schoolStatus` whose day is `statusDay`, or nil.
    let hero: StatusRow?
    /// The site's other rows for today and tomorrow, today before tomorrow.
    let others: [OtherPostedDay]
    /// The site's rows for the days after tomorrow, earliest first (`schoolStatus` later).
    let later: [LaterRow]
}

/// A school's posted days at `now`: the big status and the other posted days, which
/// together are exactly the rows of the site's `schoolStatus` for the same input.
func mySchoolDays(closings: ClosingsFile?, directory: DirectoryStamp, school: Int, zone: String?, now: Int64) -> MySchoolDays {
    let statusDay = mapDay(now, zone)
    let status = schoolStatus(school: school, directory: directory, closings: closings, now: now, zone: zone)
    guard let today = schoolToday(now, zone), let tomorrow = siteNextDay(today) else {
        return MySchoolDays(statusDay: statusDay, hero: nil, others: [], later: status.later)
    }
    var hero: StatusRow?
    var others: [OtherPostedDay] = []
    let posted: [(which: PostedDay, day: String, row: StatusRow?)] = [
        (which: PostedDay.today, day: today, row: status.today),
        (which: PostedDay.tomorrow, day: tomorrow, row: status.tomorrow),
    ]
    for entry in posted {
        guard let row = entry.row else {
            continue
        }
        if entry.day == statusDay {
            hero = row
        } else {
            others.append(OtherPostedDay(which: entry.which, day: entry.day, row: row))
        }
    }
    return MySchoolDays(statusDay: statusDay, hero: hero, others: others, later: status.later)
}
