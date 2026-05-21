---
name: amazon-cli
description: >-
  Execute amazon operations using the `amazon` CLI tool.
  Use Amazon order evidence lookup through the amazon CLI. Commands inspect visible order-history text through a saved browser session.
  Triggers: amazon, amazon cli, amazon orders, Amazon order lookup, find Amazon order, Amazon charge evidence, Amazon purchase evidence, my Amazon orders
---

<objective>
Execute amazon operations using the `amazon` CLI. All amazon interactions should use this CLI.
</objective>

<quick_start>
The `amazon` CLI follows this pattern:
```bash
amazon <command-group> <action> [arguments] [options]
```

| Command | Use |
| --- | --- |
| `amazon auth login` | Open browser login and save the Amazon session |
| `amazon auth status` | Check saved browser-session authentication |
| `amazon auth test` | Run a live browser auth test |
| `amazon orders list --limit 25` | List visible order-history evidence lines |
| `amazon orders match --amount 33.15 --query "Amazon"` | Find evidence by transaction amount and query |
| `amazon orders get line-1` | Fetch one evidence line by id |
| `amazon cache clear` | Clear cached evidence output |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `amazon` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Browser Session">
Evidence commands require a saved browser session. If authentication is missing, run `amazon auth login` and complete the visible login flow. Do not invent order, purchase, receipt, or subscription details.
</principle>

<principle name="Command Groups">
- `auth`: Authentication commands for Amazon browser-session login, status, testing, logout, and profiles.
- `orders`: Order evidence commands for visible order-history lines and transaction evidence matching.
- `cache`: Cache commands for cached evidence output.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
