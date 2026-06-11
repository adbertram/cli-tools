---
name: instacart-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute instacart operations using the `instacart` CLI tool.
  CLI interface for Instacart API -- grocery delivery orders, cart, and account management.
  Triggers: instacart, instacart cli, grocery delivery, instacart orders, instacart cart, shopping cart, grocery orders, track delivery, instacart account
---

<objective>
Execute instacart operations using the `instacart` CLI. All instacart interactions should use this CLI.
</objective>

<quick_start>
The `instacart` CLI follows this pattern:
```bash
instacart <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `instacart auth status` |
| List cart items | `instacart cart list --table` |
| Cart summary by store | `instacart cart summary --table` |
| List orders | `instacart orders list --table` |
| Get order details | `instacart orders get ORDER_ID` |
| Track delivery | `instacart orders track ORDER_ID` |
| View account info | `instacart user me` |
| List addresses | `instacart user addresses --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `instacart` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage browser session authentication (login, logout, status)
- **cart** -- View shopping cart items and summary by store
- **orders** -- List, get, create, and track grocery delivery orders
- **user** -- View account info and delivery addresses
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
