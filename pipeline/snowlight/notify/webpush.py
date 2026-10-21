"""Web Push: one encrypted message to one browser, signed with the site's VAPID key.

* The payload is encrypted for the browser (RFC 8291, ``aes128gcm``) with ``http_ece``, the
  encryption library pywebpush uses, from a fresh key pair and salt per message.
* The request is signed with VAPID (RFC 8292): a JWT (ES256) for the push service's origin,
  made here with ``cryptography``.
* It goes only to a push service the Worker accepts (:data:`PUSH_HOSTS`, the same list as
  ``api/src/notify.ts``), over https.

The private key never leaves this process: nothing here logs a key, a JWT or a payload.
"""

import base64
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal
from urllib.parse import urlsplit

import http_ece
import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PUSH_HOSTS: Final = (
    re.compile(r"fcm\.googleapis\.com"),
    re.compile(r"android\.googleapis\.com"),
    re.compile(r"updates\.push\.services\.mozilla\.com"),
    re.compile(r"web\.push\.apple\.com"),
    re.compile(r"[a-z0-9-]+\.notify\.windows\.com"),
)
"""The push services of Chrome, Edge, Firefox and Safari (``api/src/notify.ts``)."""
SUBJECT: Final = "https://snowlightmap.com"
"""Who sends, as the push services ask (a contact URL)."""
JWT_HOURS: Final = 12
MAX_PAYLOAD: Final = 3800
"""Under the 4096-byte record less the encryption's overhead, with room to spare."""
TIMEOUT: Final = httpx.Timeout(15.0, connect=10.0)
GONE: Final = frozenset({404, 410})
TOO_MANY: Final = 429

type Urgency = Literal["very-low", "low", "normal", "high"]


def b64decode(text: str) -> bytes:
    """base64url, padded or not."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class VapidError(ValueError):
    """The stored key pair is not a P-256 pair."""


@dataclass(frozen=True, slots=True)
class Vapid:
    """The site's VAPID key pair: the private scalar and the public point it serves."""

    private_key: ec.EllipticCurvePrivateKey
    public_key: str
    """base64url of the uncompressed point, as ``GET /v1/push/key`` serves it."""

    @classmethod
    def from_stored(cls, private: str, public: str) -> "Vapid":
        """From the two settings rows (``api/scripts/vapid.mjs``).

        Raises:
            VapidError: they are not one P-256 key pair.
        """
        try:
            scalar = int.from_bytes(b64decode(private), "big")
            key = ec.derive_private_key(scalar, ec.SECP256R1())
        except ValueError as error:
            raise VapidError("the VAPID private key is not a P-256 key") from error
        point = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        if b64encode(point) != public.rstrip("="):
            raise VapidError("the VAPID keys are not one pair")
        return cls(private_key=key, public_key=b64encode(point))

    def authorization(self, endpoint: str, now: int) -> str:
        """The ``Authorization`` header for a push to ``endpoint`` at Unix time ``now``."""
        parts = urlsplit(endpoint)
        header = {"typ": "JWT", "alg": "ES256"}
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": now + JWT_HOURS * 3600,
            "sub": SUBJECT,
        }
        signing = (
            f"{b64encode(json.dumps(header, separators=(',', ':')).encode())}."
            f"{b64encode(json.dumps(claims, separators=(',', ':')).encode())}"
        )
        der = self.private_key.sign(signing.encode("ascii"), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"vapid t={signing}.{b64encode(signature)}, k={self.public_key}"


def push_host_ok(endpoint: str) -> bool:
    """Whether ``endpoint`` is an https address at one of :data:`PUSH_HOSTS`."""
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or parts.port is not None or "@" in parts.netloc:
        return False
    return any(host.fullmatch(parts.hostname or "") for host in PUSH_HOSTS)


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    sender: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """The ``aes128gcm`` body of a push for the browser that made ``p256dh`` and ``auth``
    (RFC 8291). ``sender`` and ``salt`` are fresh unless given (the RFC's test vector)."""
    body: bytes = http_ece.encrypt(
        payload,
        salt=salt if salt is not None else os.urandom(16),
        private_key=sender if sender is not None else ec.generate_private_key(ec.SECP256R1()),
        dh=b64decode(p256dh),
        auth_secret=b64decode(auth),
        version="aes128gcm",
    )
    return body


class Delivery(StrEnum):
    """What the push service said."""

    SENT = "sent"
    GONE = "gone"
    """404 or 410: the browser dropped the subscription; delete it."""
    REFUSED = "refused"
    """Another 4xx (400, 401, 403, 413...): the push service will not take pushes for this
    subscription as it stands, as after a VAPID key that no longer matches. Tried again at
    the next pass, and deleted once refused :data:`~snowlight.notify.store.STRIKES` times in
    a row over more than a day."""
    FAILED = "failed"
    """No answer, 429 or a 5xx: try again at the next pass."""


@dataclass(frozen=True, slots=True)
class Message:
    """One notification for one browser."""

    payload: bytes
    ttl: int
    """Seconds the push service keeps it for a browser that is offline."""
    urgency: Urgency
    topic: str
    """A newer message with the same topic replaces one not yet delivered."""


def send(  # noqa: PLR0913, PLR0917 - the message, the browser and the transport
    client: httpx.Client,
    vapid: Vapid,
    endpoint: str,
    p256dh: str,
    auth: str,
    message: Message,
    now: int,
    *,
    loopback: bool = False,
) -> Delivery:
    """Encrypts and posts ``message`` to one browser's push service.

    ``loopback`` (the end-to-end dry run only) lets a stub push service on this machine
    through, over plain http.
    """
    if not (push_host_ok(endpoint) or (loopback and _on_loopback(endpoint))):
        return Delivery.GONE
    if len(message.payload) > MAX_PAYLOAD:
        raise ValueError("the payload is too large for one push")
    try:
        body = encrypt(message.payload, p256dh, auth)
    except (ValueError, TypeError):
        return Delivery.GONE
    headers = {
        "Authorization": vapid.authorization(endpoint, now),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(message.ttl),
        "Urgency": message.urgency,
        "Topic": message.topic,
    }
    try:
        response = client.post(endpoint, content=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError:
        return Delivery.FAILED
    return answer(response.status_code)


def answer(status: int) -> Delivery:
    """What a push service's HTTP status means for the subscription."""
    if status in GONE:
        return Delivery.GONE
    if 200 <= status < 300:  # noqa: PLR2004 - HTTP success
        return Delivery.SENT
    if 400 <= status < 500 and status != TOO_MANY:  # noqa: PLR2004 - HTTP client errors
        return Delivery.REFUSED
    return Delivery.FAILED


def _on_loopback(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    return parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
