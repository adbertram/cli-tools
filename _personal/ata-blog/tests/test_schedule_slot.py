"""Regression tests for find_next_schedule_slot future-slot selection.

Guards against two related production bugs:

1. (Original) auto-schedule snapped `now` down to the current hour and
   returned a slot at or before `now` (e.g. 17:00 when it was 17:46),
   causing the post to publish immediately instead of scheduling.

2. (Root cause behind a later incident) find_next_schedule_slot used
   datetime.now() -- the CLI host machine's naive LOCAL time (e.g. CDT,
   UTC-5) -- instead of true UTC. Scheduled Notion pages carry explicit UTC
   offsets; when the host's local timezone trailed true
   UTC, the naive "now" was read as if it were already UTC, producing a
   candidate slot hours in the past relative to true UTC now.

This is the live code path for `ata-blog notion-page publish --auto-schedule`
(AtaBlogClient.publish_article -> AtaBlogClient._schedule_article ->
AtaBlogClient.find_next_schedule_slot).
"""

from __future__ import annotations

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
    # Occupied slots are the Notion pages in Status "Scheduled". The recording
    # stub stands in for that one query, so no test here reaches the notion CLI.
    client.scheduled_pages = [
        {
            "id": f"page-{index}",
            "Title": f"Scheduled post {index}",
            "Status": "Scheduled",
            "Publish Date": slot,
        }
        for index, slot in enumerate(scheduled_slots or [])
    ]
    client.list_calls = []

    def list_articles(status=None, limit=100, filters=None):
        client.list_calls.append({"status": status, "limit": limit, "filters": filters})
        return list(client.scheduled_pages)

    client.list_articles = list_articles
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
    # now (17:46) + 1h = 18:46, ceiled up to the next hour boundary: 19:00, which
    # is past the 17:00 window close, so the slot rolls to the next weekday's
    # 09:00 opening rather than publishing in the evening.
    assert slot_utc == datetime(2026, 7, 22, 9, 0, 0, tzinfo=timezone.utc)


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
    # Ceiling of (19:52 + 1h) = 20:52 -> next hour boundary = 21:00 UTC, which is
    # outside the 09:00-17:00 window, so it rolls forward over the weekend to
    # Monday 09:00. Reading the host's local clock instead (14:52 CDT) would have
    # produced an in-window 16:00 slot on the Friday, so this assertion still
    # discriminates true UTC from host local time.
    assert slot_utc == datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)


def test_occupied_times_come_from_notion_scheduled_pages(monkeypatch, tmp_path):
    """Occupancy math must read the Notion pages in Status Scheduled."""
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)  # Tuesday
    client = _make_client(
        monkeypatch,
        tmp_path,
        utc_now,
        scheduled_slots=["2026-08-04T10:30:00+00:00"],
    )

    slot_dt = datetime.fromisoformat(client.find_next_schedule_slot())

    assert client.list_calls == [{"status": "Scheduled", "limit": 100, "filters": None}]
    # 09:00 (1.5h from 10:30) and 13:00 (2.5h from 10:30) both violate the
    # 4h gap rule against the scheduled page; 17:00 rolls to the next day at
    # 09:00, which finally clears the gap.
    assert slot_dt.astimezone(timezone.utc) == datetime(2026, 8, 5, 9, 0, 0, tzinfo=timezone.utc)


def test_naive_notion_publish_date_raises_and_names_the_page(monkeypatch, tmp_path):
    """A Scheduled page whose Publish Date has no UTC offset is a data-integrity bug."""
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(
        monkeypatch,
        tmp_path,
        utc_now,
        scheduled_slots=["2026-08-04T10:00:00"],
    )

    with pytest.raises(ClientError, match=r"page-0.*UTC offset"):
        client.find_next_schedule_slot()


def test_scheduled_page_without_publish_date_raises(monkeypatch, tmp_path):
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now, scheduled_slots=[None])

    with pytest.raises(ClientError, match=r"page-0.*no Publish Date"):
        client.find_next_schedule_slot()


def test_scheduled_query_at_the_list_limit_raises(monkeypatch, tmp_path):
    """100 rows from a limit-100 query is an incomplete read, never a complete one."""
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(
        monkeypatch,
        tmp_path,
        utc_now,
        scheduled_slots=["2027-01-04T09:00:00+00:00"] * 100,
    )

    with pytest.raises(ClientError, match="reached the 100-page list limit"):
        client.find_next_schedule_slot()


def test_window_with_two_scheduled_pages_per_day_raises_no_available_slot(monkeypatch, tmp_path):
    utc_now = datetime(2026, 8, 3, 8, 0, 0, tzinfo=timezone.utc)  # Monday
    client = _make_client(
        monkeypatch,
        tmp_path,
        utc_now,
        scheduled_slots=["2026-08-04T09:00:00+00:00", "2026-08-04T13:00:00+00:00"],
    )
    window = (
        datetime(2026, 8, 4, 9, 0, 0, tzinfo=timezone.utc),  # Tuesday
        datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(
        ClientError, match="No available schedule slot inside the frozen scheduling window"
    ):
        client.find_next_schedule_slot(window)


def test_explicit_date_equal_to_a_scheduled_pages_publish_date_is_rejected(monkeypatch, tmp_path):
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(
        monkeypatch, tmp_path, utc_now, scheduled_slots=["2026-09-01T13:00:00+00:00"]
    )

    # The same instant written with another offset is still the occupied slot.
    with pytest.raises(ClientError, match="Schedule slot is already occupied"):
        client._require_free_explicit_slot("2026-09-01T08:00:00-05:00")

    assert client.list_calls == [{"status": "Scheduled", "limit": 100, "filters": None}]


def test_explicit_date_without_utc_offset_is_rejected(monkeypatch, tmp_path):
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now)

    with pytest.raises(ClientError, match="--date must include a UTC offset"):
        client._require_free_explicit_slot("2026-09-01T13:00:00")


def test_explicit_date_outside_the_frozen_window_is_rejected(monkeypatch, tmp_path):
    utc_now = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    client = _make_client(monkeypatch, tmp_path, utc_now)
    window = (
        datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 17, 0, 0, tzinfo=timezone.utc),
    )

    # The window is [start, end): its end and the second before its start are out.
    for outside in ("2026-09-01T17:00:00+00:00", "2026-09-01T08:59:59+00:00"):
        with pytest.raises(
            ClientError, match="Schedule date is outside the frozen scheduling window"
        ):
            client._require_free_explicit_slot(outside, window)

    assert (
        client._require_free_explicit_slot("2026-09-01T09:00:00+00:00", window)
        == "2026-09-01T09:00:00+00:00"
    )


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


def test_evening_seed_rolls_into_the_next_weekday_window(monkeypatch, tmp_path):
    """A candidate seeded after the window closes must not be handed back.

    Before the window guard was unified, the 17:00 upper bound was only checked
    inside the 4-hour-gap conflict branch, so an evening seed with no conflicts
    was accepted unclamped (e.g. 20:00 UTC).
    """
    utc_now = datetime(2026, 9, 7, 19, 3, 0, tzinfo=timezone.utc)  # Monday evening
    client = _make_client(monkeypatch, tmp_path, utc_now)

    slot_utc = datetime.fromisoformat(client.find_next_schedule_slot()).astimezone(timezone.utc)

    assert slot_utc == datetime(2026, 9, 8, 9, 0, 0, tzinfo=timezone.utc)


def test_consecutive_slots_all_land_inside_the_publishing_window(monkeypatch, tmp_path):
    """Serialized publishes must never walk past the window.

    The reported failure: three consecutive calls from a Monday evening returned
    20:00, 00:00 and 04:00 UTC, because each 4-hour conflict push skipped the
    upper-bound check once the candidate crossed midnight.
    """
    utc_now = datetime(2026, 9, 7, 19, 3, 0, tzinfo=timezone.utc)  # Monday evening
    client = _make_client(monkeypatch, tmp_path, utc_now)

    slots = []
    for index in range(20):
        slot = client.find_next_schedule_slot()
        # What the Notion write does: the picked slot becomes a Scheduled page
        # the next pick reads back.
        client.scheduled_pages.append(
            {
                "id": f"picked-{index}",
                "Title": f"Picked post {index}",
                "Status": "Scheduled",
                "Publish Date": slot,
            }
        )
        slots.append(datetime.fromisoformat(slot).astimezone(timezone.utc))

    for slot in slots:
        assert slot.weekday() < 5, f"{slot.isoformat()} falls on a weekend"
        assert 9 <= slot.hour < 17, f"{slot.isoformat()} falls outside 09:00-17:00 UTC"
    assert slots == sorted(slots)
    assert len(set(slots)) == len(slots)
    assert slots[:3] == [
        datetime(2026, 9, 8, 9, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 8, 13, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 9, 9, 0, 0, tzinfo=timezone.utc),
    ]
