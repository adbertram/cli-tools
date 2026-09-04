"""Feedback command module."""
import json
import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import typer
from typing import Optional, List, Tuple

from cli_tools_shared.filters import apply_limit
from cli_tools_shared.output import command
from ..client import get_client, ClientError
from ..coursecraft_project import (
    CourseCraftProjectError,
    coursecraft_project_root,
    python3_interpreter,
)
from ..output import apply_properties_filter, project_record, print_success, print_error, print_info, print_json, print_table, warn_policy
from ..filter_translator import translate_filters
from ..field_mappings import validate_field

app = typer.Typer(help="Manage feedback records")

TABLE_NAME = "Feedback"

DEMO_FIELD = "Demo"
SLIDE_FIELD = "Slide"
CLIP_FIELD = "Clip"
MODULE_FIELD = "Module"
COURSE_FIELD = "Course"
SOURCE_FIELD = validate_field("source", "Feedback")

# A Feedback row links to EXACTLY ONE element, and that link is what says which
# level the feedback is about. The Slides/Demos/Clips/Modules 'Open Feedback
# Count' rollups each sum the Feedback 'Is Open' formula over their own link, so
# a row carrying two links would drive two records into 'Edits Needed' for one
# piece of feedback. Ordered narrowest first for stable error messages.
ELEMENT_LINK_OPTIONS = (
    ("slide", SLIDE_FIELD),
    ("demo", DEMO_FIELD),
    ("clip", CLIP_FIELD),
    ("module", MODULE_FIELD),
    ("course", COURSE_FIELD),
)


def element_link_fields(**links: Optional[str]) -> dict:
    """Airtable field writes for the one element link, clearing every other level.

    Accepts the five link options by their CLI names. Returns {} when none was
    passed (leaving the record's existing link untouched), and raises when more
    than one was passed -- a row has one level, not several.
    """
    provided = [(name, field_name) for name, field_name in ELEMENT_LINK_OPTIONS
                if links.get(name) is not None]
    if not provided:
        return {}
    if len(provided) > 1:
        names = ", ".join(f"--{name}" for name, _ in provided)
        raise ValueError(
            f"A feedback row links to exactly one element; got {names}. "
            "Pass the single level the feedback is about."
        )
    chosen_name, chosen_field = provided[0]
    fields = {chosen_field: [links[chosen_name]]}
    for _, field_name in ELEMENT_LINK_OPTIONS:
        if field_name != chosen_field:
            fields[field_name] = []
    return fields

# The Processing Status value that asserts the feedback was actually remediated.
APPLIED_STATUS = "Applied"

SKILLS_ROOT_RELATIVE_PATH = Path(".agents/skills")
COVERAGE_GATE_RELATIVE_PATH = Path(".agents/skills/course-pipeline/tools/check_validation_coverage.py")
COVERAGE_GATE_TIMEOUT_SECONDS = 120

# Tables a record: claim may name, probed in this order. A claimed record ID
# carries no table, so each CourseCraft table is asked server-side whether it
# CONTAINS the record via a RECORD_ID() filter formula on the client's uncached
# list path. A get-by-id probe cannot resolve the table: Airtable's get-record
# endpoint returns the record even when the named table is a different table in
# the same base, so the first table probed would always "match".
CLAIM_TABLES = (
    "Slides",
    "Demos",
    "Clips",
    "Modules",
    "Courses",
    "Feedback",
    "Slide Templates",
)

CLAIM_FORMS_HELP = (
    "check:<dotted.check.id> | record:<recordId>:<Field>=<expected> | "
    "record:<recordId>:<Field>~=<substring>"
)


class ClaimVerificationError(Exception):
    """A --remediation-claim could not be verified, so nothing may be written."""


def _coursecraft_project_root() -> Path:
    """The CourseCraft project checkout a remediation claim is verified against.

    One resolver for the whole CLI (coursecraft_project). Its failure is
    re-raised as a ClaimVerificationError so a missing checkout still reads as
    "this claim cannot be verified" rather than as a generic CLI crash.
    """
    try:
        return coursecraft_project_root()
    except CourseCraftProjectError as exc:
        raise ClaimVerificationError(str(exc)) from exc


def _checks_json_contracts(skills_root: Path) -> List[Tuple[Path, str]]:
    """Every checks.json under the CourseCraft skills tree, with its owning slug.

    ``.agents/skills/<skill>`` entries are symlinks into the shared skills repo,
    and ``Path.rglob`` deliberately refuses to recurse into a symlinked
    directory, so each skill entry is resolved before it is walked. Without that
    resolution the walk finds nothing and every check id would look invented.
    The slug is relative to the SKILL ENTRY, never to ``skills_root`` -- a
    resolved contract path lives in the sibling skills repo and is not under the
    CourseCraft tree at all.

    The slug inverts the dotted-slug path rule: ``<skill>/artifacts/<a>/artifacts/<b>``
    is the contract for ``<skill>.<a>.<b>``.
    """
    contracts: List[Tuple[Path, str]] = []
    for entry in sorted(skills_root.iterdir()):
        target = entry.resolve()
        if not target.is_dir():
            continue
        for path in sorted(target.rglob("checks.json")):
            parts = path.parent.relative_to(target).parts
            slug = ".".join([entry.name, *(p for p in parts if p != "artifacts")])
            contracts.append((path, slug))
    return contracts


def _find_check_id_contract(check_id: str, skills_root: Path) -> Tuple[Path, str]:
    """The checks.json that declares ``check_id`` and its slug, or raise."""
    for path, slug in _checks_json_contracts(skills_root):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ClaimVerificationError(
                f"checks.json does not parse, so check ids cannot be verified: {path} ({exc})"
            )
        for bucket in ("deterministic", "ai"):
            for entry in spec.get(bucket) or []:
                if isinstance(entry, dict) and entry.get("id") == check_id:
                    return path, slug
    raise ClaimVerificationError(
        f"claimed check id does not exist: {check_id!r} is not declared as an "
        f"'id' in any checks.json under {skills_root}. The claim asserts a "
        f"check that was never written."
    )


def _unreachable_report(root: Path) -> List[dict]:
    """The contracts the coverage gate reports as unreachable.

    Runs the CourseCraft validation-coverage gate from the repo root and reads
    its top-level ``unreachable`` key, which that gate emits unconditionally as
    a list of ``{"slug", "path", "reason"}`` records. A report missing that key,
    or carrying entries in another shape, is gate-contract drift: it is raised
    rather than read as "nothing is unreachable", because a silent empty answer
    would let a claim about a dead contract pass.
    """
    gate = root / COVERAGE_GATE_RELATIVE_PATH
    if not gate.is_file():
        raise ClaimVerificationError(
            f"validation-coverage gate is unavailable: {gate}. "
            "Contract reachability cannot be verified."
        )
    try:
        result = subprocess.run(
            # The PATH python3, never sys.executable: inside the installed CLI
            # that is the uv tool venv, which has none of the repo's imports.
            [python3_interpreter(), str(gate), "--json", "--quiet"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=COVERAGE_GATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ClaimVerificationError(
            f"validation-coverage gate timed out after {COVERAGE_GATE_TIMEOUT_SECONDS}s: {gate}"
        )
    # A non-zero status means coverage failures exist, not that the gate broke;
    # the JSON report is still the payload. Only unparsable output is fatal.
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ClaimVerificationError(
            f"validation-coverage gate emitted no JSON report (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:400]}"
        )
    if "unreachable" not in report:
        raise ClaimVerificationError(
            f"{COVERAGE_GATE_RELATIVE_PATH} --json emitted no top-level "
            f"'unreachable' key, so contract reachability cannot be read. That "
            f"gate's report shape changed; the claim is not verified."
        )
    entries = report["unreachable"]
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) and "slug" in entry and "path" in entry
        for entry in entries
    ):
        raise ClaimVerificationError(
            f"{COVERAGE_GATE_RELATIVE_PATH} --json reported 'unreachable' in an "
            f"unexpected shape (expected a list of objects carrying 'slug' and "
            f"'path'); contract reachability cannot be read."
        )
    return entries


def _verify_check_claim(claim: str, check_id: str) -> str:
    """Verify a ``check:`` claim: the id exists and its contract is reachable."""
    if not check_id:
        raise ClaimVerificationError(f"claim names no check id: {claim!r}")

    root = _coursecraft_project_root()
    skills_root = root / SKILLS_ROOT_RELATIVE_PATH
    if not skills_root.is_dir():
        raise ClaimVerificationError(
            f"CourseCraft skills tree is unavailable: {skills_root}"
        )

    contract, slug = _find_check_id_contract(check_id, skills_root)
    # The gate reports its own repo-relative view of a contract
    # (.agents/skills/<skill>/... ), while this command holds the path it walked
    # through the resolved skill symlink (the shared skills repo). The two are
    # the same file and never the same string, so paths are compared resolved.
    # Slug alone is not enough: a checks.json that does not parse, or declares
    # no slug, is reported unreachable with a null slug and would otherwise read
    # as reachable.
    resolved_contract = contract.resolve()
    listed = [
        entry["reason"] if entry.get("reason") else str(entry["path"])
        for entry in _unreachable_report(root)
        if entry["slug"] == slug or Path(entry["path"]).resolve() == resolved_contract
    ]
    if listed:
        raise ClaimVerificationError(
            f"{claim!r}: check id {check_id!r} exists in {contract}, but that "
            f"contract is reported UNREACHABLE by "
            f"{COVERAGE_GATE_RELATIVE_PATH}: {', '.join(listed)}. An unreachable "
            f"contract never runs, so the check does not enforce anything."
        )
    return f"check id {check_id!r} declared in {contract} (contract {slug} reachable)"


def _record_field_text(value) -> str:
    """One record field value as the text a claim compares against."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(_record_field_text(item) for item in value)
    return str(value)


def _find_claim_record(client, record_id: str) -> Tuple[str, dict]:
    """Locate a claimed record and its ACTUAL table, or raise.

    Uses a per-table server-side membership check
    (``filterByFormula=RECORD_ID()='rec...'``) because Airtable's
    get-record-by-ID endpoint does not enforce table membership: it returns
    the record for any table name in the same base, which would mislabel
    every record as belonging to the first table probed (see CLAIM_TABLES).
    """
    for table in CLAIM_TABLES:
        records = client.list_records(table, f"RECORD_ID()='{record_id}'")
        if records:
            return table, records[0]
    raise ClaimVerificationError(
        f"claimed record does not exist: {record_id} was not found in any of "
        f"{', '.join(CLAIM_TABLES)}."
    )


def _verify_record_claim(client, claim: str, body: str) -> str:
    """Verify a ``record:`` claim against the live record."""
    record_id, separator, rest = body.partition(":")
    if not record_id or not separator or not rest:
        raise ClaimVerificationError(
            f"malformed claim {claim!r}. Expected {CLAIM_FORMS_HELP}"
        )

    equals_at = rest.find("=")
    if equals_at < 1:
        raise ClaimVerificationError(
            f"malformed claim {claim!r}: no '=' or '~=' comparison. "
            f"Expected {CLAIM_FORMS_HELP}"
        )
    contains_form = rest[equals_at - 1] == "~"
    field = rest[: equals_at - 1] if contains_form else rest[:equals_at]
    expected = rest[equals_at + 1:]
    field = field.strip()
    if not field:
        raise ClaimVerificationError(f"claim names no field: {claim!r}")

    table, record = _find_claim_record(client, record_id)
    actual = _record_field_text(record.get("fields", {}).get(field)).strip()
    wanted = expected.strip()
    matched = wanted in actual if contains_form else wanted == actual
    if not matched:
        operator = "contain" if contains_form else "equal"
        raise ClaimVerificationError(
            f"{claim!r}: {table} record {record_id} field {field!r} does not "
            f"{operator} the claimed value. Claimed {wanted!r}; found "
            f"{actual[:400]!r}."
        )
    operator = "contains" if contains_form else "equals"
    return f"{table} record {record_id} field {field!r} {operator} {wanted!r}"


def _verify_remediation_claims(client, claims: List[str]) -> None:
    """Check every remediation claim, raising on the first one that does not hold.

    The caller reports the failure and continues; this function stays strict so
    the message names exactly which claim failed and what was found instead.
    """
    for claim in claims:
        stripped = claim.strip()
        if stripped.startswith("check:"):
            evidence = _verify_check_claim(stripped, stripped[len("check:"):].strip())
        elif stripped.startswith("record:"):
            evidence = _verify_record_claim(client, stripped, stripped[len("record:"):])
        else:
            raise ClaimVerificationError(
                f"unsupported claim form {claim!r}. Expected {CLAIM_FORMS_HELP}"
            )
        print_info(f"Verified remediation claim: {evidence}")


class FeedbackSource(str, Enum):
    """Allowed values for the Feedback "Source" single-select field.

    Every Feedback row declares where the feedback came from, so provenance
    stays distinguishable after the fact:

    - ``User`` -- Adam, in the CourseCraft web app.
    - ``CourseCraft`` -- written through the CourseCraft CLI / agent pipeline.
    - ``Pluralsight`` -- the Pluralsight slide-deck review.
    - ``Pluralsight - CQA`` -- Pluralsight Content Quality Assurance review.
    - ``Pluralsight - Tech Reviewer`` -- the Pluralsight SME / tech review.
    - ``Pluralsight - VCP`` -- Pluralsight Video Content Production review.

    The four Pluralsight values are one per reviewer, and each maps to one
    completion flag on the module's tab in the course feedback Google Sheet
    (``Slide Complete``, ``CQA Complete``, ``Reviewer Complete``, ``VCP
    Complete``). Source is provenance only: the open-feedback gate is the
    ``Open Feedback Count`` rollup over every linked row regardless of Source.
    Sheet imports write one of the four reviewer values.

    Source is required when creating a row.
    """
    PLURALSIGHT = "Pluralsight"
    PLURALSIGHT_CQA = "Pluralsight - CQA"
    PLURALSIGHT_TECH_REVIEWER = "Pluralsight - Tech Reviewer"
    PLURALSIGHT_VCP = "Pluralsight - VCP"
    COURSECRAFT = "CourseCraft"
    USER = "User"


def _airtable_utc_now() -> str:
    """Current UTC time formatted the way Airtable persists a dateTime field.

    Airtable stores dateTime values as UTC with millisecond precision and a
    trailing ``Z`` (e.g. ``2026-06-17T14:45:05.296Z``). The client verifies a
    write by re-reading the record and comparing scalar fields, so the auto-stamp
    must already match Airtable's persisted shape; a microsecond/``+00:00`` ISO
    string would be reformatted on write and fail that verification even though
    the record was created.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _first_linked_id(value) -> str:
    """Return the first linked record ID from a linked-record field value.

    Linked-record fields are stored as arrays of record IDs. Returns the first
    ID, or an empty string when the field is unset or empty.
    """
    if isinstance(value, list) and value:
        return value[0]
    return ""


def _filter_by_linked_record(records: List[dict], field: str, record_id: str) -> List[dict]:
    """Keep the records whose ``field`` link array contains ``record_id``.

    Link filtering must happen client-side: in an Airtable formula, a linked
    record field renders the linked records' PRIMARY FIELD display values, not
    their record IDs, so a server-side ``FIND('rec...', ARRAYJOIN({Field}))``
    formula can never match. The records API, by contrast, returns link fields
    as arrays of record IDs, which is what this membership test reads. Airtable
    omits empty link fields from ``fields`` entirely, so a missing key means no
    links.
    """
    return [
        rec for rec in records
        if record_id in rec.get("fields", {}).get(field, [])
    ]


COMMAND_CREDENTIALS = {
    "create": ["custom"],
    "delete": ["custom"],
    "get": ["custom"],
    "list": ["custom"],
    "update": ["custom"],
}


@app.command("list")
@command
def list_feedback(
    demo: Optional[str] = typer.Option(None, "--demo", "-D", help="Filter by linked demo record ID"),
    slide: Optional[str] = typer.Option(None, "--slide", "-S", help="Filter by linked slide record ID"),
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Filter by linked clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Filter by linked module record ID"),
    course: Optional[str] = typer.Option(None, "--course", help="Filter by linked course record ID"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., status:eq:Pending). Cannot be combined with --demo, --slide, --clip, --module, or --course.",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List feedback records.

    The --demo, --slide, --clip, --module, and --course options return feedback
    rows linked to that exact record ID. Only one link option may be used at a
    time, and a link option cannot be combined with --filter.

    Examples:
        # List all feedback
        coursecraft feedback list

        # List feedback for a specific demo
        coursecraft feedback list --demo recXXXXXXXXXXXXXXX

        # List feedback for a specific slide
        coursecraft feedback list --slide recXXXXXXXXXXXXXXX

        # List feedback for a specific clip / module / course
        coursecraft feedback list --clip recXXXXXXXXXXXXXXX
        coursecraft feedback list --module recXXXXXXXXXXXXXXX
        coursecraft feedback list --course recXXXXXXXXXXXXXXX

        # List with a standard filter
        coursecraft feedback list --filter "feedback:contains:typo"
        coursecraft feedback list --filter "patterns_learned:contains:course requirements"
        # Filter field names use lowercase snake_case, not Airtable display labels.

        # A link option cannot be combined with --filter
        coursecraft feedback list --demo recXXXXXXXXXXXXXXX

        # List with table output
        coursecraft feedback list --table

        # Limit results
        coursecraft feedback list --limit 10

        # Select specific properties
        coursecraft feedback list --properties "id,fields.Timestamp,fields.Feedback"
    """
    try:
        client = get_client()

        # Link fields store record IDs in the API but render display names in
        # formula context, so link matching happens client-side after the full
        # list is fetched. Only one link option may be active at a time.
        link_filters = {
            DEMO_FIELD: demo,
            SLIDE_FIELD: slide,
            CLIP_FIELD: clip,
            MODULE_FIELD: module,
            COURSE_FIELD: course,
        }
        active_links = {field: value for field, value in link_filters.items() if value}

        if len(active_links) > 1:
            print_error("Cannot use multiple link options (--demo, --slide, --clip, --module, --course) together")
            raise typer.Exit(1)
        if filter and active_links:
            print_error("Cannot use --filter with --demo, --slide, --clip, --module, or --course")
            raise typer.Exit(1)

        formula = translate_filters(list(filter), TABLE_NAME) if filter else None

        records = client.list_records(TABLE_NAME, formula)
        if active_links:
            field, record_id = next(iter(active_links.items()))
            records = _filter_by_linked_record(records, field, record_id)

        # Apply limit
        records = apply_limit(records, limit)

        # Apply properties filter for JSON output
        if properties and not table_output:
            records = apply_properties_filter(records, properties)

        if table_output:
            rows = []
            for rec in records:
                fields = rec.get("fields", {})
                fb = fields.get("Feedback", "")
                rows.append({
                    "id": rec["id"],
                    "timestamp": fields.get("Timestamp", ""),
                    "demo": _first_linked_id(fields.get(DEMO_FIELD)),
                    "slide": _first_linked_id(fields.get(SLIDE_FIELD)),
                    "status": fields.get("Processing Status", ""),
                    "feedback": fb[:50] + "..." if fb and len(fb) > 50 else fb,
                })
            print_table(rows, ["id", "timestamp", "demo", "slide", "status", "feedback"],
                       ["Record ID", "Timestamp", "Demo", "Slide", "Status", "Feedback"])
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
def get_feedback(
    record_id: str = typer.Argument(..., help="Feedback record ID"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Property to include (supports dot notation). Repeatable; each value may also be comma-separated."),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single feedback record by ID.

    Examples:
        coursecraft feedback get recXXXXXXXXXXXXXXX
        coursecraft feedback get recXXXXXXXXXXXXXXX --properties "id,fields.Feedback,fields.Processing Status"
        coursecraft feedback get recXXXXXXXXXXXXXXX --table
    """
    try:
        client = get_client()

        record = client.get_record(TABLE_NAME, record_id)
        if not record:
            print_error(f"Feedback not found: {record_id}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = project_record(record, properties)

        if table_output:
            fields = record.get("fields", {})
            fb = fields.get("Feedback", "")
            rows = [{
                "id": record["id"],
                "timestamp": fields.get("Timestamp", ""),
                "demo": _first_linked_id(fields.get(DEMO_FIELD)),
                "slide": _first_linked_id(fields.get(SLIDE_FIELD)),
                "feedback": fb[:60] + "..." if fb and len(fb) > 60 else fb,
            }]
            print_table(rows, ["id", "timestamp", "demo", "slide", "feedback"],
                       ["Record ID", "Timestamp", "Demo", "Slide", "Feedback"])
        else:
            print_json(record)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("create")
@command
def create_feedback(
    demo: Optional[str] = typer.Option(None, "--demo", "-D", help="Linked demo record ID"),
    slide: Optional[str] = typer.Option(None, "--slide", "-S", help="Linked slide record ID"),
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Linked clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Linked module record ID"),
    course: Optional[str] = typer.Option(None, "--course", help="Linked course record ID"),
    feedback: str = typer.Option(..., "--feedback", "-f", help="Feedback text (required)"),
    patterns_learned: Optional[str] = typer.Option(None, "--patterns-learned", "-p", help="Patterns learned from this feedback"),
    timestamp: Optional[str] = typer.Option(None, "--timestamp", help="ISO 8601 timestamp; defaults to the current UTC time when omitted"),
    source: FeedbackSource = typer.Option(..., "--feedback-source", "--source", help="Where this feedback came from: 'User' (Adam in the app), 'CourseCraft' (CLI/agent pipeline), 'Pluralsight', 'Pluralsight - CQA', 'Pluralsight - Tech Reviewer', or 'Pluralsight - VCP'. Required."),
    processing_status: Optional[str] = typer.Option(None, "--processing-status", help="Processing status (Pending, Proposed, Applied, Declined, Failed, No Action, Needs Clarification)"),
    processed_at: Optional[str] = typer.Option(None, "--processed-at", help="ISO 8601 timestamp the feedback was processed"),
    remediation: Optional[str] = typer.Option(None, "--remediation", help="Summary of which skills/agents/sources were modified and how, to remediate this feedback (orchestrator-written when set to Applied)"),
    element_type: Optional[str] = typer.Option(None, "--element-type", help="Artifact level: Course/Module/Clip/Demo/Slide"),
    attribute_name: Optional[str] = typer.Option(None, "--attribute-name", help="The artifact field the feedback is about, e.g. Script"),
    attribute_snapshot: Optional[str] = typer.Option(None, "--attribute-snapshot", help="The entire attribute value frozen at submission time"),
    selected_text: Optional[str] = typer.Option(None, "--selected-text", help="The exact span the comment targets"),
):
    """
    Create a feedback record.

    The Timestamp auto-stamps to the current UTC time when --timestamp is omitted.

    --source is required and records provenance: 'User' (Adam in the CourseCraft
    app), 'CourseCraft' (the CLI / agent pipeline), 'Pluralsight',
    'Pluralsight - CQA', or 'Pluralsight - VCP'.

    Source does NOT affect gating. Every Source counts into the 'Open Feedback
    Count' rollups on Slides, Demos, Clips and Modules, which SUM the Feedback
    'Is Open' formula with no Source condition. Any row with an open Processing
    Status therefore drives its linked element to 'Edits Needed (Design)' or
    'Edits Needed (Recorded)' and holds the module in the feedback phase.

    Examples:
        # Log feedback against a demo (auto-stamped)
        coursecraft feedback create --demo recXXX --source User --feedback "Step 3 narration was unclear"

        # Log feedback against a slide with patterns learned
        coursecraft feedback create --slide recXXX --source User \\
            --feedback "Bullet text exceeded the limit" \\
            --patterns-learned "Keep each bullet under 64 characters"

        # Log feedback against a clip / module / course
        coursecraft feedback create --clip recXXX --source User --feedback "Pacing felt rushed"
        coursecraft feedback create --module recXXX --source User --feedback "Module ordering note"
        coursecraft feedback create --course recXXX --source User --feedback "Course-wide tone note"

        # Import a Pluralsight review row
        coursecraft feedback create --clip recXXX --source Pluralsight --feedback "Fix the font on this slide" --processing-status Pending

        # Provide an explicit timestamp and processing status
        coursecraft feedback create --source User --feedback "General note" --timestamp "2026-06-17T12:00:00+00:00" --processing-status Pending

        # Freeze a snapshot of the reviewed attribute
        coursecraft feedback create --slide recXXX --source User --feedback "Tighten the opening line" \\
            --element-type Slide --attribute-name Script \\
            --attribute-snapshot "Full script text at submission time" \\
            --selected-text "the opening line"
    """
    try:
        client = get_client()

        # Auto-stamp a feedback-log row to the current time when no timestamp
        # is supplied. The default uses Airtable's persisted UTC dateTime shape
        # (millisecond precision, trailing 'Z') so the write-verification
        # round-trip matches exactly.
        timestamp_value = timestamp if timestamp is not None else _airtable_utc_now()

        # Build fields dictionary
        fields = {
            "Timestamp": timestamp_value,
            "Feedback": feedback,
            SOURCE_FIELD: source.value,
        }

        fields.update(element_link_fields(
            demo=demo, slide=slide, clip=clip, module=module, course=course
        ))
        if patterns_learned is not None:
            fields["Patterns Learned"] = patterns_learned
        if processing_status is not None:
            fields["Processing Status"] = processing_status
        if processed_at is not None:
            fields["Processed At"] = processed_at
        if remediation is not None:
            fields["Remediation"] = remediation
        if element_type is not None:
            fields["Element Type"] = element_type
        if attribute_name is not None:
            fields["Attribute Name"] = attribute_name
        if attribute_snapshot is not None:
            fields["Attribute Snapshot"] = attribute_snapshot
        if selected_text is not None:
            fields["Selected Text"] = selected_text

        # Create the record
        record_id = client.create_record(TABLE_NAME, fields)

        print_success(f"Created feedback: {record_id}")

        # Output the record ID as machine-readable JSON for scripting.
        print_json({"id": record_id})

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
@command
def update_feedback(
    record_id: str = typer.Argument(..., help="Feedback record ID"),
    demo: Optional[str] = typer.Option(None, "--demo", "-D", help="Linked demo record ID"),
    slide: Optional[str] = typer.Option(None, "--slide", "-S", help="Linked slide record ID"),
    clip: Optional[str] = typer.Option(None, "--clip", "-c", help="Linked clip record ID"),
    module: Optional[str] = typer.Option(None, "--module", "-m", help="Linked module record ID"),
    course: Optional[str] = typer.Option(None, "--course", help="Linked course record ID"),
    feedback: Optional[str] = typer.Option(None, "--feedback", "-f", help="Feedback text"),
    patterns_learned: Optional[str] = typer.Option(None, "--patterns-learned", "-p", help="Patterns learned from this feedback"),
    timestamp: Optional[str] = typer.Option(None, "--timestamp", help="ISO 8601 timestamp"),
    source: Optional[FeedbackSource] = typer.Option(None, "--feedback-source", "--source", help="Where this feedback came from: 'User', 'CourseCraft', 'Pluralsight', 'Pluralsight - CQA', 'Pluralsight - Tech Reviewer', or 'Pluralsight - VCP'"),
    processing_status: Optional[str] = typer.Option(None, "--processing-status", help="Processing status (Pending, Proposed, Applied, Declined, Failed, No Action, Needs Clarification)"),
    processed_at: Optional[str] = typer.Option(None, "--processed-at", help="ISO 8601 timestamp the feedback was processed"),
    remediation: Optional[str] = typer.Option(None, "--remediation", help="Summary of which skills/agents/sources were modified and how, to remediate this feedback (orchestrator-written when set to Applied)"),
    remediation_claim: Optional[List[str]] = typer.Option(None, "--remediation-claim", help=f"Repeatable, machine-verified evidence for --remediation. EXPECTED with --processing-status Applied + --remediation; omitting it warns. Forms: {CLAIM_FORMS_HELP}"),
    element_type: Optional[str] = typer.Option(None, "--element-type", help="Artifact level: Course/Module/Clip/Demo/Slide"),
    attribute_name: Optional[str] = typer.Option(None, "--attribute-name", help="The artifact field the feedback is about, e.g. Script"),
    attribute_snapshot: Optional[str] = typer.Option(None, "--attribute-snapshot", help="The entire attribute value frozen at submission time"),
    selected_text: Optional[str] = typer.Option(None, "--selected-text", help="The exact span the comment targets"),
):
    """
    Update a feedback record.

    Stamping a row Applied with a --remediation summary is EXPECTED to carry at
    least one --remediation-claim; omitting it warns and still writes. Every
    claim given is verified against live state before anything is written:

        check:<dotted.check.id>              the id must be declared as an 'id'
                                             in a checks.json under the
                                             CourseCraft skills tree, and its
                                             contract must be reachable
        record:<recordId>:<Field>=<value>    the live record's field must equal
                                             the claimed value (trimmed strings)
        record:<recordId>:<Field>~=<text>    the live record's field must contain
                                             the claimed substring

    A claim that does not verify is REPORTED as a warning naming the exact claim
    and what was found instead, and the update then proceeds. Treat that warning
    as a failed assertion about your own work, not as noise.

    Examples:
        coursecraft feedback update recXXX --feedback "Revised feedback text"
        coursecraft feedback update recXXX --demo recDEMOID
        coursecraft feedback update recXXX --slide recSLIDEID
        coursecraft feedback update recXXX --clip recCLIPID
        coursecraft feedback update recXXX --module recMODULEID
        coursecraft feedback update recXXX --course recCOURSEID
        coursecraft feedback update recXXX --patterns-learned "New pattern"
        coursecraft feedback update recXXX --processing-status Applied --processed-at "2026-06-17T12:00:00+00:00" \
            --remediation "slide-design SKILL.md: added a concrete-naming rule; mirrored to Codex agent. Fixes the vague-term feedback." \
            --remediation-claim "check:slide.content.script.no-vague-deixis" \
            --remediation-claim "record:recSLIDEID:Script~=the concrete term"
        coursecraft feedback update recXXX --timestamp "2026-06-17T12:00:00+00:00"
        coursecraft feedback update recXXX --element-type Slide --attribute-name Script \\
            --attribute-snapshot "Full script text" --selected-text "the opening line"
    """
    try:
        claims = [claim for claim in (remediation_claim or []) if claim.strip()]
        if (
            processing_status is not None
            and processing_status.strip().lower() == APPLIED_STATUS.lower()
            and remediation is not None
            and not claims
        ):
            warn_policy(
                "feedback.remediation_claim",
                f"--processing-status {APPLIED_STATUS} with --remediation normally "
                f"carries at least one --remediation-claim, so the remediation summary "
                f"is backed by something the CLI checked. Stamping without one. "
                f"Forms: {CLAIM_FORMS_HELP}",
            )

        client = get_client()

        # Verify record exists
        existing = client.get_record(TABLE_NAME, record_id)
        if not existing:
            print_error(f"Feedback not found: {record_id}")
            raise typer.Exit(1)

        # Advisory: every claim is still checked before the write, and a claim that
        # does not hold is REPORTED rather than blocking the stamp.
        if claims:
            try:
                _verify_remediation_claims(client, claims)
            except ClaimVerificationError as claim_error:
                warn_policy(
                    "feedback.remediation_claim",
                    f"Remediation claim not verified: {claim_error}",
                )

        # Build fields dictionary with only provided values
        fields = {}
        if timestamp is not None:
            fields["Timestamp"] = timestamp
        fields.update(element_link_fields(
            demo=demo, slide=slide, clip=clip, module=module, course=course
        ))
        if feedback is not None:
            fields["Feedback"] = feedback
        if patterns_learned is not None:
            fields["Patterns Learned"] = patterns_learned
        if source is not None:
            fields[SOURCE_FIELD] = source.value
        if processing_status is not None:
            fields["Processing Status"] = processing_status
        if processed_at is not None:
            fields["Processed At"] = processed_at
        if remediation is not None:
            fields["Remediation"] = remediation
        if element_type is not None:
            fields["Element Type"] = element_type
        if attribute_name is not None:
            fields["Attribute Name"] = attribute_name
        if attribute_snapshot is not None:
            fields["Attribute Snapshot"] = attribute_snapshot
        if selected_text is not None:
            fields["Selected Text"] = selected_text

        if not fields:
            print_error("No fields to update. Provide at least one field option.")
            raise typer.Exit(1)

        client.update_record(TABLE_NAME, record_id, fields)

        print_success(f"Updated feedback: {record_id}")
        print_json({"id": record_id})

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
@command
def delete_feedback(
    record_id: str = typer.Argument(..., help="Feedback record ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a feedback record.

    This action is PERMANENT and cannot be undone.

    Examples:
        # Delete with confirmation prompt
        coursecraft feedback delete recXXXXXXXXXXXXXXX

        # Delete without confirmation (for scripting)
        coursecraft feedback delete recXXXXXXXXXXXXXXX --force
    """
    try:
        client = get_client()

        # Verify record exists
        record = client.get_record(TABLE_NAME, record_id)
        if not record:
            print_error(f"Feedback not found: {record_id}")
            raise typer.Exit(1)

        # Confirm deletion
        if not force:
            if not typer.confirm(f"Are you sure you want to delete feedback '{record_id}'?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        # Delete the record
        client.delete_record(TABLE_NAME, record_id)
        print_success(f"Deleted feedback: {record_id}")

        # Output the deleted ID for scripting
        typer.echo(record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
