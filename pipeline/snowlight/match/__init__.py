"""Name matcher: ties closings listings to NCES districts and schools.

Build a :class:`Matcher` from the directory (:func:`load_directory` reads the
``snowlight directory build`` output) and the pinned aliases
(:func:`load_aliases`), then call :meth:`Matcher.match` for each listing. An
accepted :class:`MatchResult` names its targets: one district or school, or
every district of a school system NCES splits into several
(:class:`SchoolSystem`: New York City's 33, a Montana town's elementary and high
school districts); :meth:`Matcher.expand` turns a result into all of their
schools. Listings that are not accepted go to the unmatched queue with
:func:`update_queue`.
"""

from snowlight.match.aliases import Aliases, alias_key, load_aliases
from snowlight.match.directory import (
    Directory,
    DirectoryError,
    DirectoryRecord,
    Kind,
    load_directory,
)
from snowlight.match.matcher import Candidate, Matcher, MatchResult, MatchSettings, Reason
from snowlight.match.normalize import Level
from snowlight.match.queue import UnmatchedQueue, read_queue, update_queue
from snowlight.match.systems import SchoolSystem

__all__ = [
    "Aliases",
    "Candidate",
    "Directory",
    "DirectoryError",
    "DirectoryRecord",
    "Kind",
    "Level",
    "MatchResult",
    "MatchSettings",
    "Matcher",
    "Reason",
    "SchoolSystem",
    "UnmatchedQueue",
    "alias_key",
    "load_aliases",
    "load_directory",
    "read_queue",
    "update_queue",
]
