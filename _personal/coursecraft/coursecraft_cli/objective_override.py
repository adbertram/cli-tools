"""Fail-closed learning-objective override lifecycle for Pluralsight courses."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict

from .artifact_versions import canonical_hash, now_iso


STATE_FIELD = "Learning Objectives Override State"
AUDIT_FIELD = "Learning Objectives Override Audit"
REVIEW_FIELD = "Course Requirements Review (AI)"
REQUIREMENTS_FIELD = "Course Requirements"
OBJECTIVES_FIELD = "Learning Objectives"
VERSION_CONTROL_FIELD = "Version Control"
REQUIREMENTS_SLUG = "course.requirements"

CORRECTION_REQUESTED = "Correction Requested"
FEEDBACK_RESYNCED = "Feedback Resynced"
OVERRIDE_AUTHORIZED = "Override Authorized"
OVERRIDE_ACTIVE = "Override Active"

VALID_STATES = {
    CORRECTION_REQUESTED,
    FEEDBACK_RESYNCED,
    OVERRIDE_AUTHORIZED,
    OVERRIDE_ACTIVE,
}
_STATE_EVENT_TYPES = {
    CORRECTION_REQUESTED: {"correction_requested"},
    FEEDBACK_RESYNCED: {"feedback_resynced"},
    OVERRIDE_AUTHORIZED: {"override_authorized"},
    OVERRIDE_ACTIVE: {"override_applied", "requirements_resynced_override_active"},
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRAILER_RE = re.compile(
    r"^Reviewed-Version: course\.requirements@v([1-9][0-9]*) sha256:([0-9a-f]{64})$"
)


class ObjectiveOverrideError(ValueError):
    """The requested override transition failed a lifecycle gate."""


def sha256_text(value: str) -> str:
    """Return the canonical SHA-256 for one persisted text value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_pluralsight(fields: Dict[str, Any]) -> None:
    """Require the lifecycle's owning platform."""
    if fields.get("Platform") != "Pluralsight":
        raise ObjectiveOverrideError(
            "Learning-objective overrides are Pluralsight-only; "
            f"the course has Platform={fields.get('Platform')!r}."
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
    events = audit["events"]
    if not state:
        if events:
            raise ObjectiveOverrideError(
                f"{STATE_FIELD} is blank but {AUDIT_FIELD} contains lifecycle events."
            )
        return ""
    if not events:
        raise ObjectiveOverrideError(
            f"{STATE_FIELD} is {state!r} but {AUDIT_FIELD} contains no events."
        )
    event_type = events[-1].get("type")
    if event_type not in _STATE_EVENT_TYPES[state]:
        raise ObjectiveOverrideError(
            f"{STATE_FIELD} is {state!r}, but the last audit event is {event_type!r}."
        )
    return state


def require_state(fields: Dict[str, Any], expected: str) -> None:
    """Require one exact state before a transition."""
    actual = current_state(fields)
    if actual != expected:
        rendered = actual or "blank"
        raise ObjectiveOverrideError(
            f"Learning-objective override transition requires state {expected!r}; "
            f"current state is {rendered!r}."
        )


def current_requirements_version(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Read the current course.requirements version/hash from Version Control."""
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
    entry = ledger.get(REQUIREMENTS_SLUG)
    if not isinstance(entry, dict):
        raise ObjectiveOverrideError(
            f"{VERSION_CONTROL_FIELD} has no {REQUIREMENTS_SLUG!r} entry. "
            "Run courses sync-requirements before entering the override lifecycle."
        )
    version = entry.get("v")
    digest = entry.get("sha256")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ObjectiveOverrideError(
            f"{REQUIREMENTS_SLUG} version must be a positive integer, got {version!r}."
        )
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ObjectiveOverrideError(
            f"{REQUIREMENTS_SLUG} sha256 must be 64 lowercase hex characters."
        )
    actual_digest = canonical_hash(REQUIREMENTS_SLUG, fields)
    if digest != actual_digest:
        raise ObjectiveOverrideError(
            f"{REQUIREMENTS_SLUG} Version Control hash is stale: ledger={digest}, "
            f"current={actual_digest}. Run the version sync before continuing."
        )
    return {"v": version, "sha256": digest}


def predicted_requirements_version(
    fields: Dict[str, Any], requirements: str
) -> Dict[str, Any]:
    """Predict the version entry stamp_versions will persist for requirements."""
    current = current_requirements_version(fields)
    digest = canonical_hash(REQUIREMENTS_SLUG, {REQUIREMENTS_FIELD: requirements})
    return {
        "v": current["v"] if digest == current["sha256"] else current["v"] + 1,
        "sha256": digest,
    }


def require_current_needs_revision_review(
    fields: Dict[str, Any], version: Dict[str, Any]
) -> str:
    """Require a current NEEDS REVISION verdict with one exact version trailer."""
    raw = fields.get(REVIEW_FIELD)
    if not isinstance(raw, str) or not raw:
        raise ObjectiveOverrideError(f"{REVIEW_FIELD} is blank.")
    lines = raw.splitlines()
    if not lines or lines[0] != "NEEDS REVISION":
        first = lines[0] if lines else ""
        raise ObjectiveOverrideError(
            f"{REVIEW_FIELD} must begin with an exact NEEDS REVISION line; got {first!r}."
        )
    trailers = [match for line in lines if (match := _TRAILER_RE.fullmatch(line))]
    reviewed_version_lines = [line for line in lines if line.startswith("Reviewed-Version:")]
    if len(reviewed_version_lines) != 1 or len(trailers) != 1:
        raise ObjectiveOverrideError(
            f"{REVIEW_FIELD} must contain exactly one well-formed {REQUIREMENTS_SLUG} "
            "Reviewed-Version trailer."
        )
    trailer = trailers[0]
    reviewed = {"v": int(trailer.group(1)), "sha256": trailer.group(2)}
    if reviewed != version:
        raise ObjectiveOverrideError(
            f"{REVIEW_FIELD} is stale: reviewed {REQUIREMENTS_SLUG}@v{reviewed['v']} "
            f"sha256:{reviewed['sha256']}, current is {REQUIREMENTS_SLUG}@v{version['v']} "
            f"sha256:{version['sha256']}."
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
