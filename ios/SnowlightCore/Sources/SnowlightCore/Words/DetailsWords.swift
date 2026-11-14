// The plain details a school's listings state beside its status, in the site's own words
// (web/src/copy-details.ts `detailsFormat.said`): "Buses run snow routes. No breakfast."
// The sentences are the site's (SiteWords.detailSentences); this only says them in order.
//
// Not public: no code outside SnowlightCore can name this table.

enum DetailsWords {
    /// The sentences for a row's detail codes, in code order, each once, with any code the
    /// site has no sentence for left out; nil with none (`said`).
    static func said(_ codes: [Int]) -> ShownText? {
        var found: [String] = []
        for code in Set(codes).sorted() {
            if let sentence = element(SiteWords.detailSentences, code) {
                found.append(sentence.drawnString)
            }
        }
        return found.isEmpty ? nil : ShownText(found.joined(separator: " "))
    }
}
