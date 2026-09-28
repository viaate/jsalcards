"""The ``scripps-typed`` adapter: Scripps stations that type their closings by hand.

The registry files a Scripps station under the ``scripps-typed`` platform
(``pipeline/config/sources/scripps-typed.yaml``) only when its closings page is a
Brightspot page typed by hand rather than the closings module: KSTU (seen typed on
storm days) and the Montana stations' ``/weather/closings`` pages. Its bodies are
read by :func:`snowlight.sources.stations.scripps.parse_typed`: every variant the
``scripps`` adapter reads, and a closings page typed by hand besides
(``scripps-typed-page``; see :mod:`snowlight.sources.stations.typed`). Every other
Scripps station is read by :func:`snowlight.sources.stations.scripps.parse`, which
never reads a typed page.
"""

from snowlight.sources.stations import scripps
from snowlight.sources.stations.model import Listing


def parse(body: bytes) -> Listing:
    """Read one closings body of a Scripps station registered as typing its closings."""
    return scripps.parse_typed(body)
