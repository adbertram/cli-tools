#!/usr/bin/env bash
# Enumerate cli-tools and extract each README DESCRIPTION block as JSON.

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
# shellcheck disable=SC1091
. "$REPO_ROOT/_repo/_scripts/lib/log.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0")

Print a JSON array of CLI tool names, README paths, and DESCRIPTION text.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -gt 0 ]]; then
    log_error "unknown argument: $1"
    printf 'unknown argument: %s\n' "$1" >&2
    usage >&2
    exit 2
fi

log_info "starting $(basename "$0")"
log_info "extracting CLI README DESCRIPTION blocks from $REPO_ROOT"
REPO_ROOT="$REPO_ROOT" python3 - <<'PY'
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
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

print(json.dumps(records, indent=2))
PY
log_info "extracted CLI README DESCRIPTION blocks"
log_info "done"
