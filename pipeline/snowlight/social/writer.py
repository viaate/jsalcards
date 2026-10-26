"""The daily post Claude Haiku writes, and Haiku's second check of it.

Both calls go through the official ``anthropic`` SDK (``client.messages.create`` with
``output_config``: ``effort: low`` and a JSON schema ``format``, so the first text block is
the JSON the schema names). A ``refusal`` or ``max_tokens`` stop, or an answer that is not
the schema, is a failed attempt. :class:`Writer` makes at most :data:`MAX_CALLS` calls in a
run, each capped at :data:`MAX_TOKENS` tokens, and the SDK retries nothing
(``max_retries=0``), so a run's spend is bounded by those two numbers.

The flow (:func:`draft`): write, stating the day's model fact
(:func:`snowlight.social.rules.model_fact_for`: the LIVE model facts in turn); check it with
:func:`snowlight.social.rules.check` (which also holds it to that model fact); if that passes,
ask Haiku to check it against the facts. Either check failing gives one more try with
the problems shown; a second failure means no post today.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from snowlight.social.content import Content, Image
from snowlight.social.rules import Fact, Style, check, model_fact_for

MODEL: Final = "claude-haiku-5-5"
MAX_TOKENS: Final = 1024
MAX_CALLS: Final = 4
ATTEMPTS: Final = 2
PROBLEM_CHARS: Final = 200
"""The most of one of Haiku's problem lines that is kept (shown to the writer and logged)."""

DRAFT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "image_id": {"type": "string"},
        "kind": {"type": "string", "enum": ["dev_log", "waitlist"]},
        "facts_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "image_id", "kind", "facts_used"],
    "additionalProperties": False,
}
REVIEW_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ok", "problems"],
    "additionalProperties": False,
}

VOICE: Final = """You write one post for the X account @SnowlightMap. I am the young founder \
building Snowlight, a national map of US school closings with a snow day chance for every \
school district, and the post is in my own voice: first person ("I"), casual, specific, short, \
plain words. Never corporate, never hype, never salesy. Everything in it must be true.

Model first: every post states the one fact about Snowlight's prediction model it is given, \
plainly and specifically, so people learn that Snowlight's chances come from a real \
statistical model trained on real closing records, not a guess. Say what the model does; \
"not a guess" is fine.

Hard rules:
- Use ONLY the facts below. Never add a claim, number, feature, date or plan they do not hold.
- A fact marked TESTING or COMING is not live: say it is in testing or coming, never that it \
is live or available.
- No URL, no domain name, no @mention. The link is in my bio.
- At most one hashtag and at most one emoji (none is fine). Never "!!". No em dashes.
- Say only what Snowlight does. Never describe, name or compare any other product, site, app, \
calculator or predictor, and never talk about what others do: no "unlike", "other apps", \
"other sites", "everyone else", "better than", "more accurate", "they guess", no "-er than".
- Never use these words: AI, accurate, accuracy, revolutionary, AI-powered, machine learning, \
guaranteed, never wrong, better than, calculator, formula, reconstruction, competitor. Never \
give an accuracy number or a score.
- Never name a TV or radio station, a school, a district or a person.
- Never use a superlative or a comparison: no "best", "only", "most", "unlike", "vs".
- Nobody can use the map yet: never say "check your school", "you can now" or "available \
now"; only the waitlist is open.
- Keep it under 240 characters.
- Write a number only as the facts use it, in digits as they write it; never spell a number \
out unless the facts do. Never write a number, count, time or date from the picture's \
description: the card shows those, labeled.
- Never write "tomorrow", "next week", a weekday or a month unless the facts or the \
picture's description use it the same way. Never give a launch date.
- Say only what the image's description says about the image. Never call an older picture \
current: no "today", "now", "tonight", "currently", "just", "latest", "fresh" or a time \
about it."""

STYLES: Final[dict[Style, str]] = {
    "dev_log": "Style: a short dev log: one thing I built, fixed or learned about the "
    "prediction model, from the facts or the recent work. You may end with 'Waitlist link in "
    "my bio.'",
    "waitlist": "Style: ask people to join the waitlist, with the model fact as the reason. It "
    "MUST include the words 'link in my bio'.",
}

CHECKER: Final = """You check one draft post for the X account @SnowlightMap against the facts \
below, which are the only things known to be true. Answer ok=false, with each problem as one \
short line, when the draft: states anything the facts or the image description do not \
support; calls a TESTING or COMING fact live or available; holds a number the facts do not, \
or uses a fact's number for something else; gives a date or a launch day the facts do not; \
holds a URL, domain or @mention; compares Snowlight with, or names, another site, app or \
calculator; is hype, salesy or corporate; names a station, school, district or person; or \
says anything about the image its description does not say, or presents an older picture \
as current; does not state the model fact it was given, or states it more strongly than the \
facts do (an accuracy, a score, or "always"); or describes, names or compares any other \
product, site, app or predictor, or what others do. Otherwise ok=true with no problems."""


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    image_id: str
    kind: Literal["dev_log", "waitlist"]
    facts_used: list[str]


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    problems: list[str]


class CallCapError(RuntimeError):
    """A run asked for more than :data:`MAX_CALLS` calls."""


class AnswerError(RuntimeError):
    """A call stopped early, refused, or answered outside its schema (safe for the log)."""


class Writer:
    """The capped Haiku calls of one run."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client
        self.calls = 0

    def _ask(self, system: str, prompt: str, schema: dict[str, Any]) -> object:
        if self.calls >= MAX_CALLS:
            raise CallCapError(f"a run makes at most {MAX_CALLS} Haiku calls")
        self.calls += 1
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIStatusError as error:
            raise AnswerError(f"the Anthropic API answered HTTP {error.status_code}") from None
        except anthropic.APIError as error:
            raise AnswerError(f"the Anthropic API failed ({type(error).__name__})") from None
        if response.stop_reason == "refusal":
            raise AnswerError("Haiku declined to answer")
        if response.stop_reason != "end_turn":
            raise AnswerError(f"Haiku stopped early ({response.stop_reason})")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise AnswerError("Haiku's answer holds no text")
        try:
            return json.loads(text)
        except ValueError:
            raise AnswerError("Haiku's answer is not JSON") from None

    def write(self, prompt: str) -> Draft:
        try:
            return Draft.model_validate(self._ask(VOICE, prompt, DRAFT_SCHEMA))
        except ValidationError:
            raise AnswerError("Haiku's draft does not match its schema") from None

    def review(self, prompt: str) -> Review:
        try:
            return Review.model_validate(self._ask(CHECKER, prompt, REVIEW_SCHEMA))
        except ValidationError:
            raise AnswerError("Haiku's check does not match its schema") from None


@dataclass(frozen=True, slots=True)
class Written:
    text: str
    image: Image
    style: Style
    facts_used: tuple[str, ...]


def _plain(text: str, limit: int = PROBLEM_CHARS) -> str:
    """Haiku's free text as one short printable line: never a log command, never a new line
    (the log prints it; :func:`snowlight.social.logscan.one_line` also guards the log)."""
    printable = "".join(char if char.isprintable() else " " for char in text)
    return " ".join(printable.split())[:limit]


def _library(images: Sequence[Image]) -> str:
    return "\n".join(f"- {image.id}: {image.describe()}" for image in images)


def write_prompt(  # noqa: PLR0913 - the prompt's parts
    content: Content,
    style: Style,
    today: date,
    commits: Sequence[str],
    problems: Sequence[str],
    *,
    model_fact: Fact | None = None,
) -> str:
    """What the writer is asked (facts, the day's model fact, images, recent work, the style,
    earlier problems)."""
    parts = [
        f"Today is {today.isoformat()}.",
        STYLES[style],
        f"Set kind to {style}.",
        "Facts (the only things you may state):\n" + content.facts.text.strip(),
        *(
            [
                f"Model fact for this post (state it in my own words, numbers exactly as "
                f"written, and put {model_fact.id} in facts_used): {model_fact.text}"
            ]
            if model_fact is not None
            else []
        ),
        "The picture (set image_id to its id; the post must fit what it shows, and may say "
        "about it only what its description says):\n" + _library(content.images),
    ]
    if commits:
        parts.append(
            "What I changed since the last post (commit subjects; describe only in plain words "
            "and only what the facts support):\n" + "\n".join(f"- {line}" for line in commits)
        )
    if problems:
        parts.append(
            "Your last draft was refused for these problems; write a new one without them:\n"
            + "\n".join(f"- {line}" for line in problems)
        )
    return "\n\n".join(parts)


def review_prompt(
    content: Content, written: Written, today: date, model_fact: Fact | None = None
) -> str:
    return "\n\n".join(
        [
            f"Today is {today.isoformat()}.",
            "Facts:\n" + content.facts.text.strip(),
            f"Image: {written.image.describe()}",
            f"Kind: {written.style}",
            *([f"Model fact it was given: {model_fact.text}"] if model_fact is not None else []),
            f"Draft:\n{written.text}",
        ]
    )


def draft(  # noqa: PLR0913 - the run's parts
    writer: Writer,
    content: Content,
    *,
    style: Style,
    today: date,
    commits: Sequence[str],
    say: Callable[[str], None],
) -> Written | None:
    """The day's post, or ``None`` when both tries fail a check (each problem is said)."""
    problems: list[str] = []
    model_fact = model_fact_for(content.facts, today)
    if model_fact is not None:
        say(f"social: the model fact for {today.isoformat()} is {model_fact.id}")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            got = writer.write(
                write_prompt(content, style, today, commits, problems, model_fact=model_fact)
            )
        except AnswerError as error:
            problems = [str(error)]
            say(f"social: try {attempt}: {error}")
            continue
        image = content.image(got.image_id)
        problems = []
        if image is None:
            problems.append("the image id is not in the library")
        if got.kind != style:
            problems.append(f"the kind must be {style}")
        unknown = [fact for fact in got.facts_used if content.facts.get(fact) is None]
        if unknown:
            problems.append("facts_used names facts that are not in the file")
        if model_fact is not None and model_fact.id not in got.facts_used:
            problems.append(f"facts_used must name the model fact {model_fact.id}")
        if image is not None:
            problems += check(
                got.text,
                style=style,
                facts=content.facts,
                image_description=image.describe(),
                image_is_today=image.current,
                model_fact=model_fact,
            )
        if not problems and image is not None:
            written = Written(
                text=got.text, image=image, style=style, facts_used=tuple(got.facts_used)
            )
            try:
                verdict = writer.review(review_prompt(content, written, today, model_fact))
            except AnswerError as error:
                problems = [str(error)]
                say(f"social: try {attempt}: the check failed: {error}")
                continue
            if verdict.ok and not verdict.problems:
                return written
            problems = [plain for line in verdict.problems[:6] if (plain := _plain(line))] or [
                "the check said no"
            ]
        say(f"social: try {attempt}: refused: " + "; ".join(problems))
    return None
