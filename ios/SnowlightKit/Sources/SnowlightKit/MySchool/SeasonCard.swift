// The season card of My School's panel (approved draft 3: myschool-closed-light.html:36,
// :39, :58-59 and :98-100).
//
// A card rounded 20, filled `fill`, 13 in from its top, 16 from its sides and 14 from its
// bottom (H:36). Its key, "This school year", is shown in capitals in `ink3` (H:39); the
// line sits 8 under it (H:58). The line is one text in two runs, as the draft draws it
// (H:100): the counts, "2 closed · 1 delayed " with the space before "since" in the same
// run, semibold in `ink`, then "since Oct 27" regular in `ink2`. Where the season takes the
// site's own line (RD-10, as the lead ruled), the rest of that line is drawn in the line's
// own style, semibold in `ink`, wrapping if it must: the spec's interim look, which no M1
// picture reaches.
//
// The draft's strip of school days and its month names are left out: the season file has
// counts only (RD-10), so the card is 54 points shorter. The card sits 17 below the day row,
// or 14 below the details line (H:36, :38): MySchoolScreen gives the gap.
//
// VoiceOver reads the card as one element: its key, then its line (M1 6.1).

import SnowlightCore
import SwiftUI

struct SeasonCard: View {
    let season: MySchoolModel.Season

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ShownLabel(key)
                .typeStyle(.cardKey)
                .textCase(.uppercase)
                .foregroundStyle(Color.token(.ink3))
            line
                .typeStyle(.counts)
                .foregroundStyle(Color.token(.ink))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, CGFloat(Bands.length(Band.countsGap)))
        }
        .padding(.top, CGFloat(Bands.length(Band.cardTop)))
        .padding(.horizontal, CGFloat(Bands.length(Band.cardSide)))
        .padding(.bottom, CGFloat(Bands.length(Band.cardBottom)))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            RoundedRectangle(cornerRadius: CGFloat(Bands.length(Band.cardRadius)), style: RoundedCornerStyle.circular)
                .fill(Color.token(.fill))
        }
        .accessibilityElement(children: .combine)
    }

    private var key: ShownText {
        switch season {
        case .drawn(let key, _, _):
            return key
        case .site(let key, _):
            return key
        }
    }

    /// The card's line: the counts and since as two runs of one text, or the site's rest.
    private var line: Text {
        switch season {
        case .drawn(_, let counts, let since):
            return counts.text + since.text.fontWeight(.regular).foregroundStyle(Color.token(.ink2))
        case .site(_, let rest):
            return rest.text
        }
    }
}
