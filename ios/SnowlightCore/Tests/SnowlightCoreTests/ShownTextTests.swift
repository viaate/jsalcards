import XCTest
@testable import SnowlightCore

/// `shownTexts(in:)` finds every `ShownText` in a model, through optionals, arrays and
/// nested values, in declaration order. Written cases: the models here are made up for
/// the test and hold made-up words.
final class ShownTextTests: XCTestCase {
    /// Three fields whose names are not in alphabetical order, so an order by name
    /// would differ from the declaration order.
    private struct Three {
        let zebra: ShownText
        let apple: ShownText
        let mango: ShownText
    }

    private struct Row {
        let label: ShownText
        let note: ShownText?
    }

    private enum Slot {
        case absent
        case one(ShownText)
        case two(ShownText, ShownText)
        case named(first: ShownText, second: ShownText)
        case row(Row)
    }

    private struct Screen {
        let title: ShownText
        let count: Int
        let plain: String
        let present: ShownText?
        let missing: ShownText?
        let rows: [Row]
        let noRows: [Row]
        let slot: Slot
        let emptySlot: Slot
        let last: ShownText
    }

    private func words(in model: Any) -> [String] {
        shownTexts(in: model).map { $0.drawnString }
    }

    func testATextIsItsOwnWord() {
        XCTAssertEqual(words(in: ShownText("alone")), ["alone"])
        XCTAssertEqual(shownTexts(in: ShownText("alone")), [ShownText("alone")])
    }

    func testFieldsComeInDeclarationOrder() {
        let model = Three(zebra: ShownText("first"), apple: ShownText("second"), mango: ShownText("third"))
        XCTAssertEqual(words(in: model), ["first", "second", "third"])
    }

    func testAPresentOptionalIsFoundAndAnAbsentOneGivesNothing() {
        XCTAssertEqual(words(in: Row(label: ShownText("label"), note: ShownText("note"))), ["label", "note"])
        XCTAssertEqual(words(in: Row(label: ShownText("label"), note: nil)), ["label"])

        let present: ShownText? = ShownText("here")
        let absent: ShownText? = nil
        XCTAssertEqual(words(in: present as Any), ["here"])
        XCTAssertEqual(words(in: absent as Any), [])
    }

    func testArraysAreWalkedInOrder() {
        XCTAssertEqual(words(in: [ShownText("a"), ShownText("b"), ShownText("c")]), ["a", "b", "c"])
        let rows = [
            Row(label: ShownText("one"), note: nil),
            Row(label: ShownText("two"), note: ShownText("two's note")),
            Row(label: ShownText("three"), note: nil),
        ]
        XCTAssertEqual(words(in: rows), ["one", "two", "two's note", "three"])
        XCTAssertEqual(words(in: [Row]()), [])
    }

    func testEnumPayloadsAreWalked() {
        XCTAssertEqual(words(in: Slot.absent), [])
        XCTAssertEqual(words(in: Slot.one(ShownText("only"))), ["only"])
        XCTAssertEqual(words(in: Slot.two(ShownText("left"), ShownText("right"))), ["left", "right"])
        XCTAssertEqual(words(in: Slot.named(first: ShownText("early"), second: ShownText("late"))), ["early", "late"])
        XCTAssertEqual(words(in: Slot.row(Row(label: ShownText("label"), note: ShownText("note")))), ["label", "note"])
    }

    func testTuplesAreWalkedInOrder() {
        XCTAssertEqual(words(in: (ShownText("a"), 3, ShownText("b"))), ["a", "b"])
    }

    func testAWholeScreenInDeclarationOrder() {
        let screen = Screen(
            title: ShownText("title"),
            count: 3,
            plain: "never shown",
            present: ShownText("present"),
            missing: nil,
            rows: [
                Row(label: ShownText("row 1"), note: ShownText("note 1")),
                Row(label: ShownText("row 2"), note: nil),
            ],
            noRows: [],
            slot: .two(ShownText("slot left"), ShownText("slot right")),
            emptySlot: .absent,
            last: ShownText("last")
        )
        XCTAssertEqual(
            words(in: screen),
            ["title", "present", "row 1", "note 1", "row 2", "slot left", "slot right", "last"]
        )
    }

    func testWhatIsNotAShownTextIsNeverReported() {
        XCTAssertEqual(words(in: "a plain string"), [])
        XCTAssertEqual(words(in: 7), [])
        XCTAssertEqual(words(in: true), [])
        XCTAssertEqual(words(in: ["two", "plain strings"]), [])
        let plain: String? = "an optional plain string"
        XCTAssertEqual(words(in: plain as Any), [])
    }
}
