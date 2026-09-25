"""Links on a web page, such as a ``www2.census.gov`` directory index."""

from html.parser import HTMLParser
from urllib.parse import urljoin


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value.strip())


def page_links(html: str, base_url: str) -> list[str]:
    """Return every ``<a href>`` on the page as an absolute URL, in page order.

    Query strings and fragments are dropped so that sort links such as
    ``?C=M;O=A`` on an Apache index collapse onto the directory itself.
    """
    collector = _AnchorCollector()
    collector.feed(html)
    collector.close()
    links: list[str] = []
    for href in collector.hrefs:
        absolute = urljoin(base_url, href).split("#", 1)[0].split("?", 1)[0]
        links.append(absolute)
    return links


def child_names(html: str, base_url: str) -> list[str]:
    """Return the names of the entries directly inside ``base_url``.

    A directory keeps its trailing slash (``2026_Gazetteer/``); links that point
    anywhere other than an immediate child of ``base_url`` are ignored.
    """
    if not base_url.endswith("/"):
        raise ValueError(f"a directory URL must end with '/': {base_url!r}")
    names: list[str] = []
    seen: set[str] = set()
    for link in page_links(html, base_url):
        if not link.startswith(base_url):
            continue
        rest = link[len(base_url) :]
        if not rest or "/" in rest.rstrip("/"):
            continue
        if rest not in seen:
            seen.add(rest)
            names.append(rest)
    return names
