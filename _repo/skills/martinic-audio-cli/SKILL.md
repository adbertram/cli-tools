---
name: martinic-audio-cli
description: >-
  Execute martinic-audio operations using the `martinic-audio` CLI tool.
  CLI interface for MartinicAudio (browser automation).
  Triggers: martinic-audio, martinic-audio cli, martinic-audio search, martinic-audio auth, martinic-audio cache
---

<objective>
Execute martinic-audio operations using the `martinic-audio` CLI. All martinic-audio interactions should use this CLI.
</objective>

<quick_start>
The `martinic-audio` CLI follows this pattern:
```bash
martinic-audio <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items on MartinicAudio. Example: martinic-audio search query "my search term" --limit 20 --table martinic-audio search query "keyword" --filter "price:lt:100" martinic-audio search query "keyword" --properties "title,price" | `martinic-audio search query` |
| Get details for a specific item. Example: martinic-audio search item abc123 --table martinic-audio search item "https://example.com/item/abc123" martinic-audio search item abc123 --properties "title,price" | `martinic-audio search item` |
| List items from MartinicAudio. Example: martinic-audio search list --limit 100 --table martinic-audio search list --filter "status:active" martinic-audio search list --properties "id,name,status" | `martinic-audio search list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. Browser CLIs use client-side search. | `martinic-audio search wildcard` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `martinic-audio auth login` |
| Clear stored credentials and browser sessions. | `martinic-audio auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test`` (API/OAuth) or via the live browser check (browser_session). | `martinic-audio auth status` |
| Test authentication by verifying credentials work across profiles. | `martinic-audio auth test` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `martinic-audio` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `martinic-audio` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search martinic-audio
- **auth** -- Manage martinic-audio authentication
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
