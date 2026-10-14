"""Reads school closing listings: the status, the local dates, and the weather named.

:func:`parse_status` is the entry point::

    parse_status("2-Hour Delay", posted_at=posted, tz="America/Chicago")

It is pure and deterministic, and returns an immutable
:class:`~snowlight.classify.model.ParsedStatus`. A listing it cannot read
confidently becomes ``kind="other"`` with a low confidence: an ambiguous listing
is never reported as a closure.

* :mod:`~snowlight.classify.text`: normalization, durations, clock times.
* :mod:`~snowlight.classify.dates`: date expressions and the local calendar.
* :mod:`~snowlight.classify.mentions`: status phrases.
* :mod:`~snowlight.classify.subjects`: whose status a status word states ("Payroll delayed").
* :mod:`~snowlight.classify.revoke`: statuses the text calls off ("delay cancelled").
* :mod:`~snowlight.classify.partial`: statuses for part of a district ("except Lincoln").
* :mod:`~snowlight.classify.lexicon`: nouns and qualifier words.
* :mod:`~snowlight.classify.weather`: weather terms, reason labels, other causes.
* :mod:`~snowlight.classify.parse`: putting it together.
"""

from snowlight.classify.model import (
    KINDS,
    REASONS,
    STATUS_KINDS,
    DatedStatus,
    Kind,
    Note,
    ParsedStatus,
    Reason,
    StatusKind,
)
from snowlight.classify.parse import parse_status

__all__ = [
    "KINDS",
    "REASONS",
    "STATUS_KINDS",
    "DatedStatus",
    "Kind",
    "Note",
    "ParsedStatus",
    "Reason",
    "StatusKind",
    "parse_status",
]
