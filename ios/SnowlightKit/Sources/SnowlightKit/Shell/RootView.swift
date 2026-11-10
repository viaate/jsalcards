// The app's root view.
//
// It draws its screen model and nothing else. A view never names a word table (they are
// not public, so the compiler refuses) and holds no text in quotes.

import SnowlightCore
import SwiftUI

/// The root of the app. For now it draws one field of the shell's model: the app's name.
public struct RootView: View {
    private let model: ShellModel

    public init() {
        model = ShellModel()
    }

    public var body: some View {
        // In debug builds the picture tour (Tour/) watches the screen appear, so that it
        // can write the words of this model for the picture being taken. A release build
        // holds none of it.
        #if DEBUG
        screen.modifier(TourStage(model: model))
        #else
        screen
        #endif
    }

    private var screen: some View {
        ShownLabel(model.appName)
    }
}
