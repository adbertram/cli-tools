"""Fail-closed learning-objective override lifecycle for Pluralsight courses."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict

from .artifact_versions import canonical_hash, now_iso
from .coursecraft_project import coursecraft_project_root, resolve_course_folder


STATE_FIELD = "Learning Objectives Override State"
AUDIT_FIELD = "Learning Objectives Override Audit"
REVIEW_FIELD = "Course Requirements Review (AI)"
OUTLINE_REVIEW_FIELD = "Outline Draft Review (AI)"
REQUIREMENTS_FIELD = "Course Requirements"
OBJECTIVES_FIELD = "Learning Objectives"
CARRY_FORWARD_PLAN_FIELD = "Carry-Forward Plan"
VERSION_CONTROL_FIELD = "Version Control"
REQUIREMENTS_SLUG = "course.requirements"
OUTLINE_DRAFT_SLUG = "course.outline_draft"
OBJECTIVES_OVERRIDE_SLUG = "course.learning_objectives_override"
CARRY_FORWARD_PLAN_SLUG = "update.carry_forward_plan"
CARRY_FORWARD_REVIEW_FILENAME = "carry-forward-plan-review.md"

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
_CARRY_FORWARD_EVENT_TYPES = {
    "carry_forward_plan_migrated",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRAILER_RE = re.compile(
    r"^Reviewed-Version: course\.requirements@v([1-9][0-9]*) sha256:([0-9a-f]{64})$"
)


class ObjectiveOverrideError(ValueError):
    """The requested override transition failed a lifecycle gate."""


def _migration_resolution_binding() -> tuple[str, str, list[str]]:
    path = coursecraft_project_root() / "course-pipeline.json"
    try:
        lifecycle = json.loads(path.read_text(encoding="utf-8"))["artifact_lifecycle"]
        event = lifecycle["protocols"]["course_requirements_return"]["migration"][
            "resolution_write"
        ]["non_null_state"]["event"]
        event_type = event["type"]
        binding_key = event["state_binding_key"]
        required_keys = event["required_keys"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ObjectiveOverrideError(
            f"Cannot read course requirements migration audit contract from {path}: {error}"
        ) from None
    if (
        not isinstance(event_type, str)
        or not isinstance(binding_key, str)
        or not isinstance(required_keys, list)
        or not all(isinstance(key, str) for key in required_keys)
    ):
        raise ObjectiveOverrideError(
            "Course requirements migration audit binding is invalid."
        )
    return event_type, binding_key, required_keys


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
    state_events = [
        event for event in events if event.get("type") not in _CARRY_FORWARD_EVENT_TYPES
    ]
    if state_events:
        (
            migration_event_type,
            migration_state_key,
            migration_required_keys,
        ) = _migration_resolution_binding()
        last_event = state_events[-1]
        if last_event.get("type") == migration_event_type:
            authorities = last_event.get("authoritativeEvidence")
            valid_authorities = isinstance(authorities, list) and bool(authorities)
            if valid_authorities:
                valid_authorities = all(
                    isinstance(evidence, dict)
                    and set(evidence) == {"source", "locator", "sha256"}
                    and isinstance(evidence.get("source"), str)
                    and bool(evidence["source"].strip())
                    and isinstance(evidence.get("locator"), str)
                    and bool(evidence["locator"].strip())
                    and isinstance(evidence.get("sha256"), str)
                    and _SHA256_RE.fullmatch(evidence["sha256"]) is not None
                    for evidence in authorities
                )
            if (
                set(audit) != {"schemaVersion", "events"}
                or len(state_events) != 1
                or set(last_event) != set(migration_required_keys)
                or not isinstance(last_event.get("at"), str)
                or not last_event["at"].strip()
                or not isinstance(last_event.get("resolutionArtifactSha256"), str)
                or _SHA256_RE.fullmatch(last_event["resolutionArtifactSha256"])
                is None
                or not isinstance(last_event.get("baselineInputFingerprint"), str)
                or _SHA256_RE.fullmatch(last_event["baselineInputFingerprint"])
                is None
                or not isinstance(last_event.get("reason"), str)
                or not last_event["reason"].strip()
                or not valid_authorities
            ):
                raise ObjectiveOverrideError(
                    f"{AUDIT_FIELD} has an invalid migration-resolution audit document."
                )
            resulting_state = last_event.get(migration_state_key)
            normalized_state = state or None
            if resulting_state != normalized_state:
                raise ObjectiveOverrideError(
                    f"{STATE_FIELD} is {normalized_state!r}, but the migration-resolution "
                    f"audit binds it to {resulting_state!r}."
                )
            return state
    if not state:
        if state_events:
            raise ObjectiveOverrideError(
                f"{STATE_FIELD} is blank but {AUDIT_FIELD} contains lifecycle events."
            )
        return ""
    if not state_events:
        raise ObjectiveOverrideError(
            f"{STATE_FIELD} is {state!r} but {AUDIT_FIELD} contains no events."
        )
    event_type = state_events[-1].get("type")
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
    return current_artifact_version(fields, REQUIREMENTS_SLUG)


def current_artifact_version(fields: Dict[str, Any], slug: str) -> Dict[str, Any]:
    """Read and verify one current Airtable artifact version/hash."""
    version = artifact_version_entry(fields, slug)
    actual_digest = canonical_hash(slug, fields)
    if version["sha256"] != actual_digest:
        raise ObjectiveOverrideError(
            f"{slug} Version Control hash is stale: ledger={version['sha256']}, "
            f"current={actual_digest}. Run the version sync before continuing."
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


def current_json_artifact_version(
    fields: Dict[str, Any], slug: str, field: str
) -> Dict[str, Any]:
    """Verify a JSON text artifact while tolerating Airtable's terminal newline."""
    version = artifact_version_entry(fields, slug)
    raw = fields.get(field)
    if not isinstance(raw, str) or not raw.strip():
        raise ObjectiveOverrideError(f"{field} is blank.")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ObjectiveOverrideError(f"{field} is not valid JSON: {exc}") from None
    normalized = json.dumps(document, ensure_ascii=False, indent=2)
    current_hashes = {sha256_text(raw), sha256_text(normalized)}
    if version["sha256"] not in current_hashes:
        raise ObjectiveOverrideError(
            f"{slug} Version Control hash is stale: ledger={version['sha256']}, "
            f"current JSON hashes={sorted(current_hashes)}."
        )
    return version


def require_no_outline_revision(fields: Dict[str, Any]) -> None:
    """Require that no course.outline_draft revision or review exists yet."""
    if str(fields.get("Outline Draft") or "").strip():
        raise ObjectiveOverrideError(
            "Pre-outline Carry-Forward Plan repair is closed because Outline Draft is populated."
        )
    if str(fields.get(OUTLINE_REVIEW_FIELD) or "").strip():
        raise ObjectiveOverrideError(
            "Pre-outline Carry-Forward Plan repair is closed because Outline Draft Review (AI) is populated."
        )
    raw = fields.get(VERSION_CONTROL_FIELD)
    try:
        ledger = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ObjectiveOverrideError(
            f"{VERSION_CONTROL_FIELD} is not valid JSON: {exc}"
        ) from None
    if not isinstance(ledger, dict):
        raise ObjectiveOverrideError(f"{VERSION_CONTROL_FIELD} must decode to an object.")
    if OUTLINE_DRAFT_SLUG in ledger:
        raise ObjectiveOverrideError(
            "Pre-outline Carry-Forward Plan repair is closed because Version Control already "
            f"contains {OUTLINE_DRAFT_SLUG!r}."
        )


def require_current_pass_carry_forward_review(
    fields: Dict[str, Any], record_id: str, version: Dict[str, Any]
) -> Dict[str, str]:
    """Require the canonical PASS review file bound to the current live plan."""
    folder_root = fields.get("Course Folder Root")
    if not isinstance(folder_root, str) or not folder_root.strip():
        raise ObjectiveOverrideError("Course Folder Root is blank.")
    review_path = (
        resolve_course_folder(folder_root) / "reviews" / CARRY_FORWARD_REVIEW_FILENAME
    )
    if not review_path.is_file():
        raise ObjectiveOverrideError(f"Carry-Forward Plan review file is missing: {review_path}")
    try:
        review = review_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ObjectiveOverrideError(
            f"Could not read Carry-Forward Plan review file {review_path}: {exc}"
        ) from None
    lines = review.splitlines()
    expected_title_prefix = (
        f"# Review Report — {CARRY_FORWARD_PLAN_SLUG} — {record_id}:"
    )
    if not lines or not lines[0].startswith(expected_title_prefix):
        raise ObjectiveOverrideError(
            "Carry-Forward Plan review title is not bound to the selected course record."
        )
    if lines.count("**Reviewed Source:** Courses.Carry-Forward Plan") != 1:
        raise ObjectiveOverrideError(
            "Carry-Forward Plan review must name Courses.Carry-Forward Plan exactly once."
        )
    if lines.count("**Review Status:** PASS") != 1:
        raise ObjectiveOverrideError(
            "Carry-Forward Plan review must contain exactly one PASS status line."
        )
    identity = artifact_version_identity(CARRY_FORWARD_PLAN_SLUG, version)
    if lines.count(f"**Reviewed-Version:** {identity}") != 1:
        raise ObjectiveOverrideError(
            "Carry-Forward Plan review is not bound to the current live plan identity "
            f"{identity}."
        )
    return {"path": str(review_path), "sha256": sha256_text(review)}


def require_carry_forward_v2_migration(current: str, replacement: str) -> None:
    """Require deterministic title removal while migrating or repairing schema v2."""
    try:
        current_document = json.loads(current)
        replacement_document = json.loads(replacement)
    except json.JSONDecodeError as exc:
        raise ObjectiveOverrideError(f"Carry-Forward Plan is not valid JSON: {exc}") from None
    if not isinstance(current_document, dict) or not isinstance(replacement_document, dict):
        raise ObjectiveOverrideError("Carry-Forward Plan documents must be JSON objects.")
    source_schema = current_document.get("schemaVersion")
    if source_schema not in {1, 2}:
        raise ObjectiveOverrideError(
            "Carry-Forward Plan migration requires a schemaVersion 1 source or an incomplete "
            "schemaVersion 2 source with learner-facing verdict target titles."
        )
    if replacement_document.get("schemaVersion") != 2:
        raise ObjectiveOverrideError(
            "Carry-Forward Plan migration candidate must use schemaVersion 2."
        )

    if source_schema == 2:
        verdicts = current_document.get("verdicts")
        has_forbidden_verdict_title = isinstance(verdicts, dict) and any(
            isinstance(verdict, dict)
            and isinstance(verdict.get("target"), dict)
            and bool(set(verdict["target"]) & {"name", "title"})
            for verdict in verdicts.values()
        )
        if not has_forbidden_verdict_title:
            raise ObjectiveOverrideError(
                "schemaVersion 2 migration repair requires at least one forbidden "
                "verdicts.*.target.name/title key in the live source."
            )

    def require_identity(row: Dict[str, Any], path: str) -> None:
        if "base_record" not in row:
            raise ObjectiveOverrideError(
                f"{path} must contain base_record (a record ID or null for an addition)."
            )
        base_record = row["base_record"]
        addition_id = row.get("addition_id")
        if base_record is None:
            if not isinstance(addition_id, str) or not addition_id.strip():
                raise ObjectiveOverrideError(
                    f"{path} with base_record null must contain a non-empty addition_id."
                )
        elif not isinstance(base_record, str) or not base_record.strip():
            raise ObjectiveOverrideError(
                f"{path}.base_record must be a non-empty record ID or null."
            )
        elif "addition_id" in row:
            raise ObjectiveOverrideError(
                f"{path} with a base_record cannot contain addition_id."
            )

    def validate_v2_structure(structure: Any) -> list[Dict[str, Any]]:
        if not isinstance(structure, list) or not structure:
            raise ObjectiveOverrideError(
                "Migration candidate must contain a non-empty target_structure array."
            )
        for module_index, module in enumerate(structure):
            module_path = f"target_structure[{module_index}]"
            if not isinstance(module, dict):
                raise ObjectiveOverrideError(f"{module_path} must be an object.")
            require_identity(module, module_path)
            title_keys = sorted(set(module) & {"name", "title"})
            if title_keys:
                raise ObjectiveOverrideError(
                    f"{module_path} cannot contain {', '.join(title_keys)}. "
                    "Learner-facing names and titles belong to Course Outline Draft."
                )
            for required in ("module_order", "target_length_min", "verdict", "clips"):
                if required not in module:
                    raise ObjectiveOverrideError(f"{module_path} is missing {required!r}.")
            clips = module["clips"]
            if not isinstance(clips, list) or not clips:
                raise ObjectiveOverrideError(f"{module_path}.clips must be a non-empty array.")
            for clip_index, clip in enumerate(clips):
                clip_path = f"{module_path}.clips[{clip_index}]"
                if not isinstance(clip, dict):
                    raise ObjectiveOverrideError(f"{clip_path} must be an object.")
                require_identity(clip, clip_path)
                title_keys = sorted(set(clip) & {"name", "title"})
                if title_keys:
                    raise ObjectiveOverrideError(
                        f"{clip_path} cannot contain {', '.join(title_keys)}. "
                        "Learner-facing names and titles belong to Course Outline Draft."
                    )
                for required in ("clip_order", "target_length_min", "verdict"):
                    if required not in clip:
                        raise ObjectiveOverrideError(f"{clip_path} is missing {required!r}.")
        return structure

    target_structure = replacement_document.get("target_structure")
    validate_v2_structure(target_structure)

    source_structure = current_document.get("target_structure")
    if source_structure is not None:
        if not isinstance(source_structure, list) or not source_structure:
            raise ObjectiveOverrideError("schemaVersion 1 target_structure must be non-empty.")
        projected_structure = []
        for module_index, module in enumerate(source_structure):
            if not isinstance(module, dict):
                raise ObjectiveOverrideError(
                    f"schemaVersion 1 target_structure[{module_index}] must be an object."
                )
            projected_module = {
                key: value
                for key, value in module.items()
                if key not in {"name", "title", "clips"}
            }
            projected_module["clips"] = []
            clips = module.get("clips")
            if not isinstance(clips, list):
                raise ObjectiveOverrideError(
                    f"schemaVersion 1 target_structure[{module_index}].clips must be an array."
                )
            for clip in clips:
                if not isinstance(clip, dict):
                    raise ObjectiveOverrideError("schemaVersion 1 target_structure clip must be an object.")
                projected_clip = {
                    key: value
                    for key, value in clip.items()
                    if key not in {"name", "title"}
                }
                projected_module["clips"].append(projected_clip)
            projected_structure.append(projected_module)
        if target_structure != projected_structure:
            raise ObjectiveOverrideError(
                "schemaVersion 2 target_structure must be the exact structural projection of "
                "schemaVersion 1; titles cannot participate in migration."
            )

    source_without_structure = dict(current_document)
    source_without_structure.pop("target_structure", None)
    source_without_structure["schemaVersion"] = 2
    candidate_without_structure = dict(replacement_document)
    candidate_without_structure.pop("target_structure", None)

    source_verdicts = source_without_structure.get("verdicts")
    candidate_verdicts = candidate_without_structure.get("verdicts")
    if not isinstance(source_verdicts, dict) or not isinstance(candidate_verdicts, dict):
        raise ObjectiveOverrideError("Carry-Forward Plan verdicts must be objects.")
    normalized_source_verdicts = {}
    for record_id, verdict in source_verdicts.items():
        if not isinstance(verdict, dict):
            raise ObjectiveOverrideError(f"verdicts.{record_id} must be an object.")
        normalized_verdict = dict(verdict)
        target = verdict.get("target")
        if isinstance(target, dict):
            normalized_target = dict(target)
            normalized_target.pop("name", None)
            normalized_target.pop("title", None)
            normalized_verdict["target"] = normalized_target
        normalized_source_verdicts[record_id] = normalized_verdict
    for record_id, verdict in candidate_verdicts.items():
        if not isinstance(verdict, dict):
            raise ObjectiveOverrideError(f"verdicts.{record_id} must be an object.")
        target = verdict.get("target")
        if isinstance(target, dict):
            title_keys = sorted(set(target) & {"name", "title"})
            if title_keys:
                raise ObjectiveOverrideError(
                    f"verdicts.{record_id}.target cannot contain {', '.join(title_keys)}; "
                    "learner-facing titles belong to Course Outline Draft."
                )
    source_without_structure["verdicts"] = normalized_source_verdicts

    source_additions = source_without_structure.get("additions")
    candidate_additions = candidate_without_structure.get("additions")
    if not isinstance(source_additions, list) or not isinstance(candidate_additions, list):
        raise ObjectiveOverrideError("Carry-Forward Plan additions must be arrays.")
    if len(source_additions) != len(candidate_additions):
        raise ObjectiveOverrideError("Migration cannot add or remove additions.")
    for index, (source_addition, candidate_addition) in enumerate(
        zip(source_additions, candidate_additions)
    ):
        if not isinstance(source_addition, dict) or not isinstance(candidate_addition, dict):
            raise ObjectiveOverrideError(f"additions[{index}] must be an object.")
        if "name" in candidate_addition or "title" in candidate_addition:
            raise ObjectiveOverrideError(
                f"additions[{index}] cannot contain name/title; learner-facing titles belong "
                "to Course Outline Draft."
            )
        purpose = candidate_addition.get("planning_purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            raise ObjectiveOverrideError(
                f"additions[{index}].planning_purpose must be non-empty text."
            )
        legacy_labels = {
            source_addition[key]
            for key in ("name", "title")
            if isinstance(source_addition.get(key), str)
        }
        if purpose in legacy_labels:
            raise ObjectiveOverrideError(
                f"additions[{index}].planning_purpose cannot reuse the legacy "
                "learner-facing name/title."
            )
        normalized_source = dict(source_addition)
        normalized_source.pop("name", None)
        normalized_source.pop("title", None)
        normalized_source.pop("planning_purpose", None)
        normalized_candidate = dict(candidate_addition)
        normalized_candidate.pop("planning_purpose", None)
        if normalized_candidate != normalized_source:
            raise ObjectiveOverrideError(
                f"additions[{index}] may only replace legacy name/title with the reviewed "
                "non-editorial planning_purpose."
            )
    source_without_structure["additions"] = [
        {
            key: value
            for key, value in addition.items()
            if key not in {"name", "title", "planning_purpose"}
        }
        for addition in source_additions
    ]
    candidate_without_structure["additions"] = [
        {key: value for key, value in addition.items() if key != "planning_purpose"}
        for addition in candidate_additions
    ]
    if candidate_without_structure != source_without_structure:
        raise ObjectiveOverrideError(
            "Migration may only upgrade schemaVersion, remove learner-facing titles from "
            "verdict targets and additions, add planning_purpose, and migrate/add "
            "target_structure."
        )


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


def require_current_needs_revision_artifact_review(
    fields: Dict[str, Any], review_field: str, slug: str, version: Dict[str, Any]
) -> str:
    """Require one current NEEDS REVISION review bound to an artifact version."""
    raw = fields.get(review_field)
    if not isinstance(raw, str) or not raw:
        raise ObjectiveOverrideError(f"{review_field} is blank.")
    lines = raw.splitlines()
    if not lines or lines[0] != "NEEDS REVISION":
        first = lines[0] if lines else ""
        raise ObjectiveOverrideError(
            f"{review_field} must begin with an exact NEEDS REVISION line; got {first!r}."
        )
    expected = artifact_version_identity(slug, version)
    reviewed_version_lines = [line for line in lines if line.startswith("Reviewed-Version:")]
    if reviewed_version_lines != [f"Reviewed-Version: {expected}"]:
        raise ObjectiveOverrideError(
            f"{review_field} must contain exactly one current trailer "
            f"'Reviewed-Version: {expected}'."
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


def read_json_replacement(inline: str | None, file_value: str | None) -> str:
    """Require exactly one non-empty schemaVersion 2 JSON object."""
    if (inline is None) == (file_value is None):
        raise ObjectiveOverrideError(
            "Provide exactly one of --carry-forward-plan or --carry-forward-plan-file."
        )
    value = inline if inline is not None else file_value
    if value is None or not value.strip():
        raise ObjectiveOverrideError("Replacement Carry-Forward Plan cannot be blank.")
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ObjectiveOverrideError(f"Replacement Carry-Forward Plan is not valid JSON: {exc}") from None
    if not isinstance(document, dict) or document.get("schemaVersion") != 2:
        raise ObjectiveOverrideError(
            "Replacement Carry-Forward Plan must be a schemaVersion 2 JSON object."
        )
    return value


def version_identity(version: Dict[str, Any]) -> str:
    """Render the exact reviewed-version identity for output/audit."""
    return f"{REQUIREMENTS_SLUG}@v{version['v']} sha256:{version['sha256']}"


def artifact_version_identity(slug: str, version: Dict[str, Any]) -> str:
    """Render one exact artifact version identity."""
    return f"{slug}@v{version['v']} sha256:{version['sha256']}"
