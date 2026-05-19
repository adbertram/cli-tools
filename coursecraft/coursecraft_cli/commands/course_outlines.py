"""Course outlines command module."""
import json
import typer
from typing import Optional, List
from pathlib import Path

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info, print_json, print_table
from ..google_docs import (
    get_course_from_google_doc,
    generate_outline_markdown,
    build_table_updates_from_fields,
    build_module_table_updates,
    format_module_content,
    extract_doc_id,
    update_google_doc_outline_tables,
    find_course_organization_table_index,
    get_document_structure,
    _extract_cell_text,
)

app = typer.Typer(help="Manage course outline documents")

# Valid type values
VALID_TYPES = {"google_doc", "database"}


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
    learning_objectives: Optional[str] = None,
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
    if learning_objectives is not None:
        fields["Learning Objectives"] = learning_objectives
    if notes is not None:
        fields["Notes"] = notes

    return fields


def _parse_markdown_to_course_fields(file_path: Path) -> dict:
    """
    Parse markdown file to extract course fields.

    The markdown should follow the same table structure as Google Docs outlines.
    This reuses the parsing logic from google_docs.py.
    """
    import subprocess
    import tempfile
    import os

    content = file_path.read_text()

    # Create a temporary file and use the google CLI to parse it
    # This approach treats the markdown like a simple key-value extraction
    # For a proper implementation, we'd parse the markdown tables directly

    # For now, try to extract fields from markdown tables manually
    fields = {}

    # Parse simple "| Field | Value |" table format
    lines = content.split('\n')
    in_table = False

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
                    "Learning Objectives": "Learning Objectives",
                }

                for label, field_name in label_mapping.items():
                    if label.lower() in key.lower():
                        # Handle special conversions
                        if field_name == "Target Length (Min)":
                            # Extract number from string like "25 minutes"
                            import re
                            match = re.search(r'(\d+)', value)
                            if match:
                                fields[field_name] = int(match.group(1))
                        elif value:
                            fields[field_name] = value
                        break

    return fields


def _update_google_doc_partial(
    doc_link: str,
    fields: dict = None,
    module_updates: List[dict] = None
) -> dict:
    """
    Update ONLY the specified fields in Google Doc table cells.

    Args:
        doc_link: Google Doc URL
        fields: Dict of field names to values (only these will be updated)
        module_updates: List of module update dicts from build_module_table_updates

    Returns:
        Dict with update result info
    """
    import subprocess

    doc_id = extract_doc_id(doc_link)

    # Build updates for course fields
    updates = []
    if fields:
        updates.extend(build_table_updates_from_fields(fields))

    # Add module updates
    if module_updates:
        updates.extend(module_updates)

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

    # Verify updates actually landed. The underlying google CLI has been
    # observed to report success after writing to the wrong cell or to a
    # cell whose content did not change. Re-fetch the document and assert
    # each targeted cell now contains the expected content. Fail loudly on
    # any mismatch so callers cannot mistake a silent no-op for success.
    _verify_table_updates(doc_id, updates)

    return json.loads(result.stdout)


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
        # Compare normalized: collapse whitespace and check expected is contained.
        # Google Docs may insert trailing newlines / reformat whitespace.
        def _norm(s: str) -> str:
            return ' '.join(s.split())
        if _norm(expected) not in _norm(actual) and _norm(actual) not in _norm(expected):
            # Not a substring match either way — genuine mismatch.
            preview_exp = _norm(expected)[:80]
            preview_act = _norm(actual)[:80]
            mismatches.append(
                f"table {t_idx} row {row_idx} col {col}: "
                f"expected '{preview_exp}...' got '{preview_act}...'"
            )

    if mismatches:
        raise RuntimeError(
            "Post-update verification failed — doc was not updated as expected:\n  - "
            + "\n  - ".join(mismatches)
        )


def _update_database(
    client,
    course_record_id: str,
    course_outline_file: Optional[Path],
    course_outline_link: Optional[str]
) -> str:
    """Update Airtable's Course Outline field with markdown content."""
    content = ""

    if course_outline_file:
        # Use file content directly as markdown
        content = course_outline_file.read_text()
        print_info(f"Using content from file: {course_outline_file}")

    elif course_outline_link:
        # Parse Google Doc and convert to markdown
        print_info(f"Parsing Google Doc: {course_outline_link}")
        doc_data = get_course_from_google_doc(course_outline_link)
        content = generate_outline_markdown(doc_data, doc_data.get('modules', []))
        print_info(f"Generated markdown from Google Doc")

    # Update the Course Outline field in Airtable
    client.update_record("Courses", course_record_id, {
        "Course Outline": content
    })

    char_count = len(content)
    return f"Updated Course Outline field ({char_count} characters)"


@app.command("read")
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
        coursecraft course-outlines read -l 1UNCevDbw6QxYlvLx0_L_FQfbiAOZLY_U1sy3EhGxd-I

        # Read by URL
        coursecraft course-outlines read -l "https://docs.google.com/document/d/DOC_ID/edit"

        # Display as table
        coursecraft course-outlines read -l DOC_ID --table
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
def update_course_outline(
    course: str = typer.Argument(..., help="Course record ID or Course ID slug"),
    type_param: str = typer.Option(
        ..., "--type", "-t",
        help="Update target(s): google_doc, database, or google_doc,database"
    ),
    course_outline_file: Optional[Path] = typer.Option(
        None, "--course-outline-file", "-f",
        help="Path to file (markdown for parsing or content)"
    ),
    course_outline_link: Optional[str] = typer.Option(
        None, "--course-outline-link", "-l",
        help="Google Doc URL (only for database type - parses doc to markdown)"
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
    learning_objectives: Optional[str] = typer.Option(None, "--learning-objectives", help="Course learning objectives"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Internal notes"),
    # Module parameters
    module: Optional[int] = typer.Option(
        None, "--module", "-m",
        help="Module number to update (1, 2, 3, etc.)"
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
):
    """
    Update course outline in Google Doc and/or Airtable database.

    The --type parameter specifies where to update:
    - google_doc: Update the Google Doc's table cells with provided field values
    - database: Update Airtable's "Course Outline" field with markdown content
    - google_doc,database: Update both

    For google_doc type:
    - Provide field values via CLI params (--name, --learning-objectives, etc.)
    - Or provide --course-outline-file with markdown to parse for field values
    - Only explicitly provided fields are updated (partial update)

    For database type:
    - Provide --course-outline-file with markdown content (saved as-is)
    - Or provide --course-outline-link with Google Doc URL (parsed to markdown)

    For module updates (google_doc type only):
    - Use --module to specify which module to update (1, 2, 3, etc.)
    - Provide content via --module-name, --module-objectives, --module-layout
    - Or use --module-content or --module-content-file for full content
    - Optionally add --module-duration for the duration column

    Examples:
        # Update specific fields in Google Doc
        coursecraft course-outlines update my-course --type google_doc --name "New Name"

        # Update Google Doc from parsed markdown file
        coursecraft course-outlines update my-course --type google_doc -f outline.md

        # Update Airtable from markdown file
        coursecraft course-outlines update my-course --type database -f outline.md

        # Update Airtable by parsing a Google Doc
        coursecraft course-outlines update my-course --type database -l "https://docs.google.com/..."

        # Update a specific module in Google Doc
        coursecraft course-outlines update my-course --type google_doc --module 2 \\
            --module-name "Advanced Features" --module-duration "9"

        # Update module from content file
        coursecraft course-outlines update my-course --type google_doc --module 2 \\
            --module-content-file module2.txt --module-duration "9 min"
    """
    try:
        # Parse and validate type parameter
        update_types = _parse_type_param(type_param)

        # Validate parameter combinations
        if "google_doc" in update_types and course_outline_link:
            print_error("--course-outline-link cannot be used with --type google_doc")
            print_info("For google_doc type, use CLI params or --course-outline-file to provide data.")
            raise typer.Exit(1)

        if "database" in update_types:
            if not course_outline_file and not course_outline_link:
                print_error("--type database requires --course-outline-file or --course-outline-link")
                raise typer.Exit(1)
            if course_outline_file and course_outline_link:
                print_error("Cannot specify both --course-outline-file and --course-outline-link for database type")
                raise typer.Exit(1)

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

        if module is not None and "database" in update_types and "google_doc" not in update_types:
            print_error("Module updates only work with --type google_doc")
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
            learning_objectives=learning_objectives,
            notes=notes,
        )

        # For google_doc type, check we have data to update (either course fields or module)
        if "google_doc" in update_types:
            if not cli_fields and not course_outline_file and module is None:
                print_error("--type google_doc requires field params, --course-outline-file, or --module")
                print_info("Provide at least one field to update (e.g., --name, --learning-objectives, --module)")
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
            doc_link = course_record.get('fields', {}).get('Pluralsight Course Outline Link', '')
            if not doc_link:
                print_error("Course has no Google Doc link set in 'Pluralsight Course Outline Link' field")
                raise typer.Exit(1)

            # Build fields to update
            fields_to_update = dict(cli_fields)

            # If file provided, parse it and merge (file values take precedence)
            if course_outline_file:
                file_fields = _parse_markdown_to_course_fields(course_outline_file)
                # CLI params override file values
                for k, v in cli_fields.items():
                    file_fields[k] = v
                fields_to_update = file_fields

            # Build module updates if module is specified
            module_table_updates = []
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

                # Dynamically locate the Course Organization table — its index
                # varies by document (e.g. some docs have an "Approved Date"
                # table first, shifting indices). Never hardcode.
                course_org_table_idx = find_course_organization_table_index(doc_link)

                # Build the update for the module table
                module_table_updates = build_module_table_updates(
                    module_number=module,
                    content=final_module_content,
                    duration=module_duration,
                    table_index=course_org_table_idx,
                )

                if module_table_updates:
                    print_info(f"Updating Module {module} in Google Doc")

            # Count total updates
            field_count = len(fields_to_update)
            module_count = len(module_table_updates)
            total_desc = []
            if field_count:
                total_desc.append(f"{field_count} course field(s)")
            if module_count:
                total_desc.append(f"Module {module}")

            print_info(f"Updating Google Doc table cells: {', '.join(total_desc) if total_desc else 'no updates'}")
            result = _update_google_doc_partial(
                doc_link,
                fields=fields_to_update if fields_to_update else None,
                module_updates=module_table_updates if module_table_updates else None
            )

            updates_count = result.get('updates', 0)
            doc_url = result.get('url', doc_link)
            print_info(f"URL: {doc_url}")
            results.append(("Google Doc", f"Updated {updates_count} table cell(s)"))

        if "database" in update_types:
            result_msg = _update_database(
                client, course_record_id, course_outline_file, course_outline_link
            )
            results.append(("Database", result_msg))

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
