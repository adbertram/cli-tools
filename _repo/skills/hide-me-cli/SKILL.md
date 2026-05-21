---
name: hide-me-cli
description: >-
  Execute hide-me operations using the `hide-me` CLI tool.
  CLI interface for HideMe (browser automation).
  Triggers: hide-me, hide-me cli, hide-me search, hide-me auth, hide-me cache
---

<objective>
Execute hide-me operations using the `hide-me` CLI. All hide-me interactions should use this CLI.
</objective>

<quick_start>
The `hide-me` CLI follows this pattern:
```bash
hide-me <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on HideMe. Example: hide-me search query "my search term" --limit 20 --table hide-me search query "keyword" --filter "price:lt:100" hide-me search query "keyword" --properties "title,price" | `hide-me search query` |
| Get details for a specific item. Example: hide-me search item abc123 --table hide-me search item "https://example.com/item/abc123" hide-me search item abc123 --properties "title,price" | `hide-me search item` |
| List items from HideMe. Example: hide-me search list --limit 100 --table hide-me search list --filter "status:active" hide-me search list --properties "id,name,status" | `hide-me search list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `hide-me search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `hide-me auth login` |
| Clear stored credentials and browser sessions. | `hide-me auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test`` (API/OAuth) or via the live browser check (browser_session). | `hide-me auth status` |
| Test authentication by verifying credentials work across profiles. | `hide-me auth test` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `hide-me` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `hide-me` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search hide-me
- **auth** -- Manage hide-me authentication
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
