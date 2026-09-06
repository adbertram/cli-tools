"""CourseCraft artifact-versioning sync/backfill command.

The write-time versioning engine (``coursecraft_cli.artifact_versions``,
wired into ``client.py``'s ``create_record``/``update_record``) is the live
source of truth for Airtable-content Version Control entries going forward.
This command is the one-time/idempotent catch-up path for two things that
chokepoint cannot cover:

* Airtable-content slugs written before the engine existed have real content
  but no Version Control entry yet -- ``sync`` seeds those (never overwrites
  an entry that already exists; the live chokepoint owns updates).
* File-kind artifacts (dictation audio, environment prep scripts, promoted
  walkthrough videos) are never written through ``client.py`` at all --
  ``sync`` is the SOLE registrar that hashes them off disk and records
  new/changed files. Adam's manual file replacements (e.g. a re-edited
  ``voiceover.edited.wav``) are picked up the next time this runs.
"""
COMMAND_CREDENTIALS = {
    "reconcile": ["custom"],
    # Pure introspection of this module's own resolver table: no Airtable
    # client, no network, no credentials -- the framework's coverage gate runs
    # it offline.
    "registrars": ["no_auth"],
    "register-module-deck": ["custom"],
    "sync": ["custom"],
}

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple

import typer

from cli_tools_shared.output import command
from ..client import get_client, ClientError
from ..coursecraft_project import resolve_course_folder
from ..field_mappings import FIELD_MAPPINGS, validate_field
from ..output import print_error, print_json, print_success
from ..artifact_versions import VersioningError, coverage_map, now_iso, canonical_hash
from ..external_review import (
    ExternalReviewError,
    lifecycle_lock,
    plan_transition,
    transition_record,
    version_evidence,
)
from ..objective_override import AUDIT_FIELD, STATE_FIELD, ObjectiveOverrideError
from ..human_verification import human_verification_index

app = typer.Typer(help="Sync CourseCraft artifact Version Control entries", no_args_is_help=True)

# Confirmed on-disk conventions this command derives file paths from (see the
# course-pipeline skill's v3-field-assignment.md and SKILL.md). Three
# coverage-map file-kind slugs are NOT registered by this command.
# `slide.narration` (the per-slide take) and `clip.recording` (the promoted
# clip MP4) are open gaps rather than settled design: both paths derive from
# the parent Module's `Module Folder Root` plus the module/clip orders
# `_walk_course` already carries -- the very inputs the promoted demo MP4
# filename below is built from -- so neither is waiting on a folder-root field
# of its own. Registering them is a design decision that has not been made.
# `update.review` is deliberate and permanent: a review report's durable
# evidence is its verdict field plus the `Reviewed-Version:` trailer citing the
# REVIEWED artifact's ledger entry, so the report file carries no entry of its
# own. coverage-map.json's `version_registration` block is the authority on all
# three.
ENV_PREP_SCRIPT_FILENAME = "env_prep.ps1"
# Compiled per-demo declaration for the proof fleet (host class + cask tokens).
# Authored on disk by an agent and never written through the CLI, so this
# command is its only registrar -- exactly like the prep script above.
HOST_REQUIREMENTS_FILENAME = "host-requirements.json"
AUTOMATIC_DICTATION_FILENAME = "voiceover.wav"
MANUAL_DICTATION_FILENAME = "voiceover.edited.wav"
MANUAL_INSTRUCTOR_METHOD = "Manual Instructor Generation"
AUTOMATED_WALKTHROUGH_EXECUTION_METHOD = "Automated Walkthrough"
MODULE_DECK_APPROVED_FILENAME_TEMPLATE = "m{order}_vcp_approved.pptx"
MODULE_DECK_RAW_FILENAME_TEMPLATE = "m{order}_raw.pptx"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _existing_version_control(fields: Dict[str, Any], table: str, record_id: str) -> Dict[str, Any]:
    raw = fields.get(validate_field("version_control", table)) or "{}"
    try:
        decoded = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise ClientError(
            f"{table} record {record_id!r}: Version Control field is not valid JSON: {error}"
        ) from None
    if not isinstance(decoded, dict):
        raise ClientError(
            f"{table} record {record_id!r}: Version Control field must decode to a JSON "
            f"object, got {type(decoded).__name__}."
        )
    return decoded


def _require_sha256(value: str, option_name: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise ClientError(f"{option_name} must be exactly 64 lowercase hexadecimal characters.")


def _course_preservation_snapshot(
    fields: Dict[str, Any], content_fields: list[str]
) -> Dict[str, Any]:
    """Capture every content/lifecycle/review field this repair must preserve."""
    protected = set(content_fields)
    protected.update({AUDIT_FIELD, STATE_FIELD})
    protected.update(
        field
        for field in FIELD_MAPPINGS["Courses"].values()
        if (
            "Review" in field
            or field.endswith("Human Verified")
            or "Submitted Revision" in field
            or field.endswith("Submitted Date")
        )
    )
    protected.update(
        gate.field
        for gate in human_verification_index().by_id.values()
        if gate.table == "Courses"
    )
    return {field: fields.get(field) for field in sorted(protected)}


def _airtable_content_reconciliation(
    fields: Dict[str, Any],
    record_id: str,
    artifact_slug: str,
    expected_version: int,
    expected_old_ledger_sha: str,
    expected_live_content_sha: str,
) -> Dict[str, Any]:
    """Validate and plan one exact Course airtable-content ledger correction."""
    _require_sha256(expected_old_ledger_sha, "--expected-old-ledger-sha")
    _require_sha256(expected_live_content_sha, "--expected-live-content-sha")
    if expected_version < 1:
        raise ClientError("--expected-version must be a positive integer.")
    if expected_old_ledger_sha == expected_live_content_sha:
        raise ClientError("Expected old ledger SHA and live content SHA must differ.")

    artifact = coverage_map().get(artifact_slug)
    if not isinstance(artifact, dict):
        raise ClientError(f"Unknown CourseCraft artifact slug: {artifact_slug!r}.")
    if artifact.get("kind") != "airtable_content" or artifact.get("table") != "courses":
        raise ClientError(
            "versions reconcile only supports Course-owned airtable_content artifacts; "
            f"{artifact_slug!r} declares kind={artifact.get('kind')!r}, "
            f"table={artifact.get('table')!r}."
        )
    content_fields = artifact.get("content_fields")
    if (
        not isinstance(content_fields, list)
        or not content_fields
        or not all(isinstance(field, str) and field for field in content_fields)
    ):
        raise ClientError(f"{artifact_slug!r} has no valid content_fields contract.")

    ledger = _existing_version_control(fields, "Courses", record_id)
    entry = ledger.get(artifact_slug)
    if not isinstance(entry, dict):
        raise ClientError(f"Version Control has no object entry for {artifact_slug!r}.")
    actual_version = entry.get("v")
    if (
        not isinstance(actual_version, int)
        or isinstance(actual_version, bool)
        or actual_version < 1
    ):
        raise ClientError(
            f"{artifact_slug} ledger version must be a positive integer; "
            f"found {actual_version!r}."
        )
    if actual_version != expected_version:
        raise ClientError(
            f"{artifact_slug} ledger version mismatch: expected v{expected_version}, "
            f"found {actual_version!r}."
        )
    if entry.get("sha256") != expected_old_ledger_sha:
        raise ClientError(
            f"{artifact_slug} ledger SHA mismatch: expected {expected_old_ledger_sha}, "
            f"found {entry.get('sha256')!r}."
        )
    if not isinstance(entry.get("at"), str) or not entry["at"].strip():
        raise ClientError(f"{artifact_slug} ledger entry has no nonblank 'at' value.")

    actual_live_sha = canonical_hash(artifact_slug, fields)
    if actual_live_sha != expected_live_content_sha:
        raise ClientError(
            f"{artifact_slug} live content SHA mismatch: expected {expected_live_content_sha}, "
            f"found {actual_live_sha}."
        )
    corrected_entry = {**entry, "sha256": expected_live_content_sha}
    corrected_ledger = {**ledger, artifact_slug: corrected_entry}
    return {
        "ledger_before": ledger,
        "ledger_after": corrected_ledger,
        "entry_before": entry,
        "entry_after": corrected_entry,
        "preserved_fields": _course_preservation_snapshot(fields, content_fields),
    }


def _verify_reconciliation_readback(
    fields: Dict[str, Any],
    record_id: str,
    artifact_slug: str,
    plan: Dict[str, Any],
) -> None:
    actual_ledger = _existing_version_control(fields, "Courses", record_id)
    if actual_ledger != plan["ledger_after"]:
        raise ClientError(
            "Version Control readback differs from the exact one-entry reconciliation plan."
        )
    actual_preserved = {
        field: fields.get(field) for field in plan["preserved_fields"]
    }
    if actual_preserved != plan["preserved_fields"]:
        changed = sorted(
            field
            for field, before in plan["preserved_fields"].items()
            if actual_preserved.get(field) != before
        )
        raise ClientError(
            "Reconciliation changed protected content/lifecycle/review fields: "
            + ", ".join(changed)
        )
    before_entry = plan["entry_before"]
    after_entry = actual_ledger[artifact_slug]
    if after_entry.get("v") != before_entry.get("v") or after_entry.get("at") != before_entry.get("at"):
        raise ClientError("Reconciliation did not preserve the target entry's v and at values.")


@app.command("reconcile")
@command
def versions_reconcile(
    course: str = typer.Option(..., "--course", help="Course record ID or Course ID slug"),
    artifact_slug: str = typer.Option(
        ..., "--artifact-slug", help="Course-owned airtable_content artifact slug"
    ),
    expected_version: int = typer.Option(
        ..., "--expected-version", help="Exact positive ledger version that must remain unchanged"
    ),
    expected_old_ledger_sha: str = typer.Option(
        ..., "--expected-old-ledger-sha", help="Exact stale SHA currently stored in Version Control"
    ),
    expected_live_content_sha: str = typer.Option(
        ..., "--expected-live-content-sha", help="Exact SHA of the current persisted artifact content"
    ),
    check: bool = typer.Option(
        False, "--check", help="Verify the exact reconciliation is safe without writing"
    ),
):
    """Reconcile one stale Course airtable-content ledger SHA without bumping it."""
    try:
        client = get_client()
        record_id = client.resolve_course_id(course)

        def load_plan() -> Dict[str, Any]:
            before = client.get_record("Courses", record_id)
            if before is None:
                raise ClientError(f"Course not found: {record_id}")
            return _airtable_content_reconciliation(
                before.get("fields", {}),
                record_id,
                artifact_slug,
                expected_version,
                expected_old_ledger_sha,
                expected_live_content_sha,
            )

        if check:
            plan = load_plan()
            result = {
                "mode": "reconcile-airtable-content-ledger",
                "check": True,
                "safe": True,
                "changed": False,
                "course": record_id,
                "artifact_slug": artifact_slug,
                "version": expected_version,
                "old_ledger_sha256": expected_old_ledger_sha,
                "live_content_sha256": expected_live_content_sha,
                "preserved_at": plan["entry_before"]["at"],
            }
            print_json(result)
            return

        with lifecycle_lock(record_id):
            plan = load_plan()
            version_field = validate_field("version_control", "Courses")
            client.update_record(
                "Courses",
                record_id,
                {version_field: json.dumps(plan["ledger_after"], sort_keys=True)},
            )
            readback = client.get_record("Courses", record_id)
            if readback is None:
                raise ClientError(f"Course vanished after reconciliation: {record_id}")
            _verify_reconciliation_readback(
                readback.get("fields", {}), record_id, artifact_slug, plan
            )
            print_success(
                f"Reconciled {artifact_slug} Version Control SHA for {record_id}"
            )
            print_json({
                "mode": "reconcile-airtable-content-ledger",
                "check": False,
                "safe": True,
                "changed": True,
                "course": record_id,
                "artifact_slug": artifact_slug,
                "version": expected_version,
                "old_ledger_sha256": expected_old_ledger_sha,
                "live_content_sha256": expected_live_content_sha,
                "preserved_at": plan["entry_before"]["at"],
            })
    except (ClientError, ObjectiveOverrideError, VersioningError) as error:
        print_error(str(error))
        raise typer.Exit(1)


def _content_slugs_for_table(table_key: str) -> list:
    """coverage-map airtable_content slugs for one coverage-map table key.

    Skips a slug shared by more than one content field across slide types
    (the Slides table's Script/Build Instructions/Name) -- same "no data to
    disambiguate yet" gap as the write-time engine; see
    ``artifact_versions._resolve_slide_slug``.
    """
    slugs = []
    for slug, entry in coverage_map().items():
        if entry.get("kind") != "airtable_content" or entry.get("table") != table_key:
            continue
        slugs.append(slug)
    return slugs


def _seed_airtable_content(
    table: str, table_key: str, fields: Dict[str, Any], existing_vc: Dict[str, Any]
) -> Dict[str, Any]:
    """New Version Control entries for slugs with content but no entry yet."""
    seeded: Dict[str, Any] = {}
    if table_key == "slides":
        # Every Slides content slug shares a field with other slide types;
        # none is resolvable to one slug without Phase 2's slide_type data.
        return seeded
    for slug in _content_slugs_for_table(table_key):
        if slug in existing_vc:
            continue
        content_fields = coverage_map()[slug].get("content_fields", [])
        # Raw truthiness, matching canonical_hash's own `persisted.get(field)
        # or ""` -- a whitespace-only field is non-empty to canonical_hash,
        # so it must be non-empty to this "has real content" check too
        # (Finding 6). A `.strip()`-based check here disagreed with what the
        # live engine actually hashes, hiding whitespace-only drift from
        # `sync` entirely.
        if not any(fields.get(field) for field in content_fields):
            continue
        seeded[slug] = {"v": 1, "sha256": canonical_hash(slug, fields), "at": now_iso()}
    return seeded


def _register_file(
    slug: str, path: Path, existing_vc: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """A new-or-changed registration for one file slug, or ``None``."""
    if not path.is_file():
        return None
    new_hash = canonical_hash(slug, path)
    current = existing_vc.get(slug)
    current_hash = current.get("sha256") if isinstance(current, dict) else None
    if new_hash == current_hash:
        return None
    current_v = current.get("v", 0) if isinstance(current, dict) else 0
    return {
        "v": current_v + 1,
        "sha256": new_hash,
        "at": now_iso(),
        "path": str(path),
        "bytes": path.stat().st_size,
    }


def _demo_folder(fields: Dict[str, Any]) -> Optional[Path]:
    """The demo record's folder on disk, or ``None`` when it has no root yet."""
    folder_root = fields.get("Folder Root")
    if not isinstance(folder_root, str) or not folder_root.strip():
        return None
    return resolve_course_folder(folder_root)


def _environment_prep_script_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    folder = _demo_folder(fields)
    if folder is None:
        return None
    return folder / ENV_PREP_SCRIPT_FILENAME


def _host_requirements_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    folder = _demo_folder(fields)
    return None if folder is None else folder / HOST_REQUIREMENTS_FILENAME


def _dictation_audio_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    folder = _demo_folder(fields)
    if folder is None:
        return None
    filename = (
        MANUAL_DICTATION_FILENAME
        if fields.get("Recording Dictation Method") == MANUAL_INSTRUCTOR_METHOD
        else AUTOMATIC_DICTATION_FILENAME
    )
    return folder / filename


def _walkthrough_video_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    """The promoted final demo video, at ``<Folder Root>/m{M}c{C}-demo.mp4``."""
    folder = _demo_folder(fields)
    if folder is None or module_order is None or clip_order is None:
        return None
    return folder / f"m{module_order}c{clip_order}-demo.mp4"


def _automated_walkthrough_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    """The same video file, claimed only by the demo's own execution method."""
    if fields.get("Execution Method") != AUTOMATED_WALKTHROUGH_EXECUTION_METHOD:
        return None
    return _walkthrough_video_path(fields, module_order, clip_order)


def _manual_walkthrough_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    if fields.get("Execution Method") == AUTOMATED_WALKTHROUGH_EXECUTION_METHOD:
        return None
    return _walkthrough_video_path(fields, module_order, clip_order)


def _module_deck_path(fields: Dict[str, Any]) -> Optional[Path]:
    """Return the canonical raw or externally approved deck path for this state.

    ``Order`` must be a whole number (int/float with no fractional part, or an
    all-digit string) -- same requirement ``release-approved-deck.sh`` derives
    ``MODULE_ORDER`` under. Anything else means there is nothing safe to
    register yet.
    """
    folder_root = fields.get("Module Folder Root")
    if not isinstance(folder_root, str) or not folder_root.strip():
        return None
    order = fields.get("Order")
    if isinstance(order, (int, float)) and not isinstance(order, bool) and float(order).is_integer():
        order_str = str(int(order))
    elif isinstance(order, str) and order.isdigit():
        order_str = order
    else:
        return None
    folder = resolve_course_folder(folder_root)
    template = (
        MODULE_DECK_APPROVED_FILENAME_TEMPLATE
        if fields.get("Slide Deck Review State") == "Approved"
        else MODULE_DECK_RAW_FILENAME_TEMPLATE
    )
    return folder / "slides" / template.format(order=order_str)


def _module_powerpoint_deck_path(
    fields: Dict[str, Any], module_order: Any, clip_order: Any
) -> Optional[Path]:
    return _module_deck_path(fields)


# The ONE statement of which file-kind artifacts this command registers and
# where each one lives. `sync` iterates it to walk a record's files, and
# `registrars` emits its keys, so the command, its answer, and its help can
# never disagree the way a second hand-written list would -- `sync --help`
# already drifted from the code once, omitting a slug while it was being
# registered correctly. A resolver returns the record's path for its slug, or
# ``None`` when this record cannot own that artifact.
VERSIONS_SYNC_REGISTRAR = "versions_sync"
FILE_REGISTRARS: Dict[str, Dict[str, Any]] = {
    "demo.environment_prep_script": {
        "table": "Demos",
        "path": _environment_prep_script_path,
    },
    "demo.host_requirements": {"table": "Demos", "path": _host_requirements_path},
    "demo.dictation_audio": {"table": "Demos", "path": _dictation_audio_path},
    "demo.automated_walkthrough": {"table": "Demos", "path": _automated_walkthrough_path},
    "demo.manual_walkthrough": {"table": "Demos", "path": _manual_walkthrough_path},
    "module.powerpoint_deck": {"table": "Modules", "path": _module_powerpoint_deck_path},
}


def _seed_files(
    table: str,
    fields: Dict[str, Any],
    existing_vc: Dict[str, Any],
    module_order: Any,
    clip_order: Any,
) -> Dict[str, Any]:
    """New-or-changed file registrations for every slug this table owns."""
    updates: Dict[str, Any] = {}
    for slug, registrar in FILE_REGISTRARS.items():
        if registrar["table"] != table:
            continue
        path = registrar["path"](fields, module_order, clip_order)
        if path is None:
            continue
        registration = _register_file(slug, path, existing_vc)
        if registration is not None:
            updates[slug] = registration
    return updates


@app.command("registrars")
@command
def versions_registrars():
    """Report every file-kind artifact slug this CLI can register, by registrar.

    Pure introspection of the resolver table `versions sync` walks: no Airtable
    access, no network, no credentials -- the framework's validation-coverage
    gate reads this offline to check coverage-map.json's `version_registration`
    declarations in both directions.

    Examples:
        coursecraft versions registrars
    """
    print_json({VERSIONS_SYNC_REGISTRAR: sorted(FILE_REGISTRARS)})


def _deck_registration_consequences(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Invalidate stale deck review evidence in the same owner-record write."""
    human_field = human_verification_index().by_id["modules.powerpoint_deck"].field
    updates: Dict[str, Any] = {
        "PowerPoint Deck Review (AI)": "",
        human_field: False,
    }
    if fields.get("Slide Deck Review State") in {"Submitted", "Approved"}:
        updates["Slide Deck Review State"] = "Not Submitted"
        updates["Slide Deck Submitted Revision"] = ""
    return updates


def _validate_approved_module_deck(path: Optional[Path]) -> Path:
    """Validate the canonical returned deck candidate before registration."""
    if path is None or path.suffix.lower() != ".pptx" or not path.is_file():
        raise ExternalReviewError(
            f"Canonical approved module deck is not a .pptx file: {path}"
        )
    if path.stat().st_size <= 0:
        raise ExternalReviewError(f"Canonical approved module deck is empty: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "ppt/presentation.xml"}
            missing = sorted(required - names)
            if missing:
                raise ExternalReviewError(
                    "Canonical approved module deck is missing PPTX members: "
                    f"{', '.join(missing)}."
                )
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ExternalReviewError(
                    f"Canonical approved module deck has a corrupt member: {corrupt}."
                )
    except (OSError, zipfile.BadZipFile) as error:
        raise ExternalReviewError(
            f"Canonical approved module deck is not a readable PPTX archive: {path} ({error})"
        ) from None
    return path


def accept_approved_module_deck(
    client: Any,
    record_id: str,
    approval_evidence: str,
) -> Dict[str, Any]:
    """Atomically register and accept one returned approved module deck."""
    selected_evidence = approval_evidence.strip()
    if not selected_evidence:
        raise ExternalReviewError(
            "accept-approved-slide-deck requires nonblank --approval-evidence."
        )

    with lifecycle_lock(record_id):
        human_field = human_verification_index().by_id["modules.powerpoint_deck"].field
        before = transition_record(client, "slide_deck", record_id)
        fields = before["fields"]
        path = _validate_approved_module_deck(
            _module_deck_path({**fields, "Slide Deck Review State": "Approved"})
        )
        existing_vc = _existing_version_control(fields, "Modules", record_id)
        current = existing_vc.get("module.powerpoint_deck")
        current_version = current.get("v") if isinstance(current, dict) else None
        approved_digest = canonical_hash("module.powerpoint_deck", path)
        if (
            not isinstance(current_version, int)
            or isinstance(current_version, bool)
            or current_version < 1
        ):
            raise ExternalReviewError(
                "module.powerpoint_deck has no positive pre-release version."
            )
        if fields.get("Slide Deck Review State") == "Approved":
            current_revision = version_evidence("module.powerpoint_deck", current)
            recovery_matches = (
                current.get("sha256") == approved_digest
                and fields.get("Slide Deck Submitted Revision") == current_revision
                and fields.get("PowerPoint Deck Review (AI)") in (None, "")
                and fields.get(human_field) in (None, False)
            )
            if not recovery_matches:
                raise ExternalReviewError(
                    "Approved-deck recovery readback does not exactly match the canonical "
                    "approved deck, submitted revision, and invalidated review gates."
                )
            return {
                "mode": "accept-approved-slide-deck",
                "module": record_id,
                "approval_evidence": selected_evidence,
                "path": str(path),
                "version": current,
                "state": "Approved",
                "submitted_revision": current_revision,
                "powerpoint_deck_review_ai": None,
                "powerpoint_deck_human_verified": False,
                "recovered_after_verified_readback": True,
            }
        registration = {
            "v": current_version + 1,
            "sha256": approved_digest,
            "at": now_iso(),
            "path": str(path),
            "bytes": path.stat().st_size,
        }
        returned_revision = version_evidence("module.powerpoint_deck", registration)
        transition_updates = plan_transition(
            "slide_deck",
            "accept_approved_revision",
            "approved_deck_release_workflow",
            before,
            returned_revision=returned_revision,
            approval_evidence=selected_evidence,
            returned_candidate_validated=True,
        )
        version_field = validate_field("version_control", "Modules")
        merged = {**existing_vc, "module.powerpoint_deck": registration}
        updates = {
            version_field: json.dumps(merged, sort_keys=True),
            **transition_updates,
        }
        atomic_fields = {
            version_field,
            "Slide Deck Review State",
            "Slide Deck Submitted Revision",
            "PowerPoint Deck Review (AI)",
            human_field,
        }
        if not atomic_fields.issubset(updates):
            missing = ", ".join(sorted(atomic_fields - updates.keys()))
            raise ExternalReviewError(
                f"Approved-deck atomic update is missing contract fields: {missing}."
            )

        persisted = client.update_record("Modules", record_id, updates)
        after = transition_record(client, "slide_deck", record_id)
        persisted_fields = persisted.get("fields", {})
        persisted_vc = _existing_version_control(
            persisted_fields, "Modules", record_id
        )
        if persisted_vc.get("module.powerpoint_deck") != registration:
            raise ExternalReviewError(
                "Approved module deck Version Control readback does not match the registered revision."
            )
        if (
            after["fields"].get("Slide Deck Review State") != "Approved"
            or after["fields"].get("Slide Deck Submitted Revision")
            != returned_revision
            or after["current_revision"] != returned_revision
        ):
            raise ExternalReviewError(
                "Approved module deck lifecycle readback does not match the returned revision."
            )
        if persisted_fields.get("PowerPoint Deck Review (AI)") not in (None, ""):
            raise ExternalReviewError(
                "PowerPoint Deck Review (AI) was not cleared after approved-deck acceptance."
            )
        if persisted_fields.get(human_field) not in (None, False):
            raise ExternalReviewError(
                f"{human_field} must remain false after approved-deck acceptance."
            )

        return {
            "mode": "accept-approved-slide-deck",
            "module": record_id,
            "approval_evidence": selected_evidence,
            "path": str(path),
            "version": registration,
            "state": "Approved",
            "submitted_revision": returned_revision,
            "powerpoint_deck_review_ai": None,
            "powerpoint_deck_human_verified": False,
            "recovered_after_verified_readback": False,
        }


@app.command("register-module-deck")
@command
def versions_register_module_deck(
    module: str = typer.Argument(..., help="Module record ID, ID pattern, or name"),
):
    """Register the canonical raw deck and atomically invalidate stale review evidence."""
    try:
        client = get_client()
        record_id = client.resolve_module_id(module)
        with lifecycle_lock(record_id):
            record = client.get_record("Modules", record_id)
            if not record:
                raise ClientError(f"Module not found: {record_id}")
            fields = record.get("fields", {})
            path = _module_deck_path({**fields, "Slide Deck Review State": "Not Submitted"})
            if path is None or not path.is_file():
                raise ClientError(f"Canonical raw module deck not found: {path}")
            existing_vc = _existing_version_control(fields, "Modules", record_id)
            registration = _register_file("module.powerpoint_deck", path, existing_vc)
            if registration is None:
                print_json({
                    "mode": "register-module-deck",
                    "module": record_id,
                    "changed": False,
                    "path": str(path),
                    "version": existing_vc.get("module.powerpoint_deck"),
                })
                return
            merged = {**existing_vc, "module.powerpoint_deck": registration}
            version_field = validate_field("version_control", "Modules")
            updates = {
                version_field: json.dumps(merged, sort_keys=True),
                **_deck_registration_consequences(fields),
            }
            persisted = client.update_record("Modules", record_id, updates)
            print_success(f"Registered raw module deck for {record_id}")
            print_json({
                "mode": "register-module-deck",
                "module": record_id,
                "changed": True,
                "path": str(path),
                "version": registration,
                "state": persisted.get("fields", {}).get("Slide Deck Review State"),
            })
    except (ClientError, ExternalReviewError, VersioningError) as error:
        print_error(str(error))
        raise typer.Exit(1)


WalkItem = Tuple[str, Dict, Any, Any]


def _order(record: Dict) -> Any:
    return record.get("fields", {}).get("Order")


def _walk_clip(client, clip: Dict, module_order: Any) -> Iterator[WalkItem]:
    """Yield the clip, then its demos and slides."""
    yield ("Clips", clip, None, None)
    clip_order = _order(clip)
    for demo in client.get_demos_by_clip(clip["id"]):
        yield ("Demos", demo, module_order, clip_order)
    for slide in client.get_slides_by_clip(clip["id"]):
        yield ("Slides", slide, None, None)


def _walk_module(client, module: Dict) -> Iterator[WalkItem]:
    """Yield the module, then every clip subtree under it."""
    yield ("Modules", module, None, None)
    module_order = _order(module)
    for clip in client.get_clips_by_module(module["id"]):
        yield from _walk_clip(client, clip, module_order)


def _walk_course(client, course_record: Dict) -> Iterator[WalkItem]:
    """Yield (table, record, module_order, clip_order) for a course's tree.

    ``module_order``/``clip_order`` are ``None`` outside the Demos branch,
    where they are needed to derive the promoted-video filename.
    """
    yield ("Courses", course_record, None, None)
    for module in client.get_modules_by_course(course_record["id"]):
        yield from _walk_module(client, module)


# Record-scoped walks. One spec per scopable table: the CLI option that names
# it, the CLI field key of the lookup pointing at its parent (resolved through
# field_mappings, never a literal Airtable field name), and the parent table
# (``None`` ends the climb at Modules, whose parent lookup is the course). Each
# scope root is loaded by ID, climbed to its owning Module, and that Module's
# course must be the course being synced -- an unknown or out-of-course ID
# aborts the run before anything is walked or written.
class _ScopeSpec(NamedTuple):
    option: str
    parent_field: str
    parent_table: Optional[str]


_SCOPE: Dict[str, _ScopeSpec] = {
    "Modules": _ScopeSpec("--module", validate_field("course", "Modules"), None),
    "Clips": _ScopeSpec("--clip", validate_field("module", "Clips"), "Modules"),
    "Demos": _ScopeSpec("--demo", validate_field("clip", "Demos"), "Clips"),
    "Slides": _ScopeSpec("--slide", validate_field("clip", "Slides"), "Clips"),
}


def _parent_record_id(table: str, record: Dict) -> str:
    field = _SCOPE[table].parent_field
    value = record.get("fields", {}).get(field)
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, str) or not value.startswith("rec"):
        raise ClientError(
            f"{table} record {record['id']!r} has no usable {field!r} value "
            f"({value!r}); cannot place it in a course."
        )
    return value


def _scoped_record(client, table: str, record_id: str) -> Dict:
    record = client.get_record(table, record_id)
    if not record:
        raise ClientError(f"{table} record not found: {record_id}")
    return record


def _scope_roots(values_by_table: Dict[str, Optional[List[str]]]) -> List[Tuple[str, str]]:
    """(table, record_id) scope roots in ``_SCOPE`` order; ``[]`` when unscoped."""
    roots: List[Tuple[str, str]] = []
    for table, spec in _SCOPE.items():
        values = values_by_table[table]
        if values is None:
            continue
        for value in values:
            if not value.startswith("rec"):
                raise ClientError(f"{spec.option} expects a record ID (rec...), got {value!r}.")
            if (table, value) in roots:
                raise ClientError(f"{spec.option} {value} was given more than once.")
            roots.append((table, value))
    return roots


def _resolve_scope(
    client, course_record_id: str, roots: List[Tuple[str, str]]
) -> List[WalkItem]:
    """Load and course-check every scope root BEFORE anything is walked or written.

    Each root comes back as the same (table, record, module_order, clip_order)
    tuple ``_walk_course`` yields for it, so a later walk needs no re-fetch.
    """
    resolved: List[WalkItem] = []
    for table, record_id in roots:
        chain: Dict[str, Dict] = {table: _scoped_record(client, table, record_id)}
        chain_table = table
        while _SCOPE[chain_table].parent_table is not None:
            parent_table = _SCOPE[chain_table].parent_table
            chain[parent_table] = _scoped_record(
                client, parent_table, _parent_record_id(chain_table, chain[chain_table])
            )
            chain_table = parent_table
        owning_course = _parent_record_id("Modules", chain["Modules"])
        if owning_course != course_record_id:
            raise ClientError(
                f"{table} record {record_id} belongs to course {owning_course}, "
                f"not {course_record_id}."
            )
        module_order = _order(chain["Modules"]) if table in ("Clips", "Demos") else None
        clip_order = _order(chain["Clips"]) if table == "Demos" else None
        resolved.append((table, chain[table], module_order, clip_order))
    return resolved


def _walk_scope(client, resolved: List[WalkItem]) -> Iterator[WalkItem]:
    """Yield each resolved scope root's subtree."""
    for table, record, module_order, clip_order in resolved:
        if table == "Modules":
            yield from _walk_module(client, record)
        elif table == "Clips":
            yield from _walk_clip(client, record, module_order)
        else:
            yield (table, record, module_order, clip_order)


_TABLE_KEY = {
    "Courses": "courses",
    "Modules": "modules",
    "Clips": "clips",
    "Demos": "demos",
    "Slides": "slides",
}


@app.command("sync")
@command
def versions_sync(
    course: str = typer.Argument(..., help="CourseCraft course slug or record ID"),
    check: bool = typer.Option(
        False, "--check", help="Report drift (would-write entries) without writing anything"
    ),
    module: Optional[List[str]] = typer.Option(
        None, "--module", help="Restrict the walk to this module record ID's subtree (repeatable)"
    ),
    clip: Optional[List[str]] = typer.Option(
        None, "--clip", help="Restrict the walk to this clip record ID's subtree (repeatable)"
    ),
    demo: Optional[List[str]] = typer.Option(
        None, "--demo", help="Restrict the walk to this demo record ID (repeatable)"
    ),
    slide: Optional[List[str]] = typer.Option(
        None, "--slide", help="Restrict the walk to this slide record ID (repeatable)"
    ),
):
    """Idempotently seed missing content entries and register file artifacts.

    Walks Course -> Modules -> Clips -> Demos/Slides. For each record, seeds a
    Version Control entry for any coverage-map airtable_content slug that has
    non-empty content but no entry yet (never overwrites an existing entry --
    the write-time engine owns updates from here on), and registers new or
    changed files for every file-kind slug this command resolves a path for.
    Run `coursecraft versions registrars` for that exact set -- it is derived
    from the same resolver table this command walks, so it cannot drift from
    what is registered here.

    Any --module/--clip/--demo/--slide record ID restricts the walk to that
    record's subtree only (the Course record itself is not walked), so
    parallel workers can each sync their own record without registering a
    sibling's in-flight files. Every scope ID must exist and belong to the
    course, or the run aborts before writing anything.

    Examples:
        coursecraft versions sync my-course
        coursecraft versions sync my-course --check
        coursecraft versions sync my-course --demo recXXXXXXXXXXXXXX --check
        coursecraft versions sync my-course --clip recXXXXXXXXXXXXXX --demo recYYYYYYYYYYYYYY
    """
    try:
        client = get_client()
        course_record_id = client.resolve_course_id(course)
        course_record = client.get_record("Courses", course_record_id)
        if not course_record:
            print_error(f"Course not found: {course}")
            raise typer.Exit(1)

        roots = _scope_roots(
            {"Modules": module, "Clips": clip, "Demos": demo, "Slides": slide}
        )
        walk = (
            _walk_scope(client, _resolve_scope(client, course_record_id, roots))
            if roots
            else _walk_course(client, course_record)
        )

        report = []
        errors = []
        for table, record, module_order, clip_order in walk:
            record_id = record.get("id")
            try:
                fields = record.get("fields", {})
                table_key = _TABLE_KEY[table]
                existing_vc = _existing_version_control(fields, table, record_id)

                updates = _seed_airtable_content(table, table_key, fields, existing_vc)
                owner_consequences: Dict[str, Any] = {}
                file_updates = _seed_files(
                    table, fields, existing_vc, module_order, clip_order
                )
                updates.update(file_updates)
                if "module.powerpoint_deck" in file_updates:
                    owner_consequences.update(_deck_registration_consequences(fields))

                if not updates:
                    continue

                report.append(
                    {
                        "table": table,
                        "record_id": record_id,
                        "slugs": {slug: entry["v"] for slug, entry in updates.items()},
                    }
                )

                if not check:
                    merged = {**existing_vc, **updates}
                    version_field = validate_field("version_control", table)
                    client.update_record(
                        table,
                        record_id,
                        {
                            version_field: json.dumps(merged, sort_keys=True),
                            **owner_consequences,
                        },
                    )
            except (ClientError, VersioningError) as error:
                # One corrupt/unresolvable record must not abort the whole
                # course walk (Finding 5) -- record it and keep going. Every
                # other exception still propagates and aborts the run; this
                # is the ONE scoped catch-and-continue in this command.
                errors.append({"table": table, "record_id": record_id, "error": str(error)})
                print_error(f"{table} record {record_id}: {error}")

        result = {"synced": report, "errors": errors}
        if check:
            print_json(result)
        else:
            summary = (
                f"Synced {sum(len(r['slugs']) for r in report)} artifact version(s) "
                f"across {len(report)} record(s)."
            )
            if errors:
                summary = f"{summary} {len(errors)} record(s) failed -- see errors."
            print_success(summary)
            print_json(result)

        if errors:
            # A run with any per-record failure never reports as a clean
            # success, even though the successful records above already
            # persisted -- the caller must see that the run was partial.
            raise typer.Exit(1)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
