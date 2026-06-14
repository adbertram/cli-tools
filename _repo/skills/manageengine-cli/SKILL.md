---
name: manageengine-cli
description: >-
  Execute manageengine operations using the `manageengine` CLI tool.
  CLI interface for Manageengine (browser automation).
  Triggers: manageengine, manageengine cli, manageengine search, manageengine auth, manageengine cache, search manageengine, find manageengine program details
---

<objective>
Execute manageengine operations using the `manageengine` CLI. All manageengine interactions should use this CLI.
</objective>

<quick_start>
The `manageengine` CLI follows this pattern:
```bash
manageengine <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on Manageengine | `manageengine search query QUERY --table` |
| Get details for a specific item | `manageengine search item ITEM_ID --table` |
| List items from Manageengine | `manageengine search list --table` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search | `manageengine search wildcard "*test*"` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `manageengine auth login` |
| Clear stored credentials and browser sessions | `manageengine auth logout` |
| Check authentication status across profiles | `manageengine auth status --table` |
| Refresh OAuth access token using stored refresh token | `manageengine auth refresh --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `manageengine` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `manageengine` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **search** -- Search manageengine
- **auth** -- Manage manageengine authentication
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
