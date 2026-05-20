---
name: gearup-cli
description: >-
  Execute gearup operations using the `gearup` CLI tool.
  CLI interface for Gearup (browser automation).
  Triggers: gearup, gearup cli, gearup search, gearup auth, gearup cache
---

<objective>
Execute gearup operations using the `gearup` CLI. All gearup interactions should use this CLI.
</objective>

<quick_start>
The `gearup` CLI follows this pattern:
```bash
gearup <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on Gearup. Example: gearup search query "my search term" --limit 20 --table gearup search query "keyword" --filter "price:lt:100" gearup search query "keyword" --properties "title,price" | `gearup search query` |
| Get details for a specific item. Example: gearup search item abc123 --table gearup search item "https://example.com/item/abc123" gearup search item abc123 --properties "title,price" | `gearup search item` |
| List items from Gearup. Example: gearup search list --limit 100 --table gearup search list --filter "status:active" gearup search list --properties "id,name,status" | `gearup search list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `gearup search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `gearup auth login` |
| Clear stored credentials and browser sessions. | `gearup auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test`` (API/OAuth) or via the live browser check (browser_session). | `gearup auth status` |
| Test authentication by verifying credentials work across profiles. | `gearup auth test` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `gearup` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `gearup` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search gearup
- **auth** -- Manage gearup authentication
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
