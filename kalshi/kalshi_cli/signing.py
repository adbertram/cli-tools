"""Kalshi request signing with a private key parsed once per process."""

import base64
import binascii
import re
import time

from cli_tools_shared.exceptions import ClientError


_KEY_ID = re.compile(r"[\x21-\x7e]+")


def decode_private_key(secret: str) -> str:
    """Return the PEM text for a stored key.

    The secret manager reads multi-line values back hex-encoded, so the key is stored
    as the base64 of the PEM file on a single line.
    """
    try:
        return base64.b64decode(secret.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ClientError(
            "Stored Kalshi private key must be the base64 of the PEM file on one line: base64 -i key.pem | tr -d '\\n'"
        ) from exc


class Signer:
    """Signs `timestamp + METHOD + path` with Ed25519 or RSA-PSS (SHA-256)."""

    def __init__(self, key_id: str, private_key_pem: str):
        if not _KEY_ID.fullmatch(key_id):
            raise ClientError("Kalshi key ID must be printable ASCII without whitespace.")
        # Imported here so commands that never sign skip the cryptography import cost.
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        try:
            key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            raise ClientError(f"Kalshi private key is not a valid unencrypted PEM key: {exc}") from exc
        if isinstance(key, Ed25519PrivateKey):
            self._sign = key.sign
        elif isinstance(key, RSAPrivateKey):
            pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH)
            self._sign = lambda message: key.sign(message, pss, hashes.SHA256())
        else:
            raise ClientError("Kalshi private key must be Ed25519 or RSA.")
        self.key_id = key_id

    def headers(self, method: str, path: str) -> dict:
        """Return the three auth headers; `path` is the full URL path without the query string."""
        timestamp = str(int(time.time() * 1000))
        signature = base64.b64encode(self._sign(f"{timestamp}{method}{path}".encode("utf-8"))).decode("ascii")
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }
