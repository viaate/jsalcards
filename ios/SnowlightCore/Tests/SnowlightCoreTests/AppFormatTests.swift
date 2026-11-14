import Foundation
import XCTest
@testable import SnowlightCore

/// The app's own formats for My School (Words/AppFormat.swift, M1 4.2a, as the lead ruled):
/// each held to answers written out here, and the season card held to the site's own season
/// line over every case of season-line.json, so its numbers and its day are always the site's.
final class AppFormatTests: XCTestCase {
    /// The day line for the first day of each month of 2027 and for the tour's two days: all
    /// 12 month names drawn, each after the site's own weekday.
    func testTheDayLineForEveryMonth() throws {
        let written: [(String, String)] = [
            ("2027-01-01", "Friday, January 1"),
            ("2027-02-01", "Monday, February 1"),
            ("2027-03-01", "Monday, March 1"),
            ("2027-04-01", "Thursday, April 1"),
            ("2027-05-01", "Saturday, May 1"),
            ("2027-06-01", "Tuesday, June 1"),
            ("2027-07-01", "Thursday, July 1"),
            ("2027-08-01", "Sunday, August 1"),
            ("2027-09-01", "Wednesday, September 1"),
            ("2027-10-01", "Friday, October 1"),
            ("2027-11-01", "Monday, November 1"),
            ("2027-12-01", "Wednesday, December 1"),
            ("2027-01-12", "Tuesday, January 12"),
            ("2027-01-13", "Wednesday, January 13"),
        ]
        for (day, line) in written {
            XCTAssertEqual(try AppFormat.dayLine(day).drawnString, line, day)
        }
        XCTAssertEqual(AppWords.months.count, 12)
        // A text that is not a calendar day is refused, as the site's weekday refuses it.
        XCTAssertThrowsError(try AppFormat.dayLine("2027-02-30"))
        XCTAssertThrowsError(try AppFormat.dayLine("2027-1-12"))
    }

    /// The district line of a public school, with the site's own grades.
    func testTheDistrictLine() throws {
        let district = ShownText("Synthetic District One")
        let written: [(String, String, String)] = [
            ("06", "08", "Synthetic District One · Grades 6–8"),
            ("KG", "05", "Synthetic District One · Grades K–5"),
            ("PK", "12", "Synthetic District One · Grades PK–12"),
            ("KG", "KG", "Synthetic District One · Grades K"),
        ]
        for (low, high, line) in written {
            let grades = try SiteFormat.grades(low, high)
            XCTAssertEqual(AppFormat.districtLine(district: district, grades: grades).drawnString, line, "\(low) to \(high)")
        }
    }

    /// For every case of season-line.json, as the lead ruled (RD-10): where the draft's form
    /// holds (closed or delayed days, no remote and no early-dismissal day, and a since), its
    /// numbers and its day are the site line's, in the site's order; everywhere else the card
    /// is the site's line cut after its key; where the site throws there is no card.
    func testTheSeasonCardAsTheSitesLine() throws {
        let file = try GoldenFile.family("season-line")
        let differences = Differences()
        var none = 0
        var drawn = 0
        var site = 0
        for value in file.cases {
            // [closed, delayed, remote, earlyDismissal, since, seasonFormat.line(days, since)]
            guard let entries = value.entries, entries.count == 6 else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            var counts: [Int] = []
            for entry in entries[0..<4] {
                if let number = entry.numeric, let whole = Int(exactly: number) {
                    counts.append(whole)
                }
            }
            let since = entries[4].text
            guard counts.count == 4, since != nil || entries[4] == .null else {
                differences.note("a case this test cannot read: \(value)")
                continue
            }
            differences.compared()
            let days = SeasonDays(closed: counts[0], delayed: counts[1], remote: counts[2], earlyDismissal: counts[3])
            let card = SchoolLines.seasonCard(days, since: since)
            guard let line = entries[5].text else {
                none += 1
                if entries[5] != GoldenValue.throwsMark || card != nil {
                    differences.note("\(counts): the site gives no line, the app \(String(describing: card))")
                }
                continue
            }
            let key = "This school year"
            let joiner = since == nil ? ": " : ", "
            guard line.hasPrefix(key + joiner) else {
                differences.note("\(counts): the site's line does not start with its key: \(line)")
                continue
            }
            let draftForm = days.remote == 0 && days.earlyDismissal == 0 && (days.closed > 0 || days.delayed > 0) && since != nil
            switch card {
            case .drawn(let cardKey, let cardCounts, let cardSince)?:
                drawn += 1
                guard draftForm else {
                    differences.note("\(counts) since \(String(describing: since)): the draft's form, outside its case")
                    continue
                }
                // Read the site's own line back: "This school year, since Oct 27: closed 2 days, delayed 1."
                let after = String(line.dropFirst((key + joiner).count))
                let halves = after.components(separatedBy: ": ")
                guard halves.count == 2, halves[0].hasPrefix("since "), halves[1].hasSuffix(".") else {
                    differences.note("\(counts): the site's line does not read back: \(line)")
                    continue
                }
                var parts: [String] = []
                for (index, part) in halves[1].dropLast().components(separatedBy: ", ").enumerated() {
                    // "closed 2 days" or "delayed 1": the word, then the number, and the first's unit.
                    var words = part.components(separatedBy: " ")
                    if index == 0 {
                        words = Array(words.dropLast())
                    }
                    guard words.count == 2 else {
                        differences.note("\(counts): a part of the site's line does not read back: \(part)")
                        continue
                    }
                    parts.append(words[1] + " " + words[0])
                }
                XCTAssertEqual(cardKey.drawnString, key)
                if cardCounts.drawnString != parts.joined(separator: " · ") + " " || cardSince.drawnString != halves[0] {
                    differences.note("\(counts): the site \(line), the app '\(cardCounts.drawnString)' '\(cardSince.drawnString)'")
                }
            case .site(let cardKey, let rest)?:
                site += 1
                if draftForm {
                    differences.note("\(counts) since \(String(describing: since)): the site's form, in the draft's case")
                }
                if cardKey.drawnString != key || cardKey.drawnString + joiner + rest.drawnString != line {
                    differences.note("\(counts): the site \(line), the app '\(cardKey.drawnString)' + '\(rest.drawnString)'")
                }
            case nil:
                differences.note("\(counts): the site has a line, the app no card: \(line)")
            }
        }
        differences.report("season-line, the season card")
        XCTAssertEqual([none, drawn, site], [1, 45, 975], "season-paths-r4.out: 1 with no line, 45 in the draft's form, 975 in the site's")
    }

    /// The app's dot is the site's dot (`DOT`), character for character.
    func testTheDotIsTheSites() {
        XCTAssertEqual(AppWords.dot.drawnString, SiteFormat.dot)
        XCTAssertEqual(Array(AppWords.dot.drawnString.unicodeScalars).map { $0.value }, [0x20, 0xB7, 0x20])
    }

    /// One count above 0 gives one part and no dot, as ruled on SPEC r4; two give both, closed first.
    func testTheSeasonCountsParts() throws {
        XCTAssertEqual(try AppFormat.seasonCounts(SeasonDays(closed: 2, delayed: 0, remote: 0, earlyDismissal: 0)).drawnString, "2 closed ")
        XCTAssertEqual(try AppFormat.seasonCounts(SeasonDays(closed: 0, delayed: 1, remote: 0, earlyDismissal: 0)).drawnString, "1 delayed ")
        XCTAssertEqual(try AppFormat.seasonCounts(SeasonDays(closed: 2, delayed: 1, remote: 0, earlyDismissal: 0)).drawnString, "2 closed · 1 delayed ")
        XCTAssertEqual(try AppFormat.seasonCounts(SeasonDays(closed: 1284, delayed: 0, remote: 0, earlyDismissal: 0)).drawnString, "1,284 closed ")
        XCTAssertThrowsError(try AppFormat.seasonCounts(SeasonDays(closed: 0, delayed: 0, remote: 3, earlyDismissal: 0)))
        XCTAssertThrowsError(try AppFormat.seasonCounts(SeasonDays(closed: -1, delayed: 2, remote: 0, earlyDismissal: 0)))
        XCTAssertEqual(try AppFormat.seasonSince("2026-10-27").drawnString, "since Oct 27")
    }
}
