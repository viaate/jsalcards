// The three appearance tiles: System, Light, Dark.
//
// Drawn, not a system control. Each tile is a small picture of its look: that look's page
// color, holding a small block in that look's fill color with an ink bar. The System tile
// is half light, half dark. The chosen tile has a ring and a ticked label. One tap
// changes the whole app at once.

import SnowlightCore
import SwiftUI

struct AppearanceTiles: View {
    let options: [AppearanceOption]
    /// Called with the tile that was tapped.
    let choose: (AppearanceChoice) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ForEach(options, id: \.choice) { option in
                Button {
                    choose(option.choice)
                } label: {
                    AppearanceTile(option: option)
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(option.isChosen ? .isSelected : [])
            }
        }
    }
}

/// One tile and its label.
struct AppearanceTile: View {
    let option: AppearanceOption

    var body: some View {
        VStack(spacing: 10) {
            picture
            label
        }
        .frame(maxWidth: .infinity)
        .contentShape(Rectangle())
    }

    /// The tile: 62 points high, corner radius 14. The chosen one has a 2 point gap and
    /// then a 2.5 point ink ring.
    private var picture: some View {
        HStack(spacing: 0) {
            ForEach(option.choice.looks, id: \.self) { look in
                LookSwatch(look: look)
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 62)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            // A hairline, so a tile the color of the page still has an edge.
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color.token(.fill2), lineWidth: 1)
        }
        .overlay {
            if option.isChosen {
                RoundedRectangle(cornerRadius: 18.5, style: .continuous)
                    .strokeBorder(Color.token(.ink), lineWidth: 2.5)
                    .padding(-4.5)
            }
        }
    }

    /// The tile's name. The chosen one is stronger and has a tick; the others are quieter.
    private var label: some View {
        HStack(spacing: 4) {
            if option.isChosen {
                SymbolName.tick.image
                    .font(.system(size: 11, weight: .bold))
                    .accessibilityHidden(true)
            }
            ShownLabel(option.label)
                .typeStyle(option.isChosen ? .subStrong : .sub)
        }
        .foregroundStyle(Color.token(option.isChosen ? .ink : .ink2))
    }
}

/// A small picture of one look: its page color, a block in its fill color, an ink bar.
struct LookSwatch: View {
    let look: ResolvedAppearance

    var body: some View {
        ZStack {
            Color.token(.page, in: look)
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Color.token(.fill, in: look))
                .frame(width: 34, height: 26)
            Capsule()
                .fill(Color.token(.ink, in: look))
                .frame(width: 18, height: 4)
        }
    }
}
