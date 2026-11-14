import Foundation

// live/closings.json, read as the site reads it: the file's check
// (web/src/data/closings.ts `parseClosings`, `parseDay`), the gap column turned back into
// school positions (`decodeDay`), and a school's row on a day with its details
// (web/src/data/school-day.ts `rowOn`, `detailsOf`).
//
// A file that does not match its schema is not read at all: nothing is shown from it.

/// How far back a row's posting time may lie, in minutes (`MAX_MINUTES_AGO`).
private let maxMinutesAgo: Double = 20_160
/// The longest delay or early dismissal, in minutes (`MAX_SHIFT_MINUTES`).
private let maxShiftMinutes: Double = 720
/// The minutes of a day (`MINUTES_PER_DAY`).
private let minutesPerDay: Double = 1440
/// JavaScript's `Number.MAX_SAFE_INTEGER`: any whole reason code up to it reads.
private let maxSafeInteger: Double = 9_007_199_254_740_991
/// How many detail codes the details column may hold (school-day.ts `DETAIL_COUNT`).
private let detailCount = 22

/// A row's status: closed, delayed, remote, early dismissal (the file's codes 0 to 3).
enum ClosingStatus: Int, Equatable {
    case closed = 0
    case delayed = 1
    case remote = 2
    case earlyDismissal = 3

    /// Whether the status carries a shift and a clock entry.
    var isShifted: Bool {
        return self == .delayed || self == .earlyDismissal
    }
}

/// One day's rows, as the file holds them, checked.
struct ClosingsDay: Equatable {
    let day: String
    let gaps: [Int]
    let statuses: [ClosingStatus]
    let announced: [Int?]
    let reasons: [Int?]
    let shifts: [Int?]
    let clocks: [Int?]
    /// The rows the site's team set by hand, by position; empty for a file written before
    /// the column existed.
    let manual: [Int]
    /// The details column as the file holds it, unread: it is read row by row
    /// (`detailsOf`), so one that does not read gives none and never refuses the file.
    let details: JSONValue?
}

/// live/closings.json, checked.
struct ClosingsFile: Equatable {
    let generatedAt: String
    /// `generated_at` as whole milliseconds.
    let generatedAtMs: Int64
    let directory: DirectoryStamp
    let days: [ClosingsDay]
}

/// One day's rows, checked as closings.ts `parseDay` checks them; nil for anything else.
private func parseDay(_ value: JSONValue) -> ClosingsDay? {
    guard let group = value.fields,
          let day = group["day"]?.text, isLocalDateText(day),
          let gaps = group["gaps"]?.items,
          let statuses = group["statuses"]?.items,
          let announced = group["announced"]?.items,
          let reasons = group["reasons"]?.items,
          let shifts = group["shifts"]?.items,
          let clocks = group["clocks"]?.items else {
        return nil
    }
    let rows = gaps.count
    guard rows > 0, statuses.count == rows, announced.count == rows, reasons.count == rows else {
        return nil
    }
    var gapValues: [Int] = []
    var statusValues: [ClosingStatus] = []
    var announcedValues: [Int?] = []
    var reasonValues: [Int?] = []
    var shifted = 0
    for i in 0..<rows {
        guard let gap = indexValue(element(gaps, i)),
              let code = wholeValue(element(statuses, i), 0, 3),
              let status = ClosingStatus(rawValue: code) else {
            return nil
        }
        gapValues.append(gap)
        statusValues.append(status)
        guard let ago = nullOrWhole(element(announced, i), 0, maxMinutesAgo) else {
            return nil
        }
        announcedValues.append(ago)
        // Any whole reason code reads: one the site has no name for shows no words.
        guard let reason = nullOrWhole(element(reasons, i), 0, maxSafeInteger) else {
            return nil
        }
        reasonValues.append(reason)
        if status.isShifted {
            shifted += 1
        }
    }
    guard shifts.count == shifted, clocks.count == shifted else {
        return nil
    }
    var shiftValues: [Int?] = []
    var clockValues: [Int?] = []
    for k in 0..<shifted {
        guard let shift = nullOrWhole(element(shifts, k), 1, maxShiftMinutes),
              let clock = nullOrWhole(element(clocks, k), 0, minutesPerDay - 1) else {
            return nil
        }
        shiftValues.append(shift)
        clockValues.append(clock)
    }
    // The rows set by hand, by position: ascending, each a row of the day. A file written
    // before the column existed has none (absent; a null is not absent).
    var manualValues: [Int] = []
    if let manual = group["manual"] {
        guard let positions = manual.items else {
            return nil
        }
        var last = -1
        for position in positions {
            guard let at = wholeValue(position, Double(last + 1), Double(rows - 1)) else {
                return nil
            }
            manualValues.append(at)
            last = at
        }
    }
    return ClosingsDay(
        day: day,
        gaps: gapValues,
        statuses: statusValues,
        announced: announcedValues,
        reasons: reasonValues,
        shifts: shiftValues,
        clocks: clockValues,
        manual: manualValues,
        details: group["details"]
    )
}

/// A value that is null or a whole number from `min` to `max` (`isNullOr(value, isWhole)`):
/// nil where it is neither, else the number or nil for null.
private func nullOrWhole(_ value: JSONValue?, _ min: Double, _ max: Double) -> Int?? {
    if value == JSONValue.null {
        return .some(nil)
    }
    guard let whole = wholeValue(value, min, max) else {
        return nil
    }
    return .some(whole)
}

/// live/closings.json, checked against its schema as closings.ts `parseClosings` checks
/// it; nil for anything else.
func parseClosings(_ value: JSONValue?) -> ClosingsFile? {
    guard let file = value?.fields,
          file["schema_version"] == JSONValue.number(1),
          let generatedAt = file["generated_at"]?.text,
          let generatedAtMs = parseInstant(generatedAt),
          let directory = parseStamp(file["directory"]),
          let days = file["days"]?.items, days.count <= 3 else {
        return nil
    }
    var previous = ""
    var groups: [ClosingsDay] = []
    for day in days {
        // Sorted, one group per day.
        guard let group = parseDay(day), group.day > previous else {
            return nil
        }
        previous = group.day
        groups.append(group)
    }
    return ClosingsFile(generatedAt: generatedAt, generatedAtMs: generatedAtMs, directory: directory, days: groups)
}

/// One day's rows as the site's arrays hold them: school positions, ascending, and their
/// statuses.
struct DayRows: Equatable {
    let day: String
    /// Each row's school position. The site keeps these in a Uint32Array, so a position
    /// is kept as the site keeps it: the low 32 bits of the running sum of the gaps.
    let schools: [UInt32]
    let statuses: [ClosingStatus]
}

/// Turns the gap column back into school positions (closings.ts `decodeDay`).
func decodeDay(_ group: ClosingsDay) -> DayRows {
    var schools: [UInt32] = []
    var previous: Int64 = -1
    for gap in group.gaps {
        previous += 1 + Int64(gap)
        schools.append(UInt32(truncatingIfNeeded: previous))
    }
    return DayRows(day: group.day, schools: schools, statuses: group.statuses)
}

/// A school's status on one day, as its closings row gives it (school-day.ts `StatusRow`).
struct StatusRow: Equatable {
    let status: ClosingStatus
    /// The reason code: a named reason, or a code the site has no words for; or nil.
    let reason: Int?
    /// When it was posted, as whole milliseconds, or nil when the listing gave no time.
    let announcedAt: Int64?
    /// How late the day starts or how early it ends, for a delay or early dismissal.
    let shiftMinutes: Int?
    /// The stated opening or dismissal time, minutes after midnight.
    let clockMinute: Int?
    /// Whether the site's own team set it by hand.
    let manual: Bool
    /// The plain details its listings state (detail codes, ascending); empty for none.
    let details: [Int]
}

/// The start of the UTC minute a MinutesAgo value names (school-day.ts `minuteBefore`).
private func minuteBefore(_ generatedAtMs: Int64, _ ago: Int) -> Int64 {
    return (floorDivide(generatedAtMs, minuteMs) - Int64(ago)) * minuteMs
}

/// The details of the row at `position`: the day's details column read here, so a file
/// written before the column, or one whose column does not read, gives none
/// (school-day.ts `detailsOf`). Details only add to a status: a column that does not read
/// never hides one.
private func detailsOf(_ group: ClosingsDay, _ position: Int) -> [Int] {
    guard let column = group.details?.items else {
        return []
    }
    var last = -1
    var found: [Int] = []
    for entry in column {
        guard let pair = entry.items, pair.count == 2,
              let at = indexValue(element(pair, 0)), at > last,
              let codes = element(pair, 1)?.items, codes.count > 0 else {
            return []
        }
        var previous = -1
        var values: [Int] = []
        for code in codes {
            guard let value = indexValue(code), value > previous, value < detailCount else {
                return []
            }
            values.append(value)
            previous = value
        }
        last = at
        if at == position {
            found = values
        }
    }
    return found
}

/// The school's row on `day` (its position in the directory), or nil (school-day.ts
/// `rowOn`).
func rowOn(_ closings: ClosingsFile, day: String, school: Int) -> StatusRow? {
    guard let group = closings.days.first(where: { $0.day == day }) else {
        return nil
    }
    let rows = decodeDay(group)
    var low = 0
    var high = rows.schools.count
    let wanted = Int64(school)
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
            // shifts and clocks hold one entry for each delayed or early-dismissal row, in
            // row order.
            var slot = -1
            for status in group.statuses.prefix(middle + 1) where status.isShifted {
                slot += 1
            }
            let status = element(group.statuses, middle) ?? .closed
            let shifted = status.isShifted
            let ago = element(group.announced, middle) ?? nil
            return StatusRow(
                status: status,
                reason: element(group.reasons, middle) ?? nil,
                announcedAt: ago.map { minuteBefore(closings.generatedAtMs, $0) },
                shiftMinutes: shifted ? (element(group.shifts, slot) ?? nil) : nil,
                clockMinute: shifted ? (element(group.clocks, slot) ?? nil) : nil,
                manual: group.manual.contains(middle),
                details: detailsOf(group, middle)
            )
        }
    }
    return nil
}
