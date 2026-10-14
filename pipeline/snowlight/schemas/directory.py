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

``schools/edition.json`` (:class:`DirectoryEdition`) names the directory a deploy
serves by its content: the stamp of its ``meta.json``, and :func:`written_digest`
of it and ``points.bin``. The page never reads it. The live ingest reads it from
the deployed site to prove that the indexes it writes point into the directory the
site serves, and the directory build reads the deployed one to keep the stamp's
date while the content is unchanged (:mod:`snowlight.directory.build`).
"""

import hashlib
from itertools import pairwise
from typing import Self

from pydantic import model_validator

from snowlight.output import dumps_json
from snowlight.schemas.base import PublishedModel
from snowlight.schemas.scalars import (
    ContentDigest,
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


def written_digest(meta_bytes: bytes, generated_on: str, points: bytes) -> str:
    """Return the content digest of a written ``meta.json`` dated ``generated_on``.

    The digest is the SHA-256 of ``meta_bytes`` as they are, with the text of the
    date emptied, followed by ``points``. Two directories with equal digests list
    the same schools and districts in the same order under the same names, with
    each school in the same district, of the same kind and at the same place, so
    every school and district index means the same thing in both; only the date
    in their stamps can differ. This is the one definition: the build (which
    dates from the ``meta.json`` it writes with an empty date), :func:`validate_site
    <snowlight.schemas.site.validate_site>`, the deployed-edition reader and
    web/scripts/edition.mjs all use it, so they can never disagree about a file.

    Raises:
        ValueError: the date's text is not in ``meta_bytes`` exactly once.
    """
    dated = dumps_json({"generated_on": generated_on})[1:-1]
    if meta_bytes.count(dated) != 1:
        raise ValueError("its date is not written once as the build writes it")
    blank = dumps_json({"generated_on": ""})[1:-1]
    digest = hashlib.sha256(meta_bytes.replace(dated, blank))
    digest.update(points)
    return digest.hexdigest()


def written_edition(meta_bytes: bytes, points: bytes) -> "DirectoryEdition":
    """Return the edition of the written ``meta.json`` and ``points.bin`` given.

    Raises:
        pydantic.ValidationError: ``meta_bytes`` is not a ``meta.json``.
        ValueError: its date is not written once as the build writes it.
    """
    meta = SchoolDirectoryMeta.from_json_bytes(meta_bytes)
    return DirectoryEdition(
        schema_version=1,
        generated_on=meta.generated_on,
        schools=meta.count,
        districts=len(meta.districts.ids),
        content_sha256=written_digest(meta_bytes, meta.generated_on.isoformat(), points),
    )


class DirectoryEdition(PublishedModel):
    """schools/edition.json: the directory a deploy serves, named by its content.

    ``generated_on``, ``schools`` and ``districts`` are the stamp of the
    ``meta.json`` beside it, and ``content_sha256`` is :func:`written_digest` of
    that ``meta.json`` and the ``points.bin`` beside them.
    """

    schema_version: SchemaVersion
    generated_on: LocalDate
    schools: Count
    districts: Count
    content_sha256: ContentDigest

    def stamp(self) -> DirectoryStamp:
        """Return the stamp of the directory this edition names."""
        return DirectoryStamp(
            generated_on=self.generated_on, schools=self.schools, districts=self.districts
        )
