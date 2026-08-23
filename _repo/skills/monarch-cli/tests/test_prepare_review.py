import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare-review.sh"

MOCK_MONARCH = """\
#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

fixture_path = Path(os.environ["MOCK_MONARCH_FIXTURES"])
calls_path = Path(os.environ["MOCK_MONARCH_CALLS"])
fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
calls = []
if calls_path.exists():
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]

actual = sys.argv[1:]
with calls_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(actual) + "\\n")

index = len(calls)
if index >= len(fixtures):
    sys.stderr.write(f"unexpected monarch call #{index + 1}: {actual!r}\\n")
    sys.exit(97)

expected = fixtures[index]["args"]
if actual != expected:
    sys.stderr.write(
        f"monarch call #{index + 1} mismatch: expected {expected!r}, got {actual!r}\\n"
    )
    sys.exit(98)

sys.stdout.write(json.dumps(fixtures[index]["result"]))
sys.stdout.write("\\n")
"""


def fixture(args: list[str], result: object) -> dict:
    return {"args": args, "result": result}


BASE_CATEGORIES = [{"id": "cat-utilities", "name": "Utilities"}]
BASE_TRANSACTIONS = [
    {
        "id": "txn-1",
        "date": "2026-08-01",
        "merchant": "Power Co",
        "category": "Utilities",
        "amount": -80.0,
    }
]
BASE_RULES: list[dict] = []


class PrepareReviewTests(unittest.TestCase):
    def run_script(
        self,
        arguments: list[str],
        fixtures: list[dict],
    ) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            monarch_path = tmp / "monarch"
            monarch_path.write_text(textwrap.dedent(MOCK_MONARCH), encoding="utf-8")
            monarch_path.chmod(0o755)
            fixture_path = tmp / "fixtures.json"
            fixture_path.write_text(json.dumps(fixtures), encoding="utf-8")
            calls_path = tmp / "calls.jsonl"

            env = os.environ.copy()
            env["PATH"] = str(tmp) + os.pathsep + env["PATH"]
            env["MOCK_MONARCH_FIXTURES"] = str(fixture_path)
            env["MOCK_MONARCH_CALLS"] = str(calls_path)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), *arguments],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            calls = []
            if calls_path.exists():
                calls = [
                    json.loads(line)
                    for line in calls_path.read_text(encoding="utf-8").splitlines()
                ]
            return proc, calls

    def test_legacy_default_behavior_and_output_fields_are_unchanged(self):
        fixtures = [
            fixture(["categories", "list", "--limit", "500"], BASE_CATEGORIES),
            fixture(
                ["transactions", "list", "--needs-review"],
                BASE_TRANSACTIONS,
            ),
            fixture(["rules", "list", "--limit", "500"], BASE_RULES),
        ]
        proc, calls = self.run_script([], fixtures)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, [entry["args"] for entry in fixtures])
        output = json.loads(proc.stdout)
        self.assertNotIn("accounts", output)
        self.assertNotIn("resolved_account", output)
        self.assertNotIn("recurring_transactions", output)
        self.assertEqual(output["transactions"][0]["current_category_id"], "cat-utilities")

    def test_candidates_resolve_one_exact_account_and_include_recurring(self):
        accounts = [
            {"id": "acc-checking", "name": "Checking", "hidden": False},
            {"id": "acc-bills", "name": "Bills", "hidden": True},
        ]
        recurring = [{"id": "stream-1", "merchant": "Power Co"}]
        fixtures = [
            fixture(
                ["accounts", "list", "--hidden", "--limit", "500"],
                accounts,
            ),
            fixture(["categories", "list", "--limit", "500"], BASE_CATEGORIES),
            fixture(
                [
                    "transactions",
                    "list",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-08-22",
                    "--account",
                    "acc-bills",
                    "--limit",
                    "750",
                ],
                BASE_TRANSACTIONS,
            ),
            fixture(["rules", "list", "--limit", "500"], BASE_RULES),
            fixture(
                [
                    "transactions",
                    "recurring",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-08-22",
                ],
                recurring,
            ),
        ]
        proc, calls = self.run_script(
            [
                "--account-name-candidate",
                "Bill",
                "--account-name-candidate",
                "Bills",
                "--start",
                "2026-01-01",
                "--end",
                "2026-08-22",
                "--limit",
                "750",
                "--include-recurring",
            ],
            fixtures,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, [entry["args"] for entry in fixtures])
        output = json.loads(proc.stdout)
        self.assertEqual(output["accounts"], accounts)
        self.assertEqual(output["resolved_account"], accounts[1])
        self.assertEqual(output["recurring_transactions"], recurring)

    def test_include_accounts_is_standalone_and_hidden_inclusive(self):
        accounts = [
            {"id": "acc-family", "name": "Family Bills Checking", "hidden": False},
            {"id": "acc-old", "name": "Archived Account", "hidden": True},
        ]
        fixtures = [
            fixture(
                ["accounts", "list", "--hidden", "--limit", "500"],
                accounts,
            ),
            fixture(["categories", "list", "--limit", "500"], BASE_CATEGORIES),
            fixture(
                ["transactions", "list", "--needs-review"],
                BASE_TRANSACTIONS,
            ),
            fixture(["rules", "list", "--limit", "500"], BASE_RULES),
        ]
        proc, calls = self.run_script(["--include-accounts"], fixtures)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(calls, [entry["args"] for entry in fixtures])
        output = json.loads(proc.stdout)
        self.assertEqual(output["accounts"], accounts)
        self.assertNotIn("resolved_account", output)

    def test_account_id_and_name_candidates_are_mutually_exclusive(self):
        proc, calls = self.run_script(
            ["--account", "acc-1", "--account-name-candidate", "Bills"],
            [],
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(calls, [])
        self.assertIn("mutually exclusive", proc.stderr)

    def test_zero_exact_candidate_matches_fails_before_other_calls(self):
        accounts = [{"id": "acc-family", "name": "Family Bills Checking"}]
        fixtures = [
            fixture(
                ["accounts", "list", "--hidden", "--limit", "500"],
                accounts,
            )
        ]
        proc, calls = self.run_script(
            [
                "--account-name-candidate",
                "Bill",
                "--account-name-candidate",
                "Bills",
            ],
            fixtures,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(calls, [entry["args"] for entry in fixtures])
        self.assertIn("matched 0 accounts exactly; expected 1", proc.stderr)

    def test_multiple_exact_candidate_matches_fails_before_other_calls(self):
        accounts = [
            {"id": "acc-bill", "name": "Bill"},
            {"id": "acc-bills", "name": "Bills"},
        ]
        fixtures = [
            fixture(
                ["accounts", "list", "--hidden", "--limit", "500"],
                accounts,
            )
        ]
        proc, calls = self.run_script(
            [
                "--account-name-candidate",
                "Bill",
                "--account-name-candidate",
                "Bills",
            ],
            fixtures,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(calls, [entry["args"] for entry in fixtures])
        self.assertIn("matched 2 accounts exactly; expected 1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
