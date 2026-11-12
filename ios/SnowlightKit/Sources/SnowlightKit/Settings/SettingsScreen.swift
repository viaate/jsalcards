// The Settings screen: its title and one section, Appearance.
//
// Every word on it is a field of the screen's model. Its content keeps to the readable
// column (Layout/ReadableColumn.swift).

import SnowlightCore
import SwiftUI

struct SettingsScreen: View {
    let model: SettingsModel
    /// Called with the tile that was tapped.
    let choose: (AppearanceChoice) -> Void

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.token(.page)
                .ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                PageTitle(model.title)
                heading
                    .padding(.horizontal, 20)
                    .padding(.top, 24)
                AppearanceTiles(options: model.options, choose: choose)
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
            }
            .readableColumn()
        }
    }

    /// The section's heading and, while System is chosen, the line beside it.
    private var heading: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            ShownLabel(model.heading)
                .typeStyle(.titleSection)
                .foregroundStyle(Color.token(.ink))
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: 0)
            if let line = model.followsPhone {
                ShownLabel(line)
                    .typeStyle(.meta)
                    .foregroundStyle(Color.token(.ink2))
            }
        }
    }
}
