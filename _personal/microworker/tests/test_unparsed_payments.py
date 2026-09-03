"""A price the adapter could not read is a different fact from no price at all.

Both leave `pay_amount`/`pay_currency` null -- correct, because a price is never
invented -- so without a count of the second case a site changing its price
format ($1.50 -> $1.5, or "USD 1.00") stores every price as null, exits 0, and
silently drops those tasks out of `--filter pay_amount:gte:0` for months.

These tests pin the whole seam: the shared rule, each adapter that parses a
published price, the per-site counts in `merge`'s summary, the counts stored on
`run_sites`, the stderr warning, and the NULL a version-2 database keeps.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from cli_tools_shared.exceptions import ClientError

from conftest import SITES
from microworker_cli import db, envelope, merge, paths
from microworker_cli.adapters import humanrail, mapped, microworkers, oneforma
from microworker_cli.main import app
from test_adapter_humanrail import raw as humanrail_raw
from test_adapter_microworkers import raw as microworkers_raw
from test_adapter_oneforma import raw as oneforma_raw

RUN = "20260902T000000Z"
# The formats the audit fed the adapter: every one of these is a real price the
# regex refuses, and every one of them used to be stored as "unpriced".
UNREADABLE_PAYMENTS = ("$1.5", "$10", "USD 1.00", "$1,250.00", "$0.15 - $0.30")


@pytest.mark.parametrize("published, amount, expected", [
    ("$0.15", 0.15, False),
    (None, None, False),
    ("", None, False),
    ("   ", None, False),
    ("$1.5", None, True),
    ("$10", None, True),
    ("USD 1.00", None, True),
    ("$1,250.00", None, True),
    (0.15, None, True),
])
def test_is_unparsed_payment_table(published, amount, expected):
    assert mapped.is_unparsed_payment(published, amount) is expected


@pytest.mark.parametrize("payment", UNREADABLE_PAYMENTS)
def test_microworkers_reports_an_unreadable_price(payment):
    result = microworkers.to_task(microworkers_raw(payment=payment))
    assert result.unparsed_payment is True
    # Still null: the point is to report the gap, never to guess a number.
    assert result.task["pay_amount"] is None
    assert result.task["pay_currency"] is None


def test_microworkers_readable_price_is_not_reported():
    result = microworkers.to_task(microworkers_raw(payment="$0.15"))
    assert result.unparsed_payment is False
    assert result.task["pay_amount"] == 0.15


@pytest.mark.parametrize("payment", [None, "", "   "])
def test_microworkers_published_no_price_is_not_an_unparsed_price(payment):
    """An explicit null or a blank field is the site publishing nothing."""
    result = microworkers.to_task(microworkers_raw(payment=payment))
    assert result.unparsed_payment is False
    assert result.task["pay_amount"] is None


def test_microworkers_absent_payment_key_still_fails_loudly():
    """A record with no `payment` key never reaches the counter at all."""
    record = microworkers_raw()
    del record["payment"]
    with pytest.raises(ClientError, match="missing keys: payment"):
        microworkers.to_task(record)


@pytest.mark.parametrize("rate", ["1.5.0", "one hundred", "$100", "100 USD"])
def test_oneforma_reports_an_unreadable_rate(rate):
    result = oneforma.to_task(oneforma_raw(rate=rate))
    assert result.unparsed_payment is True
    assert result.task["pay_amount"] is None


@pytest.mark.parametrize("rate", [None, "", "   "])
def test_oneforma_published_no_rate_is_not_an_unparsed_rate(rate):
    result = oneforma.to_task(oneforma_raw(rate=rate))
    assert result.unparsed_payment is False
    assert result.task["pay_amount"] is None


def test_oneforma_readable_rate_is_not_reported():
    assert oneforma.to_task(oneforma_raw()).unparsed_payment is False


def test_oneforma_unknown_currency_symbol_is_not_an_unparsed_payment():
    """The amount was read; a null currency beside a real amount is visible."""
    result = oneforma.to_task(oneforma_raw(rate_currency_symbol="€"))
    assert result.unparsed_payment is False
    assert result.task["pay_amount"] == 100.0 and result.task["pay_currency"] is None


@pytest.mark.parametrize("payout_sats", [2500, None])
def test_humanrail_never_reports_an_unparsed_payment(payout_sats):
    """HumanRail publishes a number, not a display string this adapter parses."""
    assert humanrail.to_task(
        humanrail_raw(payout_sats=payout_sats)).unparsed_payment is False


def write_envelopes(microworkers_tasks: list, run_id: str = RUN) -> None:
    for name in SITES:
        if name == "microworkers":
            data = envelope.build(name, envelope.OK, None, microworkers_tasks)
        else:
            data = envelope.build(name, envelope.NO_ACCOUNT, "fixture", [])
        envelope.write(paths.envelope_path(run_id, name), data)


def test_merge_counts_unreadable_prices_per_site(project, clock):
    records = [microworkers_raw(campaign_id=f"c{index}", payment=payment)
               for index, payment in enumerate(UNREADABLE_PAYMENTS)]
    records.append(microworkers_raw(campaign_id="priced", payment="$0.15"))
    records.append(microworkers_raw(campaign_id="unpriced", payment=None))
    write_envelopes(records)

    summary = merge.merge(RUN)

    assert summary["unparsed_payments"]["microworkers"] == len(UNREADABLE_PAYMENTS)
    # Every configured site is keyed, so a healthy site is an explicit 0.
    assert set(summary["unparsed_payments"]) == set(SITES)
    assert all(count == 0 for site, count in summary["unparsed_payments"].items()
               if site != "microworkers")
    assert summary["task_count"] == len(records)


def test_merge_records_the_count_on_the_run(project, clock):
    write_envelopes([microworkers_raw(campaign_id="c1", payment="$1.5"),
                     microworkers_raw(campaign_id="c2", payment="$0.15")])
    merge.merge(RUN)

    sites = db.get_run(RUN)["sites"]
    assert sites["microworkers"]["unparsed_payments"] == 1
    assert sites["microworkers"]["task_count"] == 2
    assert sites["mercor"]["unparsed_payments"] == 0


def test_an_unpriced_run_reports_zero(project, clock, microworkers_record):
    write_envelopes([microworkers_record])
    summary = merge.merge(RUN)
    assert summary["unparsed_payments"] == {name: 0 for name in SITES}
    assert db.get_run(RUN)["sites"]["microworkers"]["unparsed_payments"] == 0


def test_cli_merge_prints_the_counts_and_warns_on_stderr(project, clock, runner):
    write_envelopes([microworkers_raw(campaign_id="c1", payment="$1.5"),
                     microworkers_raw(campaign_id="c2", payment="$10")])
    outcome = runner.invoke(app, ["merge", RUN])

    assert outcome.exit_code == 0, outcome.output
    summary = json.loads(outcome.stdout)
    assert summary["unparsed_payments"]["microworkers"] == 2
    assert "microworkers=2" in outcome.stderr
    # The one task filter that the defect broke, over the stored rows.
    assert db.list_tasks()[0]["pay_amount"] is None


def test_cli_merge_stays_quiet_when_every_price_parsed(
        project, clock, runner, microworkers_record):
    write_envelopes([microworkers_record])
    outcome = runner.invoke(app, ["merge", RUN])
    assert outcome.exit_code == 0, outcome.output
    assert "Unparsed payments" not in outcome.stderr


def test_version_2_rows_keep_a_null_count_and_new_rows_do_not(project, clock):
    """The migration adds the column; it does not invent history for old runs.

    A backfilled 0 would assert that no pre-version-3 run ever hit a price its
    adapter could not read. Nothing counted back then, so the honest value is
    NULL -- unknown -- and only runs merged after the migration carry a number.
    """
    path = paths.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(path)
    try:
        legacy.executescript(
            db.SCHEMA_SQL.replace("    unparsed_payments INTEGER,\n", ""))
        legacy.execute(
            "INSERT INTO runs (run_id, merged_at, task_count, inserted, updated, "
            "skipped_stale) VALUES ('20260101T000000Z', '2026-01-01T00:00:00Z', "
            "0, 0, 0, 0)")
        legacy.execute(
            "INSERT INTO run_sites (run_id, site, status, error, fetched_at, "
            "task_count) VALUES ('20260101T000000Z', 'microworkers', 'ok', NULL, "
            "'2026-01-01T00:00:00Z', 0)")
        legacy.commit()
    finally:
        legacy.close()

    write_envelopes([microworkers_raw(campaign_id="c1", payment="$1.5")])
    merge.merge(RUN)

    old = db.get_run("20260101T000000Z")["sites"]["microworkers"]
    assert old["unparsed_payments"] is None
    assert db.get_run(RUN)["sites"]["microworkers"]["unparsed_payments"] == 1
