"""Live adapter boundaries; all media/auth consumers remain test doubles."""
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from tiktok_clipping_cli.engine import AdapterFailure
from tiktok_clipping_cli.live import CAMPAIGN_BASE, LiveAdapter
from tiktok_clipping_cli.media import MediaRenderer
from tiktok_clipping_cli.safety import SafetyError


CAMPAIGN_ID = "188c3e39-7850-4896-94df-e7a5be0cfec3"
DOCUMENT_ID = "1QwGNf5KW_ACPqlkLpVvraUXlM8-lJz170yz2YOuR-SE"
DOCUMENT_URL = "https://docs.google.com/document/d/" + DOCUMENT_ID + "/edit?usp=sharing"
VIDEO_URL = "https://youtu.be/8JMrfSFQdpo?si=source"


class Media:
    _source = MediaRenderer._source

    def __init__(self, config):
        self.config = config
        self.commands = []
        self.prepared = []

    def _run(self, command, deadline):
        self.commands.append(command)
        return json.dumps({"documentId": DOCUMENT_ID, "content": "Approved video: " + VIDEO_URL}).encode()

    def prepare(self, record):
        self.prepared.append(record)
        return {"duration_seconds": 60, "transcript": "Measured speech.",
            "transcript_segments": [{"start_seconds": 0, "end_seconds": 60, "text": "Measured speech."}],
            "provenance": "TEST timed media receipt"}

    def render(self, job, proposal):
        return {"test_render": job}

    def quality(self, job, proposal, asset):
        return {"test_quality": asset}


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def geturl(self):
        return CAMPAIGN_BASE + CAMPAIGN_ID

    def read(self, maximum):
        return self.payload[:maximum]


@pytest.fixture
def live(config):
    source = config["sources"][0]
    source.update(feed=VIDEO_URL, allowed_hosts=["youtu.be", "www.youtube.com"], reuse_evidence=DOCUMENT_URL)
    source["campaign"].update(id=CAMPAIGN_ID, expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    campaign = {"id": CAMPAIGN_ID, "status": "active", "platforms": ["tiktok"],
        "referenceMaterials": [{"url": DOCUMENT_URL}], "budgetCents": 8500000,
        "metrics": {"budgetSpentCents": 1960300}}
    media = Media(config)
    adapter = LiveAdapter(config, media=media, opener=lambda request, timeout: Response({"success": True, "data": campaign}))
    return adapter, source, campaign, media


def test_observed_campaign_sources_require_measured_transcript(live):
    adapter, source, _, media = live
    records = adapter.discover(source)
    assert records[0]["media_id"] == "8JMrfSFQdpo"
    assert records[0]["transcript"] == "Measured speech."
    assert records[0]["transcript_segments"] == [{"start_seconds": 0, "end_seconds": 60, "text": "Measured speech."}]
    assert media.prepared == [{"source_id": source["id"], "media_url": VIDEO_URL}]
    assert media.commands == [["google", "docs", "read", DOCUMENT_ID]]


def test_unlisted_video_is_rejected_before_media_download(live):
    adapter, source, _, media = live
    source["feed"] = "https://www.youtube.com/watch?v=TqAgejIX7uU"
    with pytest.raises(SafetyError, match="selected_video_not_in_approved_sources"):
        adapter.discover(source)
    assert media.prepared == []


def test_unrelated_reuse_document_cannot_authorize_source(live):
    adapter, source, campaign, media = live
    campaign["referenceMaterials"] = []
    with pytest.raises(SafetyError, match="source_evidence_not_in_campaign"):
        adapter.discover(source)
    assert media.commands == []


@pytest.mark.parametrize("field,value", [("status", "paused"), ("platforms", ["youtube"])])
def test_inactive_or_unsupported_campaign_never_downloads(live, field, value):
    adapter, source, campaign, media = live
    campaign[field] = value
    with pytest.raises(SafetyError, match="campaign_not_active_funded_for_tiktok"):
        adapter.discover(source)
    assert media.prepared == []


def test_exhausted_campaign_does_not_download(live):
    adapter, source, campaign, media = live
    campaign["metrics"]["budgetSpentCents"] = campaign["budgetCents"]
    with pytest.raises(SafetyError, match="campaign_not_active_funded_for_tiktok"):
        adapter.discover(source)
    assert media.prepared == []


def test_wrong_campaign_response_fails_explicitly(live):
    adapter, _, campaign, _ = live
    campaign["id"] = "ecbd7fec-6f39-4081-aa18-1756f0ae73e9"
    with pytest.raises(SafetyError, match="campaign_response_contract_mismatch"):
        adapter.campaign(CAMPAIGN_ID)


def test_missing_budget_is_not_zero_default(live):
    adapter, _, campaign, _ = live
    del campaign["metrics"]["budgetSpentCents"]
    with pytest.raises(SafetyError):
        adapter.campaign(CAMPAIGN_ID)


def test_rate_limit_retains_category_without_invented_cooldown(live):
    adapter, _, _, _ = live
    def reject(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
    adapter.opener = reject
    with pytest.raises(AdapterFailure) as captured:
        adapter.campaign(CAMPAIGN_ID)
    assert captured.value.category == "rate_limit"
    assert captured.value.retry_after is None


@pytest.mark.parametrize("method,args", [
    ("verify_ready", ({},)), ("publish", ({}, {}, "key")),
    ("submit_rewards", ({}, {})), ("reward_status", ({}, {})), ("metrics", ({},)),
])
def test_missing_participant_capabilities_never_return_fabricated_receipts(live, method, args):
    adapter, _, _, media = live
    with pytest.raises(AdapterFailure, match="capability_missing:") as captured:
        getattr(adapter, method)(*args)
    assert captured.value.category == "permanent"
    assert media.prepared == []


def test_unverified_reconciliation_never_claims_absence(live):
    adapter, _, _, _ = live
    result = adapter.reconcile({}, "key")
    assert result["state"] == "unknown"
    assert "authoritative" not in result


def test_media_delegation_preserves_receipts(live):
    adapter, _, _, _ = live
    assert adapter.render({"id": "job"}, {}) == {"test_render": {"id": "job"}}
    assert adapter.quality({}, {}, {"path": "asset"}) == {"test_quality": {"path": "asset"}}
