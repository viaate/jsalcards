// The panel over the map: our own view, not a system sheet (M1 RD-22, as the lead ruled).
// A system sheet is shown above everything, the tab bar included; the draft shows the tab
// bar floating over the panel. So the panel is a plain view inside the system's scroll view
// (MySchool/MySchoolScreen.swift), and the system's bars float over it.
//
// Approved draft 3 draws it as `.sheet` (d3t/app.css:220-222): its top corners rounded 38,
// filled `sheet`, and in the dark look a gradient from #202127 at its top down to `sheet`
// 120 points below; its shadow is `--sheet-shadow` (CSS:19 light, :73 dark: in the dark
// look two thin light lines inside its top edge). A grabber, 36 x 5, sits 7 below its top
// (CSS:221): a drawing only, which moves nothing in M1 and is hidden from VoiceOver. Every
// length is a band of SnowlightCore's Bands.swift and every color a token or a line of its
// Shadows.swift; none is written here.
//
// Its ground runs from its top edge to the window's bottom edge, under the tab bar. Its
// width is the shape's (M1 2.5, D8): the whole window, but on the closed iPhone Duo with
// Beside the map chosen, where it stops at the system's side column.

import SnowlightCore
import SwiftUI

struct Panel<Content: View>: View {
    /// How far the panel's ground reaches across, from the window's leading edge.
    let width: CGFloat
    /// How far down it reaches at least: from its top edge to the window's bottom edge.
    let minHeight: CGFloat
    /// The grabber's centre, from the window's leading edge (PanelPlace.grabberCentre).
    let grabberCentre: CGFloat
    /// What the panel holds, laid out inside it.
    let content: Content

    @Environment(\.colorScheme) private var colorScheme

    init(width: CGFloat, minHeight: CGFloat, grabberCentre: CGFloat, @ViewBuilder content: () -> Content) {
        self.width = width
        self.minHeight = minHeight
        self.grabberCentre = grabberCentre
        self.content = content()
    }

    var body: some View {
        content
            .frame(width: width, alignment: .topLeading)
            .frame(minHeight: minHeight, alignment: .top)
            .background(alignment: .top) {
                PanelGround(look: look)
            }
            .overlay(alignment: .topLeading) {
                Grabber()
                    .padding(.top, CGFloat(Bands.length(Band.grabberTop)))
                    .padding(.leading, grabberCentre - CGFloat(Bands.length(Band.grabberWidth)) / 2)
            }
    }

    private var look: ResolvedAppearance {
        colorScheme == .dark ? ResolvedAppearance.dark : ResolvedAppearance.light
    }
}

/// The panel's shape: its two top corners rounded (CSS:220, border-radius: 38px 38px 0 0).
private func panelOutline() -> UnevenRoundedRectangle {
    let corner = CGFloat(Bands.length(Band.panelCorner))
    return UnevenRoundedRectangle(
        topLeadingRadius: corner,
        bottomLeadingRadius: 0,
        bottomTrailingRadius: 0,
        topTrailingRadius: corner,
        style: RoundedCornerStyle.circular
    )
}

/// The panel's ground and its shadow, in the look given.
private struct PanelGround: View {
    let look: ResolvedAppearance

    var body: some View {
        let shape = panelOutline()
        let layers = DrawnShadow.layers(Shadows.sheet(in: look))
        // CSS lists a shadow's layers the first on top: the outer ones are drawn the last
        // listed first, each from its own copy of the shape, so no layer shadows another.
        let outer: [DrawnShadow] = layers.filter { layer in !layer.inset }.reversed()
        let inner: [DrawnShadow] = layers.filter { layer in layer.inset }
        ZStack(alignment: .top) {
            ForEach(outer.indices, id: \.self) { index in
                shape
                    .fill(Color.token(.sheet))
                    .shadow(color: outer[index].color, radius: outer[index].deviation, x: outer[index].x, y: outer[index].y)
            }
            // The ground: `sheet`, and in the dark look the gradient at its top (CSS:222).
            shape.fill(Color.token(.sheet))
            if let top = Shadows.sheetTop(in: look) {
                LinearGradient(
                    colors: [Color.fixed(top), Color.token(.sheet)],
                    startPoint: UnitPoint.top,
                    endPoint: UnitPoint.bottom
                )
                .frame(height: CGFloat(Bands.length(Band.sheetGradient)))
                .clipShape(shape)
            }
            // The shadows drawn inside the top edge: the shape, less itself moved down by
            // the layer's offset, a thin line that follows the corners.
            ForEach(inner.indices, id: \.self) { index in
                shape
                    .subtracting(shape.offset(x: inner[index].x, y: inner[index].y))
                    .fill(inner[index].color)
            }
        }
        .accessibilityHidden(true)
    }
}

/// The grabber: a drawing only (CSS:221).
private struct Grabber: View {
    var body: some View {
        RoundedRectangle(cornerRadius: CGFloat(Bands.length(Band.grabberRadius)), style: RoundedCornerStyle.circular)
            .fill(Color.token(.grab))
            .frame(width: CGFloat(Bands.length(Band.grabberWidth)), height: CGFloat(Bands.length(Band.grabberHeight)))
            .accessibilityHidden(true)
    }
}
