"""The prospect tables and the code that reads them must name the same columns.

`legoscout prospects runs list` failed with `no such column: id` because
`commands/prospects.py` wrote its own SQL against a key it assumed rather than
the key `_SCHEMA` creates. Every prospect table names its key after itself
(`run_id`, `outreach_id`), so `id` exists nowhere. The `--table` column sets had
drifted the same way, but a missing display column renders as a blank cell, so
that half never raised.

These tests close both halves against a real database: the declared keys are
compared with PRAGMA table_info, every declared display column is compared with
the columns the table actually has, and every read path is executed.
"""
from __future__ import annotations

import pytest

from legoscout_cli.commands import prospects as prospects_cmd
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.ledger import prospects as prospects_db
from legoscout_cli.prospector import hypothesis_types

TABLES = ("prospects", "contacts", "outreach", "prospect_runs")

# Which table each `--table` column set describes.
COLUMN_SETS = {
    "prospects": prospects_cmd.PROSPECT_COLUMNS,
    "contacts": prospects_cmd.CONTACT_COLUMNS,
    "outreach": prospects_cmd.OUTREACH_COLUMNS,
    "prospect_runs": prospects_cmd.RUN_COLUMNS,
}


@pytest.fixture
def db_path(tmp_path):
    """An empty ledger at the current schema, seeded with one row per table."""
    path = str(tmp_path / "found_deals.db")
    # `connect()` refuses to create the ledger on purpose, so the test builds it
    # the way the migration does. `prospects.connect()` then adds _SCHEMA.
    ledger_db.init(path).close()
    prospect_id = prospects_db.insert_prospect(
        {
            "name": "Guard Test Resale",
            "hypothesis_type": "kids_resale_stores",
            "citation_url": "https://example.invalid/guard-test",
            "location": "Evansville, IN",
            "distance_miles": 5.0,
            "available_fulfillment": ["local_pickup"],
            "status": "active",
        },
        [{"person_name": "store", "email": "guard@example.invalid"}],
        path=path,
    )
    contact_id = prospects_db.list_contacts(path=path)[0][
        prospects_db.PRIMARY_KEYS["contacts"]]
    prospects_db.create_outreach(
        prospect_id, contact_id, subject="Guard test",
        body="Guard test body.", path=path)
    prospects_db.record_run(
        "20260806T000000Z", "kids_resale_stores", ["guard test search"], 1,
        path=path)
    return path


def _columns(path: str, table: str) -> list[str]:
    conn = prospects_db.connect(path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)]
    finally:
        conn.close()


def _primary_key(path: str, table: str) -> str:
    conn = prospects_db.connect(path)
    try:
        keys = [row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)
                if row[5]]
    finally:
        conn.close()
    assert len(keys) == 1, "%s must have exactly one primary key column" % table
    return keys[0]


@pytest.mark.parametrize("table", TABLES)
def test_declared_primary_key_matches_the_schema(db_path, table):
    assert prospects_db.PRIMARY_KEYS[table] == _primary_key(db_path, table)


def test_no_prospect_table_has_a_bare_id_column(db_path):
    """The assumption that produced the bug, stated as an assertion."""
    for table in TABLES:
        assert "id" not in _columns(db_path, table)


@pytest.mark.parametrize("table", TABLES)
def test_declared_table_columns_exist(db_path, table):
    actual = _columns(db_path, table)
    missing = [name for name in COLUMN_SETS[table] if name not in actual]
    assert not missing, "%s columns not in the table: %s" % (table, missing)


def test_declared_hypothesis_columns_exist():
    """The registry is JSON, but an invented key renders blank there too."""
    entries = hypothesis_types.table()
    assert entries, "the hypothesis registry must not be empty"
    for name, entry in entries.items():
        available = set(entry) | {"hypothesis_type"}
        missing = [key for key in prospects_cmd.HYPOTHESIS_COLUMNS
                   if key not in available]
        assert not missing, "%s carries no %s" % (name, missing)


def test_every_list_read_returns_its_seeded_row(db_path):
    """Executes the SQL each `list` command runs, so a bad column raises here."""
    assert len(prospects_db.list_prospects(path=db_path)) == 1
    assert len(prospects_db.list_contacts(path=db_path)) == 1
    assert len(prospects_db.list_outreach(path=db_path)) == 1
    assert len(prospects_db.list_runs(path=db_path)) == 1


def test_every_single_row_read_finds_its_seeded_row(db_path):
    run = prospects_db.list_runs(path=db_path)[0]
    key = prospects_db.PRIMARY_KEYS["prospect_runs"]
    assert prospects_db.run_row(run[key], path=db_path)["run_key"] == \
        "20260806T000000Z"

    outreach = prospects_db.list_outreach(path=db_path)[0]
    outreach_key = prospects_db.PRIMARY_KEYS["outreach"]
    assert prospects_db.outreach_row(
        outreach[outreach_key], path=db_path)["subject"] == "Guard test"

    contact = prospects_db.list_contacts(path=db_path)[0]
    contact_key = prospects_db.PRIMARY_KEYS["contacts"]
    assert prospects_db.contact_row(
        contact[contact_key], path=db_path)["person_name"] == "store"


def test_missing_row_reads_return_none_rather_than_raising(db_path):
    assert prospects_db.run_row(9999, path=db_path) is None
    assert prospects_db.outreach_row(9999, path=db_path) is None
    assert prospects_db.contact_row(9999, path=db_path) is None
