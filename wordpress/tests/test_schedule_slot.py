"""Tests for find_next_schedule_slot's UTC-aware scheduling.

Regression coverage for a production incident: find_next_schedule_slot used
datetime.now() -- the CLI host machine's naive LOCAL time (e.g. CDT,
UTC-5) -- instead of true UTC. WordPress writes/interprets the site's
schedule date as UTC (via date_gmt), so a naive local "now" that trailed
true UTC by ~5 hours produced an auto-scheduled slot that was actually in
the past relative to true UTC now. WordPress silently accepted it as status
"future" anyway, because it genuinely was earlier than the wall-clock
moment WordPress compared it against.

These tests pin:
- "now" is always read as UTC-aware, never local.
- occupied_times is built from date_gmt (unambiguous), never date (site-
  timezone-relative).
- rounding rounds UP to the next hour boundary.
- a final defense-in-depth guard refuses to hand back a slot that isn't
  safely in the future, independent of the rest of the function's logic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from wordpress_cli.client import ClientError, WordPressClient
from wordpress_cli.models import Post


def _make_client(tmp_path) -> WordPressClient:
    """Build a client without touching real config/credentials or the real cache dir."""
    client = WordPressClient.__new__(WordPressClient)
    client._RESERVATION_DIR = tmp_path / "schedule-reservations"
    return client


def _freeze(monkeypatch, utc_now: datetime, local_offset_hours: int = 0):
    """Patch wordpress_cli.client.datetime so now() distinguishes naive/local calls from UTC-aware ones.

    Mirrors the real incident: the host machine's local wall clock (naive
    datetime.now()) can differ from true UTC (datetime.now(timezone.utc)) by
    the host's UTC offset. A fixed implementation must only ever call the
    tz-aware form; a test that calls the naive form and gets back the
    correct UTC-based answer anyway would be a false pass.
    """
    assert utc_now.tzinfo is not None
    local_now = (utc_now - timedelta(hours=local_offset_hours)).replace(tzinfo=None)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return local_now
            return utc_now.astimezone(tz)

    monkeypatch.setattr("wordpress_cli.client.datetime", FrozenDatetime)
    return FrozenDatetime


# ---------------------------------------------------------------------------
# find_next_schedule_slot
# ---------------------------------------------------------------------------


def test_slot_uses_true_utc_now_not_host_local_time(monkeypatch, tmp_path):
    """Host machine in CDT (UTC-5): local time trails true UTC by 5 hours.

    True UTC now = 2026-08-07T19:52:00Z (host-local 14:52). The fix must
    compute the candidate from true UTC now, never from the host's local
    wall clock.
    """
    utc_now = datetime(2026, 8, 7, 19, 52, 0, tzinfo=timezone.utc)
    _freeze(monkeypatch, utc_now, local_offset_hours=5)

    client = _make_client(tmp_path)
    with patch.object(client, "list_posts", return_value=[]):
        slot = client.find_next_schedule_slot()

    slot_dt = datetime.fromisoformat(slot)
    assert slot_dt.tzinfo is not None
    slot_utc = slot_dt.astimezone(timezone.utc)
    assert slot_utc > utc_now
    # Ceiling of (19:52 + 1h) = 20:52 -> next hour boundary = 21:00 UTC.
    assert slot_utc == datetime(2026, 8, 7, 21, 0, 0, tzinfo=timezone.utc)


def test_slot_is_future_when_now_is_exactly_on_the_hour(monkeypatch, tmp_path):
    """Exactly on an hour boundary must still gain a full hour of lead time."""
    utc_now = datetime(2026, 8, 7, 13, 0, 0, tzinfo=timezone.utc)
    _freeze(monkeypatch, utc_now, local_offset_hours=0)

    client = _make_client(tmp_path)
    with patch.object(client, "list_posts", return_value=[]):
        slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())

    slot_utc = slot_dt.astimezone(timezone.utc)
    assert slot_utc > utc_now
    # now (13:00) + 1h = 14:00, already on an hour boundary -> unchanged.
    assert slot_utc == datetime(2026, 8, 7, 14, 0, 0, tzinfo=timezone.utc)


def test_occupied_times_use_date_gmt_not_site_local_date(monkeypatch, tmp_path):
    """Occupancy math must key off date_gmt; date is ambiguous and must be ignored.

    The mock post carries a deliberately different (wrong-looking) date vs
    date_gmt. If the implementation regressed to reading date instead of
    date_gmt, this test's expected slot would not match.
    """
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)  # Tuesday
    _freeze(monkeypatch, utc_now, local_offset_hours=0)

    scheduled = Post(
        id=1,
        title="t",
        status="future",
        date="2026-08-04T05:30:00",  # would mislead a date-based implementation
        date_gmt="2026-08-04T10:30:00",
    )

    client = _make_client(tmp_path)
    with patch.object(client, "list_posts", side_effect=[[scheduled], []]):
        slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())

    # 09:00 (1.5h from 10:30) and 13:00 (2.5h from 10:30) both violate the
    # 4h gap rule against the real date_gmt conflict; 17:00 rolls to the
    # next day at 09:00, which finally clears the gap.
    assert slot_dt.astimezone(timezone.utc) == datetime(2026, 8, 5, 9, 0, 0, tzinfo=timezone.utc)


def test_missing_date_gmt_raises_instead_of_silently_ignoring(monkeypatch, tmp_path):
    """A future/publish post with no date_gmt is a data integrity bug -- fail loudly."""
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    _freeze(monkeypatch, utc_now, local_offset_hours=0)

    bad_post = Post(id=2, title="t", status="future", date="2026-08-04T10:00:00")  # no date_gmt

    client = _make_client(tmp_path)
    with patch.object(client, "list_posts", side_effect=[[bad_post], []]):
        with pytest.raises(ClientError):
            client.find_next_schedule_slot()


def test_min_lead_guard_rejects_a_would_be_past_slot(monkeypatch, tmp_path):
    """Defense-in-depth: if candidate math regresses and produces a slot with
    no lead time, the final guard forces a safe retry instead of returning it.
    """
    utc_now = datetime(2026, 8, 7, 13, 0, 0, tzinfo=timezone.utc)
    _freeze(monkeypatch, utc_now, local_offset_hours=0)

    real_ceil = WordPressClient.__dict__["_ceil_to_hour"].__func__
    calls = {"n": 0}

    def fake_ceil(value):
        calls["n"] += 1
        if calls["n"] == 1:
            # Reproduce the historical bug shape: a "candidate" with zero
            # lead time over true now.
            return utc_now
        return real_ceil(value)

    client = _make_client(tmp_path)
    with patch.object(client, "list_posts", return_value=[]), \
         patch.object(WordPressClient, "_ceil_to_hour", staticmethod(fake_ceil)):
        slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())

    assert calls["n"] >= 2  # the guard actually triggered a retry
    assert slot_dt.astimezone(timezone.utc) >= utc_now + client._MIN_SCHEDULE_LEAD


# ---------------------------------------------------------------------------
# _ceil_to_hour
# ---------------------------------------------------------------------------


def test_ceil_to_hour_leaves_an_exact_boundary_unchanged():
    on_boundary = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    assert WordPressClient._ceil_to_hour(on_boundary) == on_boundary


def test_ceil_to_hour_rounds_up_not_down():
    just_after = datetime(2026, 1, 1, 9, 0, 1, tzinfo=timezone.utc)
    assert WordPressClient._ceil_to_hour(just_after) == datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    near_next_hour = datetime(2026, 1, 1, 9, 59, 59, tzinfo=timezone.utc)
    assert WordPressClient._ceil_to_hour(near_next_hour) == datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Reservation cache: UTC-aware, and legacy (pre-fix) entries are discarded
# ---------------------------------------------------------------------------


def test_read_schedule_reservations_discards_legacy_naive_entries(tmp_path):
    """Reservations written before the UTC-aware fix are naive datetimes;
    mixing them with the new aware comparisons would raise TypeError, so
    they must be treated as stale and dropped instead.
    """
    client = WordPressClient.__new__(WordPressClient)
    client._RESERVATION_DIR = tmp_path / "reservations"
    client._RESERVATION_DIR.mkdir()
    legacy = client._RESERVATION_DIR / "legacy.json"
    legacy.write_text(json.dumps({
        "slot": "2026-08-07T21:00:00",  # naive, pre-fix format
        "expires": "2026-08-07T20:10:00",  # naive, pre-fix format
        "pid": 1,
    }))

    times = client._read_schedule_reservations()

    assert times == []
    assert not legacy.exists()


def test_reservation_round_trip_is_utc_aware(tmp_path):
    client = WordPressClient.__new__(WordPressClient)
    client._RESERVATION_DIR = tmp_path / "reservations"

    slot = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc).isoformat()
    client._create_schedule_reservation(slot)

    times = client._read_schedule_reservations()

    assert len(times) == 1
    assert times[0].tzinfo is not None
    assert times[0] == datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# UTC date parsing / writing (_parse_utc_date, _xmlrpc_post_date_gmt, _rest_date_gmt)
# ---------------------------------------------------------------------------


def test_parse_utc_date_accepts_naive_z_and_zero_offset():
    assert WordPressClient._parse_utc_date("2026-01-10T09:00:00") == datetime(2026, 1, 10, 9, 0, 0)
    assert WordPressClient._parse_utc_date("2026-01-10T09:00:00Z") == datetime(2026, 1, 10, 9, 0, 0)
    assert WordPressClient._parse_utc_date("2026-01-10T09:00:00+00:00") == datetime(2026, 1, 10, 9, 0, 0)


def test_parse_utc_date_rejects_non_utc_offset():
    with pytest.raises(ClientError):
        WordPressClient._parse_utc_date("2026-01-10T09:00:00-05:00")


def test_rest_date_gmt_format():
    assert WordPressClient._rest_date_gmt("2026-01-10T09:00:00Z") == "2026-01-10T09:00:00"


def test_xmlrpc_post_date_gmt_format():
    import xmlrpc.client as xmlrpc_client

    value = WordPressClient._xmlrpc_post_date_gmt("2026-01-10T09:00:00Z")
    assert isinstance(value, xmlrpc_client.DateTime)
    assert str(value) == "20260110T09:00:00"
