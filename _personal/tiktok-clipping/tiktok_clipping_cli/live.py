"""Observed public campaign reads and media preparation, with closed live gates.

Public campaign data cannot prove participant membership, account identity,
submission eligibility, or publishing access. Those capabilities remain absent.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .engine import AdapterFailure
from .media import MediaRenderer
from .safety import SafetyError, number, strict_json, timestamp


CAMPAIGN_BASE = "https://contentrewards.com/api/campaign/campaigns/discover/"
DOCUMENT_PATH = re.compile(r"^/document/d/([A-Za-z0-9_-]+)/")
URLS = re.compile(r"https://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s<>\"\u000b]+")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def missing(capability):
    raise AdapterFailure("permanent", "capability_missing: " + capability)


class LiveAdapter:
    def __init__(self, config, *, media=None, opener=urlopen):
        self.config = config
        self.media = media if media is not None else MediaRenderer(config)
        self.opener = opener

    def campaign(self, campaign_id):
        """Read the exact JSON route observed in public campaign previews."""
        try:
            identifier = str(uuid.UUID(campaign_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SafetyError("campaign_uuid_required") from exc
        request = Request(CAMPAIGN_BASE + identifier + "?", headers={"Accept": "application/json"})
        maximum = self.config["limits"]["max_payload_bytes"]
        try:
            with self.opener(request, timeout=min(30, self.config["limits"]["work_timeout_seconds"])) as response:
                if urlparse(response.geturl()).hostname != "contentrewards.com":
                    raise SafetyError("campaign_response_host_changed")
                payload = strict_json(response.read(maximum + 1), maximum)
        except HTTPError as exc:
            category = "rate_limit" if exc.code == 429 else "transient" if exc.code >= 500 else "permanent"
            raise AdapterFailure(category, "campaign_http_status: " + str(exc.code)) from exc
        except (URLError, TimeoutError) as exc:
            raise AdapterFailure("transient", "campaign_read_unavailable") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
            raise SafetyError("campaign_response_contract_mismatch")
        data = payload["data"]
        if data.get("id") != identifier or not isinstance(data.get("platforms"), list) or not isinstance(data.get("referenceMaterials"), list):
            raise SafetyError("campaign_response_contract_mismatch")
        number(data.get("budgetCents"), 0, integer=True)
        if not isinstance(data.get("metrics"), dict):
            raise SafetyError("campaign_metrics_required")
        number(data["metrics"].get("budgetSpentCents"), 0, integer=True)
        return data

    def approved_sources(self, source, campaign):
        """Read a campaign-supplied Google Doc, never unrelated internet links."""
        evidence = source["reuse_evidence"]
        references = {item.get("url") for item in campaign["referenceMaterials"] if isinstance(item, dict)}
        if evidence not in references:
            raise SafetyError("source_evidence_not_in_campaign")
        parsed = urlparse(evidence)
        match = DOCUMENT_PATH.match(parsed.path)
        if parsed.scheme != "https" or parsed.hostname != "docs.google.com" or parsed.username or parsed.password or not match:
            missing("approved_source_document_reader")
        deadline = time.monotonic() + self.config["limits"]["work_timeout_seconds"]
        raw = self.media._run(["google", "docs", "read", match.group(1)], deadline)
        document = strict_json(raw, self.config["limits"]["max_payload_bytes"])
        if not isinstance(document, dict) or document.get("documentId") != match.group(1) or not isinstance(document.get("content"), str):
            raise SafetyError("source_document_contract_mismatch")
        approved = set()
        for url in URLS.findall(document["content"]):
            try:
                approved.add(self.media._source({"source_id": source["id"], "media_url": url}))
            except SafetyError:
                # Channel/playlist links and hosts outside this source policy
                # are not supported downloadable source records.
                continue
        if not approved:
            raise SafetyError("approved_single_video_sources_missing")
        return sorted(approved)

    def discover(self, source):
        """Prepare one explicitly selected video after live source approval."""
        if source not in self.config["sources"]:
            raise SafetyError("source_not_allowlisted")
        if timestamp(source["campaign"]["expires_at"]) <= time.time():
            raise SafetyError("campaign_expired")
        campaign = self.campaign(source["campaign"]["id"])
        remaining = campaign["budgetCents"] - campaign["metrics"]["budgetSpentCents"]
        if campaign.get("status") != "active" or "tiktok" not in campaign["platforms"] or remaining <= 0:
            raise SafetyError("campaign_not_active_funded_for_tiktok")
        record = {"source_id": source["id"], "media_url": source["feed"]}
        canonical = self.media._source(record)
        if canonical not in self.approved_sources(source, campaign):
            raise SafetyError("selected_video_not_in_approved_sources")
        measured = self.media.prepare(record)
        return [{**record, **measured, "media_id": canonical.rsplit("=", 1)[1],
            "observed_at": now_iso(), "categories": source["campaign"]["categories"],
            "provenance": measured["provenance"] + "; campaign source list: " + source["reuse_evidence"]}]

    def render(self, job, proposal):
        return self.media.render(job, proposal)

    def quality(self, job, proposal, asset):
        return self.media.quality(job, proposal, asset)

    def verify_ready(self, job):
        missing("verified_tiktok_public_publishing_and_whop_participant_submission")

    def publish(self, job, asset, idempotency_key):
        missing("verified_tiktok_public_publishing")

    def reconcile(self, job, idempotency_key):
        return {"state": "unknown", "provenance": "No verified TikTok publication reconciliation capability is configured."}

    def metrics(self, publication):
        missing("verified_tiktok_post_metrics")

    def submit_rewards(self, job, reward_ledger):
        missing("verified_whop_participant_submission")

    def reward_status(self, job, reward_ledger):
        missing("verified_whop_participant_reward_status")

    def visual_execution_state(self, envelope):
        from .visual import native_execution_state
        return native_execution_state(self.config, envelope)


def create_adapter(config):
    return LiveAdapter(config)
