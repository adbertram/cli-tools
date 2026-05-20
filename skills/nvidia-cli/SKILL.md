---
name: nvidia-cli
description: >-
  Execute nvidia operations using the `nvidia` CLI tool.
  CLI interface for Nvidia (browser automation)
  Triggers: nvidia, nvidia cli, nvidia auth, nvidia search, nvidia cache, list data in nvidia, check nvidia auth, nvidia profiles
---

<objective>
Execute nvidia operations using the `nvidia` CLI. All nvidia interactions should use this CLI.
</objective>

<quick_start>
The `nvidia` CLI follows this pattern:
```bash
nvidia <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `nvidia search query` | Search for items on Nvidia |
| `nvidia search item` | Get details for a specific item |
| `nvidia search list` | List items from Nvidia |
| `nvidia search wildcard` | Search items with wildcard pattern matching |
| `nvidia auth login` | Configure authentication credentials |
| `nvidia auth logout` | Clear stored credentials and browser sessions |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `nvidia` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `nvidia` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **`search`** — Search nvidia.
- **`auth`** — Manage nvidia authentication.
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
