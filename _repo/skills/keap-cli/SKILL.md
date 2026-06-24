---
name: keap-cli
description: >-
  Execute keap operations using the `keap` CLI tool.
  CLI interface for Keap API.
  Triggers: keap, keap cli, keap items, keap auth, keap cache
---

<objective>
Execute keap operations using the `keap` CLI. All keap interactions should use this CLI.
</objective>

<quick_start>
The `keap` CLI follows this pattern:
```bash
keap <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List items. | `keap items list` |
| Get details for a specific item. | `keap items get` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. | `keap items search` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `keap auth login` |
| Clear stored credentials. | `keap auth logout` |
| Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test``. | `keap auth status` |
| Test authentication by verifying credentials work across profiles. | `keap auth test` |
| Manage authentication profiles | `keap auth profiles` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `keap` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `keap` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **items** -- Manage keap items
- **auth** -- Manage keap authentication
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
