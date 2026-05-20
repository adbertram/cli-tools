---
name: modello-turbo-cli
description: >-
  Execute modello-turbo operations using the `modello-turbo` CLI tool.
  CLI interface for ModelloTurbo (browser automation).
  Triggers: modello-turbo, modello-turbo cli, modello-turbo search, modello-turbo auth, modello-turbo cache, search modello-turbo, find modello-turbo program details
---

<objective>
Execute modello-turbo operations using the `modello-turbo` CLI. All modello-turbo interactions should use this CLI.
</objective>

<quick_start>
The `modello-turbo` CLI follows this pattern:
```bash
modello-turbo <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on ModelloTurbo | `modello-turbo search query QUERY --table` |
| Get details for a specific item | `modello-turbo search item ITEM_ID --table` |
| List items from ModelloTurbo | `modello-turbo search list --table` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search | `modello-turbo search wildcard "*test*"` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `modello-turbo auth login` |
| Clear stored credentials and browser sessions | `modello-turbo auth logout` |
| Check authentication status across profiles | `modello-turbo auth status --table` |
| Refresh OAuth access token using stored refresh token | `modello-turbo auth refresh --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `modello-turbo` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `modello-turbo` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **search** -- Search modello-turbo
- **auth** -- Manage modello-turbo authentication
- **cache** -- Manage response cache
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
