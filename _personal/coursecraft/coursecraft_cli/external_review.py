"""Contract-driven authority for CourseCraft external-review transitions."""
from __future__ import annotations

import fcntl
import json
import os
import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping

from .artifact_versions import coverage_map
from .coursecraft_project import coursecraft_project_root
from .objective_override import current_artifact_version


PIPELINE_FILE = "course-pipeline.json"
MUTATION_HOST_ENV = "COURSECRAFT_LIFECYCLE_MUTATION_HOST"
LOCK_DIR_ENV = "COURSECRAFT_LIFECYCLE_LOCK_DIR"
LOCK_TIMEOUT_SECONDS = 10.0
_RECORD_ID_RE = re.compile(r"^rec[A-Za-z0-9]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _require_canonical_evidence(
    instance: str, raw: Any, *, allow_legacy: bool = False
) -> Mapping[str, Any]:
    """Require one exact canonical submitted-revision evidence document."""
    if not isinstance(raw, str) or not raw.strip():
        raise ExternalReviewError(f"{instance} submitted revision evidence is blank.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ExternalReviewError(
            f"{instance} submitted revision evidence is malformed JSON: {error}."
        ) from None
    contract = _instance_contract(instance)
    subjects = [contract.get("review_subject", {})]
    if allow_legacy:
        legacy = contract.get("legacy_submitted_subjects", [])
        if not isinstance(legacy, list) or not all(
            isinstance(subject, dict) for subject in legacy
        ):
            raise ExternalReviewError(
                f"Lifecycle instance {instance!r} legacy_submitted_subjects must be a list of objects."
            )
        subjects.extend(legacy)
    for subject in subjects:
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
        if valid:
            return subject
    raise ExternalReviewError(
        f"{instance} submitted revision evidence is not canonical."
    )


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


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
    linked = record.get("linked_records") or []
    for gate in instance.get("readiness_gates", []):
        kind = gate.get("kind")
        if gate.get("applies_from") and fields.get(instance["state_field"]) not in gate["applies_from"]:
            continue
        if kind in {"version_entry_current", "linked_version_entries_current"}:
            continue  # Evidence construction already proved the exact current ledger entries.
        if kind == "ai_review_current_pass":
            evidence = version_evidence(
                gate["slug"], current_artifact_version(fields, gate["slug"])
            )
            _require_current_pass(
                fields.get(gate["field"]), gate["slug"], evidence, gate["field"]
            )
        elif kind == "field_truthy":
            if not _truthy(fields.get(gate["field"])):
                raise ExternalReviewError(f"Readiness field {gate['field']!r} is not true.")
        elif kind == "field_present":
            value = fields.get(gate["field"])
            if value in (None, "", []) or (
                isinstance(value, str) and not value.strip()
            ):
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


def _lifecycle_action_statuses(action_id: Any) -> List[str]:
    """Return canonical work-phase statuses assigned to one lifecycle action."""
    if not isinstance(action_id, str):
        return []
    phases = _pipeline_document().get("work_phases")
    if not isinstance(phases, list):
        raise ExternalReviewError("Lifecycle contract work_phases must be a list.")
    statuses: List[str] = []
    for phase in phases:
        if not isinstance(phase, dict):
            raise ExternalReviewError("Lifecycle contract work_phases entries must be objects.")
        if phase.get("lifecycle_action") != action_id:
            continue
        phase_statuses = phase.get("statuses")
        if not isinstance(phase_statuses, list) or not all(
            isinstance(status, str) for status in phase_statuses
        ):
            raise ExternalReviewError(
                f"Lifecycle work phase for {action_id!r} must define string statuses."
            )
        for status in phase_statuses:
            if status not in statuses:
                statuses.append(status)
    return statuses


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

    allowed_statuses = _lifecycle_action_statuses(action_contract.get("id"))
    if allowed_statuses and fields.get("Status") not in allowed_statuses:
        raise ExternalReviewError(
            f"{instance}.{action} requires Status in {allowed_statuses!r}; "
            f"current Status is {fields.get('Status')!r}."
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
    evidence_required_states = protocol.get(
        "submitted_evidence_required_in_states", []
    )
    persisted_evidence = fields.get(revision_field)
    if current_state in evidence_required_states:
        _require_canonical_evidence(
            instance,
            persisted_evidence,
            allow_legacy=current_state in {"Submitted", "Changes Requested"},
        )
    elif persisted_evidence not in (None, ""):
        raise ExternalReviewError(
            f"{instance} state {current_state!r} forbids submitted revision evidence."
        )
    requirements = set(edge.get("requires") or [])
    if action == "submit":
        if not isinstance(current_revision, str) or not current_revision:
            raise ExternalReviewError(f"{instance} has no current revision evidence.")
        _require_canonical_evidence(instance, current_revision)
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
        _require_canonical_evidence(instance, returned_revision)
        planned[revision_field] = returned_revision
    elif evidence_action == "clear":
        planned[revision_field] = ""
    elif evidence_action != "retain":
        raise ExternalReviewError(
            f"Transition {instance}.{action} has unknown evidence rule {evidence_action!r}."
        )
    invalidated_fields = list(edge.get("invalidates") or [])
    if action == "request_changes":
        invalidated_fields.extend(
            instance_contract.get("request_changes_invalidates") or []
        )
    for invalidated_field in invalidated_fields:
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
    subject = instance["review_subject"]
    if fields.get(instance["state_field"]) == "Submitted":
        subject = _require_canonical_evidence(
            instance_name,
            fields.get(instance["submitted_revision_field"]),
            allow_legacy=True,
        )
    if subject["evidence_kind"] == "version_entry":
        artifact = coverage_map().get(subject["slug"])
        if not isinstance(artifact, dict):
            raise ExternalReviewError(
                f"Unknown coverage-map review subject {subject['slug']!r}."
            )
        if artifact.get("kind") == "airtable_content":
            version = current_artifact_version(fields, subject["slug"])
        elif artifact.get("kind") == "file":
            version = _registered_file_version(fields, subject["slug"])
        else:
            raise ExternalReviewError(
                f"Review subject {subject['slug']!r} has unsupported artifact kind "
                f"{artifact.get('kind')!r}."
            )
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
