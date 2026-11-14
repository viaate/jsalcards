import Foundation

// The day the map shows for each school, its MAP DAY (web/src/data/map-day.ts): the one
// rule the site's lights, their counts and the school panel's today all follow, and the
// day the app's big status is about (PLAN section 4, rule A).
//
// A school's map day is its own today, on its own clock, until 3:30 PM there, and its own
// tomorrow from then until midnight there; after midnight that same day is its today, so
// nothing changes at midnight. A school with no zone known keeps the day that is today in
// every contiguous US time zone, and none in the hours between.
//
// A zone is one of: nil (no zone known), `unreadZone` ("*": a predictions file shipped but
// not had, in the contiguous US), `unknownZone` ("?": its clock cannot be told), or a name
// the app's zone check accepts. Both special names live in Files/PredictionsFile.swift, with
// `inContiguous` and `regionOf`.

/// When a school's map day turns to its tomorrow: 3:30 PM on its own clock, as minutes
/// after midnight (`MAP_DAY_TURN`, an owner decision).
let mapDayTurnMinute = 15 * 60 + 30

/// The clocks every school in the contiguous US keeps, east to west (`CONTIGUOUS`).
let contiguousZones = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
]

/// Eastern Daylight Time, the contiguous US clock furthest ahead of UTC.
private let eastOffsetMs: Int64 = -4 * hourMs
/// Pacific Standard Time, the one furthest behind.
private let westOffsetMs: Int64 = -8 * hourMs

/// The states of the contiguous US, and DC, by their postal codes (`CONTIGUOUS_STATES`).
private let contiguousStates: Set<String> = [
    "AL", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA",
    "WA", "WV", "WI", "WY",
]

/// The clock a school's day is told by while the zones cannot be read, by the state its
/// record gives (map-day.ts `unreadZoneOf`): `unreadZone` in the contiguous US, else
/// `unknownZone`. Looked up letter for letter, as the site's set is.
func unreadZoneOf(_ state: String) -> String {
    return isASCII(state) && contiguousStates.contains(state) ? unreadZone : unknownZone
}

/// The calendar day that is today in every contiguous US time zone at `now`, or nil in the
/// hours when the East has reached the next day and the West has not (map-day.ts
/// `todayEverywhere`). Nil also at an instant no JavaScript Date holds.
func todayEverywhere(_ now: Int64) -> String? {
    guard isSiteTime(now),
          let east = isoDay(now + eastOffsetMs),
          let west = isoDay(now + westOffsetMs) else {
        return nil
    }
    return east == west ? east : nil
}

/// A school's map day at `now` (map-day.ts `mapDay`): its today before 3:30 PM on its clock,
/// its tomorrow from then; with no zone (nil), the day that is today everywhere (nil
/// overnight); with `unreadZone`, the day that is today everywhere while it is every
/// contiguous US clock's map day too, and nil otherwise. Nil for `unknownZone`, and for any
/// clock not known.
func mapDay(_ now: Int64, _ zone: String?) -> String? {
    guard let named = zone else {
        return todayEverywhere(now)
    }
    if named == unreadZone {
        guard let today = todayEverywhere(now) else {
            return nil
        }
        for clock in contiguousZones where mapDay(now, clock) != today {
            return nil
        }
        return today
    }
    guard let wall = wallTime(now, named) else {
        return nil
    }
    return wall.minute >= mapDayTurnMinute ? siteNextDay(wall.day) : wall.day
}

/// The next instant after `now` that what the map shows for a school in this zone can
/// change: its next 3:30 PM or midnight; with no zone, the next hour the day that is today
/// everywhere begins or ends (04:00 and 08:00 UTC); with `unreadZone`, the earliest of the
/// contiguous clocks' and of no zone's. Nil where no clock can be read (map-day.ts
/// `nextMapTurn`).
func nextMapTurn(_ now: Int64, _ zone: String?) -> Int64? {
    guard isSiteTime(now) else {
        return nil
    }
    guard let named = zone else {
        let midnight = floorDivide(now, dayMs) * dayMs
        let hours: [Int64] = [4, 8, 28]
        for hour in hours {
            let turn = midnight + hour * hourMs
            if turn > now {
                return turn
            }
        }
        return nil
    }
    if named == unreadZone {
        var zones: [String?] = []
        for clock in contiguousZones {
            zones.append(clock)
        }
        zones.append(nil)
        return nextTurnOf(now, zones)
    }
    guard let wall = wallTime(now, named) else {
        return nil
    }
    let turn: Int64?
    if wall.minute < mapDayTurnMinute {
        turn = atWall(wall.day, Int64(mapDayTurnMinute), named)
    } else if let next = siteNextDay(wall.day) {
        turn = atWall(next, 0, named)
    } else {
        turn = nil
    }
    guard let at = turn else {
        return nil
    }
    // A clock that settles on a minute already gone (a clock change at the turn): a minute on.
    return at > now ? at : now + minuteMs
}

/// The earliest next turn (`nextMapTurn`) of any of these zones; nil where none can be read
/// (map-day.ts `nextTurnOf`).
func nextTurnOf(_ now: Int64, _ zones: [String?]) -> Int64? {
    var first: Int64?
    for zone in zones {
        guard let turn = nextMapTurn(now, zone) else {
            continue
        }
        if let earliest = first, earliest <= turn {
            continue
        }
        first = turn
    }
    return first
}

/// The calendar day that is today on a school's clock (map-day.ts `clockToday`): its
/// zone's; with none, or with `unreadZone`, the day that is today everywhere (nil
/// overnight); nil for `unknownZone` and any clock not known.
func clockToday(_ now: Int64, _ zone: String?) -> String? {
    guard let named = zone, named != unreadZone else {
        return todayEverywhere(now)
    }
    return localDay(now, named)
}
