"""Durable copy of the Garrul session cookie.

`garrul auth login` mints the session inside the CLI-owned Chromium profile,
which on this host is the profile every browser-backed CLI shares. Any other
tool that forces a fresh sign-in can empty that jar, and the Garrul session then
disappears days after it was minted even though the Worker still honours it:
BrickLink's Lego-identity login cleared the shared cookie database on
2026-10-16 and took the Garrul session with it.

The cookie value is also inert on the server. The Worker keeps the session in
KV and slides that record forward on every read, but the browser copy carries
the Max-Age stamped at mint time and is never re-issued, so a daily automation
stops at the 30-day mark no matter how faithfully it ran.

Both failures come from treating the browser's cookie jar as the credential.
This module keeps the cookie the CLI was actually given, in the tool's own
profile directory, so admin requests depend on nothing but the value the Worker
issued.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

from cli_tools_shared.exceptions import ClientError

STORE_NAME = "session-cookie.json"
# Production names the cookie __Host-garrul_sess; an ENV=dev instance uses the bare name.
SESSION_COOKIE_NAMES = ("__Host-garrul_sess", "garrul_sess")


def store_path(config) -> Path:
    """Return the profile-local file that holds this instance's session cookie."""
    return config.get_profile_data_dir() / STORE_NAME


def _host(config) -> str:
    return urlparse(config.instance_origin).hostname or ""


def _normalize(entry, host: str, where: str) -> dict:
    """Validate one stored cookie entry: name and value are all the client uses."""
    if not isinstance(entry, dict):
        raise ClientError(f"{where} must contain cookie objects, not {type(entry).__name__}.")
    name = entry.get("name")
    value = entry.get("value")
    if not isinstance(name, str) or not name:
        raise ClientError(f"{where} has a cookie with no name.")
    if not isinstance(value, str) or not value:
        raise ClientError(f"{where} has a cookie named {name!r} with no value.")
    return {
        "name": name,
        "value": value,
        "domain": entry.get("domain", host),
        "path": entry.get("path", "/"),
        "expires": entry.get("expires", -1),
    }


def save(config, cookies) -> Path:
    """Persist the session cookies for the configured instance.

    Written 0600 and replaced atomically: a half-written file must never be the
    thing a later run trusts.
    """
    host = _host(config)
    if not host:
        raise ClientError("Cannot store a session cookie: the configured BASE_URL has no host.")
    rows = [_normalize(entry, host, "session cookie store") for entry in cookies]
    if not rows:
        raise ClientError("Refusing to store an empty session cookie set.")
    payload = {
        "instance": config.instance_origin,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cookies": rows,
    }
    path = store_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    return path


def load(config) -> Optional[list]:
    """Return the stored cookies for the configured instance, or None.

    A store written for another instance (BASE_URL changed) is ignored rather
    than sent to the wrong host. An unreadable store is dropped and reported as
    absent: the browser profile is still a valid source, so a corrupted cache
    degrades to the old path instead of blocking every command.
    """
    path = store_path(config)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None
    if not isinstance(payload, dict):
        path.unlink(missing_ok=True)
        return None
    if payload.get("instance") != config.instance_origin:
        return None
    rows = payload.get("cookies")
    if not isinstance(rows, list) or not rows:
        path.unlink(missing_ok=True)
        return None
    try:
        return [_normalize(entry, _host(config), str(path)) for entry in rows]
    except ClientError:
        path.unlink(missing_ok=True)
        return None


def clear(config) -> None:
    """Remove the stored cookie. Called by `garrul auth logout`."""
    store_path(config).unlink(missing_ok=True)
