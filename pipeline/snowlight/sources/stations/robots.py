"""robots.txt, read the way RFC 9309 says, plus the non-standard ``Crawl-delay``.

Python's :mod:`urllib.robotparser` ignores ``*`` and ``$`` in paths and takes the
first matching rule rather than the most specific one, so it can allow what a
site disallows. This module implements the RFC's rules:

* Groups are matched by product token, case-insensitively. The token is the
  first word of our User-Agent (``snowlight-pipeline``). Every group naming it is
  merged; if none does, every ``*`` group is merged; if there is no ``*`` group,
  everything is allowed.
* Within the chosen rules, the longest matching path wins (counted in octets of
  the pattern), and ``Allow`` wins a tie. ``*`` matches any run of characters and
  a trailing ``$`` anchors the end. An empty ``Disallow`` matches nothing.
* ``/robots.txt`` itself is always allowed.
* Status handling (section 2.3): 2xx is parsed; 3xx is followed by the client
  (at most five hops); a 4xx answer means "unavailable", which allows everything;
  a 5xx answer or a network failure means "unreachable", which disallows
  everything until the file can be read.
* Only the first 500 KiB are parsed.

``Crawl-delay`` is not part of the RFC. When the group that applies to us sets it,
the fetcher waits at least that long between requests to the host.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import quote, urlsplit

MAX_ROBOTS_BYTES = 500 * 1024
_LINE = re.compile(r"^\s*([A-Za-z-]+)\s*:\s*(.*?)\s*$")
_SAFE = "/?=&;:@!$'()*+,-._~%#"


class RobotsState(StrEnum):
    """What reading a site's robots.txt produced."""

    PARSED = "parsed"
    UNAVAILABLE = "unavailable"
    """A 4xx answer: the site has no robots.txt, so crawling is unrestricted."""
    UNREACHABLE = "unreachable"
    """A 5xx answer or a network failure: nothing may be fetched."""


@dataclass(frozen=True, slots=True)
class Rule:
    """One ``Allow`` or ``Disallow`` line."""

    allow: bool
    pattern: str

    def matches(self, path: str) -> bool:
        """Return whether this rule's pattern matches ``path`` (path plus query)."""
        if not self.pattern:
            return False
        return _compile(self.pattern).match(path) is not None


@dataclass(slots=True)
class Group:
    """The rules under one or more ``User-agent`` lines."""

    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _normalize(pattern: str) -> str:
    # Percent-encode what a request line would encode, keep existing escapes and
    # the two special characters, so a pattern compares with a request path.
    return quote(pattern, safe=_SAFE)


_COMPILED: dict[str, re.Pattern[str]] = {}


def _compile(pattern: str) -> re.Pattern[str]:
    compiled = _COMPILED.get(pattern)
    if compiled is None:
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = ".*".join(re.escape(part) for part in body.split("*"))
        compiled = re.compile(regex + ("$" if anchored else ""), re.DOTALL)
        _COMPILED[pattern] = compiled
    return compiled


def parse(text: str) -> list[Group]:
    """Parse robots.txt text into its groups (unknown lines are ignored)."""
    groups: list[Group] = []
    current: Group | None = None
    last_was_agent = False
    for raw_line in text[:MAX_ROBOTS_BYTES].splitlines():
        line = raw_line.split("#", 1)[0]
        match = _LINE.match(line)
        if match is None:
            continue
        key, value = match.group(1).lower(), match.group(2)
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = Group()
                groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if current is None:
            continue
        if key in {"allow", "disallow"}:
            current.rules.append(Rule(allow=key == "allow", pattern=_normalize(value)))
        elif key == "crawl-delay":
            try:
                delay = float(value)
            except ValueError:
                continue
            if delay >= 0:
                current.crawl_delay = delay
    return groups


def _product_token(user_agent: str) -> str:
    token = user_agent.split("/", 1)[0].split(maxsplit=1)[0] if user_agent.strip() else "*"
    return token.lower()


@dataclass(frozen=True, slots=True)
class Robots:
    """A site's robots.txt, ready to answer whether a URL may be fetched."""

    state: RobotsState
    groups: tuple[Group, ...] = ()
    sha256: str | None = None
    """SHA-256 of the robots.txt bytes read, when there were any."""

    @classmethod
    def from_bytes(cls, body: bytes) -> "Robots":
        """Build from the body of a robots.txt that was read (a 2xx answer)."""
        text = body.decode("utf-8", errors="replace")
        return cls(RobotsState.PARSED, tuple(parse(text)), hashlib.sha256(body).hexdigest())

    @classmethod
    def for_status(cls, status: int) -> "Robots":
        """Build for a robots.txt request that ended with an HTTP ``status`` other than 2xx."""
        if 400 <= status < 500:  # noqa: PLR2004
            return cls(RobotsState.UNAVAILABLE)
        return cls(RobotsState.UNREACHABLE)

    def _groups_for(self, user_agent: str) -> Sequence[Group]:
        token = _product_token(user_agent)
        named = [group for group in self.groups if token in group.agents]
        if named:
            return named
        return [group for group in self.groups if "*" in group.agents]

    def decide(self, url: str, user_agent: str) -> tuple[bool, str]:
        """Return whether ``url`` may be fetched by ``user_agent``, and why."""
        if self.state is RobotsState.UNAVAILABLE:
            return True, "robots.txt unavailable (4xx): unrestricted"
        if self.state is RobotsState.UNREACHABLE:
            return False, "robots.txt unreachable (5xx or network error): nothing may be fetched"
        parts = urlsplit(url)
        path = parts.path or "/"
        if path == "/robots.txt":
            return True, "robots.txt is always allowed"
        target = _normalize(path + (f"?{parts.query}" if parts.query else ""))
        best: Rule | None = None
        for group in self._groups_for(user_agent):
            for rule in group.rules:
                if not rule.matches(target):
                    continue
                if (
                    best is None
                    or len(rule.pattern) > len(best.pattern)
                    or (len(rule.pattern) == len(best.pattern) and rule.allow and not best.allow)
                ):
                    best = rule
        if best is None:
            return True, "no rule matches"
        verb = "Allow" if best.allow else "Disallow"
        return best.allow, f"{verb}: {best.pattern}"

    def allowed(self, url: str, user_agent: str) -> bool:
        """Return whether ``url`` may be fetched by ``user_agent``."""
        return self.decide(url, user_agent)[0]

    def crawl_delay(self, user_agent: str) -> float | None:
        """Return the largest ``Crawl-delay`` among the groups that apply, if any."""
        delays = [
            group.crawl_delay
            for group in self._groups_for(user_agent)
            if group.crawl_delay is not None
        ]
        return max(delays) if delays else None

    def disallowed_agents(self) -> tuple[str, ...]:
        """Return the named agents (not ``*``) whose group disallows the whole site."""
        agents: list[str] = []
        for group in self.groups:
            if any(not rule.allow and rule.pattern == "/" for rule in group.rules):
                agents.extend(agent for agent in group.agents if agent != "*")
        return tuple(sorted(set(agents)))
