"""What the posts are made of, read from the repository's ``social/`` folder.

* ``social/facts.md``: the facts a post may state (:func:`snowlight.social.rules.parse_facts`).
* ``social/images/<id>.json`` and the image it names: the library Haiku picks from. Each
  description says exactly what the image shows and the day it was taken.
* ``social/queue/<id>.json`` and its image: posts written ahead, sent oldest first.

Images are PNG or JPEG files under :data:`MAX_IMAGE_BYTES` (X's limit for a post image).
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    shows: str = Field(min_length=20, max_length=600)


class QueueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[0-9]{4}$")
    style: Literal["dev_log", "waitlist"]
    text: str = Field(min_length=1, max_length=600)
    image: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,60}\.(png|jpg)$")
    day: date
    shows: str = Field(min_length=20, max_length=600)


@dataclass(frozen=True, slots=True)
class Image:
    id: str
    path: Path
    day: date
    shows: str

    @property
    def content_type(self) -> str:
        return "image/png" if self.path.suffix == ".png" else "image/jpeg"

    def describe(self) -> str:
        return f"{self.shows} (taken {self.day.isoformat()})"


@dataclass(frozen=True, slots=True)
class Queued:
    id: str
    style: Style
    text: str
    image: Image

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


def _image(path: Path) -> None:
    if not path.is_file():
        raise ContentError(f"social image {path.name} is missing")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ContentError(f"social image {path.name} is over 5 MB")
    if not data.startswith(PNG if path.suffix == ".png" else JPEG):
        raise ContentError(f"social image {path.name} is not the image its name says")


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
        _image(social / "images" / entry.file)
        images.append(
            Image(
                id=entry.id, path=social / "images" / entry.file, day=entry.day, shows=entry.shows
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
        _image(social / "queue" / item.image)
        image = Image(
            id=f"queue-{item.id}",
            path=social / "queue" / item.image,
            day=item.day,
            shows=item.shows,
        )
        queue.append(Queued(id=item.id, style=item.style, text=item.text, image=image))
    return Content(facts=facts, images=tuple(images), queue=tuple(queue))
