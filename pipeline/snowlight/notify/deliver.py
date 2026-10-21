"""Sends the due pushes to each account's browsers and keeps the log.

A push is logged (``notify_sent``) once at least one of the account's browsers took it, so
a pass where every push service failed sends it again at the next pass. The log is written
as the pass goes, every :data:`~snowlight.notify.store.PER_INSERT` rows, so a database
error after sending loses at most that many rows (sent again next pass) and the pass stops
there. A browser whose push service answers 404 or 410 has dropped the subscription: it is
deleted. One that keeps refusing (another 4xx) is deleted after
:data:`~snowlight.notify.store.STRIKES` refusals in a row over more than a day. A pass
stops sending at its deadline; what it did not send is due again next time.
"""

import json
import time as clock
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from snowlight.notify import store
from snowlight.notify.d1 import D1
from snowlight.notify.rules import Account, Push, Record, SentKey, Subscription
from snowlight.notify.webpush import Delivery, Message, Vapid, send

DEADLINE_SECONDS = 240.0


@dataclass(slots=True)
class Report:
    """What a pass did, in counts (no address, name or key)."""

    due: int = 0
    sent: int = 0
    browsers: int = 0
    failed: int = 0
    gone: int = 0
    held: int = 0
    """Pushes left for the next pass (the deadline came)."""
    records: int = 0

    def line(self) -> str:
        return (
            f"{self.due} due, {self.sent} sent to {self.browsers} browsers, "
            f"{self.failed} failed, {self.gone} subscriptions gone, {self.held} left for "
            f"the next pass, {self.records} log rows"
        )


@dataclass(frozen=True, slots=True)
class Sender:
    """How one browser gets one message (tests replace it)."""

    client: httpx.Client
    vapid: Vapid
    loopback: bool = False

    def __call__(self, subscription: Subscription, message: Message, now: int) -> Delivery:
        return send(
            self.client,
            self.vapid,
            subscription.endpoint,
            subscription.p256dh,
            subscription.auth,
            message,
            now,
            loopback=self.loopback,
        )


@dataclass(slots=True)
class Clock:
    """The pass's deadline, counted from when it is made (tests replace the monotonic clock)."""

    seconds: float = DEADLINE_SECONDS
    monotonic: Callable[[], float] = clock.monotonic
    _start: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._start = self.monotonic()

    def over(self) -> bool:
        return self.monotonic() - self._start > self.seconds


def message_of(push: Push) -> Message:
    payload = json.dumps(push.payload, separators=(",", ":"), ensure_ascii=False).encode()
    return Message(payload=payload, ttl=push.ttl, urgency=push.urgency, topic=push.topic)


def _count(
    report: Report,
    subscription: Subscription,
    result: Delivery,
    sets: tuple[set[str], set[str], set[str]],
) -> None:
    """Counts one browser's answer: into the report, and into the browsers that took a push
    after refusals, are gone, or refused."""
    took_once, gone, refused = sets
    if result is Delivery.SENT:
        report.browsers += 1
        if subscription.failures:
            took_once.add(subscription.endpoint)
    elif result is Delivery.GONE:
        gone.add(subscription.endpoint)
    else:
        report.failed += 1
        if result is Delivery.REFUSED:
            refused.add(subscription.endpoint)


def deliver(  # noqa: PLR0913, PLR0917 - the pushes, who gets them and how
    db: D1,
    pushes: Sequence[Push],
    accounts: Iterable[Account],
    sender: Callable[[Subscription, Message, int], Delivery],
    now: datetime,
    deadline: Clock | None = None,
) -> Report:
    """Sends ``pushes``, logs them, and deletes gone subscriptions.

    Raises:
        D1Error: the log or the subscriptions could not be written; nothing more is sent.
    """
    deadline = deadline or Clock()
    by_user: Mapping[str, Account] = {account.user_id: account for account in accounts}
    report = Report(due=len(pushes))
    pending: list[Record] = []
    gone: set[str] = set()
    refused: set[str] = set()
    took_once: set[str] = set()
    unix = int(now.timestamp())

    def flush() -> None:
        report.records += store.write_sent(db, pending, unix * 1000)
        pending.clear()

    for push in pushes:
        if deadline.over():
            report.held += 1
            continue
        account = by_user.get(push.user_id)
        if account is None:
            continue
        took = False
        message = message_of(push)
        for subscription in account.subscriptions:
            if subscription.endpoint in gone:
                continue
            result = sender(subscription, message, unix)
            took = took or result is Delivery.SENT
            _count(report, subscription, result, (took_once, gone, refused))
        if took:
            report.sent += 1
            key = SentKey(push.user_id, push.school.id, push.kind, push.day)
            pending.append(Record(key, push.value))
            pending.extend(
                Record(SentKey(push.user_id, push.school.id, kind, push.day), value)
                for kind, value in push.also
            )
            if len(pending) >= store.PER_INSERT:
                flush()
    flush()
    if gone:
        store.delete_subscriptions(db, sorted(gone))
    report.gone = len(gone)
    # A browser that took one push and was refused another is not counted as refusing.
    if strikes := sorted(refused - took_once - gone):
        store.note_refusals(db, strikes, unix * 1000)
    if cleared := sorted(took_once - refused):
        store.clear_refusals(db, cleared)
    return report
