"""Google Docs course outline parser.

Parses a Google Doc course outline and returns the same JSON structure
as coursecraft courses get would return from Airtable.
"""
import re
import subprocess
import json
from typing import Dict, Optional, List, Any


# Mapping of Google Doc table cell labels to Airtable field names
COURSE_INFO_MAPPING = {
    "Course Title": "Name",
    "Author Name": "Author Name",
    "Opportunity ID": "Course ID",
    "Skill Path": "Skill Path",
    "Path Placement": "Path Placement",
    "Job Role": "Job Role",
    "Content Tags": "Content Tags",
    "Length Estimate in minutes": "Target Length (Min)",
    "Content Level": "Content Level",
    "Notes": "Notes",
}

COURSE_PLANNING_MAPPING = {
    "Learner Profile": "Learner Profile",
    "Learner Prerequisites": "(Required) Learner Prerequisites",
    "Storyline": "Storyline",
    "Platform/Tool Versions": "Platform/Tool Versions",
    "Short Description": "Short Description",
    "Long Description": "Long Description",
}

LEARNING_OBJECTIVES_MAPPING = {
    "Terminal": "terminal",
    "Enabling": "enabling",
}

# Bullet characters Google Docs templates use in front of objective lines.
_BULLET_CHARS = r'\s•●◦⁃*\-'

# Current Pluralsight template: objectives are bullet lines inside a single cell,
# each tagged with an inline "[Terminal]" / "[Enabling]" marker.
_OBJECTIVE_MARKER_RE = re.compile(
    rf'^[{_BULLET_CHARS}]*\[\s*(Terminal|Enabling)\s*\]\s*(.+)$',
    flags=re.IGNORECASE,
)

_LEADING_BULLET_RE = re.compile(rf'^[{_BULLET_CHARS}]+')


class LearningObjectivesParseError(RuntimeError):
    """A Learning Objectives table holds content but yielded no objectives."""


def extract_doc_id(url_or_id: str) -> str:
    """Extract document ID from a Google Docs URL or return as-is if already an ID."""
    match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', url_or_id)
    if match:
        return match.group(1)
    return url_or_id


def get_document_structure(doc_id: str) -> Dict[str, Any]:
    """Get the full document structure from Google Docs API."""
    result = subprocess.run(
        ["google", "docs", "get", doc_id],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get document: {result.stderr}")

    return json.loads(result.stdout)


def read_document_text(doc_id: str) -> str:
    """Return the document's full text, including text inside tables.

    Wraps `google docs read`, which extracts every run in the document. Use this rather
    than the outline table parser when the whole document is wanted verbatim.
    """
    result = subprocess.run(
        ["google", "docs", "read", doc_id],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to read document {doc_id}: {result.stderr}")

    return json.loads(result.stdout)["content"]


def _extract_cell_text(cell: Dict) -> str:
    """Extract text content from a table cell."""
    text = ""
    for content in cell.get('content', []):
        if 'paragraph' in content:
            for elem in content['paragraph'].get('elements', []):
                if 'textRun' in elem:
                    text += elem['textRun'].get('content', '')
    return text.strip()


def _normalize_doc_text(value: str) -> str:
    """Normalize Google Docs table text for resilient label matching."""
    return ' '.join((value or '').replace('\x0b', ' ').split()).lower()


def _parse_table(table: Dict) -> List[Dict[str, str]]:
    """Parse a table into a list of row dictionaries with first column as key."""
    rows = []
    table_rows = table.get('tableRows', [])

    for row in table_rows:
        cells = row.get('tableCells', [])
        if len(cells) >= 2:
            key = _extract_cell_text(cells[0])
            value = _extract_cell_text(cells[1])
            # Handle 3-column tables (like Course Organization)
            if len(cells) >= 3:
                third_col = _extract_cell_text(cells[2])
                rows.append({'key': key, 'value': value, 'extra': third_col})
            else:
                rows.append({'key': key, 'value': value})

    return rows


def _document_tables(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return document tables in visual order."""
    body = document.get('body', {})
    content = body.get('content', [])
    return [element['table'] for element in content if 'table' in element]


def outline_table_indices_from_document(document: Dict[str, Any]) -> Dict[str, int]:
    """Identify course outline tables by content instead of hardcoded indexes."""
    indices: Dict[str, int] = {}

    for table_idx, table in enumerate(_document_tables(document)):
        table_rows = _parse_table(table)
        table_type = _identify_table_type(table_rows)
        if table_type and table_type not in indices:
            indices[table_type] = table_idx

    return indices


def find_outline_table_indices(doc_id_or_url: str) -> Dict[str, int]:
    """Fetch a Google Doc and identify known course outline table indexes."""
    doc_id = extract_doc_id(doc_id_or_url)
    return outline_table_indices_from_document(get_document_structure(doc_id))


def _table_by_index(document: Dict[str, Any], table_index: int) -> Dict[str, Any]:
    tables = _document_tables(document)
    if table_index >= len(tables):
        raise RuntimeError(f"Document table {table_index} was not found")
    return tables[table_index]


def _find_row_by_first_cell(table: Dict[str, Any], labels: List[str]) -> int:
    """Find a row by matching candidate labels against the first cell."""
    normalized_labels = [_normalize_doc_text(label) for label in labels]

    for row_idx, row in enumerate(table.get('tableRows', [])):
        cells = row.get('tableCells', [])
        if not cells:
            continue
        first_cell = _normalize_doc_text(_extract_cell_text(cells[0]))
        for label in normalized_labels:
            if not label:
                continue
            if label.isdigit() and first_cell == label:
                return row_idx
            if not label.isdigit() and label in first_cell:
                return row_idx

    raise RuntimeError(
        "Could not find row matching any label: " + ", ".join(labels)
    )


def _table_row_labels(table: Dict[str, Any]) -> List[str]:
    """Return each row's first-cell text, whitespace-collapsed, for error messages."""
    labels = []
    for row in table.get('tableRows', []):
        cells = row.get('tableCells', [])
        if not cells:
            continue
        label = ' '.join(_extract_cell_text(cells[0]).replace('\x0b', ' ').split())
        if label:
            labels.append(label)
    return labels


def _resolve_field_row(
    field_name: str,
    table_type: str,
    table: Dict[str, Any],
    labels: List[str],
) -> int:
    """Resolve a field's target row, naming the field and the document's real rows on failure."""
    try:
        return _find_row_by_first_cell(table, labels)
    except RuntimeError as exc:
        raise RuntimeError(
            f"Field '{field_name}' has no target row in the Google Doc "
            f"'{table_type}' table. Tried row label(s): {', '.join(labels)}. "
            f"Rows present: {'; '.join(_table_row_labels(table))}. "
            f"This outline template has no row for '{field_name}' — remove that "
            "value from the update, or add the row to the document."
        ) from exc


def _find_learning_objectives_start_row(table: Dict[str, Any]) -> int:
    """Find the first editable objective row in a learning objectives table."""
    rows = table.get('tableRows', [])
    for row_idx, row in enumerate(rows):
        cells = row.get('tableCells', [])
        if len(cells) < 2:
            continue
        first = _normalize_doc_text(_extract_cell_text(cells[0]))
        second = _normalize_doc_text(_extract_cell_text(cells[1]))
        if first == "type" and ("objective" in second or second == "objectives"):
            return row_idx + 1
    return 1


def _identify_table_type(table_rows: List[Dict]) -> Optional[str]:
    """Identify the table type based on its first row content."""
    if not table_rows:
        return None

    first_row_key = table_rows[0].get('key', '').lower()

    first_row_key = _normalize_doc_text(first_row_key)

    if 'course information' in first_row_key or 'course title' in first_row_key:
        return 'course_info'
    elif 'course planning' in first_row_key or 'learner profile' in first_row_key:
        return 'course_planning'
    elif 'learning objectives' in first_row_key or first_row_key == 'terminal':
        return 'learning_objectives'
    elif 'course organization' in first_row_key or first_row_key.isdigit() or first_row_key == '1':
        return 'course_organization'

    return None


def _split_doc_lines(value: str) -> List[str]:
    """Split Google Docs cell text into display lines.

    Google Docs soft line breaks arrive as vertical tabs (\\x0b), paragraph
    breaks as newlines. Both separate objective lines.
    """
    return [line.strip() for line in re.split(r'[\n\x0b]', value or '') if line.strip()]


def _row_cell_texts(row: Dict) -> List[str]:
    """Return every cell text of a parsed table row in column order."""
    return [row.get('key', ''), row.get('value', ''), row.get('extra', '')]


def _is_learning_objectives_header_row(row: Dict) -> bool:
    """Identify the non-objective header rows of a Learning Objectives table."""
    key = _normalize_doc_text(row.get('key', ''))
    value = _normalize_doc_text(row.get('value', ''))

    if 'learning objectives' in key or 'what are objectives' in key:
        return True
    if key == 'type' and 'objective' in value:
        return True
    return False


def _extract_learning_objective_entries(table_rows: List[Dict]) -> List[Dict[str, str]]:
    """Extract ordered objective entries from either Pluralsight template shape.

    Older template: two-column rows whose first column is literally "Terminal"
    or "Enabling" and whose second column holds the objective text.

    Current template: a single cell of bullet lines, each carrying an inline
    "[Terminal]" or "[Enabling]" marker.

    Returns a list of ``{"type": "terminal"|"enabling", "text": str}`` entries
    in document order.
    """
    entries: List[Dict[str, str]] = []

    for row in table_rows:
        if _is_learning_objectives_header_row(row):
            continue

        key = _normalize_doc_text(row.get('key', ''))
        if key in ('terminal', 'enabling'):
            value = row.get('value', '').strip()
            if value:
                entries.append({'type': key, 'text': value})
            continue

        for cell_text in _row_cell_texts(row):
            for line in _split_doc_lines(cell_text):
                match = _OBJECTIVE_MARKER_RE.match(line)
                if match:
                    entries.append({
                        'type': match.group(1).lower(),
                        'text': match.group(2).strip(),
                    })

    return entries


def _format_learning_objectives(entries: List[Dict[str, str]]) -> str:
    """Render objective entries in the Airtable Learning Objectives format."""
    lines: List[str] = []
    terminal_count = 0

    for entry in entries:
        if entry['type'] == 'terminal':
            terminal_count += 1
            if lines:
                lines.append("")  # Blank line between terminal objectives
            # Strip leading number prefix if present ("1. Objective" -> "Objective")
            lines.append(f"Terminal {terminal_count}: {re.sub(r'^\d+\.\s*', '', entry['text'])}")
            continue

        # One "Enabling" cell can hold several already-bulleted lines.
        for enabling in _split_doc_lines(entry['text']):
            enabling = _LEADING_BULLET_RE.sub('', enabling).strip()
            if enabling:
                lines.append(f"- {enabling}")

    return '\n'.join(lines)


def _learning_objectives_body_text(table_rows: List[Dict]) -> str:
    """Return the whitespace-collapsed text of every non-header objective cell.

    Case is preserved so the failure message quotes the document verbatim.
    """
    parts = []
    for row in table_rows:
        if _is_learning_objectives_header_row(row):
            continue
        for cell_text in _row_cell_texts(row):
            collapsed = ' '.join((cell_text or '').replace('\x0b', ' ').split())
            if collapsed:
                parts.append(collapsed)
    return ' '.join(parts)


def _parse_learning_objectives(table_rows: List[Dict], *, doc_id: str) -> str:
    """Parse a Learning Objectives table into the Airtable string format.

    Returns a formatted string like:
    Terminal 1: Objective text
    - Enabling objective 1
    - Enabling objective 2

    Terminal 2: Objective text
    - Enabling objective 1

    Returns an empty string only when the table's objective rows are genuinely
    empty. Raises LearningObjectivesParseError when the table holds content
    that no supported template shape recognizes, so the loss is never silent.
    """
    entries = _extract_learning_objective_entries(table_rows)
    if entries:
        return _format_learning_objectives(entries)

    body_text = _learning_objectives_body_text(table_rows)
    if not body_text:
        return ''

    raise LearningObjectivesParseError(
        f"Learning Objectives table in document {doc_id} holds content but no "
        "recognizable objectives. Supported shapes are two-column rows keyed "
        "'Terminal'/'Enabling', or bullet lines marked '[Terminal]'/'[Enabling]'. "
        f"Found {len(body_text)} characters of unrecognized content, starting: "
        f"{body_text[:200]!r}"
    )


def _parse_modules(table_rows: List[Dict]) -> List[Dict[str, Any]]:
    """Parse course organization table into module structures."""
    modules = []

    for row in table_rows:
        key = row.get('key', '').strip()
        value = row.get('value', '').strip()
        duration = row.get('extra', '').strip()

        # Skip header row
        if 'course organization' in key.lower() or 'learn how to' in key.lower():
            continue

        # Check if key is a module number
        if key.isdigit():
            module_order = int(key)

            # Parse module content - extract name and details
            # Format: "Module Name\nLearning Objectives:...\nModule Layout:..."
            lines = value.split('\n')
            module_name = lines[0].strip() if lines else f"Module {module_order}"

            # Extract learning objectives section
            learning_objectives = ""
            module_layout = ""
            current_section = None

            for line in lines[1:]:
                line_lower = line.lower().strip()
                if line_lower.startswith('learning objectives:'):
                    current_section = 'objectives'
                    learning_objectives = line.split(':', 1)[1].strip() if ':' in line else ""
                elif line_lower.startswith('module layout:'):
                    current_section = 'layout'
                    module_layout = line.split(':', 1)[1].strip() if ':' in line else ""
                elif current_section == 'objectives':
                    learning_objectives += " " + line.strip()
                elif current_section == 'layout':
                    module_layout += " " + line.strip()

            # Parse duration (e.g., "_8__ Min (10-40 min)" or "8 min")
            duration_minutes = None
            if duration:
                duration_match = re.search(r'(\d+)', duration.replace('_', ''))
                if duration_match:
                    duration_minutes = int(duration_match.group(1))

            modules.append({
                'order': module_order,
                'name': module_name,
                'learning_objectives': learning_objectives.strip(),
                'module_layout': module_layout.strip(),
                'duration_minutes': duration_minutes,
                'raw_content': value
            })

    return modules


def parse_course_outline(doc_id_or_url: str) -> Dict[str, Any]:
    """
    Parse a Google Doc course outline and return structured JSON.

    Returns the same structure as coursecraft courses get would return,
    including course fields and nested modules.

    Args:
        doc_id_or_url: Google Doc ID or full URL

    Returns:
        Dict with 'id', 'fields', and 'modules' keys matching Airtable structure
    """
    doc_id = extract_doc_id(doc_id_or_url)
    document = get_document_structure(doc_id)

    # Initialize result structure to match Airtable format
    result = {
        'id': f"gdoc_{doc_id}",
        'fields': {},
        'modules': []
    }

    # Extract document title
    result['fields']['Document Title'] = document.get('title', '')

    # Parse all tables in the document
    body = document.get('body', {})
    content = body.get('content', [])

    for element in content:
        if 'table' not in element:
            continue

        table = element['table']
        table_rows = _parse_table(table)

        if not table_rows:
            continue

        table_type = _identify_table_type(table_rows)

        if table_type == 'course_info':
            for row in table_rows:
                key = row.get('key', '')
                value = row.get('value', '')
                # Normalize key by replacing newlines with spaces for matching
                key_normalized = ' '.join(key.split())

                # Find matching field name
                for doc_label, airtable_field in COURSE_INFO_MAPPING.items():
                    if doc_label.lower() in key_normalized.lower():
                        # Handle special conversions
                        if airtable_field == "Target Length (Min)":
                            # Extract number from string like "25 minutes"
                            match = re.search(r'(\d+)', value)
                            if match:
                                result['fields'][airtable_field] = int(match.group(1))
                        elif airtable_field == "Content Tags":
                            # Convert comma-separated string to array
                            tags = [tag.strip() for tag in value.split(',') if tag.strip()]
                            result['fields'][airtable_field] = tags
                        else:
                            result['fields'][airtable_field] = value
                        break

        elif table_type == 'course_planning':
            for row in table_rows:
                key = row.get('key', '')
                value = row.get('value', '')

                for doc_label, airtable_field in COURSE_PLANNING_MAPPING.items():
                    if doc_label.lower() in key.lower():
                        result['fields'][airtable_field] = value
                        break

        elif table_type == 'learning_objectives':
            objectives = _parse_learning_objectives(table_rows, doc_id=doc_id)
            result['fields']['Learning Objectives'] = objectives

        elif table_type == 'course_organization':
            modules = _parse_modules(table_rows)
            result['modules'] = modules

    return result


def get_course_from_google_doc(doc_id_or_url: str) -> Dict[str, Any]:
    """
    Get course data from a Google Doc in the same format as Airtable.

    This is the main entry point - returns data structured identically to
    what coursecraft courses get returns from Airtable.

    Args:
        doc_id_or_url: Google Doc ID or full URL

    Returns:
        Dict matching Airtable record structure with course and module data
    """
    return parse_course_outline(doc_id_or_url)


def generate_outline_markdown(course_data: Dict[str, Any], modules: List[Dict[str, Any]] = None) -> str:
    """
    Generate a course outline markdown document from course data.

    Creates markdown matching the standard course outline format used
    in Google Docs, suitable for updating via `google docs update`.

    Args:
        course_data: Course record from Airtable (with 'fields' key)
        modules: Optional list of module records. If not provided,
                 will use modules from course_data if present.

    Returns:
        Markdown string formatted as a course outline
    """
    fields = course_data.get('fields', course_data)
    lines = []

    # Course title header
    course_name = fields.get('Name', 'Untitled Course')
    lines.append(f"# {course_name} - Course Outline")
    lines.append("")

    # Course Information table
    lines.append("## Course Information")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")

    course_info_fields = [
        ("Course Title", "Name"),
        ("Author Name", "Author Name"),
        ("Opportunity ID", "Course ID"),
        ("Skill Path", "Skill Path"),
        ("Path Placement", "Path Placement"),
        ("Job Role", "Job Role"),
        ("Content Tags", "Content Tags"),
        ("Length Estimate", "Target Length (Min)"),
        ("Content Level", "Content Level"),
    ]

    for label, field_name in course_info_fields:
        value = fields.get(field_name, "")
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        if field_name == "Target Length (Min)" and value:
            value = f"{value} minutes"
        if value:
            lines.append(f"| {label} | {value} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Learning Objectives
    learning_objectives = fields.get('Learning Objectives', '')
    if learning_objectives:
        lines.append("## Learning Objectives")
        lines.append("")
        lines.append(learning_objectives)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Course Planning section
    lines.append("## Course Planning")
    lines.append("")

    planning_fields = [
        ("Learner Profile", "Learner Profile"),
        ("Learner Prerequisites", "(Required) Learner Prerequisites"),
        ("Storyline", "Storyline"),
        ("Platform/Tool Versions", "Platform/Tool Versions"),
        ("Short Description (250 char limit)", "Short Description"),
        ("Long Description", "Long Description"),
    ]

    for label, field_name in planning_fields:
        value = fields.get(field_name, "")
        if value:
            lines.append(f"### {label}")
            lines.append(value)
            lines.append("")

    lines.append("---")
    lines.append("")

    # Modules section
    module_list = modules or course_data.get('modules', [])
    if module_list:
        for module in module_list:
            mod_fields = module.get('fields', module)
            order = mod_fields.get('Order', mod_fields.get('order', ''))
            name = mod_fields.get('Name', mod_fields.get('name', ''))
            duration = mod_fields.get('Target Length (Min)', mod_fields.get('duration_minutes', ''))

            duration_str = f" ({duration} min)" if duration else ""
            lines.append(f"## Module {order}: {name}{duration_str}")
            lines.append("")

            # Module learning objectives
            mod_objectives = mod_fields.get('Learning Objectives', mod_fields.get('learning_objectives', ''))
            if mod_objectives:
                lines.append("### Learning Objectives")
                lines.append(mod_objectives)
                lines.append("")

            # Module layout
            mod_layout = mod_fields.get('Module Layout', mod_fields.get('module_layout', ''))
            if mod_layout:
                lines.append("### Module Layout")
                lines.append(mod_layout)
                lines.append("")

            lines.append("---")
            lines.append("")

    # Notes section
    notes = fields.get('Notes', '')
    if notes:
        lines.append("## Notes for Author")
        lines.append("")
        lines.append(notes)
        lines.append("")

    return '\n'.join(lines)


def update_google_doc_outline(doc_id_or_url: str, content: str) -> Dict[str, Any]:
    """
    Update a Google Doc with new outline content (replaces entire document).

    Args:
        doc_id_or_url: Google Doc ID or full URL
        content: Markdown content to write to the document

    Returns:
        Dict with document info from the update operation
    """
    doc_id = extract_doc_id(doc_id_or_url)

    # Write content to temp file and update via google CLI
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        result = subprocess.run(
            ["google", "docs", "update", doc_id, "--file", temp_path],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Failed to update document: {result.stderr}")

        return json.loads(result.stdout)
    finally:
        os.unlink(temp_path)


# Mapping of Airtable course fields to Google Doc table cells.
# Format: (table_type, row_label_candidates, column_index)
COURSE_INFO_TABLE_MAPPING = {
    "Name": ("course_info", ["Course Title"], 1),
    "Author Name": ("course_info", ["Author Name"], 1),
    "Course ID": ("course_info", ["Course Slug", "Course ID", "Opportunity ID"], 1),
    "Skill Path": ("course_info", ["Skill Path"], 1),
    "Path Placement": ("course_info", ["Path Placement"], 1),
    "Job Role": ("course_info", ["Job Role"], 1),
    "Content Tags": ("course_info", ["Content Tags"], 1),
    "Target Length (Min)": (
        "course_info",
        ["Length Estimate in minutes", "Length Estimate", "Length in minutes"],
        1,
    ),
    "Content Level": ("course_info", ["Content Level"], 1),
    "Notes": ("course_info", ["Notes", "Curriculum Notes"], 1),
}

COURSE_PLANNING_TABLE_MAPPING = {
    "Learner Profile": ("course_planning", ["Learner Profile"], 1),
    "(Required) Learner Prerequisites": (
        "course_planning",
        ["Learner Prerequisites"],
        1,
    ),
    "Storyline": ("course_planning", ["Storyline", "Purpose"], 1),
    "Author Notes": ("course_planning", ["Author Notes"], 1),
    "Platform/Tool Versions": ("course_planning", ["Platform/Tool Versions"], 1),
    "Short Description": ("course_planning", ["Short Description"], 1),
    "Long Description": ("course_planning", ["Long Description"], 1),
}


def parse_learning_objective_entries(objectives_text: str) -> List[Dict[str, str]]:
    """Parse terminal/enabling objective text into ordered table rows."""
    entries: List[Dict[str, str]] = []
    current_type: Optional[str] = None

    for raw_line in objectives_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line = re.sub(r'^\s*#+\s*', '', line)
        line = line.strip('* ')

        terminal_match = re.match(
            r'^(?:Terminal(?:\s+Objective)?(?:\s+\d+)?)\s*:?\s*(.+)$',
            line,
            flags=re.IGNORECASE,
        )
        if terminal_match:
            objective = terminal_match.group(1).strip()
            if objective:
                entries.append({"type": "Terminal", "objective": objective})
                current_type = "Terminal"
            continue

        enabling_match = re.match(
            r'^(?:[-*]\s*)?(?:Enabling(?:\s+Objective)?(?:\s+\d+)?)\s*:?\s*(.+)$',
            line,
            flags=re.IGNORECASE,
        )
        if enabling_match:
            objective = enabling_match.group(1).strip()
            if objective:
                entries.append({"type": "Enabling", "objective": objective})
                current_type = "Enabling"
            continue

        bullet_match = re.match(r'^[-*]\s+(.+)$', line)
        if bullet_match:
            objective = bullet_match.group(1).strip()
            if objective:
                entries.append({"type": "Enabling", "objective": objective})
                current_type = "Enabling"
            continue

        if current_type and entries:
            entries[-1]["objective"] = f"{entries[-1]['objective']} {line}".strip()

    return entries


def build_learning_objective_updates(
    objectives_text: str,
    *,
    table_index: int,
    table: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build updates for the Learning Objectives table using detected rows."""
    entries = parse_learning_objective_entries(objectives_text)
    if not entries:
        return []

    start_row = _find_learning_objectives_start_row(table)
    available_rows = len(table.get('tableRows', [])) - start_row
    if len(entries) > available_rows:
        raise RuntimeError(
            "Learning Objectives table has "
            f"{available_rows} editable row(s), but {len(entries)} objective row(s) "
            "were provided. Add rows to the Google Doc template before updating."
        )

    updates: List[Dict[str, Any]] = []
    for offset, entry in enumerate(entries):
        row = start_row + offset
        updates.append({
            "table": table_index,
            "row": row,
            "col": 0,
            "content": entry["type"],
        })
        updates.append({
            "table": table_index,
            "row": row,
            "col": 1,
            "content": entry["objective"],
        })

    # Clear leftover objective rows so stale template content does not remain.
    for row in range(start_row + len(entries), len(table.get('tableRows', []))):
        updates.append({
            "table": table_index,
            "row": row,
            "col": 0,
            "content": " ",
        })
        updates.append({
            "table": table_index,
            "row": row,
            "col": 1,
            "content": " ",
        })

    return updates


def validate_fields_fit_google_doc(
    fields: Dict[str, Any],
    *,
    document: Dict[str, Any],
    table_indices: Dict[str, int],
) -> List[str]:
    """Check that field values fit within the Google Doc template's table row counts.

    Returns a list of human-readable error strings; empty list = passes.
    Currently checks the Learning Objectives table row count.
    """
    errors: List[str] = []

    if fields.get("Learning Objectives"):
        entries = parse_learning_objective_entries(str(fields["Learning Objectives"]))
        if entries:
            table_idx = table_indices.get("learning_objectives", 2)
            try:
                table = _table_by_index(document, table_idx)
                start_row = _find_learning_objectives_start_row(table)
                available = len(table.get("tableRows", [])) - start_row
                if len(entries) > available:
                    deficit = len(entries) - available
                    errors.append(
                        f"Learning Objectives table has {available} editable row(s), "
                        f"but {len(entries)} objective row(s) were provided "
                        f"(need {deficit} more). "
                        f"Add rows to the Google Doc Learning Objectives table, "
                        f"or reduce the number of objectives."
                    )
            except RuntimeError as exc:
                errors.append(f"Cannot validate Learning Objectives table: {exc}")

    return errors


def build_table_updates_from_fields(
    fields: Dict[str, Any],
    *,
    document: Optional[Dict[str, Any]] = None,
    table_indices: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """
    Build a list of table cell updates from explicitly provided fields only.

    Unlike build_table_updates_from_course(), this function only generates
    updates for fields that are present in the input dict. Missing fields
    are NOT updated (partial update behavior).

    Args:
        fields: Dict of field names to values (Airtable field names)

    Returns:
        List of update dictionaries for google docs tables update command
    """
    updates = []
    table_indices = table_indices or {}

    # Course Information table (Table 0)
    for field_name, (table_type, labels, col_idx) in COURSE_INFO_TABLE_MAPPING.items():
        if field_name not in fields:
            continue

        value = fields[field_name]
        if value is None:
            continue

        # Format special values
        if field_name == "Target Length (Min)" and value:
            value = f"{value} minutes"
        elif field_name == "Content Tags" and isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, (int, float)):
            value = str(value)

        table_idx = table_indices.get(table_type, 0)
        update = {
            "table": table_idx,
            "col": col_idx,
            "content": str(value),
        }
        if document:
            update["row"] = _resolve_field_row(
                field_name, table_type, _table_by_index(document, table_idx), labels
            )
        else:
            update["label"] = labels[0]
        updates.append(update)

    # Course Planning table (Table 1)
    for field_name, (table_type, labels, col_idx) in COURSE_PLANNING_TABLE_MAPPING.items():
        if field_name not in fields:
            continue

        value = fields[field_name]
        if value:
            table_idx = table_indices.get(table_type, 1)
            update = {
                "table": table_idx,
                "col": col_idx,
                "content": str(value),
            }
            if document:
                update["row"] = _resolve_field_row(
                    field_name, table_type, _table_by_index(document, table_idx), labels
                )
            else:
                update["label"] = labels[0]
            updates.append(update)

    if "Learning Objectives" in fields and fields["Learning Objectives"]:
        table_type = "learning_objectives"
        table_idx = table_indices.get(table_type, 2)
        if document:
            updates.extend(build_learning_objective_updates(
                str(fields["Learning Objectives"]),
                table_index=table_idx,
                table=_table_by_index(document, table_idx),
            ))
        else:
            updates.append({
                "table": table_idx,
                "label": "Terminal",
                "col": 1,
                "content": str(fields["Learning Objectives"]),
            })

    return updates


def find_course_organization_table_index(doc_id_or_url: str) -> int:
    """
    Locate the Course Organization table by scanning the document's tables.

    Returns the 0-based index of the table whose first cell contains
    "course organization". Raises if not found — never falls back to a
    hardcoded index.
    """
    table_indices = find_outline_table_indices(doc_id_or_url)
    if "course_organization" in table_indices:
        return table_indices["course_organization"]

    raise RuntimeError(
        "Could not locate 'Course Organization' table in document "
        f"{extract_doc_id(doc_id_or_url)}."
    )


def build_module_table_updates(
    module_number: int,
    content: Optional[str] = None,
    duration: Optional[str] = None,
    table_index: int = 3,
    table: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Build table cell updates for a specific module in the Course Organization table.

    The Course Organization table (typically Table 3) has the structure:
    - Column 0: Module number (1, 2, 3, etc.)
    - Column 1: Module content (name, learning objectives, module layout)
    - Column 2: Duration (e.g., "9 min")

    Args:
        module_number: The module number (1, 2, 3, etc.) - determines the row
        content: Full content for column 1 (module name, objectives, layout)
        duration: Duration string for column 2 (e.g., "9 min" or just "9")
        table_index: Table index in document (default 3 for Course Organization)

    Returns:
        List of update dictionaries for google docs tables update command
    """
    updates = []

    if table:
        row = _find_row_by_first_cell(table, [str(module_number)])
    else:
        # Legacy fallback for callers without document context: row 0 is header.
        row = module_number

    if content is not None:
        updates.append({
            "table": table_index,
            "row": row,
            "col": 1,
            "content": content
        })

    if duration is not None:
        duration = duration.strip()
        if duration.isdigit():
            duration = f"{duration} min"
        elif re.search(r'\bminutes?\b', duration, flags=re.IGNORECASE):
            duration = re.sub(r'\bminutes?\b', 'min', duration, flags=re.IGNORECASE)
        elif re.search(r'\bmins?\b', duration, flags=re.IGNORECASE):
            duration = re.sub(r'\bmins?\b', 'min', duration, flags=re.IGNORECASE)
        else:
            duration = f"{duration} min"
        updates.append({
            "table": table_index,
            "row": row,
            "col": 2,
            "content": duration
        })

    return updates


def format_module_content(
    name: str,
    learning_objectives: Optional[str] = None,
    module_layout: Optional[str] = None
) -> str:
    """
    Format module content for the Course Organization table cell.

    Creates the standard format used in course outlines:
    Module Name

    Learning Objectives
    - Objective 1
    - Objective 2

    Module Layout
    Description text...

    Args:
        name: Module name
        learning_objectives: Learning objectives text (can include bullet points)
        module_layout: Module layout/description text

    Returns:
        Formatted content string for the module table cell
    """
    lines = [name, ""]

    if learning_objectives:
        lines.append("Learning Objectives")
        lines.append("")
        lines.append(learning_objectives)
        lines.append("")

    if module_layout:
        lines.append("Module Layout")
        lines.append("")
        lines.append(module_layout)

    return "\n".join(lines)


def build_table_updates_from_course(course_data: Dict[str, Any], modules: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Build a list of table cell updates from course data.

    Args:
        course_data: Course record from Airtable (with 'fields' key)
        modules: Optional list of module records

    Returns:
        List of update dictionaries for google docs tables update command
    """
    fields = course_data.get('fields', course_data)
    updates = build_table_updates_from_fields(fields)

    # Module updates (Table 3) - update module names and durations
    if modules:
        for module in modules:
            mod_fields = module.get('fields', module)
            order = mod_fields.get('Order', mod_fields.get('order'))
            name = mod_fields.get('Name', mod_fields.get('name', ''))
            duration = mod_fields.get('Target Length (Min)', mod_fields.get('duration_minutes'))

            if order and name:
                # Module name is in column 1, row = order (since row 0 is header)
                updates.append({
                    "table": 3,
                    "row": int(order),
                    "col": 1,
                    "content": name
                })

            if order and duration:
                # Duration is in column 2
                updates.append({
                    "table": 3,
                    "row": int(order),
                    "col": 2,
                    "content": f"{duration} min"
                })

    return updates


def update_google_doc_outline_tables(doc_id_or_url: str, course_data: Dict[str, Any], modules: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Update a Google Doc's table cells with course data (preserves table structure).

    Args:
        doc_id_or_url: Google Doc ID or full URL
        course_data: Course record from Airtable
        modules: Optional list of module records

    Returns:
        Dict with document info from the update operation
    """
    doc_id = extract_doc_id(doc_id_or_url)

    # Build updates from course data
    updates = build_table_updates_from_course(course_data, modules)

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

    return json.loads(result.stdout)
