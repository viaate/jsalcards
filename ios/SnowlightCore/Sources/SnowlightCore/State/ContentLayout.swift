// The layout rules every screen follows, as values the views read.
//
// A screen is laid out from the room its window gives it and the system's width class,
// never from the device, its idiom, its orientation or its screen. The same app runs on
// an iPhone 17 Pro (402 pt wide), on the iPhone Duo closed (466 pt, of which the system's
// own controls take an 84 pt column on the right) and on the Duo open (951 pt on its
// side), and folding or unfolding the Duo changes the room while the app runs. So the
// layout is a plain function of that room, asked again whenever the room changes, and it
// keeps nothing from one answer to the next.
//
// The kit holds every screen's content to a readable column (`readableLimit`) and lays it
// out inside the safe area, so the content stops where the system's controls begin. The
// width class picks one column or two: one on an iPhone and on the closed Duo (compact),
// two on the open Duo (regular), the owner's two panes. Nothing draws two columns yet.

/// The system's width class, as the screens use it.
public enum WidthClass: Equatable, Hashable, Sendable, CaseIterable {
    /// An iPhone, and the iPhone Duo closed.
    case compact
    /// The iPhone Duo open.
    case regular
}

/// How many columns a screen lays its content out in.
public enum Columns: Equatable, Hashable, Sendable, CaseIterable {
    case one
    case two
}

/// The layout of a screen for the room it is given.
public struct ContentLayout: Equatable, Hashable, Sendable {
    /// One column on a compact width, two on a regular width.
    public let columns: Columns
    /// The width of the content of a one-column screen: the room inside the two side
    /// margins, never wider than `readableLimit` and never below zero.
    public let readableWidth: Double

    /// The side margin of a page, each side, in points (draft 3's 20).
    public static let sideMargin: Double = 20

    /// The widest a column of content may run, in points: the width of the system's
    /// readable content guide at the standard text size. On every iPhone, and on the
    /// closed Duo, the room is narrower and this never applies.
    public static let readableLimit: Double = 672

    /// The layout for a room `room` points wide (the window's width less the safe area's
    /// left and right insets) and the system's width class.
    public init(room: Double, widthClass: WidthClass) {
        switch widthClass {
        case .compact:
            columns = Columns.one
        case .regular:
            columns = Columns.two
        }
        let inside = room - 2 * ContentLayout.sideMargin
        readableWidth = min(ContentLayout.readableLimit, max(0, inside))
    }
}
