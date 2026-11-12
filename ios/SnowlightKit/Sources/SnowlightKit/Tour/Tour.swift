// The picture tour. Debug builds only: nothing in this folder exists in a release build.
//
// A script outside the app (ios/tools/tour.sh) starts the app once per picture with launch
// arguments, which arrive in the app's defaults:
//
//     -tour.name <picture>        the picture's name; without it the app runs as usual
//     -tour.screen <screen>       the screen to show: myschool, map, callit, settings, search,
//                                 or probe (the machine probe, MetalProbe.swift)
//     -tour.appearance <choice>   the look to start with: system, light or dark
//     -tour.then <choice>         a look to switch to in code, after the first frame
//     -tour.outside <layout>      the Outside screen layout to start with: beside or under
//                                 (read only on a phone with an outside screen), or kept:
//                                 leave the layout an earlier launch kept as it is
//     -tour.outsideThen <layout>  a layout to choose in code, after the first frame, through
//                                 the same call the Outside screen tiles make
//     -tour.row shown             show the Outside screen row on a phone without an outside
//                                 screen: the negative sample of the pixel step's check that
//                                 the row is absent on an iPhone (that check must fail on it)
//     -tour.proof ground          the placeholder tabs' ground in the chance teal instead of
//                                 the page color, so a picture shows where it stops
//
// On such a launch the app:
//
//   1. keeps the choice named by tour.appearance where the app keeps its own choice, or
//      forgets the kept choice when the argument is absent (the app's data survives from
//      one picture to the next); the same for tour.outside and the Outside screen choice,
//      except that tour.outside kept leaves it as it is; and says whether this phone has an
//      outside screen;
//   2. shows the named screen, with animations off;
//   3. about 0.6 seconds after it appears: if tour.then or tour.outsideThen is given, makes
//      that choice through the same call the Settings tiles make, and waits 0.6 seconds
//      more;
//   4. writes the words of the screen's model, one per line, to
//      Documents/tour/<picture>.txt. The script waits for that file and then takes its
//      picture of the simulator's screen.
//
// What the file is: every string the screen's model offers the view, read off the model
// itself. It is not a reading of the screen.
//
// The probe is the one exception. It has no model and shows no word: it stands in place
// of the shell, and its file holds two facts about the machine instead (MetalProbe.swift).
//
// Only keys that begin with "tour." are ever passed. A launch argument shadows a stored
// value for the whole run, so the app's own settings keys are never given this way: if
// they were, the app could keep "system" and still read back "dark", and the picture of
// the switch would prove nothing.
//
// Reserved and not read yet: tour.zone, the viewer's time zone for a picture.

#if DEBUG

import Foundation
import SnowlightCore
import SwiftUI
import UIKit

/// What a launch of the tour shows.
enum TourShow: Sendable {
    /// One of the shell's five screens.
    case shell(ScreenID)
    /// The machine probe, in place of the shell.
    case probe
}

/// What one launch of the tour asks for.
struct TourPlan: Sendable {
    /// The picture's name. The words file is Documents/tour/<name>.txt.
    let name: String
    /// The screen to show, as the script names it.
    let screenName: String
    /// What to show.
    let show: TourShow
    /// The look to start with, or nil to start as a fresh install does.
    let appearance: AppearanceChoice?
    /// A look to switch to in code after the first frame, or nil.
    let switchTo: AppearanceChoice?
    /// The Outside screen layout to start with, or nil to start as a fresh install does.
    let outside: OutsideScreenChoice?
    /// True when the layout an earlier launch kept is left as it is (tour.outside kept).
    let keepsOutside: Bool
    /// An Outside screen layout to choose in code after the first frame, or nil.
    let outsideThen: OutsideScreenChoice?
    /// True when the Outside screen row is shown on a phone without an outside screen.
    let forcesRow: Bool
    /// True when the placeholder tabs' ground is drawn in the chance teal.
    let proofGround: Bool

    /// The screen of the shell to open on, or nil when the launch shows the probe.
    var screen: ScreenID? {
        switch show {
        case .shell(let id):
            return id
        case .probe:
            return nil
        }
    }

    /// True when the launch shows the machine probe in place of the shell.
    var showsProbe: Bool {
        switch show {
        case .shell:
            return false
        case .probe:
            return true
        }
    }

    /// The plan of this launch, or nil on every ordinary launch. Read once.
    static let ofThisLaunch: TourPlan? = TourPlan.fromLaunchArguments()

    private static func fromLaunchArguments() -> TourPlan? {
        let defaults = UserDefaults.standard
        guard let name = defaults.string(forKey: "tour.name") else {
            return nil
        }
        guard TourPlan.isPlainName(name) else {
            Tour.note("the picture's name is not a plain name")
            return nil
        }
        guard let screenName = defaults.string(forKey: "tour.screen"), TourPlan.isPlainName(screenName) else {
            Tour.note("no screen was named for the picture " + name)
            return nil
        }
        guard let show = TourPlan.show(named: screenName) else {
            Tour.note("there is no screen named " + screenName)
            return nil
        }
        let keepsOutside = defaults.string(forKey: "tour.outside") == "kept"
        return TourPlan(
            name: name,
            screenName: screenName,
            show: show,
            appearance: TourPlan.choice(under: "tour.appearance", in: defaults),
            switchTo: TourPlan.choice(under: "tour.then", in: defaults),
            outside: keepsOutside ? nil : TourPlan.layout(under: "tour.outside", in: defaults),
            keepsOutside: keepsOutside,
            outsideThen: TourPlan.layout(under: "tour.outsideThen", in: defaults),
            forcesRow: TourPlan.forcesRow(in: defaults),
            proofGround: TourPlan.proofGround(in: defaults)
        )
    }

    private static func show(named name: String) -> TourShow? {
        switch name {
        case "myschool":
            return .shell(.mySchool)
        case "map":
            return .shell(.map)
        case "callit":
            return .shell(.callIt)
        case "settings":
            return .shell(.settings)
        case "search":
            return .shell(.search)
        case "probe":
            return .probe
        default:
            return nil
        }
    }

    /// The choice a launch argument names, or nil when the argument is absent. A value
    /// that is not one of the three is said out loud and read as absent.
    private static func choice(under key: String, in defaults: UserDefaults) -> AppearanceChoice? {
        guard let value = defaults.string(forKey: key) else {
            return nil
        }
        for choice in AppearanceChoice.allCases where Tour.name(of: choice) == value {
            return choice
        }
        Tour.note(key + " is not system, light or dark")
        return nil
    }

    /// The Outside screen layout a launch argument names, or nil when it is absent. A value
    /// that is not beside or under is said out loud and read as absent.
    private static func layout(under key: String, in defaults: UserDefaults) -> OutsideScreenChoice? {
        guard let value = defaults.string(forKey: key) else {
            return nil
        }
        for choice in OutsideScreenChoice.allCases where Tour.name(of: choice) == value {
            return choice
        }
        Tour.note(key + " is not beside or under")
        return nil
    }

    /// True when tour.row says shown. Anything else is said out loud and read as absent.
    private static func forcesRow(in defaults: UserDefaults) -> Bool {
        guard let value = defaults.string(forKey: "tour.row") else {
            return false
        }
        if value == "shown" {
            return true
        }
        Tour.note("tour.row is not shown")
        return false
    }

    /// True when tour.proof says ground. Anything else is said out loud and read as absent.
    private static func proofGround(in defaults: UserDefaults) -> Bool {
        guard let value = defaults.string(forKey: "tour.proof") else {
            return false
        }
        if value == "ground" {
            return true
        }
        Tour.note("tour.proof is not ground")
        return false
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
/// launch it turns animations off and, a little after the shell appears, makes the switch
/// the launch asked for, if any, and has the words of the screen's model written; all the
/// while, the window's measure goes to the log. On the one launch that asks for the probe,
/// it shows the probe in place of the shell.
struct TourStage: ViewModifier {
    /// The app's appearance choice: the same object the Settings tiles change.
    let appearance: AppearanceStore
    /// The app's Outside screen choice: the same object its tiles change.
    let outside: OutsideScreenStore

    func body(content: Content) -> some View {
        if let plan = TourPlan.ofThisLaunch, plan.showsProbe {
            // None of the shell is shown on this launch, and the probe writes its own file.
            MetalProbeScreen(plan: plan)
        } else {
            // Behind the shell, a view of no look that writes the window's size, safe area,
            // size classes and the places of the system's bars to the log whenever they
            // change (TourGeometry.swift).
            content.background {
                TourGeometry().ignoresSafeArea()
            }
            .environment(\.placeholderGround, TourPlan.ofThisLaunch?.proofGround == true ? Token.chance : Token.page)
            .onAppear {
                guard let plan = TourPlan.ofThisLaunch, Tour.begin() else {
                    return
                }
                UIView.setAnimationsEnabled(false)
                Tour.note("showing " + plan.screenName + " for the picture " + plan.name)
                let store = appearance
                let layout = outside
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    if plan.switchTo == nil && plan.outsideThen == nil {
                        Tour.writeWords(for: plan, shownWith: store, layout: layout)
                        return
                    }
                    // The same calls a tap on a Settings tile makes.
                    if let next = plan.switchTo {
                        store.choose(next)
                        Tour.note("switched the look in code to " + Tour.name(of: next))
                    }
                    if let nextLayout = plan.outsideThen {
                        layout.choose(nextLayout)
                        Tour.note("chose the Outside screen layout " + Tour.name(of: nextLayout) + " in code, through the tiles' own call")
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                        Tour.writeWords(for: plan, shownWith: store, layout: layout)
                    }
                }
            }
        }
    }
}

enum Tour {
    /// Step 1 of a tour launch, done before the app reads its own choice: keep the look
    /// the launch names where the app keeps its choice, or forget what is kept there. On
    /// an ordinary launch this does nothing. It runs once however often it is called.
    static func prepare() {
        _ = Tour.prepared
    }

    private static let prepared: Bool = {
        guard let plan = TourPlan.ofThisLaunch else {
            return false
        }
        let defaults = UserDefaults.standard
        if let choice = plan.appearance {
            choice.keep(in: defaults)
            Tour.note("kept the look " + Tour.name(of: choice) + " for the picture " + plan.name)
        } else {
            AppearanceChoice.forget(in: defaults)
            Tour.note("forgot any kept look for the picture " + plan.name)
        }
        if plan.keepsOutside {
            let kept = OutsideScreenChoice.kept(in: defaults)
            Tour.note("left the kept Outside screen layout as it was, " + Tour.name(of: kept) + ", for the picture " + plan.name)
        } else if let layout = plan.outside {
            layout.keep(in: defaults)
            Tour.note("kept the Outside screen layout " + Tour.name(of: layout) + " for the picture " + plan.name)
        } else {
            OutsideScreenChoice.forget(in: defaults)
            Tour.note("forgot any kept Outside screen layout for the picture " + plan.name)
        }
        Tour.note("this phone has an outside screen: " + (ThisPhone.hasOuterScreen ? "yes" : "no"))
        if plan.forcesRow {
            Tour.note("the Outside screen row is shown for the picture " + plan.name + " although this phone may have no outside screen: a negative sample")
        }
        if plan.proofGround {
            Tour.note("the placeholder tabs' ground is drawn in the chance teal for the picture " + plan.name)
        }
        return true
    }()

    /// A choice's name in the tour's own launch arguments and notes. The app's stored form
    /// is SnowlightCore's and is not public; the tour names the three choices itself.
    static func name(of choice: AppearanceChoice) -> String {
        switch choice {
        case .system:
            return "system"
        case .light:
            return "light"
        case .dark:
            return "dark"
        }
    }

    /// An Outside screen layout's name in the tour's own launch arguments and notes.
    static func name(of layout: OutsideScreenChoice) -> String {
        switch layout {
        case .besideTheMap:
            return "beside"
        case .underTheControls:
            return "under"
        }
    }

    /// True when Settings shows the Outside screen row on this launch: on a phone with an
    /// outside screen, and on the one tour launch that forces it as a negative sample.
    static var showsOutsideScreenRow: Bool {
        ThisPhone.hasOuterScreen || TourPlan.ofThisLaunch?.forcesRow == true
    }

    private static var begun = false

    /// True the first time it is asked, on the main thread: the tour runs once a launch.
    static func begin() -> Bool {
        if Tour.begun {
            return false
        }
        Tour.begun = true
        return true
    }

    /// Writes the words file of a picture: the words of the screen's model as the screen
    /// is shown now, one per line.
    static func writeWords(for plan: TourPlan, shownWith store: AppearanceStore, layout: OutsideScreenStore) {
        guard let screen = plan.screen else {
            note("the picture " + plan.name + " shows no screen of the shell, so it has no words")
            return
        }
        // The same model the root view draws: with the Outside screen row only on a phone
        // that has an outside screen.
        let outsideScreen: OutsideScreenChoice? = Tour.showsOutsideScreenRow ? layout.choice : nil
        let model = ShellModel(appearance: store.choice, outsideScreen: outsideScreen).screen(screen)
        let lines = shownTexts(in: model).map { $0.drawnString }
        Tour.write(lines, for: plan)
    }

    /// Writes a draft first, then moves it, so the script outside never reads a
    /// half-written file.
    static func write(_ lines: [String], for plan: TourPlan) {
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
