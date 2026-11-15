// The on-screen words of My School, read (M1 6.3; PLAN 5 lock 4).
//
// The picture tour (tools/tour.sh) compares the words the screen's MODEL offers with
// tools/tour-words/<picture>.txt; it never reads the screen. This test reads the screen:
// for each of the six iPhone pictures of My School (closed, closed with details and
// closed for tomorrow, light and dark) it starts the app with that picture's launch
// arguments, in that picture's look, and reads the label and the value of every element
// the app shows, as VoiceOver and the system's other readers are given them. Every one it
// reads is printed, one line each, starting "ui-read".
//
// What it holds them to, all from its own bundle, by path (tools/tour-words is one folder
// reference in the test bundle, ios/project.yml):
//
// - tour-words/ui/<picture>.txt, the grouping file: one line per accessibility element,
//   its model words in order, separated by a tab. A label passes when it equals its line's
//   words joined by the system's joiner. Each part is one model word, or two model words
//   drawn as one text (the season card's counts and since). So a label is never split,
//   and a model word that holds a comma ("Tuesday, January 12") is never cut.
// - tour-words/<picture>.txt, the model's words, which the tour compares.
// - tour-words/system/myschool.txt, the words iOS itself draws on this screen: lines that
//   start with # are notes; a line `joiner<TAB>"<joiner>"` gives the joiner the system put
//   between the words of one element, quoted so its spaces show; every other line is one
//   word the system draws there itself, which may be read as a label or a value.
//
// Until that file names the joiner (M1 step 9b writes it from this test's printed lines),
// the joiner is read off the screen: on each grouped line's element, what stands between
// its first two words, and it must be the same on every one, and is printed. A run then
// fails on the model's words only: a line not read, or read more than once; a label or
// value that holds a model word but is no line (a word read alone or out of its group);
// two joiners; an asset's name read. A label that holds no model word is printed only.
// Once the file names the joiner (the strict check), that joiner is used, and every label
// and value read must also be a line or a listed word of the system.
//
// The hero's word ("Closed") is never read: VoiceOver reads the site's own line, the
// model's spoken "Closed today", in its place (M1 6.1). The application's own element, the
// root of what is read, is left out: its label is the app's name from its settings file.
//
// What one element is: the system's tree of the screen still holds, under an element made
// of its children's words (`.accessibilityElement(children: .combine)`, M1 6.1), each child
// text as it was (iOS app run 43696054459: under "Synthetic Middle School B, Closed" the two
// texts "Synthetic Middle School B" and "Closed"). VoiceOver reads such an element once and
// never its children, so nothing under a text or a button that has a label is read again.
// Every line printed gives the element's depth in the tree.

import XCTest

final class MySchoolTextTests: XCTestCase {
    @MainActor
    func testLightMySchoolClosed() throws {
        try readScreen(picture: "light-myschool-closed", fixture: "tour-closed", look: XCUIDevice.Appearance.light)
    }

    @MainActor
    func testDarkMySchoolClosed() throws {
        try readScreen(picture: "dark-myschool-closed", fixture: "tour-closed", look: XCUIDevice.Appearance.dark)
    }

    @MainActor
    func testLightMySchoolDetails() throws {
        try readScreen(picture: "light-myschool-details", fixture: "tour-details", look: XCUIDevice.Appearance.light)
    }

    @MainActor
    func testDarkMySchoolDetails() throws {
        try readScreen(picture: "dark-myschool-details", fixture: "tour-details", look: XCUIDevice.Appearance.dark)
    }

    @MainActor
    func testLightMySchoolTomorrow() throws {
        try readScreen(picture: "light-myschool-tomorrow", fixture: "tour-tomorrow", look: XCUIDevice.Appearance.light)
    }

    @MainActor
    func testDarkMySchoolTomorrow() throws {
        try readScreen(picture: "dark-myschool-tomorrow", fixture: "tour-tomorrow", look: XCUIDevice.Appearance.dark)
    }
}

/// One element read off the screen.
private struct Read {
    let label: String
    let value: String
    let type: UInt
    let depth: Int
}

/// The words iOS itself draws on the screen, and the joiner once it is recorded.
private struct SystemWords {
    let joiner: String?
    let words: [String]
}

extension MySchoolTextTests {
    /// The joiner M1 6.3 expects, said in a failure when none could be read off the screen.
    private static let expectedJoiner = ", "
    /// How many times the screen is read before the test gives up on a line: once a second.
    private static let tries = 60
    /// The start of every asset name of the app's glyph catalog (Shell/Names.swift).
    private static let assetName = "glyph."

    /// Starts the app as the tour does for the picture, reads the screen and holds what it
    /// reads to the picture's files.
    @MainActor
    private func readScreen(picture: String, fixture: String, look: XCUIDevice.Appearance) throws {
        let groups = try lines(of: picture, in: "tour-words/ui").map { line in
            line.components(separatedBy: "\t")
        }
        let modelWords = try lines(of: picture, in: "tour-words")
            .map { word in word.trimmingCharacters(in: CharacterSet.whitespaces) }
            .filter { word in !word.isEmpty }
        let system = try systemWords()
        XCTAssertFalse(groups.isEmpty, "\(picture): the grouping file has no line")

        XCUIDevice.shared.appearance = look
        let app = XCUIApplication()
        app.launchArguments = ["-tour.screen", "myschool", "-tour.name", picture, "-tour.fixture", fixture]
        app.launch()

        var reads: [Read] = []
        var joiner = system.joiner
        for attempt in 1...MySchoolTextTests.tries {
            reads = try readAll(app)
            if system.joiner == nil {
                joiner = readJoiner(groups, in: reads, picture: picture, settled: false)
            }
            let all = groups.allSatisfy { parts in
                reads.contains { read in read.label == parts.joined(separator: joiner ?? MySchoolTextTests.expectedJoiner) }
            }
            if all || attempt == MySchoolTextTests.tries {
                break
            }
            Thread.sleep(forTimeInterval: 1)
        }
        app.terminate()

        for read in reads {
            print("ui-read\t\(picture)\tdepth \(read.depth)\ttype \(read.type)\tlabel \(quoted(read.label))\tvalue \(quoted(read.value))")
        }
        if system.joiner == nil {
            joiner = readJoiner(groups, in: reads, picture: picture, settled: true)
        }
        let used = joiner ?? MySchoolTextTests.expectedJoiner
        print("ui-read\t\(picture)\tjoiner \(quoted(used))\t\(system.joiner == nil ? "read off the screen" : "from tour-words/system/myschool.txt")")
        let strict = system.joiner != nil

        let expected = groups.map { parts in parts.joined(separator: used) }
        for line in expected {
            let times = reads.filter { read in read.label == line }.count
            if times != 1 {
                XCTFail("\(picture): the line \(quoted(line)) was read \(times) times, not once")
            }
        }
        for read in reads {
            for said in [read.label, read.value] where !said.isEmpty {
                if said.hasPrefix(MySchoolTextTests.assetName) {
                    XCTFail("\(picture): an asset's name was read: \(quoted(said))")
                }
                if expected.contains(said) && said == read.label {
                    continue
                }
                if system.words.contains(said) {
                    continue
                }
                if let word = modelWords.first(where: { word in said.contains(word) }) {
                    XCTFail("\(picture): \(quoted(said)) holds the model's word \(quoted(word)) but is no line of tour-words/ui/\(picture).txt")
                } else if strict {
                    XCTFail("\(picture): \(quoted(said)) is neither a line nor a word of tour-words/system/myschool.txt")
                } else {
                    print("ui-read\t\(picture)\tnot a model word, not checked until the system's words are listed: \(quoted(said))")
                }
            }
        }
    }

    /// The joiner read off the screen: on the element of each line of more than one word,
    /// what stands between its first two words, when the label is those words so joined.
    /// Nil when no such element was read. On the settled reading two different joiners fail.
    @MainActor
    private func readJoiner(_ groups: [[String]], in reads: [Read], picture: String, settled: Bool) -> String? {
        var found: [String] = []
        for parts in groups where parts.count > 1 {
            for read in reads where read.label.hasPrefix(parts[0]) {
                let rest = read.label.dropFirst(parts[0].count)
                guard let next = rest.range(of: parts[1]) else {
                    continue
                }
                let joiner = String(rest[rest.startIndex..<next.lowerBound])
                if !joiner.isEmpty && parts.joined(separator: joiner) == read.label && !found.contains(joiner) {
                    found.append(joiner)
                }
            }
        }
        if settled && found.count > 1 {
            XCTFail("\(picture): the system joined the words of its elements in more than one way: \(found.map(quoted).joined(separator: " and "))")
        }
        return found.first
    }

    /// Every element of the app with a label or a value, the application's own left out.
    @MainActor
    private func readAll(_ app: XCUIApplication) throws -> [Read] {
        var reads: [Read] = []
        let root = try app.snapshot()
        for child in root.children {
            collect(child, depth: 1, into: &reads)
        }
        return reads
    }

    /// One element and, unless it is a text or a button with a label (one element as
    /// VoiceOver reads it, its children's words already in its label), what lies under it.
    @MainActor
    private func collect(_ node: any XCUIElementSnapshot, depth: Int, into reads: inout [Read]) {
        let value: String
        if let text = node.value as? String {
            value = text
        } else if let other = node.value {
            value = String(describing: other)
        } else {
            value = ""
        }
        if !node.label.isEmpty || !value.isEmpty {
            reads.append(Read(label: node.label, value: value, type: node.elementType.rawValue, depth: depth))
        }
        let whole = node.elementType == XCUIElement.ElementType.staticText || node.elementType == XCUIElement.ElementType.button
        if whole && !node.label.isEmpty {
            return
        }
        for child in node.children {
            collect(child, depth: depth + 1, into: &reads)
        }
    }

    /// The words iOS itself draws on My School: tour-words/system/myschool.txt.
    private func systemWords() throws -> SystemWords {
        var joiner: String?
        var words: [String] = []
        for line in try lines(of: "myschool", in: "tour-words/system") where !line.hasPrefix("#") {
            let key = "joiner\t\""
            if line.hasPrefix(key) && line.hasSuffix("\"") && line.count > key.count {
                joiner = String(line.dropFirst(key.count).dropLast())
            } else {
                words.append(line)
            }
        }
        return SystemWords(joiner: joiner, words: words)
    }

    /// The lines of a .txt file of the test bundle, by its path there; none that is empty.
    private func lines(of name: String, in folder: String) throws -> [String] {
        let bundle = Bundle(for: MySchoolTextTests.self)
        guard let url = bundle.url(forResource: name, withExtension: "txt", subdirectory: folder) else {
            XCTFail("there is no \(folder)/\(name).txt in the test bundle")
            return []
        }
        return try String(contentsOf: url, encoding: String.Encoding.utf8)
            .components(separatedBy: "\n")
            .filter { line in !line.isEmpty }
    }
}

/// A text in quotes, so its spaces show.
private func quoted(_ text: String) -> String {
    "\"" + text + "\""
}
