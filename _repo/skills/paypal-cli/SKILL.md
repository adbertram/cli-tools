---
name: "paypal-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute paypal operations using the `paypal` CLI tool. CLI interface for PayPal API. Triggers: paypal, paypal cli, paypal payouts, paypal transactions, PayPal transaction search, send paypal payment, paypal batch payout, pay someone with paypal, paypal payout status, my paypal, paypal auth profiles"
---

<objective>
Execute paypal operations using the `paypal` CLI. All paypal interactions should use this CLI.
</objective>

<quick_start>
The `paypal` CLI follows this pattern:
```bash
paypal <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `paypal auth status` |
| Send a payout | `paypal payouts create --receiver user@example.com --amount 10.00` |
| Check batch status | `paypal payouts get BATCH_ID` |
| Get payout item | `paypal payouts get-item ITEM_ID` |
| Cancel unclaimed payout | `paypal payouts cancel-item ITEM_ID` |
| List transactions by date range | `paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31` |
| Search a transaction ID | `paypal transactions get TRANSACTION_ID --start-date 2026-05-01 --end-date 2026-05-31` |
| List profiles | `paypal auth profiles list --table` |
| Switch profile | `paypal auth profiles select production` |

Auth status output uses the shared profile shape: `{"profiles":[{"name":"default","authenticated":true,"credential_types":{...}}]}`. Read `auth profiles[].authenticated` for per-profile status; do not expect a flat top-level `authenticated` field.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `paypal` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **payouts** -- Manage batch payouts (create, get, get-item, cancel-item)
- **transactions** -- List PayPal business-account transactions by date range
- **auth** -- Manage authentication (login, logout, status, test) and nested `auth profiles` management
- **cache** -- Manage response cache
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
