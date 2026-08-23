"""Per-profile store of payment-card POINTERS for the Target CLI.

A pointer records a friendly ``name`` + the card's ``last4`` (+ ``brand``) so
``cart checkout --card <name>`` can SELECT an already-saved Target wallet card by
its last4. It never stores the card NUMBER (PAN) -- the human enters that into
Target's own wallet. It MAY store the card's ``cvv`` (opt-in, see ``set_cvv`` /
``payment-method add``) so checkout can confirm the card without an interactive
prompt; a stored CVV without the PAN is not a usable card on its own.

Stored beside ``redsky_session.json`` in the active profile's data dir at 0600,
mirroring ``session.py`` -- CLI-managed runtime state, NOT the secret manager.
"""

import json
import re
import time
from pathlib import Path
from typing import List, Optional

from cli_tools_shared.exceptions import ClientError

CARDS_FILENAME = "payment_pointers.json"
STORE_VERSION = 1


def normalize_name(name: str) -> str:
    """Slugify a pointer name: lowercase, non-alphanumerics -> '-', trimmed.

    ``--card`` lookups match on this slug, so ``"Amex Personal"`` and
    ``"amex-personal"`` resolve to the same pointer.
    """
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def cards_path(config) -> Path:
    return config.get_profile_data_dir() / CARDS_FILENAME


def load_pointers(config) -> List[dict]:
    """Return the stored card pointers for the active profile (empty if none)."""
    path = cards_path(config)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return list(data.get("cards", []))


def _write(config, cards: List[dict]) -> None:
    path = cards_path(config)
    path.write_text(json.dumps({"version": STORE_VERSION, "cards": cards}, indent=2))
    path.chmod(0o600)


def get_pointer(config, name: str) -> Optional[dict]:
    slug = normalize_name(name)
    for card in load_pointers(config):
        if card.get("name") == slug:
            return card
    return None


def get_default(config) -> Optional[dict]:
    for card in load_pointers(config):
        if card.get("default"):
            return card
    return None


def find_pointer(config, identifier: str) -> Optional[dict]:
    """Resolve a pointer by its name (slug) or, failing that, its last4.

    Lets ``payment-method get`` accept either the friendly name or the card's
    last 4 digits. A name (slug) match wins; a 4-digit identifier then matches on
    ``last4`` (first match). Returns ``None`` when nothing matches.
    """
    pointers = load_pointers(config)
    slug = normalize_name(identifier)
    if slug:
        match = next((c for c in pointers if c.get("name") == slug), None)
        if match is not None:
            return match
    digits = re.sub(r"\D", "", identifier or "")
    if len(digits) == 4:
        return next((c for c in pointers if c.get("last4") == digits), None)
    return None


def normalize_cvv(cvv: str) -> str:
    """Validate a CVV to 3-4 digits, or raise."""
    digits = re.sub(r"\D", "", cvv or "")
    if not (3 <= len(digits) <= 4):
        raise ClientError("CVV must be 3 or 4 digits.")
    return digits


def add_pointer(
    config, name: str, last4: str, brand: Optional[str] = None,
    default: bool = True, cvv: Optional[str] = None,
) -> dict:
    """Persist a new card pointer. First pointer is always the default.

    ``cvv`` is optional; when provided it is stored so checkout can confirm the
    card non-interactively.
    """
    slug = normalize_name(name)
    if not slug:
        raise ClientError("Card pointer name must contain letters or digits.")
    if not (last4 and last4.isdigit() and len(last4) == 4):
        raise ClientError(f"Invalid card last4 {last4!r}; expected 4 digits.")
    cards = load_pointers(config)
    if any(c.get("name") == slug for c in cards):
        raise ClientError(f"A card pointer named '{slug}' already exists.")
    make_default = default or not cards
    if make_default:
        for c in cards:
            c["default"] = False
    pointer = {
        "name": slug,
        "last4": last4,
        "brand": brand,
        "cvv": normalize_cvv(cvv) if cvv else None,
        "default": make_default,
        "added_at": time.time(),
    }
    cards.append(pointer)
    _write(config, cards)
    return pointer


def set_cvv(config, name: str, cvv: str) -> dict:
    """Store/replace the CVV on an existing card pointer."""
    slug = normalize_name(name)
    cards = load_pointers(config)
    hit = next((c for c in cards if c.get("name") == slug), None)
    if hit is None:
        raise ClientError(f"No card pointer named '{slug}'.")
    hit["cvv"] = normalize_cvv(cvv)
    _write(config, cards)
    return hit


def remove_pointer(config, name: str) -> None:
    slug = normalize_name(name)
    cards = load_pointers(config)
    remaining = [c for c in cards if c.get("name") != slug]
    if len(remaining) == len(cards):
        raise ClientError(f"No card pointer named '{slug}'.")
    # If the removed pointer was the default and others remain, promote one so a
    # bare `checkout` still has a default to fall back on.
    if remaining and not any(c.get("default") for c in remaining):
        remaining[0]["default"] = True
    _write(config, remaining)


def set_default(config, name: str) -> None:
    slug = normalize_name(name)
    cards = load_pointers(config)
    if not any(c.get("name") == slug for c in cards):
        raise ClientError(f"No card pointer named '{slug}'.")
    for c in cards:
        c["default"] = c.get("name") == slug
    _write(config, cards)
