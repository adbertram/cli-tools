#!/usr/bin/env python3
"""prepare-review.sh — fetch categories, transactions, rules; enrich and emit JSON.

Usage:
  prepare-review.sh [--needs-review | --reviewed]
                    [--days N | --start YYYY-MM-DD --end YYYY-MM-DD]
                    [--account ACCOUNT_ID |
                     --account-name-candidate NAME [--account-name-candidate NAME ...]]
                    [--include-accounts]
                    [--include-recurring]
                    [--merchant SUBSTRING]
                    [--limit N]

If no scope flag is given, defaults to --needs-review.

Output: JSON document
  {
    "categories": [...],
    "transactions": [...],    # each enriched with current_category_id,
                              # existing_rule (rule object or null),
                              # deep_inspection_match (vendor entry or null)
    "rules": [...],
    "deep_inspection_vendors": [...],
    "category_id_by_name": {name: id},
    "rules_md_path": "...",
    "accounts": [...],                 # present with --include-accounts or name candidates
    "resolved_account": {...},         # present with --account-name-candidate
    "recurring_transactions": [...]    # present with --include-recurring
  }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
RULES_MD = SKILL_DIR / "rules.md"


def run_monarch(args: list[str]) -> list:
    proc = subprocess.run(
        ["monarch", *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"monarch {' '.join(args)} failed (exit {proc.returncode}):\n{proc.stderr}\n")
        sys.exit(proc.returncode)
    return json.loads(proc.stdout)


def resolve_account(accounts: object, candidates: list[str]) -> dict:
    if not isinstance(accounts, list):
        raise ValueError(
            "accounts response must be an array, "
            f"got {type(accounts).__name__}"
        )

    candidate_names = set(candidates)
    matches: list[dict] = []
    for index, account in enumerate(accounts):
        if not isinstance(account, dict):
            raise ValueError(
                f"accounts[{index}] must be an object, got {type(account).__name__}"
            )
        account_id = account.get("id")
        account_name = account.get("name")
        if not isinstance(account_id, str) or not account_id:
            raise ValueError(f"accounts[{index}].id must be a non-empty string")
        if not isinstance(account_name, str) or not account_name:
            raise ValueError(f"accounts[{index}].name must be a non-empty string")
        if account_name in candidate_names:
            matches.append(account)

    if len(matches) == 0:
        raise ValueError(
            "account-name candidates matched 0 accounts exactly; expected 1: "
            + ", ".join(repr(name) for name in candidates)
        )
    if len(matches) > 1:
        match_labels = ", ".join(
            f"{account['name']!r} ({account['id']})" for account in matches
        )
        raise ValueError(
            f"account-name candidates matched {len(matches)} accounts exactly; "
            f"expected 1: {match_labels}"
        )
    return matches[0]


def parse_deep_inspection_vendors(rules_md: Path) -> list[dict]:
    text = rules_md.read_text()
    m = re.search(r"^## Deep-Inspection Vendors\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return []
    body = m.group(1)
    vendors: list[dict] = []
    current: dict | None = None
    for raw in body.splitlines():
        if re.match(r"^- \S", raw):
            if current:
                vendors.append(current)
            current = {"pattern": raw[2:].strip(), "command": None, "evidence": None, "notes": None}
        elif current and re.match(r"^\s{2,}- ", raw):
            field = raw.strip()[2:]
            if ":" in field:
                key, _, val = field.partition(":")
                key = key.strip()
                val = val.strip()
                if key in current:
                    current[key] = val
    if current:
        vendors.append(current)
    return vendors


def existing_rule_for_merchant(merchant: str | None, rules: list[dict]) -> dict | None:
    if not merchant:
        return None
    m_lower = merchant.lower()
    for rule in rules:
        for crit in rule.get("merchantCriteria") or []:
            val = (crit.get("value") or "").lower()
            if not val:
                continue
            if val in m_lower or m_lower in val:
                return rule
    return None


def deep_match(merchant: str | None, vendors: list[dict]) -> dict | None:
    if not merchant:
        return None
    m_lower = merchant.lower()
    for v in vendors:
        if v["pattern"].lower() in m_lower:
            return v
    return None


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--needs-review", action="store_true")
    p.add_argument("--reviewed", action="store_true")
    p.add_argument("--days", type=int)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--account")
    p.add_argument("--account-name-candidate", action="append")
    p.add_argument("--include-accounts", action="store_true")
    p.add_argument("--include-recurring", action="store_true")
    p.add_argument("--merchant")
    p.add_argument("--limit", type=int)
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    if not RULES_MD.exists():
        sys.stderr.write(f"missing rules.md: {RULES_MD}\n")
        return 2

    if args.account and args.account_name_candidate:
        sys.stderr.write(
            "--account and --account-name-candidate are mutually exclusive\n"
        )
        return 2

    accounts: list | None = None
    resolved_account: dict | None = None
    account_id = args.account
    if args.include_accounts or args.account_name_candidate:
        accounts = run_monarch(["accounts", "list", "--hidden", "--limit", "500"])
    if args.account_name_candidate:
        try:
            resolved_account = resolve_account(accounts, args.account_name_candidate)
        except ValueError as error:
            sys.stderr.write(f"account resolution failed: {error}\n")
            return 2
        account_id = resolved_account["id"]

    txn_args: list[str] = []
    no_scope = not any([
        args.needs_review, args.reviewed, args.days, args.start, args.end,
        account_id, args.merchant,
    ])
    if no_scope:
        txn_args.append("--needs-review")
    if args.needs_review:
        txn_args.append("--needs-review")
    if args.reviewed:
        txn_args.append("--reviewed")
    if args.days is not None:
        txn_args.extend(["--days", str(args.days)])
    if args.start:
        txn_args.extend(["--start", args.start])
    if args.end:
        txn_args.extend(["--end", args.end])
    if account_id:
        txn_args.extend(["--account", account_id])
    if args.merchant:
        txn_args.extend(["--search", args.merchant])
    if args.limit is not None:
        txn_args.extend(["--limit", str(args.limit)])

    categories = run_monarch(["categories", "list", "--limit", "500"])
    transactions = run_monarch(["transactions", "list", *txn_args])
    rules = run_monarch(["rules", "list", "--limit", "500"])
    recurring_transactions = None
    if args.include_recurring:
        recurring_args = ["transactions", "recurring"]
        if args.start:
            recurring_args.extend(["--start", args.start])
        if args.end:
            recurring_args.extend(["--end", args.end])
        recurring_transactions = run_monarch(recurring_args)
    vendors = parse_deep_inspection_vendors(RULES_MD)

    cat_by_name = {c["name"]: c["id"] for c in categories}

    enriched: list[dict] = []
    for t in transactions:
        cat_name = t.get("category")
        existing = existing_rule_for_merchant(t.get("merchant"), rules)
        enriched.append({
            **t,
            "current_category_id": cat_by_name.get(cat_name) if cat_name else None,
            "existing_rule": existing,
            "deep_inspection_match": deep_match(t.get("merchant"), vendors),
        })

    output = {
        "categories": categories,
        "transactions": enriched,
        "rules": rules,
        "deep_inspection_vendors": vendors,
        "category_id_by_name": cat_by_name,
        "rules_md_path": str(RULES_MD),
    }
    if accounts is not None:
        output["accounts"] = accounts
    if resolved_account is not None:
        output["resolved_account"] = resolved_account
    if recurring_transactions is not None:
        output["recurring_transactions"] = recurring_transactions

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
