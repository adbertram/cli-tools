#!/usr/bin/env python3
"""classify-venmo.sh — deterministic Venmo evidence and category classification.

Usage:
  classify-venmo.sh
    --transaction-json PATH|-          # Monarch transaction JSON object
    [--account-user TEXT]              # user-supplied Venmo account user/profile
    [--profile PROFILE]                # explicit Venmo auth profile
    [--venmo-json PATH|-]              # fixture or prior `venmo transactions list` output
    [--profiles-json PATH]             # fixture or prior `venmo auth status` output
    [--rules-json PATH]                # classification rules JSON
    [--limit N]                        # live Venmo lookup limit; default 100
    [--posting-window-days N]          # allowed bank-posting lag; default 3

Output: JSON status object. The script never guesses a category. It returns
`classified` only when exactly one Venmo transaction matches and exactly one
explicit rule matches that Venmo evidence. If multiple Venmo profiles exist and
the Monarch transaction does not identify the account user/profile, it returns
`needs_account_user` before running any Venmo transaction lookup.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RULES = SKILL_DIR / "data/venmo-classification-rules.json"


def load_json_arg(path: str) -> Any:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text()
    return json.loads(raw)


def run_json(argv: list[str]) -> Any:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def dec(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value)).copy_abs()
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{field} must be a numeric value, got {value!r}") from exc


def iso_day(value: str, field: str) -> date:
    if not isinstance(value, str) or len(value) < 10:
        raise ValueError(f"{field} must be an ISO date string, got {value!r}")
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError as exc:
        raise ValueError(f"{field} must start with YYYY-MM-DD, got {value!r}") from exc


def profile_user_id(profile: dict[str, Any]) -> str | None:
    for block in profile.get("credential_types", {}).values():
        user_id = block.get("user_id")
        if isinstance(user_id, str) and user_id:
            return user_id
    return None


def authenticated_profiles(payload: Any) -> list[dict[str, Any]]:
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("profiles JSON must contain a profiles array")
    authenticated = []
    for profile in profiles:
        if "authenticated" not in profile:
            raise ValueError("profiles JSON must come from `venmo auth status` and include authenticated booleans")
        if profile.get("authenticated") is True:
            authenticated.append(profile)
    return authenticated


def candidate_from_transaction(txn: dict[str, Any]) -> str | None:
    for key in ("venmo_profile", "venmo_account_user", "account_user", "account_owner"):
        value = txn.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_profile(
    txn: dict[str, Any],
    profiles: list[dict[str, Any]],
    account_user: str | None,
    explicit_profile: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if explicit_profile:
        matches = [p for p in profiles if p.get("name") == explicit_profile]
        if len(matches) != 1:
            return None, f"Explicit Venmo profile {explicit_profile!r} is not authenticated."
        return matches[0], None

    candidate = account_user or candidate_from_transaction(txn)
    if candidate:
        needle = candidate.casefold()
        matches = [
            p for p in profiles
            if str(p.get("name", "")).casefold() == needle
            or str(profile_user_id(p) or "").casefold() == needle
        ]
        if len(matches) == 1:
            return matches[0], None
        return None, f"Venmo account user/profile {candidate!r} did not match exactly one authenticated profile."

    if len(profiles) == 1:
        return profiles[0], None

    return None, "Monarch transaction does not identify which Venmo account/profile to use."


def payment_date(record: dict[str, Any]) -> date:
    payment = record.get("payment")
    if not isinstance(payment, dict):
        raise ValueError("Venmo record payment must be an object")
    for key in ("date_completed", "date_created", "date_authorized"):
        value = payment.get(key)
        if isinstance(value, str) and value:
            return iso_day(value, f"payment.{key}")
    raise ValueError("Venmo record payment must include date_completed, date_created, or date_authorized")


def matches_transaction(record: dict[str, Any], amount: Decimal, posted: date, window_days: int) -> bool:
    payment = record.get("payment")
    if not isinstance(payment, dict):
        raise ValueError("Venmo record payment must be an object")
    record_amount = dec(payment.get("amount"), "payment.amount")
    record_date = payment_date(record)
    return record_amount == amount and abs((record_date - posted).days) <= window_days


def user_label(user: Any) -> str | None:
    if not isinstance(user, dict):
        return None
    for key in ("display_name", "username", "id"):
        value = user.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def evidence(record: dict[str, Any], account_user_id: str | None) -> dict[str, Any]:
    payment = record.get("payment")
    if not isinstance(payment, dict):
        raise ValueError("Venmo record payment must be an object")
    actor = payment.get("actor")
    target = payment.get("target")
    target_user = target.get("user") if isinstance(target, dict) else None
    actor_id = actor.get("id") if isinstance(actor, dict) else None
    target_id = target_user.get("id") if isinstance(target_user, dict) else None

    if account_user_id and actor_id == account_user_id:
        counterparty = user_label(target_user)
    elif account_user_id and target_id == account_user_id:
        counterparty = user_label(actor)
    else:
        actor_label = user_label(actor)
        target_label = user_label(target_user)
        counterparty = " / ".join([v for v in (actor_label, target_label) if v])

    return {
        "payment_id": record.get("payment_id") or payment.get("id"),
        "amount": str(dec(payment.get("amount"), "payment.amount")),
        "date": payment_date(record).isoformat(),
        "action": payment.get("action"),
        "status": payment.get("status"),
        "note": record.get("note") if isinstance(record.get("note"), str) else payment.get("note"),
        "actor": user_label(actor),
        "target": user_label(target_user),
        "counterparty": counterparty,
    }


def load_rules(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise ValueError("Venmo classification rules JSON must contain a rules array")
    for rule in rules:
        if not isinstance(rule.get("name"), str) or not rule["name"]:
            raise ValueError("Each Venmo classification rule needs a non-empty name")
        if not isinstance(rule.get("category"), str) or not rule["category"]:
            raise ValueError(f"Venmo classification rule {rule.get('name')!r} needs a non-empty category")
        if "note_contains" not in rule and "counterparty_contains" not in rule:
            raise ValueError(f"Venmo classification rule {rule['name']!r} needs note_contains or counterparty_contains")
    return rules


def rule_matches(rule: dict[str, Any], ev: dict[str, Any]) -> bool:
    if "note_contains" in rule:
        note = ev.get("note")
        if not isinstance(note, str) or rule["note_contains"].casefold() not in note.casefold():
            return False
    if "counterparty_contains" in rule:
        counterparty = ev.get("counterparty")
        if not isinstance(counterparty, str) or rule["counterparty_contains"].casefold() not in counterparty.casefold():
            return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--transaction-json", required=True)
    p.add_argument("--account-user")
    p.add_argument("--profile")
    p.add_argument("--venmo-json")
    p.add_argument("--profiles-json")
    p.add_argument("--rules-json", default=str(DEFAULT_RULES))
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--posting-window-days", type=int, default=3)
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    txn = load_json_arg(args.transaction_json)
    if not isinstance(txn, dict):
        raise ValueError("transaction JSON must be an object")

    amount = dec(txn.get("amount"), "transaction.amount")
    posted = iso_day(txn.get("date"), "transaction.date")

    profiles_payload = load_json_arg(args.profiles_json) if args.profiles_json else run_json(["venmo", "auth", "status"])
    profiles = authenticated_profiles(profiles_payload)
    profile, profile_error = resolve_profile(txn, profiles, args.account_user, args.profile)
    if profile is None:
        json.dump({
            "status": "needs_account_user",
            "reason": profile_error,
            "available_profiles": [p.get("name") for p in profiles],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    profile_name = profile["name"]
    profile_uid = profile_user_id(profile)
    venmo_payload = load_json_arg(args.venmo_json) if args.venmo_json else run_json([
        "venmo", "transactions", "list",
        "--profile", profile_name,
        "--filter", f"payment.amount:eq:{amount}",
        "--limit", str(args.limit),
    ])
    records = venmo_payload.get("results")
    if not isinstance(records, list):
        raise ValueError("Venmo transactions JSON must contain a results array")
    matches = [r for r in records if matches_transaction(r, amount, posted, args.posting_window_days)]

    if len(matches) == 0:
        json.dump({"status": "no_venmo_match", "profile": profile_name, "amount": str(amount), "date": posted.isoformat()}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if len(matches) > 1:
        json.dump({
            "status": "ambiguous_venmo_match",
            "profile": profile_name,
            "matches": [evidence(r, profile_uid) for r in matches],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    ev = evidence(matches[0], profile_uid)
    matching_rules = [rule for rule in load_rules(Path(args.rules_json)) if rule_matches(rule, ev)]
    if len(matching_rules) == 0:
        json.dump({"status": "needs_classification_rule", "profile": profile_name, "evidence": ev}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if len(matching_rules) > 1:
        json.dump({
            "status": "ambiguous_classification_rule",
            "profile": profile_name,
            "evidence": ev,
            "rules": [rule["name"] for rule in matching_rules],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    rule = matching_rules[0]
    json.dump({
        "status": "classified",
        "profile": profile_name,
        "suggested_category": rule["category"],
        "rule": rule["name"],
        "evidence": ev,
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write(f"classify-venmo.sh failed: {exc}\n")
        sys.exit(1)
