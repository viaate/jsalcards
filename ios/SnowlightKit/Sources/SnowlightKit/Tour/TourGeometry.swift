// The picture tour's measure of the window. Debug builds only.
//
// A view of no look behind the shell. On a tour launch, each time the window it is in
// changes (its size, its safe area, its size classes, where the system put the tab bar),
// it writes one line on the app's standard error, which the tour script keeps:
//
//     tour: geometry: window 402 x 874 pt; safe area top 62 left 0 bottom 34 right 0; ...
//
// So the log says what size the app was really given on each simulator, in points, and
// where the system's own controls went. It measures; nothing reads it back, and nothing of
// the shell is laid out by it.

#if DEBUG

import SwiftUI
import UIKit

/// Put behind the shell. It draws nothing and takes no touch.
struct TourGeometry: UIViewRepresentable {
    func makeUIView(context: Context) -> TourGeometryView {
        let view = TourGeometryView()
        view.isUserInteractionEnabled = false
        view.isOpaque = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ view: TourGeometryView, context: Context) {
        view.report()
    }
}

/// The view behind `TourGeometry`. It fills the window, so the system lays it out again
/// whenever the window changes size.
final class TourGeometryView: UIView {
    private var lastLine = ""

    override func didMoveToWindow() {
        super.didMoveToWindow()
        report()
        watchHinge()
        // The tab bar is placed a moment after the window: one more look, a second later.
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            self?.report()
        }
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        report()
    }

    override func safeAreaInsetsDidChange() {
        super.safeAreaInsetsDidChange()
        report()
    }

    private var watchingHinge = false

    /// Built with the iOS 27.1 SDK (Swift 6.4) and run on iOS 27.1 or later: puts the
    /// system's hinge interaction (UIHingeInteraction, new in that SDK) on the window and
    /// writes what it reports to the log, a hinge's status and angle or none, so the tour
    /// says what a phone with a hinge, the iPhone Duo, reports closed. It measures; nothing
    /// reads it back. Only on a tour launch, once.
    private func watchHinge() {
        #if compiler(>=6.4)
        guard !watchingHinge, TourPlan.ofThisLaunch != nil, let window = window else {
            return
        }
        if #available(iOS 27.1, *) {
            watchingHinge = true
            let interaction = UIHingeInteraction { _, update in
                if let hinge = update.hinge {
                    Tour.note("hinge: status \(hinge.status.rawValue), angle \(hinge.angle) radians")
                } else {
                    Tour.note("hinge: none (the window's hierarchy gives no hinge updates)")
                }
            }
            window.addInteraction(interaction)
            Tour.note("hinge: watching, a UIHingeInteraction is on the window")
        }
        #endif
    }

    /// Writes the line when it differs from the last one written. Only on a tour launch.
    func report() {
        guard TourPlan.ofThisLaunch != nil, let window = window else {
            return
        }
        let line = TourGeometryView.describe(window)
        if line == lastLine {
            return
        }
        lastLine = line
        Tour.note("geometry: " + line)
    }

    private static func describe(_ window: UIWindow) -> String {
        let size = window.bounds.size
        let insets = window.safeAreaInsets
        let traits = window.traitCollection
        var parts: [String] = []
        parts.append("window \(number(size.width)) x \(number(size.height)) pt")
        let top = number(insets.top)
        let left = number(insets.left)
        let bottom = number(insets.bottom)
        let right = number(insets.right)
        parts.append("safe area top \(top) left \(left) bottom \(bottom) right \(right)")
        let across = sizeClass(traits.horizontalSizeClass)
        let down = sizeClass(traits.verticalSizeClass)
        parts.append("size classes width \(across) height \(down)")
        parts.append("scale \(number(traits.displayScale))")
        if let scene = window.windowScene {
            let screen = scene.screen
            let points = "\(number(screen.bounds.width)) x \(number(screen.bounds.height)) pt"
            let pixels = "\(number(screen.nativeBounds.width)) x \(number(screen.nativeBounds.height)) px native"
            parts.append("screen \(points), \(pixels), scale \(number(screen.scale))")
            parts.append("orientation \(orientation(scene.effectiveGeometry.interfaceOrientation))")
            parts.append("scene role \(scene.session.role.rawValue)")
        }
        var bars: [String] = []
        collectBars(in: window, window: window, into: &bars)
        if bars.isEmpty {
            parts.append("no view named a bar")
        } else {
            parts.append("bars " + bars.joined(separator: ", "))
        }
        return parts.joined(separator: "; ")
    }

    /// Every view whose class name holds "TabBar", "Sidebar" or "NavigationBar" or
    /// "Toolbar", with its frame in the window's points: where the system put its
    /// controls. At most twelve, outermost first.
    private static func collectBars(in view: UIView, window: UIWindow, into bars: inout [String]) {
        if bars.count >= 12 {
            return
        }
        let name = String(describing: type(of: view))
        if name.contains("TabBar") || name.contains("Sidebar") || name.contains("NavigationBar") || name.contains("Toolbar") {
            let frame = view.convert(view.bounds, to: window)
            var entry = "\(name) at x \(number(frame.minX)) y \(number(frame.minY))"
            entry += " w \(number(frame.width)) h \(number(frame.height))"
            if view.isHidden || view.alpha < 0.01 {
                entry += " hidden"
            }
            bars.append(entry)
        }
        for child in view.subviews {
            collectBars(in: child, window: window, into: &bars)
        }
    }

    /// A length to one decimal, without the decimal when it is whole.
    private static func number(_ value: CGFloat) -> String {
        let tenths = Double((value * 10).rounded())
        if tenths.truncatingRemainder(dividingBy: 10) == 0 {
            return String(Int(tenths / 10))
        }
        return String(tenths / 10)
    }

    private static func sizeClass(_ value: UIUserInterfaceSizeClass) -> String {
        switch value {
        case .compact:
            return "compact"
        case .regular:
            return "regular"
        case .unspecified:
            return "unspecified"
        @unknown default:
            return "other " + String(value.rawValue)
        }
    }

    private static func orientation(_ value: UIInterfaceOrientation) -> String {
        switch value {
        case .portrait:
            return "portrait"
        case .portraitUpsideDown:
            return "portrait upside down"
        case .landscapeLeft:
            return "landscape left"
        case .landscapeRight:
            return "landscape right"
        case .unknown:
            return "unknown"
        @unknown default:
            return "other " + String(value.rawValue)
        }
    }
}

#endif
