"""ParentSquare Smart Sites (formerly Gabbart's SchoolSites) district sites: the pop-up alerts.

A district website on ParentSquare's Smart Sites (Orange, Osceola, Seminole, Leon
and six smaller county districts in Florida; Bonneville Joint District 93 in Idaho
Falls and Shelley in Idaho; Belgrade in Montana) shows its urgent notices as pop-up
alerts. The page loads them after it loads, from the site's own ``/api/popup-alerts`` (the
``PopUpAlertsComponent`` script asks for it with ``Accept: application/json`` and
checks the answer against the schema read here), so the poller reads that file.

Variants this adapter reads:

``smartsites-popup-alerts``
    A JSON object ``{"alerts": [...], "districtUrl": null | "..."}``; each alert
    has ``id`` (a number), ``title``, ``message``, ``link``, ``linkText`` (text or
    null), ``timeSince`` ("2 hours ago") and ``forceDistrictRedirect`` (a boolean).
    Live on 2026-09-27: ``{"alerts":[],"districtUrl":null}`` on eleven district
    sites, one notice on Belgrade's.

``schoolwires-important-announcements``
    An archived capture of the district's homepage from before it moved to Smart
    Sites (see :mod:`snowlight.sources.stations.schoolwires`): Osceola's of
    2022-09-28, "Schools To Be Closed September 27, September 28, September 29,
    2022, and September 30, 2022".

``campussuite-alert-banner``
    An archived capture of the homepage from when it was a Campus Suite site with
    the alert banner widget (see :mod:`snowlight.sources.stations.campussuite`):
    Hernando's of 2023 and 2024, with no alert up.

``wcm-announcements``
    An archived capture of the homepage from when it was a Web Community Manager
    site with its notices in an announcements app (see
    :mod:`snowlight.sources.stations.wcm`): Charlotte's of 2023-08-30, "Breaking
    News" announcing the Tropical Storm Idalia closing.

``wcm-alert-page`` / ``wcm-onscreen-alert``
    A Web Community Manager homepage loads the district's on-screen alert from its
    alert file by script: a homepage without an announcements app is a deferred
    page that loads it, one with the app names it beside its list, and the alert
    file (Broward's of Hurricane Ian, Pinellas' of Milton) is read as a list of its
    own: see :mod:`snowlight.sources.stations.wcm`.

``sharpschool-banner-slider`` / ``sharpschool-slider`` / ``sharpschool-homepage``
    An archived capture of the homepage from when it was a SharpSchool site:
    Orange County Public Schools' of 2022-09-28, whose banner rotator's slide
    "Hurricane Ian" is captioned "All Schools/District Offices Closed Wednesday,
    Thursday and Friday": see :mod:`snowlight.sources.stations.sharpschool`.

``homepage-text``
    Any other HTML page of the district's site (its Smart Sites homepage itself,
    which loads the pop-up alerts by script, or an earlier site in another CMS),
    read by its text, and page-text rows beside a homepage read in one of the forms
    above: see :mod:`snowlight.sources.stations.homepage`. A Smart Sites homepage
    showing no closing line is a page that holds no list of its own; the archive
    reader then reads the capture of the site's ``/api/popup-alerts`` nearest it
    (the station's registered data file), when the archive holds one. United ISD's
    homepage of 2026-01-26 led its news with "UPDATED: Two-Hour Delayed Start for
    Monday & Tuesday" ("As weather conditions continue to impact our area ...").

Each alert is one row. The answer names no school or district (it is the
district's own feed; the registry entry's ``leaids`` say whose), so ``raw_name`` is
the alert's ``title`` as written, ``raw_status`` its ``message`` (line breaks made
spaces), ``raw_updated_text`` its ``timeSince``, and ``raw_extra`` ``alert_id``,
``link``, ``link_text``, ``force_district_redirect`` and ``district_url``. An alert
with no title keeps its message as the name; one with neither is a skipped row. An
answer with no alerts is an empty list. Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`: a body that is neither JSON
nor an HTML page, an object without the ``alerts`` list, or an alert without a
numeric ``id``.
"""

import json
from typing import Any

from snowlight.sources.stations import campussuite, homepage, schoolwires, sharpschool, wcm
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.gap_markup import collapse, html_text, make_listing, make_row
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "smartsites-popup-alerts"


def _text(alert: dict[str, Any], key: str) -> str:
    value = alert.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ShapeError(f"alert field {key!r} is not text: {value!r}"[:200])
    return collapse(value)


def _row(alert: object, district_url: str | None) -> ParsedRow | None:
    if not isinstance(alert, dict):
        raise ShapeError("an alert is not an object")
    alert_id = alert.get("id")
    if isinstance(alert_id, bool) or not isinstance(alert_id, int):
        raise ShapeError(f"an alert has no numeric id: {alert_id!r}")
    title, message = _text(alert, "title"), _text(alert, "message")
    redirect = alert.get("forceDistrictRedirect")
    extra: dict[str, JsonScalar] = {
        "alert_id": alert_id,
        "link": _text(alert, "link") or None,
        "link_text": _text(alert, "linkText") or None,
        "force_district_redirect": redirect if isinstance(redirect, bool) else None,
        "district_url": district_url,
    }
    since = _text(alert, "timeSince") or None
    return make_row(title or message, message if title else "", since, extra)


def parse(body: bytes) -> Listing:
    """Read one answer of a Smart Sites district's ``/api/popup-alerts``.

    An archived capture of the district's homepage from before its Smart Sites
    site, when it was a Blackboard Web Community Manager site with the Important
    Announcement app (Osceola's, 2022), is read by
    :mod:`snowlight.sources.stations.schoolwires`; one from when it was a Campus
    Suite site, by :mod:`snowlight.sources.stations.campussuite`; a Web Community
    Manager homepage with an announcements app instead, by
    :mod:`snowlight.sources.stations.wcm`.
    """
    try:
        data = json.loads(decode(body))
    except (ValueError, UnicodeDecodeError) as error:
        text = html_text(body)
        if not homepage.is_html(text):
            raise ShapeError(f"not a JSON answer: {error}") from error
        return homepage.read_homepage(text, _homepage)
    return _alerts(data)


_EARLIER_FORMS = (
    (wcm.holds_alert_dialog, wcm.parse_alert_dialog),
    (schoolwires.holds_announcements, schoolwires.parse_text),
    (campussuite.holds_alert_banner, campussuite.parse_text),
    (wcm.holds_announcements, wcm.parse_text),
    (wcm.holds_alert_loader, wcm.alert_page),
    (sharpschool.holds_homepage, sharpschool.parse_homepage),
)
"""The homepage forms read before the page is read by its text, in order."""


def _homepage(text: str) -> Listing:
    for holds, read in _EARLIER_FORMS:
        if holds(text):
            return read(text)
    raise homepage.NoFormError("not a homepage form the Smart Sites reader knows")


def _alerts(data: object) -> Listing:
    if not isinstance(data, dict) or not isinstance(data.get("alerts"), list):
        raise ShapeError("the answer has no alerts list: not a Smart Sites popup-alerts answer")
    district_url = data.get("districtUrl")
    if district_url is not None and not isinstance(district_url, str):
        raise ShapeError("districtUrl is neither null nor text")
    rows: list[ParsedRow] = []
    skipped = 0
    for alert in data["alerts"]:
        row = _row(alert, district_url)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)
