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

/// A section's heading and, when there is one, the grey line beside it, at the right.
struct SectionHeading: View {
    let title: ShownText
    let aside: ShownText?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            ShownLabel(title)
                .typeStyle(.titleSection)
                .foregroundStyle(Color.token(.ink))
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: 0)
            if let line = aside {
                ShownLabel(line)
                    .typeStyle(.meta)
                    .foregroundStyle(Color.token(.ink2))
            }
        }
    }
}
