"""``schools/meta.json``: the school directory the map and every live file index into.

``snowlight directory build`` writes this file (see :mod:`snowlight.directory.build`);
this model is its contract. Position ``i`` in ``ids`` and ``names`` is the school
with index ``i``: the ``i``-th record of ``points.bin`` and the index that
``live/closings.json``, ``live/covered.json`` and the replays use. Position ``j``
in ``districts.ids`` is district index ``j``, which ``points.bin`` and
``predictions/latest.json`` use.

Every file that holds such indexes also holds a :class:`DirectoryStamp`, and a
reader must ignore the file when the stamp does not match the ``meta.json`` it has
loaded: the indexes would point at the wrong schools.
"""

from itertools import pairwise
from typing import Self

from pydantic import model_validator

from snowlight.schemas.base import PublishedModel
from snowlight.schemas.scalars import (
    Count,
    DirectoryName,
    DistrictId,
    LocalDate,
    SchemaVersion,
    SchoolId,
    SchoolYear,
)

_PUBLIC_ID_LENGTH = 12


class DirectoryStamp(PublishedModel):
    """The directory a file's school and district indexes point into.

    It must equal generated_on, count and the number of districts of the
    schools/meta.json the reader has loaded; otherwise the file is ignored.
    """

    generated_on: LocalDate
    schools: Count
    districts: Count


class DistrictList(PublishedModel):
    """Every district with a school on the map, sorted by id."""

    ids: tuple[DistrictId, ...]
    names: tuple[DirectoryName, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.ids) != len(self.names):
            raise ValueError(f"{len(self.ids)} district ids but {len(self.names)} names")
        if any(a >= b for a, b in pairwise(self.ids)):
            raise ValueError("district ids must be sorted and unique")
        return self


class SchoolYears(PublishedModel):
    """The school year of the directory each kind of school comes from."""

    public: SchoolYear
    private: SchoolYear


class SchoolDirectoryMeta(PublishedModel):
    """schools/meta.json: every school on the map, in points.bin order.

    Public schools come first, sorted by id, then private schools sorted by id.
    """

    schema_version: SchemaVersion
    generated_on: LocalDate
    count: Count
    ids: tuple[SchoolId, ...]
    names: tuple[DirectoryName, ...]
    districts: DistrictList
    school_years: SchoolYears

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not len(self.ids) == len(self.names) == self.count:
            raise ValueError(
                f"count is {self.count} but there are {len(self.ids)} ids "
                f"and {len(self.names)} names"
            )
        public = [school for school in self.ids if len(school) == _PUBLIC_ID_LENGTH]
        private = self.ids[len(public) :]
        if tuple(public) != self.ids[: len(public)] or any(
            len(school) == _PUBLIC_ID_LENGTH for school in private
        ):
            raise ValueError("public schools must all come before private schools")
        for group in (public, private):
            if any(a >= b for a, b in pairwise(group)):
                raise ValueError("school ids must be sorted and unique within each kind")
        return self

    def stamp(self) -> DirectoryStamp:
        """Return the stamp that files indexing into this directory must carry."""
        return DirectoryStamp(
            generated_on=self.generated_on,
            schools=self.count,
            districts=len(self.districts.ids),
        )
