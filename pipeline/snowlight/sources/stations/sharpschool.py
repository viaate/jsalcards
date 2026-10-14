"""SharpSchool district sites: the homepage's emergency alerts, and the forms before them.

SharpSchool (Finalsite's older district platform) serves the homepages of the
School District of Lee County, Marion County Public Schools and Polk County Public
Schools (Florida). Today their homepage shows the district's emergency alerts in a
React component (``unifiedPublishingAlertComponent``) that asks for them after the
page loads: its script (``unifiedPublishingAlert.js``) POSTs ``{"returnDummyAlerts":
false}`` as JSON to the site's
``/WebServices/UnifiedPublishing/UnifiedPublishingService.asmx/GetActiveAlerts`` and
reads the answer's ``d`` list (``AlertId``, ``Title``, ``Body``, ``AlertType``,
``Expiry``). The service answers only POST (a GET answers HTTP 500), so the station's
``data_url`` is the service and its ``data_post`` the script's body
(:class:`~snowlight.sources.stations.registry.Station`). The archive keeps no answer
to a POST: only captures of the homepage itself can show what the district posted,
and they show it in the forms the homepage had before the component:

* Lee's SharpSchool homepage of 2019-2024 led with a hero slider whose first slide
  the district used for storms ("Hurricane Ian: ... has made the decision to close
  all schools and District offices next week (October 3-7, 2022)", captured
  2022-10-04 03:52 UTC);
* Marion's homepage was a Web Community Manager site until 2024, whose
  announcements app carried the closures of Hurricane Ian ("Marion County Public
  Schools is closed Wednesday, Thursday and Friday due to Hurricane Ian", captured
  2022-09-27 23:56 UTC) and Tropical Storm Idalia: read by
  :mod:`snowlight.sources.stations.wcm`;
* Polk's homepage of 2022 was a WordPress page whose Smart Slider 3 sliders (the
  ``n2-ss`` plugin) carried a storm slide ("Public schools in Polk County will be
  closed Tuesday (Sept. 27) through Thursday (Sept. 29) in response to Hurricane
  Ian", captured 2022-09-28 10:03 UTC).

Variants this adapter reads:

``sharpschool-alerts``
    The service's JSON answer: one row per alert in ``d``; ``{"d":[]}`` is an empty
    list. An alert whose ``AlertId`` is the all-zero GUID is one of the service's
    sample alerts (what ``returnDummyAlerts: true`` asks for), never the district's:
    the answer raises :class:`~snowlight.sources.stations.model.ShapeError`.
``sharpschool-slider``
    An archived homepage with the hero slider (``div.advanced-data-display``
    holding ``div.main-slider`` and its ``div.slide`` items, each with a
    ``div.caption`` of a heading and a paragraph): one row per slide. (A homepage
    with a slider holds its list in the page, whether or not it also has the alert
    component, so it is read as its slider: the component's alerts are not in the
    archive.)
``sharpschool-banner-slider``
    An archived homepage with the banner rotator (``div.advanced-data-display``
    holding ``div.flexslider`` and its ``ul.slides > li`` items, each a linked image
    and, on most, a ``div.banner-caption``): one row per slide. Orange County Public
    Schools' homepage of 2022-09-28 (Hurricane Ian): a slide named "Hurricane Ian",
    captioned "All Schools/District Offices Closed Wednesday, Thursday and Friday";
    of 2024-10-09 (Milton): "Hurricane Milton", its image titled "Click here for
    updated severe weather information.".
``sharpschool-homepage``
    An archived homepage with the alert component and no slider: a deferred page
    that loads its list from the alert service (which the archive never holds).
``wordpress-smartslider``
    An archived WordPress homepage with Smart Slider 3 sliders (``div.n2-ss-slider``,
    each ``div.n2-ss-slide`` titled by its ``data-title``): one row per slide whose
    layers (``.n2-ss-item-content``) hold text; a slide of images alone is skipped.
``wcm-announcements`` / ``wcm-alert-page`` / ``wcm-onscreen-alert``
    A Web Community Manager homepage, or its on-screen alert file, read by
    :mod:`snowlight.sources.stations.wcm`.

An alert is one row: ``raw_name`` its title as written (an alert names no school:
the station's ``leaids`` say whose it is), ``raw_status`` its body reduced to text,
``raw_updated_text`` its ``Modified`` stamp as the service writes it
(``/Date(<ms>)/``), and ``raw_extra`` ``alert_id``, ``alert_type`` and ``expiry``
(the ``Expiry`` stamp as an ISO time). A slide is one row: ``raw_name`` its heading
(else its image's ``alt`` text), ``raw_status`` its caption's paragraph, no
``raw_updated_text``, and ``raw_extra`` ``link`` (its "Learn More" target). A banner
slide is one row: ``raw_name`` its link's ``name`` (the title the site's editors gave
the slide, "Hurricane Ian"), else its image's ``alt`` text, else its caption;
``raw_status`` its caption, else its image's ``title`` or ``alt`` text when that is not
the name; and ``raw_extra`` ``link`` and ``image_alt``. A Smart
Slider slide is one row: ``raw_name`` its ``data-title`` (the name the site's editors
gave the slide, such as "Designer"), ``raw_status`` its layers' text, no
``raw_updated_text``, and ``raw_extra`` ``slider`` (the slider's ``id``). A row with no
name is skipped. A homepage in none of these forms is read by its text
(``homepage-text``), and a homepage read in one of them as its own list gets a
page-text row for each closing line its text shows that no row holds (a news item:
Orange's "School Board Meeting - CANCELED due to Tropical Storm Nicole"): see
:mod:`snowlight.sources.stations.homepage`. A body that is neither JSON nor an HTML
page raises ``ShapeError``.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html import escape
from typing import Any

from selectolax.parser import HTMLParser, Node

from snowlight.sources.stations import homepage, wcm
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

ALERTS_VARIANT = "sharpschool-alerts"
SLIDER_VARIANT = "sharpschool-slider"
HOMEPAGE_VARIANT = "sharpschool-homepage"
SERVICE_PATH = "/WebServices/UnifiedPublishing/UnifiedPublishingService.asmx/GetActiveAlerts"
"""The alert service the homepage's component posts to (relative to the site)."""
POST_BODY = '{"returnDummyAlerts":false}'
"""What the component's script posts (``unifiedPublishingAlert.js``)."""
COMPONENT = "unifiedPublishingAlertComponent"
SLIDER = "div.advanced-data-display div.main-slider"
BANNER_VARIANT = "sharpschool-banner-slider"
BANNER_SLIDER = "div.advanced-data-display div.flexslider"
SMART_VARIANT = "wordpress-smartslider"
SMART_SLIDER = "div.n2-ss-slider"
SAMPLE_ID = "00000000-0000-0000-0000-000000000000"
_STAMP = re.compile(r"^/Date\((-?\d+)\)/$")
_REQUIRED = ("AlertId", "Title", "Body", "AlertType", "Expiry")


def _stamp(value: object) -> str | None:
    """An ASP.NET ``/Date(<ms>)/`` stamp as an ISO time (None when it is not one)."""
    found = _STAMP.match(value) if isinstance(value, str) else None
    if found is None:
        return None
    moment = datetime.fromtimestamp(int(found.group(1)) / 1000, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(fragment: str) -> str:
    tree = HTMLParser(f"<div>{fragment}</div>")
    node = tree.css_first("div")
    return node_text(node) if node is not None else collapse(fragment)


def _alert(item: Any) -> ParsedRow | None:
    if not isinstance(item, dict) or any(key not in item for key in _REQUIRED):
        raise ShapeError(f"an alert without {', '.join(_REQUIRED)}")
    if item["AlertId"] == SAMPLE_ID:
        raise ShapeError("the service's sample alerts (all-zero AlertId), not the district's")
    body = item["Body"]
    extra: dict[str, JsonScalar] = {
        "alert_id": str(item["AlertId"]),
        "alert_type": str(item["AlertType"]) if item["AlertType"] is not None else None,
        "expiry": _stamp(item["Expiry"]),
    }
    modified = item.get("Modified")
    return make_row(
        str(item["Title"] or ""),
        clip(_text(body) if isinstance(body, str) else "", MAX_STATUS),
        modified if isinstance(modified, str) else None,
        extra,
    )


def _alerts(text: str) -> Listing:
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ShapeError(f"not a JSON answer: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("d"), list):
        raise ShapeError("a JSON answer without the service's 'd' list")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in data["d"]:
        row = _alert(item)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(ALERTS_VARIANT, rows, skipped=skipped)


def _slide(slide: Node) -> ParsedRow | None:
    caption = slide.css_first("div.caption")
    heading = caption.css_first("h1, h2, h3") if caption is not None else None
    image = slide.css_first("img[alt]")
    alt = image.attributes.get("alt") if image is not None else None
    name = node_text(heading) or (collapse(alt) if isinstance(alt, str) else "")
    words = node_text(caption.css_first("p")) if caption is not None else ""
    link = None
    for anchor in slide.css("a.cta[href]"):
        href = anchor.attributes.get("href")
        if isinstance(href, str) and href.strip() not in {"", "#"}:
            link = collapse(href)
    return make_row(name, clip(words, MAX_STATUS), None, {"link": link})


def _slider(slider: Node) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for slide in slider.css("div.slide"):
        row = _slide(slide)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(SLIDER_VARIANT, rows, skipped=skipped)


def _attr_text(node: Node | None, name: str) -> str:
    value = node.attributes.get(name) if node is not None else None
    return collapse(value) if isinstance(value, str) else ""


def _banner(slide: Node) -> ParsedRow | None:
    anchor = slide.css_first("a[href]")
    image = slide.css_first("img")
    caption = node_text(slide.css_first("div.banner-caption, div.flex-caption, div.caption"))
    alt = _attr_text(image, "alt")
    titled = _attr_text(image, "title") or alt
    name = _attr_text(anchor, "name") or alt or caption
    status = caption or (titled if titled != name else "")
    href = _attr_text(anchor, "href")
    extra: dict[str, JsonScalar] = {
        "link": href if href and href != "#" else None,
        "image_alt": alt or None,
    }
    return make_row(name, clip(status, MAX_STATUS), None, extra)


def _banners(slider: Node) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for slide in slider.css("ul.slides > li"):
        row = _banner(slide)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(BANNER_VARIANT, rows, skipped=skipped)


def _smart_sliders(sliders: list[Node]) -> Listing:
    rows: list[ParsedRow] = []
    skipped = 0
    for slider in sliders:
        ident = slider.attributes.get("id")
        for slide in slider.css("div.n2-ss-slide"):
            words = collapse(" ".join(node_text(item) for item in slide.css(".n2-ss-item-content")))
            title = slide.attributes.get("data-title")
            row = (
                make_row(
                    title if isinstance(title, str) else "",
                    clip(words, MAX_STATUS),
                    None,
                    {"slider": ident if isinstance(ident, str) else None},
                )
                if words
                else None
            )
            if row is None:
                skipped += 1
            else:
                rows.append(row)
    return make_listing(SMART_VARIANT, rows, skipped=skipped)


_WCM_FORMS: tuple[tuple[Callable[[str], bool], Callable[[str], Listing]], ...] = (
    (wcm.holds_alert_dialog, wcm.parse_alert_dialog),
    (wcm.holds_announcements, wcm.parse_text),
    (wcm.holds_alert_loader, wcm.alert_page),
)
"""The Web Community Manager forms (a homepage before SharpSchool, or its alert file)."""


def _homepage(text: str) -> Listing:
    tree = HTMLParser(text)
    slider = tree.css_first(SLIDER)
    if slider is not None:
        return _slider(slider)
    banners = tree.css_first(BANNER_SLIDER)
    if banners is not None:
        return _banners(banners)
    if COMPONENT in text:
        return deferred(HOMEPAGE_VARIANT, (SERVICE_PATH,))
    smart = tree.css(SMART_SLIDER)
    if smart and "wp-content" in text:
        return _smart_sliders(smart)
    raise homepage.NoFormError(
        "not a SharpSchool alert answer or homepage (no slider, no alert component), no "
        "WordPress Smart Slider page and no Web Community Manager form"
    )


def parse(body: bytes) -> Listing:
    """Read a SharpSchool alert answer, or an archived homepage of the station's site.

    A homepage is read with :func:`snowlight.sources.stations.homepage.read_homepage`:
    in none of the forms above, by its text; read from the page itself, with the
    closing lines its text shows that no row holds (its news items).
    """
    text = html_text(body)
    if text.lstrip()[:1] == "{":
        return _alerts(text)
    return homepage.read_homepage(text, _forms)


def _forms(text: str) -> Listing:
    for holds, read in _WCM_FORMS:
        if holds(text):
            return read(text)
    return _homepage(text)


def slice_body_v2(body: bytes) -> bytes:
    """Keep what the adapter reads, Smart Slider pages too (for fixtures).

    As :func:`slice_body`, and for a WordPress page with Smart Slider sliders (and
    neither form :func:`slice_body` keeps) its title, the ``wp-content`` marker the
    adapter looks for, and each slider without scripts, styles, images or SVG.
    """
    text = html_text(body)
    if text.lstrip()[:1] == "{":
        return body
    tree = HTMLParser(text)
    if tree.css_first(SLIDER) is not None or COMPONENT in text:
        return slice_body(body)
    smart = tree.css(SMART_SLIDER)
    if not smart or "wp-content" not in text:
        return slice_body(body)
    title = tree.css_first("title")
    head = f"<title>{escape(collapse(title.text()), quote=False)}</title>" if title else ""
    kept: list[str] = []
    for slider in smart:
        for junk in slider.css("script, style, svg, picture, img, noscript"):
            junk.decompose()
        kept.append(slider.html or "")
    marker = '<link rel="stylesheet" href="/wp-content/">'
    return document(head + marker + "".join(kept))


def slice_body(body: bytes) -> bytes:
    """Keep what the adapter reads of a SharpSchool homepage (for fixtures).

    The page title, then the hero slider (without scripts or styles) when there is
    one, else the alert component's element alone; a JSON answer is kept whole.
    The slice reads exactly as the page does.
    """
    text = html_text(body)
    if text.lstrip()[:1] == "{":
        return body
    tree = HTMLParser(text)
    title = tree.css_first("title")
    head = f"<title>{escape(collapse(title.text()), quote=False)}</title>" if title else ""
    slider = tree.css_first(SLIDER)
    if slider is not None:
        for junk in slider.css("script, style"):
            junk.decompose()
        return document(head + f'<div class="advanced-data-display">{slider.html or ""}</div>')
    if COMPONENT in text:
        return document(head + f'<div class="reactComponent {COMPONENT}"></div>')
    return document(head)


def holds_homepage(text: str) -> bool:
    """Whether a page is a SharpSchool homepage in a form :func:`parse_homepage` reads."""
    if "sharpschool" not in text.lower():
        return False
    tree = HTMLParser(text)
    return (
        tree.css_first(SLIDER) is not None
        or tree.css_first(BANNER_SLIDER) is not None
        or COMPONENT in text
    )


def parse_homepage(text: str) -> Listing:
    """Read a SharpSchool homepage (its slider, banner slider or alert component)."""
    return _homepage(text)


def slice_body_v3(body: bytes) -> bytes:
    """Keep what the adapter reads of a SharpSchool homepage, banner sliders and page text too.

    The page title, the hero slider or the banner rotator (without scripts, styles
    or images; a banner slide keeps its link and its image's ``alt`` and ``title``),
    the alert component's element when the page has one, the SharpSchool marker the
    other adapters look for, and each closing line of the page's text as a paragraph
    (:func:`snowlight.sources.stations.homepage.text_blocks`). A JSON answer is kept
    whole; any other page as :func:`slice_body_v2` cuts it.
    """
    text = html_text(body)
    if text.lstrip()[:1] == "{":
        return body
    tree = HTMLParser(text)
    banners = tree.css_first(BANNER_SLIDER)
    slider = tree.css_first(SLIDER)
    if banners is None and slider is None and COMPONENT not in text:
        return slice_body_v2(body)
    title = tree.css_first("title")
    head = f"<title>{escape(collapse(title.text()), quote=False)}</title>" if title else ""
    parts = ['<link rel="stylesheet" href="https://cdn.sharpschool.com/">']
    for found in (slider, banners):
        if found is None:
            continue
        for junk in found.css("script, style, noscript, svg"):
            junk.decompose()
        for image in found.css("img"):
            for name in list(image.attributes):
                if name not in {"alt", "title"}:
                    del image.attrs[name]
        parts.append(f'<div class="advanced-data-display">{found.html or ""}</div>')
    if COMPONENT in text:
        parts.append(f'<div class="reactComponent {COMPONENT}"></div>')
    parts.append(homepage.text_blocks(text))
    return document(head + "".join(parts))
