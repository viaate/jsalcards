// The app's look, set on the window; and the two choices Settings keeps on the phone (the
// look and, on an iPhone Duo, the Outside screen layout): the one view file that holds the
// settings store.
//
// The choice (System, Light, Dark) is kept on the phone and applied to the window itself,
// not to a view: everything in a window follows the window, sheets, menus and alerts
// included, and going back to System takes effect at once, with no relaunch.

import Combine
import Foundation
import SnowlightCore
import SwiftUI
import UIKit

/// The appearance choice, as the app holds it while it runs.
final class AppearanceStore: ObservableObject {
    /// The choice now in force.
    @Published private(set) var choice: AppearanceChoice

    private let store: UserDefaults

    init(store: UserDefaults = .standard) {
        self.store = store
        choice = AppearanceChoice.kept(in: store)
    }

    /// Changes the look of the whole app at once and keeps the choice on the phone. The
    /// one call that does: the Settings tiles make it, and so does the debug tour.
    func choose(_ newChoice: AppearanceChoice) {
        newChoice.keep(in: store)
        choice = newChoice
    }
}

/// The Outside screen choice, as the app holds it while it runs. Kept in the same settings
/// store as the look, through SnowlightCore. Only an iPhone Duo shows the row that changes
/// it; on any other phone it is never read.
final class OutsideScreenStore: ObservableObject {
    /// The choice now in force.
    @Published private(set) var choice: OutsideScreenChoice

    private let store: UserDefaults

    init(store: UserDefaults = .standard) {
        self.store = store
        choice = OutsideScreenChoice.kept(in: store)
    }

    /// Changes the layout at once and keeps the choice on the phone. The one call that
    /// does: the Outside screen tiles make it.
    func choose(_ newChoice: OutsideScreenChoice) {
        newChoice.keep(in: store)
        choice = newChoice
    }
}

/// A helper view of no size in the root's background. It finds the window it is in and
/// sets the window's look, when it joins the window and again whenever the choice changes.
struct WindowStyle: UIViewRepresentable {
    let choice: AppearanceChoice

    func makeUIView(context: Context) -> WindowStyleView {
        let view = WindowStyleView()
        view.isUserInteractionEnabled = false
        view.backgroundColor = .clear
        view.look = WindowStyle.look(for: choice)
        return view
    }

    func updateUIView(_ view: WindowStyleView, context: Context) {
        view.look = WindowStyle.look(for: choice)
    }

    private static func look(for choice: AppearanceChoice) -> UIUserInterfaceStyle {
        switch choice {
        case .system:
            return .unspecified
        case .light:
            return .light
        case .dark:
            return .dark
        }
    }
}

/// The view behind `WindowStyle`. It draws nothing.
final class WindowStyleView: UIView {
    /// The look the window should have. Unspecified means: follow the phone.
    var look: UIUserInterfaceStyle = .unspecified {
        didSet {
            apply()
        }
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        apply()
    }

    private func apply() {
        guard let window = window else {
            return
        }
        if window.overrideUserInterfaceStyle != look {
            window.overrideUserInterfaceStyle = look
        }
    }
}
