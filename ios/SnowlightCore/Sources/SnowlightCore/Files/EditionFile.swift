import Foundation

// schools/edition.json: the directory a deploy serves, named by its content
// (schemas/directory-edition.schema.json). The site reads it only to fetch it fresh, so
// there is no site check to follow: it is checked here as its schema states it, and never
// wider. Its stamp is the one every other published file carries.

/// schools/edition.json, checked.
struct DirectoryEdition: Equatable {
    /// `generated_on`, `schools` and `districts`: the directory's stamp.
    let stamp: DirectoryStamp
    /// `content_sha256`: the digest of the directory's meta.json and points.bin.
    let contentSha256: String
}

/// The keys the schema allows (`additionalProperties: false`), every one required.
private let editionKeys: Set<String> = ["schema_version", "generated_on", "schools", "districts", "content_sha256"]

/// Whether a LocalDate-shaped text is a real calendar day (the schema's `format: date`).
private func isRealDay(_ text: String) -> Bool {
    guard let parts = localDateParts(text), parts.month >= 1, parts.month <= 12 else {
        return false
    }
    return parts.day >= 1 && parts.day <= daysInMonth(parts.year, parts.month)
}

/// schools/edition.json, checked against its schema; nil for anything else.
func parseEdition(_ value: JSONValue?) -> DirectoryEdition? {
    guard let file = value?.fields,
          Set(file.keys) == editionKeys,
          file["schema_version"] == JSONValue.number(1),
          let stamp = parseStamp(value),
          isRealDay(stamp.generatedOn),
          let digest = file["content_sha256"]?.text, isDigest(digest) else {
        return nil
    }
    return DirectoryEdition(stamp: stamp, contentSha256: digest)
}
