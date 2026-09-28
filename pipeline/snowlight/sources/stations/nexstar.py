"""Nexstar Media Group closings lists (its own stations, the former Tribune, Media General
and LIN stations, and the stations it runs for Mission, White Knight and others).

Every Nexstar station site runs one WordPress build. Its HTML pages answer this
pipeline's User-Agent with a PerimeterX challenge (HTTP 403, never worked around),
but the same pages are published by the WordPress REST API, which robots.txt
allows. Variants this adapter reads (the ``variant`` of each listing):

``nexstar-wp-closings``
    A REST page object, ``GET {origin}/wp-json/wp/v2/pages/{id}`` (or a JSON array
    of them from ``pages?slug={slug}``), whose ``content.rendered`` is the closings
    page as the site renders it at request time::

        <article class="closings-page" data-component="closingsPage"> ...
          <div class="closings-list">
            <a id="letter-g"></a><h2 class="closings-list__heading">G</h2>
            <div class="closing">
              <h3 class="closing__title">Glanbia Nutritionals</h3>
              <p class="closing__details">
                <span class="closing__locality closing__details__item">W Haven</span>
                <span class="closing__category closing__details__item">Business</span></p>
              <div class="closing__status">Team C and 2nd shift all locations Cancelled.</div>
              <div class="closing__comments">Weather</div>   (when there is one)
            </div> ...

    ``closing__title`` is the name and ``closing__status`` the status (a row the
    page shows with its name alone, as KOIN's "St. Agatha Catholic School" on
    2021-02-12, has the empty status). Each detail
    (``closing__locality``, ``closing__category``) and every other ``closing__*``
    child (``comments``) goes in ``raw_extra`` under its name, with the letter
    heading in force as ``letter``. The list's own sentence "Most recent closings
    and delays are listed here when there are active closures." with no rows is
    the empty state; in 2019 the list said "All is good" and "There are currently no
    closings or delays" instead (WLAX, archived 2019-10-16). An array holding several
    pages uses the one page with the closings article (two with it are read only when
    they list the same rows).

    The rest of the page's content is read too (the REST page's whole content, or
    the HTML page's rich-text block around the article): a page that types entries
    beside the article (see ``nexstar-wp-typed-beside`` below) is an error here,
    never the article's empty list.

``nexstar-page``
    The same article inside the station's HTML page (as archived captures of
    ``{origin}/weather/closings/`` hold it), read the same way.

``nexstar-app-feed``
    ``GET {origin}/wp-json/nxd_app/v1/closings_alerts``, the stations' app feed: a
    JSON array of ``{content, category, status, county, city, comments_line1, url,
    uuid}``. ``content`` is the name and ``status`` the status; every other field
    goes in ``raw_extra``. ``[]`` is the empty state. A row with a blank name is
    counted in ``skipped_rows``; a feed whose every row is nameless is an error.
    It carried the same rows as the closings page at WTNH and WPRI (2026-09-26),
    and it is what the poller reads for a site whose REST page object holds no list
    but whose closings page, drawn by the theme, was archived with rows (WDAF:
    ``fox4kc.com/weather/closings/`` is page 807, a dead Tribune frame, in the REST
    API).

``nexstar-wp-frame`` and ``nexstar-page-frame``
    A closings page (REST object or HTML) with no closings article that frames the
    station's list file (``<iframe src=...>``, or the Tribune-era shortcode
    ``[localtv_vendor_embed src="..."]``): a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` names the frame when it is a list file (Nexstar's PSG files,
    schoolclosingsnet.com reports, Tribune ``cdn.trb.tv`` and WJW ``wjwclosings``
    files, the stations' ``media.*`` closings files). A frame of the Emergency
    Closing Center application (WGN) is an application, not a list: nothing is
    named and the reader loads the station's registered ``data_url`` (the JSON
    the application reads). Other frames (video, advertising) are ignored; a page
    with neither the article nor a list frame is an error.

``nexstar-ecc-json``
    WGN's Emergency Closing Center data file
    (``media.psg.nexstardigital.net/WGNR/closings/closings.json``), an XML document
    converted to JSON: ``{"$": {"Time": "09/26/2026 05:40:31 PM"}}`` when nothing is
    listed, and a ``Closing`` array when something is. The application's own code
    (``wgnr-closings.emergencyclosingcenter.com/static/js/main.c73bd0ff.chunk.js``,
    read 2026-09-26) reads each closing as ``Name1[0]`` (name), ``City[0]``,
    ``EntityType[0]`` and ``Status1``/``Status2`` (lists of status texts shown
    together), keyed by ``ID[0]``. Those are read the same way: the status is the
    ``Status1`` then ``Status2`` texts joined with " | "; every other field goes in
    ``raw_extra`` (a one-item list as its item). ``$.Time`` is each row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``). The
    populated form has not been seen in a capture yet; a file in any other shape
    is an error.

``nexstar-psg-closings``
    KSN's closings file (``media.psg.nexstardigital.net/ksnw/weather/
    ksnwx-closings-nwt.html``). Its empty state: "No closings to report" under the
    ``#clmod_title`` heading. (Its populated form is described below.)

``schoolclosingsnet-table``
    The School Closings Network report KOLR frames
    (``www.schoolclosingsnet.com/report.php?type=html&code=...``): a table whose
    header names its columns (School Name, Closing Start, Through, Status, Notes).
    Each body row has one cell per header: "School Name" is the name, "Status" the
    status, and the other columns go in ``raw_extra`` under their header in lower
    case with underscores. A table with its header and no body rows is empty.

``nexstar-psg-closings`` (populated)
    The same KSN file on storm days (archived 2022-02-04 and 2025-01-06)::

        <div id="clmod_title"><h1>Closings &amp; Delays</h1></div>
        <div class="closing_row"><strong>Butler County Spelling Bee:</strong> Postponed; ...</div>
        <div hidden>Expires 2022-02-04 23:59:00</div>
        <div class="closing_header"><strong>Schools:</strong></div>
        <div class="closing_row"><strong><a href="https://www.usd385.org/">Andover - USD 385</a>:
          </strong> Closed Tomorrow</div><div hidden>Expires 2022-02-04 16:30:00</div> ...

    The bold text without its closing colon is the name and the text after it the
    status; the heading in force (without its colon) goes in ``raw_extra["group"]``,
    a linked name's address in ``raw_extra["link"]``, and the hidden "Expires"
    line after a row in ``raw_extra["expires"]``.

``nexstar-cgs-all-active``
    The "All Active" page of CGS Infographics Automation that WDAF (FOX4 Kansas
    City) framed in the Tribune years (``cdn.trb.tv/wdaf-ftp/closings/allactive.html``,
    archived populated on 2018-11-26 and 2019-12-16)::

        <div class="msg">12/16/2019 5:19:26 AM</div> ...
        <table class="tableborder"><tr>
          <td class="cat">Activ.</td><td class="org">Casco Area Workshop Harrisonville</td>
          <td class="sts">Closed</td> [<td class="sts2">&#160;</td>]
        </tr></table> ...

    (every other row's cells end in ``dark``). ``org`` is the name, ``sts`` the
    status, ``cat`` goes in ``raw_extra["category"]`` and ``sts2``, when the row has
    one, in ``raw_extra["status2"]``. The first ``msg`` time is each row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``). The page's
    sentence "There are no 'All Active' closings to report." with no rows is the
    empty state.

``nexstar-newsticker-table``
    WPRI's closings file (``media.wpri.com/.../WPRI_closings.html``) as it was in
    2020: a NewsTicker export in the Rhode Island Broadcasters Association's
    layout, one table with a ``timestamp`` cell ("UPDATED FRIDAY, DEC 18 AT 4:40
    PM"), heading rows (``<TD CLASS="orgname" ... COLSPAN=2><B><A NAME="22">RI
    PUBLIC SCHOOLS</A></B></TD>``) and one row per organization::

        <TR><TD ...><FONT CLASS="status">Cumberland</FONT></TD>
            <TD ...><FONT CLASS="orgname">Cumberland Public Schools</FONT>:
            <FONT CLASS="status">Ashton, BF Norton, Community ; ...</FONT></TD></TR>

    The second cell's ``orgname`` is the name and its ``status`` the status; the
    first cell (a town, often blank) goes in ``raw_extra["town"]`` and the heading in
    force in ``raw_extra["group"]``. A ``[WEB]`` link written after a name is not
    part of it: its address goes in ``raw_extra["homepage"]``. The timestamp is each row's
    ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``). The same
    file with no organization rows, "There are no active records at this time.",
    is the NewsTicker empty state that :mod:`~snowlight.sources.stations.gray_files`
    reads.

``nexstar-feed-page``
    A closings page whose list a script fills from files the page names: the
    2019-2021 WOOD page (``/weather/closings-and-delays/``) holds ``<div
    data-feed="//media.woodtv.com/.../WOODclosings.xml" data-feed-type="XML" ...
    id="closings-and-delays">``, WOWK's PSG page
    (``media.psg.nexstardigital.net/wowtv/closings/closings_page.html``) calls
    ``loadXMLDoc("closings.xml")`` (both a NewsTicker XML export, read by
    :mod:`~snowlight.sources.stations.gray_files`), and the Tribune tab pages
    that WJW and WGN framed in 2017-2020 (``s3.amazonaws.com/wjwclosings/wjw.html``,
    ``.../wgnclosings/wgn.html``) fill each tab with ``$("#school_list").load(
    "wjw_schools.html")`` and the like. Each is a
    :attr:`~snowlight.sources.stations.model.ListingState.DEFERRED` listing whose
    ``follows`` names those files, in the page's order (the schools tab first).

``nexstar-school-information``
    WREG's table on ``newcdn.tribtv.com/wreg/SchoolClosings/closings.html``
    (archived 2020-02-15): "School Information updated at 11:17am on 2/15/2020",
    one-cell heading rows ("Schools") and three-cell rows (name, status, a comment
    that goes in ``raw_extra["comment"]`` when it holds text). The update time is
    each row's ``raw_updated_text`` (``raw_extra["updated_scope"]`` is ``"page"``)
    and the heading in force ``raw_extra["group"]``. Its empty form has not been
    seen, so a table with no rows is an error.

``nexstar-storm-tracker``
    WTEN's "STORM TRACKER School Closings" file
    (``media.news10.com/nxs-wtentv-media-us-east-1/closings/school.html``, archived
    2018 and 2020): "(posted: Sunday, Mar 29, 2020 at 6:04 PM)", then
    ``<b>Name</b><br>Status<br> <br>`` per organization. The posted time is each
    row's ``raw_updated_text``; "No School Closings to Report" is the empty state.

``nexstar-tribune-tab``
    One tab of the Tribune tab pages above: the file a tab loads
    (``s3.amazonaws.com/wjwclosings/wjw_schools.html``, archived 2017-01-31 with two
    rows; ``.../wgnclosings/wgn_schools.html``, archived 2019-03-01 empty)::

        <h4>School Closings Last Updated: Mon Jan 30 22:24:03 EST 2017</h4>
        <ul id="schools" class="closings"><li class="ln-c"><span class="place">Cleveland
          State University | <span class="pstatus">Delayed 2 Hours</span></li> ...</ul>

    (the ``place`` span is never closed). The ``place`` text before its " |" is the
    name and the ``pstatus`` text the status; the heading's kind ("School") goes in
    ``raw_extra["tab"]``, the item's letter class (``ln-c``) in ``raw_extra["letter"]``,
    and the "Last Updated" time is each row's ``raw_updated_text``
    (``raw_extra["updated_scope"]`` is ``"page"``). ``<h4>No School Closings
    Reported</h4>`` alone is the empty state.

``nexstar-clmod``
    The Media General stations' closings file of 2016 (WRIC's
    ``wx.wric.com/weather/WRIC_closings_delays.html``, archived 2016-03-12, the file
    WRIC's page of 2016-03-04 framed): ``<div id="weather_clmod">``, tabs and letter
    links, then "As of 6:16pm on Mar. 4th, 2016." and a ``clmod-all`` block that
    reads "There are no reported closings or delays at this time." when nothing is
    listed: the empty state, the one form seen. The file's populated form has not
    been seen, so a file with anything else in that block is an error rather than
    being read by guesswork.

``nexstar-closing-alerts``
    The "Closing Alerts" module of the Liferay-based sites Nexstar ran before its
    WordPress build (archived WJMN ``upmatters.com/closings`` 2016-03-17 with one
    row, WBRE ``pahomepage.com/closings-and-delays`` 2017-02-07 empty)::

        <section class="mod-wrapper mod-style-02" id="closingAlertPage">
          <header class="mod-header"><h3>Closing Alerts</h3>
            <select><option value="A-F">A-F</option> ... </select></header>
          <div class="mod-body add-border">
            <p class="mod-tab-desc-A-F mod-tab-desc">There are no current closing alerts.
              Please check back later.</p> ...
            <div class="mod-inline mod-body-S-Z">
              <h4>Wakefield-Marensico</h4>
              <div class="mod-body"><ul class="list">
                <li><a class="txt-blue" href="#">Closed 3/17</a></li></ul></div>
            </div>
          </div>
        </section>

    One tab per letter range: a ``mod-inline`` block of organizations, or the
    sentence for a range with none. Each ``<h4>`` is a name and the list items of
    the ``mod-body`` after it its status (several joined with " | "); the range
    goes in ``raw_extra["range"]``. The sentence in every range and no rows is the
    empty state; an ``<h4>`` with no ``mod-body`` after it is an error.

The Tribune-era pages (2018-2020) framed their lists through the shortcode above
(also written with ``&quot;`` and further attributes) or an ``<iframe>``: WJW's
``s3.amazonaws.com/wjwclosings/wjw.html``, WGN's ``s3.amazonaws.com/wgnclosings/wgn.html``
and later its Emergency Closing Center application on ``wgnr-closings.s3.amazonaws.com``,
KDVR's ``s3.amazonaws.com/kdvrclosings/kdvr.html`` and ``newcdn.tribtv.com`` file,
WREG's ``newcdn.tribtv.com`` file and WTEN's ``media.news10.com`` file; those are
list files (or, WGN's, an application) as above. The pages of 2016-2017 framed
files on ``s3.amazonaws.com/nxsglobal/`` (WUTR's
``.../cnyhomepage/closings/closings.html``) or the station's ``wx.`` host (WRIC's
``wx.wric.com/weather/WRIC_closings_delays.html``): list files too, followed as
frames (no capture of either file has been read). Pages on the Frankly (WorldNow)
platform that some of these stations used before (WCMH, WKRN and KOIN in 2019)
loaded their lists by script from an address the page does not name, so they are
errors, as are domains that no longer serve the list (``cdn.trb.tv`` was a
domain-sale page by November 2020).

``nexstar-wp-typed-beside`` and ``nexstar-page-typed-beside`` (the ``nexstar-typed`` platform only)
    Entries typed by hand into the closings page beside its closings article, while
    the article itself is empty: KIAH (CW39 Houston) typed eight districts in a list
    below its empty article for the storm of January 2025 (archived 2025-01-25 and,
    still up, 2026-01-11), and WIVB typed a school's closing above its article (its
    REST page read live on 2026-09-28, dated 2026-09-04: the REST page's content holds
    such entries beside the article as the HTML page does). The page's content
    beside the article (the REST page's whole
    ``content.rendered``, or the HTML page's ``div.article-content`` around the
    article; an older page whose closings article is the page's own article, its
    content outside the list and letter links) is read by
    :func:`snowlight.sources.stations.typed.entries_beside`: its list items and table
    rows, else its paragraph entries with no link in them (a station's blurb, a note
    for organizations, a sign-up widget or a link to a story is no entry). With
    entries and an empty article, the entries are the listing (``nexstar-wp-typed-beside``
    for a REST page, ``nexstar-page-typed-beside`` for an HTML page), stamped with the
    page's time (``modified_gmt``, or ``article:modified_time``) and marked ``typed``;
    with none, the article's own listing stands. An article that lists rows while
    the page types entries beside it is an error (never seen; neither list is taken
    for the other). Only :func:`parse_typed` reads such entries: :func:`parse`, every
    other station's reader, raises :class:`~snowlight.sources.stations.model.ShapeError`
    for a page with entries typed beside its article, whether the article is empty
    or not.

``nexstar-wp-typed``, ``nexstar-typed-page``, ``nexstar-typed-entry-content``
    (the ``nexstar-typed`` platform only) A closings page typed by hand, with no
    closings article, frame or feed: WHNT's
    ``/weather-closings/``, WDHN's ``/severe-weather-closings-and-delays/`` and WRBL's
    ``/weather/closings-and-delays/`` (bulleted lines, sentences under county
    headings, or bold names with their status on the lines after), and WNTZ's
    2017 article (a two-column table) its closings page redirected to. These are
    read only by :func:`parse_typed`, the ``parse`` of the ``nexstar-typed`` adapter
    (:mod:`snowlight.sources.stations.nexstar_typed`), for the stations the registry
    files under that platform because their pages were seen typed on storm days;
    :func:`parse` never reads them, so on every other station's page a missing,
    blank or script-filled list is an error, not an empty list. The REST page
    object (``nexstar-wp-typed``) is read when its ``title.rendered`` says it is a
    closings page ("Weather Closings, Delays and Dismissals"); an HTML page
    (``nexstar-typed-page``, archived captures) when its ``og:title`` (else its
    ``<title>``) does, from its ``div.article-content`` rich-text block, or, on a page
    of the Tribune-era template without one (WHNT's page archived 2018-12-11, its
    closings typed under "Schools:" and "Businesses:"), from its ``div.entry-content``
    (``nexstar-typed-entry-content``). Either is
    read by :func:`snowlight.sources.stations.typed.read_typed`, whose rows are the
    block's list items, table rows or paragraph entries, whatever words they use;
    a block with none is the empty state only when it says so, and an error
    otherwise. The page's time (``modified_gmt``, or ``article:modified_time``) is
    every row's ``raw_updated_text``; the listing is marked ``typed``, so the live
    reader keeps its rows only while the page changed recently. A page holding a
    login form for organizations (WSAV's status-entry page, password field and all)
    is not a list. A news article whose title is not a closings page's ("Closing
    arguments set in trial ...") is refused.

A list file in one of the vendor formats :mod:`snowlight.sources.stations.gray_files`
reads (NewsTicker exports, FlashAlert reports and the like) is read with it, under
that module's variant names. Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from html import unescape
from urllib.parse import urlsplit

from selectolax.parser import Node

from snowlight.sources.stations import gray_files, typed
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.markup import (
    SEPARATOR,
    collapse,
    element_end,
    flat,
    iframe_sources,
    iframe_tags,
    json_value,
    minimal_document,
    node_text,
    parse_html,
    text_of,
)
from snowlight.sources.stations.model import (
    JsonScalar,
    Listing,
    ListingState,
    ParsedRow,
    ShapeError,
)

EMPTY_SENTENCE = "Most recent closings and delays are listed here when there are active closures."
EMPTY_2019 = "All is good There are currently no closings or delays"
"""The empty list's words in 2019 (``<h2>All is good</h2><p>There are currently no closings or
delays</p>``, WLAX archived 2019-10-16), as the list's text reads them."""
PSG_EMPTY = "No closings to report"
CGS_MARK = "Created by CGS Infographics Automation"
CGS_EMPTY = "There are no 'All Active' closings to report."
_ARTICLE = re.compile(r"<article\b[^>]*\bclass=\"[^\"]*\bclosings-page\b[^\"]*\"", re.IGNORECASE)
_SHORTCODE_V1 = re.compile(r"\[localtv_vendor_embed\s+src=\"([^\"]+)\"\s*\]", re.IGNORECASE)
_SHORTCODE = re.compile(
    r"\[localtv_vendor_embed\s+src=(?:\"|&quot;)([^\"&\s]*)(?:\"|&quot;)[^\]]*\]", re.IGNORECASE
)
_FEED_DIV = re.compile(r"<div\b[^>]*\bdata-feed-type=\"[^\"]*\"[^>]*>", re.IGNORECASE)
_FEED_ATTR = re.compile(r"\bdata-feed=\"([^\"]+)\"", re.IGNORECASE)
_XML_DOC = re.compile(r"loadXMLDoc\(\"([^\"]+\.xml)\"\)")
_FRANKLY = re.compile(r"closing-alerts-auto-complete|amino-v1-theme", re.IGNORECASE)
_PSG_TITLE = "<title>KSN Weather Closings</title>"
_SCN_TITLE = "<title>School Closings Network</title>"
_ECC_HOST = re.compile(r"(^|\.)emergencyclosingcenter\.com$")
_MEDIA_HOST = re.compile(r"^media\.[a-z0-9-]+\.com$")
_WX_HOST = re.compile(r"^wx\.[a-z0-9-]+\.com$")
"""The Media General stations' weather hosts (WRIC's ``wx.wric.com`` framed its list in 2016)."""
_TRIBUNE_BUCKETS = ("/wjwclosings/", "/wgnclosings/", "/kdvrclosings/")
_KNOWN_DETAILS = frozenset({"title", "details", "status"})
_FEED_KEYS = frozenset({"content", "status"})
_CGS_STAMP = re.compile(
    r"<div class=\"msg\">\s*"
    r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{4} [0-9]{1,2}:[0-9]{2}:[0-9]{2} [AP]M)\s*</div>",
    re.IGNORECASE,
)
_CGS_TABLE = re.compile(r"<table class=\"tableborder\">(.*?)</table>", re.IGNORECASE | re.DOTALL)
_CGS_CELL = re.compile(
    r"<td class=\"(cat|org|sts|sts2)(?:dark)?\">(.*?)</td>", re.IGNORECASE | re.DOTALL
)
_CGS_EMPTY_CELL = re.compile(rf"<td class=\"msg\">{re.escape(CGS_EMPTY)}</td>", re.IGNORECASE)
_TABS_LOAD = re.compile(r"\$\(\s*\"#[A-Za-z_]+\"\s*\)\.load\(\s*\"([^\"]+\.html)\"")
SCHOOL_INFO_MARK = "School Information updated at"
ALERTS_EMPTY = "There are no current closing alerts. Please check back later."
CLMOD_EMPTY = "There are no reported closings or delays at this time."
_CLMOD = re.compile(r"<div id=\"weather_clmod\">", re.IGNORECASE)
_CLMOD_ALL = re.compile(r"<div class=\"clmod-all\">(.*?)</div>", re.IGNORECASE | re.DOTALL)
_TAB_UPDATED = re.compile(r"^<h4>([A-Za-z ]+?) Closings Last Updated: ([^<]+)</h4>", re.IGNORECASE)
_TAB_EMPTY = re.compile(r"^<h4>No ([A-Za-z ]+?) Closings Reported</h4>$", re.IGNORECASE)
_TAB_ITEM = re.compile(
    r"<li class=\"(ln-[a-z0-9]+)\"><span class=\"place\">(.*?)<span class=\"pstatus\">(.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_ALERTS = re.compile(r"<section\b[^>]*\bid=\"closingAlertPage\"[^>]*>", re.IGNORECASE)
_ALERTS_RANGE = re.compile(r"^mod-(?:body|tab-desc)-([A-Z]-[A-Z])$")
_SCHOOL_INFO_STAMP = re.compile(
    r"<b>\s*School Information updated at\s*([^<]*?)\s*</b>", re.IGNORECASE
)
STORM_TRACKER_MARK = "STORM TRACKER School Closings"
STORM_TRACKER_EMPTY = "No School Closings to Report"
_STORM_STAMP = re.compile(r"\(posted:\s*([^)]*?)\s*\)", re.IGNORECASE)
_STORM_ROW = re.compile(r"<b>([^<]*)</b><br>(.*?)<br>\s*<br>", re.IGNORECASE | re.DOTALL)
_NT_TABLE_ROW = re.compile(
    r"<TD[^>]*><FONT CLASS=\"status\">[^<]*</FONT></TD>\s*<TD[^>]*><FONT CLASS=\"orgname\">",
    re.IGNORECASE,
)
_TR = re.compile(r"<TR\b[^>]*>(.*?)</TR>", re.IGNORECASE | re.DOTALL)
_TD = re.compile(r"<TD\b([^>]*)>(.*?)</TD>", re.IGNORECASE | re.DOTALL)
_FONT = re.compile(r"<FONT CLASS=\"(orgname|status)\">(.*?)</FONT>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WEB_LINK = re.compile(
    r"\[\s*<a\b[^>]*\bhref=\"?([^\"\s>]*)\"?[^>]*>\s*WEB\s*</a>\s*\]", re.IGNORECASE
)


_TYPED_BLOCK = re.compile(
    r"<div\s+class=\"article-content\b[^\"]*\brich-text\b[^\"]*\"\s*>", re.IGNORECASE
)
_ENTRY_CONTENT = re.compile(r"<div\s+class=\"entry-content\"\s*>", re.IGNORECASE)
"""The typed block of the Tribune-era page template (WHNT's page archived 2018-12-11)."""
_FORM = re.compile(r"<input\b[^>]*\btype=\"password\"", re.IGNORECASE)
"""A login form for organizations to post their status (WSAV's page): not a list."""
_OG_TITLE = re.compile(r"<meta\s+property=\"og:title\"\s+content=\"([^\"]*)\"", re.IGNORECASE)
_TITLE_TAG = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)
_DIV_OPEN = re.compile(r"<div\b[^>]*>", re.IGNORECASE)
_CLASS_ATTR = re.compile(r"\bclass=\"([^\"]*)\"", re.IGNORECASE)
_MODIFIED_META = re.compile(r"<meta\s+property=\"article:modified_time\"[^>]*>", re.IGNORECASE)


def _host_path(url: str) -> tuple[str, str]:
    parts = urlsplit(url if "://" in url else f"https:{url}")
    return (parts.hostname or "").lower(), parts.path


def _is_list_file_v1(url: str) -> bool:
    """The list files ``nexstar-v1`` slices keep (the frames seen live on 2026-09-26)."""
    host, path = _host_path(url)
    path = path.lower()
    return (
        (host == "media.psg.nexstardigital.net" and path.endswith((".html", ".json")))
        or (host.removeprefix("www.") == "schoolclosingsnet.com" and path == "/report.php")
        or host == "cdn.trb.tv"
        or (host == "s3.amazonaws.com" and path.startswith("/wjwclosings/"))
        or (_MEDIA_HOST.match(host) is not None and "closings" in path)
    )


def _is_list_file(url: str) -> bool:
    """Whether a framed address is a list file this adapter (or gray_files) can read."""
    host, path = _host_path(url)
    lower = path.lower()
    return (
        _is_list_file_v1(url)
        or (host == "media.psg.nexstardigital.net" and lower.endswith(".xml"))
        or (host == "s3.amazonaws.com" and lower.startswith(_TRIBUNE_BUCKETS))
        or (host == "newcdn.tribtv.com" and "closing" in lower)
        or (host == "s3.amazonaws.com" and lower.startswith("/nxsglobal/") and "closings" in lower)
        or (_WX_HOST.match(host) is not None and "closings" in lower)
    )


def _is_application(url: str) -> bool:
    host, _ = _host_path(url)
    return _ECC_HOST.search(host) is not None or host == "wgnr-closings.s3.amazonaws.com"


def _is_application_v1(url: str) -> bool:
    host, _ = _host_path(url)
    return _ECC_HOST.search(host) is not None


# The closings article ------------------------------------------------------------------


def _classes(node: Node) -> list[str]:
    return (node.attributes.get("class") or "").split()


def _closing_row(node: Node, letter: str | None) -> ParsedRow | None:
    """Read one ``div.closing``; None when it has no name."""
    name = ""
    status = ""
    extra: dict[str, JsonScalar] = {}
    child = node.child
    while child is not None:
        classes = _classes(child)
        parts = [c.removeprefix("closing__") for c in classes if c.startswith("closing__")]
        part = parts[0] if parts else None
        if part == "title":
            name = node_text(child)
        elif part == "status":
            status = node_text(child)
        elif part == "details":
            for item in child.css("span.closing__details__item"):
                keys = [
                    c.removeprefix("closing__")
                    for c in _classes(item)
                    if c.startswith("closing__") and c != "closing__details__item"
                ]
                if keys:
                    extra[keys[0]] = node_text(item)
        elif part is not None and part not in _KNOWN_DETAILS:
            extra[part] = node_text(child)
        child = child.next
    if letter is not None:
        extra["letter"] = letter
    if not name:
        return None
    return ParsedRow(name=name, status=status, extra=extra)


def parse_article(html: str, variant: str) -> Listing:
    """Read the ``article.closings-page`` in ``html`` (a page or a REST page's content)."""
    tree = parse_html(html)
    article = tree.css_first("article.closings-page")
    if article is None:
        raise ShapeError("no closings-page article")
    listing = article.css_first("div.closings-list")
    if listing is None:
        raise ShapeError("the closings article has no closings-list")
    rows: list[ParsedRow] = []
    skipped = 0
    letter: str | None = None
    # css("*") is the list itself, then its descendants in document order.
    for node in listing.css("*")[1:]:
        classes = _classes(node)
        if node.tag == "h2" and "closings-list__heading" in classes:
            letter = node_text(node)
        elif node.tag == "div" and "closing" in classes:
            row = _closing_row(node, letter)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    if rows:
        return Listing(
            variant=variant, state=ListingState.POPULATED, rows=tuple(rows), skipped_rows=skipped
        )
    if skipped:
        raise ShapeError("every closing in the list is missing its name")
    if node_text(listing) in (EMPTY_SENTENCE, EMPTY_2019):
        return Listing(variant=variant, state=ListingState.EMPTY, rows=())
    raise ShapeError(f"the closings list has no rows and no empty sentence: {node_text(listing)!r}")


def _shortcodes(html: str, pattern: re.Pattern[str]) -> list[str]:
    return [m.group(1) for m in pattern.finditer(html) if m.group(1)]


def _frames(html: str) -> list[str]:
    """Return the list files and applications ``html`` frames, in order."""
    sources = [*iframe_sources(html), *_shortcodes(html, _SHORTCODE)]
    return [src for src in sources if _is_list_file(src) or _is_application(src)]


def _frames_v1(html: str) -> list[str]:
    sources = [*iframe_sources(html), *_shortcodes(html, _SHORTCODE_V1)]
    return [src for src in sources if _is_list_file_v1(src) or _is_application_v1(src)]


def _feeds(html: str) -> list[str]:
    """Return the XML files a script-filled closings page names (see ``nexstar-feed-page``)."""
    found = [
        attr.group(1)
        for tag in _FEED_DIV.findall(html)
        if (attr := _FEED_ATTR.search(tag)) is not None
    ]
    found += _XML_DOC.findall(html)
    found += _TABS_LOAD.findall(html)
    return list(dict.fromkeys(found))


def _page_listing(html: str, article_variant: str, frame_variant: str) -> Listing:
    """Read a closings page's content: its article, or the list file it frames or names."""
    if _ARTICLE.search(html):
        return parse_article(html, article_variant)
    frames = _frames(html)
    if frames:
        follows = tuple(dict.fromkeys(src for src in frames if _is_list_file(src)))
        return Listing(variant=frame_variant, state=ListingState.DEFERRED, rows=(), follows=follows)
    feeds = _feeds(html)
    if feeds:
        return Listing(
            variant="nexstar-feed-page", state=ListingState.DEFERRED, rows=(), follows=tuple(feeds)
        )
    if _FRANKLY.search(html):
        raise ShapeError(
            "a Frankly (WorldNow) closings page: a script loaded its list from an address "
            "the page does not name"
        )
    raise ShapeError("the page has no closings article and frames no list file")


# REST pages ------------------------------------------------------------------------------


def _rendered(page: Mapping[str, object]) -> str:
    content = page.get("content")
    rendered = content.get("rendered") if isinstance(content, Mapping) else None
    if not isinstance(rendered, str):
        raise ShapeError("a REST page object without content.rendered")
    return rendered


def _is_page(value: object) -> bool:
    return isinstance(value, Mapping) and isinstance(value.get("content"), Mapping)


def _beside_block(html: str, *, rest: bool) -> Node | None:
    """The page content beside the closings article's list: the content, its list taken out.

    A REST page's content is the page's content whole; an HTML page's is the
    rich-text block (``div.article-content``) that holds the closings article, or,
    on an older page whose closings article is the page's own article (no rich-text
    block around it), that article. Either way the article's list
    (``div.closings-list``, with its empty sentence) and its letter links
    (``div.closings-nav``) are taken out, and everything else is kept, the rest of
    the article too. None when there is no closings article.
    """
    tree = parse_html(html)
    article = tree.css_first("article.closings-page")
    if article is None:
        return None
    if rest:
        container = tree.body
    else:
        container = article.parent
        while container is not None and not (
            container.tag == "div" and "article-content" in _classes(container)
        ):
            container = container.parent
    if container is None:
        container = article
    for part in article.css("div.closings-list, div.closings-nav"):
        part.decompose()
    return container


def _article_listing(
    html: str, variant: str, *, rest: bool, typed_beside: bool, modified: datetime | None
) -> Listing:
    """Read a closings article, and what the page types beside it (see ``nexstar-*-typed-beside``).

    Raises:
        ShapeError: the article is not one :func:`parse_article` reads; or the page
            holds entries typed beside the article and the station is not filed as
            typing closings there (``typed_beside`` false), or the article lists rows
            as well.
    """
    listing = parse_article(html, variant)
    block = _beside_block(html, rest=rest)
    beside_variant = "nexstar-wp-typed-beside" if rest else "nexstar-page-typed-beside"
    beside = typed.read_beside(block, beside_variant, modified) if block is not None else None
    if beside is None:
        return listing
    names = "; ".join(row.name for row in beside.rows[:3])
    if not typed_beside:
        raise ShapeError(
            f"the page lists {len(beside.rows)} entries typed beside its closings article "
            f"({names}), and the station is not filed as typing its closings there"
        )
    if listing.rows:
        raise ShapeError(
            f"the closings article lists {len(listing.rows)} rows and the page "
            f"{len(beside.rows)} entries typed beside it ({names})"
        )
    return beside


def parse_rest_pages(
    pages: Sequence[Mapping[str, object]], *, typed_beside: bool = False
) -> Listing:
    """Read one REST page object, or the page with the closings article among several.

    ``typed_beside`` reads the entries a page types beside its closings article (the
    ``nexstar-typed`` stations); otherwise such entries are an error.
    """
    contents = [(page, _rendered(page)) for page in pages]
    with_article = [(page, html) for page, html in contents if _ARTICLE.search(html)]
    if with_article:
        listings = [
            _article_listing(
                html,
                "nexstar-wp-closings",
                rest=True,
                typed_beside=typed_beside,
                modified=typed.rest_modified(page),
            )
            for page, html in with_article
        ]
        if any(other.rows != listings[0].rows for other in listings[1:]):
            raise ShapeError("two closings pages with the same slug list different rows")
        return listings[0]
    if len(contents) != 1:
        raise ShapeError(f"{len(contents)} REST pages and none holds the closings article")
    return _page_listing(contents[0][1], "nexstar-wp-closings", "nexstar-wp-frame")


def _knows_page(html: str) -> bool:
    """Whether a page's content has a list this adapter reads other than a typed one."""
    return bool(_ARTICLE.search(html) or _frames(html) or _feeds(html) or _FRANKLY.search(html))


def _is_typed_rest(page: Mapping[str, object], html: str) -> bool:
    """Whether a REST page is a closings page typed by hand: no list this adapter reads
    otherwise, no login form, and a title that says it is a closings page."""
    return not (
        _knows_page(html) or _FORM.search(html) or not typed.closings_title(typed.rest_title(page))
    )


def _typed_rest(page: Mapping[str, object], html: str) -> Listing:
    """Read a REST closings page typed by hand (``nexstar-wp-typed``)."""
    body = parse_html(html).body
    if body is None:  # pragma: no cover - the parser always gives a body
        raise ShapeError("a REST page whose content has no body")
    return typed.read_typed(body, "nexstar-wp-typed", typed.rest_modified(page))


def _page_title(html: str) -> str:
    """An HTML page's title: its ``og:title``, else its first ``<title>``."""
    match = _OG_TITLE.search(html) or _TITLE_TAG.search(html)
    return collapse(unescape(match.group(1))) if match is not None else ""


def _typed_block(html: str, *, entry_content: bool = True) -> tuple[str, str] | None:
    """The typed block of a closings page, byte for byte, and its variant; or None.

    The block is the page's ``div.article-content`` (``nexstar-typed-page``) or, on
    a page without one, the Tribune-era template's ``div.entry-content``
    (``nexstar-typed-entry-content``; ``entry_content`` false leaves it out, as the
    ``nexstar-v3`` slice does).
    """
    match = _TYPED_BLOCK.search(html)
    variant = "nexstar-typed-page"
    if match is None and entry_content:
        match = _ENTRY_CONTENT.search(html)
        variant = "nexstar-typed-entry-content"
    if match is None or not typed.closings_title(_page_title(html)):
        return None
    block = html[match.start() : element_end(html, match.start(), "div")]
    # A form for organizations to post their status (WSAV's) is not a list.
    return None if _FORM.search(block) else (block, variant)


def parse_typed_page(html: str) -> Listing:
    """Read a closings page whose article is typed by hand (``nexstar-typed-page`` or
    ``nexstar-typed-entry-content``).

    Raises:
        ShapeError: the page has no typed block, or the block no row and no sentence
            saying it holds none.
    """
    found = _typed_block(html)
    if found is None:
        raise ShapeError(
            "no closings page typed by hand (no rich-text block under a closings title)"
        )
    block_html, variant = found
    block = parse_html(block_html).css_first("div")
    if block is None:  # pragma: no cover - the pattern matched this element
        raise ShapeError("no closings page typed by hand")
    return typed.read_typed(block, variant, typed.html_modified(html))


# The app feed ------------------------------------------------------------------------------


def parse_feed(items: Sequence[object]) -> Listing:
    """Read the ``nxd_app/v1/closings_alerts`` feed (a JSON array)."""
    rows: list[ParsedRow] = []
    skipped = 0
    for item in items:
        if not isinstance(item, Mapping) or not set(item) >= _FEED_KEYS:
            raise ShapeError("an app-feed item is not a closing object")
        name, status = item["content"], item["status"]
        if not isinstance(name, str) or not isinstance(status, str):
            raise ShapeError("an app-feed item's content or status is not text")
        extra = {str(k): flat(v) for k, v in item.items() if k not in _FEED_KEYS}
        if not collapse(name):
            skipped += 1
            continue
        rows.append(ParsedRow(name=collapse(name), status=collapse(status), extra=extra))
    if skipped and not rows:
        raise ShapeError("every row of the app feed is missing its name")
    return Listing(
        variant="nexstar-app-feed",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


def _is_feed(items: Sequence[object]) -> bool:
    return all(isinstance(item, Mapping) and "uuid" in item for item in items)


# Emergency Closing Center JSON -------------------------------------------------------------


def _first(value: object) -> JsonScalar:
    """A one-item list (as XML-to-JSON writes a single element) as its item."""
    if isinstance(value, list) and len(value) == 1:
        return flat(value[0])
    return flat(value)


def _texts(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ShapeError(f"an ECC closing's {field} is not a list of text")
    return [collapse(item) for item in value if collapse(item)]


def _ecc_row(closing: object, updated: str) -> ParsedRow | None:
    if not isinstance(closing, Mapping):
        raise ShapeError("an ECC closing is not an object")
    names = _texts(closing.get("Name1"), "Name1")
    status = SEPARATOR.join(
        _texts(closing.get("Status1"), "Status1") + _texts(closing.get("Status2"), "Status2")
    )
    extra: dict[str, JsonScalar] = {"updated_scope": "page"}
    for key, value in closing.items():
        if key not in {"Name1", "Status1", "Status2"}:
            extra[str(key)] = _first(value)
    if not names:
        return None
    return ParsedRow(name=names[0], status=status, updated_text=updated, extra=extra)


def parse_ecc(data: Mapping[str, object]) -> Listing:
    """Read the Emergency Closing Center JSON (see the module docstring)."""
    head = data.get("$")
    time = head.get("Time") if isinstance(head, Mapping) else None
    if not isinstance(time, str) or not time.strip():
        raise ShapeError("the ECC file has no $.Time")
    unknown = set(data) - {"$", "Closing"}
    if unknown:
        raise ShapeError(f"the ECC file has unexpected fields {sorted(unknown)}")
    closings = data.get("Closing", [])
    if not isinstance(closings, list):
        raise ShapeError("the ECC file's Closing is not a list")
    rows: list[ParsedRow] = []
    skipped = 0
    for closing in closings:
        row = _ecc_row(closing, time.strip())
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if skipped and not rows:
        raise ShapeError("every ECC closing is missing its name")
    return Listing(
        variant="nexstar-ecc-json",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


# Frame files -------------------------------------------------------------------------------


def _psg_row(node: Node, group: str | None, expires: str | None) -> ParsedRow | None:
    strong = node.css_first("strong")
    if strong is None:
        raise ShapeError("a PSG closing row without its bold name")
    label = node_text(strong)
    full = node_text(node)
    if not full.startswith(label):  # pragma: no cover - the bold text opens the row
        raise ShapeError("a PSG closing row whose name does not open it")
    name = label.removesuffix(":").strip()
    extra: dict[str, JsonScalar] = {}
    if group is not None:
        extra["group"] = group
    link = strong.css_first("a")
    if link is not None and link.attributes.get("href"):
        extra["link"] = link.attributes.get("href")
    if expires is not None:
        extra["expires"] = expires
    if not name:
        return None
    return ParsedRow(name=name, status=full[len(label) :].strip(), extra=extra)


def _psg_rows(body: Node) -> tuple[list[ParsedRow], int]:
    children = [child for child in body.iter() if child.tag != "-text"]
    rows: list[ParsedRow] = []
    skipped = 0
    group: str | None = None
    for index, child in enumerate(children):
        classes = _classes(child)
        if "closing_header" in classes:
            group = node_text(child).removesuffix(":").strip()
        elif "closing_row" in classes:
            after = children[index + 1] if index + 1 < len(children) else None
            expires = None
            if after is not None and after.tag == "div" and "hidden" in after.attributes:
                expires = node_text(after).removeprefix("Expires").strip()
            row = _psg_row(child, group, expires)
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    return rows, skipped


def parse_psg(html: str) -> Listing:
    """Read KSN's PSG closings file, empty or populated (see the module docstring)."""
    tree = parse_html(html)
    body = tree.body
    if body is None or tree.css_first("#clmod_title") is None:
        raise ShapeError("not the PSG closings file")
    rows, skipped = _psg_rows(body)
    if rows:
        return Listing(
            variant="nexstar-psg-closings",
            state=ListingState.POPULATED,
            rows=tuple(rows),
            skipped_rows=skipped,
        )
    if skipped:
        raise ShapeError("every PSG closing row is missing its name")
    heading = node_text(tree.css_first("#clmod_title"))
    rest = collapse(node_text(body).removeprefix(heading))
    if rest == PSG_EMPTY:
        return Listing(variant="nexstar-psg-closings", state=ListingState.EMPTY, rows=())
    raise ShapeError(f"the PSG closings file has no rows and no empty sentence: {rest[:80]!r}")


def _cell_text(fragment: str) -> str:
    return node_text(parse_html(f"<p>{fragment}</p>").css_first("p"))


def parse_cgs(html: str) -> Listing:
    """Read the CGS "All Active" page (``nexstar-cgs-all-active``, see the module docstring)."""
    stamp = _CGS_STAMP.search(html)
    if stamp is None:
        raise ShapeError("a CGS closings page with no time stamp")
    updated = collapse(stamp.group(1))
    rows: list[ParsedRow] = []
    skipped = 0
    for table in _CGS_TABLE.finditer(html):
        cells = {kind.lower(): _cell_text(text) for kind, text in _CGS_CELL.findall(table.group(1))}
        if not {"org", "sts"} <= set(cells):
            raise ShapeError("a CGS closings row without its organization and status cells")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"}
        if "cat" in cells:
            extra["category"] = cells["cat"]
        if "sts2" in cells:
            extra["status2"] = cells["sts2"]
        if not cells["org"]:
            skipped += 1
            continue
        rows.append(
            ParsedRow(name=cells["org"], status=cells["sts"], updated_text=updated, extra=extra)
        )
    if rows:
        return Listing(
            variant="nexstar-cgs-all-active",
            state=ListingState.POPULATED,
            rows=tuple(rows),
            skipped_rows=skipped,
        )
    if skipped:
        raise ShapeError("every CGS closings row is missing its organization")
    if _CGS_EMPTY_CELL.search(html):
        return Listing(variant="nexstar-cgs-all-active", state=ListingState.EMPTY, rows=())
    raise ShapeError("a CGS closings page with no rows and no empty sentence")


def _plain(fragment: str) -> str:
    return _cell_text(_TAG.sub(" ", fragment))


def _nt_table_row(
    cells: list[tuple[str, str]], group: str | None, updated: str | None
) -> ParsedRow:
    town_fonts = _FONT.findall(cells[0][1])
    fonts = _FONT.findall(cells[1][1])
    kinds = [kind.lower() for kind, _ in fonts]
    if [kind.lower() for kind, _ in town_fonts] != ["status"] or kinds != ["orgname", "status"]:
        raise ShapeError("a NewsTicker table row is not a town, a name and a status")
    link = _WEB_LINK.search(cells[1][1])
    name, status = _plain(fonts[0][1]), _plain(fonts[1][1])
    if link is not None:
        name = _plain(_WEB_LINK.sub("", fonts[0][1]))
    if not name:
        raise ShapeError("a NewsTicker table row has no name")
    extra: dict[str, JsonScalar] = {"town": _plain(town_fonts[0][1])}
    if link is not None:
        extra["homepage"] = link.group(1)
    if group is not None:
        extra["group"] = group
    if updated is not None:
        extra["updated_scope"] = "page"
    return ParsedRow(name=name, status=status, updated_text=updated, extra=extra)


def parse_newsticker_table(html: str) -> Listing:
    """Read WPRI's 2020 NewsTicker table (``nexstar-newsticker-table``)."""
    rows: list[ParsedRow] = []
    group: str | None = None
    updated: str | None = None
    for tr in _TR.finditer(html):
        cells = _TD.findall(tr.group(1))
        attrs = [attr.upper() for attr, _ in cells]
        if len(cells) == 1 and 'CLASS="TIMESTAMP"' in attrs[0]:
            updated = _plain(cells[0][1])
        elif len(cells) == 1 and 'CLASS="ORGNAME"' in attrs[0]:
            group = _plain(cells[0][1])
        elif len(cells) == 1 and not _plain(cells[0][1]):
            continue
        elif len(cells) == 2:  # noqa: PLR2004 - a town cell and a name-and-status cell
            rows.append(_nt_table_row(cells, group, updated))
        else:
            raise ShapeError(
                f"a NewsTicker table row in no known shape: {_plain(tr.group(1))[:80]!r}"
            )
    if not rows:
        raise ShapeError("a NewsTicker table with no organization rows")
    return Listing(
        variant="nexstar-newsticker-table", state=ListingState.POPULATED, rows=tuple(rows)
    )


def parse_school_information(html: str) -> Listing:
    """Read WREG's ``newcdn.tribtv.com`` table (``nexstar-school-information``)."""
    stamp = _SCHOOL_INFO_STAMP.search(html)
    if stamp is None:
        raise ShapeError("a School Information table with no update time")
    updated = collapse(stamp.group(1))
    rows: list[ParsedRow] = []
    group: str | None = None
    for tr in _TR.finditer(html):
        cells = [cell for _, cell in _TD.findall(tr.group(1))]
        texts = [_plain(cell) for cell in cells]
        if len(cells) == 1:
            if texts[0] and SCHOOL_INFO_MARK not in texts[0]:
                group = texts[0]
            continue
        if len(cells) != 3 or not texts[0]:  # noqa: PLR2004 - name, status, comment
            raise ShapeError(f"a School Information row in no known shape: {texts!r}")
        extra: dict[str, JsonScalar] = {"updated_scope": "page"}
        if group is not None:
            extra["group"] = group
        if texts[2]:
            extra["comment"] = texts[2]
        rows.append(ParsedRow(name=texts[0], status=texts[1], updated_text=updated, extra=extra))
    if not rows:
        raise ShapeError("a School Information table with no rows (its empty form is unseen)")
    return Listing(
        variant="nexstar-school-information", state=ListingState.POPULATED, rows=tuple(rows)
    )


def parse_storm_tracker(html: str) -> Listing:
    """Read WTEN's STORM TRACKER file (``nexstar-storm-tracker``)."""
    stamp = _STORM_STAMP.search(html)
    if stamp is None:
        raise ShapeError("a STORM TRACKER file with no posted time")
    updated = collapse(stamp.group(1))
    rows = [
        ParsedRow(
            name=_plain(match.group(1)),
            status=_plain(match.group(2)),
            updated_text=updated,
            extra={"updated_scope": "page"},
        )
        for match in _STORM_ROW.finditer(html[stamp.end() :])
        if _plain(match.group(1)) and _plain(match.group(1)) != STORM_TRACKER_EMPTY
    ]
    if rows:
        return Listing(
            variant="nexstar-storm-tracker", state=ListingState.POPULATED, rows=tuple(rows)
        )
    if f"<b>{STORM_TRACKER_EMPTY}</b>" in html:
        return Listing(variant="nexstar-storm-tracker", state=ListingState.EMPTY, rows=())
    raise ShapeError("a STORM TRACKER file with no rows and no empty sentence")


def _is_clmod(text: str) -> bool:
    return _CLMOD.search(text) is not None and _PSG_TITLE not in text


def parse_clmod(html: str) -> Listing:
    """Read the Media General closings file of 2016 (``nexstar-clmod``): its empty form only."""
    blocks = _CLMOD_ALL.findall(html)
    if len(blocks) == 1 and _plain(blocks[0]) == CLMOD_EMPTY:
        return Listing(variant="nexstar-clmod", state=ListingState.EMPTY, rows=())
    raise ShapeError(
        "a Media General closings file in a form not yet seen (only its empty form is)"
    )


def _is_tribune_tab(text: str) -> bool:
    body = text.strip()
    return bool(_TAB_UPDATED.match(body) or _TAB_EMPTY.match(body))


def parse_tribune_tab(html: str) -> Listing:
    """Read one tab file of the Tribune tab pages (``nexstar-tribune-tab``)."""
    body = html.strip()
    if _TAB_EMPTY.match(body):
        return Listing(variant="nexstar-tribune-tab", state=ListingState.EMPTY, rows=())
    heading = _TAB_UPDATED.match(body)
    if heading is None:
        raise ShapeError("not a Tribune tab file")
    tab, updated = collapse(heading.group(1)), collapse(heading.group(2))
    rows: list[ParsedRow] = []
    for item in _TAB_ITEM.finditer(body):
        name = _plain(item.group(2)).removesuffix("|").strip()
        if not name:
            raise ShapeError("a Tribune tab item with no name")
        extra: dict[str, JsonScalar] = {
            "tab": tab,
            "letter": item.group(1).lower().removeprefix("ln-"),
            "updated_scope": "page",
        }
        rows.append(
            ParsedRow(name=name, status=_plain(item.group(3)), updated_text=updated, extra=extra)
        )
    if body.count("<li") != len(rows):
        raise ShapeError("a Tribune tab item this adapter cannot read")
    if not rows:
        raise ShapeError("a Tribune tab file with its update time and no rows")
    return Listing(variant="nexstar-tribune-tab", state=ListingState.POPULATED, rows=tuple(rows))


def _column(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")


def parse_scn(html: str) -> Listing:
    """Read a School Closings Network ``report.php`` table."""
    tree = parse_html(html)
    table = tree.css_first("table")
    if table is None:
        raise ShapeError("the School Closings Network report has no table")
    header = [node_text(th) for th in table.css("thead th")]
    if "School Name" not in header or "Status" not in header:
        raise ShapeError(f"the report's header is not the known one: {header}")
    rows: list[ParsedRow] = []
    skipped = 0
    for tr in table.css("tbody tr"):
        cells = [node_text(td) for td in tr.css("td")]
        if len(cells) != len(header):
            raise ShapeError(f"a report row has {len(cells)} cells for {len(header)} columns")
        values = dict(zip(header, cells, strict=True))
        extra: dict[str, JsonScalar] = {
            _column(key): value
            for key, value in values.items()
            if key not in {"School Name", "Status"}
        }
        if not values["School Name"]:
            skipped += 1
            continue
        rows.append(ParsedRow(name=values["School Name"], status=values["Status"], extra=extra))
    if skipped and not rows:
        raise ShapeError("every report row is missing its school name")
    return Listing(
        variant="schoolclosingsnet-table",
        state=ListingState.POPULATED if rows else ListingState.EMPTY,
        rows=tuple(rows),
        skipped_rows=skipped,
    )


# Dispatch ----------------------------------------------------------------------------------


def _parse_json(data: object, *, typed_beside: bool) -> Listing:
    if isinstance(data, list):
        if _is_feed(data):
            return parse_feed(data)
        if all(_is_page(item) for item in data):
            pages = [item for item in data if isinstance(item, Mapping)]
            return parse_rest_pages(pages, typed_beside=typed_beside)
        raise ShapeError("a JSON array that is neither the app feed nor REST pages")
    if isinstance(data, Mapping):
        if _is_page(data):
            return parse_rest_pages([data], typed_beside=typed_beside)
        if "$" in data:
            return parse_ecc(data)
    raise ShapeError("a JSON document this adapter does not know")


def _alert_range(node: Node) -> str:
    ranges = [m.group(1) for cls in _classes(node) if (m := _ALERTS_RANGE.match(cls))]
    if len(ranges) != 1:
        raise ShapeError("a Closing Alerts block without its letter range")
    return ranges[0]


def _alert_rows(block: Node, letters: str) -> list[ParsedRow]:
    """The organizations of one ``mod-inline`` block: each ``<h4>`` and the list after it."""
    rows: list[ParsedRow] = []
    name: str | None = None
    for node in block.iter():
        if node.tag == "h4":
            if name is not None:
                raise ShapeError(f"Closing Alerts name {name!r} has no status list")
            name = node_text(node)
        elif node.tag == "div" and "mod-body" in _classes(node):
            if name is None:
                raise ShapeError("a Closing Alerts status list without a name")
            status = SEPARATOR.join(node_text(item) for item in node.css("li"))
            if name:
                rows.append(ParsedRow(name=name, status=status, extra={"range": letters}))
            name = None
        else:
            raise ShapeError(f"unexpected {node.tag} in a Closing Alerts block")
    if name is not None:
        raise ShapeError(f"Closing Alerts name {name!r} has no status list")
    return rows


def parse_closing_alerts(html: str) -> Listing:
    """Read the ``nexstar-closing-alerts`` module (the Liferay-era sites)."""
    match = _ALERTS.search(html)
    if match is None:
        raise ShapeError("no Closing Alerts module")
    section = parse_html(html[match.start() : element_end(html, match.start(), "section")])
    body = section.css_first("section#closingAlertPage > div.mod-body")
    if body is None:
        raise ShapeError("a Closing Alerts module without its body")
    rows: list[ParsedRow] = []
    sentences: list[str] = []
    for node in body.iter():
        classes = _classes(node)
        if node.tag == "div" and "mod-inline" in classes:
            rows.extend(_alert_rows(node, _alert_range(node)))
        elif node.tag == "p" and "mod-tab-desc" in classes:
            _alert_range(node)
            sentences.append(node_text(node))
        else:
            raise ShapeError(f"unexpected {node.tag} in the Closing Alerts body")
    if any(sentence != ALERTS_EMPTY for sentence in sentences):
        raise ShapeError("a Closing Alerts tab with a sentence this adapter does not know")
    if rows:
        return Listing(
            variant="nexstar-closing-alerts", state=ListingState.POPULATED, rows=tuple(rows)
        )
    if sentences:
        return Listing(variant="nexstar-closing-alerts", state=ListingState.EMPTY, rows=())
    raise ShapeError("the Closing Alerts module has no rows and no no-alerts sentence")


def _is_newsticker_table(text: str) -> bool:
    return _NT_TABLE_ROW.search(text) is not None


_HTML_FILES: tuple[tuple[Callable[[str], bool], Callable[[str], Listing]], ...] = (
    (lambda text: _PSG_TITLE in text, parse_psg),
    (lambda text: _SCN_TITLE in text, parse_scn),
    (lambda text: CGS_MARK in text, parse_cgs),
    (_is_newsticker_table, parse_newsticker_table),
    (lambda text: SCHOOL_INFO_MARK in text, parse_school_information),
    (lambda text: STORM_TRACKER_MARK in text, parse_storm_tracker),
    (_is_tribune_tab, parse_tribune_tab),
    (_is_clmod, parse_clmod),
)
"""The HTML list files read here, each with the test that recognizes it, in order."""


def parse(body: bytes) -> Listing:
    """Read one Nexstar closings body, live or archived, in whichever known variant it is.

    A page that types closings beside its closings article is an error here (see
    ``nexstar-wp-typed-beside``): only :func:`parse_typed` reads such entries.
    """
    return _parse(body, typed_beside=False)


def _parse(body: bytes, *, typed_beside: bool) -> Listing:
    raw = decode(body)
    text = text_of(raw)
    head = text.lstrip()
    if head.startswith(("{", "[")):
        return _parse_json(json_value(head), typed_beside=typed_beside)
    if _ARTICLE.search(text):
        return _article_listing(
            text,
            "nexstar-page",
            rest=False,
            typed_beside=typed_beside,
            modified=typed.html_modified(text),
        )
    reader = next((reader for test, reader in _HTML_FILES if test(text)), None)
    if reader is not None:
        return reader(text)
    if gray_files.is_file(raw):
        return gray_files.parse(raw)
    if _frames(text) or _feeds(text) or _FRANKLY.search(text):
        return _page_listing(text, "nexstar-page", "nexstar-page-frame")
    if _ALERTS.search(text):
        return parse_closing_alerts(text)
    raise ShapeError("not a Nexstar closings body this adapter knows")


def _knows_body(raw: bytes, text: str) -> bool:
    """Whether a body holds a list :func:`parse` reads (a closings article, frame, feed,
    Closing Alerts module or list file), whether or not it read it."""
    return bool(
        _knows_page(text)
        or _ALERTS.search(text)
        or any(test(text) for test, _reader in _HTML_FILES)
        or gray_files.is_file(raw)
    )


def parse_typed(body: bytes) -> Listing:
    """Read one closings body of a station the registry files as typing its closings by hand.

    Every variant :func:`parse` reads is read the same way. A body it refuses is read
    as a closings page typed by hand when it is one: a single REST page object
    (``nexstar-wp-typed``) or an HTML page (``nexstar-typed-page``) with no list
    :func:`parse` knows, no login form, and a title that says it is a closings page
    (see :mod:`snowlight.sources.stations.typed`). This is the ``parse`` of the
    ``nexstar-typed`` adapter (:mod:`snowlight.sources.stations.nexstar_typed`);
    :func:`parse`, every other Nexstar station's, never reads a typed page, so a
    missing, blank or script-filled list there is an error.

    Raises:
        ShapeError: :func:`parse` refuses the body and it is no typed closings page, or
            a typed page holds no row and does not say it holds none.
    """
    try:
        return _parse(body, typed_beside=True)
    except ShapeError:
        raw = decode(body)
        text = text_of(raw)
        head = text.lstrip()
        if head.startswith(("{", "[")):
            data = json_value(head)
            pages = data if isinstance(data, list) else [data]
            if len(pages) == 1 and _is_page(pages[0]) and isinstance(pages[0], Mapping):
                page = pages[0]
                if _is_typed_rest(page, _rendered(page)):
                    return _typed_rest(page, _rendered(page))
            raise
        if _knows_body(raw, text) or _typed_block(text) is None:
            raise
        return parse_typed_page(text)


# Fixtures ------------------------------------------------------------------------------------


def _cut_content(html: str, frames: Callable[[str], list[str]], shortcode: re.Pattern[str]) -> str:
    """The closings article of a page's content, or its frames, byte for byte."""
    match = _ARTICLE.search(html)
    if match is not None:
        return html[match.start() : element_end(html, match.start(), "article")]
    kept = [tag for tag in iframe_tags(html) if frames(tag)]
    kept += [m.group(0) for m in shortcode.finditer(html) if m.group(1)]
    kept += [tag + "</div>" for tag in _FEED_DIV.findall(html) if _FEED_ATTR.search(tag)]
    if not kept:  # pragma: no cover - callers cut only content with an article or a frame
        raise ShapeError("nothing to keep: no closings article and no list frame")
    return "\n".join(kept)


def _cut_page_object(page: Mapping[str, object]) -> dict[str, object]:
    kept: dict[str, object] = {
        key: page[key] for key in ("id", "link", "modified_gmt", "slug") if key in page
    }
    html = _rendered(page)
    # A page with neither the article nor a list frame (an older page sharing the
    # slug) keeps an empty content: the reader passes over it either way.
    kept["content"] = {
        "rendered": _cut_content(html, _frames_v1, _SHORTCODE_V1)
        if _ARTICLE.search(html) or _frames_v1(html)
        else ""
    }
    return kept


def slice_body(body: bytes) -> bytes:
    """Cut a Nexstar body down to what :func:`parse` reads (for test fixtures): ``nexstar-v1``.

    A REST page (or array of pages) keeps only its ``id``, ``link``,
    ``modified_gmt`` and ``slug`` and, of its content, the closings article (or
    the list frames), byte for byte, written as compact JSON with sorted keys. An
    HTML page keeps its closings article (or list frames) in a minimal document.
    The app feed, the ECC file and the frame files are small and kept whole
    (decoded). The slice must read exactly as the original does. (The frames of
    the Tribune-era pages and the script-filled pages are cut by
    :func:`slice_body_v2`.)
    """
    raw = decode(body)
    text = text_of(raw)
    head = text.lstrip()
    if head.startswith(("{", "[")):
        data = json_value(head)
        if _is_page(data) and isinstance(data, Mapping):
            cut: object = _cut_page_object(data)
        elif isinstance(data, list) and data and all(_is_page(item) for item in data):
            cut = [_cut_page_object(item) for item in data if isinstance(item, Mapping)]
        else:
            return raw
        return json.dumps(cut, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if _ARTICLE.search(text) or (
        _frames_v1(text) and _PSG_TITLE not in text and _SCN_TITLE not in text
    ):
        if gray_files.is_file(raw):
            return raw
        return minimal_document([_cut_content(text, _frames_v1, _SHORTCODE_V1)])
    return raw


def _whole_file(text: str) -> bool:
    return any(
        (
            _PSG_TITLE in text,
            _SCN_TITLE in text,
            CGS_MARK in text,
            _is_newsticker_table(text),
            SCHOOL_INFO_MARK in text,
            STORM_TRACKER_MARK in text,
            _is_tribune_tab(text),
            _is_clmod(text),
        )
    )


def _v1_cuts(text: str) -> bool:
    """Whether ``nexstar-v1`` cuts this HTML body (rather than keeping it whole)."""
    return bool(
        _ARTICLE.search(text)
        or (_frames_v1(text) and _PSG_TITLE not in text and _SCN_TITLE not in text)
    )


def slice_body_v2(body: bytes) -> bytes:
    """``nexstar-v2``: :func:`slice_body`, extended to the archived page variants.

    Every body ``nexstar-v1`` cuts (a REST page, an HTML page with the closings
    article or a frame ``v1`` knows) is cut to the same bytes, and the files ``v1``
    keeps whole are kept whole. An HTML page that ``v1`` keeps whole because its
    frames or feed are ones only this version knows (the Tribune-era frames and
    shortcodes, a script-filled page's ``data-feed``) keeps those frames, shortcodes
    and ``data-feed`` elements in a minimal document (WOWK's PSG page and the
    Tribune tab pages, small files, are kept whole). The list files of the
    archived variants (CGS, the NewsTicker table, the School Information table,
    the STORM TRACKER file, the Tribune tab files, the 2016 Media General file) are
    small and kept whole. A
    Liferay-era page with the Closing Alerts module (and none of the above) keeps
    that module's ``<section>``, byte for byte, in a minimal document; ``v2``
    refused such pages and those files before, so no earlier slice changes.
    """
    raw = decode(body)
    text = text_of(raw)
    if (
        text.lstrip().startswith(("{", "["))
        or _v1_cuts(text)
        or _whole_file(text)
        or gray_files.is_file(raw)
        or _XML_DOC.search(text)
        or _TABS_LOAD.search(text)
    ):
        return slice_body(body)
    if _frames(text) or any(_FEED_ATTR.search(tag) for tag in _FEED_DIV.findall(text)):
        return minimal_document([_cut_content(text, _frames, _SHORTCODE)])
    alerts = _ALERTS.search(text)
    if alerts is not None:
        end = element_end(text, alerts.start(), "section")
        return minimal_document([text[alerts.start() : end]])
    raise ShapeError("not a Nexstar closings body this adapter knows")


def _typed_rest_cut(data: object) -> bytes | None:
    """A REST page typed by hand, cut for a fixture: its ids, title, time and whole content."""
    pages = data if isinstance(data, list) else [data]
    if len(pages) != 1 or not _is_page(pages[0]) or not isinstance(pages[0], Mapping):
        return None
    page = pages[0]
    if not _is_typed_rest(page, _rendered(page)):
        return None
    kept = {
        key: page[key] for key in ("id", "link", "modified_gmt", "slug", "title") if key in page
    }
    kept["content"] = {"rendered": _rendered(page)}
    cut: object = [kept] if isinstance(data, list) else kept
    return json.dumps(cut, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def slice_body_v3(body: bytes) -> bytes:
    """``nexstar-v3``: :func:`slice_body_v2`, extended to closings typed by hand.

    Every body ``nexstar-v2`` cuts is cut to the same bytes. A REST page whose
    content is typed by hand (``nexstar-wp-typed``) keeps its ``id``, ``link``,
    ``modified_gmt``, ``slug`` and ``title`` and its whole content; an HTML page
    typed by hand (``nexstar-typed-page``) keeps the tag that gives its title
    (``og:title``, else ``<title>``), the tag that gives its time (see
    :func:`~snowlight.sources.stations.typed.time_tags`) and its
    ``div.article-content``, byte for byte, in a minimal document. (``v2`` cut
    such a REST page's content away and refused such an HTML page.)
    """
    raw = decode(body)
    text = text_of(raw)
    head = text.lstrip()
    if head.startswith(("{", "[")):
        cut = _typed_rest_cut(json_value(head))
        return cut if cut is not None else slice_body_v2(body)
    try:
        return slice_body_v2(body)
    except ShapeError:
        found = _typed_block(text, entry_content=False)
        if found is None:
            raise
        return minimal_document([*_title_tags(text), *typed.time_tags(text), found[0]])


def _has_beside(html: str, *, rest: bool) -> bool:
    """Whether a page's content holds entries typed beside its closings article."""
    block = _beside_block(html, rest=rest)
    return block is not None and bool(typed.entries_beside(block))


def _container_span(html: str) -> tuple[int, int] | None:
    """Where the rich-text block around an HTML page's closings article starts and ends."""
    article = _ARTICLE.search(html)
    if article is None:
        return None
    article_end = element_end(html, article.start(), "article")
    found: tuple[int, int] | None = None
    for match in _DIV_OPEN.finditer(html, 0, article.start()):
        classes = _CLASS_ATTR.search(match.group(0))
        if classes is not None and "article-content" in classes.group(1).split():
            end = element_end(html, match.start(), "div")
            if end >= article_end:
                found = (match.start(), end)
    return found


def slice_body_v4(body: bytes) -> bytes:
    """``nexstar-v4``: :func:`slice_body_v3`, extended to entries typed beside the closings
    article and to the Tribune-era typed page.

    Every body ``nexstar-v3`` cuts is cut to the same bytes, except a page whose
    content holds entries typed beside its closings article (``v3`` cut them away
    with the rest of the page): a REST page keeps its ``id``, ``link``,
    ``modified_gmt``, ``slug`` and ``title`` and its whole content; an HTML page
    keeps the tag that gives its title, the tag that gives its time and the
    rich-text block that holds the article and the entries, byte for byte, in a
    minimal document. A Tribune-era page typed by hand
    (``nexstar-typed-entry-content``, which ``v3`` refused) keeps its title tag,
    its time tag and its ``div.entry-content``.
    """
    raw = decode(body)
    text = text_of(raw)
    head = text.lstrip()
    if head.startswith(("{", "[")):
        data = json_value(head)
        pages: list[object] = data if isinstance(data, list) else [data]
        whole = [
            isinstance(page, Mapping) and _is_page(page) and _has_beside(_rendered(page), rest=True)
            for page in pages
        ]
        if not any(whole):
            return slice_body_v3(body)
        kept = [
            _whole_page_object(page) if keep else _cut_page_object(page)
            for page, keep in zip(pages, whole, strict=True)
            if isinstance(page, Mapping)
        ]
        cut: object = kept if isinstance(data, list) else kept[0]
        return json.dumps(cut, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if _ARTICLE.search(text) and _has_beside(text, rest=False):
        span = _container_span(text)
        if span is None:
            raise ShapeError("entries typed beside a closings article outside any rich-text block")
        block = text[span[0] : span[1]]
        return minimal_document([*_title_tags(text), *typed.time_tags(text), block])
    try:
        return slice_body_v3(body)
    except ShapeError:
        found = _typed_block(text)
        if found is None:
            raise
        return minimal_document([*_title_tags(text), *typed.time_tags(text), found[0]])


def _whole_page_object(page: Mapping[str, object]) -> dict[str, object]:
    kept = {
        key: page[key] for key in ("id", "link", "modified_gmt", "slug", "title") if key in page
    }
    kept["content"] = {"rendered": _rendered(page)}
    return kept


def _title_tags(html: str) -> list[str]:
    """The whole tag :func:`_page_title` reads the title from (``og:title``, else ``<title>``)."""
    og = _OG_TITLE.search(html)
    if og is not None:
        return [html[og.start() : html.index(">", og.end()) + 1]]
    title = _TITLE_TAG.search(html)
    return [title.group(0)] if title is not None else []
