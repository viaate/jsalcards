import Foundation

// The status a school's light shows on the site's map (web/src/data/closings.ts
// `litStatus`): its row on its map day, by the clock its zone tells. The app's big status
// is always this (PLAN section 4: "My School's big status always equals that school's
// light on the site's map").

/// The status a school's light shows: its row on its map day (`mapDay`), or nil for none
/// (no file, a file for another directory, no day to be had, no row that day).
func litStatus(_ closings: ClosingsFile?, directory: DirectoryStamp, school: Int, zone: String?, now: Int64) -> ClosingStatus? {
    guard let file = closings, sameStamp(file.directory, directory),
          let day = mapDay(now, zone),
          let group = file.days.first(where: { $0.day == day }) else {
        return nil
    }
    let rows = decodeDay(group)
    let wanted = Int64(school)
    var low = 0
    var high = rows.schools.count
    while low < high {
        let middle = (low + high) / 2
        guard let at = element(rows.schools, middle) else {
            return nil
        }
        let found = Int64(at)
        if found < wanted {
            low = middle + 1
        } else if found > wanted {
            high = middle
        } else {
            return element(rows.statuses, middle)
        }
    }
    return nil
}
