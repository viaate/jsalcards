import XCTest
@testable import SnowlightCore

/// `format.chance`, `chanceFormat.chanceNumber` and `chanceFormat.delayInstead` give the
/// site's words for every case of chance.json: 0, the small values about the first percent,
/// every half percent from 1% to 99.5%, 99.9%, 100%, and the values the site refuses
/// (below 0, above 1, NaN and the infinities). Each percent is Math.round of the product
/// the site computes, so "<1%" and ">99%" fall where the site's do.
final class ChanceWordsTests: XCTestCase {
    func testChanceAsTheSite() throws {
        let file = try GoldenFile.family("chance")
        let differences = Differences()
        for value in file.cases {
            // [p, format.chance(p), chanceFormat.chanceNumber(p), chanceFormat.delayInstead(p)]
            guard let entries = value.entries, entries.count == 4, let p = inputNumber(entries[0]) else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let mine: [GoldenValue] = [
                shownAnswer { try SiteFormat.chance(p) },
                shownAnswer { try SiteFormat.chanceNumber(p) },
                shownAnswer { try SiteFormat.delayInstead(p) },
            ]
            if mine != Array(entries[1...]) {
                differences.note("\(entries[0]): the site \(Array(entries[1...])), the app \(mine)")
            }
        }
        differences.report("chance")
    }
}
