---
name: ubiquiti-cli
description: >-
  Execute ubiquiti operations using the `ubiquiti` CLI tool.
  CLI interface for Ubiquiti (browser automation).
  Triggers: ubiquiti, ubiquiti cli, ubiquiti search, ubiquiti auth, ubiquiti cache
---

<objective>
Execute ubiquiti operations using the `ubiquiti` CLI. All ubiquiti interactions should use this CLI.
</objective>

<quick_start>
The `ubiquiti` CLI follows this pattern:
```bash
ubiquiti <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on Ubiquiti. Example: ubiquiti search query "my search term" --limit 20 --table ubiquiti search query "keyword" --filter "price:lt:100" ubiquiti search query "keyword" --properties "title,price" | `ubiquiti search query` |
| Get details for a specific item. Example: ubiquiti search item abc123 --table ubiquiti search item "https://example.com/item/abc123" ubiquiti search item abc123 --properties "title,price" | `ubiquiti search item` |
| List items from Ubiquiti. Example: ubiquiti search list --limit 100 --table ubiquiti search list --filter "status:active" ubiquiti search list --properties "id,name,status" | `ubiquiti search list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `ubiquiti search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `ubiquiti auth login` |
| Clear stored credentials and browser sessions. | `ubiquiti auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test`` (API/OAuth) or via the live browser check (browser_session). | `ubiquiti auth status` |
| Test authentication by verifying credentials work across profiles. | `ubiquiti auth test` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `ubiquiti` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `ubiquiti` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search ubiquiti
- **auth** -- Manage ubiquiti authentication
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
