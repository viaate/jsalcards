import Foundation

// The site's calendar days (YYYY-MM-DD), read as its formatters read them
// (web/src/copy-format.ts `parseLocalDate`), and the two ways the site turns a day into an
// instant. The sums are done by hand (Files/Instant.swift: days since 1970 from year, month
// and day and back), with no time zone and no calendar of the device's.

/// The UTC midnight of a calendar day, as whole milliseconds, read as copy-format.ts
/// `parseLocalDate` reads it: `^\d{4}-\d{2}-\d{2}$` (ASCII digits only), then
/// `Date.UTC(year, month - 1, day)`, kept only if that prints back the same year, month and
/// day. So February 30 is refused, and so is any year from 0000 to 0099, which `Date.UTC`
/// reads as 1900 to 1999. It throws where the site's throws.
func parseLocalDate(_ text: String) throws -> Int64 {
    guard let parts = localDateParts(text),
          let ms = siteDateUTC(parts.year, parts.month - 1, parts.day) else {
        throw SiteRefusal()
    }
    let civil = civilFromDays(floorDivide(ms, dayMs))
    guard civil.year == parts.year, civil.month == parts.month, civil.day == parts.day else {
        throw SiteRefusal()
    }
    return ms
}

/// A day's UTC midnight as the site's `Date.parse(day + "T00:00:00Z")` gives it, as whole
/// milliseconds; nil where that is the site's invalid date. The site's Date takes a day of 1
/// to 31 in any month and rolls it on (`2027-02-30` is March 2), as `siteNextDay` does.
func siteDayStart(_ day: String) -> Int64? {
    guard let parts = localDateParts(day),
          parts.month >= 1, parts.month <= 12, parts.day >= 1, parts.day <= 31 else {
        return nil
    }
    let ms = (daysFromCivil(parts.year, parts.month, 1) + parts.day - 1) * dayMs
    return isSiteTime(ms) ? ms : nil
}

/// The day of the week of a count of days since 1970-01-01: 0 for Sunday to 6 for Saturday
/// (1970-01-01 was a Thursday).
func weekdayIndex(_ days: Int64) -> Int {
    let inWeek = ((days % 7) + 7) % 7
    return Int((inWeek + 4) % 7)
}
