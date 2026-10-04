"""Exact source rights and fresh owning-SDK checks at publication boundaries."""
from __future__ import annotations

import re
import hashlib
import sqlite3
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .engine import AdapterFailure
from .media import MediaRenderer
from .safety import SafetyError, canonical, digest, number, strict_json, string, timestamp


CAMPAIGN_BASE = "https://contentrewards.com/api/campaign/campaigns/discover/"
DOCUMENT_PATH = re.compile(r"^/document/d/([A-Za-z0-9_-]+)/")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def missing(capability):
    raise AdapterFailure("permanent", "capability_missing: " + capability)


class LiveAdapter:
    def __init__(self, config, *, media=None, opener=urlopen, whop_factory=None, studio_factory=None):
        self.config = config
        self.media = media if media is not None else MediaRenderer(config)
        self.opener = opener
        self.whop_factory, self.studio_factory = whop_factory, studio_factory

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

    def _source_evidence(self, source, campaign):
        """Read and retain complete bounded campaign/brief and immutable rights."""
        from .rights import validate_policy
        policy = source.get("publication_policy")
        if policy is None:
            raise SafetyError("explicit_scoped_publication_policy_required")
        validate_policy(policy, source)
        references = {item.get("url") for item in campaign["referenceMaterials"] if isinstance(item, dict)}
        if campaign.get("id") != policy["campaign_id"] or policy["brief_url"] not in references:
            raise SafetyError("source_evidence_not_in_campaign")
        parsed = urlparse(policy["brief_url"])
        document_id = DOCUMENT_PATH.match(parsed.path).group(1)
        deadline = time.monotonic() + self.config["limits"]["work_timeout_seconds"]
        raw = self.media._run(["google", "docs", "read", document_id], deadline)
        document = strict_json(raw, self.config["limits"]["max_payload_bytes"])
        if not isinstance(document, dict) or document.get("documentId") != document_id or not isinstance(document.get("content"), str):
            raise SafetyError("source_document_contract_mismatch")
        if hashlib.sha256(document["content"].encode()).hexdigest() != policy["brief_content_sha256"]:
            raise SafetyError("source_brief_content_changed")
        evidence = {"campaign": campaign, "campaign_digest": digest(campaign), "brief": document,
            "brief_content_sha256": policy["brief_content_sha256"], "publication_policy": policy,
            "publication_policy_digest": digest(policy), "observed_at": now_iso()}
        strict_json(canonical(evidence), self.config["limits"]["max_payload_bytes"])
        return evidence

    def approved_sources(self, source, campaign):
        evidence = self._source_evidence(source, campaign)
        return {self.media._source({"source_id": source["id"], "media_url": evidence["publication_policy"]["source_url"]})}

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

    def _reward_actor(self):
        actor = self.config.get("rewards_account")
        if actor is None:
            missing("verified_whop_rewards_account")
        return actor

    def _job_source(self, job):
        source = next((source for source in self.config["sources"] if source["id"] == job.get("input", {}).get("source_id")), None)
        if source is None:
            raise SafetyError("publication_source_context_missing")
        if "publication_policy" not in source:
            raise SafetyError("explicit_scoped_publication_policy_required")
        return source

    def _participant_call(self, operation):
        actor = self._reward_actor()
        # This read precedes external SDK work and holds no transaction open.
        with sqlite3.connect(Path(self.config["database"]).as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            row = db.execute("SELECT until FROM circuits WHERE capability='provider:whop'").fetchone()
        if row is not None and row[0] > time.time():
            raise AdapterFailure("transient", "circuit_open: provider:whop", row[0] - time.time(), provider="whop")
        if self.whop_factory is None:
            from whop_cli.config import Config
            from whop_cli.client import WhopClient
            client = WhopClient(Config(profile=actor["profile"]))
        else:
            client = self.whop_factory()
        failure = None
        try:
            if any(not callable(getattr(client, method, None)) for method in
                    ("submission_readiness", "create_submission", "reconcile_submission")):
                missing("whop_participant_submission_sdk")
            return operation(client)
        except Exception as exc:
            category = getattr(exc, "category", None)
            code = getattr(exc, "code", None)
            if category in {"auth", "rate_limit", "transient", "upstream", "policy_changed", "not_ready", "invalid_request"} and isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", code):
                mapped = category if category in {"auth", "rate_limit", "transient"} else "permanent"
                diagnostics = getattr(exc, "diagnostics", None)
                if isinstance(diagnostics, dict) and diagnostics.get("available") is True:
                    from whop_cli.config import rewards_location
                    origin, route = rewards_location(client.config.rewards_url)
                    campaign_ids = {source["campaign"]["id"] for source in self.config["sources"]}
                    if diagnostics.get("origin") != origin or diagnostics.get("path") not in {route + "/campaigns/" + identifier for identifier in campaign_ids}:
                        raise SafetyError("whop_diagnostic_route_changed")
                failure = AdapterFailure(mapped, "whop:" + code, getattr(exc, "retry_after_seconds", None), provider="whop", code=code, status=getattr(exc, "status", None) or None, diagnostics=diagnostics)
                raise failure from exc
            failure = exc
            raise
        finally:
            try:
                client.close()
            except Exception as close_error:
                if failure is None:
                    raise AdapterFailure("transient", "whop_close_failed", provider="whop") from close_error
                # Preserve the authoritative provider failure and record cleanup
                # separately, rather than replacing Retry-After with close failure.
                failure.cleanup_issue = "whop_close_failed"
                failure.args = (str(failure) + "; cleanup: whop_close_failed",)

    def _whop_ready(self, source, expected_digest=None):
        actor = self._reward_actor()
        def read(client):
            ready = client.submission_readiness(source['campaign']['id'], expected_account_id=actor['account_id'],
                expected_tiktok_account_id=self.config['account']['account_id'], expected_requirements_digest=expected_digest)
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                raise SafetyError("whop_submission_not_ready")
            expected_actor = {field: actor[field] for field in ("account_id", "username", "profile")}
            if ready.get("actor") != expected_actor or ready.get("campaign_id") != source["campaign"]["id"]:
                raise SafetyError("whop_readiness_actor_campaign_changed")
            linked = ready.get("linked_account")
            if not isinstance(linked, dict) or linked.get("account_id") != self.config["account"]["account_id"] or linked.get("username") != self.config["account"]["handle"].removeprefix("@").casefold():
                raise SafetyError("whop_readiness_linked_account_changed")
            requirement = ready.get("requirements_digest")
            if not isinstance(requirement, str) or not re.fullmatch("[a-f0-9]{64}", requirement) or (expected_digest is not None and requirement != expected_digest):
                raise SafetyError("whop_readiness_requirements_changed")
            number(ready.get("funding_remaining_cents"), 1, integer=True)
            if not 0 <= time.time() - timestamp(ready.get("observed_at")) <= self.config["limits"]["work_timeout_seconds"]:
                raise SafetyError("whop_readiness_stale")
            return ready
        return self._participant_call(read)

    def _fresh_readiness(self, job, expected_digest=None):
        source = self._job_source(job)
        from .rights import current_render_policy
        current_render_policy(source["publication_policy"])
        if timestamp(source["campaign"]["expires_at"]) <= time.time():
            raise SafetyError("campaign_expired")
        campaign = self.campaign(source["campaign"]["id"])
        remaining = campaign["budgetCents"] - campaign["metrics"]["budgetSpentCents"]
        if campaign.get("status") != "active" or "tiktok" not in campaign["platforms"] or remaining <= 0:
            raise SafetyError("campaign_not_active_funded_for_tiktok")
        evidence = self._source_evidence(source, campaign)
        if self.media._source(job["input"]) != self.media._source({"source_id": source["id"], "media_url": evidence["publication_policy"]["source_url"]}):
            raise SafetyError("publication_source_no_longer_authorized")
        from .rights import required_overlays
        required_overlays(source["publication_policy"], job["proposal"])
        ready = self._whop_ready(source, expected_digest)
        return source, ready, evidence

    def _readiness_snapshot(self, source, ready, evidence):
        snapshot = {"kind": "whop_ready", "actor": ready["actor"], "linked_account": ready["linked_account"],
            "campaign_id": ready["campaign_id"], "requirements_digest": ready["requirements_digest"],
            "brief_content_sha256": source["publication_policy"]["brief_content_sha256"],
            "publication_policy_digest": digest(source["publication_policy"]), "observed_at": ready["observed_at"],
            "source_evidence": evidence, "readiness": ready}
        strict_json(canonical(snapshot), self.config["limits"]["max_payload_bytes"])
        return snapshot

    def verify_ready(self, job):
        self._reward_actor()
        source, ready, evidence = self._fresh_readiness(job)
        snapshot = self._readiness_snapshot(source, ready, evidence)
        return {"allowed": True, "publish_capable": True, "submission_capable": True, "source_reuse_verified": True,
            "remaining_budget_cents": ready["funding_remaining_cents"], "account_id": self.config["account"]["account_id"],
            "campaign_id": source["campaign"]["id"], "checked_at": now_iso(), "provenance": canonical(snapshot)}

    def _studio(self):
        from .studio_adapter import StudioPublicationAdapter
        return self.studio_factory() if self.studio_factory is not None else StudioPublicationAdapter(self.config)

    def _studio_policy(self, job, asset):
        source = self._job_source(job)
        self.media.render_receipt(job, job["proposal"], asset)
        account = self.config["account"]
        return {"schema_version": 1, "profile": account["profile"], "account_id": account["account_id"],
            "username": account["handle"].removeprefix("@").casefold(), "caption": job["proposal"]["caption"],
            "audience": "Everyone", "timing": "now", "disclosure": "branded_content", "music_rights_confirmed": True}

    def publish(self, job, asset, idempotency_key):
        self._reward_actor()
        source = self._job_source(job)
        readiness = job.get("readiness")
        if not isinstance(readiness, dict):
            raise SafetyError("persisted_publication_readiness_missing")
        previous = strict_json(readiness["provenance"], self.config["limits"]["max_payload_bytes"])
        if previous.get("campaign_id") != source["campaign"]["id"] or previous.get("brief_content_sha256") != source["publication_policy"]["brief_content_sha256"] or previous.get("publication_policy_digest") != digest(source["publication_policy"]):
            raise SafetyError("persisted_publication_readiness_policy_changed")
        policy = self._studio_policy(job, asset)
        def fresh_before_post(binding):
            fresh_source, ready, evidence = self._fresh_readiness(job, previous["requirements_digest"])
            self.media.render_receipt(job, job["proposal"], asset)
            snapshot = {**previous, "before_public_action": {**self._readiness_snapshot(fresh_source, ready, evidence), "studio_binding": binding}}
            maximum = self.config["limits"]["max_payload_bytes"]
            strict_json(canonical(snapshot), maximum)
            # External reads have completed. Retain the new evidence under the
            # original lease; the Studio guard checks control/reservation last.
            with sqlite3.connect(Path(self.config["database"]).as_uri() + "?mode=rw", uri=True, timeout=2) as db:
                changed = db.execute("UPDATE jobs SET readiness=? WHERE id=? AND status='running' AND stage='publish' AND lease_token=? AND lease_until>?",
                    (canonical({**readiness, "provenance": canonical(snapshot)}), job["id"], job.get("lease_token"), time.time())).rowcount
                if changed != 1:
                    raise SafetyError("readiness_worker_lease_changed")
        return self._studio().publish(job, asset, idempotency_key, policy, pre_public_check=fresh_before_post)

    def reconcile(self, job, idempotency_key):
        if self.config.get("rewards_account") is None or job.get("asset") is None:
            return {"state": "unknown", "provenance": "Original verified Studio operation is unavailable."}
        bridge = self._studio()
        policy = bridge.recorded_policy(job, job["asset"], idempotency_key)
        if policy is None:
            return {"state": "unknown", "provenance": "Original Studio policy and coordinator reservation do not agree."}
        return bridge.reconcile(job, job["asset"], idempotency_key, policy)

    def metrics(self, publication):
        missing("verified_tiktok_post_metrics")

    def submit_rewards(self, job, reward_ledger):
        from .whop_adapter import WhopSubmissionAdapter
        bridge = WhopSubmissionAdapter(self.config)
        return self._participant_call(lambda client: bridge.submit(client, job, reward_ledger))

    def reconcile_rewards(self, job, reward_ledger):
        from .whop_adapter import WhopSubmissionAdapter
        bridge = WhopSubmissionAdapter(self.config)
        return self._participant_call(lambda client: bridge.reconcile(client, job, reward_ledger))

    def sync_reward_revenue(self):
        """Advance one shared provider pass before inspecting a due batch."""
        def sync(client):
            if not callable(getattr(client, 'sync_submission_revenue', None)):
                missing('whop_individual_revenue_sdk')
            result = client.sync_submission_revenue()
            actor = self._reward_actor()
            if not isinstance(result, dict) or any(result.get('binding', {}).get(k) != actor[k] for k in ('account_id', 'profile')):
                raise SafetyError('revenue_sync_actor_changed')
            failure = result.get('failure')
            if failure is not None:
                category = failure.get('category')
                raise AdapterFailure(category if category in {'auth', 'rate_limit', 'transient'} else 'permanent',
                    'whop:' + str(failure.get('code')), failure.get('retry_after_seconds'),
                    provider='whop', code=failure.get('code'), status=failure.get('status') or None)
            return result
        return self._participant_call(sync)

    def reward_status(self, job, reward_ledger, refresh_payouts=True):
        from .revenue import normalize_revenue
        from .whop_adapter import WhopSubmissionAdapter
        self._reward_actor()
        bound = WhopSubmissionAdapter(self.config)._binding(job, reward_ledger)
        def read(client):
            if not callable(getattr(client, 'submission_revenue', None)):
                missing('whop_individual_revenue_sdk')
            result = client.submission_revenue(reward_ledger['submission']['submission_id'],
                reward_ledger['campaign_id'], refresh_payouts=refresh_payouts)
            return normalize_revenue(result, reward_ledger, self._reward_actor(),
                bound['experience'], self.config['limits']['max_payload_bytes'])
        return self._participant_call(read)

    def visual_execution_state(self, envelope):
        from .visual import native_execution_state
        return native_execution_state(self.config, envelope)


def create_adapter(config):
    return LiveAdapter(config)
