"""Learning-objective override lifecycle for Pluralsight courses.

Lifecycle POLICY here is ADVISORY: platform scope, required state, audit/state
agreement, ledger freshness, and review currency are reported through
``warn_policy`` and the command proceeds. Only a field the CLI cannot decode at
all still raises.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict

from .artifact_versions import canonical_hash, now_iso  # noqa: F401 - re-exported for commands
from .output import warn_policy


STATE_FIELD = "Learning Objectives Override State"
AUDIT_FIELD = "Learning Objectives Override Audit"
REVIEW_FIELD = "Course Requirements Review (AI)"
OUTLINE_REVIEW_FIELD = "Outline Draft Review (AI)"
REQUIREMENTS_FIELD = "Course Requirements"
OBJECTIVES_FIELD = "Learning Objectives"
VERSION_CONTROL_FIELD = "Version Control"
REQUIREMENTS_SLUG = "course.requirements"
OUTLINE_DRAFT_SLUG = "course.outline_draft"
OBJECTIVES_OVERRIDE_SLUG = "course.learning_objectives_override"
CARRY_FORWARD_PLAN_SLUG = "update.carry_forward_plan"

CORRECTION_REQUESTED = "Correction Requested"
UPDATE_RECEIVED = "Update Received"
FEEDBACK_RESYNCED = "Feedback Resynced"
OVERRIDE_AUTHORIZED = "Override Authorized"
OVERRIDE_ACTIVE = "Override Active"

VALID_STATES = {
    CORRECTION_REQUESTED,
    UPDATE_RECEIVED,
    FEEDBACK_RESYNCED,
    OVERRIDE_AUTHORIZED,
    OVERRIDE_ACTIVE,
}
_STATE_EVENT_TYPES = {
    CORRECTION_REQUESTED: {"correction_requested"},
    UPDATE_RECEIVED: {"update_received"},
    FEEDBACK_RESYNCED: {"feedback_resynced"},
    OVERRIDE_AUTHORIZED: {"override_authorized", "override_reauthorized"},
    OVERRIDE_ACTIVE: {
        "override_applied",
        "requirements_resynced_override_active",
    },
}
_STATE_EVENT_TYPE_NAMES = frozenset().union(*_STATE_EVENT_TYPES.values())

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRAILER_RE = re.compile(
    r"^Reviewed-Version: course\.requirements@v([1-9][0-9]*) sha256:([0-9a-f]{64})$"
)


class ObjectiveOverrideError(ValueError):
    """The override audit or ledger is malformed and cannot be interpreted.

    Override lifecycle POLICY (platform scope, required state, ledger freshness)
    is advisory and reported through ``warn_policy``; the owning artifact's
    requirements and the reviewer enforce it. This exception is reserved for a
    field whose shape the CLI cannot read at all.
    """


def sha256_text(value: str) -> str:
    """Return the canonical SHA-256 for one persisted text value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_pluralsight(fields: Dict[str, Any]) -> None:
    """Report when the lifecycle runs off its owning platform."""
    if fields.get("Platform") != "Pluralsight":
        warn_policy(
            "objective_override.platform",
            "Learning-objective overrides are designed for Pluralsight; "
            f"the course has Platform={fields.get('Platform')!r}.",
        )


def current_state(fields: Dict[str, Any]) -> str:
    """Return state only when its append-only audit proves the same transition."""
    raw = fields.get(STATE_FIELD)
    state = str(raw).strip() if raw is not None else ""
    if state and state not in VALID_STATES:
        raise ObjectiveOverrideError(
            f"{STATE_FIELD} has unsupported value {state!r}; expected blank or one of "
            + ", ".join(sorted(VALID_STATES))
            + "."
        )
    audit = load_audit(fields)
    # State is derived from the latest STATE event only; provenance events of
    # other types in the same append-only document do not move the state.
    state_events = [
        event for event in audit["events"] if event.get("type") in _STATE_EVENT_TYPE_NAMES
    ]
    if not state:
        if state_events:
            warn_policy(
                "objective_override.audit",
                f"{STATE_FIELD} is blank but {AUDIT_FIELD} contains lifecycle events.",
            )
        return ""
    if not state_events:
        warn_policy(
            "objective_override.audit",
            f"{STATE_FIELD} is {state!r} but {AUDIT_FIELD} contains no events.",
        )
        return state
    event_type = state_events[-1].get("type")
    if event_type not in _STATE_EVENT_TYPES[state]:
        warn_policy(
            "objective_override.audit",
            f"{STATE_FIELD} is {state!r}, but the last audit event is {event_type!r}.",
        )
    return state


def require_state(fields: Dict[str, Any], expected: str) -> None:
    """Report when a transition runs from an unexpected state."""
    actual = current_state(fields)
    if actual != expected:
        rendered = actual or "blank"
        warn_policy(
            "objective_override.state",
            f"Learning-objective override transition normally runs from state "
            f"{expected!r}; current state is {rendered!r}.",
        )


def current_requirements_version(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Read the current course.requirements version/hash from Version Control."""
    return current_artifact_version(fields, REQUIREMENTS_SLUG)


def current_artifact_version(fields: Dict[str, Any], slug: str) -> Dict[str, Any]:
    """Read one Airtable artifact version/hash, reporting a stale ledger entry."""
    version = artifact_version_entry(fields, slug)
    actual_digest = canonical_hash(slug, fields)
    if version["sha256"] != actual_digest:
        warn_policy(
            "objective_override.ledger",
            f"{slug} Version Control hash is stale: ledger={version['sha256']}, "
            f"current={actual_digest}. Run `coursecraft versions sync` to refresh it.",
        )
    return version


def artifact_version_entry(fields: Dict[str, Any], slug: str) -> Dict[str, Any]:
    """Read one validated Version Control entry without choosing content canonicalization."""
    raw = fields.get(VERSION_CONTROL_FIELD)
    try:
        ledger = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ObjectiveOverrideError(
            f"{VERSION_CONTROL_FIELD} is not valid JSON: {exc}"
        ) from None
    if not isinstance(ledger, dict):
        raise ObjectiveOverrideError(
            f"{VERSION_CONTROL_FIELD} must decode to an object, got {type(ledger).__name__}."
        )
    entry = ledger.get(slug)
    if not isinstance(entry, dict):
        raise ObjectiveOverrideError(
            f"{VERSION_CONTROL_FIELD} has no {slug!r} entry."
        )
    version = entry.get("v")
    digest = entry.get("sha256")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ObjectiveOverrideError(
            f"{slug} version must be a positive integer, got {version!r}."
        )
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ObjectiveOverrideError(
            f"{slug} sha256 must be 64 lowercase hex characters."
        )
    return {"v": version, "sha256": digest}


def predicted_requirements_version(
    fields: Dict[str, Any], requirements: str
) -> Dict[str, Any]:
    """Predict the version entry the pre-write planner will persist."""
    current = current_requirements_version(fields)
    digest = canonical_hash(REQUIREMENTS_SLUG, {REQUIREMENTS_FIELD: requirements})
    return {
        "v": current["v"] if digest == current["sha256"] else current["v"] + 1,
        "sha256": digest,
    }


def require_current_needs_revision_review(
    fields: Dict[str, Any], version: Dict[str, Any]
) -> str:
    """Report on the current NEEDS REVISION verdict and its version trailer.

    Advisory: the review's verdict and freshness are reported, and the field's
    text is returned as-is so the caller can record it.
    """
    raw = fields.get(REVIEW_FIELD)
    if not isinstance(raw, str) or not raw:
        warn_policy("objective_override.review", f"{REVIEW_FIELD} is blank.")
        return ""
    lines = raw.splitlines()
    if not lines or lines[0] != "NEEDS REVISION":
        first = lines[0] if lines else ""
        warn_policy(
            "objective_override.review",
            f"{REVIEW_FIELD} normally begins with an exact NEEDS REVISION line; "
            f"got {first!r}.",
        )
    trailers = [match for line in lines if (match := _TRAILER_RE.fullmatch(line))]
    reviewed_version_lines = [line for line in lines if line.startswith("Reviewed-Version:")]
    if len(reviewed_version_lines) != 1 or len(trailers) != 1:
        warn_policy(
            "objective_override.review",
            f"{REVIEW_FIELD} normally carries exactly one well-formed "
            f"{REQUIREMENTS_SLUG} Reviewed-Version trailer.",
        )
        return raw
    trailer = trailers[0]
    reviewed = {"v": int(trailer.group(1)), "sha256": trailer.group(2)}
    if reviewed != version:
        warn_policy(
            "objective_override.review",
            f"{REVIEW_FIELD} is stale: reviewed {REQUIREMENTS_SLUG}@v{reviewed['v']} "
            f"sha256:{reviewed['sha256']}, current is {REQUIREMENTS_SLUG}@v{version['v']} "
            f"sha256:{version['sha256']}.",
        )
    return raw


def require_current_needs_revision_artifact_review(
    fields: Dict[str, Any], review_field: str, slug: str, version: Dict[str, Any]
) -> str:
    """Report on one NEEDS REVISION review bound to an artifact version.

    Advisory: the verdict and trailer are reported, and the field's text is
    returned as-is so the caller can record it.
    """
    raw = fields.get(review_field)
    if not isinstance(raw, str) or not raw:
        warn_policy("objective_override.review", f"{review_field} is blank.")
        return ""
    lines = raw.splitlines()
    if not lines or lines[0] != "NEEDS REVISION":
        first = lines[0] if lines else ""
        warn_policy(
            "objective_override.review",
            f"{review_field} normally begins with an exact NEEDS REVISION line; "
            f"got {first!r}.",
        )
    expected = artifact_version_identity(slug, version)
    reviewed_version_lines = [line for line in lines if line.startswith("Reviewed-Version:")]
    if reviewed_version_lines != [f"Reviewed-Version: {expected}"]:
        warn_policy(
            "objective_override.review",
            f"{review_field} normally carries exactly one current trailer "
            f"'Reviewed-Version: {expected}'.",
        )
    return raw


def load_audit(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Decode the append-only logical audit document or initialize it."""
    raw = fields.get(AUDIT_FIELD)
    if raw in (None, ""):
        return {"schemaVersion": 1, "events": []}
    if not isinstance(raw, str):
        raise ObjectiveOverrideError(f"{AUDIT_FIELD} must be JSON text.")
    try:
        audit = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ObjectiveOverrideError(f"{AUDIT_FIELD} is not valid JSON: {exc}") from None
    if not isinstance(audit, dict) or audit.get("schemaVersion") != 1:
        raise ObjectiveOverrideError(
            f"{AUDIT_FIELD} must be a schemaVersion 1 JSON object."
        )
    events = audit.get("events")
    if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
        raise ObjectiveOverrideError(f"{AUDIT_FIELD}.events must be an array of objects.")
    return audit


def append_audit(fields: Dict[str, Any], event: Dict[str, Any]) -> str:
    """Append one event without rewriting or deleting prior logical events."""
    audit = load_audit(fields)
    audit["events"].append(event)
    return json.dumps(audit, ensure_ascii=False, separators=(",", ":"))


def content_snapshot(fields: Dict[str, Any]) -> Dict[str, str]:
    """Capture the two canonical text surfaces verbatim."""
    return {
        "courseRequirements": str(fields.get(REQUIREMENTS_FIELD) or ""),
        "learningObjectives": str(fields.get(OBJECTIVES_FIELD) or ""),
    }


def read_replacement(inline: str | None, file_value: str | None) -> str:
    """Require exactly one non-empty replacement input."""
    if (inline is None) == (file_value is None):
        raise ObjectiveOverrideError(
            "Provide exactly one of --learning-objectives or --learning-objectives-file."
        )
    value = inline if inline is not None else file_value
    if value is None or not value.strip():
        raise ObjectiveOverrideError("Replacement learning objectives cannot be blank.")
    return value


def version_identity(version: Dict[str, Any]) -> str:
    """Render the exact reviewed-version identity for output/audit."""
    return f"{REQUIREMENTS_SLUG}@v{version['v']} sha256:{version['sha256']}"


def artifact_version_identity(slug: str, version: Dict[str, Any]) -> str:
    """Render one exact artifact version identity."""
    return f"{slug}@v{version['v']} sha256:{version['sha256']}"
