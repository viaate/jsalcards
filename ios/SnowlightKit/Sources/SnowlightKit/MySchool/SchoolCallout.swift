// The callout over the school's marker: the school's name and its status chip, in a capsule
// of the system's own glass (approved draft 3: d3t/app.css:240-245, app.js:170-186; RD-13,
// as the lead ruled: the system's Liquid Glass, not the draft's imitation of it).
//
// The capsule is 38 high and rounded 19, its two words 8 apart, with 14 before the name
// (the draft's own form with no crest, JS:178), 1 after it (CSS:243) and 5 after the chip
// (CSS:240). The name is drawn in `mapInk` (CSS:175). The chip is 26 high, rounded 13, 10
// in from each side, its word in `closedOn` on `closedChip` (CSS:244-245). Neither word
// wraps (`white-space: nowrap`). In M1 only the closed chip is drawn.
//
// VoiceOver reads it as one element: the name, then the chip's word (M1 6.1). It is not a
// button in M1.
//
// Its place (JS:181-185): centred over the dot, its bottom 30 above the dot, and kept
// inside the map's area, 16 from its edges (SnowlightCore's PanelPlace: calloutFrom and
// calloutTo), which needs its width: CalloutPlacement below measures it and places it.

import SnowlightCore
import SwiftUI

struct SchoolCallout: View {
    let callout: MySchoolModel.Callout

    var body: some View {
        HStack(spacing: CGFloat(Bands.length(Band.calloutGap))) {
            ShownLabel(callout.name)
                .typeStyle(.calloutName)
                .foregroundStyle(Color.token(.mapInk))
                .lineLimit(1)
                .fixedSize()
                .padding(.trailing, CGFloat(Bands.length(Band.calloutNameTrailing)))
            ShownLabel(callout.chip)
                .typeStyle(.chip)
                .foregroundStyle(Color.token(.closedOn))
                .lineLimit(1)
                .fixedSize()
                .padding(.horizontal, CGFloat(Bands.length(Band.chipPadding)))
                .frame(height: CGFloat(Bands.length(Band.chipHeight)))
                .background {
                    RoundedRectangle(cornerRadius: CGFloat(Bands.length(Band.chipRadius)), style: RoundedCornerStyle.circular)
                        .fill(Color.token(.closedChip))
                }
        }
        .padding(.leading, CGFloat(Bands.length(Band.calloutLeading)))
        .padding(.trailing, CGFloat(Bands.length(Band.calloutTrailing)))
        .frame(height: CGFloat(Bands.length(Band.calloutHeight)))
        .glassEffect(
            Glass.regular,
            in: RoundedRectangle(cornerRadius: CGFloat(Bands.length(Band.calloutRadius)), style: RoundedCornerStyle.circular)
        )
        .accessibilityElement(children: .combine)
    }
}

/// Places one view, the callout, at its own size: centred on `centreX`, its bottom at
/// `bottomY`, and moved in so that it stays between `from` and `to` (all from the leading
/// and top edges of the room it is given), as the draft's script places it (JS:181-185).
/// It takes the whole room it is offered and draws nothing of its own.
struct CalloutPlacement: Layout {
    let centreX: CGFloat
    let bottomY: CGFloat
    let from: CGFloat
    let to: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        proposal.replacingUnspecifiedDimensions()
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for subview in subviews {
            let size = subview.sizeThatFits(ProposedViewSize.unspecified)
            let left = max(from, min(to - size.width, centreX - size.width / 2))
            subview.place(
                at: CGPoint(x: bounds.minX + left, y: bounds.minY + bottomY - size.height),
                anchor: UnitPoint.topLeading,
                proposal: ProposedViewSize(size)
            )
        }
    }
}
