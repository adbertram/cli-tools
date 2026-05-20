---
name: databox-cli
description: >-
  Execute databox operations using the `databox` CLI tool.
  CLI interface for Databox API
  Triggers: databox, databox cli, databox auth, databox items, databox cache, list data in databox, check databox auth, databox profiles
---

<objective>
Execute databox operations using the `databox` CLI. All databox interactions should use this CLI.
</objective>

<quick_start>
The `databox` CLI follows this pattern:
```bash
databox <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `databox items list` | List items |
| `databox items get` | Get details for a specific item |
| `databox items search` | Search items with wildcard pattern matching |
| `databox auth login` | Configure authentication credentials |
| `databox auth logout` | Clear stored credentials and browser sessions |
| `databox auth status` | Check authentication status across profiles |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `databox` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `databox` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **`items`** — Manage databox items.
- **`auth`** — Manage databox authentication.
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
