---
name: kick-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute kick operations using the `kick` CLI tool.
  CLI interface for Kick accounting/invoicing API -- transactions, categories, workspaces, entities, clients, rule groups, integrations, and statistics.
  Triggers: kick, kick cli, kick transactions, kick accounting, kick invoicing, list kick transactions, kick categories, kick clients, kick statistics, kick rule groups
---

<objective>
Execute kick operations using the `kick` CLI. All Kick accounting/invoicing interactions should use this CLI.
</objective>

<quick_start>
The `kick` CLI follows this pattern:
```bash
kick <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List transactions | `kick transactions list --table` |
| Search transactions | `kick transactions search "invoice" --table` |
| Get transaction details | `kick transactions get TRANSACTION_ID --table` |
| List categories | `kick categories list --table` |
| List clients | `kick clients list --table` |
| Get statistics | `kick statistics get --table` |
| List rule groups | `kick rule-groups list --table` |
| Check auth status | `kick auth status --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `kick` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- OAuth2 authentication (login, refresh, logout, status)
- **transactions** -- Financial transactions (list, search, get, update)
- **categories** -- Transaction categories (list, get)
- **workspaces** -- Workspace management (list, get)
- **entities** -- Companies/organizations (list, get)
- **statistics** -- Transaction statistics (get)
- **rule-groups** -- Auto-categorization rules (list, get, add, delete, rules)
- **clients** -- Client management (list, get, create)
- **integrations** -- External service integrations (list, get)
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
