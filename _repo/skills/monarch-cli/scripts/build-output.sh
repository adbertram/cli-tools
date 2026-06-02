#!/usr/bin/env python3
"""build-output.sh — render the review table from a decisions JSON file.

This script prints the main 8-column review table. It validates the decisions
JSON against the output-format spec and exits non-zero with a descriptive error
if anything is malformed. The transaction IDs and rule commands stay in the
decisions JSON for `apply-approved-updates.sh` to consume — they are not
rendered into the human-facing output.

Usage:
  build-output.sh --decisions PATH         # render table + sections to stdout
  build-output.sh --decisions PATH --validate-only   # exit 0 if valid, 1 + errors otherwise
  build-output.sh --decisions -            # read decisions JSON from stdin

Decisions JSON schema (one row per reviewed transaction, INCLUDING
already-correct transactions):
  {
    "rows": [
      {
        "row": 1,                                       # int, 1-based, sequential
        "transaction_id": "243...",
        "vendor": "Holiday World...",
        "amount": -171.96,
        "description": "Card Hold / HOLIDAY WORLD ...",
        "current_category": "Entertainment & Recreation",
        "suggested_category": "(unchanged)",            # or category name, or "(needs your input)"
        "needs_input": false,
        "recommended_rule": "Apply once — suppressed: already correct",
        "rule_command": null                            # required (string) when recommended_rule starts with "Apply + create rule:"
      },
      ...
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import sys

REQUIRED_FIELDS = [
    "row", "transaction_id", "vendor", "amount", "description",
    "current_category", "suggested_category", "needs_input",
    "recommended_rule", "rule_command",
]

ALLOWED_RULE_PREFIXES = (
    "Apply once — suppressed: ",
    "Apply + create rule: ",
    "No rule — needs input",
)

NEEDS_INPUT_SUGGESTED = "(needs your input)"
UNCHANGED_SUGGESTED = "(unchanged)"


def validate(decisions: dict) -> list[str]:
    errors: list[str] = []
    rows = decisions.get("rows")
    if not isinstance(rows, list) or not rows:
        return ["decisions.rows must be a non-empty array"]

    for i, row in enumerate(rows, start=1):
        prefix = f"row #{i}"
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        if missing:
            errors.append(f"{prefix}: missing fields {missing}")
            continue
        if row["row"] != i:
            errors.append(f"{prefix}: 'row' field is {row['row']!r}, expected {i} (rows must be sequential starting at 1)")
        if not isinstance(row["needs_input"], bool):
            errors.append(f"{prefix}: needs_input must be true/false, got {row['needs_input']!r}")
        if not isinstance(row["vendor"], str) or not row["vendor"]:
            errors.append(f"{prefix}: vendor must be a non-empty string")
        if not isinstance(row["transaction_id"], str) or not row["transaction_id"]:
            errors.append(f"{prefix}: transaction_id must be a non-empty string")
        if not isinstance(row["amount"], (int, float)):
            errors.append(f"{prefix}: amount must be a number")
        suggested = row["suggested_category"]
        if not isinstance(suggested, str) or not suggested:
            errors.append(f"{prefix}: suggested_category must be a non-empty string")
        rec = row["recommended_rule"]
        if not isinstance(rec, str) or not rec:
            errors.append(f"{prefix}: recommended_rule must be a non-empty string")
        elif not any(rec.startswith(p) or rec == p for p in ALLOWED_RULE_PREFIXES):
            errors.append(
                f"{prefix}: recommended_rule {rec!r} must start with one of "
                f"'Apply once — suppressed: ', 'Apply + create rule: ', or equal 'No rule — needs input'"
            )

        # Cross-field invariants
        if row["needs_input"] is True:
            if suggested != NEEDS_INPUT_SUGGESTED:
                errors.append(
                    f"{prefix}: needs_input=true requires suggested_category={NEEDS_INPUT_SUGGESTED!r}, got {suggested!r}"
                )
            if rec != "No rule — needs input":
                errors.append(
                    f"{prefix}: needs_input=true requires recommended_rule='No rule — needs input', got {rec!r}"
                )

        if isinstance(rec, str) and rec.startswith("Apply + create rule: "):
            if not row.get("rule_command"):
                errors.append(f"{prefix}: 'Apply + create rule' rows must include a non-empty rule_command")
            elif not isinstance(row["rule_command"], str) or not row["rule_command"].startswith("monarch rules create"):
                errors.append(f"{prefix}: rule_command must start with 'monarch rules create'")

    return errors


def render(decisions: dict) -> str:
    rows = decisions["rows"]
    lines: list[str] = []

    # Main table
    lines.append("| # | Vendor | Amount | Description | Current Category | Suggested Category | Needs Input | Recommended Rule |")
    lines.append("|---|--------|--------|-------------|------------------|--------------------|-------------|------------------|")
    for r in rows:
        amount = f"-${abs(r['amount']):,.2f}" if r["amount"] < 0 else f"${r['amount']:,.2f}"
        desc = (r["description"] or "").replace("|", "\\|").replace("\n", " ")
        vendor = (r["vendor"] or "").replace("|", "\\|")
        cur_cat = (r["current_category"] or "Uncategorized").replace("|", "\\|")
        sug_cat = r["suggested_category"].replace("|", "\\|")
        rec = r["recommended_rule"].replace("|", "\\|")
        needs = "true" if r["needs_input"] else "false"
        lines.append(f"| {r['row']} | {vendor} | {amount} | {desc} | {cur_cat} | {sug_cat} | {needs} | {rec} |")

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--decisions", required=True, help="path to decisions JSON, or '-' for stdin")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    raw = sys.stdin.read() if args.decisions == "-" else open(args.decisions).read()
    try:
        decisions = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"invalid JSON in decisions input: {e}\n")
        return 2

    errors = validate(decisions)
    if errors:
        sys.stderr.write("decisions JSON failed validation:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    if args.validate_only:
        sys.stdout.write("OK\n")
        return 0

    sys.stdout.write(render(decisions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
