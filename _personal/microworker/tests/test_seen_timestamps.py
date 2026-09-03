"""Seen timestamps are observation times, and older sightings do not win.

A task's `first_seen_at`/`last_seen_at` come from its envelope's `fetched_at` --
when the site's CLI actually answered -- while `runs.merged_at` is the merge
wallclock. Merges do not have to run in observation order, so the two clocks are
driven apart here on purpose: `clock` sets the envelope's `fetched_at` at write
time, and `merged` sets it again at merge time, which is what stamps the run row.
"""

from __future__ import annotations

from conftest import SITES
from microworker_cli import db, envelope, merge, paths

JANUARY_RUN = "20260101T000000Z"
SEPTEMBER_RUN = "20260902T000000Z"
JANUARY = "2026-01-01T00:00:00Z"
SEPTEMBER = "2026-09-02T00:00:00Z"
MERGED_AT = "2026-12-25T00:00:00Z"


def write_run(clock, run_id: str, fetched_at: str, tasks: list) -> None:
    """One envelope per site for `run_id`, all observed at `fetched_at`."""
    clock.set(fetched_at)
    for name in SITES:
        if name == "microworkers":
            data = envelope.build(name, envelope.OK, None, tasks)
        else:
            data = envelope.build(name, envelope.NO_ACCOUNT, "fixture", [])
        envelope.write(paths.envelope_path(run_id, name), data)


def merge_at(clock, run_id: str, merged_at: str = MERGED_AT) -> dict:
    """Merge with the wallclock set to `merged_at`, not to any fetched_at."""
    clock.set(merged_at)
    return merge.merge(run_id)


def test_seen_timestamps_come_from_the_envelope_not_the_merge_clock(
        project, clock, microworkers_record):
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [microworkers_record])
    merge_at(clock, SEPTEMBER_RUN)

    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task["first_seen_at"] == SEPTEMBER
    assert task["last_seen_at"] == SEPTEMBER
    # The merge wallclock stamps the run row and only the run row.
    assert db.get_run(SEPTEMBER_RUN)["merged_at"] == MERGED_AT


def test_two_sightings_months_apart_keep_distinct_timestamps(
        project, clock, microworkers_record):
    write_run(clock, JANUARY_RUN, JANUARY, [microworkers_record])
    merge_at(clock, JANUARY_RUN, "2026-01-01T06:00:00Z")
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [microworkers_record])
    merge_at(clock, SEPTEMBER_RUN, "2026-09-02T06:00:00Z")

    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task["first_seen_at"] == JANUARY
    assert task["last_seen_at"] == SEPTEMBER


def test_out_of_order_merge_cannot_overwrite_fresher_contract_columns(
        project, clock, microworkers_record):
    """September merged first, then January: January must not win the title."""
    september = dict(microworkers_record, title="September title", payment="$0.99")
    january = dict(microworkers_record, title="January title", payment="$0.10")
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [september])
    merge_at(clock, SEPTEMBER_RUN)
    write_run(clock, JANUARY_RUN, JANUARY, [january])
    summary = merge_at(clock, JANUARY_RUN)

    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task["title"] == "September title"
    assert task["pay_amount"] == 0.99
    assert task["raw"] == september
    assert task["last_seen_at"] == SEPTEMBER
    assert task["last_seen_run_id"] == SEPTEMBER_RUN
    # The stale sighting is still the earliest one, so it widens first-seen.
    assert task["first_seen_at"] == JANUARY
    assert task["first_seen_run_id"] == JANUARY_RUN
    assert summary["updated"] == 0 and summary["skipped_stale"] == 1


def test_first_seen_never_lands_after_last_seen(project, clock, microworkers_record):
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [microworkers_record])
    merge_at(clock, SEPTEMBER_RUN)
    write_run(clock, JANUARY_RUN, JANUARY, [microworkers_record])
    merge_at(clock, JANUARY_RUN)

    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task["first_seen_at"] <= task["last_seen_at"]
    assert task["first_seen_run_id"] < task["last_seen_run_id"]


def test_counts_partition_the_run_into_inserted_updated_skipped(
        project, clock, microworkers_record):
    """A skipped-as-stale sighting is neither an insert nor an update."""
    fresh = dict(microworkers_record, campaign_id="fresh01")
    stale = dict(microworkers_record, campaign_id="stale01")
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [fresh, stale])
    merge_at(clock, SEPTEMBER_RUN)

    brand_new = dict(microworkers_record, campaign_id="brandnew01")
    write_run(clock, JANUARY_RUN, JANUARY, [stale, brand_new])
    summary = merge_at(clock, JANUARY_RUN)

    assert summary["task_count"] == 2
    assert summary["inserted"] == 1
    assert summary["updated"] == 0
    assert summary["skipped_stale"] == 1
    assert (summary["inserted"] + summary["updated"] + summary["skipped_stale"]
            == summary["task_count"])
    assert db.get_run(JANUARY_RUN)["skipped_stale"] == 1


def test_equally_fresh_sighting_still_refreshes(project, clock, microworkers_record):
    """Same `fetched_at` from a later run is applied, so re-merges stay idempotent."""
    first = dict(microworkers_record, title="First")
    second = dict(microworkers_record, title="Second")
    write_run(clock, JANUARY_RUN, SEPTEMBER, [first])
    merge_at(clock, JANUARY_RUN)
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [second])
    summary = merge_at(clock, SEPTEMBER_RUN)

    assert summary["updated"] == 1 and summary["skipped_stale"] == 0
    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task["title"] == "Second"
    # Equal observation times do not move first-seen off the run that set it.
    assert task["first_seen_run_id"] == JANUARY_RUN


def test_a_run_merged_from_an_old_database_gains_a_zero_skipped_count(
        project, clock, microworkers_record):
    """`runs.skipped_stale` is added to a schema-version-1 database in place."""
    write_run(clock, SEPTEMBER_RUN, SEPTEMBER, [microworkers_record])
    merge_at(clock, SEPTEMBER_RUN)

    # Reduce the live database to the version-1 `runs` shape, then merge again.
    conn = db.connect()
    try:
        conn.execute("ALTER TABLE runs DROP COLUMN skipped_stale")
        conn.commit()
    finally:
        conn.close()

    write_run(clock, JANUARY_RUN, JANUARY, [microworkers_record])
    merge_at(clock, JANUARY_RUN)
    runs = {run["run_id"]: run for run in db.list_runs()}
    assert runs[SEPTEMBER_RUN]["skipped_stale"] == 0
    assert runs[JANUARY_RUN]["skipped_stale"] == 1
