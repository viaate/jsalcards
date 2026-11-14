import Foundation

// A published file as the site's JSON.parse hands it to the site's checks, and the small
// checks those use (web/src/data/map-day.ts, closings.ts, season.ts).
//
// Decoded with JSONDecoder, never JSONSerialization: on Apple platforms the latter blurs
// `true` and `1`, and the site's checks keep them apart (`typeof value === 'number'`).

/// One JSON value, kept apart by kind: `true` is never a number and a number is never text.
indirect enum JSONValue: Decodable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    /// A file's bytes as JSON, or nil where they are not JSON (the site's read of such a
    /// file fails and it uses none).
    static func read(_ data: Data) -> JSONValue? {
        return try? JSONDecoder().decode(JSONValue.self, from: data)
    }

    /// The fields of an object; nil for any other kind.
    var fields: [String: JSONValue]? {
        if case .object(let fields) = self {
            return fields
        }
        return nil
    }

    /// The items of a list; nil for any other kind (`Array.isArray`).
    var items: [JSONValue]? {
        if case .array(let items) = self {
            return items
        }
        return nil
    }

    /// The text of a string; nil for any other kind (`typeof value === 'string'`).
    var text: String? {
        if case .string(let text) = self {
            return text
        }
        return nil
    }

    /// The value of a number; nil for any other kind (`typeof value === 'number'`).
    var numeric: Double? {
        if case .number(let value) = self {
            return value
        }
        return nil
    }
}

/// The item at a position of a list, or nil outside it: the site's `list[i]`, which is
/// `undefined` there. Never an unchecked subscript.
func element<Item>(_ list: [Item], _ position: Int) -> Item? {
    guard position >= 0, position < list.count else {
        return nil
    }
    return list[position]
}

/// The largest position or count a file may hold (`MAX_INDEX`).
let maxIndex: Double = 4_294_967_294

/// Whether a number is whole as `Number.isInteger` says: finite and equal to its floor.
func isInteger(_ value: Double) -> Bool {
    return value.isFinite && value == value.rounded(.down)
}

/// A whole number from `min` to `max` (the site's `isWhole`), as an Int; nil for anything
/// else, `true` and text included. Absent (nil) is not a number either.
func wholeValue(_ value: JSONValue?, _ min: Double, _ max: Double) -> Int? {
    guard let number = value?.numeric, isInteger(number), number >= min, number <= max else {
        return nil
    }
    return Int(exactly: number)
}

/// Whether a value is a whole number from `min` to `max`.
func isWhole(_ value: JSONValue?, _ min: Double, _ max: Double) -> Bool {
    return wholeValue(value, min, max) != nil
}

/// A position or count from 0 to `maxIndex` (`isIndex`, map-day.ts), as an Int.
func indexValue(_ value: JSONValue?) -> Int? {
    return wholeValue(value, 0, maxIndex)
}

/// Whether a value is a position or count (`isIndex`, map-day.ts).
func isIndex(_ value: JSONValue?) -> Bool {
    return indexValue(value) != nil
}

/// The names on the app's list that this machine's Foundation also knows, worked out once.
private enum KnownZones {
    static let here: Set<String> = {
        var known: Set<String> = []
        for name in ZoneNames.all where TimeZone(identifier: name) != nil {
            known.insert(name)
        }
        return known
    }()
}

/// Whether a name is a time zone, narrower than the site's on purpose (item 27).
///
/// The site's rule is "a name `Intl` accepts" (map-day.ts `isTimeZone`). Apple's and
/// Linux's Foundation each accept a different set, so the app does not ask them: a name is
/// a time zone only if it is, letter for letter, on the app's list (`ZoneNames.swift`,
/// written from the site's own answers, so never wider than the site), and this machine's
/// Foundation knows it. The special values `"*"` and `"?"` are not zones.
///
/// Letter for letter means UTF-16 unit for unit, as JavaScript compares text: Swift's own
/// `==` calls two texts equal when Unicode deems them the same (the Kelvin sign and the
/// letter K), so a name with any unit outside ASCII is refused before the list is asked.
func isTimeZone(_ name: String) -> Bool {
    return isASCII(name) && ZoneNames.all.contains(name) && KnownZones.here.contains(name)
}

/// Whether every UTF-16 unit of a text is ASCII: there Swift's `==` and JavaScript's `===`
/// agree.
func isASCII(_ text: String) -> Bool {
    for unit in text.utf16 where unit >= 0x80 {
        return false
    }
    return true
}

/// Whether a value is a time zone name: text, then as `isTimeZone(_ name:)` says.
func isTimeZone(_ value: JSONValue?) -> Bool {
    guard let name = value?.text else {
        return false
    }
    return isTimeZone(name)
}

/// Whether a list name is one this machine's Foundation does not know: there the app reads
/// it as unknown, though the site would accept it.
func isListedButUnknownHere(_ name: String) -> Bool {
    return isASCII(name) && ZoneNames.all.contains(name) && !KnownZones.here.contains(name)
}
