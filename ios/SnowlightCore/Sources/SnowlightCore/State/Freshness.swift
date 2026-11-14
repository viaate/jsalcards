import Foundation

// The update line for a data file, and whether it calls the file live
// (web/src/state/freshness.ts `updateState`). The time on the line is always the file's own
// generated_at. The clock decides two things only: whether the file is recent enough to
// call live, and whether the line needs a day because the file is from another day.
//
// The clock, the viewer's zone and how long the app has held the file are parameters: the
// line is told on the viewer's clock.

/// How long after its generated_at a live file still counts as live while the app is
/// online (`LIVE_FRESH_MS`).
let liveFreshMs: Int64 = 20 * minuteMs

/// How far ahead of the viewer's clock a live file's generated_at may be and still count as
/// live (`LIVE_LEAD_MS`). The site allows it only in a build that reads its closings file
/// from a live root, and the app reads from the live root, as the deployed site does.
let liveLeadMs: Int64 = 2 * minuteMs

/// The update line, and whether it calls the file live (freshness.ts `UpdateState`).
struct UpdateState: Equatable {
    let text: ShownText
    let live: Bool
}

/// "Live · 6:42 AM", "Updated 6:42 AM" or "Offline · Updated 6:42 AM", with the day added
/// when the file is from another day; nil when `generatedAt` is not an instant, so nothing
/// false is shown (freshness.ts `updateState`). A file held longer than `liveWithinMs` is no
/// longer live, whatever the clock says of its age. It throws where the site's does: for a
/// viewer's zone with no clock.
func updateState(generatedAt: String, online: Bool, zone: String, now: Int64, heldMs: Int64 = 0, liveWithinMs: Int64 = liveFreshMs) throws -> UpdateState? {
    guard let generated = parseInstant(generatedAt) else {
        return nil
    }
    if !online {
        let text = try SiteFormat.offline(generated, zone: zone, now: now)
        return UpdateState(text: text, live: false)
    }
    let age = now - generated
    if age >= -liveLeadMs && age <= liveWithinMs && heldMs <= liveWithinMs {
        let text = try SiteFormat.liveAt(generated, zone: zone)
        return UpdateState(text: text, live: true)
    }
    let text = try SiteFormat.updatedAt(generated, zone: zone, now: now)
    return UpdateState(text: text, live: false)
}
