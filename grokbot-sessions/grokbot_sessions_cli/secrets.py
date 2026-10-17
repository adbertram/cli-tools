"""Read the Grok Bot desktop app's stored session credentials.

Grok Bot is an Electron app that keeps its Cursor session in
``~/Library/Application Support/Grok Bot/sand-secrets.json``. The account list
is a plaintext JSON *string*; the access token and machine id inside it are
Electron safeStorage blobs (``v10`` + AES-128-CBC) whose key lives in the macOS
Keychain.

This module never writes, logs, prints, or caches credential material. The
sensitive members of :class:`AppAccount` are excluded from ``repr`` so an
accidental exception message cannot leak them, and callers only ever see an
opaque account index plus the decrypted values they need to build a header.
"""
import base64
import binascii
import hashlib
import json
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from cli_tools_shared.exceptions import CredentialError

KEYCHAIN_SERVICE = "Grok Bot Safe Storage"
KEYCHAIN_ACCOUNT = "Grok Bot Key"

_PBKDF2_SALT = b"saltysalt"
_PBKDF2_ITERATIONS = 1003
_KEY_LENGTH = 16
_IV = b" " * 16
_SAFE_STORAGE_PREFIX = b"v10"
_KEYCHAIN_TIMEOUT_SECONDS = 30

_SIGN_IN_HINT = (
    "Open Grok Bot, sign in, and retry. grokbot-sessions can only adopt the "
    "session the desktop app already holds; it cannot mint one."
)


@dataclass(frozen=True)
class AppAccount:
    """One Grok Bot account scope and its decrypted session material.

    Every field is credential material: ``scope`` identifies the signed-in
    account, ``access_token`` is the bearer token, and ``machine_id`` seeds the
    request checksum. None of them appear in ``repr``.
    """

    index: int
    scope: str = field(repr=False)
    access_token: str = field(repr=False)
    machine_id: str = field(repr=False)
    active: bool = True

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return f"AppAccount(index={self.index}, active={self.active}, material=<redacted>)"


def _keychain_password() -> str:
    """Return the Grok Bot safeStorage password from the macOS Keychain.

    Raises:
        CredentialError: when the ``security`` tool is unavailable, the read
            fails, times out, or returns an empty password. The message always
            names the remediation.
    """
    command = [
        "security",
        "find-generic-password",
        "-s",
        KEYCHAIN_SERVICE,
        "-a",
        KEYCHAIN_ACCOUNT,
        "-w",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_KEYCHAIN_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise CredentialError(
            "The macOS 'security' command is not available, so the Grok Bot "
            f"safeStorage key cannot be read. {_SIGN_IN_HINT}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CredentialError(
            "Timed out reading the Grok Bot safeStorage key from the macOS "
            f"Keychain. {_SIGN_IN_HINT}"
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        raise CredentialError(
            "Could not read the Grok Bot safeStorage key from the macOS Keychain "
            f"({detail}). {_SIGN_IN_HINT}"
        )

    password = result.stdout.rstrip("\n")
    if not password:
        raise CredentialError(
            f"The macOS Keychain returned an empty Grok Bot safeStorage key. {_SIGN_IN_HINT}"
        )
    return password


def _unseal(blob: str, password: str) -> str:
    """Decrypt one Electron safeStorage ``v10`` value."""
    try:
        raw = base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CredentialError(
            "Grok Bot stored a value that is not valid base64 safeStorage data. "
            f"{_SIGN_IN_HINT}"
        ) from exc

    if not raw.startswith(_SAFE_STORAGE_PREFIX):
        raise CredentialError(
            "Grok Bot stored a value that is not a v10 safeStorage blob, which "
            f"this CLI cannot decrypt. {_SIGN_IN_HINT}"
        )

    key = hashlib.pbkdf2_hmac(
        "sha1", password.encode("utf-8"), _PBKDF2_SALT, _PBKDF2_ITERATIONS, _KEY_LENGTH
    )
    decryptor = Cipher(algorithms.AES(key), modes.CBC(_IV)).decryptor()
    try:
        plaintext = decryptor.update(raw[len(_SAFE_STORAGE_PREFIX):]) + decryptor.finalize()
    except ValueError as exc:
        raise CredentialError(
            "Could not decrypt a Grok Bot safeStorage value: the Keychain key "
            f"does not match this Grok Bot install. {_SIGN_IN_HINT}"
        ) from exc

    if not plaintext:
        raise CredentialError(
            f"A decrypted Grok Bot safeStorage value was empty. {_SIGN_IN_HINT}"
        )

    padding = plaintext[-1]
    if padding < 1 or padding > _KEY_LENGTH or padding > len(plaintext):
        raise CredentialError(
            "A decrypted Grok Bot safeStorage value had invalid PKCS#7 padding. "
            f"{_SIGN_IN_HINT}"
        )
    try:
        return plaintext[:-padding].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialError(
            f"A decrypted Grok Bot safeStorage value was not valid UTF-8. {_SIGN_IN_HINT}"
        ) from exc


def _read_store(app_dir: Path) -> Dict:
    """Read and parse Grok Bot's ``sand-secrets.json``."""
    secrets_path = app_dir / "sand-secrets.json"
    try:
        document = json.loads(secrets_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CredentialError(
            f"Grok Bot's credential store was not found at {secrets_path}. {_SIGN_IN_HINT}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise CredentialError(
            f"Could not read Grok Bot's credential store at {secrets_path}: {exc}. "
            f"{_SIGN_IN_HINT}"
        ) from exc
    if not isinstance(document, dict):
        raise CredentialError(
            f"Grok Bot's credential store at {secrets_path} is not a JSON object. "
            f"{_SIGN_IN_HINT}"
        )
    return document


def _read_account_entries(app_dir: Path) -> Dict:
    """Return ``{active_scope, accounts}`` from Grok Bot's credential store.

    The account list is a plaintext JSON string value, so this needs no
    Keychain access and is safe to call for index-only views such as
    ``projects list``.
    """
    document = _read_store(app_dir)
    raw_accounts = document.get("cursor-accounts")
    if not isinstance(raw_accounts, str) or not raw_accounts.strip():
        raise CredentialError(
            "Grok Bot's credential store has no 'cursor-accounts' entry. "
            f"{_SIGN_IN_HINT}"
        )
    try:
        parsed = json.loads(raw_accounts)
    except ValueError as exc:
        raise CredentialError(
            "Grok Bot's 'cursor-accounts' entry is not valid JSON. "
            f"{_SIGN_IN_HINT}"
        ) from exc
    accounts = parsed.get("accounts") if isinstance(parsed, dict) else None
    if not isinstance(accounts, dict) or not accounts:
        raise CredentialError(f"Grok Bot has no signed-in account. {_SIGN_IN_HINT}")
    return {"active_scope": parsed.get("active"), "accounts": accounts}


def account_labels(app_dir: Path) -> List[Dict]:
    """Return one non-sensitive descriptor per signed-in account scope.

    Each record carries a stable ``account-<n>`` label (``index``), the
    ``active`` flag, and whether an access token is present. The account scope
    itself is credential material and is deliberately never returned.
    """
    entries = _read_account_entries(app_dir)
    labels = []
    for index, payload in enumerate(entries["accounts"].items(), start=1):
        scope, account = payload
        has_token = isinstance(account, dict) and bool(account.get("cursor-access-token"))
        labels.append(
            {
                "id": f"account-{index}",
                "index": index,
                "active": scope == entries["active_scope"],
                "has_token": has_token,
                "has_profile": isinstance(account, dict)
                and bool(account.get("cursor-account-profile")),
            }
        )
    if labels and not any(label["active"] for label in labels):
        labels[0]["active"] = True
    return labels


def load_accounts(app_dir: Path) -> List[AppAccount]:
    """Decrypt every usable Grok Bot account, in the app's own order."""
    document = _read_store(app_dir)
    entries = _read_account_entries(app_dir)

    machine_blob = document.get("cursor-machine-id")
    if not isinstance(machine_blob, str) or not machine_blob.strip():
        raise CredentialError(
            "Grok Bot's credential store has no 'cursor-machine-id' entry. "
            f"{_SIGN_IN_HINT}"
        )

    password = _keychain_password()
    machine_id = _unseal(machine_blob, password)

    accounts: List[AppAccount] = []
    for index, payload in enumerate(entries["accounts"].items(), start=1):
        scope, account = payload
        if not isinstance(account, dict):
            continue
        token_blob = account.get("cursor-access-token")
        if not isinstance(token_blob, str) or not token_blob.strip():
            continue
        accounts.append(
            AppAccount(
                index=index,
                scope=scope,
                access_token=_unseal(token_blob, password),
                machine_id=machine_id,
                active=scope == entries["active_scope"],
            )
        )

    if not accounts:
        raise CredentialError(f"Grok Bot has no usable access token. {_SIGN_IN_HINT}")
    if not any(account.active for account in accounts):
        accounts[0] = replace(accounts[0], active=True)
    return accounts


def active_account(app_dir: Path) -> AppAccount:
    """Return the account Grok Bot itself is currently signed in to."""
    accounts = load_accounts(app_dir)
    active = next((account for account in accounts if account.active), None)
    if active is None:  # pragma: no cover - load_accounts guarantees one
        raise CredentialError(f"Grok Bot has no active account. {_SIGN_IN_HINT}")
    return active


def account_at(app_dir: Path, index: int) -> AppAccount:
    """Return the account at a 1-based ``account-<n>`` index."""
    accounts = load_accounts(app_dir)
    for account in accounts:
        if account.index == index:
            return account
    raise CredentialError(
        f"Grok Bot has no account-{index}. Available: "
        + ", ".join(f"account-{account.index}" for account in accounts)
    )
