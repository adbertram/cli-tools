---
name: dell-cli
description: >-
  Execute dell operations using the `dell` CLI tool.
  CLI interface for Dell (browser automation).
  Triggers: dell, dell cli, dell search, dell auth, dell cache
---

<objective>
Execute dell operations using the `dell` CLI. All dell interactions should use this CLI.
</objective>

<quick_start>
The `dell` CLI follows this pattern:
```bash
dell <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on Dell. Example: dell search query "my search term" --limit 20 --table dell search query "keyword" --filter "price:lt:100" dell search query "keyword" --properties "title,price" | `dell search query` |
| Get details for a specific item. Example: dell search item abc123 --table dell search item "https://example.com/item/abc123" dell search item abc123 --properties "title,price" | `dell search item` |
| List items from Dell. Example: dell search list --limit 100 --table dell search list --filter "status:active" dell search list --properties "id,name,status" | `dell search list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `dell search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `dell auth login` |
| Clear stored credentials and browser sessions. | `dell auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test`` (API/OAuth) or via the live browser check (browser_session). | `dell auth status` |
| Test authentication by verifying credentials work across profiles. | `dell auth test` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `dell` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `dell` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search dell
- **auth** -- Manage dell authentication
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
