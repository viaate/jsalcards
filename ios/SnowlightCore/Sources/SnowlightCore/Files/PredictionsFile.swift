import Foundation

// predictions/latest.json, read as the site reads it: the file's check and its private
// schools' section (web/src/data/map-day.ts `parsePredictions`, `parseSchools`), the zones
// it gives each school (`zonesOf`, `zonesFor`, `zoneOf`, `schoolZone`, `regionOf`), and a
// private school's entry (web/src/data/school-day.ts `schoolEntry`).
//
// Of a forecast, M0 reads its state, `p_no_school`, `p_delay` and `reasons` (checked as
// the site checks them) and keeps `buses_at` as the file holds it, to be read with the
// day rules. Every other part is kept as the raw value and not read until M2.

/// How many reason codes a forecast may name (`REASON_COUNT`).
private let reasonCount: Double = 8

/// The zone of a school whose zone cannot be read, in the contiguous US (`UNREAD_ZONE`).
let unreadZone = "*"
/// The zone of a school whose clock cannot be told at all (`UNKNOWN_ZONE`).
let unknownZone = "?"

/// One day's forecast for a district or a private school, checked.
enum Forecast: Equatable {
    /// `no_threat`: nothing to forecast. The value is kept as the file holds it.
    case noThreat(raw: JSONValue)
    /// `forecast`: a chance of no school.
    case forecast(DayForecast)
}

/// A day with a chance (a forecast whose state is `forecast`).
struct DayForecast: Equatable {
    /// `p_no_school`: 0.01 to 0.99.
    let noSchool: Double
    /// `p_delay`: 0 to 1.
    let delay: Double
    /// `reasons`: each 0 to 7.
    let reasons: [Int]
    /// `buses_at`, unread (absent: nil).
    let busesAt: JSONValue?
    /// The whole day as the file holds it.
    let raw: JSONValue
}

/// A district's entry.
struct DistrictForecast: Equatable {
    let district: Int
    let timeZone: String
    /// One forecast for each of the file's days.
    let days: [Forecast]
    /// The whole entry as the file holds it.
    let raw: JSONValue
}

/// A private school's entry (school-day.ts `SchoolForecast`).
struct SchoolForecast: Equatable {
    let school: Int
    /// Its time zone, as its place in the file's `zones`.
    let zone: Int
    /// Its outlook for each of the file's days, as a place in the file's `outlooks`.
    let days: [Int]
}

/// predictions/latest.json, checked.
struct PredictionsFile: Equatable {
    let generatedAt: String
    /// `generated_at` as whole milliseconds.
    let generatedAtMs: Int64
    let directory: DirectoryStamp
    /// Consecutive days, today first.
    let days: [String]
    let districts: [DistrictForecast]
    /// The private schools, sorted by position; empty in a file without them.
    let schools: [SchoolForecast]
    let outlooks: [Forecast]
    let zones: [String]
    /// The whole file as it was read.
    let raw: JSONValue
}

/// A probability: finite, 0 to 1 (`isProbability`).
private func probability(_ value: JSONValue?) -> Double? {
    guard let number = value?.numeric, number.isFinite, number >= 0, number <= 1 else {
        return nil
    }
    return number
}

/// One day's forecast, checked as map-day.ts `parseForecast` checks it; nil for anything
/// else. Every forecast carries its reasons list, even empty.
private func parseForecast(_ value: JSONValue) -> Forecast? {
    guard let day = value.fields else {
        return nil
    }
    switch day["state"] {
    case .some(.string("no_threat")):
        return .noThreat(raw: value)
    case .some(.string("forecast")):
        // A chance of no school is never a certainty: 0.01 to 0.99, so its sum always shows.
        guard let noSchool = probability(day["p_no_school"]), noSchool >= 0.01, noSchool <= 0.99,
              let delay = probability(day["p_delay"]),
              let reasons = day["reasons"]?.items else {
            return nil
        }
        var codes: [Int] = []
        for reason in reasons {
            guard let number = reason.numeric, isInteger(number), number >= 0, number < reasonCount,
                  let code = Int(exactly: number) else {
                return nil
            }
            codes.append(code)
        }
        return .forecast(DayForecast(noSchool: noSchool, delay: delay, reasons: codes, busesAt: day["buses_at"], raw: value))
    default:
        return nil
    }
}

/// A list that may be absent or null, where the site reads `file.key ?? []`: its items, an
/// empty list for absent or null, nil for anything else (refused).
private func listOrNone(_ value: JSONValue?) -> [JSONValue]? {
    switch value {
    case .none, .some(.null):
        return []
    case .some(.array(let items)):
        return items
    default:
        return nil
    }
}

/// predictions/latest.json, checked as map-day.ts `parsePredictions` checks it; nil for
/// anything else. A zone name is checked with the app's own `isTimeZone`, which is
/// narrower than the site's: a file the site reads with a zone the app does not know is
/// refused here.
func parsePredictions(_ value: JSONValue?) -> PredictionsFile? {
    guard let whole = value, let file = whole.fields,
          file["schema_version"] == JSONValue.number(1),
          let generatedAt = file["generated_at"]?.text,
          let generatedAtMs = parseInstant(generatedAt),
          let directory = parseStamp(file["directory"]),
          let dayValues = file["days"]?.items, dayValues.count > 0,
          let districtValues = file["districts"]?.items else {
        return nil
    }
    var days: [String] = []
    var previous = ""
    for value in dayValues {
        // Consecutive days, today first.
        guard let day = value.text, isLocalDateText(day) else {
            return nil
        }
        if previous != "" {
            guard let next = siteNextDay(previous), day == next else {
                return nil
            }
        }
        previous = day
        days.append(day)
    }
    var districts: [DistrictForecast] = []
    for entry in districtValues {
        guard let fields = entry.fields,
              let district = indexValue(fields["district"]),
              let forecastValues = fields["days"]?.items, forecastValues.count == days.count,
              isTimeZone(fields["time_zone"]),
              let zone = fields["time_zone"]?.text else {
            return nil
        }
        var forecasts: [Forecast] = []
        for forecastValue in forecastValues {
            guard let forecast = parseForecast(forecastValue) else {
                return nil
            }
            forecasts.append(forecast)
        }
        districts.append(DistrictForecast(district: district, timeZone: zone, days: forecasts, raw: entry))
    }
    guard let section = parseSchools(file, days.count) else {
        return nil
    }
    return PredictionsFile(
        generatedAt: generatedAt,
        generatedAtMs: generatedAtMs,
        directory: directory,
        days: days,
        districts: districts,
        schools: section.schools,
        outlooks: section.outlooks,
        zones: section.zones,
        raw: whole
    )
}

/// The private schools' section (contract C3), checked as map-day.ts `parseSchools` checks
/// it: each school once, sorted, with its time zone named by its place in the file's zones
/// (each one a zone) and one outlook a day named by its place in the file's outlooks, each
/// of which reads. A file without one has no private school's outlook.
private func parseSchools(_ file: [String: JSONValue], _ dayCount: Int) -> (schools: [SchoolForecast], outlooks: [Forecast], zones: [String])? {
    guard let schoolValues = listOrNone(file["schools"]),
          let outlookValues = listOrNone(file["outlooks"]),
          let zoneValues = listOrNone(file["zones"]) else {
        return nil
    }
    var outlooks: [Forecast] = []
    for value in outlookValues {
        guard let outlook = parseForecast(value) else {
            return nil
        }
        outlooks.append(outlook)
    }
    var zones: [String] = []
    for value in zoneValues {
        guard isTimeZone(value), let zone = value.text else {
            return nil
        }
        zones.append(zone)
    }
    var schools: [SchoolForecast] = []
    var previous = -1
    for entry in schoolValues {
        guard let fields = entry.fields,
              let school = indexValue(fields["school"]), school > previous else {
            return nil
        }
        previous = school
        guard let zone = indexValue(fields["zone"]), zone < zones.count,
              let named = fields["days"]?.items, named.count == dayCount else {
            return nil
        }
        var places: [Int] = []
        for index in named {
            guard let place = indexValue(index), place < outlooks.count else {
                return nil
            }
            places.append(place)
        }
        schools.append(SchoolForecast(school: school, zone: zone, days: places))
    }
    return (schools, outlooks, zones)
}

/// Each school's time zone, as a predictions file gives it: its district's, or a private
/// school's own (map-day.ts `MapZones`).
struct MapZones: Equatable {
    /// The directory the file was written against: a school is its position there alone.
    let directory: DirectoryStamp
    /// The file's generated_at, to tell a newer file.
    let generatedAt: String
    /// The zones the file names, each once, in the order first named.
    let names: [String]
    /// Each district's zone, as its place in `names`, by district position.
    let district: [Int: Int]
    /// Each private school's zone, as its place in `names`, by school position.
    let school: [Int: Int]
}

/// The zones a checked predictions file gives (map-day.ts `zonesOf`).
func zonesOf(_ predictions: PredictionsFile) -> MapZones {
    var names: [String] = []
    var places: [String: Int] = [:]
    func placeOf(_ zone: String) -> Int {
        if let place = places[zone] {
            return place
        }
        let place = names.count
        names.append(zone)
        places[zone] = place
        return place
    }
    var district: [Int: Int] = [:]
    for entry in predictions.districts {
        district[entry.district] = placeOf(entry.timeZone)
    }
    var school: [Int: Int] = [:]
    for entry in predictions.schools {
        if let zone = element(predictions.zones, entry.zone) {
            school[entry.school] = placeOf(zone)
        }
    }
    return MapZones(directory: predictions.directory, generatedAt: predictions.generatedAt, names: names, district: district, school: school)
}

/// Whether the zones were read against this directory (map-day.ts `zonesFor`).
func zonesFor(_ zones: MapZones, _ directory: DirectoryStamp) -> Bool {
    return sameStamp(zones.directory, directory)
}

/// A school's time zone: its district's (`district`, its position, or -1 for none), else
/// its own entry's; nil where the file gives it none (map-day.ts `zoneOf`).
func zoneOf(_ zones: MapZones, school: Int, district: Int) -> String? {
    let place = district >= 0 ? zones.district[district] : zones.school[school]
    guard let found = place else {
        return nil
    }
    return element(zones.names, found)
}

/// The zones a school's day is told by (map-day.ts `ToldZones`).
enum ToldZones: Equatable {
    /// A build that ships no predictions file: every school by the day that is today
    /// everywhere (the site's null).
    case noFile
    /// None for the school's directory can be had yet (the site's undefined).
    case unread
    /// A file's zones, read against the school's directory.
    case zones(MapZones)
}

/// Whether a place is in the contiguous US, by a box about it (map-day.ts `inContiguous`).
func inContiguous(lon: Double, lat: Double) -> Bool {
    return lat >= 24.3 && lat <= 49.5 && lon >= -125 && lon <= -66.8
}

/// The clock a school's day is told by (map-day.ts `schoolZone`): its zone from the file
/// (nil where the file gives none, or with no file shipped), or while none can be had,
/// `unreadZone` in the contiguous US and `unknownZone` outside it.
func schoolZone(_ told: ToldZones, school: Int, district: Int, lon: Double, lat: Double) -> String? {
    switch told {
    case .noFile:
        return nil
    case .unread:
        return inContiguous(lon: lon, lat: lat) ? unreadZone : unknownZone
    case .zones(let zones):
        return zoneOf(zones, school: school, district: district)
    }
}

/// Where in the country a time zone keeps its clock (copy-format.ts `RegionKey`).
enum ZoneRegion: String, Equatable {
    case eastern
    case central
    case mountain
    case arizona
    case pacific
    case alaska
    case hawaii
    case other
}

/// The site's region table (map-day.ts `REGIONS`).
private let regions: [String: ZoneRegion] = [
    "America/New_York": .eastern,
    "America/Detroit": .eastern,
    "America/Indiana/Indianapolis": .eastern,
    "America/Indiana/Marengo": .eastern,
    "America/Indiana/Petersburg": .eastern,
    "America/Indiana/Vevay": .eastern,
    "America/Indiana/Vincennes": .eastern,
    "America/Indiana/Winamac": .eastern,
    "America/Kentucky/Louisville": .eastern,
    "America/Kentucky/Monticello": .eastern,
    "America/Chicago": .central,
    "America/Indiana/Knox": .central,
    "America/Indiana/Tell_City": .central,
    "America/Menominee": .central,
    "America/North_Dakota/Beulah": .central,
    "America/North_Dakota/Center": .central,
    "America/North_Dakota/New_Salem": .central,
    "America/Denver": .mountain,
    "America/Boise": .mountain,
    "America/Phoenix": .arizona,
    "America/Los_Angeles": .pacific,
    "America/Anchorage": .alaska,
    "America/Juneau": .alaska,
    "America/Metlakatla": .alaska,
    "America/Nome": .alaska,
    "America/Sitka": .alaska,
    "America/Yakutat": .alaska,
    "Pacific/Honolulu": .hawaii,
]

/// Where in the country a time zone keeps its clock, for the key's day line; `.other` for
/// none (map-day.ts `regionOf`). Looked up letter for letter, as the site's table is.
func regionOf(_ zone: String?) -> ZoneRegion {
    guard let name = zone, isASCII(name), let region = regions[name] else {
        return .other
    }
    return region
}

/// A private school's entry in the file, by binary search, the schools being sorted
/// (school-day.ts `schoolEntry`).
func schoolEntry(_ predictions: PredictionsFile, school: Int) -> SchoolForecast? {
    var low = 0
    var high = predictions.schools.count
    while low < high {
        let middle = (low + high) / 2
        guard let found = element(predictions.schools, middle) else {
            return nil
        }
        if found.school < school {
            low = middle + 1
        } else if found.school > school {
            high = middle
        } else {
            return found
        }
    }
    return nil
}
