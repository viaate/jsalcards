// The app's look: follow the phone, or always light, or always dark.
//
// The choice is kept on the phone as one short word. It is turned to and from that stored
// form here and nowhere else, so no view ever handles the word.

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
    public static let standard = AppearanceChoice.system

    /// The form kept on the phone.
    public var stored: String {
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
    /// reads as System.
    public init(stored: String?) {
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
