// Every length of My School's drawing, in points, as approved draft 3 draws it.
//
// This table is the only place such a length is written. The views read it, and
// PanelPlace.swift builds the panel's place from it; no view holds a length of its own.
//
// The values are approved draft 3's: its My School page (design/app/premium/d3t/
// myschool-closed-light.html, "H" below; the details form "HD" is H with one more line),
// its style sheet (d3t/app.css, "CSS") and script (d3t/app.js, "JS"), and the iPhone Duo
// mock-ups drawn from it (design/app/duo/html/closed-myschool-light.html "DUO",
// closed-details-light.html "DUOD", closed-myschool-under-light.html "DUOB", duo.js "DJS"),
// each with its line beside it. The draft's full content heights are summed from those
// lines by the build spec's bands.mjs (bands.out). Only what M1 draws is here: the parts
// the build spec leaves out (the map picture, the snowfall, the weather, the crests, the
// share button, the chance card, the season strip) bring their lengths when they are
// drawn. Type sizes and tracking are the kit's type styles; a line's height (its CSS line
// box) is here, since the bands are stacked from it. The shadows' lengths stay with the
// shadows, in Shadows.swift.

/// The names of the lengths.
public enum Band: Equatable, Hashable, Sendable, CaseIterable {
    // The map window.

    /// The fade at the window's top: 90 high, the full width. CSS:219.
    case topFade
    /// The school marker's core: 16 round. CSS:226.
    case markerCore
    /// The school's dot, from the window's leading edge, on every shape. H:156, DUO:174, DUOB:187.
    case markerX
    /// The stem's width. CSS:228.
    case stemWidth
    /// How far above the dot the stem starts and the callout's bottom sits (`lift: 30`). JS:158, :166, :185.
    case calloutLift
    /// Where the stem stops above the dot in the light look. JS:165.
    case stemEndLight
    /// Where the stem stops above the dot in the dark look. JS:165.
    case stemEndDark
    /// The callout's height. CSS:240.
    case calloutHeight
    /// The callout's corner radius. CSS:240.
    case calloutRadius
    /// The gap between the callout's name and its chip. CSS:240.
    case calloutGap
    /// The callout's leading padding with no crest. JS:178.
    case calloutLeading
    /// The callout's trailing padding. CSS:240.
    case calloutTrailing
    /// The padding after the name in the callout. CSS:243.
    case calloutNameTrailing
    /// The chip's height. CSS:244.
    case chipHeight
    /// The chip's corner radius. CSS:244.
    case chipRadius
    /// The chip's padding on each side. CSS:244.
    case chipPadding
    /// How far the callout is kept from the edges of the map's area. JS:183; DJS:155-164.
    case calloutEdge

    // The panel.

    /// The panel's top corner radius. CSS:220.
    case panelCorner
    /// How far down the dark panel's gradient runs, from its top color to `sheet`. CSS:222.
    case sheetGradient
    /// The grabber's width. CSS:221.
    case grabberWidth
    /// The grabber's height. CSS:221.
    case grabberHeight
    /// The grabber's corner radius. CSS:221.
    case grabberRadius
    /// The grabber's distance below the panel's top. CSS:221.
    case grabberTop
    /// The content's inset from the panel's top. H:16.
    case contentTop
    /// The content's leading and trailing inset where the tab bar runs along the bottom. H:16.
    case marginBottomBar
    /// The content's leading and trailing inset on the closed Duo, both layouts. DUO:76; DUOD:81; DUOB:82, :86.
    case marginOutside
    /// The top row's height, kept with nothing in it to set it. H:17, CSS:292 (the 36 round
    /// button sets it in the draft); DUO:71.
    case topRow
    /// The district line's line box. CSS:277.
    case districtLine
    /// The gap above the school's name. H:20.
    case nameGap
    /// The school name's line box. CSS:276.
    case nameLine
    /// The gap above the hero row. H:21.
    case heroGap
    /// The status word's line box. H:22.
    case statusLine
    /// The status word's leading offset from the content's edge. H:22.
    case statusLeading
    /// The gap above the day row. H:27.
    case dayGap
    /// The day's line box. H:28.
    case dayLine
    /// The clock glyph's size. H:30.
    case clock
    /// The gap between the clock and Posted. H:29.
    case postedGap
    /// Posted's line box. H:29.
    case postedLine
    /// How far the clock-and-Posted pair's centre sits above the day's baseline: half the
    /// clock, whose bottom edge is on the baseline. H:30.
    case postedBaseline
    /// The gap above the details line. H:33.
    case detailsGap
    /// The details line's line box. H:33.
    case detailsLine
    /// The gap above the season card, under the day row. H:36.
    case cardGap
    /// The gap above the season card, under the details line. H:38.
    case cardGapAfterDetails
    /// The season card's corner radius. H:36.
    case cardRadius
    /// The season card's top padding. H:36.
    case cardTop
    /// The season card's padding on each side. H:36.
    case cardSide
    /// The season card's bottom padding. H:36.
    case cardBottom
    /// The card key's line box. H:39.
    case keyLine
    /// The gap above the counts line. H:58.
    case countsGap
    /// The counts line's line box. H:58.
    case countsLine

    // Where the panel rests (build spec 2.0 and 2.7; RD-11 as ruled).

    /// The draft's chance card, all of it. bands.out (H:43-55, :88-96).
    case draftChanceCard
    /// The draft's season card with its strip and month names. bands.out (H:36, :39, :58-62, :98-103).
    case draftSeasonCard
    /// The gap between the draft's two cards. H:37.
    case draftCardToCard
    /// The draft's content, status only. bands.out.
    case draftContentStatusOnly
    /// The draft's content, details known. bands.out.
    case draftContentDetails
    /// The gap the draft leaves under its content above the tab bar, status only: 791 - 260 - 517. H:14.
    case gapBottomBarStatusOnly
    /// The same, details known: 791 - 240 - 540. H:15.
    case gapBottomBarDetails
    /// The gap above the closed Duo's bottom edge, Beside the map, status only: 678 - 140 - 517. DUO:68.
    case gapBesideStatusOnly
    /// The same, details known: 678 - 114 - 540. DUOD:77.
    case gapBesideDetails
    /// The gap above the closed Duo's bottom edge, Under the controls, status only: 678 - 134 - 517. DUOB:72.
    case gapUnderStatusOnly
    /// The school's dot above the panel's rest, tab bar along the bottom, status only: 260 - 151. H:14, :108, :156.
    case markerAboveRestBottomBarStatusOnly
    /// The same, details known: 240 - 140. H:15, :108, :156.
    case markerAboveRestBottomBarDetails
    /// The same on the closed Duo, Beside the map, status only: 140 - 87. DUO:68, :125.
    case markerAboveRestBesideStatusOnly
    /// The same, details known: 114 - 84. DUOD:77, :131.
    case markerAboveRestBesideDetails
    /// The same, Under the controls, status only: 134 - 85. DUOB:72, :135.
    case markerAboveRestUnderStatusOnly
}

/// The table.
public enum Bands {
    /// The length, in points.
    public static func length(_ band: Band) -> Double {
        switch band {
        case .topFade:
            return 90 // CSS:219 .mapfade { height: 90px }
        case .markerCore:
            return 16 // CSS:226 .mk .core { width: 16px; height: 16px; border-radius: 8px }
        case .markerX:
            return 175 // H:156 pin({ x: 175 }); DUO:174, DUOB:187 pinIn({ x: 175 })
        case .stemWidth:
            return 1 // CSS:228 .mk .stem { width: 1px }
        case .calloutLift:
            return 30 // JS:158 lift: 30; the stem from -o.lift (JS:166), the callout at o.y - o.lift - h (JS:185)
        case .stemEndLight:
            return 11.5 // JS:165 stemFrom = DARK ? 11 : 11.5
        case .stemEndDark:
            return 11 // JS:165
        case .calloutHeight:
            return 38 // CSS:240 .callout { height: 38px }
        case .calloutRadius:
            return 19 // CSS:240 border-radius: 19px
        case .calloutGap:
            return 8 // CSS:240 gap: 8px
        case .calloutLeading:
            return 14 // JS:178 if (!o.crestOn) co.style.paddingLeft = '14px'
        case .calloutTrailing:
            return 5 // CSS:240 padding: 0 5px 0 5px
        case .calloutNameTrailing:
            return 1 // CSS:243 .callout .nm { padding-right: 1px }
        case .chipHeight:
            return 26 // CSS:244 .chip { height: 26px }
        case .chipRadius:
            return 13 // CSS:244 border-radius: 13px
        case .chipPadding:
            return 10 // CSS:244 padding: 0 10px
        case .calloutEdge:
            return 16 // JS:183 Math.max(16, Math.min(402 - 16 - w, left)); DJS:155-164 pinIn
        case .panelCorner:
            return 38 // CSS:220 .sheet { border-radius: 38px 38px 0 0 }
        case .sheetGradient:
            return 120 // CSS:222 linear-gradient(180deg, #202127 0, var(--sheet) 120px)
        case .grabberWidth:
            return 36 // CSS:221 .sheet .grab { width: 36px }
        case .grabberHeight:
            return 5 // CSS:221 height: 5px
        case .grabberRadius:
            return 3 // CSS:221 border-radius: 3px
        case .grabberTop:
            return 7 // CSS:221 top: 7px
        case .contentTop:
            return 22 // H:16 .inner { padding: 22px 20px 0 }
        case .marginBottomBar:
            return 20 // H:16
        case .marginOutside:
            return 16 // DUO:76 .inner { padding-left: 16px; padding-right: 16px }; DUOD:81; DUOB:82 (S + 16px), :86
        case .topRow:
            return 36 // H:17 .toprow, set by CSS:292 .btn-round { height: 36px }; DUO:71 .toprow { min-height: 36px }
        case .districtLine:
            return 20 // CSS:277 .meta { font: 400 15px/20px }
        case .nameGap:
            return 9 // H:20 .schoolname { margin-top: 9px }
        case .nameLine:
            return 27 // CSS:276 .schoolname { font: 700 22px/27px }
        case .heroGap:
            return 8 // H:21 .hero { margin-top: 8px }
        case .statusLine:
            return 66 // H:22 .status { font: 700 68px/66px }
        case .statusLeading:
            return -3 // H:22 margin-left: -3px
        case .dayGap:
            return 5 // H:27 .dayrow { margin-top: 5px }
        case .dayLine:
            return 25 // H:28 .day { font: 600 20px/25px }
        case .clock:
            return 14 // H:30 .posted i { width: 14px; height: 14px }
        case .postedGap:
            return 5 // H:29 .posted { gap: 5px }
        case .postedLine:
            return 20 // H:29 font: 400 15px/20px
        case .postedBaseline:
            return 7 // H:30: half of the clock's 14
        case .detailsGap:
            return 6 // H:33 .details { margin-top: 6px }
        case .detailsLine:
            return 20 // H:33 font: 400 15px/20px
        case .cardGap:
            return 17 // H:36 .mod { margin-top: 17px }
        case .cardGapAfterDetails:
            return 14 // H:38 body.known .details + .mod { margin-top: 14px }
        case .cardRadius:
            return 20 // H:36 border-radius: 20px
        case .cardTop:
            return 13 // H:36 padding: 13px 16px 14px
        case .cardSide:
            return 16 // H:36
        case .cardBottom:
            return 14 // H:36
        case .keyLine:
            return 15 // H:39 .mod .k { font: 600 12px/15px }
        case .countsGap:
            return 8 // H:58 .yr { margin-top: 8px }
        case .countsLine:
            return 22 // H:58 font: 600 17px/22px
        case .draftChanceCard:
            return 166 // bands.out chance: 166
        case .draftSeasonCard:
            return 126 // bands.out season: 126
        case .draftCardToCard:
            return 10 // H:37 .mod + .mod { margin-top: 10px }
        case .draftContentStatusOnly:
            return 517 // bands.out statusOnly: 517
        case .draftContentDetails:
            return 540 // bands.out details: 540
        case .gapBottomBarStatusOnly:
            return 14 // H:14 .sheet { top: 260px }: 791 - 260 - 517
        case .gapBottomBarDetails:
            return 11 // H:15 body.known .sheet { top: 240px }: 791 - 240 - 540
        case .gapBesideStatusOnly:
            return 21 // DUO:68 .sheet { top: 140px }: 678 - 140 - 517
        case .gapBesideDetails:
            return 24 // DUOD:77 body.known .sheet { top: 114px }: 678 - 114 - 540
        case .gapUnderStatusOnly:
            return 27 // DUOB:72 .sheet { top: 134px }: 678 - 134 - 517
        case .markerAboveRestBottomBarStatusOnly:
            return 109 // H:14 (260), H:108 and :156 (147 + 4 = 151)
        case .markerAboveRestBottomBarDetails:
            return 100 // H:15 (240), H:108 and :156 (147 - 7 = 140)
        case .markerAboveRestBesideStatusOnly:
            return 53 // DUO:68 (140), DUO:125 (PY = 87)
        case .markerAboveRestBesideDetails:
            return 30 // DUOD:77 (114), DUOD:131 (PY = 84)
        case .markerAboveRestUnderStatusOnly:
            return 49 // DUOB:72 (134), DUOB:135 (PY = 85)
        }
    }

    /// Where the stem stops above the dot in a look. JS:165.
    public static func stemEnd(in look: ResolvedAppearance) -> Double {
        switch look {
        case .light:
            return Bands.length(Band.stemEndLight)
        case .dark:
            return Bands.length(Band.stemEndDark)
        }
    }
}
