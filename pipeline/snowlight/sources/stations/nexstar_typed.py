"""The ``nexstar-typed`` adapter: Nexstar stations that type their closings by hand.

The registry files a Nexstar station under the ``nexstar-typed`` platform
(``pipeline/config/sources/nexstar-typed.yaml``) only when its closings page was
seen typed by hand on storm days (WHNT, WDHN and WRBL), its closings address was
archived as such an article (WNTZ), or its closings page was seen with closings
typed beside its empty closings article (KIAH, archived 2025-01-25; WIVB, live
2026-09-28). Its bodies are read by
:func:`snowlight.sources.stations.nexstar.parse_typed`: every variant the
``nexstar`` adapter reads, a closings page typed by hand besides
(``nexstar-wp-typed``, ``nexstar-typed-page``, ``nexstar-typed-entry-content``), and
entries typed beside the closings article (``nexstar-wp-typed-beside``,
``nexstar-page-typed-beside``; see :mod:`snowlight.sources.stations.typed`). Every
other Nexstar station is read by :func:`snowlight.sources.stations.nexstar.parse`,
which never reads a typed page and refuses a page with entries typed beside its
closings article.
"""

from snowlight.sources.stations import nexstar
from snowlight.sources.stations.model import Listing


def parse(body: bytes) -> Listing:
    """Read one closings body of a Nexstar station registered as typing its closings."""
    return nexstar.parse_typed(body)
