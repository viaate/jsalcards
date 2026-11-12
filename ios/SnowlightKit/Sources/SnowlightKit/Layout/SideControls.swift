// The layout value of the iPhone Duo's outside screen, put on a view: where a page's
// ground meets the system's side controls.
//
// On the closed Duo the system stands its controls in a column on the right, and the
// owner's Outside screen setting picks how a screen's content meets it (SnowlightCore's
// OutsideScreen.swift): "Beside the map" (A, the default) stops the content where the
// column begins; "Under the controls" (B) runs it on under the column to the right edge.
// The root view hands every screen the kept choice through the environment, nil on any
// other phone; a screen reads it through `PageGround` (the placeholder tabs today, the
// screens with a sheet over the map from M1 on). On any other phone, and on the open Duo,
// the ground runs under the system's controls, as it always has.

import SnowlightCore
import SwiftUI

private struct OutsideScreenKey: EnvironmentKey {
    static let defaultValue: OutsideScreenChoice? = nil
}

private struct PlaceholderGroundKey: EnvironmentKey {
    static let defaultValue: Token = Token.page
}

extension EnvironmentValues {
    /// The kept Outside screen choice on a phone with an outside screen; nil on any other.
    var outsideScreen: OutsideScreenChoice? {
        get { self[OutsideScreenKey.self] }
        set { self[OutsideScreenKey.self] = newValue }
    }

    /// The token the placeholder tabs fill their ground with: the page color. The debug
    /// tour alone sets another, to show in its pictures where the ground stops.
    var placeholderGround: Token {
        get { self[PlaceholderGroundKey.self] }
        set { self[PlaceholderGroundKey.self] = newValue }
    }
}

/// A page's ground in one token. It runs to the window's edges, under the system's bars,
/// except on the closed iPhone Duo with Beside the map chosen, where it stops at the
/// trailing edge of the safe area: where the system's side controls begin.
struct PageGround: View {
    let token: Token

    @Environment(\.outsideScreen) private var outsideScreen
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        Color.token(token)
            .ignoresSafeArea(.all, edges: edges)
    }

    private var edges: Edge.Set {
        switch sideControls(outsideScreen: outsideScreen, widthClass: widthClass) {
        case .contentRunsUnder:
            return Edge.Set.all
        case .contentStopsBeside:
            return [Edge.Set.top, Edge.Set.bottom, Edge.Set.leading]
        }
    }

    private var widthClass: WidthClass {
        sizeClass == .regular ? WidthClass.regular : WidthClass.compact
    }
}
