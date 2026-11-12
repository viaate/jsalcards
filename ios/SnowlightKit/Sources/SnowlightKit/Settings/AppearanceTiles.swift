// The three appearance tiles: System, Light, Dark.
//
// Drawn, not a system control. Each tile is a small picture of its look: that look's page
// color, holding a small block in that look's fill color with an ink bar. The System tile
// is half light, half dark. The chosen tile has a ring and a ticked label. One tap
// changes the whole app at once. The frame, the ring and the label of a tile are
// `SettingsTile`, which the Outside screen tiles share.

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
                    SettingsTile(label: option.label, isChosen: option.isChosen) {
                        HStack(spacing: 0) {
                            ForEach(option.choice.looks, id: \.self) { look in
                                LookSwatch(look: look)
                            }
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(option.isChosen ? .isSelected : [])
            }
        }
    }
}

/// One tile of a Settings row and its label: a picture 62 points high with corner radius
/// 14 and a hairline edge; the chosen one has a 2 point gap and then a 2.5 point ink ring,
/// and its label is stronger and ticked; the others' labels are quieter.
struct SettingsTile<Picture: View>: View {
    let label: ShownText
    let isChosen: Bool
    let picture: Picture

    init(label: ShownText, isChosen: Bool, @ViewBuilder picture: () -> Picture) {
        self.label = label
        self.isChosen = isChosen
        self.picture = picture()
    }

    var body: some View {
        VStack(spacing: 10) {
            framed
            name
        }
        .frame(maxWidth: .infinity)
        .contentShape(Rectangle())
    }

    private var framed: some View {
        picture
            .frame(maxWidth: .infinity)
            .frame(height: 62)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                // A hairline, so a tile the color of the page still has an edge.
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Color.token(.fill2), lineWidth: 1)
            }
            .overlay {
                if isChosen {
                    RoundedRectangle(cornerRadius: 18.5, style: .continuous)
                        .strokeBorder(Color.token(.ink), lineWidth: 2.5)
                        .padding(-4.5)
                }
            }
    }

    private var name: some View {
        HStack(spacing: 4) {
            if isChosen {
                SymbolName.tick.image
                    .font(.system(size: 11, weight: .bold))
                    .accessibilityHidden(true)
            }
            ShownLabel(label)
                .typeStyle(isChosen ? .subStrong : .sub)
        }
        .foregroundStyle(Color.token(isChosen ? .ink : .ink2))
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
