"""Strict output parsing helpers for wrapper CLIs.

Default scaffold expectation: the wrapped CLI can emit JSON for the commands
this wrapper calls. If the real CLI only emits text, replace this parser with
one that matches the real output shape instead of adding auto-detection logic.
"""

import json
from typing import Any


def parse_cli_output(output: str) -> Any:
    """Parse one JSON payload from the wrapped CLI."""
    payload = output.strip()
    if not payload:
        return []
    return json.loads(payload)


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

def parse_{{name}}_list(output: str) -> List[Dict]:
    """
    Parse {{cli_command}} list command output.

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


def parse_{{name}}_item(output: str) -> Dict:
    """
    Parse {{cli_command}} show/get command output.

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
