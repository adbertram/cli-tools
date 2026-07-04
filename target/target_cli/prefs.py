"""Per-profile checkout preferences for the Target CLI.

Target does NOT persist the pickup contact to the account, so every pickup order
needs a pickup person name + email. These defaults are stored per profile (beside
``redsky_session.json`` / ``payment_pointers.json``) so ``cart checkout`` can
supply them automatically; an explicit ``--pickup-email`` / ``--pickup-name`` on
the command line still overrides the stored default.
"""

import json
from pathlib import Path
from typing import Optional

PREFS_FILENAME = "checkout_prefs.json"


def prefs_path(config) -> Path:
    return config.get_profile_data_dir() / PREFS_FILENAME


def load_prefs(config) -> dict:
    path = prefs_path(config)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _write(config, prefs: dict) -> None:
    path = prefs_path(config)
    path.write_text(json.dumps(prefs, indent=2))
    path.chmod(0o600)


def get_pickup_contact(config) -> dict:
    """Return the stored ``{email, name}`` pickup defaults (values may be None)."""
    prefs = load_prefs(config)
    return {"email": prefs.get("pickup_email"), "name": prefs.get("pickup_name")}


def set_pickup_contact(
    config, email: Optional[str] = None, name: Optional[str] = None
) -> dict:
    """Set the default pickup email and/or name (only the provided fields change)."""
    prefs = load_prefs(config)
    if email is not None:
        prefs["pickup_email"] = email.strip() or None
    if name is not None:
        prefs["pickup_name"] = name.strip() or None
    _write(config, prefs)
    return {"email": prefs.get("pickup_email"), "name": prefs.get("pickup_name")}


def clear_pickup_contact(config) -> None:
    prefs = load_prefs(config)
    prefs.pop("pickup_email", None)
    prefs.pop("pickup_name", None)
    _write(config, prefs)
