---
name: microsoft-advertising-cli
description: >-
  Execute microsoft-advertising operations using the `microsoft-advertising` CLI tool.
  CLI interface for MicrosoftAdvertising (browser automation).
  Triggers: microsoft-advertising, microsoft-advertising cli, microsoft-advertising search, microsoft-advertising auth, microsoft-advertising cache, search microsoft-advertising, find microsoft-advertising program details
---

<objective>
Execute microsoft-advertising operations using the `microsoft-advertising` CLI. All microsoft-advertising interactions should use this CLI.
</objective>

<quick_start>
The `microsoft-advertising` CLI follows this pattern:
```bash
microsoft-advertising <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on MicrosoftAdvertising | `microsoft-advertising search query QUERY --table` |
| Get details for a specific item | `microsoft-advertising search item ITEM_ID --table` |
| List items from MicrosoftAdvertising | `microsoft-advertising search list --table` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search | `microsoft-advertising search wildcard "*test*"` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `microsoft-advertising auth login` |
| Clear stored credentials and browser sessions | `microsoft-advertising auth logout` |
| Check authentication status across profiles | `microsoft-advertising auth status --table` |
| Refresh OAuth access token using stored refresh token | `microsoft-advertising auth refresh --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `microsoft-advertising` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `microsoft-advertising` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **search** -- Search microsoft-advertising
- **auth** -- Manage microsoft-advertising authentication
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
