"""What the posts are made of, read from the repository's ``social/`` folder.

* ``social/facts.md``: the facts a post may state (:func:`snowlight.social.rules.parse_facts`).
* ``social/images/<id>.json`` and the card it names: the library a post falls back to when
  the run's fresh card failed. Each is a finished card made from a real picture of the map,
  dated on its face ("From <date>", never a clock), with a description of exactly what it
  shows and the day it was taken, its alt text, and the kind of post it is labeled for.
* ``social/queue/<id>.json``: posts written ahead, sent oldest first. A queued post goes out
  with the run's fresh card for its style (:mod:`snowlight.social.cards`) when the picture
  is of a kind its ``pictures`` list allows (any, without the list); else with its own image
  when it names one, else with the library's newest card for its style.

Images are PNG or JPEG files under :data:`MAX_IMAGE_BYTES` (X's limit for a post image).
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from snowlight.social.rules import Facts, Style, parse_facts

MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024
PNG: Final = b"\x89PNG\r\n\x1a\n"
JPEG: Final = b"\xff\xd8\xff"
ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class ContentError(ValueError):
    """A file under ``social/`` is missing or malformed."""


class ImageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ID.pattern)
    file: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,60}\.(png|jpg)$")
    day: date
    shows: str = Field(min_length=20, max_length=800)
    alt: str | None = Field(default=None, min_length=20, max_length=1000)
    """The card's alt text (X's limit is 1,000 characters)."""
    style: Literal["dev_log", "waitlist"] | None = None
    """The kind of post the card is labeled for (any, when absent)."""
    tagline: str | None = Field(default=None, min_length=10, max_length=200)
    """The line from the facts file baked into the card, if any: it must still be words of a
    LIVE fact or the whole text of a COMING one, or the card is no longer true (re-render the
    library)."""


class QueueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[0-9]{4}$")
    style: Literal["dev_log", "waitlist"]
    text: str = Field(min_length=1, max_length=600)
    pictures: tuple[Literal["closings", "district", "national", "region"], ...] | None = Field(
        default=None, min_length=1
    )
    """The fresh picture kinds the text fits (any, when absent)."""
    image: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{0,60}\.(png|jpg)$")
    day: date | None = None
    shows: str | None = Field(default=None, min_length=20, max_length=600)

    @model_validator(mode="after")
    def _image_whole(self) -> "QueueEntry":
        if len({self.image is None, self.day is None, self.shows is None}) != 1:
            raise ValueError("a queued post names its image, day and shows together, or none")
        return self


@dataclass(frozen=True, slots=True)
class Image:
    id: str
    path: Path
    day: date
    shows: str
    fresh: str | None = None
    """The fresh picture's kind; ``None`` for a stored image (library or queue)."""
    current: bool = False
    """Whether a post may call what it shows current: only a fresh picture of live files."""
    alt: str | None = None
    """The alt text X shows for the image."""
    style: str | None = None
    """The kind of post a library card is labeled for (any, when ``None``)."""

    @property
    def content_type(self) -> str:
        return "image/png" if self.path.suffix == ".png" else "image/jpeg"

    def describe(self) -> str:
        if self.fresh is not None:
            return f"{self.shows} (taken for this post)"
        return (
            f"{self.shows} (an older picture, taken {self.day.isoformat()}, not a picture of now)"
        )


@dataclass(frozen=True, slots=True)
class Queued:
    id: str
    style: Style
    text: str
    image: Image | None
    pictures: tuple[str, ...] | None = None

    @property
    def slot(self) -> str:
        return f"queue:{self.id}"


@dataclass(frozen=True, slots=True)
class Content:
    facts: Facts
    images: tuple[Image, ...]
    queue: tuple[Queued, ...]

    def image(self, image_id: str) -> Image | None:
        return next((image for image in self.images if image.id == image_id), None)

    def newest(self, style: str | None = None) -> Image | None:
        """The library's newest card for ``style`` (the latest day, then the last id), else
        its newest of any kind: the fallback."""
        fitting = [image for image in self.images if image.style in (None, style)]
        return max(fitting or self.images, key=lambda image: (image.day, image.id), default=None)


def check_image(path: Path) -> None:
    """Raises :class:`ContentError` unless ``path`` is a PNG or JPEG X takes."""
    if not path.is_file():
        raise ContentError(f"social image {path.name} is missing")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ContentError(f"social image {path.name} is over 5 MB")
    if not data.startswith(PNG if path.suffix == ".png" else JPEG):
        raise ContentError(f"social image {path.name} is not the image its name says")


def _still_true(line: str, facts: Facts) -> bool:
    """Whether a card's line is still true per the facts: words of a LIVE fact's text (the
    model line is part of the LIVE fact ``model``), or the whole text of a COMING fact, which
    says itself that it is coming (a part of one could drop the "coming")."""
    wanted = line.strip().rstrip(".").lower()
    return any(
        (fact.status == "LIVE" and wanted in fact.text.lower())
        or (fact.status == "COMING" and fact.text.strip().rstrip(".").lower() == wanted)
        for fact in facts.facts
    )


def _json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContentError(f"{path.name} is not readable JSON") from error


def load(root: Path) -> Content:
    """The ``social/`` folder under the repository root.

    Raises:
        ContentError: a file is missing or malformed (the error names the file).
    """
    social = root / "social"
    try:
        facts = parse_facts((social / "facts.md").read_text(encoding="utf-8"))
    except OSError as error:
        raise ContentError("social/facts.md is missing") from error
    except ValueError as error:
        raise ContentError(f"social/facts.md: {error}") from error
    images: list[Image] = []
    for path in sorted((social / "images").glob("*.json")):
        try:
            entry = ImageEntry.model_validate(_json(path))
        except ValidationError as error:
            raise ContentError(f"social/images/{path.name} is malformed") from error
        if path.stem != entry.id:
            raise ContentError(f"social/images/{path.name} names another id")
        if entry.tagline is not None and not _still_true(entry.tagline, facts):
            raise ContentError(
                f"social/images/{path.name}: its card's line is no longer in the facts file;"
                " re-render the library (docs/social.md)"
            )
        check_image(social / "images" / entry.file)
        images.append(
            Image(
                id=entry.id,
                path=social / "images" / entry.file,
                day=entry.day,
                shows=entry.shows,
                alt=entry.alt,
                style=entry.style,
            )
        )
    queue: list[Queued] = []
    for path in sorted((social / "queue").glob("*.json")):
        try:
            item = QueueEntry.model_validate(_json(path))
        except ValidationError as error:
            raise ContentError(f"social/queue/{path.name} is malformed") from error
        if path.stem != item.id:
            raise ContentError(f"social/queue/{path.name} names another id")
        image = None
        if item.image is not None and item.day is not None and item.shows is not None:
            check_image(social / "queue" / item.image)
            image = Image(
                id=f"queue-{item.id}",
                path=social / "queue" / item.image,
                day=item.day,
                shows=item.shows,
            )
        queue.append(
            Queued(
                id=item.id, style=item.style, text=item.text, image=image, pictures=item.pictures
            )
        )
    return Content(facts=facts, images=tuple(images), queue=tuple(queue))
