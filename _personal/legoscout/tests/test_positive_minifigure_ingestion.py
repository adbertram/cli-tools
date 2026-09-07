"""Proposed regression: reviewed minifigures survive the authoritative writer."""
import pytest

from legoscout_cli.ledger import build_record, db, ingestion
from legoscout_cli.pricing.minifig_receipt import (
    PUBLICATION_FIELDS, validate_publication_record,
)
from test_build_record_identification import (
    _appraisal, _candidate, _entry, _identification,
)


def test_reviewed_minifigure_builder_record_survives_ingestion_and_replay(tmp_path):
    server = str(tmp_path / "server.db")
    baseline = str(tmp_path / "baseline.db")
    db.init(server).close()
    db.snapshot(server, baseline, baseline=True)
    identification = _identification([_entry("g1", quantity=2, unit=30.0)])
    record = build_record.build_deal_record(
        _candidate(), _appraisal(),
        first_seen_at="2026-09-07T12:00:00Z",
        last_seen_at="2026-09-07T12:00:00Z",
        identification=identification, fee_rate=.13, favorite_sellers=set(),
    )
    payload = ingestion.prepare("reviewed-minifigure", baseline, [record])
    accepted = ingestion.ingest(payload, path=server)
    stored = db.get_deal("k-bid|1", path=server)
    assert accepted["inserted"] == 1
    assert accepted["updated"] == 0
    assert accepted["replayed"] is False
    assert stored["listing_category"] == "minifigure"
    assert stored["minifig_review_receipt"]["synthesis_sha256"]
    assert {
        key: value for key, value in stored["minifig_review_receipt"].items()
        if key != "synthesis_sha256"
    } == identification["minifig_review_receipt"]
    assert {key: stored[key] for key in PUBLICATION_FIELDS} == {
        key: record[key] for key in PUBLICATION_FIELDS
    }
    assert stored["figure_count"] == 2
    assert stored["potential_profit"] == 12.2
    assert stored["profit_incomplete"] is False
    validate_publication_record(stored, kind="deal")
    before_replay = db.load_document(server)
    assert ingestion.ingest(payload, path=server) == {**accepted, "replayed": True}
    assert db.load_document(server) == before_replay
    assert db.query("SELECT run_id FROM ingestion_runs", path=server) == [
        {"run_id": "reviewed-minifigure"}
    ]


def _built_record():
    identification = _identification([_entry("g1", quantity=2, unit=30.0)])
    return build_record.build_deal_record(
        _candidate(), _appraisal(),
        first_seen_at="2026-09-07T12:00:00Z",
        last_seen_at="2026-09-07T12:00:00Z",
        identification=identification, fee_rate=.13, favorite_sellers=set(),
    )


@pytest.mark.parametrize("field,value", [
    ("current_price", 1.0),
    ("estimated_total", 1.0),
    ("potential_profit", 999999.0),
    ("score", 100.0),
    ("source", "ebay"),
])
def test_post_build_deal_mutations_break_synthesis_receipt(field, value):
    record = _built_record()
    record[field] = value
    with pytest.raises(ValueError, match="changed after canonical synthesis"):
        validate_publication_record(record, kind="deal")


def test_server_owned_fields_do_not_break_synthesis_receipt():
    record = _built_record()
    record.update(
        status="rejected",
        last_status="rejected",
        first_seen_at="2020-01-01T00:00:00Z",
        last_seen_at="2030-01-01T00:00:00Z",
    )
    validate_publication_record(record, kind="deal")
