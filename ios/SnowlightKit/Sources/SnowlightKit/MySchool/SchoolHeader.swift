// The top of My School's panel: the district line in a row of its own, then the school's
// name (approved draft 3: myschool-closed-light.html:17-20 and :72-77; d3t/app.css:276-277).
//
// The draft's row holds the school's crest, the district line and the share button; the
// row is 36 high, set by the round share button (CSS:292). With the crest left out (RD-4,
// as the lead ruled on SPEC r4: the line starts at the content's edge) and share left out
// until M7 (RD-12 (b)), the row holds the district line alone, and keeps its 36 points so
// that every band below sits where the draft puts it (DUO:70-71, the Duo mock-up's own
// ruling). The line is centred on the row (align-items: center), in `ink2`, and wraps if
// it must. The name sits 9 below the row, in `ink`; VoiceOver reads it as a heading.

import SnowlightCore
import SwiftUI

struct SchoolHeader: View {
    let header: MySchoolModel.Header

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                ShownLabel(header.districtLine)
                    .typeStyle(.panelLine)
                    .foregroundStyle(Color.token(.ink2))
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .frame(minHeight: CGFloat(Bands.length(Band.topRow)))
            if let name = header.name {
                ShownLabel(name)
                    .typeStyle(.schoolName)
                    .foregroundStyle(Color.token(.ink))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                    .padding(.top, CGFloat(Bands.length(Band.nameGap)))
            }
        }
    }
}
