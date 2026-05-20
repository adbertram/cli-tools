---
name: apple-cli
description: >-
  Execute apple operations using the `apple` CLI tool.
  Use Apple purchase evidence lookup through the apple CLI. Commands inspect visible Apple purchase-history text through a saved browser session.
  Triggers: apple, apple cli, apple purchases, Apple purchase lookup, Apple receipt lookup, Apple charge evidence, Apple subscription evidence, my Apple purchases
---

<objective>
Execute apple operations using the `apple` CLI. All apple interactions should use this CLI.
</objective>

<quick_start>
The `apple` CLI follows this pattern:
```bash
apple <command-group> <action> [arguments] [options]
```

| Command | Use |
| --- | --- |
| `apple auth login` | Open browser login and save the Apple session |
| `apple auth status` | Check saved browser-session authentication |
| `apple auth test` | Run a live browser auth test |
| `apple purchases list --limit 25` | List visible purchase-history evidence lines |
| `apple purchases match --amount 33.15 --query "Apple One"` | Find evidence by amount and query |
| `apple purchases get line-1` | Fetch one evidence line by id |
| `apple cache clear` | Clear cached evidence output |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `apple` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Browser Session">
Evidence commands require a saved browser session. If authentication is missing, run `apple auth login` and complete the visible login flow. Do not invent order, purchase, receipt, or subscription details.
</principle>

<principle name="Command Groups">
- `auth`: Authentication commands for Apple browser-session login, status, testing, logout, and profiles.
- `purchases`: Purchase evidence commands for visible purchase-history lines and transaction evidence matching.
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
