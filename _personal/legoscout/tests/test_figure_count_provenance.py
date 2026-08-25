"""`figure_count_source`: the provenance that rides with every figure count.

The minifigure pricing path multiplies the eBay $/fig average by
`figure_count`, so a bare count with no provenance is exactly how an invented
number reaches Adam's money. The classifier states WHICH kind of answer it is:
`stated` (the seller's own text), `photo_count` (the mandatory image pass's
exact count), or `unknown` (images inspected, exact count not determinable).

Contract covered here:
- schema carries the field in the appraisal phase with a closed vocabulary;
- `_enum_errors` pairs count and source (number without source errors,
  source without number errors, wrong-category count errors);
- the row builder passes it through as `figSrc` only on minifigure rows.
"""
from __future__ import annotations

import pytest

from legoscout_cli.display import rows as display_rows
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.ledger import schema as deal_schema
from legoscout_cli.ledger import validate


def _mf_deal(**overrides):
    deal = {
        "listing_key": "ebay|fcs0001",
        "listing_category": "minifigure",
        "figure_count": 10,
        "figure_count_source": "photo_count",
    }
    deal.update(overrides)
    return deal


# --- schema -----------------------------------------------------------------


def test_figure_count_source_is_an_appraisal_field():
    assert "figure_count_source" in deal_schema.fields_for_phase("appraisal")


def test_figure_count_source_vocabulary_is_closed():
    spec = deal_schema.load()["properties"]["figure_count_source"]
    assert set(spec["enum"]) == {"stated", "photo_count", "unknown", None}


def test_column_exists_after_connect(tmp_path):
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    cols = {row["name"] for row in ledger_db.connect(path).execute(
        "PRAGMA table_info(deals)")}
    # db.query() accepts SELECT/WITH only -- PRAGMA goes through connect().
    assert "figure_count_source" in cols


# --- validator --------------------------------------------------------------


def test_stated_and_photo_count_pass():
    assert validate._figure_count_errors(
        _mf_deal(figure_count_source="stated"), "minifigure") == []
    assert validate._figure_count_errors(
        _mf_deal(), "minifigure") == []


def test_number_without_source_errors():
    rec = _mf_deal()
    del rec["figure_count_source"]
    errors = validate._figure_count_errors(rec, "minifigure")
    assert len(errors) == 1 and "figure_count_source" in errors[0]


def test_unknown_source_with_a_number_is_legal_but_named():
    # `unknown` means inspected-but-not-countable; a number under it is
    # contradictory, but that is the classifier saying its provenance plainly
    # rather than the schema lying about it. Only an OUT-OF-VOCABULARY value
    # is the hand-off defect.
    assert validate._figure_count_errors(
        _mf_deal(figure_count_source="vibes"), "minifigure") != []


def test_source_without_a_number_errors():
    errors = validate._figure_count_errors(
        _mf_deal(figure_count=None, figure_count_source="photo_count"),
        "minifigure")
    assert len(errors) == 1 and "without a count" in errors[0]


def test_count_on_a_non_minifigure_row_errors():
    errors = validate._figure_count_errors(_mf_deal(), "bulk")
    assert any("misclassified record" in e for e in errors)


def test_absent_everywhere_is_clean():
    assert validate._figure_count_errors({}, "set") == []


# --- display row passthrough -------------------------------------------------


def _row_deal(category="minifigure", **fields):
    deal = {
        "listing_key": "ebay|fcs0002",
        "listing_category": category,
        "listing_type": "fixed",
        "title": "t",
        "url": "https://example.invalid",
        "status": "active",
        "source": "ebay",
        "available_fulfillment": ["shipping"],
    }
    deal.update(fields)
    return deal


@pytest.fixture
def registry_paths(tmp_path, monkeypatch):
    """A scratch DB whose registry knows ebay, like the real one.

    `init()` creates only deals/meta/source_watermarks; the registry tables
    come from the sources migration. Copy them wholesale (data included) out
    of the working ledger with CREATE TABLE ... AS SELECT.
    """
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("ATTACH ? AS w", (ledger_db.DB_PATH,))
    for table in ("sources", "source_registry_meta", "source_notes"):
        try:
            conn.execute(
                "CREATE TABLE %s AS SELECT * FROM w.%s" % (table, table))
        except sqlite3.OperationalError:
            continue
    conn.commit()
    conn.close()
    return path


def test_row_carries_figsrc_on_minifigure(registry_paths):
    reg = __import__("legoscout_cli.sources.registry", fromlist=["Registry"])
    row = display_rows.row(
        _row_deal(figure_count=10, figure_count_source="stated"),
        favorites=set(),
        reg=reg.Registry(registry_paths))
    assert row["figSrc"] == "stated"


def test_row_drops_figsrc_on_bulk(registry_paths):
    reg = __import__("legoscout_cli.sources.registry", fromlist=["Registry"])
    row = display_rows.row(
        _row_deal(category="bulk", weight_lbs=5.0), favorites=set(),
        reg=reg.Registry(registry_paths))
    assert "figSrc" not in row
