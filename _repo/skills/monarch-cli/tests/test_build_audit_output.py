import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-audit-output.sh"

CATEGORIES = [
    {"id": "1", "name": "Office Supplies & Expenses", "group": "Business", "icon": ""},
    {"id": "2", "name": "Software", "group": "Business", "icon": ""},
    {"id": "3", "name": "Business Travel & Meals", "group": "Business", "icon": ""},
    {"id": "4", "name": "Groceries", "group": "Food & Dining", "icon": ""},
    {"id": "5", "name": "Shopping", "group": "Shopping", "icon": ""},
]


def audit_row(
    row=1,
    transaction_id="243000001",
    date="2026-03-04",
    account="Chase Business Checking",
    merchant="Amazon",
    amount=-171.96,
    current_category="Shopping",
    bucket="miscategorization",
    recommended_category="Office Supplies & Expenses",
    confidence="high",
    evidence="Order 112-8842 lists two desk chairs.",
) -> dict:
    return {
        "row": row,
        "transaction_id": transaction_id,
        "date": date,
        "account": account,
        "merchant": merchant,
        "amount": amount,
        "current_category": current_category,
        "bucket": bucket,
        "recommended_category": recommended_category,
        "confidence": confidence,
        "evidence": evidence,
    }


def audit_doc(rows: list[dict], source_transaction_count: int | None = None) -> dict:
    return {
        "scope_label": "Geek Life business expense audit",
        "source_transaction_count": len(rows) if source_transaction_count is None else source_transaction_count,
        "rows": rows,
    }


def recurring_item() -> dict:
    return {
        "row": 1,
        "stable_name": "Power | Utility",
        "aliases": ["POWER CO", "POWER | AUTOPAY"],
        "cadence": "monthly",
        "transaction_ids": ["charge-1", "charge-2"],
        "netting_transaction_ids": ["net-1"],
        "observed_dates": ["2026-06-01", "2026-07-01"],
        "observed_amounts": [-50.0, 52.0],
        "occurrence_count": 2,
        "amount_range": {"min": 50.0, "max": 52.0},
        "detection_basis": "Two monthly charges.",
        "projection_window": "2026-06-01..2026-07-01",
        "projection_basis": "Mean observed monthly charge.",
        "normalized_monthly_average": 51.0,
        "status": "verified",
        "monarch_recurring_evidence": "Matched | stream",
    }


def recurring_doc() -> dict:
    return {
        "audit_kind": "recurring_expenses",
        "scope_label": "Bills | recurring expenses",
        "account": {"id": "acc-bills", "name": "Family Bills Checking"},
        "analysis_window": {
            "requested_start": "2026-01-01",
            "requested_end": "2026-08-22",
            "earliest_transaction_date": "2026-06-01",
            "latest_transaction_date": "2026-07-15",
            "source_transaction_count": 4,
            "history_limit": 500,
            "history_complete": True,
        },
        "recurring_cross_check": {
            "monarch_streams_total": 4,
            "monarch_streams_matched_account": 1,
            "history_detected_items": 1,
            "history_only_items": 0,
            "monarch_only_items": 0,
            "evidence": "Matched raw streams | against account history.",
        },
        "items": [recurring_item()],
        "excluded_transactions": [
            {
                "transaction_id": "excluded-1",
                "date": "2026-07-15",
                "merchant": "Power refund",
                "amount": 12.34,
                "classification": "refund/reversal",
                "reason": "Refund | reversal.",
            }
        ],
        "reconciliation": {
            "source_transactions": 4,
            "recurring_charge_transactions": 2,
            "netting_transactions": 1,
            "excluded_transactions": 1,
            "recurring_items": 1,
            "unique_transaction_ids": 4,
            "reconciled": True,
        },
    }


class BuildAuditOutputTests(unittest.TestCase):
    def run_script(self, audit: dict, *extra: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            audit_path = tmp / "audit.json"
            audit_path.write_text(json.dumps(audit))
            categories_path = tmp / "categories.json"
            categories_path.write_text(json.dumps(CATEGORIES))
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--audit",
                    str(audit_path),
                    "--categories",
                    str(categories_path),
                    *extra,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_valid_audit_renders_table_totals_and_reconciliation(self):
        rows = [
            audit_row(),
            audit_row(
                row=2,
                transaction_id="243000002",
                merchant="GitHub",
                amount=-21.0,
                current_category="Software",
                bucket="business cost",
                recommended_category="Software",
                evidence="Monthly team seat.",
            ),
            audit_row(
                row=3,
                transaction_id="243000003",
                merchant="Kroger",
                amount=-88.42,
                current_category="Uncategorized",
                bucket="owner draw",
                recommended_category="Groceries",
                confidence="medium",
                evidence="Household groceries paid from the business account.",
            ),
        ]
        proc = self.run_script(audit_doc(rows))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn(
            "| # | Date | Account | Merchant | Amount | Current Category | Bucket | "
            "Recommended Category | Confidence | Evidence |",
            out,
        )
        self.assertIn("### Summary Totals", out)
        self.assertIn("| business cost | 1 | -$21.00 |", out)
        self.assertIn("| owner draw | 1 | -$88.42 |", out)
        self.assertIn("| miscategorization | 1 | -$171.96 |", out)
        self.assertIn("| **Total** | 3 | -$281.38 |", out)
        self.assertIn("### Count Reconciliation", out)
        self.assertIn("| Source transactions | 3 |", out)
        self.assertIn("| Rows by bucket (sum) | 3 |", out)
        self.assertIn("| Category changes recommended | 2 |", out)
        self.assertIn("| Already correct | 1 |", out)
        self.assertIn("| Reconciled | PASS |", out)

    def test_legacy_audit_rendering_is_byte_for_byte_stable(self):
        proc = self.run_script(audit_doc([audit_row()]))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout,
            """### Audit — Geek Life business expense audit

| # | Date | Account | Merchant | Amount | Current Category | Bucket | Recommended Category | Confidence | Evidence |
|---|------|---------|----------|--------|------------------|--------|----------------------|------------|----------|
| 1 | 2026-03-04 | Chase Business Checking | Amazon | -$171.96 | Shopping | miscategorization | Office Supplies & Expenses | high | Order 112-8842 lists two desk chairs. |

### Summary Totals

| Bucket | Rows | Amount |
|--------|------|--------|
| business cost | 0 | $0.00 |
| owner draw | 0 | $0.00 |
| miscategorization | 1 | -$171.96 |
| **Total** | 1 | -$171.96 |

### Count Reconciliation

| Check | Value |
|-------|-------|
| Source transactions | 1 |
| Rendered rows | 1 |
| Rows by bucket (sum) | 1 |
| Unique transaction IDs | 1 |
| Category changes recommended | 1 |
| Already correct | 0 |
| Reconciled | PASS |
""",
        )

    def test_validate_only_prints_ok(self):
        proc = self.run_script(audit_doc([audit_row()]), "--validate-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "OK\n")

    def test_unknown_recommended_category_fails(self):
        proc = self.run_script(audit_doc([audit_row(recommended_category="Office Supplies")]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("recommended_category 'Office Supplies' does not exist", proc.stderr)

    def test_unknown_current_category_fails(self):
        proc = self.run_script(audit_doc([audit_row(current_category="Shoppingg")]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("current_category 'Shoppingg' is not in the Monarch category map", proc.stderr)

    def test_empty_bucket_fails_as_unclassified(self):
        proc = self.run_script(audit_doc([audit_row(bucket="")]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("UNCLASSIFIED ROW — bucket is empty", proc.stderr)

    def test_unknown_bucket_fails_as_unclassified(self):
        proc = self.run_script(audit_doc([audit_row(bucket="Business Cost")]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("UNCLASSIFIED ROW — bucket 'Business Cost' is unknown", proc.stderr)

    def test_count_mismatch_fails(self):
        proc = self.run_script(audit_doc([audit_row()], source_transaction_count=4))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("count reconciliation failed", proc.stderr)

    def test_duplicate_transaction_id_fails(self):
        rows = [audit_row(), audit_row(row=2, merchant="Amazon Again")]
        proc = self.run_script(audit_doc(rows))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("duplicate transaction_id '243000001'", proc.stderr)

    def test_non_sequential_row_number_fails(self):
        proc = self.run_script(audit_doc([audit_row(row=2)], source_transaction_count=1))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("rows must be sequential starting at 1", proc.stderr)

    def test_bad_date_fails(self):
        proc = self.run_script(audit_doc([audit_row(date="03/04/2026")]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("date must match YYYY-MM-DD", proc.stderr)

    def test_bad_confidence_fails(self):
        proc = self.run_script(audit_doc([audit_row(confidence="pretty sure")]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("confidence must be one of", proc.stderr)

    def test_missing_row_field_fails(self):
        row = audit_row()
        del row["evidence"]
        proc = self.run_script(audit_doc([row]))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing fields ['evidence']", proc.stderr)

    def test_missing_root_field_fails(self):
        doc = audit_doc([audit_row()])
        del doc["scope_label"]
        proc = self.run_script(doc)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing root fields ['scope_label']", proc.stderr)

    def test_pipe_in_evidence_is_escaped(self):
        proc = self.run_script(audit_doc([audit_row(evidence="seat | renewal")]))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("seat \\| renewal", proc.stdout)

    def test_malformed_categories_file_fails_with_contract_error(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            audit_path = tmp / "audit.json"
            audit_path.write_text(json.dumps(audit_doc([audit_row()])))
            categories_path = tmp / "categories.json"
            categories_path.write_text(json.dumps({"stuff": 1}))
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--audit",
                    str(audit_path),
                    "--categories",
                    str(categories_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("JSON_CONTRACT_MISMATCH", proc.stderr)


class BuildRecurringAuditOutputTests(unittest.TestCase):
    def run_script(self, audit: dict, *extra: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "recurring-audit.json"
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--recurring-audit",
                    str(audit_path),
                    *extra,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_happy_path_exact_output(self):
        proc = self.run_script(recurring_doc())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout,
            """### Recurring Expense Audit — Bills \\| recurring expenses

| # | Stable Name | Aliases | Cadence | Occurrences | Observed Dates | Observed Amounts | Amount Range | Normalized Monthly Projection | Detection Basis | Projection Window | Projection Basis | Monarch Recurring Evidence | Status |
|---|-------------|---------|---------|-------------|----------------|------------------|--------------|-------------------------------|-----------------|-------------------|------------------|----------------------------|--------|
| 1 | Power \\| Utility | POWER CO, POWER \\| AUTOPAY | monthly | 2 | 2026-06-01, 2026-07-01 | -$50.00, +$52.00 | $50.00–$52.00 | $51.00 | Two monthly charges. | 2026-06-01..2026-07-01 | Mean observed monthly charge. | Matched \\| stream | verified |

### Summary Totals

| Metric | Value |
|--------|-------|
| Account ID | acc-bills |
| Account name | Family Bills Checking |
| Requested range | 2026-01-01..2026-08-22 |
| Exact analyzed transaction range | 2026-06-01..2026-07-15 |
| Source transaction count | 4 |
| History limit | 500 |
| History complete | true |
| Verified normalized monthly total | $51.00 |
| UNVERIFIED items | 0 |

#### Monarch Recurring Cross-Check

| Metric | Value |
|--------|-------|
| Monarch streams total | 4 |
| Monarch streams matched account | 1 |
| History-detected items | 1 |
| History-only items | 0 |
| Monarch-only items | 0 |
| Evidence | Matched raw streams \\| against account history. |

#### Exclusions and Ambiguities

| Classification | Count | Date Range | Total Amount | Merchants | Reasons |
|----------------|-------|------------|--------------|-----------|---------|
| transfer | 0 | — | $0.00 | — | — |
| deposit/income | 0 | — | $0.00 | — | — |
| one-off purchase | 0 | — | $0.00 | — | — |
| refund/reversal | 1 | 2026-07-15 | +$12.34 | Power refund | Refund \\| reversal. |
| ambiguous | 0 | — | $0.00 | — | — |

### Count Reconciliation

| Count | Declared | Derived |
|-------|----------|---------|
| Source transactions | 4 | 4 |
| Recurring charge transactions | 2 | 2 |
| Netting transactions | 1 | 1 |
| Excluded transactions | 1 | 1 |
| Recurring items | 1 | 1 |
| Unique transaction ids | 4 | 4 |
| Reconciled | true | PASS |
""",
        )
        top_level_blocks = [
            line for line in proc.stdout.splitlines() if line.startswith("### ")
        ]
        self.assertEqual(
            top_level_blocks,
            [
                "### Recurring Expense Audit — Bills \\| recurring expenses",
                "### Summary Totals",
                "### Count Reconciliation",
            ],
        )

    def test_validate_only_supports_recurring_mode(self):
        proc = self.run_script(recurring_doc(), "--validate-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "OK\n")

    def test_reconciliation_count_mismatch_fails(self):
        audit = recurring_doc()
        audit["reconciliation"]["recurring_charge_transactions"] = 99
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(
            "reconciliation.recurring_charge_transactions=99 but derived count=2",
            proc.stderr,
        )

    def test_occurrence_count_mismatch_fails(self):
        audit = recurring_doc()
        audit["items"][0]["occurrence_count"] = 3
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("occurrence_count=3 but len(transaction_ids)=2", proc.stderr)
        self.assertIn("occurrence_count=3 but len(observed_dates)=2", proc.stderr)
        self.assertIn("occurrence_count=3 but len(observed_amounts)=2", proc.stderr)

    def test_duplicate_id_across_item_and_exclusion_fails(self):
        audit = recurring_doc()
        audit["excluded_transactions"][0]["transaction_id"] = "net-1"
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("duplicate transaction_id 'net-1'", proc.stderr)

    def test_invalid_calendar_date_fails(self):
        audit = recurring_doc()
        audit["items"][0]["observed_dates"][0] = "2026-02-30"
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("must be a valid calendar date", proc.stderr)

    def test_invalid_cadence_fails(self):
        audit = recurring_doc()
        audit["items"][0]["cadence"] = "biweekly"
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cadence must be one of", proc.stderr)

    def test_invalid_status_fails(self):
        audit = recurring_doc()
        audit["items"][0]["status"] = "Verified"
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("status must be one of ['verified', 'UNVERIFIED']", proc.stderr)

    def test_verified_projection_must_be_nonnegative_number(self):
        audit = recurring_doc()
        audit["items"][0]["normalized_monthly_average"] = None
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(
            "normalized_monthly_average must be a number >= 0 when status is 'verified'",
            proc.stderr,
        )

    def test_unverified_projection_must_be_null(self):
        audit = recurring_doc()
        audit["items"][0]["status"] = "UNVERIFIED"
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(
            "normalized_monthly_average must be null when status is 'UNVERIFIED'",
            proc.stderr,
        )

    def test_invalid_exclusion_classification_fails(self):
        audit = recurring_doc()
        audit["excluded_transactions"][0]["classification"] = "refund"
        proc = self.run_script(audit)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("classification must be one of", proc.stderr)

    def test_input_modes_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            path.write_text(json.dumps(recurring_doc()), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--audit",
                    str(path),
                    "--recurring-audit",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not allowed with argument", proc.stderr)


if __name__ == "__main__":
    unittest.main()
