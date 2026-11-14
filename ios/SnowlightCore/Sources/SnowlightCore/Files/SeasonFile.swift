import Foundation

// live/season.json: each school's closed, delayed, remote and early-dismissal days this
// school year, read as the site reads it (web/src/data/season.ts `parseSeason`,
// `lastDayOver`, `schoolSeason`).
//
// A count is said only when the file holds it and still speaks for now: a file that does
// not read, is for another directory, is emptied or is stale says nothing, and neither
// does a school it does not list.

/// The far west's lag behind UTC (PST): a day is over everywhere 8 hours after UTC midnight.
private let westBehindMs: Int64 = 8 * hourMs
/// How long past its due time a file's last day counted still stands (`SEASON_GRACE_MS`).
let seasonGraceMs: Int64 = hourMs
/// The most days a count may hold (`MAX_DAYS`).
private let maxDays: Double = 366

/// live/season.json, checked.
struct SeasonFile: Equatable {
    let season: String
    let since: String
    let through: String
    let directory: DirectoryStamp
    /// The digest of the counts, or nil for a file emptied on purpose (a blank).
    let contentSha256: String?
    let gaps: [Int]
    let closed: [Int]
    let delayed: [Int]
    let remote: [Int]
    let earlyDismissal: [Int]
}

/// A school's days this school year (copy-season.ts `SeasonDays`).
struct SeasonDays: Equatable {
    let closed: Int
    let delayed: Int
    let remote: Int
    let earlyDismissal: Int
}

/// What the panel's season line says for one school (season.ts `SchoolSeason`).
struct SchoolSeason: Equatable {
    let days: SeasonDays
    /// The day counting began, when it is after the school year's first day; else nil.
    let since: String?
}

/// The site's refusal: where a site function throws, the port throws this.
struct SiteRefusal: Error, Equatable {}

/// A real calendar day (YYYY-MM-DD) as its UTC midnight in ms, or nil (season.ts `dayMs`).
/// The site makes the day with `Date.UTC`, which reads a year from 0 to 99 as 1900 to
/// 1999, and keeps it only if it prints back the same: so such a year never reads.
private func seasonDayMs(_ value: JSONValue?) -> Int64? {
    guard let text = value?.text, let parts = localDateParts(text),
          let ms = siteDateUTC(parts.year, parts.month - 1, parts.day),
          isoDay(ms) == text else {
        return nil
    }
    return ms
}

/// A stamp as season.ts `isStamp` checks it: stricter than map-day.ts `parseStamp`, its
/// day must be a real one.
private func seasonStamp(_ value: JSONValue?) -> DirectoryStamp? {
    guard let fields = value?.fields,
          seasonDayMs(fields["generated_on"]) != nil,
          let day = fields["generated_on"]?.text,
          let schools = indexValue(fields["schools"]),
          let districts = indexValue(fields["districts"]) else {
        return nil
    }
    return DirectoryStamp(generatedOn: day, schools: schools, districts: districts)
}

/// A list of whole numbers from 0 to `max` (season.ts `wholes`); nil for anything else.
private func wholes(_ value: JSONValue?, _ max: Double) -> [Int]? {
    guard let items = value?.items else {
        return nil
    }
    var values: [Int] = []
    for item in items {
        guard let whole = wholeValue(item, 0, max) else {
            return nil
        }
        values.append(whole)
    }
    return values
}

/// Whether a text is a SHA-256 digest: 64 lower-case hexadecimal digits (`DIGEST`, the
/// schemas' `ContentDigest`).
func isDigest(_ text: String) -> Bool {
    let units = Array(text.utf16)
    guard units.count == 64 else {
        return false
    }
    for unit in units {
        let digit = unit >= 0x30 && unit <= 0x39
        let letter = unit >= 0x61 && unit <= 0x66
        if !(digit || letter) {
            return false
        }
    }
    return true
}

/// live/season.json, checked as the pipeline writes it (season.ts `parseSeason`); nil for
/// anything else.
func parseSeason(_ value: JSONValue?) -> SeasonFile? {
    guard let file = value?.fields,
          file["schema_version"] == JSONValue.number(1),
          let season = file["season"]?.text,
          let directory = seasonStamp(file["directory"]) else {
        return nil
    }
    // The school year, `^(\d{4})-(\d{4})$`, its second year the first's next.
    let units = Array(season.utf16)
    guard units.count == 9, element(units, 4) == 0x2D,
          let firstYear = asciiNumber(units, 0..<4),
          let secondYear = asciiNumber(units, 5..<9),
          secondYear == firstYear + 1 else {
        return nil
    }
    guard let first = seasonDayMs(file["since"]),
          let last = seasonDayMs(file["through"]),
          let since = file["since"]?.text,
          let through = file["through"]?.text,
          let start = siteDateUTC(firstYear, 6, 1),
          let end = siteDateUTC(secondYear, 5, 30),
          start <= first, first <= last, last <= end else {
        return nil
    }
    // The digest: null, or a digest; absent is neither.
    let digest: String?
    switch file["content_sha256"] {
    case .some(.null):
        digest = nil
    case .some(.string(let text)) where isDigest(text):
        digest = text
    default:
        return nil
    }
    guard let gaps = wholes(file["gaps"], maxIndex),
          let closed = wholes(file["closed"], maxDays), closed.count == gaps.count,
          let delayed = wholes(file["delayed"], maxDays), delayed.count == gaps.count,
          let remote = wholes(file["remote"], maxDays), remote.count == gaps.count,
          let early = wholes(file["early_dismissal"], maxDays), early.count == gaps.count else {
        return nil
    }
    // Math.round((last - first) / DAY_MS) + 1: both are UTC midnights, so the division is
    // exact.
    let span = Int((last - first) / dayMs) + 1
    var school = -1
    for row in 0..<gaps.count {
        school += (element(gaps, row) ?? 0) + 1
        let sum = (element(closed, row) ?? 0) + (element(delayed, row) ?? 0)
            + (element(remote, row) ?? 0) + (element(early, row) ?? 0)
        if sum < 1 || sum > span {
            return nil
        }
    }
    if school >= directory.schools || (digest == nil && gaps.count > 0) {
        return nil
    }
    return SeasonFile(
        season: season,
        since: since,
        through: through,
        directory: directory,
        contentSha256: digest,
        gaps: gaps,
        closed: closed,
        delayed: delayed,
        remote: remote,
        earlyDismissal: early
    )
}

/// The last day over everywhere at `now` (YYYY-MM-DD): the newest day a file can count
/// (season.ts `lastDayOver`). It throws where the site's does: where its Date is invalid.
func lastDayOver(_ now: Int64) throws -> String {
    guard isSiteTime(now), isSiteTime(now - westBehindMs) else {
        throw SiteRefusal()
    }
    let at = now - westBehindMs
    let civil = civilFromDays(floorDivide(at, dayMs))
    guard let midnight = siteDateUTC(civil.year, civil.month - 1, civil.day),
          let day = isoDay(midnight - dayMs) else {
        throw SiteRefusal()
    }
    return day
}

/// The school's days this school year, from a checked file, or nil when the file is for
/// another directory, emptied or stale at `now`, or does not list the school
/// (season.ts `schoolSeason`). A `now` no JavaScript Date holds is the site's invalid
/// date: nil. It throws where the site's does (an instant at the very edge of what a Date
/// holds, an hour before which is not one).
func schoolSeason(_ file: SeasonFile, school: Int, directory: DirectoryStamp, now: Int64) throws -> SchoolSeason? {
    guard isSiteTime(now) else {
        return nil
    }
    guard file.contentSha256 != nil, sameStamp(file.directory, directory) else {
        return nil
    }
    let lastOver = try lastDayOver(now - seasonGraceMs)
    if file.through < lastOver {
        return nil
    }
    var index = -1
    for row in 0..<file.gaps.count {
        index += (element(file.gaps, row) ?? 0) + 1
        if index > school {
            return nil
        }
        if index == school {
            let days = SeasonDays(
                closed: element(file.closed, row) ?? 0,
                delayed: element(file.delayed, row) ?? 0,
                remote: element(file.remote, row) ?? 0,
                earlyDismissal: element(file.earlyDismissal, row) ?? 0
            )
            let yearStart = String(file.season.prefix(4)) + "-07-01"
            return SchoolSeason(days: days, since: file.since > yearStart ? file.since : nil)
        }
    }
    return nil
}
