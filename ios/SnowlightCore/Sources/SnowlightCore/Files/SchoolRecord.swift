import Foundation

// A school's record, as the site's school panel reads it: one row of the details shards, at
// its position in the directory (web/src/data/details.ts `recordOf`, the row in
// details-format.ts `DETAIL_COLUMNS` order), plus the two names the site shows for the school
// and its district (server piece S3: the deployed site's own `shownName` and `districtShown`,
// written beside the row; M1 RD-5 (b)). M1 reads it from the picture tour's fixtures; M5 from
// the shards.
//
// recordOf checks nothing: the shard reader (details.ts `isDetailRow`) has checked the row
// before it. Here a row whose entries are not of the kinds recordOf reads gives no record, so
// nothing is shown from it. The names stay text inside SnowlightCore: only Words/ turns them
// into words (Words/SchoolLines.swift `schoolName`, `districtName`).

/// The columns of a details row (`DETAIL_COLUMNS`).
private let detailColumns = 16

/// The kind flags of a row (details-format.ts `KIND_FLAGS`).
private let privateFlag = 0x01
private let charterFlag = 0x02
private let virtualFlag = 0x04
/// The largest flags value a row may hold: all three kinds.
private let allFlags: Double = 7

/// The columns of a nearby school's entry: position, id, name, metres, longitude, latitude.
private let nearbyColumns = 6

/// A school's district: its position in the directory, its id and its name as the row writes
/// it (not the name the site shows: that is `SchoolRecord.districtShown`).
struct RecordDistrict: Equatable {
    let index: Int
    let id: String
    let name: String
}

/// A school's lowest and highest grades, as NCES codes ("PK", "KG", "01" to "13").
struct RecordGrades: Equatable {
    let low: String
    let high: String
}

/// A school next door, as the row lists it (details.ts `nearby`).
struct RecordNearby: Equatable {
    let index: Int
    let id: String
    let name: String
    let metres: Double
    let lon: Double
    let lat: Double
}

/// A school's record (details.ts `SchoolRecord`), with S3's two shown names.
struct SchoolRecord: Equatable {
    let id: String
    /// The school's position in the directory.
    let index: Int
    /// The name as the directory writes it (not the name the site shows: that is `shown`).
    let name: String
    /// `private` in the site's record.
    let isPrivate: Bool
    let charter: Bool
    let virtual: Bool
    /// The school's district, or nil for a school with none (most private schools).
    let district: RecordDistrict?
    let street: String?
    let city: String?
    let state: String
    let zip: String?
    let county: String?
    /// The school's grades, or nil where the row gives neither end or only one.
    let grades: RecordGrades?
    let enrollment: Double?
    let phone: String?
    let nearby: [RecordNearby]
    /// The directory the record's positions point into.
    let directory: DirectoryStamp
    /// The name the site shows for the school (S3), or nil where none was given.
    let shown: String?
    /// The name the site shows for the school's district (S3), or nil.
    let districtShown: String?
}

/// A text or null: the text, or nil for null, wrapped; nil itself for anything else.
private func textOrNull(_ value: JSONValue?) -> String?? {
    guard let found = value else {
        return nil
    }
    if found == JSONValue.null {
        return .some(nil)
    }
    guard let text = found.text else {
        return nil
    }
    return .some(text)
}

/// A number or null: the number, or nil for null, wrapped; nil itself for anything else.
private func numberOrNull(_ value: JSONValue?) -> Double?? {
    guard let found = value else {
        return nil
    }
    if found == JSONValue.null {
        return .some(nil)
    }
    guard let number = found.numeric else {
        return nil
    }
    return .some(number)
}

/// A whole number from 0 to `maxIndex` or null: the number, or nil for null, wrapped; nil
/// itself for anything else.
private func indexOrNull(_ value: JSONValue?) -> Int?? {
    if value == JSONValue.null {
        return .some(nil)
    }
    guard let index = indexValue(value) else {
        return nil
    }
    return .some(index)
}

/// One nearby school's entry, or nil where it is not of the kinds recordOf reads.
private func nearbyOf(_ value: JSONValue) -> RecordNearby? {
    guard let entries = value.items, entries.count == nearbyColumns,
          let index = indexValue(element(entries, 0)),
          let id = element(entries, 1)?.text,
          let name = element(entries, 2)?.text,
          let metres = element(entries, 3)?.numeric,
          let lon = element(entries, 4)?.numeric,
          let lat = element(entries, 5)?.numeric else {
        return nil
    }
    return RecordNearby(index: index, id: id, name: name, metres: metres, lon: lon, lat: lat)
}

/// A details row as a record at its position in the directory (details.ts `recordOf`), with
/// the names S3 gives; nil where the row is not of the kinds recordOf reads.
func recordOf(_ row: JSONValue?, index: Int, directory: DirectoryStamp, shown: String?, districtShown: String?) -> SchoolRecord? {
    guard let entries = row?.items, entries.count == detailColumns,
          let id = element(entries, 0)?.text,
          let name = element(entries, 1)?.text,
          let flags = wholeValue(element(entries, 2), 0, allFlags),
          let district = indexOrNull(element(entries, 3)),
          let districtId = textOrNull(element(entries, 4)),
          let districtName = textOrNull(element(entries, 5)),
          let street = textOrNull(element(entries, 6)),
          let city = textOrNull(element(entries, 7)),
          let state = element(entries, 8)?.text,
          let zip = textOrNull(element(entries, 9)),
          let county = textOrNull(element(entries, 10)),
          let low = textOrNull(element(entries, 11)),
          let high = textOrNull(element(entries, 12)),
          let enrollment = numberOrNull(element(entries, 13)),
          let phone = textOrNull(element(entries, 14)),
          let nearbyEntries = element(entries, 15)?.items else {
        return nil
    }
    var nearby: [RecordNearby] = []
    for entry in nearbyEntries {
        guard let found = nearbyOf(entry) else {
            return nil
        }
        nearby.append(found)
    }
    var inDistrict: RecordDistrict?
    if let position = district, let named = districtId, let written = districtName {
        inDistrict = RecordDistrict(index: position, id: named, name: written)
    }
    var grades: RecordGrades?
    if let lowest = low, let highest = high {
        grades = RecordGrades(low: lowest, high: highest)
    }
    return SchoolRecord(
        id: id,
        index: index,
        name: name,
        isPrivate: (flags & privateFlag) != 0,
        charter: (flags & charterFlag) != 0,
        virtual: (flags & virtualFlag) != 0,
        district: inDistrict,
        street: street,
        city: city,
        state: state,
        zip: zip,
        county: county,
        grades: grades,
        enrollment: enrollment,
        phone: phone,
        nearby: nearby,
        directory: directory,
        shown: shown,
        districtShown: districtShown
    )
}
