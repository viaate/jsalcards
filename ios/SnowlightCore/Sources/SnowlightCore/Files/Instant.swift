import Foundation

// The published files' UtcInstant, read as strictly as the site reads it
// (web/src/state/instant.ts), and the few calendar sums the file readers need, done by
// hand: no formatter, no pattern engine, no calendar of the device's.
//
// An instant inside the package is whole milliseconds since 1970-01-01T00:00:00Z (Int64),
// as a JavaScript Date holds it.

/// Milliseconds in a minute, an hour and a day.
let minuteMs: Int64 = 60_000
let hourMs: Int64 = 3_600_000
let dayMs: Int64 = 86_400_000

/// The widest instant a JavaScript Date holds, either side of 1970 (TimeClip).
let siteTimeLimit: Int64 = 8_640_000_000_000_000

/// Whether an instant is one a JavaScript Date can hold (else the site's Date is invalid).
func isSiteTime(_ ms: Int64) -> Bool {
    return ms >= -siteTimeLimit && ms <= siteTimeLimit
}

/// `a / b` rounded down, for b > 0 (Swift's `/` rounds toward zero).
func floorDivide(_ a: Int64, _ b: Int64) -> Int64 {
    let quotient = a / b
    return (a % b != 0 && a < 0) ? quotient - 1 : quotient
}

/// Days since 1970-01-01 of a day of the proleptic Gregorian calendar (month 1...12).
func daysFromCivil(_ year: Int64, _ month: Int64, _ day: Int64) -> Int64 {
    let y = month <= 2 ? year - 1 : year
    let era = floorDivide(y, 400)
    let yoe = y - era * 400
    let mp = (month + 9) % 12
    let doy = (153 * mp + 2) / 5 + day - 1
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
    return era * 146_097 + doe - 719_468
}

/// The year, month (1...12) and day of a count of days since 1970-01-01.
func civilFromDays(_ days: Int64) -> (year: Int64, month: Int64, day: Int64) {
    let z = days + 719_468
    let era = floorDivide(z, 146_097)
    let doe = z - era * 146_097
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
    let mp = (5 * doy + 2) / 153
    let day = doy - (153 * mp + 2) / 5 + 1
    let month = mp < 10 ? mp + 3 : mp - 9
    return (month <= 2 ? yoe + era * 400 + 1 : yoe + era * 400, month, day)
}

/// The number of days in a month (1...12) of a year.
func daysInMonth(_ year: Int64, _ month: Int64) -> Int64 {
    switch month {
    case 2:
        let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
        return leap ? 29 : 28
    case 4, 6, 9, 11:
        return 30
    default:
        return 31
    }
}

/// JavaScript's `Date.UTC(year, monthIndex, day)` for whole numbers: a year from 0 to 99
/// is read as 1900 to 1999, a month past 11 or a day past the month's end rolls on, and
/// nil is the site's invalid date (beyond what a Date holds).
func siteDateUTC(_ year: Int64, _ monthIndex: Int64, _ day: Int64) -> Int64? {
    let fullYear = (year >= 0 && year <= 99) ? year + 1900 : year
    let addedYears = floorDivide(monthIndex, 12)
    let month = monthIndex - addedYears * 12
    let days = daysFromCivil(fullYear + addedYears, month + 1, 1) + day - 1
    let ms = days * dayMs
    return isSiteTime(ms) ? ms : nil
}

/// Digits of a whole number, at least `width` of them, with no sign.
private func digits(_ value: Int64, _ width: Int) -> String {
    let plain = "\(value < 0 ? -value : value)"
    let count = plain.utf16.count
    return count >= width ? plain : String(repeating: "0", count: width - count) + plain
}

/// The day of an instant as `toISOString().slice(0, 10)` writes it (YYYY-MM-DD; a year
/// before 0 or after 9999 as six digits with its sign, as JavaScript writes it); nil where
/// the site's Date is invalid and `toISOString` throws.
func isoDay(_ ms: Int64) -> String? {
    guard isSiteTime(ms) else {
        return nil
    }
    let civil = civilFromDays(floorDivide(ms, dayMs))
    let yearText: String
    if civil.year >= 0 && civil.year <= 9999 {
        yearText = digits(civil.year, 4)
    } else {
        yearText = (civil.year < 0 ? "-" : "+") + digits(civil.year, 6)
    }
    return yearText + "-" + digits(civil.month, 2) + "-" + digits(civil.day, 2)
}

/// The value of the ASCII digits 0 to 9 at `range` of a UTF-16 text, or nil if any unit is
/// not one. JavaScript's `\d` is these ten and no other script's.
func asciiNumber(_ units: [UInt16], _ range: Range<Int>) -> Int64? {
    guard range.lowerBound >= 0, range.upperBound <= units.count else {
        return nil
    }
    var value: Int64 = 0
    for index in range {
        let unit = units[index]
        guard unit >= 0x30, unit <= 0x39 else {
            return nil
        }
        value = value * 10 + Int64(unit - 0x30)
    }
    return value
}

/// The year, month and day of a text shaped `^\d{4}-\d{2}-\d{2}$` (the files' LocalDate
/// pattern), whether or not it names a real day; nil for any other shape.
func localDateParts(_ text: String) -> (year: Int64, month: Int64, day: Int64)? {
    let units = Array(text.utf16)
    guard units.count == 10, units[4] == 0x2D, units[7] == 0x2D,
          let year = asciiNumber(units, 0..<4),
          let month = asciiNumber(units, 5..<7),
          let day = asciiNumber(units, 8..<10) else {
        return nil
    }
    return (year, month, day)
}

/// Whether a text has the files' LocalDate shape, `^\d{4}-\d{2}-\d{2}$` (the shape only:
/// `2027-02-30` passes, as it does on the site).
func isLocalDateText(_ text: String) -> Bool {
    return localDateParts(text) != nil
}

/// Whether a value is text of the LocalDate shape.
func isLocalDate(_ value: JSONValue?) -> Bool {
    guard let text = value?.text else {
        return false
    }
    return isLocalDateText(text)
}

/// The calendar day after `day`, as the site's `nextDay` gives it (map-day.ts):
/// `Date.parse(day + "T00:00:00Z")` and a day on. The site's Date takes a day of 1 to 31 in
/// any month and rolls it on (`2027-02-30` is March 2); a month outside 1 to 12 or a day
/// outside 1 to 31 is an invalid date, on which the site's `toISOString` throws: nil here,
/// and every caller refuses the file.
func siteNextDay(_ day: String) -> String? {
    guard let parts = localDateParts(day),
          parts.month >= 1, parts.month <= 12, parts.day >= 1, parts.day <= 31 else {
        return nil
    }
    return isoDay((daysFromCivil(parts.year, parts.month, 1) + parts.day) * dayMs)
}

/// A UtcInstant (`YYYY-MM-DDTHH:MM:SSZ`) that names a real moment, as whole milliseconds;
/// nil for any other text (web/src/state/instant.ts `parseInstant`). February 30 is
/// refused; the year 0000 is read, as on the site.
func parseInstant(_ text: String) -> Int64? {
    let units = Array(text.utf16)
    guard units.count == 20,
          units[4] == 0x2D, units[7] == 0x2D, units[10] == 0x54,
          units[13] == 0x3A, units[16] == 0x3A, units[19] == 0x5A,
          let year = asciiNumber(units, 0..<4),
          let month = asciiNumber(units, 5..<7),
          let day = asciiNumber(units, 8..<10),
          let hour = asciiNumber(units, 11..<13),
          let minute = asciiNumber(units, 14..<16),
          let second = asciiNumber(units, 17..<19) else {
        return nil
    }
    guard month >= 1, month <= 12, day >= 1, day <= daysInMonth(year, month),
          hour <= 23, minute <= 59, second <= 59 else {
        return nil
    }
    let days = daysFromCivil(year, month, day)
    return days * dayMs + hour * hourMs + minute * minuteMs + second * 1000
}

/// A value that is a UtcInstant, as whole milliseconds; nil for anything else.
func parseInstant(_ value: JSONValue?) -> Int64? {
    guard let text = value?.text else {
        return nil
    }
    return parseInstant(text)
}
