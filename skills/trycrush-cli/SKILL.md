---
name: trycrush-cli
description: >-
  Execute trycrush operations using the `trycrush` CLI tool.
  CLI interface for Trycrush (browser automation).
  Triggers: trycrush, trycrush cli, trycrush search, trycrush auth, trycrush cache, search trycrush, list trycrush items, trycrush data, my trycrush, search trycrush results
---

<objective>
Execute trycrush operations using the `trycrush` CLI. All trycrush interactions should use this CLI.
</objective>

<quick_start>
The `trycrush` CLI follows this pattern:
```bash
trycrush <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get details for a specific item. | `trycrush search item` |
| List items from Trycrush. | `trycrush search list` |
| Search for items on Trycrush. | `trycrush search query` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `trycrush search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `trycrush auth login` |
| Clear stored credentials and browser sessions. | `trycrush auth logout` |
| Create a new profile from .env.example template. | `trycrush auth profiles create` |
| Delete a profile and its data. | `trycrush auth profiles delete` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `trycrush` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `trycrush` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search trycrush
- **auth** -- Manage trycrush authentication
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
