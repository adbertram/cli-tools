---
name: wegic-cli
description: >-
  Execute wegic operations using the `wegic` CLI tool.
  CLI interface for Wegic (browser automation)
  Triggers: wegic, wegic cli, wegic auth, wegic search, wegic cache, list data in wegic, check wegic auth, wegic profiles
---

<objective>
Execute wegic operations using the `wegic` CLI. All wegic interactions should use this CLI.
</objective>

<quick_start>
The `wegic` CLI follows this pattern:
```bash
wegic <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `wegic search query` | Search for items on Wegic |
| `wegic search item` | Get details for a specific item |
| `wegic search list` | List items from Wegic |
| `wegic search wildcard` | Search items with wildcard pattern matching |
| `wegic auth login` | Configure authentication credentials |
| `wegic auth logout` | Clear stored credentials and browser sessions |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `wegic` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `wegic` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **`search`** — Search wegic.
- **`auth`** — Manage wegic authentication.
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
