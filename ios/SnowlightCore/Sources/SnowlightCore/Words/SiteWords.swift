// The site's fixed words, each beside its key path in web/src/copy.ts (and, for the details
// and the chance's one line, web/src/copy-details.ts and web/src/copy-chance.ts).
//
// Not public: no code outside SnowlightCore can name this table, so a view can never
// reach past its screen model for a word. Tests reach it with `@testable import` and
// compare each word with the site's own, read from the golden files copy.json and
// details.json, which the generator writes by loading the site's own modules.

/// A status's line for today, for tomorrow, and the word that leads a dated day
/// (`copy.statusLine.<status>`).
struct StatusLineWords {
    let today: ShownText
    let tomorrow: ShownText
    let on: ShownText
}

enum SiteWords {
    /// `copy.appName`
    static let appName = ShownText("Snowlight")

    /// `copy.search.placeholder`
    static let searchPlaceholder = ShownText("Search a school, city, or ZIP")

    // Status names: `copy.status.*`.

    /// `copy.status.closed`
    static let statusClosed = ShownText("Closed")
    /// `copy.status.delayed`
    static let statusDelayed = ShownText("Delayed")
    /// `copy.status.remote`
    static let statusRemote = ShownText("Remote")
    /// `copy.status.earlyDismissal`
    static let statusEarlyDismissal = ShownText("Early dismissal")

    /// A status's name (`copy.status[STATUS_KEYS[code]]`).
    static func status(_ status: ClosingStatus) -> ShownText {
        switch status {
        case .closed:
            return statusClosed
        case .delayed:
            return statusDelayed
        case .remote:
            return statusRemote
        case .earlyDismissal:
            return statusEarlyDismissal
        }
    }

    // A school's status line: `copy.statusLine.*.{today, tomorrow, on}`.

    /// `copy.statusLine.closed`
    static let statusLineClosed = StatusLineWords(
        today: ShownText("Closed today"),
        tomorrow: ShownText("Closed tomorrow"),
        on: ShownText("Closed")
    )
    /// `copy.statusLine.delayed`
    static let statusLineDelayed = StatusLineWords(
        today: ShownText("Delayed start today"),
        tomorrow: ShownText("Delayed start tomorrow"),
        on: ShownText("Delayed start")
    )
    /// `copy.statusLine.remote`
    static let statusLineRemote = StatusLineWords(
        today: ShownText("Remote learning today"),
        tomorrow: ShownText("Remote learning tomorrow"),
        on: ShownText("Remote learning")
    )
    /// `copy.statusLine.earlyDismissal`
    static let statusLineEarlyDismissal = StatusLineWords(
        today: ShownText("Early dismissal today"),
        tomorrow: ShownText("Early dismissal tomorrow"),
        on: ShownText("Early dismissal")
    )

    /// A status's line (`copy.statusLine[STATUS_KEYS[code]]`).
    static func statusLine(_ status: ClosingStatus) -> StatusLineWords {
        switch status {
        case .closed:
            return statusLineClosed
        case .delayed:
            return statusLineDelayed
        case .remote:
            return statusLineRemote
        case .earlyDismissal:
            return statusLineEarlyDismissal
        }
    }

    /// `copy.days.today`
    static let daysToday = ShownText("Today")
    /// `copy.days.tomorrow`
    static let daysTomorrow = ShownText("Tomorrow")

    /// `copy.live.updated`
    static let liveUpdated = ShownText("Updated")
    /// `copy.live.offline`
    static let liveOffline = ShownText("Offline")

    /// `copy.nav.live`
    static let navLive = ShownText("Live")

    /// `copy.detail.posted`
    static let detailPosted = ShownText("Posted")
    /// `copy.detail.confirmed`
    static let detailConfirmed = ShownText("Confirmed by our team")

    /// `chanceCopy.noSchool` (copy-chance.ts)
    static let chanceNoSchool = ShownText("Chance of no school")

    /// `detailsCopy.said.*` (copy-details.ts), one sentence per detail code, in code order
    /// (the generated `Detail` codes 0 to 21).
    static let detailSentences: [ShownText] = [
        // 0 students_and_staff
        ShownText("Students and staff."),
        // 1 staff_report
        ShownText("Staff report, students stay home."),
        // 2 staff_late
        ShownText("Staff report late."),
        // 3 buses_snow_routes
        ShownText("Buses run snow routes."),
        // 4 buses_emergency_routes
        ShownText("Buses run emergency routes."),
        // 5 buses_paved_roads
        ShownText("Buses run on paved roads only."),
        // 6 buses_limited
        ShownText("Buses run limited routes."),
        // 7 no_buses
        ShownText("No buses."),
        // 8 no_breakfast
        ShownText("No breakfast."),
        // 9 no_lunch
        ShownText("No lunch."),
        // 10 no_hot_lunch
        ShownText("No hot lunch."),
        // 11 grab_and_go
        ShownText("Grab-and-go meals."),
        // 12 no_am_prek
        ShownText("No morning pre-K."),
        // 13 no_pm_prek
        ShownText("No afternoon pre-K."),
        // 14 no_prek
        ShownText("No pre-K."),
        // 15 activities_cancelled
        ShownText("Activities cancelled."),
        // 16 after_school_cancelled
        ShownText("After-school activities cancelled."),
        // 17 evening_cancelled
        ShownText("Evening activities cancelled."),
        // 18 childcare_closed
        ShownText("Childcare closed."),
        // 19 childcare_open
        ShownText("Childcare open."),
        // 20 offices_closed
        ShownText("Offices closed."),
        // 21 offices_open
        ShownText("Offices open."),
    ]
}
