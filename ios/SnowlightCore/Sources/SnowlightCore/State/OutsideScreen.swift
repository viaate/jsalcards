// The iPhone Duo's outside screen: where a screen's content goes beside the system's own
// controls when the phone is closed.
//
// The owner's ruling (Nov 11 and 12, 2026): on the closed Duo the system stands its
// controls in a column on the right. Settings offers two layouts, "Beside the map" (A, the
// default: the content stops where that column begins, and the map runs on under it) and
// "Under the controls" (B: the content runs on under the column to the right edge). The
// row exists only on an iPhone Duo; on any other iPhone Settings stays as it was, and the
// content runs under the system's controls as it always has.
//
// The choice is kept like the appearance choice: one short word under one key of the
// app's settings store, both known only here, read and written only through the three
// calls at the end of this file. Which phone has an outside screen is known here too, from
// the phone's model name handed in as bytes, so no text crosses the public surface.

import Foundation

/// What the Outside screen row of Settings offers, in the order it shows them.
public enum OutsideScreenChoice: Equatable, Hashable, Sendable, CaseIterable {
    /// A: the content stops beside the system's side controls.
    case besideTheMap
    /// B: the content runs on under the system's side controls.
    case underTheControls

    /// The choice of a phone that has never been asked: Beside the map.
    public static let standard: OutsideScreenChoice = OutsideScreenChoice.besideTheMap

    /// The form kept on the phone. Not public: it never leaves this package.
    var stored: String {
        switch self {
        case .besideTheMap:
            return "beside"
        case .underTheControls:
            return "under"
        }
    }

    /// Reads the stored form. Nothing stored, or anything this build does not know, reads
    /// as Beside the map. Not public, like the form itself.
    init(stored: String?) {
        var found = OutsideScreenChoice.standard
        if let stored = stored {
            for choice in OutsideScreenChoice.allCases where choice.stored == stored {
                found = choice
            }
        }
        self = found
    }
}

extension OutsideScreenChoice {
    /// The key of the app's settings store that the choice is kept under.
    static let storeKey = "outsideScreen"

    /// The choice kept in a settings store. Nothing kept, or a value this build does not
    /// know, reads as Beside the map.
    public static func kept(in store: UserDefaults) -> OutsideScreenChoice {
        OutsideScreenChoice(stored: store.string(forKey: OutsideScreenChoice.storeKey))
    }

    /// Keeps this choice in a settings store, in its stored form.
    public func keep(in store: UserDefaults) {
        store.set(stored, forKey: OutsideScreenChoice.storeKey)
    }

    /// Forgets the choice kept in a settings store, so that the next read is Beside the map.
    public static func forget(in store: UserDefaults) {
        store.removeObject(forKey: OutsideScreenChoice.storeKey)
    }
}

/// How a screen's content meets the system's controls on the side of the window: the
/// layout value every screen reads (a placeholder tab today; My School's sheet and the
/// others from M1 on).
public enum SideControls: Equatable, Hashable, Sendable, CaseIterable {
    /// The content stops where the system's side controls begin (A, on the closed Duo).
    case contentStopsBeside
    /// The content runs on under the system's controls: B on the closed Duo, and every
    /// other phone and pose, as the app has always been laid out.
    case contentRunsUnder
}

/// The layout value for a phone. `outsideScreen` is the kept choice on a phone with an
/// outside screen and nil on any other phone; `widthClass` is the window's: compact on the
/// closed Duo, regular on the open one, where the choice does not apply.
public func sideControls(outsideScreen: OutsideScreenChoice?, widthClass: WidthClass) -> SideControls {
    guard let choice = outsideScreen else {
        return SideControls.contentRunsUnder
    }
    switch widthClass {
    case .regular:
        return SideControls.contentRunsUnder
    case .compact:
        switch choice {
        case .besideTheMap:
            return SideControls.contentStopsBeside
        case .underTheControls:
            return SideControls.contentRunsUnder
        }
    }
}

/// Which phones have an outside screen, by the phone's model name.
///
/// No documented call of the iOS 27.1 SDK says whether a phone has an outside screen, so
/// the model name is the last resort the build spec allows: the one place the app knows
/// the device. The kit reads the name (Shell/ThisPhone.swift) and hands it here as bytes.
public enum PhoneModel {
    /// The model names of the iPhone Duo. The simulator's iPhone Duo is iPhone19,4 (its
    /// device profile, iOS app run 43129256570).
    static let withOuterScreen: [String] = ["iPhone19,4"]

    /// True when the model name, as bytes, is one of the iPhone Duo's. Zero bytes at the
    /// end (a C string's) are ignored; anything else must match exactly.
    public static func hasOuterScreen(machine: [UInt8]) -> Bool {
        var name = machine
        while let last = name.last, last == 0 {
            name.removeLast()
        }
        if name.isEmpty {
            return false
        }
        for model in PhoneModel.withOuterScreen where Array(model.utf8) == name {
            return true
        }
        return false
    }
}
