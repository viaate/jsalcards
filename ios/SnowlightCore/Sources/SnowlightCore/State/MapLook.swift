// Which map goes with which look of the app.
//
// Decided: matched. Light panels sit over the pale map and dark panels over the dark map.
// The other pairing, the dark map under either look, stays here so both can be held side
// by side on a phone later. Nothing draws a map yet; the rule and its test exist so the
// map does not have to invent it.

/// The two maps the app can draw.
public enum MapLook: Equatable, Hashable, Sendable, CaseIterable {
    case dark
    case pale
}

/// How the map is paired with the app's look.
public enum Pairing: Equatable, Hashable, Sendable, CaseIterable {
    /// The pale map in the light look, the dark map in the dark look.
    case matched
    /// The dark map whatever the look.
    case alwaysDarkMap

    /// The pairing the app ships with.
    public static let standard = Pairing.matched
}

/// The map to draw under the app's look.
public func mapLook(for appearance: ResolvedAppearance, pairing: Pairing) -> MapLook {
    switch pairing {
    case .alwaysDarkMap:
        return .dark
    case .matched:
        switch appearance {
        case .light:
            return .pale
        case .dark:
            return .dark
        }
    }
}
