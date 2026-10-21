"""Web Push encryption (RFC 8291's own test vector), the VAPID signature (RFC 8292), the push
service list, and what each push service answer means."""

import json

import http_ece
import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from notify.fakes import Browser, vapid_rows
from snowlight.notify.webpush import (
    Delivery,
    Message,
    Vapid,
    VapidError,
    b64decode,
    encrypt,
    push_host_ok,
    send,
)

# RFC 8291, Appendix A.
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmY"
    "WAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexS"
    "gSxsj_Qulcy4a-fN"
)

MESSAGE = Message(payload=b'{"v":1}', ttl=600, urgency="high", topic="st-1-0114")


def test_encrypts_exactly_as_rfc_8291_appendix_a() -> None:
    sender = ec.derive_private_key(int.from_bytes(b64decode(AS_PRIVATE), "big"), ec.SECP256R1())
    body = encrypt(PLAINTEXT, UA_PUBLIC, AUTH, sender=sender, salt=b64decode(SALT))
    assert body == b64decode(BODY)


def test_a_browser_decrypts_what_it_is_sent() -> None:
    browser = Browser.make("https://fcm.googleapis.com/fcm/send/x")
    body = encrypt(b"hello", browser.p256dh, browser.auth_b64)
    clear = http_ece.decrypt(
        body, private_key=browser.private, auth_secret=browser.auth, version="aes128gcm"
    )
    assert clear == b"hello"
    assert encrypt(b"hello", browser.p256dh, browser.auth_b64) != body, "fresh keys every time"


def test_vapid_header_is_an_es256_jwt_for_the_push_service_origin() -> None:
    private, public, vapid = vapid_rows()
    header = vapid.authorization("https://fcm.googleapis.com/fcm/send/abc?x=1", now=1_800_000_000)
    token, key = header.removeprefix("vapid t=").split(", k=")
    assert key == public
    head, claims, signature = token.split(".")
    assert json.loads(b64decode(head)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(b64decode(claims)) == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1_800_000_000 + 12 * 3600,
        "sub": "https://snowlightmap.com",
    }
    raw = b64decode(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64decode(public))
    verifier.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        verifier.verify(der, f"{head}.{claims}x".encode(), ec.ECDSA(hashes.SHA256()))
    assert private not in header


def test_stored_keys_must_be_one_pair() -> None:
    private, _public, _vapid = vapid_rows()
    _other_private, other_public, _ = vapid_rows()
    with pytest.raises(VapidError):
        Vapid.from_stored(private, other_public)
    with pytest.raises(VapidError):
        Vapid.from_stored("AA", other_public)


@pytest.mark.parametrize(
    ("endpoint", "ok"),
    [
        ("https://fcm.googleapis.com/fcm/send/abc:APA91b", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/gAAA", True),
        ("https://web.push.apple.com/QGuQyavXutnMH", True),
        ("https://wns2-by3p.notify.windows.com/w/?token=x", True),
        ("http://fcm.googleapis.com/fcm/send/abc", False),
        ("https://fcm.googleapis.com.evil.example/x", False),
        ("https://evil.example/fcm.googleapis.com", False),
        ("https://fcm.googleapis.com:8443/x", False),
        ("https://user@fcm.googleapis.com/x", False),
        ("https://127.0.0.1/x", False),
    ],
)
def test_sends_only_to_known_push_services(endpoint: str, ok: bool) -> None:
    assert push_host_ok(endpoint) is ok


def _client(status: int | None, seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status is None:
            raise httpx.ConnectTimeout("no answer")
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("status", "delivery"),
    [
        (201, Delivery.SENT),
        (200, Delivery.SENT),
        (404, Delivery.GONE),
        (410, Delivery.GONE),
        (429, Delivery.FAILED),
        (500, Delivery.FAILED),
        (413, Delivery.REFUSED),
        (403, Delivery.REFUSED),
        (401, Delivery.REFUSED),
        (400, Delivery.REFUSED),
        (None, Delivery.FAILED),
    ],
)
def test_reads_the_push_service_answer(status: int | None, delivery: Delivery) -> None:
    _private, _public, vapid = vapid_rows()
    browser = Browser.make("https://fcm.googleapis.com/fcm/send/abc")
    seen: list[httpx.Request] = []
    got = send(
        _client(status, seen), vapid, browser.endpoint, browser.p256dh, browser.auth_b64, MESSAGE, 1
    )
    assert got is delivery
    request = seen[0]
    assert request.headers["TTL"] == "600"
    assert request.headers["Urgency"] == "high"
    assert request.headers["Topic"] == "st-1-0114"
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["Authorization"].startswith("vapid t=")
    clear = http_ece.decrypt(
        request.content, private_key=browser.private, auth_secret=browser.auth, version="aes128gcm"
    )
    assert clear == MESSAGE.payload


def test_never_posts_to_an_unknown_host_or_with_broken_keys() -> None:
    _private, _public, vapid = vapid_rows()
    browser = Browser.make("https://evil.example/push")
    seen: list[httpx.Request] = []
    client = _client(201, seen)
    assert send(client, vapid, browser.endpoint, browser.p256dh, browser.auth_b64, MESSAGE, 1) is (
        Delivery.GONE
    )
    good = "https://fcm.googleapis.com/fcm/send/x"
    assert send(client, vapid, good, "AAAA", browser.auth_b64, MESSAGE, 1) is Delivery.GONE
    assert seen == []
    loop = "http://127.0.0.1:9/push/x"
    assert send(client, vapid, loop, browser.p256dh, browser.auth_b64, MESSAGE, 1) is Delivery.GONE
    assert (
        send(client, vapid, loop, browser.p256dh, browser.auth_b64, MESSAGE, 1, loopback=True)
        is Delivery.SENT
    )


def test_refuses_a_payload_over_one_record() -> None:
    _private, _public, vapid = vapid_rows()
    browser = Browser.make("https://fcm.googleapis.com/fcm/send/x")
    big = Message(payload=b"x" * 5000, ttl=1, urgency="normal", topic="t")
    with pytest.raises(ValueError, match="too large"):
        send(_client(201, []), vapid, browser.endpoint, browser.p256dh, browser.auth_b64, big, 1)
