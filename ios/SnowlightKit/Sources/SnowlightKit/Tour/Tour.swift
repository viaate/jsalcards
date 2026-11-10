// The picture tour. Debug builds only: nothing in this folder exists in a release build.
//
// A script outside the app (ios/tools/tour.sh) starts the app once per picture with two
// launch arguments, which arrive in the app's defaults:
//
//     -tour.name <picture>    the picture's name; without it the app runs as usual
//     -tour.screen <screen>   the screen to show
//
// The app shows that screen and, a little after it appears, writes the words of the
// screen's model, one per line, to Documents/tour/<picture>.txt. The script waits for
// that file and then takes its picture of the simulator's screen.
//
// What the file is: every string the model offers the view, read off the model itself.
// It is not a reading of the screen.
//
// Only keys that begin with "tour." are ever passed. A launch argument shadows a stored
// value for the whole run, so the app's own settings keys are never given this way.

#if DEBUG

import Foundation
import SnowlightCore
import SwiftUI
import UIKit

/// What one launch of the tour asks for.
struct TourPlan: Sendable {
    /// The picture's name. The words file is Documents/tour/<name>.txt.
    let name: String
    /// The screen to show.
    let screen: String

    /// The one screen there is so far.
    static let rootScreen = "root"

    /// The plan of this launch, or nil on every ordinary launch.
    static func fromLaunchArguments() -> TourPlan? {
        let defaults = UserDefaults.standard
        guard let name = defaults.string(forKey: "tour.name") else {
            return nil
        }
        guard isPlainName(name) else {
            Tour.note("the picture's name is not a plain name")
            return nil
        }
        guard let screen = defaults.string(forKey: "tour.screen"), isPlainName(screen) else {
            Tour.note("no screen was named for the picture " + name)
            return nil
        }
        return TourPlan(name: name, screen: screen)
    }

    /// Lower-case letters, digits and hyphens only, so a name is safe as a file name.
    private static func isPlainName(_ text: String) -> Bool {
        let bytes = Array(text.utf8)
        if bytes.isEmpty || bytes.count > 64 {
            return false
        }
        for byte in bytes {
            let isLetter = byte >= 0x61 && byte <= 0x7A
            let isDigit = byte >= 0x30 && byte <= 0x39
            let isHyphen = byte == 0x2D
            if !(isLetter || isDigit || isHyphen) {
                return false
            }
        }
        return true
    }
}

/// Put on the root view in debug builds. On an ordinary launch it does nothing. On a tour
/// launch it turns animations off and, about 0.6 seconds after the screen appears, hands
/// the words of the screen's model to be written.
struct TourStage: ViewModifier {
    /// The model the screen draws.
    let model: ShellModel

    func body(content: Content) -> some View {
        content.onAppear {
            guard let plan = TourPlan.fromLaunchArguments() else {
                return
            }
            guard plan.screen == TourPlan.rootScreen else {
                Tour.note("there is no screen named " + plan.screen)
                return
            }
            UIView.setAnimationsEnabled(false)
            Tour.note("showing " + plan.screen + " for the picture " + plan.name)
            let lines = shownTexts(in: model).map { $0.drawnString }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                Tour.writeWords(lines, for: plan)
            }
        }
    }
}

enum Tour {
    /// Writes the words file of a picture: a draft first, then a move, so the script
    /// outside never reads a half-written file.
    static func writeWords(_ lines: [String], for plan: TourPlan) {
        let files = FileManager.default
        guard let documents = files.urls(for: .documentDirectory, in: .userDomainMask).first else {
            note("this app has no Documents folder")
            return
        }
        let folder = documents.appendingPathComponent("tour", isDirectory: true)
        let draft = folder.appendingPathComponent(plan.name + ".draft", isDirectory: false)
        let ready = folder.appendingPathComponent(plan.name + ".txt", isDirectory: false)
        var text = ""
        for line in lines {
            text += line
            text += "\n"
        }
        do {
            try files.createDirectory(at: folder, withIntermediateDirectories: true, attributes: nil)
            try Data(text.utf8).write(to: draft)
            if files.fileExists(atPath: ready.path) {
                try files.removeItem(at: ready)
            }
            try files.moveItem(at: draft, to: ready)
            note("wrote " + ready.path)
        } catch {
            note("the words file could not be written: " + String(describing: error))
        }
    }

    /// One line on the app's standard error, which the script keeps in a file.
    static func note(_ message: String) {
        FileHandle.standardError.write(Data(("tour: " + message + "\n").utf8))
    }
}

#endif
