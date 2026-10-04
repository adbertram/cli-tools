"""Reject wrong account data before accepting any verified publication."""

import pytest

from conftest import claim, payload
from tiktok_clipping_cli.safety import SafetyError, validate_config


@pytest.mark.parametrize("handle", ["ata_clipper", "@ata_clipper", "@ATA_CLIPPER"])
def test_verified_target_accepts_explicit_handle_forms(config, handle):
    config["account"]["handle"] = handle
    assert validate_config(config) is config


@pytest.mark.parametrize("account_id", ["7692213003349443598", "test-account", "", 7692213003349443597])
def test_target_handle_cannot_authorize_other_account_id(config, account_id):
    config["account"]["account_id"] = account_id
    with pytest.raises(SafetyError):
        validate_config(config)


@pytest.mark.parametrize("profile", ["default", "test-only", "itstories", ""])
def test_target_identity_requires_explicit_clipper_profile(config, profile):
    config["account"]["profile"] = profile
    with pytest.raises(SafetyError):
        validate_config(config)


@pytest.mark.parametrize("field", ["handle", "account_id", "profile", "verified_at", "provenance"])
def test_target_identity_does_not_fill_missing_verification(config, field):
    del config["account"][field]
    with pytest.raises(SafetyError, match="schema_keys"):
        validate_config(config)


@pytest.mark.parametrize("field,value", [("verified_at", "not-a-timestamp"), ("provenance", "")])
def test_target_identity_requires_verification_evidence(config, field, value):
    config["account"][field] = value
    with pytest.raises(SafetyError):
        validate_config(config)


def test_wrong_readiness_account_id_blocks_render_and_upload(engine, adapter, clock, monkeypatch):
    original = adapter.verify_ready
    monkeypatch.setattr(adapter, "verify_ready", lambda job: original(job) | {"account_id": "7692213003349443598"})
    envelope = claim(engine, clock)
    result = engine.apply(payload(envelope))
    assert result["state"] == "failed"
    assert result["error"] == "publication_preflight_identity_mismatch"
    assert adapter.calls == ["verify_ready"]
    assert adapter.uploads == []
    assert engine.status()["budgets"][0]["posts"] == 0


@pytest.mark.parametrize("patch,error", [
    ({"handle": "@itstories"}, "publication_account_mismatch"),
    ({"account_id": "7692213003349443598"}, "publication_account_mismatch"),
    ({"handle": "@@ata_clipper"}, "publication_account_mismatch"),
    ({"publication_url": "https://www.tiktok.com/@itstories/video/123"}, "publication_url_account_mismatch"),
    ({"publication_url": "https://www.tiktok.com/@ata_clipping/video/123"}, "publication_url_account_mismatch"),
])
def test_wrong_publication_identity_never_authorizes_rewards(engine, adapter, clock, monkeypatch, patch, error):
    original = adapter.receipt
    monkeypatch.setattr(adapter, "receipt", lambda job: original(job) | patch)
    envelope = claim(engine, clock)
    result = engine.apply(payload(envelope))
    assert result["state"] == "ambiguous"
    assert result["error"] == error
    assert "submit_rewards" not in adapter.calls
    with engine.transaction() as db:
        assert db.execute("SELECT count(*) FROM rewards").fetchone()[0] == 0
        assert db.execute("SELECT state FROM publications").fetchone()[0] == "ambiguous"


def test_reconciliation_cannot_accept_wrong_id_with_matching_handle(engine, adapter, clock, monkeypatch):
    original = adapter.receipt
    monkeypatch.setattr(adapter, "receipt", lambda job: original(job) | {"account_id": "7692213003349443598"})
    envelope = claim(engine, clock)
    assert engine.apply(payload(envelope))["state"] == "ambiguous"
    with pytest.raises(SafetyError, match="publication_account_mismatch"):
        engine.reconcile(envelope["job_id"])
    assert "submit_rewards" not in adapter.calls
    assert len(adapter.uploads) == 1
