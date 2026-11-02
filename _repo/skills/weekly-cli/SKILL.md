---
name: weekly-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Weekly operations using the `weekly` CLI tool.
  Read Weekly budgets, account balances and transaction exports; create manual entries, update categories and split eligible bank-linked expenses.
  Triggers: weekly budgeting app, weekly budget cli, weekly transactions cli
---

<objective>
Use the `weekly` CLI for supported Weekly budgeting reads and spending operations.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh weekly-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `weekly` CLI follows this pattern:
```bash
weekly <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Import and verify a captured Weekly login and refresh | `weekly auth import-capture <DIRECTORY>` |
| Import transaction export settings from an authorized capture | `weekly auth import-export <DIRECTORY>` |
| Configure authentication credentials | `weekly auth import-capture <DIRECTORY>` |
| Clear stored credentials | `weekly auth logout` |
| Create a new profile from .env.example template | `weekly auth profiles create <NAME>` |
| Delete a profile and its data | `weekly auth profiles delete <NAME>` |
| Get details for a specific profile | `weekly auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `weekly auth profiles list` |
| Delete a profile and its data | `weekly auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `weekly auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `weekly auth profiles select <NAME>` |
| Refresh and verify the saved Weekly session | `weekly auth refresh` |
| Check authentication status across profiles | `weekly auth status` |
| Test authentication by verifying credentials work across profiles | `weekly auth test` |
| Get a saved account balance by ID | `weekly balances get <ITEM_ID>` |
| List saved account balance records | `weekly balances list` |
| Read current week, recurring items, funds and budget preferences | `weekly budget current` |
| Remove all cached responses | `weekly cache clear` |
| Get a saved spending category by ID | `weekly categories get <ITEM_ID>` |
| List saved categories available for manual spending | `weekly categories list` |
| Create a manual safe-to-spend entry | `weekly transactions create` |
| Find one transaction in the selected export range | `weekly transactions get <TRANSACTION_ID>` |
| List transactions in the selected export range | `weekly transactions list` |
| Split an eligible 10.00 bank-linked expense | `weekly transactions split <TRANSACTION_ID> --part '6.00:Groceries' --part '4.00:Other'` |
| Update a safe-to-spend category, or a manual entry amount and title | `weekly transactions update <TRANSACTION_ID>` |
</quick_start>

<service_boundaries>
- `budget current` returns raw current-week, recurring-item, fund, and preference records. It does not calculate the dashboard's safe-to-spend total; initialWeeklySpendingLimit is an initial preference.
- Balance records are saved Weekly snapshots; reading them does not refresh bank connections.
- Transaction list/get use the app's captured CSV export range and captured exclusion settings. The full CSV is downloaded before local filters and limits; there is no default limit. `get` searches within the selected range, not every historical record.
- Create requires an existing unique category name (`weekly categories list`). Positive amounts represent spending; date defaults to the user's account timezone and can be specified with `--date YYYY-MM-DD`. New entries use the observed native color `warning`.
- Update supports category changes on manual and bank-linked non-transfer safe-to-spend entries. Title and amount changes remain limited to manual entries. It checks the server update-time precondition; transfers are not updated.
- Split accepts only positive, unsplit, bank-linked, non-transfer Safe-to-Spend expenses; manual entries, refunds, transfers and already-split entries are rejected. Supply at least two positive exact-cent `--part AMOUNT:CATEGORY` values totaling the original amount exactly. Each category must uniquely match a current account category, case-insensitively. Use `--table` or `--profile NAME` as needed.
- Split preserves title, date, color and the complete bank link. The first part retains the original ID; later parts get new IDs. The commit is atomic. If an outcome is uncertain, reconcile the reported transaction IDs before proceeding; never blindly retry.
- Capture import uses the capture's temporary decoder; choose a segment with `--flow-file` (for example, `wireguard-1.flows`). Live operations do not depend on the proxy. Reusable session credentials are stored through the CLI-tools secret manager. Never print captures or secrets.
</service_boundaries>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `weekly` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `weekly --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage weekly authentication (subcommands: import-capture, import-export, login, logout, profiles, refresh, status, test)
- **balances** -- Read linked account balances (subcommands: get, list)
- **budget** -- Read Weekly budget records (subcommands: current)
- **cache** -- Manage response cache (subcommands: clear)
- **categories** -- Read spending categories (subcommands: get, list)
- **transactions** -- Read transactions and manage spending (subcommands: create, get, list, split, update)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`weekly --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
