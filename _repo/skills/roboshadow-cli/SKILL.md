---
name: roboshadow-cli
description: >-
  Execute roboshadow operations using the `roboshadow` CLI tool.
  CLI interface for Roboshadow (browser automation).
  Triggers: roboshadow, roboshadow cli, roboshadow search, roboshadow auth, roboshadow cache
---

<objective>
Execute roboshadow operations using the `roboshadow` CLI. All roboshadow interactions should use this CLI.
</objective>

<quick_start>
The `roboshadow` CLI follows this pattern:
```bash
roboshadow <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on Roboshadow. Example: roboshadow search query "my search term" --limit 20 --table roboshadow search query "keyword" --filter "price:lt:100" roboshadow search query "keyword" --properties "title,price" | `roboshadow search query` |
| Get details for a specific item. Example: roboshadow search item abc123 --table roboshadow search item "https://example.com/item/abc123" roboshadow search item abc123 --properties "title,price" | `roboshadow search item` |
| List items from Roboshadow. Example: roboshadow search list --limit 100 --table roboshadow search list --filter "status:active" roboshadow search list --properties "id,name,status" | `roboshadow search list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `roboshadow search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `roboshadow auth login` |
| Clear stored credentials and browser sessions. | `roboshadow auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test`` (API/OAuth) or via the live browser check (browser_session). | `roboshadow auth status` |
| Test authentication by verifying credentials work across profiles. | `roboshadow auth test` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `roboshadow` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `roboshadow` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search roboshadow
- **auth** -- Manage roboshadow authentication
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
