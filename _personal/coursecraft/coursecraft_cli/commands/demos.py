"""Demos command module."""
import json
from enum import Enum
from functools import lru_cache
import typer
from typing import Optional, List, Dict, Union
from pathlib import Path

from cli_tools_shared.filters import apply_limit
from cli_tools_shared.output import command
from ..batch import load_batch_payload
from ..client import get_client, ClientError
from ..coursecraft_project import (
    load_coursecraft_module,
    resolve_course_folder,
    run_coursecraft_script,
    script_flags,
)
from ..dependency_graph_display import SLUG_DISPLAY_NAMES, connected_artifacts, find_demo_intro_slide, load_router
from ..output import apply_properties_filter, project_record, print_success, print_error, print_info, print_json, print_table, print_mandatory_review
from ..filter_translator import translate_filters
from ..field_mappings import collect_mapped_updates, validate_field
from ..voice_recording_fields import (
    DICTATION_RECORDED_FIELD,
    VOICE_SOURCE_HASH_FIELD,
    get_demo_voice_recording_invalidation_fields,
)
from .voice_recordings import _load_canonical_script_contract, validate_manual_demo_narration

app = typer.Typer(help="Manage demo records")


class DemoExecutionMethod(str, Enum):
    """Allowed values for the Demos 'Execution Method' single-select field."""
    AUTOMATED_WALKTHROUGH = "Automated Walkthrough"
    MANUAL_INSTRUCTOR = "Manual Instructor"
    MANUAL_STEP_THROUGH = "Manual Step-Through"


class DemoEnvironment(str, Enum):
    """Allowed values for the Demos 'Demo Environment' single-select field."""
    LOCAL_MACOS = "Local - macOS"
    LINUX_DOCKER = "Linux - Docker"


class DemoProofState(str, Enum):
    """Allowed values for the Demos 'Proof State' single-select field.

    A projection of the fleet lane-state registry
    (``.agents/skills/demo-execute/scripts/coursecraft_demo_fleet/lane-states.json``
    in the CourseCraft checkout): the member values are its ``state`` column in
    file order, which is also the Airtable choice order. The registry's own
    tests pin this class to that file, so a reorder or rename is a deliberate
    three-home change (registry, Airtable choices, this enum).
    """
    QUEUED = "Queued"
    SEALING = "Sealing"
    REVIEW_REQUIRED = "Review Required"
    SEALED = "Sealed"
    REPAIR_PAUSED = "Repair Paused"
    PROVISIONING = "Provisioning"
    WALKING = "Walking"
    HELD = "Held"
    PUBLISHING = "Publishing"
    MEDIA_REVIEW_REQUIRED = "Media Review Required"
    WALK_PROOF_COMPLETE = "Walk Proof Complete"
    CANDIDATE_VALID = "Candidate Valid"
    RECORDING_APPROVAL_REQUIRED = "Recording Approval Required"
    FINAL_VIDEO_REGISTERED = "Final Video Registered"
    HAND_BACK = "Hand-back"
    FAILED = "Failed"


class RecordingDictationMethod(str, Enum):
    """Allowed values for the Demos 'Recording Dictation Method' single-select field."""
    INSTRUCTOR = "Manual Instructor Generation"
    AUTOMATIC = "Automatic Narration Generation"


DICTATION_METHOD_HELP = (
    "How this demo's narration is produced: 'Manual Instructor Generation' "
    "(Adam reads the Demo Script) or 'Automatic Narration Generation' "
    "(ElevenLabs generates it). Set per demo -- it is the only level that "
    "carries this field."
)


EXECUTION_METHOD_HELP = (
    "Demo execution method: decides ONLY the shape of the final recording "
    "phase. The demo.action_summary host walk (screenshots, click-log, "
    "manifest) is mandatory and runs in full for every demo regardless of "
    "this value. 'Automated Walkthrough' (agent builds and captures the "
    "walkthrough with synthetic narration), 'Manual Instructor' (instructor "
    "records live over the same proven walkthrough), or 'Manual Step-Through' "
    "(instructor drives the proven walkthrough.json step by step in the "
    "CourseCraft app while narration and host screen record together)."
)


DEMO_ENVIRONMENT_HELP = (
    "Compute surface this demo runs on: 'Local - macOS' (the shared macOS demo "
    "host) or 'Linux - Docker' (the demo gets its own Linux container). This is "
    "the compute surface only -- Azure and other cloud resources are a resource "
    "dimension of the Environment Spec, never a value here."
)


PROOF_STATE_HELP = (
    "Fleet lane state of this demo's automated proof, written by demo-fleet at "
    "every transition. The choices are the lane-state registry's states in "
    "registry order."
)
DEMO_LENGTH_FIELD = "Target Length (Min)"
WALKTHROUGH_TEST_COMPLETE_FIELD = validate_field("walkthrough_test_complete", "Demos")

# Walkthrough Test Complete attests to a walk that ran on the demo host. That walk binds to the
# Action Summary's ordered <action>/<expect> cue sequence only, so the walk
# contract -- not a whole-field text compare -- decides whether an Action Summary
# edit invalidates it. The contract has one home in the CourseCraft checkout.
WALK_CONTRACT_RELATIVE_PATH = Path(
    ".agents/skills/demo/artifacts/action_summary/tools/walk_contract.py"
)
WALKTHROUGH_NAME = "walkthrough.json"
EXECUTABLE_CUES_HASH_KEY = "executableCuesSha256"

# The one standard manual export name, declared in course-pipeline/SKILL.md. Adam saves
# every manual demo edit under it, so a manual take's path is a function of Folder Root
# alone and is never stored on the Demo record.
MANUAL_TAKE_FILENAME = "voiceover.edited.wav"
DEMO_PROOF_WRAPPER = ".agents/skills/demo-execute/scripts/demo-fleet"
CANDIDATE_AUDIT_TIMEOUT_SECONDS = 600


def _review_host_action(router: dict, change_token: str) -> str:
    """Return the active CourseCraft host action for one source change."""
    try:
        impact = router["automated_walkthrough_policy"]["review_impact_map"][change_token]
        host_action = impact["hostAction"]
    except (KeyError, TypeError):
        raise ClientError(f"UNMAPPED_REVIEW_DELTA: {change_token}") from None
    if not isinstance(host_action, str) or not host_action:
        raise ClientError(f"UNMAPPED_REVIEW_DELTA: {change_token}.hostAction")
    return host_action


@lru_cache(maxsize=1)
def _load_walk_contract():
    """Load CourseCraft's sole owner of the executable-cue hash."""
    return load_coursecraft_module(WALK_CONTRACT_RELATIVE_PATH, "coursecraft_cli_walk_contract")


def _walk_invalidation_reason(action_summary: str, folder_root: Optional[str]) -> str:
    """Why this Action Summary edit invalidates the proven walk, or "" if it does not.

    Author direction -- ``<explain ...>``, ``<observe ...>``, ``<wait ...>`` -- and
    the ``## Goal`` prose drive no host step, so rewording them re-proves the
    identical sequence and must keep Walkthrough Test Complete. Anything the CLI cannot compare
    against a proven walk clears the flag, which is the fail-closed side.

    Only the INCOMING Action Summary is validated. The proven walk is prior state
    read solely to tell a re-proving edit from an invalidating one, so a walk this
    CLI cannot read is a missing comparison basis, not a failure of this write --
    refusing there let a stale artifact veto an Action Summary edit and made the
    demo permanently unwritable. Reading the file is separate from interpreting
    it: an OSError still raises, because a Drive placeholder that will not open is
    a real error, while only the file's own deterministic JSON violation becomes a
    reason.
    """
    if not isinstance(folder_root, str) or not folder_root.strip():
        return "the Action Summary changed and the demo has no Folder Root, so no proven walk could be read"

    walkthrough_path = resolve_course_folder(folder_root) / WALKTHROUGH_NAME
    if not walkthrough_path.is_file():
        return f"the Action Summary changed and there is no proven walk at {walkthrough_path}"

    raw_walk = walkthrough_path.read_text(encoding="utf-8")
    try:
        walk = json.loads(raw_walk)
    except json.JSONDecodeError as error:
        return (
            f"the Action Summary changed and the proven walk at {walkthrough_path} "
            f"is not valid JSON ({error}), so its cue sequence could not be read"
        )
    stored_hash = walk.get(EXECUTABLE_CUES_HASH_KEY) if isinstance(walk, dict) else None
    if not stored_hash:
        return (
            f"the Action Summary changed and {walkthrough_path} records no "
            f"{EXECUTABLE_CUES_HASH_KEY}"
        )

    contract = _load_walk_contract()
    try:
        live_hash = contract.executable_cues_sha256(action_summary)
    except contract.WalkContractError as error:
        return f"the Action Summary changed and its executable cues do not parse: {error}"

    if live_hash == stored_hash:
        return ""
    return (
        "the Action Summary's executable cues changed "
        f"(walk {stored_hash[:12]}, live {live_hash[:12]})"
    )


def _classify_script_change(
    existing_script: object, candidate_script: str
) -> tuple[bool, bool, str]:
    """Classify one Script edit: narration changed, ordered cues changed, and why the
    stored Script could not be compared ("" when it was compared).

    Only the CANDIDATE is validated. Its parse runs first and unguarded, so a malformed
    incoming Script still stops the write -- that is the contract this command enforces.

    The stored value is parsed for one reason only: to tell a content change from a
    formatting one, so an edit that leaves the normalized narration and the ordered
    manifest cues identical keeps the recorded take and the proven walk. That comparison
    needs a parsed prior, and a Script written under an older contract cannot supply one.
    That is a missing comparison basis, not a failure of this write -- refusing there let
    the value being REPLACED veto its own replacement and made such a record permanently
    unwritable. With no comparable prior nothing can be shown unchanged, so both flags
    stay set and every downstream consequence applies, exactly as for a demo that has no
    Script at all. Only the contract's own deterministic violation is handled here; any
    other failure of the contract module still raises.
    """
    contract = _load_canonical_script_contract()
    candidate = contract.parse_script(candidate_script)
    no_comparison = (True, bool(candidate.cues))
    if not isinstance(existing_script, str) or not existing_script.strip():
        return (*no_comparison, "")

    try:
        existing = contract.parse_script(existing_script)
    except contract.ScriptContractError as error:
        return (
            *no_comparison,
            "the stored Script does not parse under the current Script contract "
            f"({error}), so nothing in it could be compared against the new one",
        )

    narration_changed = (
        candidate.normalized_narration_sha256
        != existing.normalized_narration_sha256
    )
    existing_cues = tuple(
        cue.text
        for cue in existing.cues
        if cue.opener not in contract.NON_MANIFEST_CUE_OPENERS
    )
    candidate_cues = tuple(
        cue.text
        for cue in candidate.cues
        if cue.opener not in contract.NON_MANIFEST_CUE_OPENERS
    )
    # The stored Script parsed and was compared, so there is no
    # missing-comparison reason. This third element is not optional: the
    # annotation, the docstring, both early returns above, and the sole caller's
    # three-name unpack all require it.
    return narration_changed, candidate_cues != existing_cues, ""


def _manual_demo_take(existing_fields: dict) -> Path:
    """Derive the manual narration take for one demo from its Folder Root.

    Manual Instructor Generation has exactly one standard export location, so the
    take's path is derived here and never read from the Demo record. The path stays
    lexical, matching the ``/Users/adam/courses/...`` form the folder is written in.
    """
    folder_root = existing_fields.get("Folder Root")
    if not isinstance(folder_root, str) or not folder_root.strip():
        raise ValueError(
            "--preserve-manual-voice-recording requires the demo's Folder Root to "
            "derive its manual take."
        )
    return resolve_course_folder(folder_root) / MANUAL_TAKE_FILENAME


def _verify_manual_voice_recording_preservation(existing_fields: dict, script: str) -> dict:
    """Prove the derived manual take still speaks a changed Script."""
    if existing_fields.get("Recording Dictation Method") != RecordingDictationMethod.INSTRUCTOR.value:
        raise ValueError(
            "--preserve-manual-voice-recording requires Recording Dictation Method "
            "to be Manual Instructor Generation."
        )
    if existing_fields.get(DICTATION_RECORDED_FIELD) is not True:
        raise ValueError(
            "--preserve-manual-voice-recording requires the existing manual take "
            "to have Dictation Recorded set."
        )
    if existing_fields.get(VOICE_SOURCE_HASH_FIELD) not in (None, ""):
        raise ValueError(
            "--preserve-manual-voice-recording cannot preserve a generated take "
            "with Voice Source Hash metadata."
        )

    voice_path = _manual_demo_take(existing_fields)
    if not voice_path.is_file() or voice_path.stat().st_size <= 0:
        raise ValueError(
            "--preserve-manual-voice-recording requires a non-empty manual take at "
            f"{voice_path}"
        )

    return validate_manual_demo_narration(existing_fields, script, voice_path)


def _create_one_demo(
    client,
    clip: str,
    *,
    name: Optional[str] = None,
    clip_order: Optional[int] = None,
    target_length: Optional[float] = None,
    learner_takeaway: Optional[str] = None,
    demo_overview: Optional[str] = None,
    action_summary: Optional[str] = None,
    script: Optional[str] = None,
    execution_method: Optional[Union[str, DemoExecutionMethod]] = None,
    recording_dictation_method: Optional[Union[str, RecordingDictationMethod]] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Create one demo, refusing a name that already exists in the clip.

    ``execution_method`` takes the Typer enum in single mode and the raw JSON
    string in batch mode; both are validated through ``DemoExecutionMethod``.
    """
    if name:
        existing_id = client.check_demo_exists(name, clip)
        if existing_id:
            print_error(f"Demo with name '{name}' already exists in this clip: {existing_id}")
            raise typer.Exit(1)

    fields: Dict = {
        "Clip": [clip],
        **collect_mapped_updates(
            "Demos",
            {
                "clip_order": clip_order,
                "name": name or None,
                "target_length": target_length,
                "learner_takeaway": learner_takeaway,
                "demo_overview": demo_overview,
                "action_summary": action_summary,
                "script": script,
                "execution_method": (
                    DemoExecutionMethod(execution_method).value
                    if execution_method is not None
                    else None
                ),
                "recording_dictation_method": (
                    RecordingDictationMethod(recording_dictation_method).value
                    if recording_dictation_method is not None
                    else None
                ),
                "notes": notes,
            },
        ),
    }

    record_id = client.create_record("Demos", fields)
    print_success(f"Created demo '{name if name else 'demo'}': {record_id}")
    return record_id


@app.command("create")
@command
def create_demo(
    clip: str = typer.Option(..., "--clip", "-c", help="Clip record ID (required)"),
    clip_order: int = typer.Option(..., "--clip-order", "-o", help="Order within the clip (required, e.g., 1, 2, 3)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Demo name"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 2.5)"),
    learner_takeaway: Optional[str] = typer.Option(None, "--learner-takeaway", help="One-sentence transferable capability the demo proves"),
    demo_overview: Optional[str] = typer.Option(None, "--demo-overview", help="High-level instructional overview for the demo"),
    action_summary: Optional[str] = typer.Option(None, "--action-summary", "-a", help="Action summary for the demo"),
    script: Optional[str] = typer.Option(None, "--script", "-s", help="Demo script"),
    execution_method: Optional[DemoExecutionMethod] = typer.Option(None, "--execution-method", help=EXECUTION_METHOD_HELP),
    recording_dictation_method: RecordingDictationMethod = typer.Option(RecordingDictationMethod.INSTRUCTOR, "--recording-dictation-method", help=DICTATION_METHOD_HELP),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    demos_json: Optional[str] = typer.Option(None, "--json", help="Inline JSON array of demos (batch mode)"),
    demos_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with demo definitions"),
):
    """
    Create demo record(s) in Airtable linked to a clip.

    Supports two modes:
    1. Single demo mode: Use optional fields to create one demo
    2. Batch mode: Use --json or --file to create multiple demos

    The --clip-order is required and specifies the position of the demo within the clip,
    alongside slides which also have a clip order.

    In batch mode the per-demo JSON keys "name", "clip_order", "target_length",
    "demo_overview", "action_summary", "script", "execution_method", and
    "notes" set each demo's values. Every one of those keys except "name"
    falls back to the matching CLI option when the key is absent, so
    --clip-order, --target-length, --demo-overview, --action-summary, --script,
    --execution-method, and --notes act as per-demo defaults. --name is
    never a batch default: two demos in one clip cannot share a name.

    Examples:
        # Single demo
        coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo"

        # Set the execution method
        coursecraft demos create --clip recXXX --clip-order 1 --name "Setup Demo" --execution-method "Manual Instructor"

        # Batch from inline JSON (clip_order required in each object)
        coursecraft demos create --clip recXXX --clip-order 1 --json '[{"name":"Demo 1","clip_order":1},{"name":"Demo 2","clip_order":2}]'

        # Batch from file
        coursecraft demos create --clip recXXX --clip-order 1 --file demos.json
    """
    try:
        client = get_client()

        # Determine mode: batch or single
        if demos_file or demos_json:
            # Batch mode
            demos_list = load_batch_payload(demos_json, demos_file)

            print_info(f"Creating {len(demos_list)} demo(s)...")

            created_ids = []
            for demo_data in demos_list:
                created_ids.append(
                    _create_one_demo(
                        client,
                        clip,
                        # --name is not a batch default; each demo names its own
                        name=demo_data.get("name"),
                        clip_order=demo_data.get("clip_order", clip_order),
                        target_length=demo_data.get("target_length", target_length),
                        learner_takeaway=demo_data.get("learner_takeaway", learner_takeaway),
                        demo_overview=demo_data.get("demo_overview", demo_overview),
                        action_summary=demo_data.get("action_summary", action_summary),
                        script=demo_data.get("script", script),
                        execution_method=demo_data.get("execution_method", execution_method),
                        recording_dictation_method=demo_data.get("recording_dictation_method", recording_dictation_method),
                        notes=demo_data.get("notes", notes),
                    )
                )

            # Output all created IDs as JSON array for scripting
            typer.echo(json.dumps(created_ids))
        else:
            # Single demo mode
            record_id = _create_one_demo(
                client,
                clip,
                name=name,
                clip_order=clip_order,
                target_length=target_length,
                learner_takeaway=learner_takeaway,
                demo_overview=demo_overview,
                action_summary=action_summary,
                script=script,
                execution_method=execution_method,
                recording_dictation_method=recording_dictation_method,
                notes=notes,
            )

            # Output the record ID for scripting
            typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
@command
def list_demos(
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Filter by clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by module record ID (gets all demos in module)"),
    course: Optional[str] = typer.Option(None, "--course", help="Filter by course slug or record ID (gets all demos in course)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List demo records.

    Examples:
        # List all demos
        coursecraft demos list

        # List demos for a clip
        coursecraft demos list --clip recXXX

        # List demos for a module (all clips in module)
        coursecraft demos list --module recXXX

        # List demos for a course (all demos in course)
        coursecraft demos list --course advanced-features-cursor-ai

        # List with standard filter
        coursecraft demos list --filter "status:eq:Complete"

        # Filter by the Demo ID field
        coursecraft demos list --filter "id:eq:69"

        # Filter by name pattern
        coursecraft demos list --filter "name:startswith:M1"
        coursecraft demos list --filter "name:contains:Setup"

        # Combine a convenience option with --filter (AND-ed together)
        coursecraft demos list --course advanced-features-cursor-ai --filter "name:contains:Setup"

        # List with table output
        coursecraft demos list --clip recXXX --table

        # Limit results
        coursecraft demos list --limit 5

        # Select specific properties
        coursecraft demos list --properties "id,fields.Name,fields.Status"
    """
    try:
        client = get_client()

        # Count how many convenience options are used
        convenience_options = sum(1 for opt in [clip, module, course] if opt is not None)
        if convenience_options > 1:
            print_error("Cannot use multiple convenience options (--clip, --module, --course) together")
            raise typer.Exit(1)

        # --filter combines with a convenience option (AND-ed together), the
        # same pattern list_modules uses for --course + --filter.
        filter_formula = translate_filters(list(filter), 'Demos') if filter else None

        # Get records based on filter type
        if course:
            # Hierarchical query: get all demos in course, optionally AND-ed with --filter
            records = client.get_demos_by_course(course, filter_formula=filter_formula)
        elif module:
            # Hierarchical query: get all demos in module, optionally AND-ed with --filter
            records = client.get_demos_by_module(module, filter_formula=filter_formula)
        elif clip:
            formula = f"{{Clip Record ID}}='{clip}'"
            if filter_formula:
                formula = f"AND({formula},{filter_formula})"
            records = client.list_records("Demos", formula)
        elif filter:
            records = client.list_records("Demos", filter_formula)
        else:
            records = client.list_records("Demos", None)

        # Apply limit
        records = apply_limit(records, limit)

        # Apply properties filter for JSON output
        if properties and not table_output:
            records = apply_properties_filter(records, properties)

        if table_output:
            # Format for table display
            rows = []
            for rec in records:
                fields = rec.get("fields", {})
                rows.append({
                    "id": rec["id"],
                    "name": fields.get("Name", ""),
                    "status": fields.get("Status", ""),
                })
            print_table(rows, ["id", "name", "status"],
                       ["Record ID", "Name", "Status"])
        else:
            print_json(records)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
@command
def get_demo(
    record_id: str = typer.Argument(..., help="Demo record ID"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single demo record by ID.

    Examples:
        coursecraft demos get recXXXXXXXXXXXXXXX
        coursecraft demos get recXXXXXXXXXXXXXXX --properties "id,fields.Name"
        coursecraft demos get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()
        record = client.get_record("Demos", record_id)

        if not record:
            print_error(f"Demo not found: {record_id}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = project_record(record, properties)

        if table_output:
            fields = record.get("fields", {})
            action_summary = fields.get("Action Summary", "")
            rows = [{
                "id": record["id"],
                "name": fields.get("Name", ""),
                "status": fields.get("Status", ""),
                "action_summary": action_summary[:40] + "..." if action_summary and len(action_summary) > 40 else action_summary,
            }]
            print_table(rows, ["id", "name", "status", "action_summary"],
                       ["Record ID", "Name", "Status", "Action Summary"])
        else:
            print_json(record)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("audit-candidate")
@command
def audit_candidate(
    record_id: str = typer.Argument(..., help="Demo record ID"),
):
    """Audit the current demo recording candidate and its proof lifecycle.

    The CourseCraft proof package owns every audit rule and the concise JSON
    result. This command only resolves the demo's current Folder Root and
    dispatches that supported audit path.
    """
    client = get_client()
    record = client.get_record("Demos", record_id)
    if not record:
        raise ClientError(f"Demo not found: {record_id}")

    folder_root = record.get("fields", {}).get("Folder Root")
    if not isinstance(folder_root, str) or not folder_root.strip():
        raise ClientError(f"Demo has no Folder Root: {record_id}")

    args = ["audit-candidate", *script_flags([
        ("--demo-record-id", record_id),
        ("--folder-root", resolve_course_folder(folder_root)),
    ])]
    raise typer.Exit(
        run_coursecraft_script(
            DEMO_PROOF_WRAPPER,
            args,
            timeout=CANDIDATE_AUDIT_TIMEOUT_SECONDS,
            interpreter=["bash"],
        )
    )


@app.command("update")
@command
def update_demo(
    record_id: str = typer.Argument(..., help="Demo record ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Demo name"),
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Re-parent the demo to this clip record ID; pass \"\" to unlink the demo from its clip"),
    clip_order: Optional[int] = typer.Option(None, "--clip-order", "-o", help="Order within the clip (e.g., 1, 2, 3)"),
    target_length: Optional[float] = typer.Option(None, "--target-length", "-l", help="Target length in minutes (e.g., 2.5)"),
    learner_takeaway: Optional[str] = typer.Option(None, "--learner-takeaway", help="One-sentence transferable capability the demo proves"),
    learner_takeaway_review_ai: Optional[str] = typer.Option(None, "--learner-takeaway-review-ai", help="AI review of the learner takeaway"),
    demo_overview: Optional[str] = typer.Option(None, "--demo-overview", help="High-level instructional overview for the demo"),
    demo_overview_review_ai: Optional[str] = typer.Option(None, "--demo-overview-review-ai", help="AI review of the demo overview"),
    demo_overview_review_human: Optional[bool] = typer.Option(None, "--demo-overview-review-human/--no-demo-overview-review-human", help="Mark demo overview human review as complete"),
    environment_spec: Optional[str] = typer.Option(None, "--environment-spec", help="Declarative environment spec (WHAT the demo environment must be) for the demo"),
    environment_spec_review_ai: Optional[str] = typer.Option(None, "--environment-spec-review-ai", help="AI review of the environment spec"),
    environment_prep_review_ai: Optional[str] = typer.Option(None, "--environment-prep-review-ai", help="AI review of the environment prep"),
    execution_method: Optional[DemoExecutionMethod] = typer.Option(None, "--execution-method", help=EXECUTION_METHOD_HELP),
    proof_state: Optional[DemoProofState] = typer.Option(None, "--proof-state", help=PROOF_STATE_HELP),
    demo_environment: Optional[DemoEnvironment] = typer.Option(None, "--demo-environment", help=DEMO_ENVIRONMENT_HELP),
    recording_dictation_method: Optional[RecordingDictationMethod] = typer.Option(None, "--recording-dictation-method", help=DICTATION_METHOD_HELP),
    action_summary: Optional[str] = typer.Option(None, "--action-summary", "-a", help="Action summary"),
    action_summary_review_ai: Optional[str] = typer.Option(None, "--action-summary-review-ai", help="AI review of the action summary"),
    action_summary_review_human: Optional[bool] = typer.Option(None, "--action-summary-review-human/--no-action-summary-review-human", help="Mark action summary human review as complete"),
    walkthrough_test_complete: Optional[bool] = typer.Option(None, "--walkthrough-test-complete/--no-walkthrough-test-complete", help="Mark the demo's walkthrough test complete after a full automated walkthrough is confirmed correct"),
    script: Optional[str] = typer.Option(None, "--script", "-s", help="Demo script"),
    preserve_manual_voice_recording: bool = typer.Option(False, "--preserve-manual-voice-recording", help="Keep a verified registered manual voice take after a changed script"),
    script_review_ai: Optional[str] = typer.Option(None, "--script-review-ai", help="AI review of the demo script"),
    script_review_human: Optional[bool] = typer.Option(None, "--script-review-human/--no-script-review-human", help="Mark script human review as complete"),
    recording_review_human: Optional[bool] = typer.Option(None, "--recording-review-human/--no-recording-review-human", help="Set or clear the demo recording human-review flag"),
    dictation_recorded: Optional[bool] = typer.Option(None, "--dictation-recorded/--no-dictation-recorded", help="Mark demo dictation audio as recorded"),
    recorded: Optional[bool] = typer.Option(None, "--recorded/--no-recorded", help="Mark demo as recorded"),
    audio_synced: Optional[bool] = typer.Option(None, "--audio-synced/--no-audio-synced", help="Mark demo narration audio as synced onto the recorded video"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    feedback_requested: Optional[bool] = typer.Option(None, "--feedback-requested/--no-feedback-requested", help="Set or clear the feedback-requested gate flag"),
    feedback_requested_at: Optional[str] = typer.Option(None, "--feedback-requested-at", help="ISO 8601 timestamp the feedback gate was requested"),
    estimated_length: Optional[float] = typer.Option(None, "--estimated-length", help="Estimated demo length in minutes"),
    notes_to_llm: Optional[str] = typer.Option(None, "--notes-to-llm", help="Demo authoring notes addressed to the model"),
    demo_review_complete: Optional[bool] = typer.Option(None, "--demo-review-complete/--no-demo-review-complete", help="Set or clear the demo review-complete flag"),
    demo_edited: Optional[bool] = typer.Option(None, "--demo-edited/--no-demo-edited", help="Set or clear the demo edited flag"),
    base_record: Optional[str] = typer.Option(None, "--base-record", help="Course-update lineage: the demo in the base course version this record derives from"),
):
    """
    Update a demo record.

    Examples:
        coursecraft demos update recXXX --name "New Name"
        coursecraft demos update recXXX --clip recCLIPID
        coursecraft demos update recXXX --clip ""  # unlink the demo from its clip
        coursecraft demos update recXXX --clip-order 2
        coursecraft demos update recXXX --action-summary "Step-by-step demo flow..."
        coursecraft demos update recXXX --demo-overview "High-level demo plan..."
        coursecraft demos update recXXX --execution-method "Automated Walkthrough"
        coursecraft demos update recXXX --proof-state "Walking"
        coursecraft demos update recXXX --demo-environment "Linux - Docker"
        coursecraft demos update recXXX --demo-overview-review-human
        coursecraft demos update recXXX --action-summary-review-human
        coursecraft demos update recXXX --walkthrough-test-complete
        coursecraft demos update recXXX --dictation-recorded
        coursecraft demos update recXXX --script "Corrected narration" --preserve-manual-voice-recording
        coursecraft demos update recXXX --audio-synced

    Changing --demo-overview, --action-summary, --script, --learner-takeaway,
    or --environment-spec to a value that differs from what is already saved
    bumps that slug's Version Control entry and auto-clears its paired
    "... Review (AI)" field (a no-op resubmission of identical content leaves
    it untouched, and passing that paired review field explicitly in the same
    call as a real content change is rejected) -- see the
    coursecraft_cli.artifact_versions write-time versioning engine. A changed
    --learner-takeaway never touches Walkthrough Test Complete.

    A changed Script always clears Audio Synced and Recorded. A normalized spoken-text
    change also clears voice metadata unless --preserve-manual-voice-recording is set.
    That option requires Manual Instructor Generation, a non-empty manual take at the
    derived <Folder Root>/voiceover.edited.wav, Dictation Recorded, no Voice Source
    Hash, and fresh canonical-narration transcript recall plus action-cue checks. It
    cannot be combined with --dictation-recorded.

    Only the Script being WRITTEN is validated against the Script contract. When the
    Script being REPLACED predates that contract and no longer parses, there is no
    comparison basis, so the edit counts as a full narration and cue change and prints a
    notice naming that reason. A legacy stored value never blocks a valid new Script.

    Walkthrough Test Complete is auto-cleared only when the active CourseCraft
    review-impact contract requires a host walk. Cue-aware Action Summary and
    Script changes also require an executable-cue change. The CLI
    compares the new Action Summary's executable-cue hash against
    executableCuesSha256 in the demo folder's walkthrough.json, so rewording an
    <explain>/<observe>/<wait> author cue or the "## Goal" prose keeps Walkthrough Test Complete.
    With no readable walkthrough.json, any Action Summary change clears it. Each
    auto-clear prints a notice naming the reason.

    Setting --demo-overview, --environment-spec, --action-summary, or --script
    prints a MANDATORY REVIEW banner for every other artifact CourseCraft's
    dependency graph (course-pipeline.json) connects to the changed field --
    same-cluster siblings, direct dependents, and their downstream cascade --
    except an artifact that is itself being edited in this same call. This
    replaces a fixed set of pairwise checks, so a Script edit also flags the
    Demo Intro Slide and Environment Spec, not just the Action Summary, and an
    Environment Spec edit flags the Environment Prep Script.
    """
    try:
        client = get_client()

        # Verify record exists
        existing = client.get_record("Demos", record_id)
        if not existing:
            print_error(f"Demo not found: {record_id}")
            raise typer.Exit(1)

        existing_fields = existing.get("fields", {})

        def _content_changed(new_value: Optional[str], field_name: str) -> bool:
            if new_value is None:
                return False
            return new_value.strip() != (existing_fields.get(field_name) or "").strip()

        # A field only counts as "changed" when it differs from what is already
        # persisted; a no-op resubmission of identical content must not clear
        # Walkthrough Test Complete below. (Paired review-flag auto-clear and
        # its mutual-exclusion rejection are now owned by the write-time
        # versioning engine in client.py -- coursecraft_cli.artifact_versions.)
        demo_overview_changed = _content_changed(demo_overview, "Demo Overview")
        environment_spec_changed = _content_changed(environment_spec, "Environment Spec")
        action_summary_changed = _content_changed(action_summary, "Action Summary")
        script_changed = _content_changed(script, "Script")
        script_narration_changed = False
        script_cues_changed = False
        script_no_comparison_reason = ""
        if script_changed:
            (
                script_narration_changed,
                script_cues_changed,
                script_no_comparison_reason,
            ) = _classify_script_change(existing_fields.get("Script"), script)

        if preserve_manual_voice_recording:
            if script is None or not script_changed:
                print_error(
                    "--preserve-manual-voice-recording requires a changed --script."
                )
                raise typer.Exit(1)
            if dictation_recorded is not None:
                print_error(
                    "--preserve-manual-voice-recording cannot be combined with "
                    "--dictation-recorded."
                )
                raise typer.Exit(1)
            _verify_manual_voice_recording_preservation(existing_fields, script)

        if script_changed and (audio_synced is True or recorded is True):
            print_error(
                "A changed --script clears Audio Synced and Recorded. Set those "
                "fields only after the new render is complete."
            )
            raise typer.Exit(1)
        if (
            script_narration_changed
            and not preserve_manual_voice_recording
            and dictation_recorded is True
        ):
            print_error(
                "A normalized narration change clears Dictation Recorded. Record "
                "the new narration before setting that field."
            )
            raise typer.Exit(1)

        # The demo-cluster artifacts this command can write: pipeline slug ->
        # (Airtable field, this call's new value). Single source of truth for
        # every "which cluster artifacts is this call writing?" question below
        # -- whether the review router must be loaded, which slugs seed the
        # dependency-graph reminders, which reminder targets are suppressed
        # because this same call already writes them, and which stored field
        # supplies a target's preview. All of those are derived from this one
        # registry so a newly writable artifact cannot be silently dropped
        # from one of them.
        demo_cluster_writes: Dict[str, tuple] = {
            "demo.overview": ("Demo Overview", demo_overview),
            "demo.environment_spec": ("Environment Spec", environment_spec),
            "demo.action_summary": ("Action Summary", action_summary),
            "demo.script": ("Script", script),
        }
        written_by_slug = {
            slug: value is not None for slug, (_field, value) in demo_cluster_writes.items()
        }

        # CourseCraft's active review-impact contract decides which source
        # changes require another host walk. The cue-aware actions still use
        # their canonical contracts to decide whether executable cues changed.
        review_router = load_router() if any(written_by_slug.values()) else None
        invalidation_reasons: List[str] = []
        for changed, token, reason in (
            (demo_overview_changed, "overview", "the Demo Overview changed"),
            (environment_spec_changed, "environment_spec", "the Environment Spec changed"),
        ):
            if changed and _review_host_action(review_router, token) == "walk":
                invalidation_reasons.append(reason)
        if action_summary_changed:
            cue_reason = _walk_invalidation_reason(action_summary, existing_fields.get("Folder Root"))
            if (
                cue_reason
                and _review_host_action(review_router, "action_summary_executable")
                == "walk"
            ):
                invalidation_reasons.append(cue_reason)
        if script_cues_changed and _review_host_action(
            review_router, "script_cue"
        ) in {"walk", "walk-if-executable-cue-changed"}:
            if script_no_comparison_reason:
                invalidation_reasons.append(script_no_comparison_reason)
            else:
                invalidation_reasons.append("the Script's ordered cues changed")

        walkthrough_test_complete_invalidated = bool(invalidation_reasons)
        if walkthrough_test_complete_invalidated and walkthrough_test_complete is not None:
            print_error(
                "Cannot set Walkthrough Test Complete in the same update as a change that "
                "invalidates the proven walk (" + "; ".join(invalidation_reasons) + "). "
                "Update the content first, verify it, then run a separate "
                "update with --walkthrough-test-complete."
            )
            raise typer.Exit(1)

        # Walkthrough Test Complete is written ONLY when this update intends to change it: an
        # invalidating change clears it, an explicit --walkthrough-test-complete/--no-walkthrough-test-complete
        # sets it. It is never re-derived from existing_fields -- that read can
        # be stale (another machine may have finalized the demo since), and
        # re-writing it would silently clobber the newer remote value.
        walkthrough_test_complete_write: Optional[bool] = False if walkthrough_test_complete_invalidated else walkthrough_test_complete

        # Map ordinary scalar options once. Linked-record writes and lifecycle
        # invalidation remain explicit below.
        fields = collect_mapped_updates(
            "Demos",
            {
                "name": name,
                "clip_order": clip_order,
                "target_length": target_length,
                "learner_takeaway": learner_takeaway,
                "learner_takeaway_review_ai": learner_takeaway_review_ai,
                "demo_overview": demo_overview,
                "demo_overview_review_ai": demo_overview_review_ai,
                "demo_overview_review_human": demo_overview_review_human,
                "environment_spec": environment_spec,
                "environment_spec_review_ai": environment_spec_review_ai,
                "environment_prep_review_ai": environment_prep_review_ai,
                "execution_method": execution_method.value if execution_method is not None else None,
                "proof_state": proof_state.value if proof_state is not None else None,
                "demo_environment": demo_environment.value if demo_environment is not None else None,
                "recording_dictation_method": (
                    recording_dictation_method.value
                    if recording_dictation_method is not None
                    else None
                ),
                "action_summary": action_summary,
                "action_summary_review_ai": action_summary_review_ai,
                "action_summary_review_human": action_summary_review_human,
                "walkthrough_test_complete": walkthrough_test_complete_write,
                "script": script,
                "script_review_ai": script_review_ai,
                "script_review_human": script_review_human,
                "recording_review_human": recording_review_human,
                "dictation_recorded": dictation_recorded,
                "recorded": recorded,
                "audio_synced": audio_synced,
                "notes": notes,
                "feedback_requested": feedback_requested,
                "feedback_requested_at": feedback_requested_at,
                "estimated_length": estimated_length,
                "notes_to_llm": notes_to_llm,
                "demo_review_complete": demo_review_complete,
                "demo_edited": demo_edited,
            },
        )
        if clip is not None:
            # An empty string is the explicit "unlink" sentinel: send an empty
            # linked-record array instead of a single-element list containing
            # "", which Airtable rejects as an invalid record ID.
            fields["Clip"] = [clip] if clip else []
        if script is not None:
            if script_narration_changed and not preserve_manual_voice_recording:
                fields.update(get_demo_voice_recording_invalidation_fields())
        # Audio Synced/Recorded invalidation stays command-side: it is
        # recording-state invalidation, not a "... Review (AI)"/human-verified
        # pair the write-time versioning engine's consequence engine resolves
        # from course-pipeline.json, so the engine has no data-driven way to
        # own it.
        if script_changed:
            fields["Audio Synced"] = False
            fields["Recorded"] = False
        if base_record is not None:
            fields["Base Record"] = [base_record]

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        # Update the record
        client.update_record("Demos", record_id, fields)
        print_success(f"Updated demo: {record_id}")

        if script_no_comparison_reason:
            print_info(
                "⚠️  Treated the Script edit as a full narration and cue change because "
                + script_no_comparison_reason
                + "."
            )

        if preserve_manual_voice_recording:
            print_info(
                "Preserved the registered manual voice take after fresh transcript proof."
            )

        if walkthrough_test_complete_invalidated:
            print_info(
                "⚠️  Cleared Walkthrough Test Complete because " + "; ".join(invalidation_reasons) + "."
            )
            print_info("   Re-run the walk, then finalize the demo again.")

        # Dependency-graph review reminders. course-pipeline.json's
        # `connected_artifacts` graph -- not a fixed set of pairwise checks --
        # decides which other artifacts might now be stale: same-cluster
        # siblings, artifacts built directly from the changed field, and the
        # rest of the downstream cascade. A target is skipped when it is one
        # of the fields this same call is already writing (including the
        # changed field itself), or when it falls outside the demo-cluster
        # slugs this banner knows how to display.
        changed_slugs = [slug for slug, written in written_by_slug.items() if written]

        if changed_slugs:
            changed_names = ", ".join(SLUG_DISPLAY_NAMES[slug] for slug in changed_slugs)
            written_slugs = set(changed_slugs)
            connected = connected_artifacts(written_slugs, review_router)

            ordered_targets: List[str] = []
            target_bucket: Dict[str, str] = {}
            for bucket in ("siblings", "direct", "cascade"):
                for slug in changed_slugs:
                    for target in connected.get(slug, {}).get(bucket, []):
                        if (
                            target in target_bucket
                            or target in written_slugs
                            or target not in SLUG_DISPLAY_NAMES
                        ):
                            continue
                        target_bucket[target] = bucket
                        ordered_targets.append(target)

            demo_intro_slide = None
            if "slide.demo_intro" in ordered_targets:
                demo_intro_slide = find_demo_intro_slide(client, record_id)

            for target in ordered_targets:
                display = SLUG_DISPLAY_NAMES[target]
                is_sibling = target_bucket[target] == "siblings"

                if target == "slide.demo_intro":
                    if demo_intro_slide is None:
                        continue
                    preview = demo_intro_slide.get("fields", {}).get("Script")
                elif target in demo_cluster_writes:
                    preview = existing_fields.get(demo_cluster_writes[target][0], "")
                else:
                    # demo.environment_prep_script (file-based, not an Airtable
                    # field), demo.dictation_audio, demo.automated_walkthrough.
                    preview = None

                if is_sibling:
                    action = f"Verify the {display} still matches the updated {changed_names}"
                    reason = (
                        f"{changed_names} changed - {display} shares this demo's "
                        f"consistency cluster and must remain consistent with it"
                    )
                else:
                    action = f"Re-check the {display} after this {changed_names} update"
                    reason = f"{changed_names} changed - {display} is built from it and may now be stale"

                print_mandatory_review(
                    title=display,
                    action=action,
                    reason=reason,
                    preview=preview,
                )

        # Workflow sequence warnings. These effective values are display-only --
        # they never reach the write payload above.
        effective_walkthrough_test_complete = (
            walkthrough_test_complete_write
            if walkthrough_test_complete_write is not None
            else existing_fields.get(WALKTHROUGH_TEST_COMPLETE_FIELD, False)
        )
        effective_action_summary_reviewed = fields.get(
            "Action Summary Human Verified",
            existing_fields.get("Action Summary Human Verified", False),
        )

        if recorded and not effective_walkthrough_test_complete:
            print_info("")
            print_info("⚠️  WARNING: Demo has not been marked as Walkthrough Test Complete.")
            print_info("   Complete and confirm the automated walkthrough before recording.")

        if script_review_human and not effective_action_summary_reviewed:
            print_info("")
            print_info("⚠️  WARNING: Action Summary human review is not complete.")
            print_info("   The Script is derived from the Action Summary - consider reviewing that first.")

        # Output the record ID as JSON for machine consumers.
        print_json(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
@command
def delete_demo(
    record_id: str = typer.Argument(..., help="Demo record ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a demo record.

    This action is PERMANENT and cannot be undone.

    Examples:
        # Delete with confirmation prompt
        coursecraft demos delete recXXXXXXXXXXXXXXX

        # Delete without confirmation (for scripting)
        coursecraft demos delete recXXXXXXXXXXXXXXX --force
    """
    try:
        client = get_client()

        # Verify record exists
        record = client.get_record("Demos", record_id)
        if not record:
            print_error(f"Demo not found: {record_id}")
            raise typer.Exit(1)

        demo_name = record.get("fields", {}).get("Name", record_id)

        # Confirm deletion
        if not force:
            if not typer.confirm(f"Are you sure you want to delete demo '{demo_name}'?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        # Delete the record
        client.delete_record("Demos", record_id)
        print_success(f"Deleted demo: {record_id}")

        # Output the deleted ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "audit-candidate": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
