// The school's marker on the map, and its stem (approved draft 3: d3t/app.css:225-238 and
// app.js:157-166).
//
// The draft draws the marker as a 16 point round core with CSS box-shadows: a white ring
// and two pale halos by day, two glows at night, and a soft drop shadow by day. A
// box-shadow `x y b s c` on a round box of radius 8 is a circle of radius 8 + s, moved by
// (x, y), filled c, then blurred by a Gaussian whose standard deviation is b / 2; the
// layers lie under the core, the first listed on top (M1 2.6, the marker table). So the
// marker is a stack of circles, the last listed at the back; SwiftUI's blur radius is that
// standard deviation. The values are SnowlightCore's Shadows.swift and Bands.swift.
//
// The stem is 1 point wide. It starts where the callout's bottom sits, 30 above the dot,
// and stops 11.5 above it by day and 11 at night, a gradient from its top down (JS:165-166,
// CSS:232, :238). It is drawn after the core, as the draft appends it after the core.
//
// Both are drawings: hidden from VoiceOver, and they take no touch. In M1 only the closed
// marker is drawn (M1 2.1 rows 5 and 6); the others come with the screens that show them.

import SnowlightCore
import SwiftUI

/// The closed school's marker, centred on the point it is placed at.
struct SchoolMarker: View {
    let look: ResolvedAppearance

    var body: some View {
        let core = CGFloat(Bands.length(Band.markerCore))
        let layers: [DrawnShadow] = DrawnShadow.layers(Shadows.closedMarker(in: look)).reversed()
        ZStack {
            ForEach(layers.indices, id: \.self) { index in
                let layer = layers[index]
                Circle()
                    .fill(layer.color)
                    .frame(width: core + 2 * layer.spread, height: core + 2 * layer.spread)
                    .offset(x: layer.x, y: layer.y)
                    .blur(radius: layer.deviation)
            }
            Circle()
                .fill(Color.fixed(Shadows.closedMarkerCore(in: look)))
                .frame(width: core, height: core)
        }
        .frame(width: core, height: core)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// The marker's stem: from the callout's bottom down to just above the dot.
struct SchoolStem: View {
    let look: ResolvedAppearance

    var body: some View {
        let ends = Shadows.stem(in: look)
        LinearGradient(
            colors: [Color.fixed(ends.top), Color.fixed(ends.bottom)],
            startPoint: UnitPoint.top,
            endPoint: UnitPoint.bottom
        )
        .frame(width: CGFloat(Bands.length(Band.stemWidth)), height: SchoolStem.height(in: look))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    /// Its length: from 30 above the dot to 11.5 (day) or 11 (night) above it.
    static func height(in look: ResolvedAppearance) -> CGFloat {
        CGFloat(Bands.length(Band.calloutLift) - Bands.stemEnd(in: look))
    }
}
