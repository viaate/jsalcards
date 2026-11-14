import Foundation

// The day and minute a zone's clock shows at an instant (web/src/data/map-day.ts
// `wallClock`, `localDay`; web/src/copy-format.ts `localDay`), and the instant a day's
// minute strikes on it (map-day.ts `atWall`, web/src/app/chance.ts `atLocalTime`).
//
// A zone is used for one thing only: its offset from UTC at an instant. Only a name the
// app's zone check accepts is asked (`knownZone`); any other name has no clock, and every
// function here gives nil for it, never a crash. The instant and the zone are always
// parameters: nothing here reads the device's clock or zone.

/// What a zone's clock shows at an instant: the calendar day and the minute of it.
struct WallTime: Equatable {
    /// YYYY-MM-DD.
    let day: String
    /// Minutes after midnight, 0 to 1439.
    let minute: Int
}

/// A zone's offset from UTC at an instant, in milliseconds; nil for a name with no clock
/// here, or an instant no JavaScript Date holds.
func zoneOffsetMs(_ zone: String, at instant: Int64) -> Int64? {
    guard isSiteTime(instant), let found = knownZone(zone) else {
        return nil
    }
    let moment = Date(timeIntervalSince1970: Double(instant) / 1000)
    return Int64(found.secondsFromGMT(for: moment)) * 1000
}

/// What a zone's clock shows at an instant; nil for a name with no clock here.
///
/// The site's clock writes the year with four digits (map-day.ts refuses any other), so a
/// local year outside 1000 to 9999 has no clock here either: the app is narrower there,
/// never wider, and no file of this century comes near it.
func wallTime(_ instant: Int64, _ zone: String) -> WallTime? {
    guard let offset = zoneOffsetMs(zone, at: instant) else {
        return nil
    }
    let local = instant + offset
    let days = floorDivide(local, dayMs)
    let civil = civilFromDays(days)
    guard civil.year >= 1000, civil.year <= 9999, let day = isoDay(days * dayMs) else {
        return nil
    }
    let minute = Int((local - days * dayMs) / minuteMs)
    return WallTime(day: day, minute: minute)
}

/// The calendar day a zone's clock shows at an instant (YYYY-MM-DD); nil for a clock not
/// known (map-day.ts `localDay`; copy-format.ts `localDay`, which throws where this is nil).
func localDay(_ instant: Int64, _ zone: String) -> String? {
    return wallTime(instant, zone)?.day
}

/// The instant a calendar day's minute strikes on a zone's clock, as whole milliseconds
/// (map-day.ts `atWall`; app/chance.ts `atLocalTime` with its hour and minute as one
/// minute of the day). The site's three steps: two settle any offset, a third the rare hour
/// a clock change moves. Nil where the site's would throw: a day its Date cannot read, or a
/// clock not known.
func atWall(_ day: String, _ minute: Int64, _ zone: String) -> Int64? {
    guard let midnight = siteDayStart(day) else {
        return nil
    }
    let target = midnight + minute * minuteMs
    var at = target
    for _ in 0..<3 {
        guard let wall = wallTime(at, zone), let wallMidnight = siteDayStart(wall.day) else {
            return nil
        }
        at += target - (wallMidnight + Int64(wall.minute) * minuteMs)
    }
    return at
}
