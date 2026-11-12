// The Settings screen: its title, the Appearance section and, on an iPhone Duo only, the
// Outside screen section right under it.
//
// Every word on it is a field of the screen's model. Its content keeps to the readable
// column (Layout/ReadableColumn.swift). The Outside screen section is drawn as Appearance
// is: the same heading and grey line beside it, the same tiles, ring and tick. It exists
// only when the model has it, so on any other iPhone Settings is as it was.

import SnowlightCore
import SwiftUI

struct SettingsScreen: View {
    let model: SettingsModel
    /// Called with the appearance tile that was tapped.
    let choose: (AppearanceChoice) -> Void
    /// Called with the Outside screen tile that was tapped.
    let chooseOutsideScreen: (OutsideScreenChoice) -> Void

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.token(.page)
                .ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                PageTitle(model.title)
                SectionHeading(title: model.heading, aside: model.followsPhone)
                    .padding(.horizontal, 20)
                    .padding(.top, 24)
                AppearanceTiles(options: model.options, choose: choose)
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                if let row = model.outsideScreen {
                    // Draft 3's gap between two sections (13 points), then the same
                    // heading and tiles as Appearance.
                    SectionHeading(title: row.heading, aside: row.aside)
                        .padding(.horizontal, 20)
                        .padding(.top, 13)
                    OutsideScreenTiles(options: row.options, choose: chooseOutsideScreen)
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                }
            }
            .readableColumn()
        }
    }
}

/// A section's heading and, when there is one, the grey line beside it, at the right, on
/// one line as the draft draws them, both at full size: the line in the `meta` style, with
/// the draft's -0.2 tracking. The gap between the two is at least 12 points and otherwise
/// whatever is left, as the draft's row spreads them apart. (Run 43192616125 broke the
/// Outside screen row's line in two on the closed Duo: the stack's own spacing then stood
/// on both sides of the spacer, 24 points, and the line had no tracking.) The line is
/// never made smaller; if it ever does not fit, it ends in an ellipsis on one line, for a
/// person to see in the pictures.
struct SectionHeading: View {
    let title: ShownText
    let aside: ShownText?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            ShownLabel(title)
                .typeStyle(.titleSection)
                .foregroundStyle(Color.token(.ink))
                .accessibilityAddTraits(.isHeader)
                .layoutPriority(1)
            Spacer(minLength: 12)
            if let line = aside {
                ShownLabel(line)
                    .typeStyle(.meta)
                    .foregroundStyle(Color.token(.ink2))
                    .lineLimit(1)
            }
        }
    }
}
