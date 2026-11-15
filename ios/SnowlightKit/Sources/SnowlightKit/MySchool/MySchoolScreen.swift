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
// Between the map and the scroll view lies the panel's ground once more, `sheet` in the
// panel's own outline from its top edge to the window's bottom edge (lead ruling R21, B2):
// the system's scroll edge effect under the tab bar (RD-16) dissolves the panel onto what
// lies behind the scroll view, and so onto the sheet's color, as the draft draws it (rows 8
// and 16d), never onto the map's ground.
//
// The places are from the window's top leading corner, so the screen lays itself out over
// the whole window and sets the safe area's insets itself: the content keeps inside the
// safe area, and its bottom keeps clear of the tab bar when it scrolls. A view laid out over
// the whole window sees no safe area (run 43656288039: its reader gave insets of 0, and the
// panel rested 83 points low), so the insets come from the frame of a view that keeps to
// the safe area: on the iPhone 17 Pro, 62 at the top and 83 at the bottom, the tab bar's.
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
    /// The safe area, in the window's points: measured by a view that keeps to it.
    @State private var safe = CGRect.zero

    var body: some View {
        ZStack(alignment: .topLeading) {
            // A view of no look that keeps to the safe area, so its frame in the window is
            // the safe area's: the screen below lays itself out over the whole window, where
            // no safe area is seen, and takes its insets from this.
            Color.clear
                .accessibilityHidden(true)
                .onGeometryChange(for: CGRect.self) { room in
                    room.frame(in: .global)
                } action: { rect in
                    safe = rect
                }
            GeometryReader { window in
                let insets = MySchoolScreen.insets(of: safe, in: window.size)
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
                        .onChange(of: place, initial: true) {
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
    }

    /// The safe area's insets in a window of this size, from the safe area's frame in it;
    /// none until that frame is measured.
    private static func insets(of safe: CGRect, in window: CGSize) -> EdgeInsets {
        if safe.width <= 0 || safe.height <= 0 {
            return EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0)
        }
        return EdgeInsets(
            top: safe.minY,
            leading: safe.minX,
            bottom: max(0, window.height - safe.maxY),
            trailing: max(0, window.width - safe.maxX)
        )
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
            MySchoolScreen.panelBacking()
                .frame(width: width, height: max(0, size.height - rest))
                .padding(.top, rest)
            ScrollView(.vertical) {
                // Leading: the panel starts at the window's leading edge on every shape. Beside
                // the map it is narrower than the window and would sit centred otherwise.
                VStack(alignment: .leading, spacing: 0) {
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

    /// The panel's ground behind the scroll view (R21, B2): `sheet` in the panel's outline,
    /// its two top corners rounded (CSS:220, border-radius: 38px 38px 0 0). A drawing only.
    private static func panelBacking() -> some View {
        let corner = CGFloat(Bands.length(Band.panelCorner))
        return UnevenRoundedRectangle(
            topLeadingRadius: corner,
            bottomLeadingRadius: 0,
            bottomTrailingRadius: 0,
            topTrailingRadius: corner,
            style: RoundedCornerStyle.circular
        )
        .fill(Color.token(.sheet))
        .accessibilityHidden(true)
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
