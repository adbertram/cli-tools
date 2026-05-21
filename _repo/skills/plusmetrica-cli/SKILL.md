---
name: plusmetrica-cli
description: >-
  Execute plusmetrica operations using the `plusmetrica` CLI tool.
  CLI interface for Plusmetrica (browser automation).
  Triggers: plusmetrica, plusmetrica cli, plusmetrica search, plusmetrica auth, plusmetrica cache, search plusmetrica, list plusmetrica items, plusmetrica data, my plusmetrica, search plusmetrica results
---

<objective>
Execute plusmetrica operations using the `plusmetrica` CLI. All plusmetrica interactions should use this CLI.
</objective>

<quick_start>
The `plusmetrica` CLI follows this pattern:
```bash
plusmetrica <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get details for a specific item. | `plusmetrica search item` |
| List items from Plusmetrica. | `plusmetrica search list` |
| Search for items on Plusmetrica. | `plusmetrica search query` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `plusmetrica search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `plusmetrica auth login` |
| Clear stored credentials and browser sessions. | `plusmetrica auth logout` |
| Create a new profile from .env.example template. | `plusmetrica auth profiles create` |
| Delete a profile and its data. | `plusmetrica auth profiles delete` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `plusmetrica` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `plusmetrica` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search plusmetrica
- **auth** -- Manage plusmetrica authentication
- **cache** -- Manage response cache
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
