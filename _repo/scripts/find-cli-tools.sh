#!/usr/bin/env bash
# Enumerate cli-tools and extract each README DESCRIPTION block as JSON or compact markdown.

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
# shellcheck disable=SC1091
. "$REPO_ROOT/_repo/_scripts/lib/log.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--markdown]

Print the available CLI tools with their README DESCRIPTION text.

  (default)    JSON array of {name, readme, description}
  --markdown   Compact markdown list "- name: <first sentence>" for context injection
EOF
}

MODE="json"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --markdown|--md)
            MODE="markdown"
            shift
            ;;
        *)
            log_error "unknown argument: $1"
            printf 'unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

log_info "starting $(basename "$0")"
log_info "extracting CLI README DESCRIPTION blocks from $REPO_ROOT (mode=$MODE)"
REPO_ROOT="$REPO_ROOT" MODE="$MODE" python3 - <<'PY'
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
mode = os.environ.get("MODE", "json")
records = []

for pyproject_path in sorted(repo_root.glob("*/pyproject.toml")):
    tool_dir = pyproject_path.parent
    readme_path = tool_dir / "README.md"
    if not readme_path.exists():
        continue

    lines = readme_path.read_text().splitlines()
    try:
        start = lines.index("## DESCRIPTION")
    except ValueError:
        description = ""
    else:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].startswith("## "):
                end = index
                break
        description = " ".join(line.strip() for line in lines[start + 1 : end] if line.strip())

    records.append(
        {
            "name": tool_dir.name,
            "readme": str(readme_path.relative_to(repo_root)),
            "description": description,
        }
    )

if mode == "markdown":
    out = ["Available CLI tools. Before running one, load the `cli-tool` skill to learn its command structure — do not guess syntax:"]
    for record in records:
        description = record["description"]
        first_sentence = description.split(". ")[0].strip()
        if first_sentence and not first_sentence.endswith("."):
            first_sentence += "."
        out.append(f"- {record['name']}: {first_sentence}" if first_sentence else f"- {record['name']}")
    print("\n".join(out))
else:
    print(json.dumps(records, indent=2))
PY
log_info "extracted CLI README DESCRIPTION blocks"
log_info "done"
