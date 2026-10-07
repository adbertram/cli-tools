#!/usr/bin/env bash
# Enumerate cli-tools and extract each README DESCRIPTION block as JSON or compact markdown.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
. "$REPO_ROOT/_repo/_scripts/lib/log.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--json|--markdown] [--summary] [tool-name ...]

Print the available CLI tools with their README DESCRIPTION text.

  (default), --json
               JSON array of {name, readme, description} (full description)
  --markdown   Markdown list "- name: <full description>" for context injection
  --summary    Trim each tool's description to its first sentence. Applies to
               both --json (drops the readme field too, to stay compact) and
               --markdown. Use this for a full discovery pass across every
               tool; omit it to get full detail, normally after already
               filtering to one or a few tool names.
  tool-name    Optional exact tool name filter. May be passed more than once.
EOF
}

MODE="json"
SUMMARY="false"
FILTER_NAMES=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --json)
            MODE="json"
            shift
            ;;
        --markdown|--md)
            MODE="markdown"
            shift
            ;;
        --summary)
            SUMMARY="true"
            shift
            ;;
        -*)
            log_error "unknown argument: $1"
            printf 'unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
        *)
            FILTER_NAMES+=("$1")
            shift
            ;;
    esac
done

log_info "starting $(basename "$0")"
log_info "extracting CLI README DESCRIPTION blocks from $REPO_ROOT (mode=$MODE summary=$SUMMARY filters=${FILTER_NAMES[*]:-all})"
FILTER_NAMES_JOINED="$(IFS=$'\n'; printf '%s' "${FILTER_NAMES[*]:-}")"
REPO_ROOT="$REPO_ROOT" MODE="$MODE" SUMMARY="$SUMMARY" FILTER_NAMES="$FILTER_NAMES_JOINED" python3 - <<'PY'
import json
import os
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
mode = os.environ.get("MODE", "json")
summary = os.environ.get("SUMMARY") == "true"
filter_names = {name for name in os.environ.get("FILTER_NAMES", "").splitlines() if name}
records = []

pyproject_paths = list(repo_root.glob("*/pyproject.toml"))
personal_root = repo_root / "_personal"
if personal_root.is_dir():
    pyproject_paths.extend(personal_root.glob("*/pyproject.toml"))

for pyproject_path in sorted(pyproject_paths):
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

if filter_names:
    records = [record for record in records if record["name"] in filter_names]


def first_sentence(description):
    sentence = description.split(". ")[0].strip()
    if sentence and not sentence.endswith("."):
        sentence += "."
    return sentence


if summary:
    for record in records:
        record["description"] = first_sentence(record["description"])

if mode == "markdown":
    out = ["Available CLI tools. Before running one, load the `cli-tool` skill to learn its command structure — do not guess syntax:"]
    for record in records:
        description = record["description"]
        out.append(f"- {record['name']}: {description}" if description else f"- {record['name']}")
    print("\n".join(out))
elif summary:
    # --summary: keep it to name + one-line description, dropping readme too,
    # so a full discovery pass across every tool stays cheap.
    compact = [{"name": r["name"], "description": r["description"]} for r in records]
    print(json.dumps(compact, indent=2))
else:
    # Full detail: untruncated description plus the readme path.
    print(json.dumps(records, indent=2))
PY
log_info "extracted CLI README DESCRIPTION blocks"
log_info "done"
