// The app's look, set on the window.
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
        choice = DefaultsKey.appearance.readAppearance(in: store)
    }

    /// Changes the look of the whole app at once and keeps the choice on the phone. The
    /// one call that does: the Settings tiles make it, and so does the debug tour.
    func choose(_ newChoice: AppearanceChoice) {
        DefaultsKey.appearance.keep(newChoice, in: store)
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
