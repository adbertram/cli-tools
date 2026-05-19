"""OS keychain integration for CLI tool secrets.

Uses the cross-platform ``keyring`` library, which transparently maps to:

- macOS:    Keychain (via the ``Security`` framework)
- Windows:  Credential Manager (via ``wincred``)
- Linux:    libsecret (GNOME Keyring / KWallet); for headless servers,
            ``keyrings.alt`` provides a ``pass``-store fallback.

Secrets are namespaced as ``<service>`` + ``<profile>:<key>`` so that:
- Each CLI tool gets its own service entry (visible in Keychain Access etc.)
- Each profile (``default``, ``staging``, ``progress``, …) keeps its
  credentials separate even when the same key name is reused.

If ``keyring`` is not installed (it is an optional dependency of
``cli-tools-shared`` because not every tool needs secrets), every helper
falls back to a clear error explaining how to install it. None of the
helpers ever silently fall back to an in-memory or plaintext store —
that would defeat the security purpose.
"""

from __future__ import annotations

import os
from typing import Optional


__all__ = [
    "SecretError",
    "format_username",
    "get_secret",
    "set_secret",
    "delete_secret",
    "keyring_available",
    "keyring_backend_name",
    "is_dummy_keyring",
]


class SecretError(RuntimeError):
    """Raised when the keychain is required but unavailable or fails."""


def format_username(profile: str, key: str) -> str:
    """Build the keyring ``username`` field as ``<profile>:<key>``."""
    if not profile:
        raise SecretError("profile is required for secret storage")
    if not key:
        raise SecretError("key is required for secret storage")
    return f"{profile}:{key}"


def _import_keyring():
    """Import keyring once and return the module, or raise SecretError."""
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError as exc:
        raise SecretError(
            "The 'keyring' package is required for secret storage. "
            "Install it with: pip install keyring"
        ) from exc


def keyring_available() -> bool:
    """Check whether a usable keychain backend is present.

    Returns False if keyring isn't installed OR if the active backend is the
    null/fail backend (which silently no-ops). Used by tools to decide whether
    to prompt for migration vs. defer to the user.
    """
    try:
        keyring = _import_keyring()
    except SecretError:
        return False
    return not is_dummy_keyring(keyring.get_keyring())


def is_dummy_keyring(backend) -> bool:
    """Return True if the backend is one of keyring's no-op fallbacks."""
    cls_name = type(backend).__name__
    # keyring.backends.fail.Keyring and keyring.backends.null.Keyring are
    # both used when no real backend is available. Both fail or no-op on
    # set_password — neither is acceptable for storing real credentials.
    return cls_name in {"Keyring", "fail.Keyring", "null.Keyring"} and (
        type(backend).__module__.endswith(".fail")
        or type(backend).__module__.endswith(".null")
    )


def keyring_backend_name() -> str:
    """Return a short name describing the active keyring backend (for diagnostics)."""
    keyring = _import_keyring()
    backend = keyring.get_keyring()
    return f"{type(backend).__module__}.{type(backend).__name__}"


def get_secret(service: str, profile: str, key: str) -> Optional[str]:
    """Read a secret from the OS keychain.

    Returns None if the secret is not present. Raises ``SecretError`` if
    the keyring layer itself fails (e.g. user denied access).
    """
    keyring = _import_keyring()
    username = format_username(profile, key)
    try:
        return keyring.get_password(service, username)
    except Exception as exc:  # pragma: no cover - backend-specific
        raise SecretError(
            f"Failed to read secret {service}:{username} from keychain: {exc}"
        ) from exc


def set_secret(service: str, profile: str, key: str, value: str) -> None:
    """Store a secret in the OS keychain.

    Raises ``SecretError`` if the keyring backend is unavailable or write fails.
    """
    if value is None:
        raise SecretError("Refusing to store a None value as a secret")
    keyring = _import_keyring()
    backend = keyring.get_keyring()
    if is_dummy_keyring(backend):
        raise SecretError(
            "No real keyring backend is available — secrets cannot be stored. "
            "On Linux, install libsecret (e.g. `sudo apt install libsecret-1-0 "
            "gir1.2-secret-1`) or `pip install keyrings.alt` for a "
            "pass-based fallback. On macOS/Windows the system keychain should "
            "be available by default; check the keyring docs for diagnostics."
        )
    username = format_username(profile, key)
    try:
        keyring.set_password(service, username, value)
    except Exception as exc:  # pragma: no cover
        raise SecretError(
            f"Failed to write secret {service}:{username} to keychain: {exc}"
        ) from exc


def delete_secret(service: str, profile: str, key: str) -> bool:
    """Delete a secret from the OS keychain.

    Returns True if a secret was removed, False if none existed. Raises
    ``SecretError`` only if the keyring layer itself errors.
    """
    keyring = _import_keyring()
    username = format_username(profile, key)
    try:
        existing = keyring.get_password(service, username)
    except Exception as exc:  # pragma: no cover
        raise SecretError(
            f"Failed to read secret {service}:{username} for deletion: {exc}"
        ) from exc
    if existing is None:
        return False
    try:
        keyring.delete_password(service, username)
    except Exception as exc:
        # PasswordDeleteError is the canonical "not found"; treat as no-op.
        if exc.__class__.__name__ == "PasswordDeleteError":
            return False
        raise SecretError(  # pragma: no cover
            f"Failed to delete secret {service}:{username}: {exc}"
        ) from exc
    return True


def disable_keyring_in_environment() -> bool:
    """Return True when the env asks for keyring to be skipped.

    Useful for tests and CI: setting ``CLI_TOOLS_DISABLE_KEYRING=1`` causes
    code paths to act as if no keyring is available, exercising fallback
    error messages without requiring a live backend.
    """
    return os.environ.get("CLI_TOOLS_DISABLE_KEYRING", "").lower() in ("1", "true", "yes")
