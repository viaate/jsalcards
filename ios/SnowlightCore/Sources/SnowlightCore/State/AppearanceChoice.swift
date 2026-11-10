// The app's look: follow the phone, or always light, or always dark.
//
// The choice is kept on the phone as one short word, under one key of the app's settings
// store. The word and the key live here and nowhere else: the stored form is not public,
// and the store is read and written only through the three calls at the end of this file,
// which deal in choices. So no stored word ever reaches SnowlightKit, and no view can
// hand one to a control that takes a plain string.

import Foundation

/// The look the app is drawn in once the choice and the phone are both known.
public enum ResolvedAppearance: Equatable, Hashable, Sendable, CaseIterable {
    case light
    case dark
}

/// What Settings offers: System, Light, Dark, in that order.
public enum AppearanceChoice: Equatable, Hashable, Sendable, CaseIterable {
    case system
    case light
    case dark

    /// The choice of a phone that has never been asked: follow the phone.
    public static let standard: AppearanceChoice = AppearanceChoice.system

    /// The form kept on the phone. Not public: it never leaves this package.
    var stored: String {
        switch self {
        case .system:
            return "system"
        case .light:
            return "light"
        case .dark:
            return "dark"
        }
    }

    /// Reads the stored form. Nothing stored, or anything this build does not know,
    /// reads as System. Not public, like the form itself.
    init(stored: String?) {
        var found = AppearanceChoice.standard
        if let stored = stored {
            for choice in AppearanceChoice.allCases where choice.stored == stored {
                found = choice
            }
        }
        self = found
    }

    /// The look this choice gives on a phone that is, or is not, in its dark look.
    public func resolved(phoneIsDark: Bool) -> ResolvedAppearance {
        switch self {
        case .system:
            return phoneIsDark ? .dark : .light
        case .light:
            return .light
        case .dark:
            return .dark
        }
    }

    /// Every look this choice can give, light before dark. System can give both.
    public var looks: [ResolvedAppearance] {
        switch self {
        case .system:
            return [.light, .dark]
        case .light:
            return [.light]
        case .dark:
            return [.dark]
        }
    }
}

extension AppearanceChoice {
    /// The key of the app's settings store that the choice is kept under.
    static let storeKey = "appearance"

    /// The choice kept in a settings store. Nothing kept, or a value this build does not
    /// know, reads as System.
    public static func kept(in store: UserDefaults) -> AppearanceChoice {
        AppearanceChoice(stored: store.string(forKey: AppearanceChoice.storeKey))
    }

    /// Keeps this choice in a settings store, in its stored form.
    public func keep(in store: UserDefaults) {
        store.set(stored, forKey: AppearanceChoice.storeKey)
    }

    /// Forgets the choice kept in a settings store, so that the next read is System.
    public static func forget(in store: UserDefaults) {
        store.removeObject(forKey: AppearanceChoice.storeKey)
    }
}
