---
name: ship7-cli
description: >-
  Execute ship7 operations using the `ship7` CLI tool.
  CLI interface for Ship7 (browser automation)
  Triggers: ship7, ship7 cli, ship7 auth, ship7 search, ship7 cache, list data in ship7, check ship7 auth, ship7 profiles
---

<objective>
Execute ship7 operations using the `ship7` CLI. All ship7 interactions should use this CLI.
</objective>

<quick_start>
The `ship7` CLI follows this pattern:
```bash
ship7 <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `ship7 search query` | Search for items on Ship7 |
| `ship7 search item` | Get details for a specific item |
| `ship7 search list` | List items from Ship7 |
| `ship7 search wildcard` | Search items with wildcard pattern matching |
| `ship7 auth login` | Configure authentication credentials |
| `ship7 auth logout` | Clear stored credentials and browser sessions |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `ship7` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `ship7` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **`search`** — Search ship7.
- **`auth`** — Manage ship7 authentication.
- **`cache`** — Manage response cache.
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
