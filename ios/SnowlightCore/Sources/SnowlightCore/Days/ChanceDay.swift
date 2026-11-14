import Foundation

// The chance's day (PLAN section 4, rule C): the outlook the school panel reads from the
// predictions file (web/src/data/school-day.ts `schoolOutlook`), whether a school day is
// under way (web/src/app/chance.ts `underWay`), and the day the chance is for
// (app/chance.ts `headlineDay`).
//
// The outlook is said only when the file is for the school's directory, at most 90 minutes
// old and stamped at most 15 minutes ahead, has an entry for the school, and holds the
// school's own today. A forecast's bus time is read as the site reads it
// (web/src/data/forecast-detail.ts `forecastDetail`): only when it falls on that day on the
// school's clock. Of the rest of a forecast, nothing is read until M2.

/// When a school day is under way: 7:30 AM on the school's clock, as minutes after midnight
/// (`UNDER_WAY_AT`).
let underWayAtMinute: Int64 = 7 * 60 + 30
/// How old a predictions file may be and still be read (`PREDICTIONS_FRESH_MS`).
let predictionsFreshMs: Int64 = 90 * minuteMs
/// How far ahead of now its stamp may be (`PREDICTIONS_AHEAD_MS`).
let predictionsAheadMs: Int64 = 15 * minuteMs

/// One day of a school's outlook (school-day.ts `DayOutlook`).
enum DayOutlook: Equatable {
    /// `no_threat`.
    case noThreat
    /// A chance of no school, for a day.
    case forecast(ForecastDay)
}

/// A forecast day of an outlook: its chances, its reasons, the day it is for, and its bus
/// time where that falls on the day on the school's clock.
struct ForecastDay: Equatable {
    let noSchool: Double
    let delay: Double
    let reasons: [Int]
    /// YYYY-MM-DD.
    let day: String
    /// When the buses run, as whole milliseconds; nil where the file gives none that day.
    let busesAt: Int64?
}

/// What the panel's chance reads (school-day.ts `Outlook`): today and tomorrow on the
/// school's clock (tomorrow nil where the file stops at today), and that clock.
struct Outlook: Equatable {
    let today: DayOutlook
    let tomorrow: DayOutlook?
    let timeZone: String
    /// When the predictions file was made, as whole milliseconds.
    let generatedAt: Int64
}

/// Whether a school day is under way at `now` (app/chance.ts `underWay`): from 7:30 AM on
/// the school's clock, or once its buses have run where they run before that. A clock that
/// cannot be read says the day is under way: the day is not said.
func underWay(_ day: String, now: Int64, zone: String, buses: Int64?) -> Bool {
    if let run = buses, now >= run {
        return true
    }
    guard let start = atWall(day, underWayAtMinute, zone) else {
        return true
    }
    return now >= start
}

/// The entry an outlook is read from: a district's, or a private school's own
/// (school-day.ts `entryOf`).
private func outlookEntry(district: Int?, school: Int?, _ file: PredictionsFile) -> (timeZone: String, days: [Forecast])? {
    if let wanted = district {
        guard let found = file.districts.first(where: { $0.district == wanted }) else {
            return nil
        }
        return (found.timeZone, found.days)
    }
    guard let wanted = school, let found = schoolEntry(file, school: wanted) else {
        return nil
    }
    var days: [Forecast] = []
    for place in found.days {
        guard let outlook = element(file.outlooks, place) else {
            return nil
        }
        days.append(outlook)
    }
    guard let zone = element(file.zones, found.zone) else {
        return nil
    }
    return (zone, days)
}

/// One day's outlook (school-day.ts `dayOutlook`), with its bus time read as
/// forecast-detail.ts reads it: an instant that falls on `day` on the school's clock.
private func dayOutlook(_ forecast: Forecast, day: String, zone: String) -> DayOutlook {
    switch forecast {
    case .noThreat:
        return .noThreat
    case .forecast(let value):
        var buses: Int64?
        if let at = parseInstant(value.busesAt), localDay(at, zone) == day {
            buses = at
        }
        return .forecast(ForecastDay(noSchool: value.noSchool, delay: value.delay, reasons: value.reasons, day: day, busesAt: buses))
    }
}

/// The outlook the panel shows (school-day.ts `schoolOutlook`): nil when the build ships no
/// predictions, the school has neither a district nor a position, there is no file, the file
/// is for another directory, too old or too far ahead, has no entry for the school, or does
/// not hold the school's own today.
func schoolOutlook(district: Int?, school: Int?, directory: DirectoryStamp, shipped: Bool, predictions: PredictionsFile?, now: Int64) -> Outlook? {
    guard shipped, district != nil || school != nil else {
        return nil
    }
    guard let file = predictions, sameStamp(file.directory, directory) else {
        return nil
    }
    let age = now - file.generatedAtMs
    guard age <= predictionsFreshMs, age >= -predictionsAheadMs else {
        return nil
    }
    guard let entry = outlookEntry(district: district, school: school, file) else {
        return nil
    }
    // The unit's own today: its evening is still today, however late it is in the east.
    guard let today = schoolToday(now, entry.timeZone),
          let at = file.days.firstIndex(of: today),
          let first = element(entry.days, at),
          let firstDay = element(file.days, at) else {
        return nil
    }
    var tomorrow: DayOutlook?
    if let second = element(entry.days, at + 1) {
        let secondDay = element(file.days, at + 1) ?? siteNextDay(firstDay) ?? ""
        tomorrow = dayOutlook(second, day: secondDay, zone: entry.timeZone)
    }
    return Outlook(
        today: dayOutlook(first, day: firstDay, zone: entry.timeZone),
        tomorrow: tomorrow,
        timeZone: entry.timeZone,
        generatedAt: file.generatedAtMs
    )
}

/// The day the chance is for (app/chance.ts `headlineDay`): the first of today and tomorrow,
/// on the school's clock, that is not decided (a status is posted for it), has a forecast,
/// and is not under way; nil for none.
func headlineDay(_ outlook: Outlook?, decidedToday: Bool, decidedTomorrow: Bool, now: Int64) -> ForecastDay? {
    guard let found = outlook else {
        return nil
    }
    let days: [DayOutlook?] = [decidedToday ? nil : found.today, decidedTomorrow ? nil : found.tomorrow]
    for day in days {
        guard case .some(.forecast(let forecast)) = day else {
            continue
        }
        if underWay(forecast.day, now: now, zone: found.timeZone, buses: forecast.busesAt) {
            continue
        }
        return forecast
    }
    return nil
}
