"""Course outlines command module."""
import json
import re
import subprocess
import typer
from typing import Optional, List
from pathlib import Path

from cli_tools_shared.output import command

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info, print_json, print_table
from ..google_docs import (
    get_course_from_google_doc,
    build_table_updates_from_fields,
    build_module_table_updates,
    format_module_content,
    extract_doc_id,
    find_course_organization_table_index,
    get_document_structure,
    _extract_cell_text,
    outline_table_indices_from_document,
    _table_by_index,
    validate_fields_fit_google_doc,
)

app = typer.Typer(help="Manage course outline documents")

# Valid type values
VALID_TYPES = {"google_doc"}


def _parse_type_param(type_value: str) -> List[str]:
    """Parse comma-separated type parameter into list of valid types."""
    types = [t.strip() for t in type_value.split(",")]
    invalid = set(types) - VALID_TYPES
    if invalid:
        raise typer.BadParameter(
            f"Invalid type(s): {', '.join(invalid)}. "
            f"Valid types: {', '.join(sorted(VALID_TYPES))}"
        )
    return types


def _build_fields_from_params(
    name: Optional[str] = None,
    course_id: Optional[str] = None,
    target_length: Optional[int] = None,
    short_description: Optional[str] = None,
    long_description: Optional[str] = None,
    content_level: Optional[str] = None,
    content_tags: Optional[str] = None,
    job_role: Optional[str] = None,
    learner_profile: Optional[str] = None,
    prerequisites: Optional[str] = None,
    platform_versions: Optional[str] = None,
    storyline: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Build course fields dict from CLI params (only non-None values)."""
    fields = {}

    if name is not None:
        fields["Name"] = name
    if course_id is not None:
        fields["Course ID"] = course_id
    if target_length is not None:
        fields["Target Length (Min)"] = target_length
    if short_description is not None:
        fields["Short Description"] = short_description
    if long_description is not None:
        fields["Long Description"] = long_description
    if content_level is not None:
        fields["Content Level"] = content_level
    if content_tags is not None:
        fields["Content Tags"] = content_tags
    if job_role is not None:
        fields["Job Role"] = job_role
    if learner_profile is not None:
        fields["Learner Profile"] = learner_profile
    if prerequisites is not None:
        fields["(Required) Learner Prerequisites"] = prerequisites
    if platform_versions is not None:
        fields["Platform/Tool Versions"] = platform_versions
    if storyline is not None:
        fields["Storyline"] = storyline
    if notes is not None:
        fields["Notes"] = notes

    return fields


def _extract_markdown_section(content: str, heading: str) -> str:
    """Extract text under an exact level-two heading through its subsections."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else ""


def _plain_text_from_markdown(content: str) -> str:
    """Convert approved outline Markdown blocks to Google Doc plain text."""
    output: List[str] = []
    in_fence = False

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if re.match(r"^-\s+\[[ xX]\]\s+", line):
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            line = "- " + " — ".join(cells)
        else:
            line = re.sub(r"^#{1,6}\s+", "", line)

        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", line)
        line = line.replace("`", "")
        output.append(line)

    if in_fence:
        raise RuntimeError("Course outline contains an unclosed fenced code block")

    return "\n".join(output).strip()


def _extract_draft_labeled_block(block: str, label: str) -> str:
    """Extract a ``**Label:**`` value/block from the approved outline draft."""
    match = re.search(
        rf"^\*\*{re.escape(label)}:\*\*\s*([^\n]*)\n?"
        rf"([\s\S]*?)(?=^\*\*[^*\n]+:\*\*|^##\s+|\Z)",
        block,
        flags=re.MULTILINE,
    )
    if not match:
        return ""
    return "\n".join(part for part in match.groups() if part).strip()


def _parse_outline_draft_modules(content: str) -> tuple[List[dict], str]:
    """Map canonical ``course.outline_draft`` module blocks to Doc updates."""
    module_heading = re.compile(
        r"^##\s+Module\s+(\d+)\s+-\s+(.+?)\s*$",
        flags=re.MULTILINE,
    )
    matches = list(module_heading.finditer(content))
    if not matches:
        raise RuntimeError("Course outline draft contains no canonical '## Module N - Title' sections")

    modules = []
    all_objectives = []
    for idx, match in enumerate(matches):
        module_number = int(match.group(1))
        module_name = _plain_text_from_markdown(match.group(2))
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        block = content[match.end():block_end].strip()

        duration = _extract_draft_labeled_block(block, "Total Length")
        terminal = _extract_draft_labeled_block(block, "Terminal Objective")
        enabling_block = _extract_draft_labeled_block(block, "Enabling Learning Objectives")
        clips_block = _extract_draft_labeled_block(block, "Clips")
        missing = [
            label
            for label, value in (
                ("Total Length", duration),
                ("Terminal Objective", terminal),
                ("Enabling Learning Objectives", enabling_block),
                ("Clips", clips_block),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Module {module_number} is missing required draft block(s): {', '.join(missing)}"
            )

        enabling = [
            _plain_text_from_markdown(re.sub(r"^-\s+", "", line.strip()))
            for line in enabling_block.splitlines()
            if line.strip()
        ]
        objectives = [f"Terminal {module_number}: {_plain_text_from_markdown(terminal)}"]
        objectives.extend(
            f"Enabling {module_number}.{objective_number}: {objective}"
            for objective_number, objective in enumerate(enabling, start=1)
        )
        all_objectives.extend(objectives)

        clip_lines = []
        for clip_number, line in enumerate(
            (line.strip() for line in clips_block.splitlines() if line.strip()),
            start=1,
        ):
            clip_match = re.fullmatch(
                r"-\s+\*\*(.+?)\*\*\s+\(([^)]+)\):\s*(.+)",
                line,
            )
            if not clip_match:
                raise RuntimeError(
                    f"Module {module_number} has a malformed clip entry: {line}"
                )
            clip_title, clip_duration, clip_description = clip_match.groups()
            clip_lines.append(
                f"Clip {clip_number}: {_plain_text_from_markdown(clip_title)} "
                f"({clip_duration}) — {_plain_text_from_markdown(clip_description)}"
            )

        objectives_plain = "\n".join(objectives)
        layout_plain = "\n".join(clip_lines)
        module_content = "\n\n".join([
            f"Module {module_number} - {module_name}",
            f"Learning Objectives:\n\n{objectives_plain}",
            f"Module Description:\n\n{_plain_text_from_markdown(terminal)}",
            f"Module Layout:\n\n{layout_plain}",
        ])
        modules.append({
            "module_number": module_number,
            "name": module_name,
            "duration": duration,
            "learning_objectives": objectives_plain,
            "module_description": _plain_text_from_markdown(terminal),
            "module_layout": layout_plain,
            "content": module_content,
        })

    actual_numbers = [module["module_number"] for module in modules]
    expected_numbers = list(range(1, len(modules) + 1))
    if actual_numbers != expected_numbers:
        raise RuntimeError(
            f"Course outline draft modules must be consecutive from 1; found {actual_numbers}"
        )
    return modules, "\n".join(all_objectives)


def _parse_markdown_to_course_fields(file_path: Path) -> dict:
    """
    Parse markdown file to extract course fields.

    The markdown should follow the same table structure as Google Docs outlines.
    This reuses the parsing logic from google_docs.py.
    """
    content = file_path.read_text()

    fields = {}

    # Parse simple "| Field | Value |" table format
    lines = content.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith('|') and '|' in line[1:]:
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 2:
                # Skip header separator rows
                if parts[0].startswith('-') or parts[1].startswith('-'):
                    continue

                key = parts[0]
                value = parts[1]

                # Map common markdown labels to Airtable field names
                label_mapping = {
                    "Course Title": "Name",
                    "Course Name": "Name",
                    "Name": "Name",
                    "Author Name": "Author Name",
                    "Opportunity ID": "Course ID",
                    "Course ID": "Course ID",
                    "Job Role": "Job Role",
                    "Content Tags": "Content Tags",
                    "Length Estimate": "Target Length (Min)",
                    "Target Length": "Target Length (Min)",
                    "Content Level": "Content Level",
                    "Notes": "Notes",
                    "Learner Profile": "Learner Profile",
                    "Learner Prerequisites": "(Required) Learner Prerequisites",
                    "Prerequisites": "(Required) Learner Prerequisites",
                    "Storyline": "Storyline",
                    "Platform/Tool Versions": "Platform/Tool Versions",
                    "Platform Versions": "Platform/Tool Versions",
                    "Short Description": "Short Description",
                    "Long Description": "Long Description",
                }

                for label, field_name in label_mapping.items():
                    if label.lower() in key.lower():
                        # Handle special conversions
                        if field_name == "Target Length (Min)":
                            # Extract number from string like "25 minutes"
                            match = re.search(r'(\d+)', value)
                            if match:
                                fields[field_name] = int(match.group(1))
                        elif value:
                            fields[field_name] = value
                        break

    section_field_mapping = {
        "Learner Profile": "Learner Profile",
        "Learner Prerequisites": "(Required) Learner Prerequisites",
        "Course Storyline": "Storyline",
        "Course Short Description": "Short Description",
        "Course Long Description": "Long Description",
    }
    for heading, field_name in section_field_mapping.items():
        value = _extract_markdown_section(content, heading)
        if value:
            fields[field_name] = _plain_text_from_markdown(value)

    author_notes = _extract_markdown_section(content, "Notes for Author")
    if author_notes:
        fields["Author Notes"] = _plain_text_from_markdown(author_notes)

    draft_labels = {
        "Short Description": "Short Description",
        "Long Description": "Long Description",
        "Learner Profile": "Learner Profile",
        "Prerequisites": "(Required) Learner Prerequisites",
    }
    for label, field_name in draft_labels.items():
        value = _extract_draft_labeled_block(content, label)
        if value:
            fields[field_name] = _plain_text_from_markdown(value)

    if "Long Description" in fields:
        fields.setdefault("Storyline", fields["Long Description"])
    if re.search(r"^##\s+Module\s+\d+\s+-\s+", content, flags=re.MULTILINE):
        fields.setdefault("Author Notes", " ")

    return fields


def _parse_markdown_to_outline_update(file_path: Path) -> dict:
    """Parse the approved Course Outline Draft into field and module updates."""
    content = file_path.read_text()
    fields = _parse_markdown_to_course_fields(file_path)
    modules, learning_objectives = _parse_outline_draft_modules(content)
    fields["Learning Objectives"] = learning_objectives
    required_fields = {
        "Learner Profile",
        "(Required) Learner Prerequisites",
        "Storyline",
        "Short Description",
        "Long Description",
    }
    missing_fields = sorted(required_fields - fields.keys())
    if missing_fields:
        raise RuntimeError(
            "Course outline draft is missing required field block(s): "
            + ", ".join(missing_fields)
        )
    return {
        "fields": fields,
        "modules": modules,
    }


def _apply_table_updates(doc_id: str, updates: List[dict]) -> dict:
    """
    Write already-resolved table cell updates to the Google Doc.

    Every update must already carry a concrete table/row/col. Row-label
    resolution happens in the caller so that --validate-only and the real
    write exercise the same resolution code and cannot disagree.

    Args:
        doc_id: Google Doc document ID
        updates: Resolved cell updates from build_table_updates_from_fields
            and build_module_table_updates

    Returns:
        Dict with update result info
    """
    if not updates:
        return {"documentId": doc_id, "updates": 0, "message": "No updates to apply"}

    # Convert to JSON and call google docs tables update
    updates_json = json.dumps(updates)

    result = subprocess.run(
        ["google", "docs", "tables", "update", doc_id, "--data", updates_json],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to update document tables: {result.stderr}")

    payload = json.loads(result.stdout)

    # Re-fetch the document and assert every targeted cell has the requested
    # content. This distinguishes an idempotent no-op from a silent wrong-cell
    # write: exact matches succeed, while any mismatch still fails loudly.
    _verify_table_updates(doc_id, updates)

    return payload


def _verify_table_updates(doc_id: str, updates: List[dict]) -> None:
    """Re-fetch the doc and assert each update's target cell matches expected content."""
    document = get_document_structure(doc_id)
    body = document.get('body', {})
    content = body.get('content', [])

    # Collect tables in order
    tables = [el['table'] for el in content if 'table' in el]

    mismatches = []
    for upd in updates:
        t_idx = upd.get('table')
        col = upd.get('col')
        expected = upd.get('content', '')

        if t_idx is None or t_idx >= len(tables):
            mismatches.append(f"table {t_idx} missing")
            continue

        rows = tables[t_idx].get('tableRows', [])

        # Resolve row (support label-based lookup)
        row_idx = upd.get('row')
        if row_idx is None and 'label' in upd:
            label = upd['label'].lower()
            row_idx = None
            for i, r in enumerate(rows):
                cells = r.get('tableCells', [])
                if cells and label in _extract_cell_text(cells[0]).lower():
                    row_idx = i
                    break
            if row_idx is None:
                mismatches.append(f"table {t_idx} label '{upd['label']}' not found")
                continue

        if row_idx >= len(rows):
            mismatches.append(f"table {t_idx} row {row_idx} missing")
            continue

        cells = rows[row_idx].get('tableCells', [])
        if col is None or col >= len(cells):
            mismatches.append(f"table {t_idx} row {row_idx} col {col} missing")
            continue

        actual = _extract_cell_text(cells[col])

        # Collapse whitespace, then require exact equality. Collapsing absorbs the
        # trailing newlines and reformatted spacing Google Docs introduces, which
        # is the only difference a successful write may leave. Containment is NOT
        # accepted in either direction: a cell holding more than was written is a
        # write that did not land, which is precisely what this check exists to
        # catch.
        expected_norm = ' '.join(expected.split())
        actual_norm = ' '.join(actual.split())
        if expected_norm != actual_norm:
            mismatches.append(
                f"table {t_idx} row {row_idx} col {col}: "
                f"expected '{expected_norm[:80]}' got '{actual_norm[:80]}'"
            )

    if mismatches:
        raise RuntimeError(
            "Post-update verification failed — doc was not updated as expected:\n  - "
            + "\n  - ".join(mismatches)
        )


@app.command("read")
@command
def read_course_outline(
    course_outline_link: str = typer.Option(
        ..., "--course-outline-link", "-l",
        help="Google Doc URL or document ID to read"
    ),
    table_output: bool = typer.Option(
        False, "--table", "-t",
        help="Output as formatted table"
    ),
):
    """
    Read course outline data from a Google Doc.

    Parses the Google Doc and returns structured JSON matching the same
    schema as 'coursecraft courses get'. Extracts course fields and
    module information from the document tables.

    Examples:
        # Read by document ID
        coursecraft course-outline read -l 1UNCevDbw6QxYlvLx0_L_FQfbiAOZLY_U1sy3EhGxd-I

        # Read by URL
        coursecraft course-outline read -l "https://docs.google.com/document/d/DOC_ID/edit"

        # Display as table
        coursecraft course-outline read -l DOC_ID --table
    """
    try:
        result = get_course_from_google_doc(course_outline_link)

        if table_output:
            # Display course fields as table
            fields = result.get("fields", {})
            rows = [{
                "field": key,
                "value": str(value)[:80] + "..." if len(str(value)) > 80 else str(value)
            } for key, value in fields.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])

            # Display modules if present
            if result.get("modules"):
                print_info("\nModules:")
                module_rows = [{
                    "order": m.get("order"),
                    "name": m.get("name", "")[:50],
                    "duration": m.get("duration_minutes")
                } for m in result["modules"]]
                print_table(module_rows, ["order", "name", "duration"], ["#", "Name", "Duration"])
        else:
            print_json(result)

    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("update")
@command
def update_course_outline(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    type_param: str = typer.Option(
        ..., "--type", "-t",
        help="Update target: google_doc"
    ),
    course_outline_file: Optional[Path] = typer.Option(
        None, "--course-outline-file", "-f",
        help="Path to file (markdown for parsing or content)"
    ),
    # Course field parameters
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Course name"),
    course_id_field: Optional[str] = typer.Option(None, "--course-id", help="Course slug identifier"),
    target_length: Optional[int] = typer.Option(None, "--target-length", help="Target length in minutes"),
    short_description: Optional[str] = typer.Option(None, "--short-description", help="Brief course summary"),
    long_description: Optional[str] = typer.Option(None, "--long-description", help="Detailed description"),
    content_level: Optional[str] = typer.Option(None, "--content-level", help="Entry-level, Intermediate, Advanced"),
    content_tags: Optional[str] = typer.Option(None, "--content-tags", help="Comma-separated content tags"),
    job_role: Optional[str] = typer.Option(None, "--job-role", help="Target job role"),
    learner_profile: Optional[str] = typer.Option(None, "--learner-profile", help="Learner description"),
    prerequisites: Optional[str] = typer.Option(None, "--prerequisites", help="Required learner prerequisites"),
    platform_versions: Optional[str] = typer.Option(None, "--platform-versions", help="Platform/tool versions"),
    storyline: Optional[str] = typer.Option(None, "--storyline", help="Course storyline narrative"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    # Module parameters
    module: Optional[int] = typer.Option(
        None, "--module", "-m",
        help="Module number to update (1, 2, 3, etc.)"
    ),
    clear_module: bool = typer.Option(
        False, "--clear-module",
        help="Clear the selected module slot's number, content, and duration"
    ),
    module_name: Optional[str] = typer.Option(
        None, "--module-name",
        help="Module name/title"
    ),
    module_objectives: Optional[str] = typer.Option(
        None, "--module-objectives",
        help="Module learning objectives"
    ),
    module_layout: Optional[str] = typer.Option(
        None, "--module-layout",
        help="Module layout description"
    ),
    module_duration: Optional[str] = typer.Option(
        None, "--module-duration",
        help="Module duration (e.g., '9' or '9 min')"
    ),
    module_content: Optional[str] = typer.Option(
        None, "--module-content",
        help="Full module content (overrides --module-name, --module-objectives, --module-layout)"
    ),
    module_content_file: Optional[Path] = typer.Option(
        None, "--module-content-file",
        help="File containing full module content"
    ),
    validate_only: bool = typer.Option(
        False, "--validate-only",
        help="Validate that the outline data fits the Google Doc template without writing"
    ),
):
    """
    Update course outline Google Doc table cells.

    The --type parameter specifies where to update:
    - google_doc: Update the Google Doc's table cells with provided field values

    For google_doc type:
    - Provide field values via CLI params (--name, --short-description, etc.)
    - Or provide --course-outline-file with markdown to parse for field values
    - Only explicitly provided fields are updated (partial update)

    For module updates:
    - Use --module to specify which module to update (1, 2, 3, etc.)
    - Provide content via --module-name, --module-objectives, --module-layout
    - Or use --module-content or --module-content-file for full content
    - Optionally add --module-duration for the duration column
    - Use --clear-module to clear an unused module slot

    Examples:
        # Update specific fields in Google Doc
        coursecraft course-outline update my-course --type google_doc --name "New Name"

        # Update Google Doc from parsed markdown file
        coursecraft course-outline update my-course --type google_doc -f outline.md

        # Update a specific module in Google Doc
        coursecraft course-outline update my-course --type google_doc --module 2 \\
            --module-name "Advanced Features" --module-duration "9"

        # Update module from content file
        coursecraft course-outline update my-course --type google_doc --module 2 \\
            --module-content-file module2.txt --module-duration "9 min"

        # Clear an unused module slot
        coursecraft course-outline update my-course --type google_doc --module 4 --clear-module

        # Validate an outline file fits the Google Doc template without writing
        coursecraft course-outline update my-course --type google_doc -f outline.md --validate-only
    """
    try:
        # Parse and validate type parameter
        update_types = _parse_type_param(type_param)

        # Validate module parameter combinations
        has_module_params = any([module_name, module_objectives, module_layout, module_content, module_content_file])
        if module is None and has_module_params:
            print_error("--module is required when using module update params")
            raise typer.Exit(1)

        if module is not None and module < 1:
            print_error("--module must be a positive integer (1, 2, 3, etc.)")
            raise typer.Exit(1)

        if module_content and module_content_file:
            print_error("Cannot specify both --module-content and --module-content-file")
            raise typer.Exit(1)

        if clear_module and module is None:
            print_error("--clear-module requires --module")
            raise typer.Exit(1)

        if clear_module and any([
            module_name,
            module_objectives,
            module_layout,
            module_duration,
            module_content,
            module_content_file,
        ]):
            print_error("--clear-module cannot be combined with module content or duration options")
            raise typer.Exit(1)

        # Validate files exist if specified
        if course_outline_file and not course_outline_file.exists():
            print_error(f"File not found: {course_outline_file}")
            raise typer.Exit(1)

        if module_content_file and not module_content_file.exists():
            print_error(f"File not found: {module_content_file}")
            raise typer.Exit(1)

        # Build fields from CLI params
        cli_fields = _build_fields_from_params(
            name=name,
            course_id=course_id_field,
            target_length=target_length,
            short_description=short_description,
            long_description=long_description,
            content_level=content_level,
            content_tags=content_tags,
            job_role=job_role,
            learner_profile=learner_profile,
            prerequisites=prerequisites,
            platform_versions=platform_versions,
            storyline=storyline,
            notes=notes,
        )

        if clear_module and (course_outline_file or cli_fields):
            print_error("--clear-module cannot be combined with course field updates")
            raise typer.Exit(1)

        # For google_doc type, check we have data to update (either course fields or module)
        if "google_doc" in update_types:
            if not cli_fields and not course_outline_file and module is None:
                print_error("--type google_doc requires field params, --course-outline-file, or --module")
                print_info("Provide at least one field to update (e.g., --name, --short-description, --module)")
                raise typer.Exit(1)

        client = get_client()

        # Resolve course identifier to get Google Doc link
        course_record_id = client.resolve_course_id(course)
        course_record = client.get_record("Courses", course_record_id)

        if not course_record:
            print_error(f"Course not found: {course}")
            raise typer.Exit(1)

        # Platform guard: course outlines are only supported for Pluralsight courses
        course_platform = course_record.get('fields', {}).get('Platform', 'Pluralsight')
        if course_platform == 'Udemy':
            print_error("Course outlines are only supported for Pluralsight courses.")
            print_info("Udemy courses do not use a Google Doc course outline.")
            raise typer.Exit(1)

        # Execute updates based on type
        results = []

        if "google_doc" in update_types:
            # Get Google Doc link from course record
            doc_link = course_record.get('fields', {}).get('Course Requirements Link', '')
            if not doc_link:
                print_error("Course has no Google Doc link set in 'Course Requirements Link' field")
                raise typer.Exit(1)

            # Build fields to update
            fields_to_update = dict(cli_fields)
            parsed_modules = []

            # If file provided, parse it and merge (file values take precedence)
            if course_outline_file:
                parsed_outline = _parse_markdown_to_outline_update(course_outline_file)
                file_fields = parsed_outline["fields"]
                parsed_modules = parsed_outline["modules"]
                # CLI params override file values
                for k, v in cli_fields.items():
                    file_fields[k] = v
                fields_to_update = file_fields

            # Build module updates if module is specified
            module_table_updates = []
            document = get_document_structure(extract_doc_id(doc_link))
            table_indices = outline_table_indices_from_document(document)
            course_org_table_idx = table_indices.get("course_organization")
            if course_org_table_idx is None:
                course_org_table_idx = find_course_organization_table_index(doc_link)
            course_org_table = _table_by_index(document, course_org_table_idx)

            # Pre-flight: validate fields fit the Google Doc template before any write
            preflight_errors = validate_fields_fit_google_doc(
                fields_to_update,
                document=document,
                table_indices=table_indices,
            )
            if preflight_errors:
                for err in preflight_errors:
                    print_error(f"Pre-flight validation failed: {err}")
                raise typer.Exit(1)

            # Build every table cell update before deciding to write. Row-label
            # resolution lives here, so --validate-only runs the exact resolution
            # the write runs and fails on any field with no row in this document.
            if module is not None:
                # Determine module content
                final_module_content = None

                if module_content_file:
                    # Read content from file
                    final_module_content = module_content_file.read_text()
                elif module_content:
                    # Use provided content directly
                    final_module_content = module_content
                elif module_name:
                    # Build content from structured params
                    final_module_content = format_module_content(
                        name=module_name,
                        learning_objectives=module_objectives,
                        module_layout=module_layout
                    )

                # Build the update for the module table
                module_table_updates = build_module_table_updates(
                    module_number=module,
                    content=final_module_content,
                    duration=module_duration,
                    clear=clear_module,
                    table_index=course_org_table_idx,
                    table=course_org_table,
                )

            elif parsed_modules:
                for parsed_module in parsed_modules:
                    module_table_updates.extend(build_module_table_updates(
                        module_number=parsed_module["module_number"],
                        content=parsed_module["content"],
                        duration=parsed_module["duration"],
                        table_index=course_org_table_idx,
                        table=course_org_table,
                    ))

            # Resolve every supplied course field to a concrete row in this document.
            cell_updates = []
            if fields_to_update:
                cell_updates.extend(build_table_updates_from_fields(
                    fields_to_update,
                    document=document,
                    table_indices=table_indices,
                ))
            cell_updates.extend(module_table_updates)

            # Count total updates
            field_count = len(fields_to_update)
            module_count = module if module is not None else len(parsed_modules)
            total_desc = []
            if field_count:
                total_desc.append(f"{field_count} course field(s)")
            if module_count:
                if module is not None:
                    total_desc.append(f"Module {module}")
                else:
                    total_desc.append(f"{module_count} module(s)")

            update_desc = ', '.join(total_desc) if total_desc else 'no updates'

            if validate_only:
                print_success(
                    f"Validation passed: {update_desc} resolved to "
                    f"{len(cell_updates)} Google Doc table cell(s)."
                )
                typer.echo(course_record_id)
                return

            if module is not None and module_table_updates:
                action = "Clearing" if clear_module else "Updating"
                print_info(f"{action} Module {module} in Google Doc")

            print_info(f"Updating Google Doc table cells: {update_desc}")
            result = _apply_table_updates(extract_doc_id(doc_link), cell_updates)

            updates_count = result.get('updates', 0)
            doc_url = result.get('url', doc_link)
            print_info(f"URL: {doc_url}")
            if updates_count == 0:
                results.append((
                    "Google Doc",
                    f"No changes needed; {len(cell_updates)} targeted table cell(s) already match",
                ))
            else:
                results.append(("Google Doc", f"Updated {updates_count} table cell(s)"))

        # Report results
        for target, result in results:
            print_success(f"{target}: {result}")

        # Output course record ID for scripting
        typer.echo(course_record_id)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "read": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
