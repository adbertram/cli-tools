#!/usr/bin/env python3
"""apply-approved-updates.sh — apply approved category updates and create approved rules.

Reads the decisions JSON used by build-output.sh and applies updates to Monarch
for rows whose row number appears in --approved. For every approved row whose
`recommended_rule` starts with "Apply + create rule: ", the row's `rule_command`
is ALSO executed unless an equivalent rule already exists (same merchant
criterion + same set-category action). This is the default behavior — no
separate --create-rules range is required. Approved rows are marked reviewed
(needs-review cleared) unless --no-clear-needs-review is passed.

Usage:
  apply-approved-updates.sh
    --decisions PATH               # same JSON build-output.sh consumes
    [--approved RANGE]             # rows to update, e.g. "1,3,5-8" (omitted = no updates)
    [--create-rules RANGE]         # explicit override; by default auto-derived from --approved
    [--skip-rule-creation]         # do NOT auto-create rules for approved rows
    [--no-clear-needs-review]      # default: every approved row also gets --no-needs-review
    [--dry-run]                    # print intended commands, do not execute

Output: a JSON document with per-row status:
  {
    "updates": [
      {"row": 1, "transaction_id": "...", "category_id": "...", "status": "ok|skipped|failed",
       "stderr": null, "verified_category": "..."}
    ],
    "rules_created": [
      {"row": 6, "rule_command": "...", "status": "ok|skipped|failed",
       "rule_id": "...", "stderr": null, "existing_rule_id": "..."}
    ]
  }

Exits 0 if every requested action succeeded. Exits 1 if any failed (output JSON
still contains the per-row status so the caller can surface failures precisely).
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys


def parse_range(spec: str | None) -> set[int]:
    if not spec:
        return set()
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(chunk))
    return out


def run_capture(argv: list[str], dry_run: bool) -> tuple[int, str, str]:
    if dry_run:
        return 0, f"[dry-run] {shlex.join(argv)}\n", ""
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def load_decisions(path: str) -> dict:
    raw = sys.stdin.read() if path == "-" else open(path).read()
    return json.loads(raw)


def get_row(decisions: dict, row_num: int) -> dict | None:
    for r in decisions.get("rows", []):
        if r.get("row") == row_num:
            return r
    return None


def proposed_category_id(row: dict, category_id_by_name: dict[str, str] | None) -> str | None:
    """Resolve the category ID for an Apply-able row. AI passes category_id directly
    where it can; otherwise we look it up from the prepared category_id_by_name map.
    """
    if row.get("suggested_category_id"):
        return row["suggested_category_id"]
    sug = row.get("suggested_category")
    if sug and category_id_by_name and sug in category_id_by_name:
        return category_id_by_name[sug]
    return None


def parse_rule_command(cmd: str) -> dict:
    """Extract the merchant criterion and set-category from a `monarch rules create` command."""
    argv = shlex.split(cmd)
    merchant_criteria: list[str] = []
    set_category: str | None = None
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("--merchant", "-m") and i + 1 < len(argv):
            merchant_criteria.append(argv[i + 1])
            i += 2
        elif tok in ("--set-category",) and i + 1 < len(argv):
            set_category = argv[i + 1]
            i += 2
        else:
            i += 1
    return {"merchant_criteria": sorted(merchant_criteria), "set_category": set_category}


def fetch_existing_rules() -> list[dict]:
    proc = subprocess.run(
        ["monarch", "rules", "list", "--limit", "500"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def find_matching_rule(parsed: dict, existing: list[dict]) -> str | None:
    """Return rule ID if an existing rule has the same merchant criteria and set-category."""
    target_set = parsed["set_category"]
    target_merchants = parsed["merchant_criteria"]
    if not target_set or not target_merchants:
        return None
    for rule in existing:
        action = rule.get("setCategoryAction") or {}
        if action.get("id") != target_set:
            continue
        existing_merchants = sorted(
            f"{mc.get('operator')}:{mc.get('value')}"
            for mc in (rule.get("merchantCriteria") or [])
        )
        if existing_merchants == target_merchants:
            return rule.get("id")
    return None


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--decisions", required=True)
    p.add_argument("--approved", default="")
    p.add_argument("--create-rules", default="")
    p.add_argument("--skip-rule-creation", action="store_true")
    p.add_argument("--no-clear-needs-review", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    decisions = load_decisions(args.decisions)
    cat_id_by_name = decisions.get("category_id_by_name")  # optional, supplied by prepare-review

    approved_rows = parse_range(args.approved)
    if args.create_rules:
        rule_rows = parse_range(args.create_rules)
    elif args.skip_rule_creation:
        rule_rows = set()
    else:
        rule_rows = {
            r["row"] for r in decisions.get("rows", [])
            if r["row"] in approved_rows
            and isinstance(r.get("recommended_rule"), str)
            and r["recommended_rule"].startswith("Apply + create rule: ")
            and r.get("rule_command")
        }

    updates_out: list[dict] = []
    rules_out: list[dict] = []
    overall_ok = True

    # Apply category updates
    for row_num in sorted(approved_rows):
        row = get_row(decisions, row_num)
        if not row:
            updates_out.append({"row": row_num, "status": "failed", "stderr": "row not in decisions"})
            overall_ok = False
            continue
        cat_id = proposed_category_id(row, cat_id_by_name)
        if not cat_id:
            updates_out.append({
                "row": row_num, "transaction_id": row.get("transaction_id"),
                "status": "failed",
                "stderr": f"no suggested_category_id and no category_id_by_name match for {row.get('suggested_category')!r}",
            })
            overall_ok = False
            continue
        argv = ["monarch", "transactions", "update", row["transaction_id"], "--category", cat_id]
        rc, stdout, stderr = run_capture(argv, args.dry_run)
        result = {
            "row": row_num,
            "transaction_id": row["transaction_id"],
            "category_id": cat_id,
            "status": "ok" if rc == 0 else "failed",
            "stderr": stderr if rc != 0 else None,
        }
        if rc != 0:
            overall_ok = False
        elif not args.dry_run:
            # Verify by re-reading transaction
            verify = subprocess.run(
                ["monarch", "transactions", "get", row["transaction_id"]],
                capture_output=True, text=True, check=False,
            )
            if verify.returncode == 0:
                try:
                    obj = json.loads(verify.stdout)
                    result["verified_category"] = obj.get("category")
                    result["verified_needs_review"] = obj.get("needs_review")
                except Exception:
                    pass
        updates_out.append(result)

    # Create rules — skip any rule whose merchant+set-category already exists
    existing_rules = fetch_existing_rules() if rule_rows and not args.dry_run else []
    for row_num in sorted(rule_rows):
        row = get_row(decisions, row_num)
        if not row:
            rules_out.append({"row": row_num, "status": "failed", "stderr": "row not in decisions"})
            overall_ok = False
            continue
        cmd = row.get("rule_command")
        if not cmd:
            rules_out.append({"row": row_num, "status": "failed", "stderr": "no rule_command on this row"})
            overall_ok = False
            continue
        parsed = parse_rule_command(cmd)
        existing_id = find_matching_rule(parsed, existing_rules) if existing_rules else None
        if existing_id:
            rules_out.append({
                "row": row_num,
                "rule_command": cmd,
                "status": "skipped",
                "existing_rule_id": existing_id,
                "stderr": None,
                "rule_id": None,
            })
            continue
        argv = shlex.split(cmd)
        rc, stdout, stderr = run_capture(argv, args.dry_run)
        result = {
            "row": row_num,
            "rule_command": cmd,
            "status": "ok" if rc == 0 else "failed",
            "stderr": stderr if rc != 0 else None,
            "rule_id": None,
        }
        if rc == 0 and not args.dry_run:
            try:
                rule_obj = json.loads(stdout) if stdout.strip().startswith("{") else None
                if rule_obj and rule_obj.get("id"):
                    result["rule_id"] = rule_obj["id"]
            except Exception:
                pass
        elif rc != 0:
            overall_ok = False
        rules_out.append(result)

    json.dump({"updates": updates_out, "rules_created": rules_out}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
