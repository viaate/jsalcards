"""The refresh token's seal: AES-256-GCM under a key derived from ``X_CLIENT_SECRET``.

Two keys come from the client secret by HKDF-SHA256, each under its own ``info``: one
seals the refresh token stored in D1, the other keys the fingerprint of the
``X_REFRESH_TOKEN`` secret a stored chain started from. The fingerprint tells a newly pasted
secret from the one already used: a stored chain whose fingerprint is not the current
secret's was started from an older secret, so the run starts again from the secret.

Neither key nor any token ever leaves this module except as the sealed text or the
fingerprint, and an error never says more than that the seal did not open.
"""

import base64
import hashlib
import hmac
import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PREFIX: Final = "v1."
"""The sealed text's format: ``v1.`` and base64url of the 12-byte nonce and the ciphertext."""
SALT: Final = b"snowlight social x refresh token"
SEAL_INFO: Final = b"seal v1"
SEED_INFO: Final = b"seed fingerprint v1"
AAD: Final = b"snowlight social_token id=1"
NONCE_BYTES: Final = 12


class SealError(ValueError):
    """A sealed token did not open (another client secret, or damaged text)."""


def _key(client_secret: str, info: bytes) -> bytes:
    if not client_secret:
        raise ValueError("no client secret to derive a key from")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=SALT, info=info).derive(
        client_secret.encode()
    )


def seal(token: str, client_secret: str) -> str:
    """The token sealed under the client secret's key, with a fresh random nonce."""
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(_key(client_secret, SEAL_INFO)).encrypt(nonce, token.encode(), AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def unseal(text: str, client_secret: str) -> str:
    """The token a :func:`seal` text holds.

    Raises:
        SealError: the text is not a seal, or not one made with this client secret.
    """
    if not text.startswith(PREFIX):
        raise SealError("the stored token is not sealed in a known format")
    try:
        raw = base64.urlsafe_b64decode(text[len(PREFIX) :].encode())
    except ValueError as error:
        raise SealError("the stored token's seal is damaged") from error
    if len(raw) <= NONCE_BYTES:
        raise SealError("the stored token's seal is damaged")
    try:
        opened = AESGCM(_key(client_secret, SEAL_INFO)).decrypt(
            raw[:NONCE_BYTES], raw[NONCE_BYTES:], AAD
        )
    except InvalidTag as error:
        raise SealError("the stored token's seal did not open") from error
    return opened.decode()


def fingerprint(seed: str, client_secret: str) -> str:
    """A keyed fingerprint (HMAC-SHA256, hex) of the secret a chain starts from."""
    return hmac.new(_key(client_secret, SEED_INFO), seed.encode(), hashlib.sha256).hexdigest()
