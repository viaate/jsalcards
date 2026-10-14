# ruff: noqa: E501, RUF001 - the real links, titles and datelines are kept whole, dashes and all
"""KIFI's closings articles: which posts the poller reads as closings, and how old its list is.

The cases are REAL: every post of KIFI's WordPress REST list (localnews8.com) whose title
speaks of closing, cancelling or delaying school, found by searches of that list from
2022-09 to 2026-10 (read 2026-10-13 with the project's User-Agent; robots.txt: no rule
matches). Each case keeps the post's date, link, title and the opening of its dateline only
(the article's text is not kept); the expected verdicts are the ones the titles call for:
47 of the station's own closings articles (27 storm-day lists, 20 stories of one closing),
and the wire's stories and the stories about closings that announce none.
"""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from snowlight.sources.stations import fetch, wp_closings
from snowlight.sources.stations.model import ListingState, stale_before
from snowlight.sources.stations.seasons import ClosureEvent, ClosureSeasons

# (published day, link, title, dateline opening, a closings article, a list article)
CASES: list[tuple[str, str, str, str, bool, bool]] = [
    (
        "2022-10-12",
        "https://localnews8.com/news/blackfoot/2022/10/12/blackfoot-high-school-cancels-school-thursday/",
        "Blackfoot High School cancels school Thursday",
        "BLACKFOOT, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2022-11-18",
        "https://localnews8.com/news/2022/11/18/school-canceled-for-teton-elementary-today/",
        "School canceled for Teton Elementary today",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2022-12-02",
        "https://localnews8.com/news/2022/12/02/school-closures-for-dec-2/",
        "School closures for Friday, Dec. 2",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2022-12-12",
        "https://localnews8.com/news/top-stories/2022/12/12/school-closure-december-12-2022/",
        "School Closures and Delays – December 12, 2022",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2022-12-22",
        "https://localnews8.com/news/idaho/2022/12/21/school-closures-for-thursday-dec-22/",
        "School closures for Thursday, Dec. 22",
        "MACKAY, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-01-11",
        "https://localnews8.com/news/2023/01/11/school-closures-january-11-2023/",
        "School Closures – January 11, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-01-29",
        "https://localnews8.com/news/2023/01/29/schools-canceling-monday-classes-due-to-extreme-cold/",
        "Schools canceling Monday classes due to extreme cold",
        "IDAHO FALLS, Idaho (KIFI)-",
        True,
        False,
    ),
    (
        "2023-01-29",
        "https://localnews8.com/news/2023/01/29/blackfoot-school-district-cancels-monday-classes/",
        "Blackfoot School District cancels Monday classes",
        "BLACKFOOT, Idaho (KIFI)-",
        True,
        False,
    ),
    (
        "2023-01-29",
        "https://localnews8.com/news/top-stories/2023/01/29/pocatello-and-firth-school-districts-cancel-classes/",
        "Updated list of Monday school cancelations in Eastern Idaho",
        "EASTERN IDAHO (KIFI)-",
        True,
        True,
    ),
    (
        "2023-01-31",
        "https://localnews8.com/news/idaho/2023/01/30/school-closures-for-tuesday-jan-31/",
        "School closures for Tuesday, Jan. 31",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-02-01",
        "https://localnews8.com/news/education/2023/02/01/canceling-school-is-not-an-easy-task-when-it-comes-to-idaho-weather/",
        "Canceling school is not an easy task when it comes to Idaho weather",
        "REXBURG, Idaho (KIFI) -",
        False,
        False,
    ),
    (
        "2023-02-14",
        "https://localnews8.com/news/top-stories/2023/02/14/school-closures-february-14-2023/",
        "School Closures – February 14, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-02-15",
        "https://localnews8.com/news/local-news/2023/02/14/school-closures-for-wednesday-and-i-15-closure/",
        "School closures – February 15, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-02-17",
        "https://localnews8.com/news/top-stories/2023/02/17/school-closures-february-17-2023/",
        "School Closures – February 17, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-02-21",
        "https://localnews8.com/news/top-stories/2023/02/21/school-closures-february-21-2023/",
        "School Closures – February 21, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-02-22",
        "https://localnews8.com/news/top-stories/2023/02/22/school-closures-early-release-feb-22-2023/",
        "School closures, early release – Feb. 22, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-02-27",
        "https://localnews8.com/news/2023/02/26/delayed-start-time-for-jefferson-county-schools/",
        "School Closures or Delays – Monday, Feb. 27, 2023",
        "IDAHO FALLS, Idaho (KIFI)-",
        True,
        True,
    ),
    (
        "2023-02-28",
        "https://localnews8.com/news/top-stories/2023/02/27/school-closures-for-feb-28th/",
        "School closures for Feb. 28, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-04-04",
        "https://localnews8.com/news/top-stories/2023/04/04/school-closure-april-4-2023/",
        "School Closure – April 4, 2023",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2023-04-06",
        "https://localnews8.com/news/blackfoot/2023/04/05/blackfoot-school-district-55-canceling-thurs-classes/",
        "Blackfoot School District 55 canceling Thursday classes",
        "BLACKFOOT, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2023-05-12",
        "https://localnews8.com/news/education/2023/05/12/bonneville-high-school-cancels-in-person-classes-due-to-well-failure/",
        "Bonneville High School cancels in-person classes due to well failure",
        "BONNEVILLE COUNTY, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2023-08-24",
        "https://localnews8.com/news/2023/08/24/kentucky-school-districts-cancel-classes-less-than-2-weeks-into-school-year-due-to-covid-19-viruses-and-strep-outbreaks/",
        "Kentucky school districts cancel classes less than 2 weeks into school year due to Covid-19, viruses and strep outbreaks",
        "By Zenebou Sylla, CNN (CNN) —",
        False,
        False,
    ),
    (
        "2023-08-31",
        "https://localnews8.com/news/2023/08/31/5-people-shot-in-illinois-neighborhood-and-2-are-in-critical-condition/",
        "5 people shot and wounded, 2 critically, in Illinois city, as gun violence cancels school events",
        "PEORIA, Ill. (AP) —",
        False,
        False,
    ),
    (
        "2023-09-01",
        "https://localnews8.com/news/2023/09/01/with-some-schools-crumbling-uk-government-orders-action-on-aging-concrete-risk/",
        "UK orders more than 100 schools to keep buildings closed, citing risk of crumbling concrete",
        "By DANICA KIRKA Associated Press LONDON (AP) —",
        False,
        False,
    ),
    (
        "2023-09-05",
        "https://localnews8.com/news/2023/09/05/2-pennsylvania-school-districts-close-after-authorities-say-search-for-escaped-murderer-has-expanded/",
        "Manhunt for escaped killer continues for 6th day, leaving school districts closed and a Pennsylvania community on edge",
        "By Lauren Mascarenhas and Alisha Ebrahimji, CNN Chester County, Pennsylvania (CNN) —",
        False,
        False,
    ),
    (
        "2023-09-06",
        "https://localnews8.com/news/2023/09/06/are-heat-days-the-new-snow-days-schools-are-canceling-class-because-of-dangerous-heat-this-week/",
        "Are heat days the new snow days? Schools are canceling class as temperatures soar",
        "By Rachel Ramirez and Gabe Cohen, CNN (CNN) —",
        False,
        False,
    ),
    (
        "2023-10-25",
        "https://localnews8.com/news/2023/10/25/new-jersey-school-district-cancels-halloween-themed-events/",
        "New Jersey school district cancels Halloween-themed events",
        "By Web Staff Click here for updates on this story MAPLEWOOD, New Jersey ( WCBS ) —",
        False,
        False,
    ),
    (
        "2024-01-10",
        "https://localnews8.com/news/2024/01/09/school-closures-for-wednesday-2/",
        "School Closures for Wednesday",
        "",
        True,
        True,
    ),
    (
        "2024-01-11",
        "https://localnews8.com/news/2024/01/11/school-closures-for-friday-jan-12/",
        "School closures for Friday, Jan 12",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2024-01-16",
        "https://localnews8.com/news/top-stories/2024/01/15/school-closures-and-delays-for-tuesday-jan-16th/",
        "UPDATE: School Closures and Delays for Tuesday, Jan 16th",
        "",
        True,
        True,
    ),
    (
        "2024-01-18",
        "https://localnews8.com/news/top-stories/2024/01/18/school-closures-today-jan-18th/",
        "School closures for today, Jan. 18th",
        "POCATELLO, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2024-03-04",
        "https://localnews8.com/news/top-stories/2024/03/03/regional-charter-schools-and-public-school-districts-announce-closures-for-monday/",
        "More schools in Eastern Idaho announce closures for Monday",
        "IDAHO (KIFI)-",
        True,
        True,
    ),
    (
        "2024-03-05",
        "https://localnews8.com/news/2024/03/04/schools-closed-for-tuesday-mar-5-2024/",
        "Schools closed for Tuesday, Mar. 5, 2024",
        "BONNEVILLE COUNTY, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2024-03-06",
        "https://localnews8.com/news/2024/03/06/school-closures-delays-for-wednesday-march-6/",
        "School closures and delays for Wednesday, March 6",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2024-12-05",
        "https://localnews8.com/news/education/2024/12/04/ririe-elementary-school-canceled-for-thursday/",
        "Ririe Elementary School canceled for Thursday",
        "RIRIE, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2025-01-20",
        "https://localnews8.com/news/2025/01/19/schools-announcing-closures-due-to-cold-temperatures-on-monday-jan-20/",
        "Schools announcing closures due to cold temperatures on Monday, Jan. 20",
        "EASTERN IDAHO, Idaho (KIFI)–",
        True,
        True,
    ),
    (
        "2025-01-20",
        "https://localnews8.com/news/pocatello/2025/01/20/tendoy-elementary-families-and-staff-hold-rally-ahead-of-possible-school-closure/",
        "Tendoy Elementary families and staff hold rally ahead of possible school closure",
        "POCATELLO, Idaho (KIFI)–",
        False,
        False,
    ),
    (
        "2025-01-22",
        "https://localnews8.com/news/pocatello/2025/01/21/school-board-votes-to-close-washington-elementary/",
        "School board votes to close Washington Elementary",
        "BANNOCK COUNTY, Idaho (KIFI) —",
        False,
        False,
    ),
    (
        "2025-02-04",
        "https://localnews8.com/news/local-news/2025/02/04/ransomware-found-on-jefferson-school-districts-computer-systems/",
        "Jefferson School District cancels Thursday’s classes following cyberattack",
        "RIGBY, Idaho (KIFI)—",
        True,
        False,
    ),
    (
        "2025-02-07",
        "https://localnews8.com/news/2025/02/07/friday-school-canceled-for-butte-county-school-district/",
        "Friday School canceled for Butte County School District",
        "ARCO, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2025-02-11",
        "https://localnews8.com/news/local-news/2025/02/11/butte-county-cancels-school-due-to-rapidly-rising-flu-cases/",
        "Butte County cancels school due to rapidly rising Flu cases",
        "BUTTE COUNTY, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2025-02-11",
        "https://localnews8.com/news/2025/02/11/extreme-cold-causes-school-dealys-wednesday/",
        "Extreme cold causes school delays Wednesday",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2025-02-13",
        "https://localnews8.com/news/top-stories/2025/02/13/mackay-school-district-cancels-classes-for-february-13/",
        "School Closures and Delays for February 13",
        "MACKAY, Idaho (KIFI) -",
        True,
        True,
    ),
    (
        "2025-02-14",
        "https://localnews8.com/news/top-stories/2025/02/13/school-closures-on-february-14-due-to-harsh-weather/",
        "School closures on February 14 due to harsh weather",
        "IDAHO FALLS, Idaho (KIFI) –",
        True,
        True,
    ),
    (
        "2025-02-25",
        "https://localnews8.com/news/2025/02/25/school-closures-tuesday-february-25-2025/",
        "School Closures – Tuesday February 25, 2025",
        "IDAHO FALLS (KIFI) -",
        True,
        True,
    ),
    (
        "2025-02-26",
        "https://localnews8.com/news/top-stories/2025/02/25/hillcrest-high-school-cancels-classes-due-to-heat-outage/",
        "Hillcrest High School cancels classes due to heat outage",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2025-04-21",
        "https://localnews8.com/news/local-news/2025/04/21/madison-high-school-cancels-classes-on-monday/",
        "Madison High School cancels classes on Monday",
        "REXBURG, Idaho (KIFI) —",
        True,
        False,
    ),
    (
        "2025-09-25",
        "https://localnews8.com/news/idaho/2025/09/25/school-cancelled-for-some-d91-schools/",
        "School Cancelled for Some D91 Schools",
        "",
        True,
        False,
    ),
    (
        "2025-12-18",
        "https://localnews8.com/news/top-stories/2025/12/18/taylorview-middle-school-closed-thursday-due-to-down-heat-pumps/",
        "Taylorview Middle School closed Thursday due to down heat pumps",
        "IDAHO FALLS, Idaho (KIFI) -",
        True,
        False,
    ),
    (
        "2026-01-28",
        "https://localnews8.com/news/2026/01/28/classes-canceled-rising-illnesses-and-absences-force-multi-day-closure-for-ririe-school-district/",
        "Classes Canceled: Rising illnesses and absences force multi-day closure for Ririe School District",
        "RIRIE, Idaho (KIFI) —",
        True,
        False,
    ),
    (
        "2026-04-11",
        "https://localnews8.com/alerts/2026/04/11/school-bus-delays-expected-as-idaho-falls-intersection-closes-for-construction/",
        "School bus delays expected as Idaho Falls intersection closes for construction",
        "IDAHO FALLS, Idaho (KIFI)—",
        False,
        False,
    ),
    (
        "2026-04-13",
        "https://localnews8.com/news/2026/04/13/road-closure-on-s-5th-west-in-idaho-falls-to-cause-traffic-disruptions-school-bus-delays/",
        "Road Closure on S. 5th West in Idaho Falls to cause traffic disruptions & school bus delays",
        "Idaho Falls, ID (KIFI) -",
        False,
        False,
    ),
    (
        "2026-04-22",
        "https://localnews8.com/news/top-stories/2026/04/22/hawthorne-middle-school-closed-thursday-due-to-plumbing-issue/",
        "Hawthorne Middle School closed Thursday due to plumbing issue",
        "POCATELLO, Idaho (KIFI) —",
        True,
        False,
    ),
    (
        "2026-04-27",
        "https://localnews8.com/alerts/2026/04/27/school-closure-2/",
        "SCHOOL CLOSURE",
        "BUTTE COUNTY, IDAHO (KIFI) -",
        True,
        True,
    ),
    (
        "2026-05-07",
        "https://localnews8.com/news/top-stories/2026/05/06/classes-cancelled-compass-academy-tomorrow-due-to-threat/",
        "Classes Cancelled Compass Academy Tomorrow due to Threat",
        "",
        True,
        False,
    ),
    (
        "2026-08-31",
        "https://localnews8.com/news/idaho-falls/2026/08/31/fox-hollow-elementary-canceled-classes-after-smoke-fills-hallways/",
        "Fox Hollow Elementary canceled classes after smoke fills hallways",
        "IDAHO FALLS, Idaho (KIFI) —",
        True,
        False,
    ),
    (
        "2026-09-25",
        "https://localnews8.com/news/top-stories/2026/09/24/teton-county-schools-closed-tomorrow-due-to-jackson-boil-order/",
        "Teton County Schools Closed Tomorrow due to Jackson Boil Order",
        "",
        True,
        False,
    ),
    (
        "2026-10-07",
        "https://localnews8.com/news/2026/10/07/school-canceled-for-chief-tahgee-elementary-academy/",
        "School canceled for Chief Tahgee Elementary Academy",
        "",
        True,
        False,
    ),
]


def _post(case: tuple[str, str, str, str, bool, bool], number: int = 1) -> dict[str, Any]:
    day, link, title, opening, _, _ = case
    return {
        "id": number,
        "date_gmt": f"{day}T12:00:00",
        "modified_gmt": f"{day}T13:00:00",
        "link": link,
        "title": {"rendered": title},
        "content": {"rendered": f"<p>{opening} The rest of the story.</p>"},
    }


@pytest.mark.parametrize("case", CASES, ids=[case[2][:50] for case in CASES])
def test_every_real_kifi_post_is_read_as_its_title_calls_for(
    case: tuple[str, str, str, str, bool, bool],
) -> None:
    post = _post(case)
    assert wp_closings.closings_article(post) is case[4]
    if case[4]:
        assert wp_closings.list_article(post) is case[5]


def test_the_recall_covers_every_kind_of_closings_title() -> None:
    closings = [case for case in CASES if case[4]]
    assert len(closings) == 47
    assert sum(1 for case in closings if case[5]) == 27
    newest = max(case[0] for case in closings)
    assert newest == "2026-10-07"


def test_a_wire_story_under_the_stations_own_news_path_is_not_its_list() -> None:
    # REAL shape: the AP's story of 2024-11-19 as KIFI's site carries it (post 1452251),
    # under /news/YYYY/MM/DD/ with no wire marker in its path.
    post = {
        "id": 1452251,
        "date_gmt": "2024-11-19T12:33:36",
        "modified_gmt": "2024-11-19T12:33:36",
        "link": "https://localnews8.com/news/2024/11/19/school-closures-and-travel-delays-as-arctic-"
        "air-brings-snow-and-sleet-to-parts-of-the-uk/",
        "title": {
            "rendered": "School closures and travel delays as Arctic air brings snow and sleet to "
            "parts of the UK"
        },
        "content": {"rendered": "<p>LONDON (AP) &#8212; Dozens of schools closed ...</p>"},
    }
    assert not wp_closings.own_article(post)
    assert not wp_closings.closings_article(post)
    listing = wp_closings.parse(f"[{json.dumps(post)}]".encode())
    assert listing.state is ListingState.EMPTY
    assert listing.list_updated_at is None


def test_another_stations_credit_is_not_the_stations_own() -> None:
    case = (
        "2026-10-05",
        "https://localnews8.com/news/2026/10/05/x/",
        "School canceled at X",
        "",
        True,
        False,
    )
    post = _post(case)
    post["content"] = {"rendered": "<p>BOISE, Idaho (KIVI) &#8212; School is canceled ...</p>"}
    assert not wp_closings.closings_article(post)
    post["content"] = {
        "rendered": "<p>IDAHO FALLS, Idaho (KIFI) &#8212; School is canceled ...</p>"
    }
    assert wp_closings.closings_article(post)


def test_a_story_is_one_row_and_a_late_edit_does_not_make_it_new() -> None:
    post = _post(CASES[0])
    post["date_gmt"] = "2022-10-12T18:00:00"
    post["modified_gmt"] = "2026-10-13T08:00:00"
    listing = wp_closings.parse(json.dumps([post]).encode())
    assert len(listing.rows) == 1
    assert listing.rows[0].name == "Blackfoot High School cancels school Thursday"
    assert listing.rows[0].updated_text == "2022-10-12T18:00:00Z"
    assert listing.list_updated_at == datetime(2022, 10, 12, 18, 0, tzinfo=UTC)


KIFI = "npg-articles-kifi"
MOUNTAIN_WARNING = ClosureEvent(date(2025, 12, 5), date(2025, 12, 5), 0.878, ("WS.W",))


def test_a_newsroom_whose_newest_closings_article_predates_a_missed_storm_reads_stale() -> None:
    read_at = datetime(2026, 10, 13, 16, 0, tzinfo=UTC)
    record = ClosureSeasons(date(2026, 10, 12), {KIFI: (MOUNTAIN_WARNING,)})
    last_list = datetime(2025, 2, 25, 14, 0, tzinfo=UTC)
    written = fetch.old_write(None, last_list, stale_before(read_at))
    assert written == last_list
    verdict = record.judge(KIFI, written)
    assert verdict is not None
    assert verdict.stale


def test_a_newsroom_with_a_closings_article_since_the_winter_began_is_in_use() -> None:
    read_at = datetime(2026, 10, 13, 16, 0, tzinfo=UTC)
    newest = datetime(2026, 10, 7, 10, 55, tzinfo=UTC)
    assert fetch.old_write(None, newest, stale_before(read_at)) is None
