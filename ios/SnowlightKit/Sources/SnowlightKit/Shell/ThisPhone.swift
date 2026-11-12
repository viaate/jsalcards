// The one place the app knows which phone it runs on: whether it has an outside screen.
//
// The Outside screen row of Settings exists only on an iPhone Duo (the owner's ruling of
// Nov 11, 2026). The iOS 27.1 SDK has no documented call that says whether a phone has an
// outside screen. It does have UIKit's hinge interaction (UIHinge.h, UIHingeInteraction.h,
// iOS 27.1): on the closed Duo simulator it reported "status 1 (Closed)" on every launch
// (iOS app run 43204344211), and on the iPhone 18 Pro it never called back at all. Whether a
// hinge counts as "has an outside screen", and whether the app should switch to it, is the
// lead's ruling, still open; until then this reads the phone's model name, the last resort
// the build spec allows, and SnowlightCore says whether that model is a Duo (PhoneModel).
// On the simulator the model name is the simulated phone's, which the simulator hands the
// app in its environment; on a phone it is the system's own (hw.machine). The Duo's name,
// iPhone19,4, comes from the simulator's device profile only: it is not yet confirmed on a
// real iPhone Duo, and if the real one differs the row would not show there.

// It hands out one Bool and nothing else: no name read here reaches a view, and the name
// is never turned into words. tools/check-ios.mjs lets this file, and no other view file,
// hold the two names below and read ProcessInfo (rule this.phone).

import Foundation
import SnowlightCore

enum ThisPhone {
    /// True on an iPhone Duo. Read once: a phone does not change while the app runs.
    static let hasOuterScreen: Bool = PhoneModel.hasOuterScreen(machine: ThisPhone.modelBytes())

    /// The phone's model name as bytes, or none when it cannot be read.
    private static func modelBytes() -> [UInt8] {
        #if targetEnvironment(simulator)
        guard let model = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] else {
            return []
        }
        return Array(model.utf8)
        #else
        var size = 0
        guard sysctlbyname("hw.machine", nil, &size, nil, 0) == 0, size > 0, size < 256 else {
            return []
        }
        var bytes = [UInt8](repeating: 0, count: size)
        guard sysctlbyname("hw.machine", &bytes, &size, nil, 0) == 0 else {
            return []
        }
        return bytes
        #endif
    }
}
