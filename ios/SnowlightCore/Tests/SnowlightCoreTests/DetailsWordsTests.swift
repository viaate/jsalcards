import XCTest
@testable import SnowlightCore

/// `detailsFormat.said` gives the site's sentences for every case of details.json: each code
/// alone, every pair, every run of three, fifty larger sets in any order and with repeats,
/// the empty set (nothing said) and sets holding codes the site has no sentence for (left
/// out). And each of the app's 22 sentences is the site's, by its code.
final class DetailsWordsTests: XCTestCase {
    func testSaidAsTheSite() throws {
        let file = try GoldenFile.family("details")
        let differences = Differences()
        for value in file.cases {
            // [codes, detailsFormat.said(codes)]
            guard let entries = value.entries, entries.count == 2, let list = entries[0].entries else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            var codes: [Int] = []
            for code in list {
                if let number = code.numeric, let whole = Int(exactly: number) {
                    codes.append(whole)
                }
            }
            guard codes.count == list.count else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine = shownAnswer { DetailsWords.said(codes) }
            if mine != entries[1] {
                differences.note("\(codes): the site \(entries[1]), the app \(mine)")
            }
        }
        differences.report("details")
    }

    func testEachSentenceIsTheSitesByItsCode() throws {
        // The site's sentence for code i is its answer for the set [i] alone.
        let file = try GoldenFile.family("details")
        var bySingle: [Int: GoldenValue] = [:]
        for value in file.cases {
            if let entries = value.entries, entries.count == 2, let list = entries[0].entries, list.count == 1,
               let number = list[0].numeric, let code = Int(exactly: number) {
                bySingle[code] = entries[1]
            }
        }
        XCTAssertEqual(SiteWords.detailSentences.count, 22)
        for (code, sentence) in SiteWords.detailSentences.enumerated() {
            XCTAssertEqual(GoldenValue.string(sentence.drawnString), bySingle[code], "the sentence for detail code \(code).")
        }
        // And the same 22 sentences are the whole of the site's table.
        let copy = try GoldenFile.family("copy")
        let first = try XCTUnwrap(copy.cases.first)
        guard case .some(.object(let said)) = first.at(["detailsCopy", "said"]) else {
            XCTFail("copy.json holds no detailsCopy.said.")
            return
        }
        let theirs = Set(said.values.compactMap { $0.text })
        let mine = Set(SiteWords.detailSentences.map { $0.drawnString })
        XCTAssertEqual(mine, theirs)
    }
}
