"""Studio SDK binding and the coordinator's immediate public-action authority.

TikTok owns its private operation journal. This module alone reads the clipping
coordinator database; no permit files or control mirrors are accepted.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import re
import secrets
import sqlite3
import time
import uuid

from .safety import SafetyError, canonical, digest, keys, number, strict_json

PRE_ACTION_STATES = {"preparing", "preparation_failed", "prepared"}


def publication_request_id(idempotency_key):
    if not isinstance(idempotency_key, str) or not re.fullmatch(r"[a-f0-9]{64}", idempotency_key):
        raise SafetyError("invalid_publication_idempotency_key")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "tiktok-clipping:publication:" + idempotency_key))


def studio_reservation_identity(binding):
    """Durable operation identity, registered while preparation is still private."""
    fields = ("request_id", "asset_sha256", "policy_digest", "actor", "draft_id")
    return {"kind": "studio", "schema_version": 1, **{field: binding[field] for field in fields}}


class StudioPublicActionGuard:
    """Match the original worker lease against fresh authoritative SQLite state."""
    def __init__(self, config, job, asset, idempotency_key, policy, prepared, journal_reader, *, clock=time.time):
        self.config, self.job, self.asset = config, job, asset
        self.key, self.policy, self.prepared = idempotency_key, policy, prepared
        self.journal_reader, self.clock = journal_reader, clock
        self.request_id = publication_request_id(idempotency_key)

    def __call__(self, binding):
        keys(binding, {"request_id", "asset_sha256", "policy_digest", "actor", "draft_id", "project_id"})
        account = self.config["account"]
        actor = {"account_id": account["account_id"], "username": account["handle"].removeprefix("@").casefold(), "profile": account["profile"]}
        if binding["request_id"] != self.request_id or binding["asset_sha256"] != self.asset["sha256"] or binding["policy_digest"] != digest(self.policy) or binding["actor"] != actor:
            raise SafetyError("studio_callback_operation_binding_changed")
        pending = self.journal_reader(self.request_id)
        for name in ("request_id", "asset_sha256", "policy_digest", "actor", "draft_id", "project_id"):
            if pending.get(name) != binding[name]:
                raise SafetyError("studio_callback_private_journal_binding_changed")
        if pending.get("state") != "dispatch_pending" or pending.get("public_action_dispatched") is not False:
            raise SafetyError("studio_callback_private_dispatch_boundary_changed")
        if pending.get("policy") != self.policy or pending.get("binding") != digest({"asset_sha256": self.asset["sha256"], "policy": self.policy}):
            raise SafetyError("studio_callback_private_policy_changed")
        if binding["draft_id"] != self.prepared["draft_id"] or pending.get("draft") != self.prepared["draft"]:
            raise SafetyError("studio_callback_owned_draft_changed")
        token = self.job.get("lease_token")
        if not isinstance(token, str) or not token:
            raise SafetyError("studio_callback_original_lease_missing")
        # All local journal work precedes the final fresh coordinator snapshot.
        # Existing-file mode cannot create a missing coordinator. Commit the
        # exact dispatch boundary before allowing the SDK to send anything.
        with sqlite3.connect(Path(self.config["database"]).as_uri() + "?mode=rw", uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM jobs WHERE id=?", (self.job["id"],)).fetchone()
            reservation = db.execute("SELECT * FROM publications WHERE job_id=?", (self.job["id"],)).fetchone()
            control = db.execute("SELECT value FROM settings WHERE key='control'").fetchone()
            if control is None or control[0] != "running":
                raise SafetyError("studio_callback_control_not_running")
            if current is None or current["kind"] != "clip" or current["status"] != "running" or current["stage"] != "publish":
                raise SafetyError("studio_callback_job_not_running_publication")
            if not isinstance(current["lease_token"], str) or not secrets.compare_digest(current["lease_token"], token) or number(current["lease_until"], 0) <= self.clock():
                raise SafetyError("studio_callback_lease_expired_or_reclaimed")
            if current["policy_digest"] != digest(self.config) or current["policy_digest"] != self.job["policy_digest"]:
                raise SafetyError("studio_callback_coordinator_policy_changed")
            maximum = self.config["limits"]["max_payload_bytes"]
            for field in ("input", "proposal"):
                measured = digest(strict_json(current[field], maximum))
                if measured != current[field + "_digest"] or measured != self.job[field + "_digest"]:
                    raise SafetyError("studio_callback_" + field + "_changed")
            if strict_json(current["asset"], maximum) != self.asset:
                raise SafetyError("studio_callback_asset_changed")
            if reservation is None or reservation["state"] != "uploading" or reservation["id"] != self.key or reservation["idempotency_key"] != self.key or reservation["account_id"] != actor["account_id"] or reservation["asset_digest"] != binding["asset_sha256"]:
                raise SafetyError("studio_callback_publication_reservation_changed")
            identity = studio_reservation_identity(binding)
            if reservation["data"] is None or strict_json(reservation["data"], maximum) != identity:
                raise SafetyError("studio_callback_reserved_request_changed")
            dispatch = {**identity, "project_id": binding["project_id"], "dispatch_authorized_at": self.clock()}
            changed = db.execute("UPDATE publications SET state='dispatch_pending',data=? WHERE job_id=? AND state='uploading' AND idempotency_key=?", (canonical(dispatch), self.job["id"], self.key)).rowcount
            if changed != 1:
                raise SafetyError("studio_callback_dispatch_reservation_changed")


class StudioPublicationAdapter:
    """Owning SDK bridge. Its explicit policy must come from verified rights.

    A journal miss, corrupt record, or missing feed item never proves absence.
    Accepted projects and uncertain dispatches are only reconciled.
    """
    def __init__(self, config, *, publisher_factory=None, clock=time.time):
        self.config, self.clock = config, clock
        if publisher_factory is None:
            from tiktok_cli.config import Config
            from tiktok_cli.studio_publishing import StudioPublisher
            publisher_factory = lambda: StudioPublisher(Config(profile=config["account"]["profile"]))
        self.publisher_factory = publisher_factory

    def _binding(self, asset, key, policy):
        from tiktok_cli.studio_publishing import validate_policy
        policy = validate_policy(policy)
        account = self.config["account"]
        actor = {"account_id": account["account_id"], "username": account["handle"].removeprefix("@").casefold(), "profile": account["profile"]}
        if any(policy[name] != value for name, value in actor.items()):
            raise SafetyError("studio_policy_actor_changed")
        return {"request_id": publication_request_id(key), "asset_sha256": asset["sha256"], "policy_digest": digest(policy), "actor": actor}

    def _matches(self, operation, binding, policy):
        return (isinstance(operation, dict) and all(operation.get(k) == v for k, v in binding.items())
                and operation.get("policy") == policy
                and operation.get("binding") == digest({"asset_sha256": binding["asset_sha256"], "policy": policy}))

    def _reserve(self, job, key, binding, draft_id=None):
        """Save request identity before private upload; never reset a dispatch."""
        with sqlite3.connect(Path(self.config["database"]).as_uri() + "?mode=rw", uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            row = db.execute("SELECT * FROM publications WHERE job_id=?", (job["id"],)).fetchone()
            if (current is None or current["status"] != "running" or current["stage"] != "publish"
                    or not secrets.compare_digest(current["lease_token"] or "", job.get("lease_token") or "")
                    or not job.get("lease_token") or current["lease_until"] <= self.clock()):
                raise SafetyError("studio_prepare_worker_lease_changed")
            if (row is None or row["state"] != "uploading" or row["idempotency_key"] != key
                    or row["id"] != key or row["asset_digest"] != binding["asset_sha256"]
                    or row["account_id"] != binding["actor"]["account_id"]):
                raise SafetyError("studio_prepare_reservation_changed")
            identity = studio_reservation_identity({**binding, "draft_id": draft_id})
            if row["data"] is not None:
                previous = strict_json(row["data"], self.config["limits"]["max_payload_bytes"])
                if any(previous.get(k) != identity[k] for k in identity if k != "draft_id"):
                    raise SafetyError("studio_prepare_reserved_request_changed")
            db.execute("UPDATE publications SET data=? WHERE job_id=?", (canonical(identity), job["id"]))

    def _receipt(self, operation):
        if operation.get("state") != "published_verified":
            raise SafetyError("studio_publication_not_verified")
        verified = operation["verification"]
        actor = operation["actor"]
        if (verified.get("id") != operation.get("item_id") or verified.get("url") != operation.get("url")
                or verified.get("account_id") != actor["account_id"] or verified.get("author") != actor["username"]
                or verified.get("profile") != actor["profile"] or verified.get("caption") != operation["policy"]["caption"]
                or verified.get("visibility") != 1):
            raise SafetyError("studio_verified_receipt_binding_changed")
        posted = verified.get("posted_at")
        number(posted, 1, integer=True)
        return {"publication_id": operation["item_id"], "publication_url": operation["url"],
                "account_id": operation["actor"]["account_id"], "handle": operation["actor"]["username"],
                "published_at": datetime.fromtimestamp(posted, timezone.utc).isoformat(),
                "provenance": canonical({"kind": "studio_verified", "request_id": operation["request_id"],
                    "post_project_id": operation.get("post_project_id"), "asset_sha256": operation["asset_sha256"],
                    "policy_digest": operation["policy_digest"], "readback": verified["provenance"]})}

    def _failure(self, sdk, binding, policy, exc):
        from .engine import AdapterFailure
        try:
            operation = sdk.status(binding["request_id"])
            pre_action = self._matches(operation, binding, policy) and operation.get("state") in PRE_ACTION_STATES and operation.get("public_action_dispatched") is False
        except Exception:
            pre_action = False
        return AdapterFailure("transient" if pre_action else "ambiguous", "studio_publish: " + type(exc).__name__)

    def _close(self, sdk, binding, policy, verified_receipt=None):
        try:
            sdk.close()
        except Exception as exc:
            if verified_receipt is not None:
                # Remote publication is already exact and verified. Preserve
                # this separate recoverable local issue in durable provenance.
                provenance = strict_json(verified_receipt["provenance"])
                provenance["cleanup_issue"] = {"kind": "studio_browser_close_failed", "error_type": type(exc).__name__, "recoverable": True}
                verified_receipt["provenance"] = canonical(provenance)
                return
            raise self._failure(sdk, binding, policy, exc) from exc

    def publish(self, job, asset, key, policy):
        binding = self._binding(asset, key, policy)
        sdk = self.publisher_factory()
        try:
            try:
                existing = sdk.status(binding["request_id"])
            except Exception:
                existing = None
            if existing is not None and self._matches(existing, binding, policy) and existing.get("state") not in PRE_ACTION_STATES:
                # Existing accepted/uncertain record never re-enters prepare.
                result = sdk.reconcile(binding["request_id"])
                if not self._matches(result, binding, policy):
                    raise SafetyError("studio_reconciliation_binding_changed")
                return self._receipt(result)
            self._reserve(job, key, binding)
            prepared = sdk.prepare(asset["path"], policy, binding["request_id"])
            if not self._matches(prepared, binding, policy) or prepared.get("state") != "prepared" or prepared.get("public_action_dispatched") is not False:
                raise SafetyError("studio_prepare_operation_changed")
            self._reserve(job, key, binding, prepared["draft_id"])
            guard = StudioPublicActionGuard(self.config, job, asset, key, policy, prepared, sdk.status, clock=self.clock)
            result = sdk.publish(binding["request_id"], before_public_action=guard)
            if not self._matches(result, binding, policy):
                raise SafetyError("studio_publication_operation_changed")
            return self._receipt(result)
        except Exception as exc:
            # Trust exact persisted pre-action proof, never an exception label.
            raise self._failure(sdk, binding, policy, exc) from exc
        finally:
            self._close(sdk, binding, policy)

    def reconcile(self, job, asset, key, policy):
        binding = self._binding(asset, key, policy)
        sdk = self.publisher_factory()
        verified_receipt = None
        try:
            try:
                operation = sdk.status(binding["request_id"])
            except Exception:
                return {"state": "unknown", "provenance": "Exact Studio journal unavailable; no absence proof."}
            if not self._matches(operation, binding, policy):
                return {"state": "unknown", "provenance": "Exact Studio operation binding changed; preserve reservation."}
            if operation.get("state") in PRE_ACTION_STATES and operation.get("public_action_dispatched") is False:
                return {"state": "absent", "authoritative": True, "provenance": canonical({"kind": "studio_pre_action_journal", **binding, "state": operation["state"]})}
            result = sdk.reconcile(binding["request_id"])
            if not self._matches(result, binding, policy):
                raise SafetyError("studio_reconciliation_binding_changed")
            if result.get("state") == "published_verified":
                verified_receipt = self._receipt(result)
                return {"state": "published", "publication": verified_receipt}
            return {"state": "unknown", "provenance": canonical({"kind": "studio_reconcile_only", **binding, "state": result.get("state"), "post_project_id": result.get("post_project_id")})}
        finally:
            self._close(sdk, binding, policy, verified_receipt)
