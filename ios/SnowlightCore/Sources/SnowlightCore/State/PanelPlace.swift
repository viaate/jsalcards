// Where My School's panel rests over the map, and where the school's marker, the grabber
// and the callout go, from the room the window gives and nothing about the device.
//
// The inputs are what a view knows: the window's height, the bottom inset the content
// reports, the safe area's width, the kept Outside screen choice (nil on any phone with no
// outside screen) and the system's width class. From the last two comes the panel's shape,
// as `sideControls` comes from them (OutsideScreen.swift).
//
// The rule is the build spec's (2.0; RD-11 as the lead ruled it: the panel rests where
// approved draft 3 draws it). The room's bottom is the tab bar's top when the tab bar runs
// along the bottom, and the window's bottom on the closed Duo, whose mock-ups end their
// content a drawn gap above the 678 pt edge. The panel rests the draft's full content and
// its drawn gap above that bottom, and the school's dot sits the drawn height above the
// panel's rest. Every number is a length of Bands.swift.

/// How the panel meets the system's controls.
public enum PanelShape: Equatable, Hashable, Sendable, CaseIterable {
    /// The tab bar runs along the bottom: every iPhone, and the open Duo (not drawn in M1).
    case bottomBar
    /// The closed Duo, Beside the map (A): the panel stops where the system's side column begins.
    case outsideBeside
    /// The closed Duo, Under the controls (B): the panel's ground runs on under the column.
    case outsideUnder
}

/// The panel's shape for a phone. `outsideScreen` is the kept choice on a phone with an
/// outside screen and nil on any other phone; `widthClass` is the window's.
public func panelShape(outsideScreen: OutsideScreenChoice?, widthClass: WidthClass) -> PanelShape {
    guard let choice = outsideScreen else {
        return PanelShape.bottomBar
    }
    switch widthClass {
    case .regular:
        return PanelShape.bottomBar
    case .compact:
        switch choice {
        case .besideTheMap:
            return PanelShape.outsideBeside
        case .underTheControls:
            return PanelShape.outsideUnder
        }
    }
}

/// The panel's place in a room, in points.
public struct PanelPlace: Equatable, Sendable {
    /// The panel's top edge, from the window's top.
    public let rest: Double
    /// The school's dot, from the window's leading edge.
    public let markerX: Double
    /// The school's dot, from the window's top.
    public let markerY: Double
    /// The content's leading inset inside the safe area.
    public let margin: Double
    /// The content's trailing inset inside the safe area.
    public let trailing: Double
    /// The grabber's centre, from the window's leading edge.
    public let grabberCentre: Double
    /// The callout is kept inside [calloutFrom, calloutTo], from the window's leading edge.
    public let calloutFrom: Double
    public let calloutTo: Double
}

/// The panel's place for a shape, with the details line shown or not, in a window
/// `windowHeight` high whose content reports `bottomInset` at its bottom and whose safe
/// area is `safeWidth` wide. Nil where the draft draws no place: Under the controls with
/// details known (RD-19).
public func panelPlace(shape: PanelShape, details: Bool, windowHeight: Double, bottomInset: Double,
                       safeWidth: Double) -> PanelPlace? {
    let roomBottom: Double
    let gap: Band
    let markerAboveRest: Band
    let margin: Double
    switch shape {
    case .bottomBar:
        roomBottom = windowHeight - bottomInset
        gap = details ? Band.gapBottomBarDetails : Band.gapBottomBarStatusOnly
        markerAboveRest = details ? Band.markerAboveRestBottomBarDetails : Band.markerAboveRestBottomBarStatusOnly
        margin = Bands.length(Band.marginBottomBar)
    case .outsideBeside:
        roomBottom = windowHeight
        gap = details ? Band.gapBesideDetails : Band.gapBesideStatusOnly
        markerAboveRest = details ? Band.markerAboveRestBesideDetails : Band.markerAboveRestBesideStatusOnly
        margin = Bands.length(Band.marginOutside)
    case .outsideUnder:
        if details {
            return nil
        }
        roomBottom = windowHeight
        gap = Band.gapUnderStatusOnly
        markerAboveRest = Band.markerAboveRestUnderStatusOnly
        margin = Bands.length(Band.marginOutside)
    }
    let content = details ? Bands.length(Band.draftContentDetails) : Bands.length(Band.draftContentStatusOnly)
    let rest = roomBottom - (content + Bands.length(gap))
    let edge = Bands.length(Band.calloutEdge)
    return PanelPlace(
        rest: rest,
        markerX: Bands.length(Band.markerX),
        markerY: rest - Bands.length(markerAboveRest),
        margin: margin,
        trailing: margin,
        grabberCentre: safeWidth / 2,
        calloutFrom: edge,
        calloutTo: safeWidth - edge
    )
}
