"""Output parsing utilities for CLI wrapper.

This module provides utilities to parse various output formats from
underlying CLI tools and transform them into standard Python data structures.
"""
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Union, Any, Optional


def format_local_time(timestamp: str, format: str = '%b %d %H:%M') -> str:
    """
    Convert an ISO timestamp to local timezone and format it.

    Use this function to display ALL timestamps in the CLI to ensure
    consistent local timezone display across all commands.

    Args:
        timestamp: ISO format timestamp (e.g., "2025-01-13T14:30:45Z" or "2025-01-13T14:30:45+00:00")
        format: strftime format string (default: "Jan 13 14:30")

    Returns:
        Formatted time string in local timezone, or original timestamp if parsing fails
    """
    if not timestamp:
        return ''

    try:
        # Parse ISO timestamp - handle 'Z' suffix or timezone offset
        if timestamp.endswith('Z'):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(timestamp)

        # Convert to local timezone
        local_dt = dt.astimezone()

        return local_dt.strftime(format)
    except (ValueError, AttributeError):
        # Fallback: return truncated timestamp if parsing fails
        return timestamp[:16] if len(timestamp) > 16 else timestamp


def format_local_time_only(timestamp: str) -> str:
    """
    Convert an ISO timestamp to local timezone and return just the time portion.

    Args:
        timestamp: ISO format timestamp (e.g., "2025-01-13T14:30:45Z")

    Returns:
        Time string in HH:MM:SS format in local timezone
    """
    return format_local_time(timestamp, '%H:%M:%S')


class OutputFormat(Enum):
    """Supported output formats from underlying CLIs."""
    AUTO = "auto"       # Auto-detect format
    JSON = "json"       # JSON output
    CSV = "csv"         # CSV/TSV output
    TABLE = "table"     # Fixed-width table
    LINES = "lines"     # One item per line
    KEY_VALUE = "kv"    # Key: Value pairs


def parse_cli_output(
    output: str,
    format: OutputFormat = OutputFormat.AUTO,
) -> Union[Dict, List, str]:
    """
    Parse CLI output into structured data.

    Args:
        output: Raw CLI output string
        format: Expected output format (auto-detect by default)

    Returns:
        Parsed data as dict, list, or original string
    """
    output = output.strip()

    if not output:
        return {}

    if format == OutputFormat.AUTO:
        format = _detect_format(output)

    parsers = {
        OutputFormat.JSON: _parse_json,
        OutputFormat.CSV: _parse_csv,
        OutputFormat.TABLE: _parse_table,
        OutputFormat.LINES: _parse_lines,
        OutputFormat.KEY_VALUE: _parse_key_value,
    }

    parser = parsers.get(format, lambda x: x)
    try:
        return parser(output)
    except Exception:
        # Fall back to returning raw output as lines
        return _parse_lines(output)


def _detect_format(output: str) -> OutputFormat:
    """Auto-detect the format of CLI output."""
    output = output.strip()

    # Check for JSON
    if output.startswith('{') or output.startswith('['):
        try:
            json.loads(output)
            return OutputFormat.JSON
        except json.JSONDecodeError:
            pass

    lines = output.split('\n')

    # Check for CSV (has commas and consistent columns)
    if len(lines) > 1:
        first_commas = lines[0].count(',')
        if first_commas > 0 and all(line.count(',') == first_commas for line in lines[:5] if line):
            return OutputFormat.CSV

    # Check for key-value pairs (more than half of lines match pattern)
    kv_pattern = r'^[\w\s\-_]+:\s*.+$'
    kv_lines = len([l for l in lines if re.match(kv_pattern, l)])
    if kv_lines > 0 and kv_lines >= len([l for l in lines if l.strip()]) * 0.5:
        return OutputFormat.KEY_VALUE

    # Check for table (consistent whitespace alignment with 2+ spaces as delimiter)
    if len(lines) > 1 and '  ' in lines[0]:
        # Count non-empty lines with consistent spacing patterns
        spaced_lines = [l for l in lines if '  ' in l]
        if len(spaced_lines) > len(lines) * 0.5:
            return OutputFormat.TABLE

    # Default to lines
    return OutputFormat.LINES


def _parse_json(output: str) -> Union[Dict, List]:
    """Parse JSON output."""
    return json.loads(output)


def _parse_csv(output: str, delimiter: str = ',') -> List[Dict]:
    """Parse CSV/TSV output into list of dicts."""
    lines = output.strip().split('\n')
    if len(lines) < 2:
        # Single line - return as list with one item
        if lines and lines[0].strip():
            values = [v.strip() for v in lines[0].split(delimiter)]
            return [{"value": v} for v in values if v]
        return []

    # First line is header
    headers = [h.strip() for h in lines[0].split(delimiter)]

    result = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = [v.strip() for v in line.split(delimiter)]
        row = dict(zip(headers, values))
        result.append(row)

    return result


def _parse_table(output: str) -> List[Dict]:
    """
    Parse fixed-width table output.

    Attempts to detect column boundaries from whitespace patterns.
    """
    lines = output.strip().split('\n')
    if not lines:
        return []

    # Skip separator lines (all dashes, equals, or whitespace)
    content_lines = [l for l in lines if not re.match(r'^[-=\s]+$', l) and l.strip()]

    if not content_lines:
        return []

    # If only one line, treat as single-column list
    if len(content_lines) == 1:
        return [{"name": content_lines[0].strip()}]

    # Assume first line is header
    header_line = content_lines[0]

    # Find column boundaries by looking for runs of 2+ spaces
    boundaries = [0]
    in_space = False
    space_start = 0
    for i, char in enumerate(header_line):
        if char == ' ':
            if not in_space:
                space_start = i
                in_space = True
        elif in_space:
            if i - space_start >= 2:  # At least 2 spaces = column boundary
                boundaries.append(i)
            in_space = False
    boundaries.append(len(header_line) + 100)  # End boundary with buffer

    # Extract headers
    headers = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        if start < len(header_line):
            header = header_line[start:min(end, len(header_line))].strip()
            if header:
                headers.append(header)

    # If no headers found, treat as lines
    if not headers:
        return _parse_lines(output)

    # Parse data rows
    result = []
    for line in content_lines[1:]:
        if not line.strip():
            continue

        values = []
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1]
            if start < len(line):
                value = line[start:min(end, len(line))].strip()
                values.append(value)
            else:
                values.append('')

        if values:
            # Pad values to match headers or trim
            while len(values) < len(headers):
                values.append('')
            row = dict(zip(headers, values[:len(headers)]))
            result.append(row)

    return result


def _parse_lines(output: str) -> List[Dict]:
    """Parse output as one item per line."""
    lines = output.strip().split('\n')
    result = []
    for line in lines:
        line = line.strip()
        if line:
            result.append({"name": line})
    return result


def _parse_key_value(output: str, delimiter: str = ':') -> Dict[str, str]:
    """Parse key: value formatted output."""
    result = {}
    for line in output.strip().split('\n'):
        if delimiter in line:
            key, _, value = line.partition(delimiter)
            key = key.strip()
            value = value.strip()
            if key:
                result[key] = value
    return result


# ==================== Custom Parsers ====================
# Add custom parsing functions for specific CLI output formats below

def parse_whisper_list(output: str) -> List[Dict]:
    """
    Parse whisper list command output.

    TODO: Customize this for your CLI's specific output format.

    Example patterns to handle:
        - lpass ls: "Group/Name [id: 12345]"
        - aws s3 ls: "2024-01-01 12:00:00 bucket-name"
        - gh repo list: "owner/repo  description  public  2024-01-01"
    """
    items = []

    # Example: Parse "Name [id: 12345]" format (like lpass)
    # pattern = r'^(.+?)\s+\[id:\s*(\d+)\]$'
    # for line in output.strip().split('\n'):
    #     match = re.match(pattern, line.strip())
    #     if match:
    #         items.append({
    #             "name": match.group(1).strip(),
    #             "id": match.group(2),
    #         })
    #     elif line.strip():
    #         items.append({"name": line.strip()})

    # Default: Use auto-detection
    return parse_cli_output(output, OutputFormat.AUTO)


def parse_whisper_item(output: str) -> Dict:
    """
    Parse whisper show/get command output.

    TODO: Customize this for your CLI's specific output format.

    Example patterns to handle:
        - lpass show: "Name: My Entry\nUsername: user@example.com"
        - JSON output from modern CLIs
        - Custom formats
    """
    # Default: Try auto-detection, preferring key-value
    result = parse_cli_output(output, OutputFormat.AUTO)

    if isinstance(result, dict):
        return result
    elif isinstance(result, list) and result:
        # If list, merge all dicts or return first
        if all(isinstance(item, dict) for item in result):
            merged = {}
            for item in result:
                merged.update(item)
            return merged
        return {"items": result}
    else:
        return {"raw": output.strip()}
