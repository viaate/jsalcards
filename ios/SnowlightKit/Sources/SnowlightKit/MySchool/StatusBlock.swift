// The big status of My School's panel: the status word, the day row under it and, when the
// school posted any, the details line (approved draft 3: myschool-closed-light.html:21-33
// and :78-86; myschool-closed-details-light.html:86).
//
// - The word sits 8 below the name, 3 left of the content's edge, in `closedHero` (H:21-22).
//   The weather beside it in the draft is left out: the app has no weather (RD-3); the row
//   keeps the word's 66 point line box, so nothing else moves.
// - The day row sits 5 below it (H:27): the day leading, the clock and Posted trailing, on
//   the day's baseline (align-items: baseline). The clock (14 x 14, `ink2`, H:30) and
//   Posted are centred on each other, 5 apart (H:29-30), and the pair sits with the clock's
//   bottom edge on the day's baseline: its centre half the clock above it (M1 2.6, as
//   measured on the approved pictures). The clock is the draft's own glyph, a decorative
//   image, so VoiceOver never reads a name for it.
// - The details line, when there is one, sits 6 below the day row, the content's full
//   width, in `ink2`, wrapping if it must (H:33).
//
// VoiceOver reads the whole block as one element: the site's own line for the status
// ("Closed today", the model's `spoken`) in place of the word, then the day, Posted and
// the details (M1 6.1).

import SnowlightCore
import SwiftUI

struct StatusBlock: View {
    let posted: MySchoolModel.Posted

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ShownLabel(posted.word)
                .typeStyle(.statusWord)
                .foregroundStyle(Color.token(.closedHero))
                .accessibilityLabel(posted.spoken.text)
                .padding(.leading, CGFloat(Bands.length(Band.statusLeading)))
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                ShownLabel(posted.day)
                    .typeStyle(.day)
                    .foregroundStyle(Color.token(.ink))
                Spacer(minLength: 0)
                if let time = posted.posted {
                    HStack(alignment: .center, spacing: CGFloat(Bands.length(Band.postedGap))) {
                        GlyphName.clock.decorative
                            .resizable()
                            .frame(width: CGFloat(Bands.length(Band.clock)), height: CGFloat(Bands.length(Band.clock)))
                            .accessibilityHidden(true)
                        ShownLabel(time)
                            .typeStyle(.panelLine)
                    }
                    .foregroundStyle(Color.token(.ink2))
                    .alignmentGuide(.firstTextBaseline) { pair in
                        pair[VerticalAlignment.center] + CGFloat(Bands.length(Band.postedBaseline))
                    }
                }
            }
            .padding(.top, CGFloat(Bands.length(Band.dayGap)))
            if let details = posted.details {
                ShownLabel(details)
                    .typeStyle(.panelLine)
                    .foregroundStyle(Color.token(.ink2))
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, CGFloat(Bands.length(Band.detailsGap)))
            }
        }
        .padding(.top, CGFloat(Bands.length(Band.heroGap)))
        .accessibilityElement(children: .combine)
    }
}
