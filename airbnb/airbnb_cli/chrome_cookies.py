"""Read Airbnb cookies from Adam's logged-in Chrome profile."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from cli_tools_shared.exceptions import ClientError

CHROME_COOKIE_DB = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
CHROME_SAFE_STORAGE_SERVICE = "Chrome Safe Storage"
CHROMIUM_V10_PREFIX = b"v10"
CHROMIUM_KEY_SALT = b"saltysalt"
CHROMIUM_KEY_ITERATIONS = 1003
CHROMIUM_KEY_LENGTH = 16
CHROMIUM_IV = b" " * 16
CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600
REQUIRED_AIRBNB_COOKIE_NAMES = {"_airbed_session_id"}


@dataclass(frozen=True)
class BrowserCookie:
    name: str
    value: str
    domain: str
    path: str
    secure: bool

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
        }


def _get_safe_storage_password() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", CHROME_SAFE_STORAGE_SERVICE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown keychain error"
        raise ClientError(
            "Failed to read Chrome cookie key from macOS Keychain.\n\n"
            f"stderr: {stderr}\n\n"
            "Open Chrome, allow Keychain access if prompted, then retry 'airbnb auth login'."
        )
    password = result.stdout.strip()
    if not password:
        raise ClientError("Chrome Safe Storage returned an empty cookie password.")
    return password


def _derive_chromium_v10_key(password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=CHROMIUM_KEY_LENGTH,
        salt=CHROMIUM_KEY_SALT,
        iterations=CHROMIUM_KEY_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def _decrypt_chromium_v10_value(host_key: str, encrypted_value: bytes, password: str) -> str:
    if not encrypted_value.startswith(CHROMIUM_V10_PREFIX):
        raise ClientError(
            "Airbnb cookie uses an unsupported Chrome encryption format.\n\n"
            f"Cookie host: {host_key}\n"
            f"Encrypted prefix: {encrypted_value[:3]!r}"
        )

    key = _derive_chromium_v10_key(password)
    cipher = Cipher(algorithms.AES(key), modes.CBC(CHROMIUM_IV))
    decryptor = cipher.decryptor()
    padded_plaintext = decryptor.update(encrypted_value[len(CHROMIUM_V10_PREFIX):]) + decryptor.finalize()

    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    host_digest = hashlib.sha256(host_key.encode("utf-8")).digest()
    if plaintext.startswith(host_digest):
        plaintext = plaintext[len(host_digest):]
    return plaintext.decode("utf-8")


def _is_expired(expires_utc: int) -> bool:
    if expires_utc == 0:
        return False
    expires_seconds = (expires_utc / 1_000_000) - CHROME_EPOCH_OFFSET_SECONDS
    return expires_seconds <= time.time()


def _read_cookie_rows(cookie_db: Path) -> Iterable[tuple]:
    if not cookie_db.exists():
        raise ClientError(
            "Chrome cookie store not found.\n\n"
            f"Expected: {cookie_db}\n\n"
            "Open Chrome, sign in to Airbnb, then retry 'airbnb auth login'."
        )

    with tempfile.TemporaryDirectory(prefix="airbnb-chrome-cookies-") as temp_dir:
        snapshot_path = Path(temp_dir) / "Cookies"
        shutil.copy2(cookie_db, snapshot_path)
        conn = sqlite3.connect(snapshot_path)
        try:
            return list(
                conn.execute(
                    """
                    SELECT host_key, name, value, encrypted_value, path, is_secure, expires_utc
                    FROM cookies
                    WHERE host_key LIKE '%airbnb.com'
                    """
                )
            )
        finally:
            conn.close()


def read_airbnb_cookies(cookie_db: Path = CHROME_COOKIE_DB) -> list[dict]:
    """Return decrypted Airbnb cookies from Chrome's Default profile."""
    password = _get_safe_storage_password()
    cookies: list[BrowserCookie] = []

    for host_key, name, value, encrypted_value, path, is_secure, expires_utc in _read_cookie_rows(cookie_db):
        if _is_expired(int(expires_utc or 0)):
            continue
        cookie_value = value
        if not cookie_value:
            cookie_value = _decrypt_chromium_v10_value(host_key, bytes(encrypted_value or b""), password)
        if not cookie_value:
            continue
        cookies.append(
            BrowserCookie(
                name=name,
                value=cookie_value,
                domain=host_key,
                path=path or "/",
                secure=bool(is_secure),
            )
        )

    names = {cookie.name for cookie in cookies}
    missing = sorted(REQUIRED_AIRBNB_COOKIE_NAMES - names)
    if missing:
        raise ClientError(
            "Chrome does not contain the Airbnb signed-in cookie this CLI needs.\n\n"
            f"Missing: {', '.join(missing)}\n\n"
            "Sign in to Airbnb in Chrome, load https://www.airbnb.com/hosting, then retry 'airbnb auth login'."
        )

    return [cookie.as_dict() for cookie in cookies]
