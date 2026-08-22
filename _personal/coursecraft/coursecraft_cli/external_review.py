"""Contract-driven authority for CourseCraft external-review transitions."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping

from .coursecraft_project import coursecraft_project_root
from .objective_override import ObjectiveOverrideError, current_artifact_version


PIPELINE_FILE = "course-pipeline.json"
MUTATION_HOST_ENV = "COURSECRAFT_LIFECYCLE_MUTATION_HOST"
LOCK_DIR_ENV = "COURSECRAFT_LIFECYCLE_LOCK_DIR"
LOCK_TIMEOUT_SECONDS = 10.0
_RECORD_ID_RE = re.compile(r"^rec[A-Za-z0-9]+$")
_BASE_ID_RE = re.compile(r"^app[A-Za-z0-9]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_SECONDS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LEGACY_EVIDENCE_KEYS = {
    "kind",
    "subject",
    "baseline_sha256",
    "input_fingerprint",
}
_ROLLBACK_KIND = "artifact_lifecycle_rollback_plan"
_ROLLBACK_ENVELOPE_KEYS = {
    "content_sha256",
    "kind",
    "schema_version",
    "created_at",
    "plan_sha256",
    "baseline_sha256",
    "forward_pipeline_sha256",
    "pipeline_sha256",
    "base_id",
    "record_reverse",
    "formula_reverse",
    "schema_reverse",
    "apply_supported",
}
_ROLLBACK_ENTRY_KEYS = {
    "operation_sha256",
    "operation_id",
    "kind",
    "process",
    "table",
    "record_id",
    "owned_fields",
    "rollback_cli",
    "expected_after_fields",
    "restore_before_fields",
    "plan_sha256",
    "baseline_sha256",
    "pipeline_sha256",
    "base_id",
}


class ExternalReviewError(ValueError):
    """A lifecycle transition failed a contract or integrity gate."""


def _pipeline_document() -> Dict[str, Any]:
    path = coursecraft_project_root() / PIPELINE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalReviewError(
            f"Cannot read lifecycle contract {path}: {exc}"
        ) from None
    if not isinstance(data, dict):
        raise ExternalReviewError(f"{path} must contain a JSON object.")
    return data


def _contract() -> Dict[str, Any]:
    path = coursecraft_project_root() / PIPELINE_FILE
    data = _pipeline_document()
    lifecycle = data.get("artifact_lifecycle")
    if not isinstance(lifecycle, dict):
        raise ExternalReviewError(f"{path} has no artifact_lifecycle object.")
    return lifecycle


def _instance_contract(instance: str) -> Dict[str, Any]:
    instances = _contract().get("instances")
    value = instances.get(instance) if isinstance(instances, dict) else None
    if not isinstance(value, dict):
        raise ExternalReviewError(f"Unknown lifecycle instance {instance!r}.")
    return value


def _protocol_contract(instance: Mapping[str, Any]) -> Dict[str, Any]:
    protocols = _contract().get("protocols")
    name = instance.get("protocol")
    value = protocols.get(name) if isinstance(protocols, dict) else None
    if not isinstance(value, dict):
        raise ExternalReviewError(f"Unknown lifecycle protocol {name!r}.")
    return value


def _legacy_evidence_policy() -> Dict[str, Any]:
    protocols = _contract().get("protocols")
    protocol = (
        protocols.get("pluralsight_review") if isinstance(protocols, dict) else None
    )
    if not isinstance(protocol, dict):
        raise ExternalReviewError(
            "Lifecycle contract has no pluralsight_review protocol."
        )
    union = protocol.get("submitted_evidence_union")
    expected = {
        "canonical": {
            "version_entry_keys": ["slug", "v", "sha256"],
            "module_video_manifest_item_keys": ["clip_id", "v", "sha256"],
        },
        "legacy_migration": {
            "kind": "legacy_airtable_baseline",
            "keys": ["kind", "subject", "baseline_sha256", "input_fingerprint"],
            "subjects_by_instance": {
                "course_outline": "course.outline_draft",
                "slide_deck": "module.powerpoint_deck",
                "module_video": "clip.recording",
            },
            "allowed_states": ["Submitted", "Changes Requested", "Approved"],
            "entry_path": "sealed_baseline_bound_migration_resolution",
            "retain_actions": ["request_changes", "reviewed_input_changed"],
            "replace_actions": ["submit"],
            "reject_actions": ["approve", "accept_approved_revision"],
            "reject_message": "resubmit current registered evidence first",
        },
    }
    if union != expected:
        raise ExternalReviewError(
            "Lifecycle submitted evidence union does not match the fail-closed contract."
        )
    return union["legacy_migration"]


def _validate_legacy_evidence(
    value: Any,
    instance: str,
    *,
    label: str,
    baseline_sha256: str | None = None,
    input_fingerprint: str | None = None,
) -> None:
    policy = _legacy_evidence_policy()
    subjects = policy["subjects_by_instance"]
    if instance not in subjects:
        raise ExternalReviewError(f"{label} has no legacy review subject.")
    if not isinstance(value, dict) or set(value) != _LEGACY_EVIDENCE_KEYS:
        raise ExternalReviewError(
            f"{label} legacy evidence must contain exactly "
            f"{sorted(_LEGACY_EVIDENCE_KEYS)}."
        )
    if value.get("kind") != policy["kind"]:
        raise ExternalReviewError(
            f"{label} legacy evidence kind must be {policy['kind']}."
        )
    if value.get("subject") != subjects[instance]:
        raise ExternalReviewError(
            f"{label} legacy evidence subject does not match {instance}."
        )
    for key in ["baseline_sha256", "input_fingerprint"]:
        digest = value.get(key)
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise ExternalReviewError(
                f"{label} legacy evidence {key} must be 64 lowercase hex characters."
            )
    if baseline_sha256 is not None and value["baseline_sha256"] != baseline_sha256:
        raise ExternalReviewError(
            f"{label} legacy evidence does not match the sealed baseline digest."
        )
    if input_fingerprint is not None and value["input_fingerprint"] != input_fingerprint:
        raise ExternalReviewError(
            f"{label} legacy evidence does not match the entry baseline fingerprint."
        )


def _persisted_evidence_kind(instance: str, raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ExternalReviewError(f"{instance} submitted revision evidence is blank.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ExternalReviewError(
            f"{instance} submitted revision evidence is malformed JSON: {error}."
        ) from None
    if isinstance(value, dict) and bool(_LEGACY_EVIDENCE_KEYS & set(value)):
        _validate_legacy_evidence(value, instance, label=instance)
        return "legacy"
    subject = _instance_contract(instance).get("review_subject", {})
    if subject.get("evidence_kind") == "version_entry":
        valid = (
            isinstance(value, dict)
            and set(value) == {"slug", "v", "sha256"}
            and value.get("slug") == subject.get("slug")
            and isinstance(value.get("v"), int)
            and not isinstance(value.get("v"), bool)
            and value["v"] > 0
            and isinstance(value.get("sha256"), str)
            and _SHA256_RE.fullmatch(value["sha256"]) is not None
        )
    elif subject.get("evidence_kind") == "sorted_linked_record_manifest":
        valid = isinstance(value, list) and bool(value)
        clip_ids: List[str] = []
        if valid:
            for item in value:
                if not (
                    isinstance(item, dict)
                    and set(item) == {"clip_id", "v", "sha256"}
                    and isinstance(item.get("clip_id"), str)
                    and isinstance(item.get("v"), int)
                    and not isinstance(item.get("v"), bool)
                    and item["v"] > 0
                    and isinstance(item.get("sha256"), str)
                    and _SHA256_RE.fullmatch(item["sha256"]) is not None
                ):
                    valid = False
                    break
                clip_ids.append(item["clip_id"])
            valid = valid and clip_ids == sorted(set(clip_ids))
    else:
        raise ExternalReviewError(
            f"Lifecycle instance {instance!r} has an unknown submitted evidence kind."
        )
    if not valid:
        raise ExternalReviewError(
            f"{instance} submitted revision evidence is not canonical or typed legacy evidence."
        )
    return "canonical"


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _pipeline_fingerprint(value: Any) -> str:
    """Match the migration controller's stable, indented pipeline digest."""
    serialized = json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def version_evidence(slug: str, version: Mapping[str, Any]) -> str:
    """Serialize one exact version/hash as stable submitted evidence."""
    return _stable_json(
        {"sha256": version.get("sha256"), "slug": slug, "v": version.get("v")}
    )


def _registered_file_version(fields: Mapping[str, Any], slug: str) -> Dict[str, Any]:
    """Read one exact machine-registered file revision from Version Control."""
    raw = fields.get("Version Control") or "{}"
    try:
        ledger = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExternalReviewError(f"Version Control is not valid JSON: {exc}.") from None
    entry = ledger.get(slug) if isinstance(ledger, dict) else None
    if not isinstance(entry, dict):
        raise ExternalReviewError(f"Version Control has no {slug!r} entry.")
    version = entry.get("v")
    digest = entry.get("sha256")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ExternalReviewError(f"{slug} version must be a positive integer.")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ExternalReviewError(f"{slug} sha256 must be 64 lowercase hex characters.")
    return {"v": version, "sha256": digest}


def module_video_evidence(clips: List[Mapping[str, Any]]) -> str:
    """Build the contract's sorted linked-Clip recording manifest."""
    manifest = []
    for clip in clips:
        clip_id = clip.get("id")
        fields = clip.get("fields")
        if not isinstance(clip_id, str) or not isinstance(fields, dict):
            raise ExternalReviewError("Module video evidence contains an invalid Clip record.")
        version = _registered_file_version(fields, "clip.recording")
        manifest.append(
            {"clip_id": clip_id, "sha256": version["sha256"], "v": version["v"]}
        )
    manifest.sort(key=lambda item: item["clip_id"])
    return _stable_json(manifest)


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExternalReviewError(f"Readiness field {field!r} is not numeric: {value!r}.")
    return float(value)


def _require_current_pass(review: Any, slug: str, evidence: str, field: str) -> None:
    if not isinstance(review, str) or not review:
        raise ExternalReviewError(f"Readiness field {field!r} is blank.")
    lines = review.splitlines()
    if not lines or lines[0] != "PASS":
        raise ExternalReviewError(f"Readiness field {field!r} must begin with PASS.")
    parsed = json.loads(evidence)
    trailer = f"Reviewed-Version: {slug}@v{parsed['v']} sha256:{parsed['sha256']}"
    reviewed = [line for line in lines if line.startswith("Reviewed-Version:")]
    if reviewed != [trailer]:
        raise ExternalReviewError(
            f"Readiness field {field!r} must contain exactly {trailer!r}."
        )


def _require_readiness(
    instance_name: str,
    instance: Mapping[str, Any],
    record: Mapping[str, Any],
) -> None:
    fields = record["fields"]
    evidence = record["current_revision"]
    linked = record.get("linked_records") or []
    for gate in instance.get("readiness_gates", []):
        kind = gate.get("kind")
        if gate.get("applies_from") and fields.get(instance["state_field"]) not in gate["applies_from"]:
            continue
        if kind in {"version_entry_current", "linked_version_entries_current"}:
            continue  # Evidence construction already proved the exact current ledger entries.
        if kind == "ai_review_current_pass":
            _require_current_pass(fields.get(gate["field"]), gate["slug"], evidence, gate["field"])
        elif kind == "field_truthy":
            if not _truthy(fields.get(gate["field"])):
                raise ExternalReviewError(f"Readiness field {gate['field']!r} is not true.")
        elif kind == "field_present":
            if fields.get(gate["field"]) in (None, "", []):
                raise ExternalReviewError(f"Readiness field {gate['field']!r} is blank.")
        elif kind == "positive_count":
            if _number(fields.get(gate["field"]), gate["field"]) <= 0:
                raise ExternalReviewError(f"Readiness field {gate['field']!r} must be positive.")
        elif kind == "zero_count":
            if _number(fields.get(gate["field"]), gate["field"]) != 0:
                raise ExternalReviewError(f"Readiness field {gate['field']!r} must be zero.")
        elif kind == "counts_equal":
            left = _number(fields.get(gate["left"]), gate["left"])
            right = _number(fields.get(gate["right"]), gate["right"])
            if left != right:
                raise ExternalReviewError(
                    f"Readiness counts do not match: {gate['left']}={left:g}, "
                    f"{gate['right']}={right:g}."
                )
        elif kind == "linked_field_truthy":
            if not linked:
                raise ExternalReviewError(f"{instance_name} has no linked records.")
            bad = [item.get("id") for item in linked if not _truthy(item["fields"].get(gate["field"]))]
            if bad:
                raise ExternalReviewError(
                    f"Linked readiness field {gate['field']!r} is not true for: "
                    + ", ".join(str(item) for item in bad)
                    + "."
                )
        else:
            raise ExternalReviewError(
                f"Lifecycle instance {instance_name!r} uses unknown readiness gate {kind!r}."
            )


def plan_transition(
    instance: str,
    action: str,
    actor: str,
    record: Mapping[str, Any],
    *,
    returned_revision: str | None = None,
    approval_evidence: str | None = None,
    returned_candidate_validated: bool = False,
) -> Dict[str, Any]:
    """Plan one legal contract transition without performing a write."""
    instance_contract = _instance_contract(instance)
    protocol = _protocol_contract(instance_contract)
    fields = record.get("fields")
    if not isinstance(fields, dict):
        raise ExternalReviewError("Transition record has no fields object.")
    if fields.get("Platform") != "Pluralsight":
        raise ExternalReviewError(
            f"{instance} is Pluralsight-only; Platform={fields.get('Platform')!r}."
        )

    action_contract = instance_contract.get("actions", {}).get(action)
    if not isinstance(action_contract, dict):
        raise ExternalReviewError(f"Action {action!r} is not defined for {instance!r}.")
    if action_contract.get("actor") != actor:
        raise ExternalReviewError(
            f"Action {action!r} for {instance!r} belongs to actor "
            f"{action_contract.get('actor')!r}, not {actor!r}."
        )

    state_field = instance_contract.get("state_field")
    revision_field = instance_contract.get("submitted_revision_field")
    current_state = fields.get(state_field)
    transitions = [
        edge for edge in protocol.get("transitions", [])
        if edge.get("action") == action and current_state in edge.get("from", [])
    ]
    if len(transitions) != 1:
        raise ExternalReviewError(
            f"Illegal {instance}.{action} transition from {current_state!r}."
        )
    edge = transitions[0]
    current_revision = record.get("current_revision")
    evidence_kind = None
    evidence_required_states = protocol.get(
        "submitted_evidence_required_in_states", []
    )
    persisted_evidence = fields.get(revision_field)
    if current_state in evidence_required_states:
        evidence_kind = _persisted_evidence_kind(
            instance, persisted_evidence
        )
    elif persisted_evidence not in (None, ""):
        raise ExternalReviewError(
            f"{instance} state {current_state!r} forbids submitted revision evidence."
        )
    legacy_policy = _legacy_evidence_policy()
    if evidence_kind == "legacy" and action in legacy_policy["reject_actions"]:
        raise ExternalReviewError(
            f"{instance}.{action}: {legacy_policy['reject_message']}."
        )
    requirements = set(edge.get("requires") or [])
    if action == "submit":
        if not isinstance(current_revision, str) or not current_revision:
            raise ExternalReviewError(f"{instance} has no current revision evidence.")
        if _persisted_evidence_kind(instance, current_revision) != "canonical":
            raise ExternalReviewError(
                f"{instance}.submit requires canonical current revision evidence."
            )
        _require_readiness(instance, instance_contract, record)
    if "submitted_evidence_exactly_matches_current" in requirements:
        if fields.get(revision_field) != current_revision:
            raise ExternalReviewError(
                f"{instance} submitted revision does not match the current artifact."
            )
    if "prior_submitted_evidence_exactly_matches_pre_release_current" in requirements:
        if fields.get(revision_field) != current_revision:
            raise ExternalReviewError(
                f"{instance} submitted revision does not match the pre-release artifact."
            )
    if "explicit_approval_evidence_selected" in requirements:
        if not isinstance(approval_evidence, str) or not approval_evidence.strip():
            raise ExternalReviewError(
                f"{instance}.{action} requires explicit approval evidence."
            )
    if "returned_deck_candidate_validated" in requirements:
        if returned_candidate_validated is not True:
            raise ExternalReviewError(
                f"{instance}.{action} requires a validated returned deck candidate."
            )
    if action == "request_changes" and instance_contract.get("request_changes_gates"):
        receipts = set(record.get("workflow_receipts") or [])
        for gate in instance_contract["request_changes_gates"]:
            if gate.get("kind") == "workflow_receipt" and gate.get("name") not in receipts:
                raise ExternalReviewError(
                    f"{instance}.{action} requires workflow receipt {gate.get('name')!r}."
                )
            if (
                gate.get("kind") == "submitted_evidence_exactly_matches_current"
                and evidence_kind != "legacy"
                and fields.get(revision_field) != current_revision
            ):
                raise ExternalReviewError(
                    f"{instance} submitted revision does not match the current artifact."
                )

    planned = {state_field: edge.get("to")}
    evidence_action = edge.get("submitted_evidence")
    if evidence_action == "replace_with_current":
        planned[revision_field] = current_revision
    elif evidence_action == "replace_with_returned_approved_revision":
        if not isinstance(returned_revision, str) or not returned_revision:
            raise ExternalReviewError(
                f"{instance}.{action} requires returned revision evidence."
            )
        if _persisted_evidence_kind(instance, returned_revision) != "canonical":
            raise ExternalReviewError(
                f"{instance}.{action}: {legacy_policy['reject_message']}."
            )
        planned[revision_field] = returned_revision
    elif evidence_action == "clear":
        planned[revision_field] = ""
    elif evidence_action != "retain":
        raise ExternalReviewError(
            f"Transition {instance}.{action} has unknown evidence rule {evidence_action!r}."
        )
    for invalidated_field in edge.get("invalidates") or []:
        planned[invalidated_field] = (
            False if invalidated_field.endswith("Human Verified") else ""
        )
    if "setting_human_verification_true" in (edge.get("forbids") or []):
        forbidden = [
            field
            for field, value in planned.items()
            if field.endswith("Human Verified") and value is True
        ]
        if forbidden:
            raise ExternalReviewError(
                f"{instance}.{action} cannot set human verification true: "
                + ", ".join(forbidden)
                + "."
            )
    return planned


def _module_course_platform(client: Any, fields: Mapping[str, Any]) -> str:
    values = fields.get("Course Record ID") or fields.get("Course")
    course_id = next((item for item in values if isinstance(item, str)), None) if isinstance(values, list) else values
    if not isinstance(course_id, str):
        raise ExternalReviewError("Module has no linked Course record ID.")
    course = client.get_record("Courses", course_id)
    if not course:
        raise ExternalReviewError(f"Linked Course not found: {course_id}.")
    return course.get("fields", {}).get("Platform")


def transition_record(client: Any, instance_name: str, record_id: str) -> Dict[str, Any]:
    """Read one owner plus the exact current revision/readiness context."""
    instance = _instance_contract(instance_name)
    table = instance["table"]
    owner = client.get_record(table, record_id)
    if not owner:
        raise ExternalReviewError(f"{table} record not found: {record_id}.")
    fields = dict(owner.get("fields", {}))
    if table == "Modules":
        fields["Platform"] = _module_course_platform(client, fields)
    legacy_fallback = None
    protocol = _protocol_contract(instance)
    if fields.get(instance["state_field"]) in protocol.get(
        "submitted_evidence_required_in_states", []
    ):
        persisted = fields.get(instance["submitted_revision_field"])
        if persisted not in (None, "") and _persisted_evidence_kind(
            instance_name, persisted
        ) == "legacy":
            legacy_fallback = persisted
    subject = instance["review_subject"]
    try:
        if subject["evidence_kind"] == "version_entry":
            if subject["slug"] == "course.outline_draft":
                version = current_artifact_version(fields, subject["slug"])
            else:
                version = _registered_file_version(fields, subject["slug"])
            evidence = version_evidence(subject["slug"], version)
            linked: List[Mapping[str, Any]] = []
        elif subject["evidence_kind"] == "sorted_linked_record_manifest":
            linked = client.get_clips_by_module(record_id)
            evidence = module_video_evidence(linked)
        else:
            raise ExternalReviewError(
                f"Lifecycle instance {instance_name!r} uses unknown evidence kind "
                f"{subject.get('evidence_kind')!r}."
            )
    except (ExternalReviewError, ObjectiveOverrideError) as error:
        if legacy_fallback is None or "Version Control has no" not in str(error):
            raise
        evidence = legacy_fallback
        linked = client.get_clips_by_module(record_id) if table == "Modules" else []
    return {
        "id": record_id,
        "fields": fields,
        "current_revision": evidence,
        "linked_records": linked,
    }


def _require_mutation_host() -> Path:
    configured_host = os.environ.get(MUTATION_HOST_ENV)
    configured_lock_dir = os.environ.get(LOCK_DIR_ENV)
    if not configured_host:
        raise ExternalReviewError(f"{MUTATION_HOST_ENV} is not configured.")
    if socket.gethostname() != configured_host:
        raise ExternalReviewError(
            f"Lifecycle mutations must run on {configured_host!r}; current host is "
            f"{socket.gethostname()!r}."
        )
    if not configured_lock_dir:
        raise ExternalReviewError(f"{LOCK_DIR_ENV} is not configured.")
    lock_dir = Path(configured_lock_dir)
    if not lock_dir.is_absolute():
        raise ExternalReviewError(f"{LOCK_DIR_ENV} must be an absolute path.")
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir


@contextmanager
def lifecycle_lock(record_id: str) -> Iterator[None]:
    """Acquire one bounded persistent owner-record POSIX lease."""
    if not _RECORD_ID_RE.fullmatch(record_id):
        raise ExternalReviewError(f"Invalid Airtable record ID for lock: {record_id!r}.")
    lock_path = _require_mutation_host() / f"{record_id}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ExternalReviewError(
                        f"Timed out after {LOCK_TIMEOUT_SECONDS:g}s waiting for {record_id} lifecycle lock."
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def execute_transition(
    client: Any,
    instance: str,
    action: str,
    actor: str,
    record_id: str,
    *,
    workflow_receipts: List[str] | None = None,
) -> Dict[str, Any]:
    """Serialize, write, read back, and integrity-check one transition."""
    with lifecycle_lock(record_id):
        before = transition_record(client, instance, record_id)
        if workflow_receipts:
            before["workflow_receipts"] = list(workflow_receipts)
        updates = plan_transition(instance, action, actor, before)
        contract = _instance_contract(instance)
        table = contract["table"]
        client.update_record(table, record_id, updates)
        after = transition_record(client, instance, record_id)
        for field, expected in updates.items():
            actual = after["fields"].get(field)
            if expected == "" and actual in (None, ""):
                continue
            if actual != expected:
                raise ExternalReviewError(
                    f"Persisted lifecycle readback mismatch for {table}.{field}: "
                    f"expected {expected!r}, got {actual!r}."
                )
        state = after["fields"].get(contract["state_field"])
        submitted = after["fields"].get(contract["submitted_revision_field"])
        if state in {"Submitted", "Approved"} and submitted != after["current_revision"]:
            compensation = {
                contract["state_field"]: "Not Submitted",
                contract["submitted_revision_field"]: "",
            }
            client.update_record(table, record_id, compensation)
            compensated = client.get_record(table, record_id)
            compensated_fields = compensated.get("fields", {}) if compensated else {}
            if compensated_fields.get(contract["state_field"]) != "Not Submitted" or compensated_fields.get(contract["submitted_revision_field"]) not in (None, ""):
                raise ExternalReviewError(
                    f"Integrity blocker: {instance} raced a reviewed-input change and compensation did not persist."
                )
            raise ExternalReviewError(
                f"{instance} raced a reviewed-input change; compensated to Not Submitted."
            )
        return {
            "instance": instance,
            "action": action,
            "actor": actor,
            "record_id": record_id,
            "state": state,
            "submitted_revision": submitted,
        }


def verified_video_feedback_receipts(
    client: Any, module_id: str, feedback_record_ids: List[str]
) -> List[str]:
    """Read back a nonempty, module-owned Pluralsight feedback import."""
    unique_ids = sorted(set(feedback_record_ids))
    if not unique_ids:
        raise ExternalReviewError(
            "mark-video-changes-requested requires at least one --feedback-record-id."
        )
    clips = client.get_clips_by_module(module_id)
    clip_ids = {item["id"] for item in clips}
    demo_ids = {
        item["id"] for clip_id in clip_ids for item in client.get_demos_by_clip(clip_id)
    }
    slide_ids = {
        item["id"] for clip_id in clip_ids for item in client.get_slides_by_clip(clip_id)
    }
    owned = {
        "Module": {module_id},
        "Clip": clip_ids,
        "Demo": demo_ids,
        "Slide": slide_ids,
    }
    for feedback_id in unique_ids:
        feedback = client.get_record("Feedback", feedback_id)
        if not feedback:
            raise ExternalReviewError(f"Feedback record not found: {feedback_id}.")
        fields = feedback.get("fields", {})
        source = fields.get("Source")
        if not isinstance(source, str) or not source.startswith("Pluralsight"):
            raise ExternalReviewError(
                f"Feedback {feedback_id} is not Pluralsight-sourced: {source!r}."
            )
        status = fields.get("Processing Status")
        if not isinstance(status, str) or not status:
            raise ExternalReviewError(
                f"Feedback {feedback_id} has no Processing Status readback."
            )
        matches = []
        for field, allowed_ids in owned.items():
            linked = fields.get(field) or []
            if isinstance(linked, str):
                linked = [linked]
            if any(item in allowed_ids for item in linked):
                matches.append(field)
        if len(matches) != 1:
            raise ExternalReviewError(
                f"Feedback {feedback_id} does not resolve to exactly one element owned "
                f"by Module {module_id}."
            )
    return [
        "nonempty_feedback_import",
        "feedback_rows_persisted_and_read_back",
    ]


_RESOLUTION_KIND = "artifact_lifecycle_conflict_resolutions"
_RESOLUTION_PROCESSES = {
    "course_requirements_return",
    "course_outline",
    "slide_deck",
    "module_video",
}
_REVIEW_STATES = {"Not Submitted", "Submitted", "Changes Requested", "Approved"}


def _require_resolution(condition: bool, message: str) -> None:
    if not condition:
        raise ExternalReviewError(message)


def _validate_resolution_desired_values(
    process: str,
    desired_state: Any,
    desired_evidence: Any,
    index: int,
    baseline_sha256: str,
    input_fingerprint: str,
) -> None:
    label = f"Resolution entry {index}"
    if process == "course_requirements_return":
        protocol = _contract().get("protocols", {}).get(process, {})
        allowed_states = protocol.get("states")
        _require_resolution(
            isinstance(allowed_states, list) and desired_state in allowed_states,
            f"{label} has an invalid course requirements state.",
        )
        _require_resolution(
            desired_evidence is None,
            f"{label} forbids revision evidence for course requirements.",
        )
        return

    _require_resolution(
        desired_state is None
        or (isinstance(desired_state, str) and desired_state in _REVIEW_STATES),
        f"{label} has an invalid external-review state.",
    )
    if desired_state in {None, "Not Submitted"}:
        _require_resolution(
            desired_evidence is None,
            f"{label} forbids submitted evidence in state {desired_state!r}.",
        )
        return
    if isinstance(desired_evidence, dict) and bool(
        _LEGACY_EVIDENCE_KEYS & set(desired_evidence)
    ):
        _validate_legacy_evidence(
            desired_evidence,
            process,
            label=label,
            baseline_sha256=baseline_sha256,
            input_fingerprint=input_fingerprint,
        )
        return
    if process in {"course_outline", "slide_deck"}:
        subject = _instance_contract(process).get("review_subject", {})
        _require_resolution(
            isinstance(desired_evidence, dict)
            and set(desired_evidence) == {"slug", "v", "sha256"}
            and desired_evidence.get("slug") == subject.get("slug")
            and isinstance(desired_evidence.get("v"), int)
            and not isinstance(desired_evidence.get("v"), bool)
            and desired_evidence["v"] > 0
            and isinstance(desired_evidence.get("sha256"), str)
            and _SHA256_RE.fullmatch(desired_evidence["sha256"]) is not None,
            f"{label} has invalid version-entry evidence.",
        )
        return
    _require_resolution(
        isinstance(desired_evidence, list) and bool(desired_evidence),
        f"{label} needs a nonempty Module Video manifest.",
    )
    clip_ids: List[str] = []
    for item in desired_evidence:
        _require_resolution(
            isinstance(item, dict)
            and set(item) == {"clip_id", "v", "sha256"}
            and isinstance(item.get("clip_id"), str)
            and isinstance(item.get("v"), int)
            and not isinstance(item.get("v"), bool)
            and item["v"] > 0
            and isinstance(item.get("sha256"), str)
            and _SHA256_RE.fullmatch(item["sha256"]) is not None,
            f"{label} has invalid Module Video manifest evidence.",
        )
        clip_ids.append(item["clip_id"])
    _require_resolution(
        clip_ids == sorted(set(clip_ids)),
        f"{label} Module Video manifest is not uniquely sorted.",
    )


def _sealed_resolution(
    path: Path, process: str, record_id: str
) -> tuple[Dict[str, Any], str]:
    """Load and fully validate one immutable planner-sealed resolution artifact."""
    try:
        envelope = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExternalReviewError(
            f"Cannot read sealed lifecycle resolution {path}: {error}"
        ) from None
    _require_resolution(
        isinstance(envelope, dict), "Sealed lifecycle resolution must be a JSON object."
    )
    _require_resolution(
        set(envelope)
        == {
            "content_sha256",
            "kind",
            "schema_version",
            "created_at",
            "baseline_sha256",
            "entries",
        },
        "Sealed lifecycle resolution has an invalid envelope shape.",
    )
    content_hash = envelope.get("content_sha256")
    _require_resolution(
        isinstance(content_hash, str)
        and _SHA256_RE.fullmatch(content_hash) is not None,
        "Sealed lifecycle resolution has an invalid content_sha256.",
    )
    payload = {key: value for key, value in envelope.items() if key != "content_sha256"}
    _require_resolution(
        _fingerprint(payload) == content_hash,
        "Sealed lifecycle resolution content hash does not match its payload.",
    )
    _require_resolution(
        envelope.get("kind") == _RESOLUTION_KIND,
        "Sealed lifecycle resolution has the wrong kind.",
    )
    _require_resolution(
        isinstance(envelope.get("schema_version"), int)
        and not isinstance(envelope.get("schema_version"), bool)
        and envelope["schema_version"] == 1,
        "Sealed lifecycle resolution must use schema_version 1.",
    )
    _require_resolution(
        isinstance(envelope.get("created_at"), str)
        and bool(envelope["created_at"].strip()),
        "Sealed lifecycle resolution has no created_at timestamp.",
    )
    baseline_sha256 = envelope.get("baseline_sha256")
    _require_resolution(
        isinstance(baseline_sha256, str)
        and _SHA256_RE.fullmatch(baseline_sha256) is not None,
        "Sealed lifecycle resolution has an invalid baseline_sha256.",
    )
    entries = envelope.get("entries")
    _require_resolution(
        isinstance(entries, list) and bool(entries),
        "Sealed lifecycle resolution must contain nonempty entries.",
    )
    required_entry_keys = {
        "process",
        "record_id",
        "baseline_input_fingerprint",
        "desired_state",
        "desired_evidence",
        "reason",
        "authoritative_evidence",
    }
    seen: set[tuple[str, str]] = set()
    matches: List[Dict[str, Any]] = []
    for index, entry in enumerate(entries):
        _require_resolution(
            isinstance(entry, dict) and set(entry) == required_entry_keys,
            f"Resolution entry {index} has an invalid shape.",
        )
        entry_process = entry.get("process")
        entry_record_id = entry.get("record_id")
        _require_resolution(
            isinstance(entry_process, str)
            and entry_process in _RESOLUTION_PROCESSES,
            f"Resolution entry {index} has an unknown process.",
        )
        _require_resolution(
            isinstance(entry_record_id, str)
            and _RECORD_ID_RE.fullmatch(entry_record_id) is not None,
            f"Resolution entry {index} has an invalid record ID.",
        )
        baseline = entry.get("baseline_input_fingerprint")
        _require_resolution(
            isinstance(baseline, str) and _SHA256_RE.fullmatch(baseline) is not None,
            f"Resolution entry {index} has an invalid baseline fingerprint.",
        )
        _require_resolution(
            isinstance(entry.get("reason"), str) and bool(entry["reason"].strip()),
            f"Resolution entry {index} needs a nonblank reason.",
        )
        authorities = entry.get("authoritative_evidence")
        _require_resolution(
            isinstance(authorities, list) and bool(authorities),
            f"Resolution entry {index} needs authoritative evidence.",
        )
        for evidence_index, evidence in enumerate(authorities):
            _require_resolution(
                isinstance(evidence, dict)
                and set(evidence) == {"source", "locator", "sha256"}
                and isinstance(evidence.get("source"), str)
                and bool(evidence["source"].strip())
                and isinstance(evidence.get("locator"), str)
                and bool(evidence["locator"].strip())
                and isinstance(evidence.get("sha256"), str)
                and _SHA256_RE.fullmatch(evidence["sha256"]) is not None,
                f"Resolution entry {index} authoritative evidence {evidence_index} is invalid.",
            )
        _validate_resolution_desired_values(
            entry_process,
            entry.get("desired_state"),
            entry.get("desired_evidence"),
            index,
            baseline_sha256,
            baseline,
        )
        key = (entry_process, entry_record_id)
        _require_resolution(key not in seen, f"Duplicate lifecycle resolution entry {key}.")
        seen.add(key)
        if key == (process, record_id):
            matches.append(entry)
    _require_resolution(
        len(matches) == 1,
        f"Sealed lifecycle resolution does not contain exactly one {process} entry for {record_id}.",
    )
    return matches[0], content_hash


def _rollback_process_contract(
    process: str,
) -> tuple[str, List[str], List[str]]:
    """Return the one contract-owned table, field set, and command prefix."""
    if process == "course_requirements_return":
        protocol = _contract().get("protocols", {}).get(process)
        if not isinstance(protocol, dict):
            raise ExternalReviewError(
                "Lifecycle contract has no course requirements return protocol."
            )
        table = "Courses"
        owned_fields = [protocol.get("field"), protocol.get("audit_field")]
        migration = protocol.get("migration")
    else:
        instance = _instance_contract(process)
        table = instance.get("table")
        owned_fields = [
            instance.get("state_field"),
            instance.get("submitted_revision_field"),
        ]
        migration = instance.get("migration")
    if table not in {"Courses", "Modules"} or not all(
        isinstance(field, str) and bool(field) for field in owned_fields
    ):
        raise ExternalReviewError(
            f"Lifecycle rollback ownership contract is invalid for {process}."
        )
    rollback_cli = migration.get("rollback_cli") if isinstance(migration, dict) else None
    if not (
        isinstance(rollback_cli, dict)
        and set(rollback_cli) == {"group", "command"}
        and rollback_cli.get("group")
        == ("courses" if table == "Courses" else "modules")
        and isinstance(rollback_cli.get("command"), str)
        and bool(rollback_cli["command"])
    ):
        raise ExternalReviewError(
            f"Lifecycle rollback CLI contract is invalid for {process}."
        )
    return table, owned_fields, [rollback_cli["group"], rollback_cli["command"]]


def _require_sha256(value: Any, label: str) -> str:
    _require_resolution(
        isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None,
        f"{label} must be 64 lowercase hex characters.",
    )
    return value


def _validate_authoritative_evidence(value: Any, label: str) -> None:
    _require_resolution(
        isinstance(value, list) and bool(value),
        f"{label} must be a nonempty array.",
    )
    for index, evidence in enumerate(value):
        _require_resolution(
            isinstance(evidence, dict)
            and set(evidence) == {"source", "locator", "sha256"}
            and isinstance(evidence.get("source"), str)
            and bool(evidence["source"].strip())
            and isinstance(evidence.get("locator"), str)
            and bool(evidence["locator"].strip())
            and isinstance(evidence.get("sha256"), str)
            and _SHA256_RE.fullmatch(evidence["sha256"]) is not None,
            f"{label} item {index} is invalid.",
        )


def _validate_requirements_after_fields(
    expected: Mapping[str, Any], owned_fields: List[str], label: str
) -> None:
    state_field, audit_field = owned_fields
    state = expected[state_field]
    audit = expected[audit_field]
    _require_resolution(
        state is None or isinstance(state, str),
        f"{label} state must be a string or null.",
    )
    if not isinstance(audit, dict):
        _require_resolution(
            audit is None or isinstance(audit, str),
            f"{label} audit must be text, null, or the fixed journal constraint.",
        )
        return
    _require_resolution(
        set(audit) == {"kind", "semantic"}
        and audit.get("kind") == "forward_journal_exact"
        and isinstance(audit.get("semantic"), dict),
        f"{label} audit constraint has an invalid shape.",
    )
    semantic = audit["semantic"]
    mode = semantic.get("mode")
    if mode == "append_update_received":
        _require_resolution(
            set(semantic)
            == {
                "mode",
                "baseline_input_fingerprint",
                "resulting_state",
                "required_event_type",
            }
            and semantic.get("resulting_state") == "Update Received"
            and semantic.get("required_event_type") == "update_received"
            and state == semantic["resulting_state"],
            f"{label} update-received audit constraint is invalid.",
        )
        _require_sha256(
            semantic.get("baseline_input_fingerprint"),
            f"{label} baseline_input_fingerprint",
        )
        return
    if mode == "migration_resolution_applied":
        _require_resolution(
            set(semantic)
            == {
                "mode",
                "resolution_artifact_sha256",
                "baseline_input_fingerprint",
                "resulting_state",
                "reason",
                "authoritative_evidence",
            }
            and (semantic.get("resulting_state") is None or isinstance(semantic.get("resulting_state"), str))
            and state == semantic.get("resulting_state")
            and isinstance(semantic.get("reason"), str)
            and bool(semantic["reason"].strip()),
            f"{label} migration-resolution audit constraint is invalid.",
        )
        _require_sha256(
            semantic.get("resolution_artifact_sha256"),
            f"{label} resolution_artifact_sha256",
        )
        _require_sha256(
            semantic.get("baseline_input_fingerprint"),
            f"{label} baseline_input_fingerprint",
        )
        _validate_authoritative_evidence(
            semantic.get("authoritative_evidence"),
            f"{label} authoritative_evidence",
        )
        return
    raise ExternalReviewError(f"{label} audit constraint mode is invalid.")


def _validate_rollback_operation(
    operation: Any, envelope: Mapping[str, Any], index: int
) -> Dict[str, Any]:
    label = f"Rollback operation {index}"
    _require_resolution(
        isinstance(operation, dict) and set(operation) == _ROLLBACK_ENTRY_KEYS,
        f"{label} has an invalid shape.",
    )
    process = operation.get("process")
    record_id = operation.get("record_id")
    _require_resolution(
        isinstance(process, str) and process in _RESOLUTION_PROCESSES,
        f"{label} has an unknown process.",
    )
    _require_resolution(
        isinstance(record_id, str) and _RECORD_ID_RE.fullmatch(record_id) is not None,
        f"{label} has an invalid record ID.",
    )
    _require_resolution(
        operation.get("kind") == "record_reverse",
        f"{label} has the wrong kind.",
    )
    _require_resolution(
        operation.get("operation_id") == f"record.{process}.{record_id}",
        f"{label} has the wrong operation ID.",
    )
    table, owned_fields, rollback_cli = _rollback_process_contract(process)
    _require_resolution(
        operation.get("table") == table,
        f"{label} targets the wrong table.",
    )
    _require_resolution(
        operation.get("owned_fields") == owned_fields,
        f"{label} does not contain the contract-owned fields in exact order.",
    )
    _require_resolution(
        operation.get("rollback_cli") == rollback_cli,
        f"{label} does not use the fixed rollback command prefix.",
    )
    for binding in ["plan_sha256", "baseline_sha256", "pipeline_sha256", "base_id"]:
        _require_resolution(
            operation.get(binding) == envelope.get(binding),
            f"{label} {binding} does not match its sealed envelope.",
        )
    expected = operation.get("expected_after_fields")
    restore = operation.get("restore_before_fields")
    expected_keys = set(owned_fields)
    _require_resolution(
        isinstance(expected, dict) and set(expected) == expected_keys,
        f"{label} expected_after_fields has an invalid field set.",
    )
    _require_resolution(
        isinstance(restore, dict) and set(restore) == expected_keys,
        f"{label} restore_before_fields has an invalid field set.",
    )
    _require_resolution(
        all(value is None or isinstance(value, str) for value in restore.values()),
        f"{label} restore_before_fields must contain only raw text or null values.",
    )
    if process == "course_requirements_return":
        _validate_requirements_after_fields(expected, owned_fields, label)
    else:
        _require_resolution(
            all(value is None or isinstance(value, str) for value in expected.values()),
            f"{label} expected_after_fields must contain only raw text or null values.",
        )
    operation_hash = operation.get("operation_sha256")
    _require_sha256(operation_hash, f"{label} operation_sha256")
    operation_payload = {
        key: value for key, value in operation.items() if key != "operation_sha256"
    }
    _require_resolution(
        _fingerprint(operation_payload) == operation_hash,
        f"{label} content hash does not match its payload.",
    )
    return operation


def _sealed_rollback_entry(
    path: Path, process: str, record_id: str
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Load one immutable rollback plan and return its sole matching operation."""
    try:
        envelope = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExternalReviewError(
            f"Cannot read sealed lifecycle rollback plan {path}: {error}"
        ) from None
    _require_resolution(
        isinstance(envelope, dict) and set(envelope) == _ROLLBACK_ENVELOPE_KEYS,
        "Sealed lifecycle rollback plan has an invalid envelope shape.",
    )
    content_hash = envelope.get("content_sha256")
    _require_sha256(content_hash, "Sealed lifecycle rollback plan content_sha256")
    payload = {key: value for key, value in envelope.items() if key != "content_sha256"}
    _require_resolution(
        _fingerprint(payload) == content_hash,
        "Sealed lifecycle rollback plan content hash does not match its payload.",
    )
    _require_resolution(
        envelope.get("kind") == _ROLLBACK_KIND,
        "Sealed lifecycle rollback plan has the wrong kind.",
    )
    _require_resolution(
        envelope.get("schema_version") == 2
        and not isinstance(envelope.get("schema_version"), bool),
        "Sealed lifecycle rollback plan must use schema_version 2.",
    )
    _require_resolution(
        isinstance(envelope.get("created_at"), str)
        and bool(envelope["created_at"].strip()),
        "Sealed lifecycle rollback plan has no created_at timestamp.",
    )
    for binding in [
        "plan_sha256",
        "baseline_sha256",
        "forward_pipeline_sha256",
        "pipeline_sha256",
    ]:
        _require_sha256(envelope.get(binding), f"Rollback plan {binding}")
    _require_resolution(
        isinstance(envelope.get("base_id"), str)
        and _BASE_ID_RE.fullmatch(envelope["base_id"]) is not None,
        "Sealed lifecycle rollback plan has an invalid base ID.",
    )
    _require_resolution(
        envelope.get("schema_reverse")
        == "leave_additive_lifecycle_fields_in_place",
        "Sealed lifecycle rollback plan has an invalid schema_reverse policy.",
    )
    _require_resolution(
        envelope.get("apply_supported") is True,
        "Sealed lifecycle rollback plan is not apply-supported.",
    )
    _require_resolution(
        isinstance(envelope.get("formula_reverse"), list),
        "Sealed lifecycle rollback plan formula_reverse must be an array.",
    )
    current_pipeline_hash = _pipeline_fingerprint(_pipeline_document())
    _require_resolution(
        envelope["pipeline_sha256"] == current_pipeline_hash,
        "Sealed lifecycle rollback plan targets a different lifecycle contract.",
    )
    operations = envelope.get("record_reverse")
    _require_resolution(
        isinstance(operations, list) and bool(operations),
        "Sealed lifecycle rollback plan must contain record_reverse operations.",
    )
    seen: set[tuple[str, str]] = set()
    matches: List[Dict[str, Any]] = []
    for index, value in enumerate(operations):
        operation = _validate_rollback_operation(value, envelope, index)
        key = (operation["process"], operation["record_id"])
        _require_resolution(key not in seen, f"Duplicate lifecycle rollback operation {key}.")
        seen.add(key)
        if key == (process, record_id):
            matches.append(operation)
    _require_resolution(
        len(matches) == 1,
        f"Sealed lifecycle rollback plan does not contain exactly one {process} operation for {record_id}.",
    )
    return matches[0], envelope


def _normalized_platform(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None


def _strict_legacy_bool(
    fields: Mapping[str, Any], field: str, conflicts: List[str]
) -> bool:
    value = fields.get(field)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    conflicts.append(f"{field}:non_boolean")
    return False


def _planner_version_evidence(fields: Mapping[str, Any], slug: str) -> Dict[str, Any]:
    raw = fields.get("Version Control")
    if not isinstance(raw, str) or not raw.strip():
        raise ExternalReviewError("Version Control is blank")
    try:
        ledger = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ExternalReviewError(f"Version Control is malformed JSON: {error}") from None
    if not isinstance(ledger, dict):
        raise ExternalReviewError("Version Control must be an object")
    entry = ledger.get(slug)
    if not isinstance(entry, dict):
        raise ExternalReviewError(f"Version Control has no {slug} entry")
    version = entry.get("v")
    digest = entry.get("sha256")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ExternalReviewError(f"{slug} has invalid version")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ExternalReviewError(f"{slug} has invalid sha256")
    return {"slug": slug, "v": version, "sha256": digest}


def _planner_video_manifest(
    client: Any, fields: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    clip_ids = fields.get("Clips")
    if not isinstance(clip_ids, list) or not clip_ids:
        raise ExternalReviewError("module has no linked Clips")
    if not all(isinstance(clip_id, str) for clip_id in clip_ids):
        raise ExternalReviewError("module Clips contains invalid IDs")
    manifest = []
    for clip_id in sorted(clip_ids):
        clip = client.get_record("Clips", clip_id)
        if not clip or not isinstance(clip.get("fields"), dict):
            raise ExternalReviewError(f"linked Clip {clip_id} is missing from baseline")
        evidence = _planner_version_evidence(clip["fields"], "clip.recording")
        manifest.append(
            {"clip_id": clip_id, "v": evidence["v"], "sha256": evidence["sha256"]}
        )
    return manifest


def _review_baseline_inputs(
    client: Any, instance_name: str, fields: Mapping[str, Any]
) -> Dict[str, Any]:
    instance = _instance_contract(instance_name)
    migration = instance.get("migration", {})
    legacy = migration.get("legacy_fields")
    if not isinstance(legacy, dict):
        raise ExternalReviewError(f"{instance_name} has no migration legacy fields.")
    if instance_name == "module_video":
        legacy_names = [
            legacy["submitted"],
            legacy["approved"],
            legacy["feedback_needed"],
            legacy["feedback_ready"],
            legacy["post_feedback_submitted"],
        ]
        names = [
            "Platform",
            "Clips",
            instance["state_field"],
            instance["submitted_revision_field"],
            *legacy_names,
        ]
        inputs = {name: fields.get(name) for name in names}
        clip_ids = fields.get("Clips", [])
        if not isinstance(clip_ids, list):
            raise ExternalReviewError("Module Clips baseline input is not a list.")
        linked_versions: Dict[str, Any] = {}
        for clip_id in clip_ids:
            if not isinstance(clip_id, str):
                continue
            clip = client.get_record("Clips", clip_id)
            clip_fields = clip.get("fields", {}) if isinstance(clip, dict) else {}
            linked_versions[clip_id] = clip_fields.get("Version Control")
        inputs["linked_clip_versions"] = linked_versions
        return inputs
    names = [
        "Platform",
        "Version Control",
        legacy["submitted"],
        legacy["approved"],
        instance["state_field"],
        instance["submitted_revision_field"],
    ]
    return {name: fields.get(name) for name in names}


def _existing_review_conflicts(
    fields: Mapping[str, Any],
    state_field: str,
    evidence_field: str,
    desired_state: str,
    desired_evidence: Any,
) -> List[str]:
    conflicts: List[str] = []
    state = fields.get(state_field)
    evidence = fields.get(evidence_field)
    if state in (None, ""):
        if evidence not in (None, ""):
            conflicts.append("partial_backfill:evidence_without_state")
        return conflicts
    if not isinstance(state, str) or state not in _REVIEW_STATES:
        return ["partial_backfill:invalid_state"]
    if state != desired_state:
        conflicts.append(f"partial_backfill:state_mismatch:{state}")
    if desired_state == "Not Submitted":
        if evidence not in (None, ""):
            conflicts.append("partial_backfill:not_submitted_with_evidence")
    elif evidence in (None, ""):
        conflicts.append("partial_backfill:submitted_state_without_evidence")
    else:
        try:
            parsed = json.loads(evidence) if isinstance(evidence, str) else None
            if parsed != desired_evidence:
                conflicts.append("partial_backfill:submitted_evidence_mismatch")
        except json.JSONDecodeError:
            conflicts.append("partial_backfill:malformed_submitted_evidence")
    return conflicts


def _review_migration_conflicts(
    client: Any, instance_name: str, fields: Mapping[str, Any]
) -> List[str]:
    instance = _instance_contract(instance_name)
    legacy = instance["migration"]["legacy_fields"]
    conflicts: List[str] = []
    platform = _normalized_platform(fields.get("Platform"))
    if platform not in {"Pluralsight", "Udemy"}:
        conflicts.append("platform_not_exactly_pluralsight_or_udemy")
    if instance_name in {"course_outline", "slide_deck"}:
        submitted = _strict_legacy_bool(fields, legacy["submitted"], conflicts)
        approved = _strict_legacy_bool(fields, legacy["approved"], conflicts)
        if approved and not submitted:
            conflicts.append("approved_without_submitted")
        desired_state = "Approved" if approved else "Submitted" if submitted else "Not Submitted"
    else:
        legacy_names = [
            legacy["submitted"],
            legacy["approved"],
            legacy["feedback_needed"],
            legacy["feedback_ready"],
            legacy["post_feedback_submitted"],
        ]
        submitted, approved, feedback_needed, feedback_ready, post_submitted = [
            _strict_legacy_bool(fields, name, conflicts) for name in legacy_names
        ]
        if approved and not (submitted or post_submitted):
            conflicts.append("approved_without_submission")
        if approved and (feedback_needed or feedback_ready):
            conflicts.append("approved_with_feedback_cycle")
        if feedback_needed and not (submitted or post_submitted):
            conflicts.append("feedback_without_submission")
        if feedback_ready and not feedback_needed:
            conflicts.append("feedback_ready_without_feedback_needed")
        if post_submitted and feedback_needed:
            conflicts.append("post_feedback_submitted_with_feedback_needed")
        if post_submitted and feedback_ready:
            conflicts.append("post_feedback_submitted_with_feedback_ready")
        desired_state = (
            "Approved"
            if approved
            else "Changes Requested"
            if feedback_needed
            else "Submitted"
            if submitted or post_submitted
            else "Not Submitted"
        )
    desired_evidence: Any = None
    if platform == "Pluralsight" and desired_state != "Not Submitted":
        try:
            if instance_name == "module_video":
                desired_evidence = _planner_video_manifest(client, fields)
            else:
                desired_evidence = _planner_version_evidence(
                    fields, instance["review_subject"]["slug"]
                )
        except ExternalReviewError as error:
            conflicts.append(str(error))
    state_field = instance["state_field"]
    evidence_field = instance["submitted_revision_field"]
    if platform == "Udemy":
        if fields.get(state_field) not in (None, "") or fields.get(evidence_field) not in (
            None,
            "",
        ):
            conflicts.append(f"udemy_has_{instance_name}_lifecycle_evidence")
    else:
        conflicts.extend(
            _existing_review_conflicts(
                fields,
                state_field,
                evidence_field,
                desired_state,
                desired_evidence,
            )
        )
    return sorted(set(conflicts))


def _execute_resolved_review_migration(
    client: Any,
    instance_name: str,
    record_id: str,
    resolution_path: Path,
) -> Dict[str, Any]:
    resolution, artifact_hash = _sealed_resolution(
        resolution_path, instance_name, record_id
    )
    with lifecycle_lock(record_id):
        instance = _instance_contract(instance_name)
        table = instance["table"]
        owner = client.get_record(table, record_id)
        if not owner or not isinstance(owner.get("fields"), dict):
            raise ExternalReviewError(f"{table} record not found: {record_id}.")
        fields = owner["fields"]
        inputs = _review_baseline_inputs(client, instance_name, fields)
        current_fingerprint = _fingerprint(inputs)
        if current_fingerprint != resolution["baseline_input_fingerprint"]:
            raise ExternalReviewError(
                f"Stale sealed resolution baseline for {instance_name} {record_id}: "
                f"expected {resolution['baseline_input_fingerprint']}, got {current_fingerprint}."
            )
        conflicts = _review_migration_conflicts(client, instance_name, fields)
        if not conflicts:
            raise ExternalReviewError(
                f"Sealed resolution targets non-conflict {instance_name} record {record_id}."
            )
        desired_state = resolution["desired_state"]
        desired_evidence = resolution["desired_evidence"]
        state_field = instance["state_field"]
        evidence_field = instance["submitted_revision_field"]
        serialized_evidence = (
            "" if desired_evidence is None else _stable_json(desired_evidence)
        )
        updates = {
            state_field: desired_state,
            evidence_field: serialized_evidence,
        }
        client.update_record(table, record_id, updates)
        persisted = client.get_record(table, record_id)
        persisted_fields = persisted.get("fields", {}) if persisted else {}
        actual_state = persisted_fields.get(state_field)
        actual_evidence = persisted_fields.get(evidence_field)
        if actual_state != desired_state:
            raise ExternalReviewError(
                f"Resolved migration state readback mismatch for {instance_name} {record_id}."
            )
        if desired_evidence is None:
            evidence_matches = actual_evidence in (None, "")
        else:
            try:
                evidence_matches = (
                    isinstance(actual_evidence, str)
                    and json.loads(actual_evidence) == desired_evidence
                )
            except json.JSONDecodeError:
                evidence_matches = False
        if not evidence_matches:
            raise ExternalReviewError(
                f"Resolved migration evidence readback mismatch for {instance_name} {record_id}."
            )
        return {
            "instance": instance_name,
            "action": "migrate_resolved_conflict",
            "record_id": record_id,
            "state": actual_state,
            "submitted_revision": actual_evidence,
            "resolution_artifact_sha256": artifact_hash,
            "baseline_input_fingerprint": current_fingerprint,
            "resolved_conflicts": conflicts,
        }


def _requirements_baseline_inputs(fields: Mapping[str, Any]) -> Dict[str, Any]:
    protocol = _contract().get("protocols", {}).get("course_requirements_return")
    if not isinstance(protocol, dict):
        raise ExternalReviewError("Missing course requirements migration protocol.")
    state_field = protocol.get("field")
    audit_field = protocol.get("audit_field")
    legacy_field = protocol.get("migration", {}).get("legacy_returned_field")
    if not all(isinstance(name, str) for name in [state_field, audit_field, legacy_field]):
        raise ExternalReviewError("Course requirements migration fields are invalid.")
    return {
        "Platform": fields.get("Platform"),
        state_field: fields.get(state_field),
        audit_field: fields.get(audit_field),
        legacy_field: fields.get(legacy_field),
    }


def _audit_contains_event(value: Any, event_type: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        audit = json.loads(value)
    except json.JSONDecodeError:
        return False
    events = audit.get("events") if isinstance(audit, dict) else None
    return isinstance(events, list) and any(
        isinstance(event, dict) and event.get("type") == event_type
        for event in events
    )


def _requirements_migration_conflicts(fields: Mapping[str, Any]) -> List[str]:
    protocol = _contract()["protocols"]["course_requirements_return"]
    state_field = protocol["field"]
    audit_field = protocol["audit_field"]
    legacy_field = protocol["migration"]["legacy_returned_field"]
    conflicts: List[str] = []
    platform = _normalized_platform(fields.get("Platform"))
    if platform not in {"Pluralsight", "Udemy"}:
        conflicts.append("platform_not_exactly_pluralsight_or_udemy")
    state = fields.get(state_field)
    allowed_states = protocol.get("states", [])
    if state != "" and not any(state == allowed for allowed in allowed_states):
        conflicts.append("invalid_requirements_state")
    returned = _strict_legacy_bool(fields, legacy_field, conflicts)
    if platform == "Udemy":
        if (
            state not in (None, "")
            or fields.get(audit_field) not in (None, "")
            or returned
        ):
            conflicts.append("udemy_has_requirements_lifecycle_evidence")
    elif returned:
        if state != "Correction Requested":
            conflicts.append("legacy_returned_true_outside_correction_requested")
        elif not _audit_contains_event(
            fields.get(audit_field), "correction_requested"
        ):
            conflicts.append("missing_matching_correction_request_audit_event")
    return sorted(set(conflicts))


def execute_requirements_migration_resolution(
    client: Any, record_id: str, resolution_file: Path
) -> Dict[str, Any]:
    """Apply one planner-sealed course-requirements conflict resolution."""
    process = "course_requirements_return"
    resolution, artifact_hash = _sealed_resolution(
        resolution_file, process, record_id
    )
    with lifecycle_lock(record_id):
        course = client.get_record("Courses", record_id)
        if not course or not isinstance(course.get("fields"), dict):
            raise ExternalReviewError(f"Courses record not found: {record_id}.")
        fields = course["fields"]
        inputs = _requirements_baseline_inputs(fields)
        current_fingerprint = _fingerprint(inputs)
        if current_fingerprint != resolution["baseline_input_fingerprint"]:
            raise ExternalReviewError(
                f"Stale sealed resolution baseline for {process} {record_id}: "
                f"expected {resolution['baseline_input_fingerprint']}, got {current_fingerprint}."
            )
        conflicts = _requirements_migration_conflicts(fields)
        if not conflicts:
            raise ExternalReviewError(
                f"Sealed resolution targets non-conflict {process} record {record_id}."
            )

        protocol = _contract()["protocols"][process]
        migration_write = protocol.get("migration", {}).get("resolution_write")
        if not isinstance(migration_write, dict):
            raise ExternalReviewError(
                "Course requirements migration contract has no resolution_write object."
            )
        state_field = protocol["field"]
        audit_field = protocol["audit_field"]
        if migration_write.get("scope") != "conflict_resolution_only":
            raise ExternalReviewError("Requirements resolution_write scope is invalid.")
        if migration_write.get("fields_written_atomically") != [
            state_field,
            audit_field,
        ]:
            raise ExternalReviewError(
                "Requirements resolution_write atomic field contract is invalid."
            )
        if migration_write.get("post_write_readback_required") is not True:
            raise ExternalReviewError(
                "Requirements resolution_write must require post-write readback."
            )
        desired_state = resolution["desired_state"]
        if desired_state is None:
            null_write = migration_write.get("null_state")
            if null_write != {"state_value": None, "audit_value": None}:
                raise ExternalReviewError(
                    "Requirements resolution_write null-state contract is invalid."
                )
            expected_audit = None
        else:
            non_null = migration_write.get("non_null_state")
            if not isinstance(non_null, dict) or non_null.get(
                "replace_existing_audit"
            ) is not True:
                raise ExternalReviewError(
                    "Requirements resolution_write non-null audit contract is invalid."
                )
            audit_contract = non_null.get("audit_document")
            event_contract = non_null.get("event")
            if not isinstance(audit_contract, dict) or not isinstance(
                event_contract, dict
            ):
                raise ExternalReviewError(
                    "Requirements resolution_write audit metadata is invalid."
                )
            event_values = {
                "type": event_contract.get("type"),
                "at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                event_contract.get("state_binding_key"): desired_state,
                "resolutionArtifactSha256": artifact_hash,
                "baselineInputFingerprint": current_fingerprint,
                "reason": resolution["reason"],
                "authoritativeEvidence": resolution["authoritative_evidence"],
            }
            required_keys = event_contract.get("required_keys")
            if (
                event_contract.get("type") != "migration_resolution_applied"
                or event_contract.get("state_binding_key") != "resultingState"
                or not isinstance(required_keys, list)
                or set(event_values) != set(required_keys)
                or audit_contract.get("schemaVersion") != 1
                or audit_contract.get("events_key") != "events"
            ):
                raise ExternalReviewError(
                    "Requirements resolution_write event contract is invalid."
                )
            expected_audit = _stable_json(
                {
                    "schemaVersion": audit_contract["schemaVersion"],
                    audit_contract["events_key"]: [event_values],
                }
            )
        updates = {state_field: desired_state, audit_field: expected_audit}
        client.update_record("Courses", record_id, updates)
        persisted = client.get_record("Courses", record_id)
        persisted_fields = persisted.get("fields", {}) if persisted else {}
        if persisted_fields.get(state_field) != desired_state:
            raise ExternalReviewError(
                f"Resolved requirements state readback mismatch for {record_id}."
            )
        actual_audit = persisted_fields.get(audit_field)
        if expected_audit is None:
            audit_matches = actual_audit is None
        else:
            try:
                audit_matches = (
                    isinstance(actual_audit, str)
                    and json.loads(actual_audit) == json.loads(expected_audit)
                )
            except json.JSONDecodeError:
                audit_matches = False
        if not audit_matches:
            raise ExternalReviewError(
                f"Resolved requirements audit readback mismatch for {record_id}."
            )
        return {
            "instance": process,
            "action": "migrate_resolved_conflict",
            "record_id": record_id,
            "state": desired_state,
            "resolution_artifact_sha256": artifact_hash,
            "baseline_input_fingerprint": current_fingerprint,
            "resolved_conflicts": conflicts,
        }


def _legacy_bool(fields: Mapping[str, Any], field: str) -> bool:
    value = fields.get(field)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ExternalReviewError(
        f"{field} migration input must be a boolean, got {value!r}."
    )


def _migration_state(instance_name: str, fields: Mapping[str, Any]) -> str:
    instance = _instance_contract(instance_name)
    legacy = instance.get("migration", {}).get("legacy_fields")
    if not isinstance(legacy, dict):
        raise ExternalReviewError(
            f"Lifecycle instance {instance_name!r} has no legacy migration fields."
        )
    values = {name: _legacy_bool(fields, field) for name, field in legacy.items()}
    if instance_name in {"course_outline", "slide_deck"}:
        if values["approved"] and not values["submitted"]:
            raise ExternalReviewError(
                f"{instance_name} migration conflict: approved_without_submitted."
            )
        if values["approved"]:
            return "Approved"
        if values["submitted"]:
            return "Submitted"
        return "Not Submitted"

    submitted = values["submitted"]
    approved = values["approved"]
    feedback_needed = values["feedback_needed"]
    feedback_ready = values["feedback_ready"]
    post_submitted = values["post_feedback_submitted"]
    conflicts = []
    if approved and not (submitted or post_submitted):
        conflicts.append("approved_without_submission")
    if approved and (feedback_needed or feedback_ready):
        conflicts.append("approved_with_feedback_cycle")
    if feedback_needed and not (submitted or post_submitted):
        conflicts.append("feedback_without_submission")
    if feedback_ready and not feedback_needed:
        conflicts.append("feedback_ready_without_feedback_needed")
    if post_submitted and feedback_needed:
        conflicts.append("post_feedback_submitted_with_feedback_needed")
    if post_submitted and feedback_ready:
        conflicts.append("post_feedback_submitted_with_feedback_ready")
    if conflicts:
        raise ExternalReviewError(
            "module_video migration conflict: " + ", ".join(conflicts) + "."
        )
    if approved:
        return "Approved"
    if feedback_needed:
        return "Changes Requested"
    if submitted or post_submitted:
        return "Submitted"
    return "Not Submitted"


def execute_migration_initialization(
    client: Any,
    instance_name: str,
    record_id: str,
    resolution_file: Path | None = None,
) -> Dict[str, Any]:
    """Backfill one lifecycle instance from its fixed contract legacy inputs."""
    if resolution_file is not None:
        return _execute_resolved_review_migration(
            client, instance_name, record_id, resolution_file
        )
    with lifecycle_lock(record_id):
        instance = _instance_contract(instance_name)
        table = instance["table"]
        owner = client.get_record(table, record_id)
        if not owner:
            raise ExternalReviewError(f"{table} record not found: {record_id}.")
        fields = dict(owner.get("fields", {}))
        platform = _normalized_platform(fields.get("Platform"))
        state_field = instance["state_field"]
        revision_field = instance["submitted_revision_field"]
        if fields.get(state_field) not in (None, ""):
            raise ExternalReviewError(
                f"{instance_name} is already initialized: {fields.get(state_field)!r}."
            )
        conflicts = _review_migration_conflicts(client, instance_name, fields)
        if conflicts:
            raise ExternalReviewError(
                f"{instance_name} migration has unresolved conflicts: "
                + ", ".join(conflicts)
                + ". Use the planner-sealed --resolution-file path."
            )
        if platform != "Pluralsight":
            updates = {state_field: None, revision_field: ""}
            state = None
        else:
            state = _migration_state(instance_name, fields)
            evidence = ""
            if state != "Not Submitted":
                if instance_name == "module_video":
                    evidence = _stable_json(_planner_video_manifest(client, fields))
                else:
                    evidence = _stable_json(
                        _planner_version_evidence(
                            fields, instance["review_subject"]["slug"]
                        )
                    )
            updates = {state_field: state, revision_field: evidence}
        persisted = client.update_record(table, record_id, updates)
        readback = persisted.get("fields", {})
        actual_revision = readback.get(revision_field)
        if readback.get(state_field) != state or (
            updates[revision_field] == "" and actual_revision not in (None, "")
        ) or (
            updates[revision_field] != "" and actual_revision != updates[revision_field]
        ):
            raise ExternalReviewError(
                f"Persisted migration readback mismatch for {instance_name} {record_id}."
            )
        return {
            "instance": instance_name,
            "action": "migrate_legacy",
            "record_id": record_id,
            "state": state,
            "submitted_revision": actual_revision,
        }


def _raw_field_matches(expected: Any, actual: Any) -> bool:
    """Compare raw Airtable values with its one supported blank round-trip."""
    if expected == "":
        return actual in (None, "")
    return actual == expected


def _owned_fields_match(
    fields: Mapping[str, Any], expected: Mapping[str, Any]
) -> bool:
    return all(
        _raw_field_matches(value, fields.get(field))
        for field, value in expected.items()
    )


def _audit_document(value: Any, label: str) -> Dict[str, Any]:
    if value in (None, ""):
        return {"schemaVersion": 1, "events": []}
    if not isinstance(value, str):
        raise ExternalReviewError(f"{label} must be JSON text.")
    try:
        document = json.loads(value)
    except json.JSONDecodeError as error:
        raise ExternalReviewError(f"{label} is malformed JSON: {error}.") from None
    if not (
        isinstance(document, dict)
        and document.get("schemaVersion") == 1
        and isinstance(document.get("events"), list)
        and all(isinstance(event, dict) for event in document["events"])
    ):
        raise ExternalReviewError(
            f"{label} must be a schemaVersion 1 audit document."
        )
    return document


def _requirements_update_received_matches(
    actual: Any, baseline: Any, semantic: Mapping[str, Any]
) -> bool:
    if not isinstance(actual, str):
        return False
    baseline_document = _audit_document(
        baseline, "Rollback baseline Learning Objectives Override Audit"
    )
    baseline_events = baseline_document["events"]
    if not baseline_events:
        return False
    correction = baseline_events[-1]
    version = correction.get("requirementsVersion")
    if not (
        correction.get("type") == "correction_requested"
        and isinstance(correction.get("at"), str)
        and bool(correction["at"])
        and isinstance(version, dict)
        and set(version) == {"v", "sha256"}
        and isinstance(version.get("v"), int)
        and not isinstance(version.get("v"), bool)
        and version["v"] > 0
        and isinstance(version.get("sha256"), str)
        and _SHA256_RE.fullmatch(version["sha256"]) is not None
    ):
        return False
    try:
        actual_document = json.loads(actual)
    except json.JSONDecodeError:
        return False
    if not (
        isinstance(actual_document, dict)
        and isinstance(actual_document.get("events"), list)
        and len(actual_document["events"]) == len(baseline_events) + 1
    ):
        return False
    event = actual_document["events"][-1]
    if not isinstance(event, dict):
        return False
    event_at = event.get("at")
    expected_event = {
        "type": semantic["required_event_type"],
        "at": event_at,
        "correctionRequestedAt": correction["at"],
        "requirementsVersion": version,
        "requirementsVersionIdentity": (
            f"course.requirements@v{version['v']} sha256:{version['sha256']}"
        ),
    }
    if event != expected_event or not (
        isinstance(event_at, str) and _UTC_SECONDS_RE.fullmatch(event_at) is not None
    ):
        return False
    expected_document = json.loads(
        json.dumps(baseline_document, ensure_ascii=False, separators=(",", ":"))
    )
    expected_document["events"].append(expected_event)
    expected_text = json.dumps(
        expected_document, ensure_ascii=False, separators=(",", ":")
    )
    return actual == expected_text


def _requirements_resolution_matches(
    actual: Any, semantic: Mapping[str, Any]
) -> bool:
    if not isinstance(actual, str):
        return False
    try:
        document = json.loads(actual)
    except json.JSONDecodeError:
        return False
    if not (
        isinstance(document, dict)
        and set(document) == {"schemaVersion", "events"}
        and document.get("schemaVersion") == 1
        and isinstance(document.get("events"), list)
        and len(document["events"]) == 1
        and isinstance(document["events"][0], dict)
    ):
        return False
    event = document["events"][0]
    event_at = event.get("at")
    expected_event = {
        "type": "migration_resolution_applied",
        "at": event_at,
        "resultingState": semantic["resulting_state"],
        "resolutionArtifactSha256": semantic["resolution_artifact_sha256"],
        "baselineInputFingerprint": semantic["baseline_input_fingerprint"],
        "reason": semantic["reason"],
        "authoritativeEvidence": semantic["authoritative_evidence"],
    }
    if event != expected_event or not (
        isinstance(event_at, str) and _UTC_SECONDS_RE.fullmatch(event_at) is not None
    ):
        return False
    return actual == _stable_json(
        {"schemaVersion": 1, "events": [expected_event]}
    )


def _requirements_forward_matches(
    fields: Mapping[str, Any], operation: Mapping[str, Any]
) -> bool:
    state_field, audit_field = operation["owned_fields"]
    expected = operation["expected_after_fields"]
    if not _raw_field_matches(expected[state_field], fields.get(state_field)):
        return False
    audit_expected = expected[audit_field]
    if not isinstance(audit_expected, dict):
        return _raw_field_matches(audit_expected, fields.get(audit_field))
    semantic = audit_expected["semantic"]
    if semantic["mode"] == "append_update_received":
        baseline = operation["restore_before_fields"][audit_field]
        return _requirements_update_received_matches(
            fields.get(audit_field), baseline, semantic
        )
    return _requirements_resolution_matches(fields.get(audit_field), semantic)


def _execute_migration_rollback(
    client: Any, process: str, record_id: str, rollback_plan: Path
) -> Dict[str, Any]:
    operation, envelope = _sealed_rollback_entry(
        rollback_plan, process, record_id
    )
    if getattr(client, "base_id", None) != envelope["base_id"]:
        raise ExternalReviewError(
            "Sealed lifecycle rollback plan targets a different Airtable base."
        )
    table = operation["table"]
    before_fields = operation["restore_before_fields"]
    with lifecycle_lock(record_id):
        owner = client.get_record(table, record_id)
        if not owner or not isinstance(owner.get("fields"), dict):
            raise ExternalReviewError(f"{table} record not found: {record_id}.")
        current_fields = owner["fields"]
        if _owned_fields_match(current_fields, before_fields):
            return {
                "instance": process,
                "action": "rollback_migration",
                "record_id": record_id,
                "already_restored": True,
                "restored_fields": dict(before_fields),
                "rollback_plan_sha256": envelope["content_sha256"],
            }
        if process == "course_requirements_return":
            forward_matches = _requirements_forward_matches(
                current_fields, operation
            )
        else:
            forward_matches = _owned_fields_match(
                current_fields, operation["expected_after_fields"]
            )
        if not forward_matches:
            raise ExternalReviewError(
                f"Rollback refused for {process} {record_id}: live owner fields are "
                "neither the sealed forward result nor the sealed baseline."
            )
        updates = {
            field: "" if value is None else value
            for field, value in before_fields.items()
        }
        client.update_record(table, record_id, updates)
        persisted = client.get_record(table, record_id)
        persisted_fields = persisted.get("fields", {}) if persisted else {}
        if not _owned_fields_match(persisted_fields, before_fields):
            raise ExternalReviewError(
                f"Rollback readback mismatch for {process} {record_id}; the exact "
                "sealed baseline could not be restored."
            )
        return {
            "instance": process,
            "action": "rollback_migration",
            "record_id": record_id,
            "already_restored": False,
            "restored_fields": {
                field: persisted_fields.get(field)
                for field in operation["owned_fields"]
            },
            "rollback_plan_sha256": envelope["content_sha256"],
        }


def execute_review_migration_rollback(
    client: Any, instance_name: str, record_id: str, rollback_plan: Path
) -> Dict[str, Any]:
    """Restore one review lifecycle owner from its planner-sealed baseline."""
    if instance_name not in {"course_outline", "slide_deck", "module_video"}:
        raise ExternalReviewError(
            f"Unknown review rollback process {instance_name!r}."
        )
    return _execute_migration_rollback(
        client, instance_name, record_id, rollback_plan
    )


def execute_requirements_migration_rollback(
    client: Any, record_id: str, rollback_plan: Path
) -> Dict[str, Any]:
    """Restore Course Requirements lifecycle fields from a sealed baseline."""
    return _execute_migration_rollback(
        client, "course_requirements_return", record_id, rollback_plan
    )
