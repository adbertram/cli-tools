#!/usr/bin/env python3
"""build-rule-command.sh — emit the exact `monarch rules create ...` command for a recommended rule.

Usage:
  build-rule-command.sh
    --merchant TEXT                # merchant string to match on
    --match equals|contains        # matcher operator (default: equals)
    --category-id ID               # category ID to assign
    [--amount-eq VAL]              # amount equals
    [--amount-gt VAL]
    [--amount-lt VAL]
    [--amount-between LOW:HIGH]
    [--income]                     # default --expense when amount is set
    [--use-original-statement]
    [--add-tag TAG_ID]             # repeatable
    [--apply-to-existing]

Prints a single-line `monarch rules create ...` command (no trailing newline beyond one).
Exits non-zero with a descriptive message if required args are missing or values look bogus.
"""

from __future__ import annotations

import argparse
import shlex
import sys


def main() -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--merchant", required=True)
    p.add_argument("--match", choices=["equals", "contains"], default="equals")
    p.add_argument("--category-id", required=True)
    p.add_argument("--amount-eq")
    p.add_argument("--amount-gt")
    p.add_argument("--amount-lt")
    p.add_argument("--amount-between")
    p.add_argument("--income", action="store_true")
    p.add_argument("--use-original-statement", action="store_true")
    p.add_argument("--add-tag", action="append", default=[])
    p.add_argument("--apply-to-existing", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args()

    if args.help:
        sys.stdout.write(__doc__)
        return 0

    amount_flags = [args.amount_eq, args.amount_gt, args.amount_lt, args.amount_between]
    set_amount = [f for f in amount_flags if f is not None]
    if len(set_amount) > 1:
        sys.stderr.write("only one of --amount-eq/--amount-gt/--amount-lt/--amount-between may be set\n")
        return 2

    parts: list[str] = ["monarch", "rules", "create"]
    parts.extend(["--merchant", f"{args.match}:{args.merchant}"])

    if args.amount_eq is not None:
        parts.extend(["--amount", f"eq:{args.amount_eq}"])
    elif args.amount_gt is not None:
        parts.extend(["--amount", f"gt:{args.amount_gt}"])
    elif args.amount_lt is not None:
        parts.extend(["--amount", f"lt:{args.amount_lt}"])
    elif args.amount_between is not None:
        if ":" not in args.amount_between:
            sys.stderr.write("--amount-between must be LOW:HIGH\n")
            return 2
        parts.extend(["--amount", f"between:{args.amount_between}"])

    if set_amount:
        parts.append("--income" if args.income else "--expense")

    if args.use_original_statement:
        parts.append("--use-original-statement")
    if args.apply_to_existing:
        parts.append("--apply-to-existing")
    for tag in args.add_tag:
        parts.extend(["--add-tag", tag])

    parts.extend(["--set-category", args.category_id])

    sys.stdout.write(shlex.join(parts) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
