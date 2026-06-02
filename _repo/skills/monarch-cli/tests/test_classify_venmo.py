import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("_repo/skills/monarch-cli/scripts/classify-venmo.sh")


def write_json(tmp: Path, name: str, value: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(value))
    return path


def venmo_record(payment_id="p1", amount=25.0, completed="2026-05-28T12:00:00", note="pizza", actor_id="u1", target_id="u2"):
    return {
        "payment_id": payment_id,
        "note": note,
        "payment": {
            "id": payment_id,
            "amount": amount,
            "status": "settled",
            "action": "pay",
            "date_completed": completed,
            "actor": {"id": actor_id, "display_name": "Example User"},
            "target": {"type": "user", "user": {"id": target_id, "display_name": "Example Counterparty"}},
        },
    }


class ClassifyVenmoTests(unittest.TestCase):
    def run_script(self, tmp: Path, txn: dict, profiles: dict, venmo: dict, rules: dict, *extra: str) -> dict:
        txn_path = write_json(tmp, "txn.json", txn)
        profiles_path = write_json(tmp, "profiles.json", profiles)
        venmo_path = write_json(tmp, "venmo.json", venmo)
        rules_path = write_json(tmp, "rules.json", rules)
        proc = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--transaction-json",
                str(txn_path),
                "--profiles-json",
                str(profiles_path),
                "--venmo-json",
                str(venmo_path),
                "--rules-json",
                str(rules_path),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_multiple_profiles_without_account_user_asks_first(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = self.run_script(
                tmp,
                {"id": "m1", "date": "2026-05-28", "amount": -25.0, "merchant": "Venmo", "account_name": "Home Budget"},
                {"profiles": [{"name": "primary", "authenticated": True}, {"name": "secondary", "authenticated": True}]},
                {"results": [venmo_record()]},
                {"rules": []},
            )
        self.assertEqual(result["status"], "needs_account_user")
        self.assertEqual(result["available_profiles"], ["primary", "secondary"])

    def test_account_user_resolves_profile_and_classifies_by_rule(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = self.run_script(
                tmp,
                {"id": "m1", "date": "2026-05-28", "amount": -25.0, "merchant": "Venmo"},
                {"profiles": [{"name": "primary", "authenticated": True, "credential_types": {"custom": {"user_id": "u1"}}}]},
                {"results": [venmo_record(note="pizza night")]},
                {"rules": [{"name": "pizza", "note_contains": "pizza", "category": "Dining"}]},
                "--account-user",
                "primary",
            )
        self.assertEqual(result["status"], "classified")
        self.assertEqual(result["suggested_category"], "Dining")
        self.assertEqual(result["evidence"]["counterparty"], "Example Counterparty")

    def test_single_profile_without_matching_rule_needs_classification_rule(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = self.run_script(
                tmp,
                {"id": "m1", "date": "2026-05-28", "amount": -25.0, "merchant": "Venmo"},
                {"profiles": [{"name": "default", "authenticated": True}]},
                {"results": [venmo_record(note="unknown memo")]},
                {"rules": []},
            )
        self.assertEqual(result["status"], "needs_classification_rule")
        self.assertEqual(result["profile"], "default")

    def test_multiple_matching_venmo_records_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = self.run_script(
                tmp,
                {"id": "m1", "date": "2026-05-28", "amount": -25.0, "merchant": "Venmo"},
                {"profiles": [{"name": "default", "authenticated": True}]},
                {"results": [venmo_record(payment_id="p1"), venmo_record(payment_id="p2")]},
                {"rules": [{"name": "pizza", "note_contains": "pizza", "category": "Dining"}]},
            )
        self.assertEqual(result["status"], "ambiguous_venmo_match")
        self.assertEqual([m["payment_id"] for m in result["matches"]], ["p1", "p2"])


if __name__ == "__main__":
    unittest.main()
