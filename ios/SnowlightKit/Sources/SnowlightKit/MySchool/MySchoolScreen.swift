// My School: the school's panel over the map, as approved draft 3 draws "My School, closed"
// (design/app/premium/d3t/myschool-closed-light.html and its details form), band for band.
// Each length is a band of SnowlightCore's Bands.swift, each color a token or a line of its
// Shadows.swift, each word a ShownText of the screen's model (MySchoolModel). The parts the
// app cannot draw yet are left out, each as the lead ruled it (M1 section 3): the map
// picture, the snowfall, the weather, the crests, the share button, the chance card and the
// season card's strip.
//
// The screen is laid out from the room the window gives and nothing about the device
// (README rule 10). From that room, the kept Outside screen choice and the width class,
// SnowlightCore's PanelPlace gives the panel's rest, the marker's place, the margins, the
// grabber and the callout's limits (M1 2.0). Behind everything is the map's window, the
// one full-bleed surface; over it the system's own scroll view holds the panel, which
// rests where the draft draws it and runs on to the window's bottom edge under the tab
// bar. The content never fills the room at the standard text size, so the scroll view does
// not move (`.scrollBounceBehavior(.basedOnSize)`); at larger sizes it scrolls (RD-22).
//
// The places are from the window's top leading corner, so the screen lays itself out over
// the whole window and sets the safe area's insets itself: the content keeps inside the
// safe area, and its bottom keeps clear of the tab bar when it scrolls.
//
// In M1 the screen is shown only when the debug tour hands it a model (Shell/RootView.swift);
// where the draft draws no place for the panel (Under the controls with details known,
// RD-19) the tab is the plain one, as on every other launch.

import SnowlightCore
import SwiftUI

struct MySchoolScreen: View {
    let model: MySchoolModel
    /// The plain tab, shown where the draft draws no place for the panel.
    let plain: PlainScreenModel

    @Environment(\.outsideScreen) private var outsideScreen
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        GeometryReader { window in
            let insets = window.safeAreaInsets
            let shape = panelShape(outsideScreen: outsideScreen, widthClass: widthClass)
            if let place = panelPlace(
                shape: shape,
                details: model.rest == MySchoolModel.PanelRest.details,
                windowHeight: Double(window.size.height),
                bottomInset: Double(insets.bottom),
                safeWidth: Double(window.size.width - insets.leading - insets.trailing)
            ) {
                drawn(place: place, shape: shape, size: window.size, insets: insets)
                #if DEBUG
                    .onAppear {
                        Tour.notePanel(window: window.size, insets: insets, shape: shape, place: place)
                    }
                #endif
            } else {
                // The plain tab, given back the safe area this screen lays itself out over.
                EmptyTab(model: plain)
                    .safeAreaPadding(insets)
            }
        }
        .ignoresSafeArea()
    }

    private var widthClass: WidthClass {
        sizeClass == .regular ? WidthClass.regular : WidthClass.compact
    }

    /// The posted status the panel draws, or nil: in M1 only a closing is drawn.
    private var closing: MySchoolModel.Posted? {
        if case .posted(let posted) = model.lead, posted.status == StatusKey.closed {
            return posted
        }
        return nil
    }

    private func drawn(place: PanelPlace, shape: PanelShape, size: CGSize, insets: EdgeInsets) -> some View {
        let rest = CGFloat(place.rest)
        // The panel's ground stops at the side column Beside the map, and runs on under it
        // everywhere else (M1 2.5, D8); its content keeps inside the safe area either way.
        let width = shape == PanelShape.outsideBeside ? size.width - insets.trailing : size.width
        let trailing = width - (size.width - insets.trailing) + CGFloat(place.trailing)
        return ZStack(alignment: .topLeading) {
            MapWindow(place: place, callout: model.callout, marked: closing != nil)
            ScrollView(.vertical) {
                VStack(spacing: 0) {
                    Color.clear
                        .frame(height: rest)
                        .accessibilityHidden(true)
                    Panel(width: width, minHeight: size.height - rest, grabberCentre: CGFloat(place.grabberCentre)) {
                        content
                            .padding(.top, CGFloat(Bands.length(Band.contentTop)))
                            .padding(.leading, insets.leading + CGFloat(place.margin))
                            .padding(.trailing, trailing)
                            .padding(.bottom, insets.bottom)
                    }
                }
                .frame(width: size.width, alignment: .topLeading)
            }
            .scrollBounceBehavior(.basedOnSize)
            .ignoresSafeArea()
        }
    }

    /// The panel's content, top to bottom (M1 2.6).
    private var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            SchoolHeader(header: model.header)
            if let posted = closing {
                StatusBlock(posted: posted)
            }
            if let season = model.season {
                SeasonCard(season: season)
                    .padding(.top, CGFloat(Bands.length(cardGap)))
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    /// The gap above the season card: 17 under the day row, 14 under the details line.
    private var cardGap: Band {
        closing?.details == nil ? Band.cardGap : Band.cardGapAfterDetails
    }
}
