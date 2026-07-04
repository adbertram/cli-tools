"""Tests for `payment-method get`: pointer resolution + safe display shape.

Two decidable layers, verifiable without a browser:
- ``cards.find_pointer`` resolves a pointer by name (slug) or last4, else None.
- ``main._pointer_row`` builds the display row shared by list/get and must NEVER
  emit the stored CVV -- only whether one is stored.
"""
from target_cli import cards
from target_cli.main import _pointer_row


class _Cfg:
    """Stand-in config; find_pointer only reaches load_pointers(config)."""


def _patch_pointers(monkeypatch, pointers):
    monkeypatch.setattr(cards, "load_pointers", lambda config: pointers)


POINTERS = [
    {"name": "amex-personal", "last4": "1004", "brand": "American Express", "default": True, "cvv": "123"},
    {"name": "debit", "last4": "5636", "brand": "Mastercard", "default": False, "cvv": None},
]


# ---- cards.find_pointer ---------------------------------------------------

def test_find_pointer_by_name(monkeypatch):
    _patch_pointers(monkeypatch, POINTERS)
    assert cards.find_pointer(_Cfg(), "amex-personal")["last4"] == "1004"


def test_find_pointer_normalizes_name_input(monkeypatch):
    _patch_pointers(monkeypatch, POINTERS)
    # "Amex Personal" slugifies to "amex-personal", matching the stored pointer.
    assert cards.find_pointer(_Cfg(), "Amex Personal")["last4"] == "1004"


def test_find_pointer_by_last4(monkeypatch):
    _patch_pointers(monkeypatch, POINTERS)
    assert cards.find_pointer(_Cfg(), "5636")["name"] == "debit"


def test_find_pointer_returns_none_when_nothing_matches(monkeypatch):
    _patch_pointers(monkeypatch, POINTERS)
    assert cards.find_pointer(_Cfg(), "9999") is None   # 4 digits, no such card
    assert cards.find_pointer(_Cfg(), "nope") is None    # not a name


# ---- main._pointer_row (CVV must never leak) ------------------------------

def test_pointer_row_reports_cvv_stored_without_leaking_cvv():
    row = _pointer_row(POINTERS[0], wallet_last4={"1004"})
    assert row == {
        "name": "amex-personal",
        "brand": "American Express",
        "last4": "1004",
        "default": True,
        "cvv_stored": True,
        "in_wallet": True,
    }
    assert "cvv" not in row
    assert "123" not in row.values()


def test_pointer_row_flags_missing_cvv_and_wallet():
    row = _pointer_row(POINTERS[1], wallet_last4={"1004"})
    assert row["cvv_stored"] is False
    assert row["in_wallet"] is False
