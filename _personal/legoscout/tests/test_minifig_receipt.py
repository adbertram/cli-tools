"""Offline acceptance tests for reviewed input, publication, and ledger receipts."""
import copy
import hashlib
import json

import pytest

from legoscout_cli.pricing import minifig_identification as identification
from legoscout_cli.pricing import minifig_receipt as receipt
from legoscout_cli.pricing.minifig_checker_prompt import build
from minifig_review_fixtures import prepare_review_files
from test_minifig_contract_repairs import _artifact, _group, _priced


def _verified():
    return _artifact([("ebay|1", [_group("g1", "c1", candidates=("sw0001", "sw0002"))],
                       "success", None)])


def _review(tmp_path):
    output = tmp_path / "ebay.identify-1.json"
    source = prepare_review_files(tmp_path, _verified(), output)
    return source, output


def _complete(tmp_path, output):
    return receipt.complete(scratch_dir=str(tmp_path),
                            identifier_run_json=str(tmp_path / "identifier-run.json"),
                            checker_result_json=str(tmp_path / "checker-result.json"),
                            artifact=str(output))


def test_reject_changed_verified_identity_after_checker_pass_at_every_boundary(tmp_path):
    source, output = _review(tmp_path)
    mutated = json.loads(source.read_bytes())
    group = mutated["listings"][0]["groups"][0]
    group["fig_no"] = "sw0002"
    group["catalog"]["no"] = "sw0002"
    source.write_text(json.dumps(mutated))
    calls = []
    with pytest.raises(receipt.AuditError, match="changed after checker request"):
        receipt.gate(scratch_dir=str(tmp_path),
                     identifier_run_json=str(tmp_path / "identifier-run.json"),
                     checker_result_json=str(tmp_path / "checker-result.json"))
    with pytest.raises(receipt.AuditError, match="changed after checker request"):
        identification.price_file(source, output, pricer=lambda *args, **kwargs: calls.append(args))
    assert calls == []
    assert not output.exists()
    with pytest.raises(receipt.AuditError, match="changed after checker request"):
        _complete(tmp_path, output)
    assert not (tmp_path / "identifier.complete.json").exists()


def test_reject_whitespace_change_and_refreeze_after_checker_pass(tmp_path):
    source, output = _review(tmp_path)
    original = (tmp_path / "checker-request.json").read_bytes()
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(receipt.AuditError, match="already frozen"):
        build(verified_json=str(source), identifier_run_json=str(tmp_path / "identifier-run.json"),
              launch_marker_json=str(tmp_path / "identifier.launch.json"))
    assert (tmp_path / "checker-request.json").read_bytes() == original
    with pytest.raises(receipt.AuditError, match="changed after checker request"):
        identification.price_file(source, output, pricer=_priced)


def test_publish_and_consume_portable_receipt_then_reject_tampering(tmp_path):
    source, output = _review(tmp_path)
    identification.price_file(source, output, pricer=_priced)
    row = json.loads(output.read_bytes())[0]
    receipt.validate_publication_record(row, kind="identification")
    _complete(tmp_path, output)
    marker = json.loads((tmp_path / "identifier.complete.json").read_bytes())
    assert marker["verified_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert marker["artifact_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    # The ingestion validator does not require worker-local files.
    deal = {key: row[key] for key in receipt.PUBLICATION_FIELDS}
    deal.update(listing_category="minifigure", status="active", profit_incomplete=False,
                minifig_review_receipt=copy.deepcopy(row[receipt.RECEIPT_FIELD]))
    receipt.bind_deal_record(deal)
    receipt.validate_publication_record(deal, kind="deal")
    for field, value in (("figure_count", 99), ("listing_key", "ebay|2")):
        altered = copy.deepcopy(deal)
        altered[field] = value
        with pytest.raises(receipt.AuditError, match="changed after pricing"):
            receipt.validate_publication_record(altered, kind="deal")
    altered = copy.deepcopy(deal)
    altered["minifig_analysis"][0]["fig_no"] = "sw0002"
    # Updating only the publication digest still cannot launder an unchecked identity.
    altered[receipt.RECEIPT_FIELD]["publication_sha256"] = receipt.publication_digest(
        altered, altered[receipt.RECEIPT_FIELD]["pricing_complete"])
    with pytest.raises(receipt.AuditError, match="does not match reviewed identity"):
        receipt.validate_publication_record(altered, kind="deal")


def test_reject_changed_pricing_completeness_even_with_category_injected(tmp_path):
    source, output = _review(tmp_path)
    identification.price_file(source, output, pricer=_priced)
    row = json.loads(output.read_bytes())[0]
    row["pricing_complete"] = False
    row["listing_category"] = "minifigure"
    with pytest.raises(receipt.AuditError, match="priced row changed"):
        receipt.validate_publication_record(row, kind="identification")


def test_price_publication_is_one_shot_and_complete_is_idempotent(tmp_path):
    source, output = _review(tmp_path)
    identification.price_file(source, output, pricer=_priced)
    _complete(tmp_path, output)
    marker = (tmp_path / "identifier.complete.json").read_bytes()
    assert _complete(tmp_path, output)["ok"]
    assert marker == (tmp_path / "identifier.complete.json").read_bytes()
    with pytest.raises(receipt.AuditError, match="one-shot"):
        identification.price_file(source, output, pricer=_priced)
    output.write_bytes(output.read_bytes() + b"\n")
    with pytest.raises(receipt.AuditError, match="already completed"):
        _complete(tmp_path, output)
    assert marker == (tmp_path / "identifier.complete.json").read_bytes()


@pytest.mark.parametrize("field", ["verified_sha256", "request_sha256"])
def test_unbound_checker_receipts_fail_before_pricing(tmp_path, field):
    source, output = _review(tmp_path)
    checker_path = tmp_path / "checker-result.json"
    checker = json.loads(checker_path.read_bytes())
    del checker[field]
    checker_path.write_text(json.dumps(checker))
    with pytest.raises(receipt.AuditError, match="keys must be exactly"):
        identification.price_file(source, output, pricer=_priced)
    assert not output.exists()


def test_price_uses_same_input_buffer_that_passed_digest_check(tmp_path, monkeypatch):
    source, output = _review(tmp_path)
    original = receipt.consume_review
    def mutate_after_check(*args, **kwargs):
        result = original(*args, **kwargs)
        modified = json.loads(source.read_bytes())
        modified["listings"][0]["groups"][0]["fig_no"] = "sw0002"
        source.write_text(json.dumps(modified))
        return result
    monkeypatch.setattr(receipt, "consume_review", mutate_after_check)
    identification.price_file(source, output, pricer=_priced)
    row = json.loads(output.read_bytes())[0]
    assert row["minifig_analysis"][0]["fig_no"] == "sw0001"
    receipt.validate_publication_record(row, kind="identification")
    with pytest.raises(receipt.AuditError, match="changed after checker request"):
        _complete(tmp_path, output)


def test_publish_preserves_nonlexical_input_order(tmp_path):
    artifact = _artifact([
        ("ebay|2", [_group("g2", "c2")], "success", None),
        ("ebay|1", [_group("g1", "c1")], "success", None),
    ])
    output = tmp_path / "ebay.identify-1.json"
    source = prepare_review_files(tmp_path, artifact, output)
    identification.price_file(source, output, pricer=_priced)
    assert [row["listing_key"] for row in json.loads(output.read_bytes())] == ["ebay|2", "ebay|1"]
    _complete(tmp_path, output)


def test_completion_rejects_other_runs_valid_receipt(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    source, output = _review(first)
    other_source, other_output = _review(second)
    identification.price_file(source, output, pricer=_priced)
    identification.price_file(other_source, other_output, pricer=_priced)
    output.write_bytes(other_output.read_bytes())
    with pytest.raises(receipt.AuditError, match="does not match this review request"):
        _complete(first, output)
    assert not (first / "identifier.complete.json").exists()


def test_ingestion_rejects_changed_receipt_completeness(tmp_path):
    source, output = _review(tmp_path)
    identification.price_file(source, output, pricer=_priced)
    row = json.loads(output.read_bytes())[0]
    deal = {key: row[key] for key in receipt.PUBLICATION_FIELDS}
    deal.update(listing_category="minifigure", profit_incomplete=False,
                minifig_review_receipt=row[receipt.RECEIPT_FIELD])
    receipt.bind_deal_record(deal)
    deal[receipt.RECEIPT_FIELD]["pricing_complete"] = False
    with pytest.raises(receipt.AuditError, match="changed after pricing"):
        receipt.validate_publication_record(deal, kind="deal")


def test_publication_does_not_overwrite_output_created_during_pricing(tmp_path):
    source, output = _review(tmp_path)
    sentinel = b"a concurrent publisher won"
    def pricer(*args, **kwargs):
        output.write_bytes(sentinel)
        return _priced(*args, **kwargs)
    with pytest.raises(identification.DetectionOutputError, match="FileExistsError"):
        identification.price_file(source, output, pricer=pricer)
    assert output.read_bytes() == sentinel
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.parametrize("mutation", ["drop", "reverse", "duplicate"])
@pytest.mark.parametrize("existing_marker", [False, True])
def test_completion_rejects_changed_batch_coverage_before_marker_acceptance(
    tmp_path, mutation, existing_marker,
):
    artifact = _artifact([
        ("ebay|2", [_group("g2", "c2")], "success", None),
        ("ebay|1", [_group("g1", "c1")], "success", None),
    ])
    output = tmp_path / "ebay.identify-1.json"
    source = prepare_review_files(tmp_path, artifact, output)
    identification.price_file(source, output, pricer=_priced)
    marker = tmp_path / "identifier.complete.json"
    if existing_marker:
        _complete(tmp_path, output)
    rows = json.loads(output.read_bytes())
    if mutation == "drop":
        rows.pop()
    elif mutation == "reverse":
        rows.reverse()
    else:
        rows.append(copy.deepcopy(rows[0]))
    output.write_text(json.dumps(rows))
    if existing_marker:
        # Simulate a marker stamped by the previous buggy completion path:
        # it consistently hashes the altered batch but never checked its keys.
        old_marker = json.loads(marker.read_bytes())
        old_marker["artifact_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        marker.write_text(json.dumps(old_marker))
        previous = marker.read_bytes()
    with pytest.raises(receipt.AuditError, match="coverage/order"):
        _complete(tmp_path, output)
    if existing_marker:
        assert marker.read_bytes() == previous
    else:
        assert not marker.exists()
