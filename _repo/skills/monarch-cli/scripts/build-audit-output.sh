#!/usr/bin/env python3
"""build-audit-output.sh — render a report-only audit table from an audit JSON file.

This script is the deterministic renderer for report-only Monarch audits (for
example a business-expense audit). It is the companion of `build-output.sh`,
which renders the approval-driven review table. Use this script when the task
classifies transactions into buckets and reports findings, and when the task
does NOT propose per-row category changes for approval.

It prints three blocks:
  1. the 10-column audit table,
  2. the summary totals block (one line per bucket plus a grand total),
  3. the count reconciliation block.

Every `recommended_category` is validated against the live Monarch category map.
Every row must carry a known bucket. The script exits non-zero with field-level
errors when anything is malformed, unknown, or unclassified. There is no
fallback and no silent repair.

Usage:
  build-audit-output.sh --audit PATH                  # render the audit report to stdout
  build-audit-output.sh --audit -                     # read the audit JSON from stdin
  build-audit-output.sh --audit PATH --validate-only  # exit 0 if valid, 1 + errors otherwise
  build-audit-output.sh --audit PATH --categories PATH  # use a saved category map

Category map source (exactly one path, chosen explicitly):
  * default            — run `monarch categories list --limit 500` live.
  * --categories PATH  — read the map from PATH. PATH holds either a raw
                         `monarch categories list` array, or a `prepare-review.sh`
                         output document that contains a `categories` array.
                         A malformed file is an error. The script does not fall
                         back to the live command.

Audit JSON schema (one row per audited transaction, INCLUDING rows that are
already categorized correctly):
  {
    "scope_label": "Geek Life business expense audit — 2026-01-01..2026-08-13",
    "source_transaction_count": 17,               # int, must equal len(rows)
    "rows": [
      {
        "row": 1,                                 # int, 1-based, sequential
        "transaction_id": "243...",
        "date": "2026-03-04",                     # YYYY-MM-DD
        "account": "Chase Business Checking",
        "merchant": "Amazon",
        "amount": -171.96,
        "current_category": "Shopping",           # live category name, or "Uncategorized"
        "bucket": "business cost",                # business cost | owner draw | miscategorization
        "recommended_category": "Office Supplies",  # must exist in the live category map
        "confidence": "high",                     # high | medium | low
        "evidence": "Invoice 8842 lists two office chairs."
      },
      ...
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

REQUIRED_ROOT_FIELDS = ["scope_label", "source_transaction_count", "rows"]

REQUIRED_ROW_FIELDS = [
    "row", "transaction_id", "date", "account", "merchant", "amount",
    "current_category", "bucket", "recommended_category", "confidence",
    "evidence",
]

# Fixed render order. Every bucket prints in the summary, including empty ones.
ALLOWED_BUCKETS = ["business cost", "owner draw", "miscategorization"]

ALLOWED_CONFIDENCE = ["high", "medium", "low"]

UNCATEGORIZED = "Uncategorized"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_json_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def category_names_from_live_cli() -> set[str]:
    proc = subprocess.run(
        ["monarch", "categories", "list", "--limit", "500"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"monarch categories list failed (exit {proc.returncode}):\n{proc.stderr}\n"
        )
        sys.exit(proc.returncode)
    return category_names_from_payload(json.loads(proc.stdout), "monarch categories list")


def category_names_from_payload(payload: object, source: str) -> set[str]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        if "categories" not in payload:
            sys.stderr.write(
                f"JSON_CONTRACT_MISMATCH: {source} object has no 'categories' key; "
                f"keys={sorted(payload)}\n"
            )
            sys.exit(2)
        records = payload["categories"]
    else:
        sys.stderr.write(
            f"JSON_CONTRACT_MISMATCH: {source} root must be a list or an object, "
            f"got {type(payload).__name__}\n"
        )
        sys.exit(2)

    if not isinstance(records, list) or not records:
        sys.stderr.write(f"JSON_CONTRACT_MISMATCH: {source} categories must be a non-empty array\n")
        sys.exit(2)

    names: set[str] = set()
    for i, record in enumerate(records):
        if not isinstance(record, dict) or not record.get("name"):
            sys.stderr.write(f"MISSING_JSON_PATH: {source} categories[{i}].name\n")
            sys.exit(2)
        names.add(record["name"])
    return names


def load_category_names(categories_path: str | None) -> set[str]:
    if categories_path is None:
        return category_names_from_live_cli()
    raw = load_json_text(categories_path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"invalid JSON in --categories input: {e}\n")
        sys.exit(2)
    return category_names_from_payload(payload, f"--categories {categories_path}")


def validate(audit: dict, category_names: set[str]) -> list[str]:
    errors: list[str] = []

    if not isinstance(audit, dict):
        return [f"audit root must be an object, got {type(audit).__name__}"]

    missing_root = [f for f in REQUIRED_ROOT_FIELDS if f not in audit]
    if missing_root:
        return [f"audit is missing root fields {missing_root}"]

    if not isinstance(audit["scope_label"], str) or not audit["scope_label"].strip():
        errors.append("scope_label must be a non-empty string")

    count = audit["source_transaction_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append(f"source_transaction_count must be a non-negative integer, got {count!r}")

    rows = audit["rows"]
    if not isinstance(rows, list) or not rows:
        errors.append("audit.rows must be a non-empty array")
        return errors

    seen_ids: dict[str, int] = {}

    for i, row in enumerate(rows, start=1):
        prefix = f"row #{i}"
        if not isinstance(row, dict):
            errors.append(f"{prefix}: must be an object, got {type(row).__name__}")
            continue
        missing = [f for f in REQUIRED_ROW_FIELDS if f not in row]
        if missing:
            errors.append(f"{prefix}: missing fields {missing}")
            continue

        if row["row"] != i:
            errors.append(
                f"{prefix}: 'row' field is {row['row']!r}, expected {i} "
                "(rows must be sequential starting at 1)"
            )

        txn_id = row["transaction_id"]
        if not isinstance(txn_id, str) or not txn_id:
            errors.append(f"{prefix}: transaction_id must be a non-empty string")
        elif txn_id in seen_ids:
            errors.append(
                f"{prefix}: duplicate transaction_id {txn_id!r} (first seen in row #{seen_ids[txn_id]})"
            )
        else:
            seen_ids[txn_id] = i

        if not isinstance(row["date"], str) or not DATE_RE.match(row["date"]):
            errors.append(f"{prefix}: date must match YYYY-MM-DD, got {row['date']!r}")

        for field in ("account", "merchant", "evidence"):
            if not isinstance(row[field], str) or not row[field].strip():
                errors.append(f"{prefix}: {field} must be a non-empty string")

        if not isinstance(row["amount"], (int, float)) or isinstance(row["amount"], bool):
            errors.append(f"{prefix}: amount must be a number")

        current = row["current_category"]
        if not isinstance(current, str) or not current:
            errors.append(f"{prefix}: current_category must be a non-empty string")
        elif current != UNCATEGORIZED and current not in category_names:
            errors.append(
                f"{prefix}: current_category {current!r} is not in the Monarch category map "
                f"(use an exact category name or {UNCATEGORIZED!r})"
            )

        bucket = row["bucket"]
        if not isinstance(bucket, str) or not bucket.strip():
            errors.append(
                f"{prefix}: UNCLASSIFIED ROW — bucket is empty; one of {ALLOWED_BUCKETS} is required"
            )
        elif bucket not in ALLOWED_BUCKETS:
            errors.append(
                f"{prefix}: UNCLASSIFIED ROW — bucket {bucket!r} is unknown; "
                f"use one of {ALLOWED_BUCKETS} (exact lowercase)"
            )

        recommended = row["recommended_category"]
        if not isinstance(recommended, str) or not recommended:
            errors.append(f"{prefix}: recommended_category must be a non-empty string")
        elif recommended not in category_names:
            errors.append(
                f"{prefix}: recommended_category {recommended!r} does not exist in the live "
                f"Monarch category map ({len(category_names)} categories loaded)"
            )

        confidence = row["confidence"]
        if not isinstance(confidence, str) or confidence not in ALLOWED_CONFIDENCE:
            errors.append(
                f"{prefix}: confidence must be one of {ALLOWED_CONFIDENCE}, got {confidence!r}"
            )

    if isinstance(count, int) and not isinstance(count, bool) and count != len(rows):
        errors.append(
            f"count reconciliation failed: source_transaction_count={count} but "
            f"rows={len(rows)}; every audited transaction needs exactly one row"
        )

    return errors


def money(value: float) -> str:
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render(audit: dict) -> str:
    rows = audit["rows"]
    lines: list[str] = []

    lines.append(f"### Audit — {cell(audit['scope_label'])}")
    lines.append("")
    lines.append(
        "| # | Date | Account | Merchant | Amount | Current Category | Bucket | "
        "Recommended Category | Confidence | Evidence |"
    )
    lines.append(
        "|---|------|---------|----------|--------|------------------|--------|"
        "----------------------|------------|----------|"
    )
    for r in rows:
        lines.append(
            f"| {r['row']} | {cell(r['date'])} | {cell(r['account'])} | {cell(r['merchant'])} "
            f"| {money(r['amount'])} | {cell(r['current_category'])} | {cell(r['bucket'])} "
            f"| {cell(r['recommended_category'])} | {cell(r['confidence'])} | {cell(r['evidence'])} |"
        )

    # Summary totals
    lines.append("")
    lines.append("### Summary Totals")
    lines.append("")
    lines.append("| Bucket | Rows | Amount |")
    lines.append("|--------|------|--------|")
    bucket_counts = {b: 0 for b in ALLOWED_BUCKETS}
    bucket_amounts = {b: 0.0 for b in ALLOWED_BUCKETS}
    for r in rows:
        bucket_counts[r["bucket"]] += 1
        bucket_amounts[r["bucket"]] += r["amount"]
    for bucket in ALLOWED_BUCKETS:
        lines.append(f"| {bucket} | {bucket_counts[bucket]} | {money(bucket_amounts[bucket])} |")
    lines.append(f"| **Total** | {len(rows)} | {money(sum(bucket_amounts.values()))} |")

    # Count reconciliation
    changed = sum(1 for r in rows if r["recommended_category"] != r["current_category"])
    unchanged = len(rows) - changed
    lines.append("")
    lines.append("### Count Reconciliation")
    lines.append("")
    lines.append("| Check | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Source transactions | {audit['source_transaction_count']} |")
    lines.append(f"| Rendered rows | {len(rows)} |")
    lines.append(f"| Rows by bucket (sum) | {sum(bucket_counts.values())} |")
    lines.append(f"| Unique transaction IDs | {len({r['transaction_id'] for r in rows})} |")
    lines.append(f"| Category changes recommended | {changed} |")
    lines.append(f"| Already correct | {unchanged} |")
    lines.append("| Reconciled | PASS |")

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--audit", help="path to audit JSON, or '-' for stdin")
    p.add_argument("--categories", help="path to a saved category map (default: live monarch CLI)")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    if not args.audit:
        sys.stderr.write("--audit is required (path to audit JSON, or '-' for stdin)\n")
        return 2

    raw = load_json_text(args.audit)
    try:
        audit = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"invalid JSON in audit input: {e}\n")
        return 2

    category_names = load_category_names(args.categories)

    errors = validate(audit, category_names)
    if errors:
        sys.stderr.write("audit JSON failed validation:\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    if args.validate_only:
        sys.stdout.write("OK\n")
        return 0

    sys.stdout.write(render(audit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
