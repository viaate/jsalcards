// The map behind My School's panel. In M1 there is no map yet (it comes in M3; RD-1): the
// window shows the map's ground, the fade at its top, and the school's marker, stem and
// callout, as PLAN M1 says ("the panel over a plain map-colored ground with the school's
// marker and pill"). Approved draft 3 draws them at d3t/app.css:119, :218-219, :224-245
// and app.js:157-186.
//
// It is the one full-bleed surface (R15 rule 2): it runs to every edge of the window,
// under the status bar, the system's bars and, on the closed iPhone Duo, its side column
// (M1 2.5, D2). It is a picture, not a control: it takes no touch in M1, and its ground,
// fade, marker and stem are hidden from VoiceOver (M1 6.1); the callout is read.
//
// The map's look follows the app's look through the pairing the app ships with (State/
// MapLook.swift: matched, the pale map in the light look and the dark map in the dark). The
// places are SnowlightCore's PanelPlace, from the window's top leading corner: this view
// is laid out over the whole window.

import SnowlightCore
import SwiftUI

struct MapWindow: View {
    let place: PanelPlace
    /// The callout, drawn only over a closed school (M1 draws no other marker).
    let callout: MySchoolModel.Callout?
    /// True when the school's marker is drawn: the panel's status is a posted closing.
    let marked: Bool

    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let look = colorScheme == .dark ? ResolvedAppearance.dark : ResolvedAppearance.light
        let map = mapLook(for: look, pairing: Pairing.standard)
        let x = CGFloat(place.markerX)
        let y = CGFloat(place.markerY)
        let lift = CGFloat(Bands.length(Band.calloutLift))
        ZStack(alignment: .topLeading) {
            Color.token(.mapBg, in: MapWindow.look(of: map))
                .accessibilityHidden(true)
            LinearGradient(
                colors: [Color.token(.mapFade, in: MapWindow.look(of: map)), Color.token(.mapFade0, in: MapWindow.look(of: map))],
                startPoint: UnitPoint.top,
                endPoint: UnitPoint.bottom
            )
            .frame(height: CGFloat(Bands.length(Band.topFade)))
            .accessibilityHidden(true)
            if marked {
                SchoolMarker(look: look)
                    .position(x: x, y: y)
                SchoolStem(look: look)
                    .position(x: x, y: y - lift + SchoolStem.height(in: look) / 2)
                if let callout = callout {
                    CalloutPlacement(
                        centreX: x,
                        bottomY: y - lift,
                        from: CGFloat(place.calloutFrom),
                        to: CGFloat(place.calloutTo)
                    ) {
                        SchoolCallout(callout: callout)
                    }
                }
            }
        }
        .allowsHitTesting(false)
    }

    /// The look whose map colors a map look takes: the pale map's are the light look's
    /// tokens and the dark map's the dark look's (CSS:50-54, :102-106).
    private static func look(of map: MapLook) -> ResolvedAppearance {
        switch map {
        case .pale:
            return ResolvedAppearance.light
        case .dark:
            return ResolvedAppearance.dark
        }
    }
}
