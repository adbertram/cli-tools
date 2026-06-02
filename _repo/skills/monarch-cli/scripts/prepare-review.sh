#!/usr/bin/env python3
"""prepare-review.sh — fetch categories, transactions, rules; enrich and emit JSON.

Usage:
  prepare-review.sh [--needs-review | --reviewed]
                    [--days N | --start YYYY-MM-DD --end YYYY-MM-DD]
                    [--account ACCOUNT_ID]
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
    "rules_md_path": "..."
  }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RULES_MD = Path("_repo/skills/monarch-cli/rules.md")


def run_monarch(args: list[str]) -> list:
    proc = subprocess.run(
        ["monarch", *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"monarch {' '.join(args)} failed (exit {proc.returncode}):\n{proc.stderr}\n")
        sys.exit(proc.returncode)
    return json.loads(proc.stdout)


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

    txn_args: list[str] = []
    no_scope = not any([
        args.needs_review, args.reviewed, args.days, args.start, args.end,
        args.account, args.merchant,
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
    if args.account:
        txn_args.extend(["--account", args.account])
    if args.merchant:
        txn_args.extend(["--search", args.merchant])
    if args.limit is not None:
        txn_args.extend(["--limit", str(args.limit)])

    categories = run_monarch(["categories", "list", "--limit", "500"])
    transactions = run_monarch(["transactions", "list", *txn_args])
    rules = run_monarch(["rules", "list", "--limit", "500"])
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

    json.dump(
        {
            "categories": categories,
            "transactions": enriched,
            "rules": rules,
            "deep_inspection_vendors": vendors,
            "category_id_by_name": cat_by_name,
            "rules_md_path": str(RULES_MD),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
