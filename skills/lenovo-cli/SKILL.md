---
name: lenovo-cli
description: >-
  Execute lenovo operations using the `lenovo` CLI tool.
  CLI interface for Lenovo (browser automation)
  Triggers: lenovo, lenovo cli, lenovo auth, lenovo search, lenovo cache, list data in lenovo, check lenovo auth, lenovo profiles
---

<objective>
Execute lenovo operations using the `lenovo` CLI. All lenovo interactions should use this CLI.
</objective>

<quick_start>
The `lenovo` CLI follows this pattern:
```bash
lenovo <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `lenovo search query` | Search for items on Lenovo |
| `lenovo search item` | Get details for a specific item |
| `lenovo search list` | List items from Lenovo |
| `lenovo search wildcard` | Search items with wildcard pattern matching |
| `lenovo auth login` | Configure authentication credentials |
| `lenovo auth logout` | Clear stored credentials and browser sessions |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `lenovo` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `lenovo` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **`search`** — Search lenovo.
- **`auth`** — Manage lenovo authentication.
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
