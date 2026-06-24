---
name: revo-uninstaller-cli
description: >-
  Execute revo-uninstaller operations using the `revo-uninstaller` CLI tool.
  CLI interface for RevoUninstaller (browser automation).
  Triggers: revo-uninstaller, revo-uninstaller cli, revo-uninstaller search, revo-uninstaller auth, revo-uninstaller cache, search revo-uninstaller, find revo-uninstaller program details
---

<objective>
Execute revo-uninstaller operations using the `revo-uninstaller` CLI. All revo-uninstaller interactions should use this CLI.
</objective>

<quick_start>
The `revo-uninstaller` CLI follows this pattern:
```bash
revo-uninstaller <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on RevoUninstaller | `revo-uninstaller search query QUERY --table` |
| Get details for a specific item | `revo-uninstaller search item ITEM_ID --table` |
| List items from RevoUninstaller | `revo-uninstaller search list --table` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search | `revo-uninstaller search wildcard "*test*"` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `revo-uninstaller auth login` |
| Clear stored credentials and browser sessions | `revo-uninstaller auth logout` |
| Check authentication status across profiles | `revo-uninstaller auth status --table` |
| Refresh OAuth access token using stored refresh token | `revo-uninstaller auth refresh --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `revo-uninstaller` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `revo-uninstaller` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **search** -- Search revo-uninstaller
- **auth** -- Manage revo-uninstaller authentication
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
