#!/usr/bin/env python3
"""build-audit-output.sh — render a deterministic report-only Monarch audit.

This script is the deterministic renderer for report-only Monarch audits (for
example a business-expense audit). It is the companion of `build-output.sh`,
which renders the approval-driven review table. Use this script when the task
classifies transactions into buckets and reports findings, and when the task
does NOT propose per-row category changes for approval.

It prints exactly three top-level blocks:
  1. the selected audit mode's item table,
  2. its summary totals and supporting cross-checks,
  3. its count reconciliation.

In legacy `--audit` mode, every `recommended_category` is validated against the
Monarch category map and every row must carry a known bucket. In
`--recurring-audit` mode, every item, exclusion, transaction ID, and declared
count is validated before rendering. The script exits non-zero with field-level
errors when anything is malformed, unknown, unclassified, duplicated, or
unreconciled. There is no fallback and no silent repair.

Usage:
  build-audit-output.sh --audit PATH                  # render the audit report to stdout
  build-audit-output.sh --audit -                     # read the audit JSON from stdin
  build-audit-output.sh --recurring-audit PATH        # render recurring expenses
  build-audit-output.sh --recurring-audit -           # read recurring JSON from stdin
  build-audit-output.sh --audit PATH --validate-only  # exit 0 if valid, 1 + errors otherwise
  build-audit-output.sh --audit PATH --categories PATH  # use a saved category map

`--audit` and `--recurring-audit` are mutually exclusive. `--validate-only`
works with either selected mode. `--categories` applies only to `--audit`.

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

Recurring-expense audit JSON schema:
  {
    "audit_kind": "recurring_expenses",
    "scope_label": "Bills account recurring expenses",
    "account": {"id": "acc-1", "name": "Bills"},
    "analysis_window": {
      "requested_start": "2025-01-01",
      "requested_end": "2026-08-22",
      "earliest_transaction_date": "2025-01-03",
      "latest_transaction_date": "2026-08-20",
      "source_transaction_count": 24,
      "history_limit": 500,
      "history_complete": true
    },
    "recurring_cross_check": {
      "monarch_streams_total": 12,
      "monarch_streams_matched_account": 3,
      "history_detected_items": 2,
      "history_only_items": 1,
      "monarch_only_items": 1,
      "evidence": "Raw Monarch recurring streams were cross-checked against history."
    },
    "items": [
      {
        "row": 1,
        "stable_name": "Example utility",
        "aliases": ["EXAMPLE UTIL"],
        "cadence": "monthly",
        "transaction_ids": ["txn-1", "txn-2"],
        "netting_transaction_ids": [],
        "observed_dates": ["2026-06-01", "2026-07-01"],
        "observed_amounts": [-50.0, -52.0],
        "occurrence_count": 2,
        "amount_range": {"min": 50.0, "max": 52.0},
        "detection_basis": "Two monthly charges.",
        "projection_window": "2026-06-01..2026-07-01",
        "projection_basis": "Mean observed monthly charge.",
        "normalized_monthly_average": 51.0,
        "status": "verified",
        "monarch_recurring_evidence": "Matched one Monarch recurring stream."
      }
    ],
    "excluded_transactions": [
      {
        "transaction_id": "txn-3",
        "date": "2026-07-02",
        "merchant": "Example refund",
        "amount": 10.0,
        "classification": "refund/reversal",
        "reason": "Refund is not a recurring charge."
      }
    ],
    "reconciliation": {
      "source_transactions": 3,
      "recurring_charge_transactions": 2,
      "netting_transactions": 0,
      "excluded_transactions": 1,
      "recurring_items": 1,
      "unique_transaction_ids": 3,
      "reconciled": true
    }
  }

Recurring cadence values are `monthly`, `quarterly`, `semiannual`, `annual`,
and `irregular recurring`. Item status is exactly `verified` or `UNVERIFIED`.
Exclusion classification is exactly `transfer`, `deposit/income`,
`one-off purchase`, `refund/reversal`, or `ambiguous`. Transaction IDs must be
globally unique across item charges, item netting IDs, and exclusions. Every
reconciliation count must equal the derived count and the unique ID union must
equal `analysis_window.source_transaction_count`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date

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

RECURRING_ROOT_FIELDS = [
    "audit_kind", "scope_label", "account", "analysis_window",
    "recurring_cross_check", "items", "excluded_transactions", "reconciliation",
]

ACCOUNT_FIELDS = ["id", "name"]

ANALYSIS_WINDOW_FIELDS = [
    "requested_start", "requested_end", "earliest_transaction_date",
    "latest_transaction_date", "source_transaction_count", "history_limit",
    "history_complete",
]

RECURRING_CROSS_CHECK_FIELDS = [
    "monarch_streams_total", "monarch_streams_matched_account",
    "history_detected_items", "history_only_items", "monarch_only_items",
    "evidence",
]

RECURRING_ITEM_FIELDS = [
    "row", "stable_name", "aliases", "cadence", "transaction_ids",
    "netting_transaction_ids", "observed_dates", "observed_amounts",
    "occurrence_count", "amount_range", "detection_basis", "projection_window",
    "projection_basis", "normalized_monthly_average", "status",
    "monarch_recurring_evidence",
]

AMOUNT_RANGE_FIELDS = ["min", "max"]

EXCLUSION_FIELDS = [
    "transaction_id", "date", "merchant", "amount", "classification", "reason",
]

RECONCILIATION_FIELDS = [
    "source_transactions", "recurring_charge_transactions", "netting_transactions",
    "excluded_transactions", "recurring_items", "unique_transaction_ids",
    "reconciled",
]

ALLOWED_CADENCES = [
    "monthly", "quarterly", "semiannual", "annual", "irregular recurring",
]

ALLOWED_RECURRING_STATUSES = ["verified", "UNVERIFIED"]

ALLOWED_EXCLUSION_CLASSIFICATIONS = [
    "transfer", "deposit/income", "one-off purchase", "refund/reversal", "ambiguous",
]


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


def is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def require_object_fields(
    value: object,
    path: str,
    required_fields: list[str],
    errors: list[str],
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object, got {type(value).__name__}")
        return False
    missing = [field for field in required_fields if field not in value]
    if missing:
        errors.append(f"{path} is missing fields {missing}")
        return False
    return True


def validate_nonempty_string(value: object, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-empty string")


def validate_date(value: object, path: str, errors: list[str]) -> date | None:
    if not isinstance(value, str) or not DATE_RE.match(value):
        errors.append(f"{path} must match YYYY-MM-DD, got {value!r}")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{path} must be a valid calendar date, got {value!r}")
        return None


def validate_recurring(audit: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(audit, dict):
        return [f"recurring audit root must be an object, got {type(audit).__name__}"]

    missing_root = [field for field in RECURRING_ROOT_FIELDS if field not in audit]
    if missing_root:
        return [f"recurring audit is missing root fields {missing_root}"]

    if audit["audit_kind"] != "recurring_expenses":
        errors.append(
            "audit_kind must be exactly 'recurring_expenses', "
            f"got {audit['audit_kind']!r}"
        )
    validate_nonempty_string(audit["scope_label"], "scope_label", errors)

    account = audit["account"]
    if require_object_fields(account, "account", ACCOUNT_FIELDS, errors):
        validate_nonempty_string(account["id"], "account.id", errors)
        validate_nonempty_string(account["name"], "account.name", errors)

    source_count: int | None = None
    analysis = audit["analysis_window"]
    if require_object_fields(
        analysis, "analysis_window", ANALYSIS_WINDOW_FIELDS, errors
    ):
        requested_start = validate_date(
            analysis["requested_start"], "analysis_window.requested_start", errors
        )
        requested_end = validate_date(
            analysis["requested_end"], "analysis_window.requested_end", errors
        )
        earliest = validate_date(
            analysis["earliest_transaction_date"],
            "analysis_window.earliest_transaction_date",
            errors,
        )
        latest = validate_date(
            analysis["latest_transaction_date"],
            "analysis_window.latest_transaction_date",
            errors,
        )
        if requested_start is not None and requested_end is not None and requested_start > requested_end:
            errors.append("analysis_window.requested_start must be on or before requested_end")
        if earliest is not None and latest is not None and earliest > latest:
            errors.append(
                "analysis_window.earliest_transaction_date must be on or before "
                "latest_transaction_date"
            )

        if (
            not is_integer(analysis["source_transaction_count"])
            or analysis["source_transaction_count"] < 0
        ):
            errors.append(
                "analysis_window.source_transaction_count must be a non-negative integer"
            )
        else:
            source_count = analysis["source_transaction_count"]
        if not is_integer(analysis["history_limit"]) or analysis["history_limit"] <= 0:
            errors.append("analysis_window.history_limit must be a positive integer")
        if not isinstance(analysis["history_complete"], bool):
            errors.append("analysis_window.history_complete must be a boolean")

    cross_check = audit["recurring_cross_check"]
    if require_object_fields(
        cross_check,
        "recurring_cross_check",
        RECURRING_CROSS_CHECK_FIELDS,
        errors,
    ):
        for field in RECURRING_CROSS_CHECK_FIELDS[:-1]:
            value = cross_check[field]
            if not is_integer(value) or value < 0:
                errors.append(
                    f"recurring_cross_check.{field} must be a non-negative integer"
                )
        validate_nonempty_string(
            cross_check["evidence"], "recurring_cross_check.evidence", errors
        )
        total = cross_check["monarch_streams_total"]
        matched = cross_check["monarch_streams_matched_account"]
        if is_integer(total) and is_integer(matched) and matched > total:
            errors.append(
                "recurring_cross_check.monarch_streams_matched_account cannot exceed "
                "monarch_streams_total"
            )

    items_value = audit["items"]
    if not isinstance(items_value, list) or not items_value:
        errors.append("items must be a non-empty array")
        items: list = []
    else:
        items = items_value

    exclusions_value = audit["excluded_transactions"]
    if not isinstance(exclusions_value, list):
        errors.append("excluded_transactions must be an array")
        exclusions: list = []
    else:
        exclusions = exclusions_value

    seen_ids: dict[str, str] = {}
    recurring_charge_count = 0
    netting_count = 0

    def validate_transaction_ids(
        values: object,
        path: str,
        require_nonempty: bool,
    ) -> int:
        if not isinstance(values, list) or (require_nonempty and not values):
            requirement = "a non-empty array" if require_nonempty else "an array"
            errors.append(f"{path} must be {requirement}")
            return 0
        for index, transaction_id in enumerate(values):
            id_path = f"{path}[{index}]"
            if not isinstance(transaction_id, str) or not transaction_id:
                errors.append(f"{id_path} must be a non-empty string")
            elif transaction_id in seen_ids:
                errors.append(
                    f"{id_path}: duplicate transaction_id {transaction_id!r}; "
                    f"first used at {seen_ids[transaction_id]}"
                )
            else:
                seen_ids[transaction_id] = id_path
        return len(values)

    for index, item in enumerate(items, start=1):
        path = f"items[{index - 1}]"
        if not require_object_fields(item, path, RECURRING_ITEM_FIELDS, errors):
            continue

        if not is_integer(item["row"]) or item["row"] != index:
            errors.append(
                f"{path}.row is {item['row']!r}, expected {index} "
                "(rows must be sequential starting at 1)"
            )
        validate_nonempty_string(item["stable_name"], f"{path}.stable_name", errors)

        aliases = item["aliases"]
        if not isinstance(aliases, list) or not aliases:
            errors.append(f"{path}.aliases must be a non-empty array")
        else:
            for alias_index, alias in enumerate(aliases):
                validate_nonempty_string(
                    alias, f"{path}.aliases[{alias_index}]", errors
                )

        if item["cadence"] not in ALLOWED_CADENCES:
            errors.append(
                f"{path}.cadence must be one of {ALLOWED_CADENCES}, "
                f"got {item['cadence']!r}"
            )

        charge_count = validate_transaction_ids(
            item["transaction_ids"], f"{path}.transaction_ids", True
        )
        recurring_charge_count += charge_count
        netting_count += validate_transaction_ids(
            item["netting_transaction_ids"],
            f"{path}.netting_transaction_ids",
            False,
        )

        observed_dates = item["observed_dates"]
        if not isinstance(observed_dates, list):
            errors.append(f"{path}.observed_dates must be an array")
            observed_date_count = 0
        else:
            observed_date_count = len(observed_dates)
            for observed_index, observed in enumerate(observed_dates):
                validate_date(
                    observed,
                    f"{path}.observed_dates[{observed_index}]",
                    errors,
                )

        observed_amounts = item["observed_amounts"]
        if not isinstance(observed_amounts, list):
            errors.append(f"{path}.observed_amounts must be an array")
            observed_amount_count = 0
        else:
            observed_amount_count = len(observed_amounts)
            for amount_index, amount in enumerate(observed_amounts):
                if not is_number(amount):
                    errors.append(
                        f"{path}.observed_amounts[{amount_index}] must be a number"
                    )

        occurrence_count = item["occurrence_count"]
        if not is_integer(occurrence_count) or occurrence_count <= 0:
            errors.append(f"{path}.occurrence_count must be a positive integer")
        else:
            for field, derived_count in (
                ("transaction_ids", charge_count),
                ("observed_dates", observed_date_count),
                ("observed_amounts", observed_amount_count),
            ):
                if occurrence_count != derived_count:
                    errors.append(
                        f"{path}.occurrence_count={occurrence_count} but "
                        f"len({field})={derived_count}"
                    )

        amount_range = item["amount_range"]
        if require_object_fields(
            amount_range, f"{path}.amount_range", AMOUNT_RANGE_FIELDS, errors
        ):
            range_min = amount_range["min"]
            range_max = amount_range["max"]
            if not is_number(range_min):
                errors.append(f"{path}.amount_range.min must be a number")
            if not is_number(range_max):
                errors.append(f"{path}.amount_range.max must be a number")
            if is_number(range_min) and is_number(range_max) and range_min > range_max:
                errors.append(f"{path}.amount_range.min must be <= amount_range.max")

        for field in (
            "detection_basis",
            "projection_window",
            "projection_basis",
            "monarch_recurring_evidence",
        ):
            validate_nonempty_string(item[field], f"{path}.{field}", errors)

        item_status = item["status"]
        if item_status not in ALLOWED_RECURRING_STATUSES:
            errors.append(
                f"{path}.status must be one of {ALLOWED_RECURRING_STATUSES}, "
                f"got {item_status!r}"
            )
        projection = item["normalized_monthly_average"]
        if item_status == "verified":
            if not is_number(projection) or projection < 0:
                errors.append(
                    f"{path}.normalized_monthly_average must be a number >= 0 "
                    "when status is 'verified'"
                )
        elif item_status == "UNVERIFIED" and projection is not None:
            errors.append(
                f"{path}.normalized_monthly_average must be null when status is 'UNVERIFIED'"
            )

    for index, exclusion in enumerate(exclusions):
        path = f"excluded_transactions[{index}]"
        if not require_object_fields(exclusion, path, EXCLUSION_FIELDS, errors):
            continue
        validate_transaction_ids([exclusion["transaction_id"]], path, True)
        validate_date(exclusion["date"], f"{path}.date", errors)
        validate_nonempty_string(exclusion["merchant"], f"{path}.merchant", errors)
        if not is_number(exclusion["amount"]):
            errors.append(f"{path}.amount must be a number")
        if exclusion["classification"] not in ALLOWED_EXCLUSION_CLASSIFICATIONS:
            errors.append(
                f"{path}.classification must be one of "
                f"{ALLOWED_EXCLUSION_CLASSIFICATIONS}, "
                f"got {exclusion['classification']!r}"
            )
        validate_nonempty_string(exclusion["reason"], f"{path}.reason", errors)

    reconciliation = audit["reconciliation"]
    if require_object_fields(
        reconciliation, "reconciliation", RECONCILIATION_FIELDS, errors
    ):
        for field in RECONCILIATION_FIELDS[:-1]:
            value = reconciliation[field]
            if not is_integer(value) or value < 0:
                errors.append(f"reconciliation.{field} must be a non-negative integer")

        derived_counts = {
            "source_transactions": source_count,
            "recurring_charge_transactions": recurring_charge_count,
            "netting_transactions": netting_count,
            "excluded_transactions": len(exclusions),
            "recurring_items": len(items),
            "unique_transaction_ids": len(seen_ids),
        }
        for field, derived_count in derived_counts.items():
            declared = reconciliation[field]
            if derived_count is not None and is_integer(declared) and declared != derived_count:
                errors.append(
                    f"reconciliation.{field}={declared} but derived count={derived_count}"
                )

        if reconciliation["reconciled"] is not True:
            errors.append("reconciliation.reconciled must be true")

    if source_count is not None and len(seen_ids) != source_count:
        errors.append(
            "unique transaction ID union does not equal "
            f"analysis_window.source_transaction_count: {len(seen_ids)} != {source_count}"
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


def markdown_cell(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def positive_money(value: float) -> str:
    return f"${abs(value):,.2f}"


def signed_money(value: float) -> str:
    if value < 0:
        return f"-${abs(value):,.2f}"
    if value > 0:
        return f"+${value:,.2f}"
    return "$0.00"


def positive_range(amount_range: dict) -> str:
    low, high = sorted(
        (abs(amount_range["min"]), abs(amount_range["max"]))
    )
    if low == high:
        return positive_money(low)
    return f"{positive_money(low)}–{positive_money(high)}"


def inclusive_date_range(dates: list[str]) -> str:
    if not dates:
        return "—"
    first = min(dates)
    last = max(dates)
    return first if first == last else f"{first}..{last}"


def render_recurring(audit: dict) -> str:
    items = audit["items"]
    analysis = audit["analysis_window"]
    cross_check = audit["recurring_cross_check"]
    reconciliation = audit["reconciliation"]
    exclusions = audit["excluded_transactions"]
    lines: list[str] = []

    lines.append(
        f"### Recurring Expense Audit — {markdown_cell(audit['scope_label'])}"
    )
    lines.append("")
    lines.append(
        "| # | Stable Name | Aliases | Cadence | Occurrences | Observed Dates | "
        "Observed Amounts | Amount Range | Normalized Monthly Projection | "
        "Detection Basis | Projection Window | Projection Basis | "
        "Monarch Recurring Evidence | Status |"
    )
    lines.append(
        "|---|-------------|---------|---------|-------------|----------------|"
        "------------------|--------------|-------------------------------|"
        "-----------------|-------------------|------------------|"
        "----------------------------|--------|"
    )
    for item in items:
        aliases = ", ".join(markdown_cell(alias) for alias in item["aliases"])
        dates = ", ".join(markdown_cell(value) for value in item["observed_dates"])
        amounts = ", ".join(signed_money(value) for value in item["observed_amounts"])
        normalized = (
            positive_money(item["normalized_monthly_average"])
            if item["status"] == "verified"
            else "UNVERIFIED"
        )
        lines.append(
            f"| {item['row']} | {markdown_cell(item['stable_name'])} | {aliases} | "
            f"{markdown_cell(item['cadence'])} | {item['occurrence_count']} | {dates} | "
            f"{amounts} | {positive_range(item['amount_range'])} | {normalized} | "
            f"{markdown_cell(item['detection_basis'])} | "
            f"{markdown_cell(item['projection_window'])} | "
            f"{markdown_cell(item['projection_basis'])} | "
            f"{markdown_cell(item['monarch_recurring_evidence'])} | "
            f"{markdown_cell(item['status'])} |"
        )

    verified_total = sum(
        item["normalized_monthly_average"]
        for item in items
        if item["status"] == "verified"
    )
    unverified_count = sum(1 for item in items if item["status"] == "UNVERIFIED")

    lines.append("")
    lines.append("### Summary Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Account ID | {markdown_cell(audit['account']['id'])} |")
    lines.append(f"| Account name | {markdown_cell(audit['account']['name'])} |")
    lines.append(
        "| Requested range | "
        f"{analysis['requested_start']}..{analysis['requested_end']} |"
    )
    lines.append(
        "| Exact analyzed transaction range | "
        f"{analysis['earliest_transaction_date']}..{analysis['latest_transaction_date']} |"
    )
    lines.append(
        f"| Source transaction count | {analysis['source_transaction_count']} |"
    )
    lines.append(f"| History limit | {analysis['history_limit']} |")
    lines.append(
        f"| History complete | {str(analysis['history_complete']).lower()} |"
    )
    lines.append(
        f"| Verified normalized monthly total | {positive_money(verified_total)} |"
    )
    lines.append(f"| UNVERIFIED items | {unverified_count} |")

    lines.append("")
    lines.append("#### Monarch Recurring Cross-Check")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(
        f"| Monarch streams total | {cross_check['monarch_streams_total']} |"
    )
    lines.append(
        "| Monarch streams matched account | "
        f"{cross_check['monarch_streams_matched_account']} |"
    )
    lines.append(
        f"| History-detected items | {cross_check['history_detected_items']} |"
    )
    lines.append(f"| History-only items | {cross_check['history_only_items']} |")
    lines.append(f"| Monarch-only items | {cross_check['monarch_only_items']} |")
    lines.append(
        f"| Evidence | {markdown_cell(cross_check['evidence'])} |"
    )

    lines.append("")
    lines.append("#### Exclusions and Ambiguities")
    lines.append("")
    lines.append(
        "| Classification | Count | Date Range | Total Amount | Merchants | Reasons |"
    )
    lines.append(
        "|----------------|-------|------------|--------------|-----------|---------|"
    )
    for classification in ALLOWED_EXCLUSION_CLASSIFICATIONS:
        group = [
            exclusion
            for exclusion in exclusions
            if exclusion["classification"] == classification
        ]
        dates = [exclusion["date"] for exclusion in group]
        total_amount = sum(exclusion["amount"] for exclusion in group)
        merchants = sorted({exclusion["merchant"] for exclusion in group})
        reasons = sorted({exclusion["reason"] for exclusion in group})
        lines.append(
            f"| {markdown_cell(classification)} | {len(group)} | "
            f"{inclusive_date_range(dates)} | {signed_money(total_amount)} | "
            f"{markdown_cell('; '.join(merchants) if merchants else '—')} | "
            f"{markdown_cell('; '.join(reasons) if reasons else '—')} |"
        )

    unique_ids = {
        transaction_id
        for item in items
        for transaction_id in (
            item["transaction_ids"] + item["netting_transaction_ids"]
        )
    }
    unique_ids.update(
        exclusion["transaction_id"] for exclusion in exclusions
    )
    derived_counts = {
        "source_transactions": analysis["source_transaction_count"],
        "recurring_charge_transactions": sum(
            len(item["transaction_ids"]) for item in items
        ),
        "netting_transactions": sum(
            len(item["netting_transaction_ids"]) for item in items
        ),
        "excluded_transactions": len(exclusions),
        "recurring_items": len(items),
        "unique_transaction_ids": len(unique_ids),
    }

    lines.append("")
    lines.append("### Count Reconciliation")
    lines.append("")
    lines.append("| Count | Declared | Derived |")
    lines.append("|-------|----------|---------|")
    for field in RECONCILIATION_FIELDS[:-1]:
        label = field.replace("_", " ").capitalize()
        lines.append(
            f"| {label} | {reconciliation[field]} | {derived_counts[field]} |"
        )
    lines.append("| Reconciled | true | PASS |")

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    input_group = p.add_mutually_exclusive_group()
    input_group.add_argument("--audit", help="path to legacy audit JSON, or '-' for stdin")
    input_group.add_argument(
        "--recurring-audit", help="path to recurring-expense audit JSON, or '-' for stdin"
    )
    p.add_argument("--categories", help="path to a saved category map (default: live monarch CLI)")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    if not args.audit and not args.recurring_audit:
        sys.stderr.write(
            "exactly one input mode is required: --audit PATH or --recurring-audit PATH\n"
        )
        return 2

    if args.recurring_audit and args.categories:
        sys.stderr.write("--categories is only valid with --audit\n")
        return 2

    input_path = args.recurring_audit if args.recurring_audit else args.audit
    raw = load_json_text(input_path)
    try:
        audit = json.loads(raw)
    except json.JSONDecodeError as e:
        input_label = "recurring audit" if args.recurring_audit else "audit"
        sys.stderr.write(f"invalid JSON in {input_label} input: {e}\n")
        return 2

    if args.recurring_audit:
        errors = validate_recurring(audit)
        error_heading = "recurring audit JSON failed validation:"
    else:
        category_names = load_category_names(args.categories)
        errors = validate(audit, category_names)
        error_heading = "audit JSON failed validation:"
    if errors:
        sys.stderr.write(f"{error_heading}\n")
        for err in errors:
            sys.stderr.write(f"  - {err}\n")
        return 1

    if args.validate_only:
        sys.stdout.write("OK\n")
        return 0

    if args.recurring_audit:
        sys.stdout.write(render_recurring(audit))
    else:
        sys.stdout.write(render(audit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
