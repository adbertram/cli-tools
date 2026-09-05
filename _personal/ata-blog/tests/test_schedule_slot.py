"""Regression tests for find_next_schedule_slot future-slot selection.

Guards against two related production bugs:

1. (Original) auto-schedule snapped `now` down to the current hour and
   returned a slot at or before `now` (e.g. 17:00 when it was 17:46),
   causing WordPress to publish immediately instead of scheduling.

2. (Root cause behind a later incident) find_next_schedule_slot used
   datetime.now() -- the CLI host machine's naive LOCAL time (e.g. CDT,
   UTC-5) -- instead of true UTC. Publisher runtime records use explicit UTC
   offsets; when the host's local timezone trailed true
   UTC, the naive "now" was read as if it were already UTC, producing a
   candidate slot hours in the past relative to true UTC now. WordPress
   silently accepted the resulting timestamp as status "future" anyway,
   because it genuinely was earlier than the moment WordPress compared it
   against.

This is the live code path for `ata-blog notion-page publish --auto-schedule`
(AtaBlogClient.publish_article -> AtaBlogClient.find_next_schedule_slot),
which is a separate, independent reimplementation of the same scheduling
logic that also exists in wordpress_cli.client.WordPressClient (used by
`wordpress posts update --auto-schedule` / `ata-blog wordpress posts update
--auto-schedule`). Both copies had the identical bug and both are fixed and
tested independently.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import ata_blog_cli.client as client_module
from ata_blog_cli.client import AtaBlogClient, ClientError


class _Config:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def get_profile_data_dir(self):
        return self.data_dir


def _make_client(monkeypatch, tmp_path, utc_now: datetime, local_offset_hours: int = 0,
                  scheduled_slots=None):
    """Build a client with time/cache/IO frozen and no __init__ side effects.

    utc_now must be tz-aware UTC. local_offset_hours simulates the host
    machine's local timezone trailing true UTC by that many hours (e.g. 5
    for CDT), mirroring the real incident. A test that only ever freezes
    the naive and aware clocks to the SAME instant would pass even with the
    pre-fix bug, so this offset is what actually exercises the fix.
    """
    assert utc_now.tzinfo is not None
    local_now = (utc_now - timedelta(hours=local_offset_hours)).replace(tzinfo=None)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return local_now
            return utc_now.astimezone(tz)

    monkeypatch.setattr(client_module, "datetime", FrozenDatetime)

    client = AtaBlogClient.__new__(AtaBlogClient)
    client.config = _Config(tmp_path / "profile")
    # Isolate the reservation cache from the real ~/.cache directory instead
    # of stubbing the reservation methods, so the real read/write/expiry
    # logic (including the UTC-aware fix in it) is exercised too.
    client._RESERVATION_DIR = tmp_path / "schedule-reservations"
    transaction_root = client._publisher_runtime_root() / "transactions"
    transaction_root.mkdir(parents=True)
    for index, slot in enumerate(scheduled_slots or []):
        (transaction_root / f"{index}.runtime.json").write_text(
            json.dumps({"scheduled_date": slot})
        )
    return client


def test_slot_is_strictly_future_mid_afternoon(monkeypatch, tmp_path):
    # Tuesday 2026-07-21 at 17:46 UTC -- previously returned 17:00 (in the past).
    utc_now = datetime(2026, 7, 21, 17, 46, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now)

    slot = client.find_next_schedule_slot()
    slot_dt = datetime.fromisoformat(slot)

    assert slot_dt.tzinfo is not None, f"slot {slot} must carry an explicit UTC offset"
    slot_utc = slot_dt.astimezone(timezone.utc)
    assert slot_utc > utc_now, f"slot {slot} is not strictly after true UTC now {utc_now}"
    # now (17:46) + 1h = 18:46, ceiled up to the next hour boundary: 19:00.
    assert slot_utc == datetime(2026, 7, 21, 19, 0, 0, tzinfo=timezone.utc)


def test_slot_is_future_when_now_is_on_the_hour(monkeypatch, tmp_path):
    # Exactly on the hour must still advance to the next hour, not return now.
    utc_now = datetime(2026, 7, 21, 13, 0, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now)

    slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())
    slot_utc = slot_dt.astimezone(timezone.utc)

    assert slot_utc > utc_now
    assert slot_utc == datetime(2026, 7, 21, 14, 0, 0, tzinfo=timezone.utc)


def test_slot_uses_true_utc_now_not_host_local_time(monkeypatch, tmp_path):
    """The exact incident shape: host machine in CDT (UTC-5) reads a naive
    local time that trails true UTC by 5 hours (true UTC 19:52 == local
    14:52). The fix must ignore local time and compute from true UTC now.
    """
    utc_now = datetime(2026, 8, 7, 19, 52, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now, local_offset_hours=5)

    slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())
    slot_utc = slot_dt.astimezone(timezone.utc)

    assert slot_utc > utc_now
    # Ceiling of (19:52 + 1h) = 20:52 -> next hour boundary = 21:00 UTC.
    assert slot_utc == datetime(2026, 8, 7, 21, 0, 0, tzinfo=timezone.utc)


def test_occupied_times_use_static_publisher_runtime(monkeypatch, tmp_path):
    """Occupancy math must include committed static publisher runtime slots."""
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)  # Tuesday
    client = _make_client(
        monkeypatch,
        tmp_path,
        utc_now,
        scheduled_slots=["2026-08-04T10:30:00+00:00"],
    )

    slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())

    # 09:00 (1.5h from 10:30) and 13:00 (2.5h from 10:30) both violate the
    # 4h gap rule against the real date_gmt conflict; 17:00 rolls to the
    # next day at 09:00, which finally clears the gap.
    assert slot_dt.astimezone(timezone.utc) == datetime(2026, 8, 5, 9, 0, 0, tzinfo=timezone.utc)


def test_naive_runtime_schedule_raises_instead_of_silently_ignoring(monkeypatch, tmp_path):
    """A runtime slot without a UTC offset is a data-integrity bug."""
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(
        monkeypatch,
        tmp_path,
        utc_now,
        scheduled_slots=["2026-08-04T10:00:00"],
    )

    with pytest.raises(ClientError):
        client.find_next_schedule_slot()


def test_min_lead_guard_rejects_a_would_be_past_slot(monkeypatch, tmp_path):
    """Defense-in-depth: if candidate math regresses and produces a slot with
    no lead time, the final guard forces a safe retry instead of returning it.
    """
    utc_now = datetime(2026, 8, 7, 13, 0, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now)

    real_ceil = AtaBlogClient.__dict__["_ceil_to_hour"].__func__
    calls = {"n": 0}

    def fake_ceil(value):
        calls["n"] += 1
        if calls["n"] == 1:
            # Reproduce the historical bug shape: a "candidate" with zero
            # lead time over true now.
            return utc_now
        return real_ceil(value)

    monkeypatch.setattr(AtaBlogClient, "_ceil_to_hour", staticmethod(fake_ceil))

    slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())

    assert calls["n"] >= 2  # the guard actually triggered a retry
    assert slot_dt.astimezone(timezone.utc) >= utc_now + client._MIN_SCHEDULE_LEAD


def test_ceil_to_hour_leaves_an_exact_boundary_unchanged():
    on_boundary = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    assert AtaBlogClient._ceil_to_hour(on_boundary) == on_boundary


def test_ceil_to_hour_rounds_up_not_down():
    just_after = datetime(2026, 1, 1, 9, 0, 1, tzinfo=timezone.utc)
    assert AtaBlogClient._ceil_to_hour(just_after) == datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_read_schedule_reservations_discards_legacy_naive_entries(tmp_path):
    """Reservations written before the UTC-aware fix are naive datetimes;
    mixing them with the new aware comparisons would raise TypeError, so
    they must be treated as stale and dropped instead.
    """
    client = AtaBlogClient.__new__(AtaBlogClient)
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
