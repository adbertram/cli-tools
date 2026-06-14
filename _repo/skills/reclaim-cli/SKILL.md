---
name: reclaim-cli
description: >-
  Execute reclaim operations using the `reclaim` CLI tool.
  CLI interface for Reclaim (browser automation).
  Triggers: reclaim, reclaim cli, reclaim search, reclaim auth, reclaim cache, search reclaim, find reclaim program details
---

<objective>
Execute reclaim operations using the `reclaim` CLI. All reclaim interactions should use this CLI.
</objective>

<quick_start>
The `reclaim` CLI follows this pattern:
```bash
reclaim <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on Reclaim | `reclaim search query QUERY --table` |
| Get details for a specific item | `reclaim search item ITEM_ID --table` |
| List items from Reclaim | `reclaim search list --table` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search | `reclaim search wildcard "*test*"` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `reclaim auth login` |
| Clear stored credentials and browser sessions | `reclaim auth logout` |
| Check authentication status across profiles | `reclaim auth status --table` |
| Refresh OAuth access token using stored refresh token | `reclaim auth refresh --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `reclaim` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `reclaim` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **search** -- Search reclaim
- **auth** -- Manage reclaim authentication
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
