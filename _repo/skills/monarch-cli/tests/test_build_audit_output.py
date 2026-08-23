import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("_repo/skills/monarch-cli/scripts/build-audit-output.sh")

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
                    "python3",
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
                    "python3",
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


if __name__ == "__main__":
    unittest.main()
