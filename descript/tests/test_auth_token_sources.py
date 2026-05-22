"""Regression tests for Descript desktop auth token lookup."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from descript_cli.client import (
    CHROMIUM_IV,
    CHROMIUM_KEY_ITERATIONS,
    CHROMIUM_KEY_LENGTH,
    CHROMIUM_KEY_SALT,
    CHROMIUM_V10_PREFIX,
    ClientError,
    DescriptClient,
)
from descript_cli.config import Config


def _make_client(tmp_path: Path) -> DescriptClient:
    config = SimpleNamespace(
        base_url="https://web.descript.com",
        get_profile_data_dir=lambda: tmp_path / "profile-data",
    )
    return DescriptClient(config=config)


def _encrypt_v10_cookie(plaintext: str, password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=CHROMIUM_KEY_LENGTH,
        salt=CHROMIUM_KEY_SALT,
        iterations=CHROMIUM_KEY_ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(CHROMIUM_IV))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return CHROMIUM_V10_PREFIX + ciphertext


def test_read_encrypted_session_cookie_reads_descript_partition_db(tmp_path, monkeypatch):
    cookie_db = tmp_path / "Cookies"
    conn = sqlite3.connect(cookie_db)
    try:
        conn.execute(
            """
            CREATE TABLE cookies (
                host_key TEXT NOT NULL,
                name TEXT NOT NULL,
                encrypted_value BLOB NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO cookies(host_key, name, encrypted_value) VALUES (?, ?, ?)",
            (".descript.com", "stytch_session_jwt", b"v10-test-cookie"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("descript_cli.client.DESCRIPT_COOKIE_DB", cookie_db)

    client = _make_client(tmp_path)
    assert client._read_encrypted_session_cookie() == b"v10-test-cookie"


def test_decrypt_chromium_v10_value_returns_plaintext(tmp_path):
    client = _make_client(tmp_path)
    encrypted_value = _encrypt_v10_cookie("jwt-token", "safe-storage-password")

    decrypted = client._decrypt_chromium_v10_value(encrypted_value, "safe-storage-password")

    assert decrypted == "jwt-token"


def test_get_jwt_reads_cookie_and_caches_token(tmp_path, monkeypatch):
    client = _make_client(tmp_path)
    encrypted_value = _encrypt_v10_cookie("desktop-jwt", "safe-storage-password")

    monkeypatch.setattr(client, "_get_safe_storage_password", lambda: "safe-storage-password")
    monkeypatch.setattr(client, "_read_encrypted_session_cookie", lambda: encrypted_value)

    assert client._get_jwt() == "desktop-jwt"

    cache_path = client.token_cache_file
    assert cache_path.exists()
    cache_data = json.loads(cache_path.read_text())
    assert cache_data["jwt"] == "desktop-jwt"
    assert client._get_cached_token()["jwt"] == "desktop-jwt"


def test_config_test_connection_reports_client_error(monkeypatch):
    config = Config.__new__(Config)

    def raise_client_error(self):
        raise ClientError("keychain access denied")

    monkeypatch.setattr("descript_cli.client.DescriptClient._get_jwt", raise_client_error)

    assert config.test_connection() == {"api_test": "failed: keychain access denied"}


def test_config_test_connection_returns_token_preview(monkeypatch):
    config = Config.__new__(Config)
    token = "abcdefghijklmnopqrstuvwxyz"

    monkeypatch.setattr("descript_cli.client.DescriptClient._get_jwt", lambda self: token)

    assert config.test_connection() == {
        "api_test": "passed",
        "token_preview": "abcdefghijklmnopqrst...",
    }
