import Foundation

// The ids a saved school or a shared link carries (web/src/state/ids.ts): an NCES public
// school id (12 digits) or a private school's PPIN (8 capital letters or digits). Checked
// by hand over UTF-16 units, as the site's patterns check them: `\d` is 0 to 9 only and `$`
// is the true end. A well-formed id is not necessarily a school on the map: the directory
// decides that.

/// The longest text worth looking at, in UTF-16 units (`MAX_INPUT`).
private let maxInput = 16

/// Whether a UTF-16 unit is one JavaScript's `trim()` removes: U+0009 to U+000D, U+0020,
/// U+00A0, U+1680, U+2000 to U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF.
/// (Swift's own whitespace set leaves U+FEFF in and takes U+0085 out.)
func isSiteSpace(_ unit: UInt16) -> Bool {
    switch unit {
    case 0x09...0x0D, 0x20, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF:
        return true
    default:
        return false
    }
}

/// A text's UTF-16 units with what JavaScript's `trim()` removes taken off both ends.
func siteTrimmed(_ text: String) -> [UInt16] {
    let units = Array(text.utf16)
    var start = 0
    var end = units.count
    while start < end, let unit = element(units, start), isSiteSpace(unit) {
        start += 1
    }
    while end > start, let unit = element(units, end - 1), isSiteSpace(unit) {
        end -= 1
    }
    return Array(units[start..<end])
}

/// `^\d{12}$` (`PUBLIC_SCHOOL_ID`).
private func isPublicID(_ units: [UInt16]) -> Bool {
    guard units.count == 12 else {
        return false
    }
    for unit in units where !(unit >= 0x30 && unit <= 0x39) {
        return false
    }
    return true
}

/// `^[0-9A-Z]{8}$` (`PRIVATE_SCHOOL_ID`).
private func isPrivateID(_ units: [UInt16]) -> Bool {
    guard units.count == 8 else {
        return false
    }
    for unit in units where !((unit >= 0x30 && unit <= 0x39) || (unit >= 0x41 && unit <= 0x5A)) {
        return false
    }
    return true
}

/// Whether a text is a school id, as it stands (ids.ts `isSchoolId`).
func isSchoolId(_ text: String) -> Bool {
    let units = Array(text.utf16)
    return isPublicID(units) || isPrivateID(units)
}

/// A school id from untrusted text, or nil (ids.ts `parseSchoolId`): surrounding space is
/// dropped and a private school id is upper-cased, since people retype them by hand. The
/// upper-casing is the Unicode one, as JavaScript's `toUpperCase()` is ("ß" becomes "SS").
func parseSchoolId(_ raw: String?) -> String? {
    guard let given = raw else {
        return nil
    }
    let trimmed = siteTrimmed(given)
    guard trimmed.count > 0, trimmed.count <= maxInput else {
        return nil
    }
    let text = String(decoding: trimmed, as: UTF16.self)
    if isPublicID(trimmed) {
        return text
    }
    let upper = text.uppercased()
    return isPrivateID(Array(upper.utf16)) ? upper : nil
}
