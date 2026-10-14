"""Blackboard Web Community Manager district homepages: the announcements apps.

Before many districts moved their sites to Apptegy, ParentSquare Smart Sites or
Finalsite's current template, their homepages were Blackboard Web Community
Manager (WCM, "Schoolwires") sites. :mod:`snowlight.sources.stations.schoolwires`
reads the homepages that carry WCM's "Important Announcement" app; others posted
their urgent notices in an announcements app on the homepage instead, which WCM
renders into the page as served. Archived captures of those homepages hold them,
for example Clarke County's on 2020-10-30 (Hurricane Zeta)::

    <div class="ui-widget app announcements">
      <div class="ui-widget-header"><h1>Announcements</h1></div>
      <div class="ui-widget-detail"><ul class="ui-articles">
        <li><div class="ui-article"><div class="ui-article-description">
          <span><h2>ALL CLARKE COUNTY SCHOOLS ARE CLOSED FRIDAY, 10/30 DUE TO DAMAGE
          FROM HURRICANE ZETA</h2> ...

and Charlotte County's on 2023-08-30 (Tropical Storm Idalia), a headlines app the
district titled "Breaking News"::

    <div class="ui-widget app headlines"><div class="ui-widget-header"><h1>Breaking News</h1>
      ... <h1 class="ui-article-title"><a ...><span>Tropical Storm Idalia Announcement -
      8/28/23</span></a></h1>
      <p class="ui-article-description">To help our families remain safe and prepared,
      Charlotte County Schools will be closed on Tuesday, August 29 and Wednesday, August 30 ...

The Apptegy, Smart Sites and Finalsite adapters read such a capture of their
station's homepage with :func:`parse_text`, after the forms they read first
(Schoolwires' important announcements among them).

Variant this module reads:

``wcm-announcements``
    Every WCM app on the page (``div.ui-widget.app``) that is the district's
    announcements: the Announcements app (class ``announcements``), whatever its
    title, and a Headlines & Features app (class ``headlines``) whose title names
    it as announcements, alerts or the district's information (:data:`CHANNEL_TITLE`:
    "Announcements", "District Announcements", "Breaking News", "Alerts", "Urgent",
    "Emergency", "Important", "District Information": Great Falls kept its notices in
    an announcements app titled "District Information" in 2022 and in a headlines app
    of the same title in 2023 and 2024); a headlines app titled otherwise ("District
    News", "Top Stories", "PCS Newsroom") is the district's news, not its notices,
    and is not read.
    Each article (``.ui-article`` in ``ul.ui-articles``) is one row.

A row's ``raw_name`` is the site's name (the page title before " / ", "Clarke
County Schools"; the article names no school, and the station's ``leaids`` say
whose it is), ``raw_status`` the article's words (its title, then its
description; words past the status limit are cut with an ellipsis), no
``raw_updated_text`` (an app shows a date only when the district typed one), and
``raw_extra`` ``app`` (``announcements`` or ``headlines``), ``app_title``,
``module_id`` (the app's ``module-content-N`` number) and ``links`` (the article's
link targets). An article with no words is a skipped row. An app
with no article is an empty list. A page with no such app raises
:class:`~snowlight.sources.stations.model.ShapeError` (it is not this format, or
the district kept no announcements app on its homepage).

The on-screen alert: a WCM homepage also fetches the district's on-screen alert
after it loads, by script, from the site's alert file (Broward's homepage of
2024-10-09)::

    GetContent(homeURL + "/cms/Tools/OnScreenAlerts/UserControls/
        OnScreenAlertDialogListWrapper.aspx?OnScreenAlertCookie=" + onscreenAlertCookie
        + "&SiteID=4", "onscreenalert-holder", 2, "OnScreenAlertCheckListItem();");

(one line in the page, broken here; ``SiteID`` names the site: the district's
own, or one of its schools'). A page
with the announcements app names that file beside its list
(``Listing.also_loads``); a page with the loader and no such app is
``wcm-alert-page``, a deferred page that loads its list from that file
(``Listing.follows``). :func:`alert_file` finds the file's address as the page
names it (the cookie left empty, as for a first visit).

``wcm-onscreen-alert``
    The on-screen alert file itself (Broward's of 2022-09-28 00:17 UTC, Hurricane
    Ian: "Broward County Public Schools and District offices will be closed on
    Wednesday, September 28, 2022, and Thursday, September 29, 2022, due to impacts
    from Hurricane Ian."): a fragment holding ``div#onscreenalert-ctrl-msglist``,
    and in it, while an alert is up, ``ul#onscreenalertdialoglist`` with one
    ``li[id]`` per alert. A fragment whose message list holds no such list (the
    heading ``span.titleMessage`` then empty) is an empty list.

    Each alert is one row: ``raw_name`` its first line (the first paragraph or
    block with words: the alert's own title, "BCPS Update on School Operations Due
    to Hurricane Ian"; the file names no district, and the station's ``leaids`` say
    whose it is), ``raw_status`` the alert's words, lines joined (cut at the status
    limit), no ``raw_updated_text`` (an alert shows a time only when the district
    typed one), and ``raw_extra`` ``alert_id`` (the item's ``id``), ``heading`` (the
    dialog's heading, "Important Message") and ``links`` (the alert's link
    targets). An alert with no words is a skipped row. A body without the message
    list raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import re
from html import escape

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations.gap_markup import (
    clip,
    collapse,
    deferred,
    document,
    html_text,
    make_listing,
    make_row,
    node_text,
)
from snowlight.sources.stations.model import MAX_STATUS, JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "wcm-announcements"
ALERT_PAGE_VARIANT = "wcm-alert-page"
ALERT_VARIANT = "wcm-onscreen-alert"
ALERT_LIST = "#onscreenalert-ctrl-msglist"
_BREAKS = re.compile(r"<br\s*/?>|</(?:p|div|h[1-6]|li|ul|ol|tr)\s*>", re.IGNORECASE)
"""A line break or the end of a block: where an alert's lines part."""
_LOADER = re.compile(
    r'"(/cms/Tools/OnScreenAlerts/UserControls/OnScreenAlertDialogListWrapper\.aspx'
    r'\?OnScreenAlertCookie=)"\s*\+\s*[A-Za-z_$][\w$]*(?:\s*\+\s*"(&(?:amp;)?SiteID=\d+)")?',
    re.IGNORECASE,
)
"""The homepage script's call that fetches the site's on-screen alert file (older WCM
versions name no ``SiteID``: the file then answers for the site the homepage is)."""
APP = "div.ui-widget.app"
CHANNEL_TITLE = re.compile(
    r"\bannouncements?\b|\balerts?\b|\bbreaking\s+news\b|\burgent\b|\bemergency\b|\bimportant\b"
    r"|\binformation\b",
    re.IGNORECASE,
)
"""A headlines app's title that names it as the district's announcements or alerts."""
_MODULE = re.compile(r"^module-content-(\d+)$")


def _kind(app: Node) -> str | None:
    classes = str(app.attributes.get("class") or "").split()
    if "announcements" in classes:
        return "announcements"
    if "headlines" in classes:
        return "headlines"
    return None


def _title(app: Node) -> str:
    return node_text(app.css_first(".ui-widget-header"))


def channel_apps(tree: HTMLParser) -> list[tuple[Node, str, str]]:
    """Return the page's announcements apps, each with its kind and title."""
    found: list[tuple[Node, str, str]] = []
    for app in tree.css(APP):
        kind = _kind(app)
        if kind is None:
            continue
        title = _title(app)
        if kind == "headlines" and not CHANNEL_TITLE.search(title):
            continue
        found.append((app, kind, title))
    return found


def holds_announcements(text: str) -> bool:
    """Whether a page has a WCM announcements app (see the module docstring)."""
    if "ui-widget app" not in text:
        return False
    return bool(channel_apps(HTMLParser(text)))


def _site_name(tree: HTMLParser) -> str:
    title = tree.css_first("title")
    name = collapse(title.text()).split(" / ")[0] if title is not None else ""
    if not name:
        raise ShapeError("the Web Community Manager page has no title to name the district by")
    return name


def _module_id(app: Node) -> str | None:
    node: Node | None = app.parent
    while node is not None:
        found = _MODULE.match(str(node.attributes.get("id") or ""))
        if found is not None:
            return found.group(1)
        node = node.parent
    return None


def _words(article: Node) -> str:
    title = article.css_first(".ui-article-title")
    description = article.css_first(".ui-article-description")
    parts = [node_text(title), node_text(description)]
    if not any(parts):
        # An article that is neither titled nor described keeps its words elsewhere.
        clone = HTMLParser(article.html or "")
        for control in clone.css(".ui-article-controls"):
            control.decompose()
        return node_text(clone.body)
    return collapse(" ".join(part for part in parts if part))


def alert_file(text: str) -> str | None:
    """The on-screen alert file a WCM homepage fetches, as it names it, or None.

    The address is the one the page asks for on a first visit (its alert cookie
    empty), such as ``/cms/Tools/OnScreenAlerts/UserControls/`` then
    ``OnScreenAlertDialogListWrapper.aspx?OnScreenAlertCookie=&SiteID=4``.
    """
    found = _LOADER.search(text)
    if found is None:
        return None
    return found.group(1) + (found.group(2) or "").replace("&amp;", "&")


def holds_alert_dialog(text: str) -> bool:
    """Whether a body is a WCM on-screen alert file (its message list)."""
    return (
        "onscreenalert-ctrl-msglist" in text and HTMLParser(text).css_first(ALERT_LIST) is not None
    )


def _alert_lines(item: Node) -> list[str]:
    """The alert's lines: its text broken at each line break and block, blanks dropped."""
    marked = _BREAKS.sub(lambda found: found.group(0) + "\n", item.html or "")
    root = HTMLParser(marked).body
    text = root.text(deep=True, separator="") if root is not None else ""
    return [line for line in (collapse(part) for part in text.split("\n")) if line]


def parse_alert_dialog(text: str) -> Listing:
    """Read a WCM on-screen alert file (``text`` is the fragment the homepage loaded)."""
    tree = HTMLParser(text)
    holder = tree.css_first(ALERT_LIST)
    if holder is None:
        raise ShapeError("no on-screen alert message list: not a WCM on-screen alert file")
    heading = node_text(tree.css_first("span.titleMessage")) or None
    rows: list[ParsedRow] = []
    skipped = 0
    for item in holder.css("ul#onscreenalertdialoglist > li"):
        lines = _alert_lines(item)
        if not lines:
            skipped += 1
            continue
        links = [
            href
            for anchor in item.css("a")
            if isinstance(href := anchor.attributes.get("href"), str) and href
        ]
        extra: dict[str, JsonScalar] = {
            "alert_id": collapse(str(item.attributes.get("id") or "")) or None,
            "heading": heading,
            "links": " ".join(links) or None,
        }
        row = make_row(lines[0], clip(node_text(item), MAX_STATUS), None, extra)
        if row is None:  # pragma: no cover - a line has words
            skipped += 1
        else:
            rows.append(row)
    return make_listing(ALERT_VARIANT, rows, skipped=skipped)


def holds_alert_loader(text: str) -> bool:
    """Whether a page's script loads a WCM on-screen alert file (see :func:`alert_file`)."""
    return alert_file(text) is not None


def alert_page(text: str) -> Listing:
    """Read a WCM homepage with no announcements app: it loads its on-screen alert file."""
    target = alert_file(text)
    if target is None:
        raise ShapeError("no Web Community Manager on-screen alert loader on the page")
    return deferred(ALERT_PAGE_VARIANT, (target,))


def parse_text(text: str) -> Listing:
    """Read a WCM homepage's announcements apps (``text`` is the page).

    The page's on-screen alert file, when it loads one, is named beside the list
    (``also_loads``).
    """
    listing = _announcements(text)
    target = alert_file(text)
    if target is None:
        return listing
    return Listing.model_validate({**listing.model_dump(), "also_loads": (target,)})


def _announcements(text: str) -> Listing:
    tree = HTMLParser(text)
    apps = channel_apps(tree)
    if not apps:
        raise ShapeError("no Web Community Manager announcements app on the page")
    name = _site_name(tree)
    rows: list[ParsedRow] = []
    skipped = 0
    for app, kind, title in apps:
        module = _module_id(app)
        for article in app.css("ul.ui-articles .ui-article"):
            words = _words(article)
            if not words:
                skipped += 1
                continue
            links = [
                href
                for anchor in article.css("a")
                if isinstance(href := anchor.attributes.get("href"), str)
                and href
                and "Comments=true" not in href
            ]
            extra: dict[str, JsonScalar] = {
                "app": kind,
                "app_title": title or None,
                "module_id": module,
                "links": " ".join(links) or None,
            }
            row = make_row(name, clip(words, MAX_STATUS), None, extra)
            if row is None:  # pragma: no cover - the name was checked above
                skipped += 1
            else:
                rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep the page title and the announcements apps, each in its module's wrapper.

    The slice is a minimal document that reads exactly as the page does (scripts
    and styles dropped); a page without such an app slices to an empty document.
    """
    tree = HTMLParser(html_text(body))
    apps = channel_apps(tree)
    if not apps:
        return document("")
    title = tree.css_first("title")
    head = f"<title>{escape(title.text(), quote=False)}</title>" if title is not None else ""
    kept: list[str] = []
    for app, _kind_name, _title_text in apps:
        for junk in app.css("style, script"):
            junk.decompose()
        module = _module_id(app)
        inner = app.html or ""
        kept.append(f'<div id="module-content-{module}">{inner}</div>' if module else inner)
    return document(head + "".join(kept))


def slice_body_v2(body: bytes) -> bytes:
    """Keep what :func:`slice_body` keeps, and the page's on-screen alert loader.

    The loader's call (as :data:`_LOADER` matches it) is kept alone in a
    ``<script>`` element, so the slice names the same alert file as the page; the
    rest of the page's scripts are dropped. A page with neither an announcements app
    nor the loader slices to an empty document.
    """
    text = html_text(body)
    found = _LOADER.search(text)
    tree = HTMLParser(text)
    apps = channel_apps(tree)
    if not apps and found is None:
        return document("")
    title = tree.css_first("title")
    head = f"<title>{escape(title.text(), quote=False)}</title>" if title is not None else ""
    kept: list[str] = []
    for app, _kind_name, _title_text in apps:
        for junk in app.css("style, script"):
            junk.decompose()
        module = _module_id(app)
        inner = app.html or ""
        kept.append(f'<div id="module-content-{module}">{inner}</div>' if module else inner)
    if found is not None:
        kept.append(f"<script>{found.group(0)}</script>")
    return document(head + "".join(kept))
