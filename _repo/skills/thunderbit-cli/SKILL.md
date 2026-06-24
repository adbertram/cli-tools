---
name: thunderbit-cli
description: >-
  Execute thunderbit operations using the `thunderbit` CLI tool.
  CLI interface for Thunderbit API.
  Triggers: thunderbit, thunderbit cli, thunderbit distill, thunderbit extract, thunderbit auth, thunderbit cache, distill page with thunderbit, extract with thunderbit
---

<objective>
Execute thunderbit operations using the `thunderbit` CLI. All thunderbit interactions should use this CLI.
</objective>

<quick_start>
The `thunderbit` CLI follows this pattern:
```bash
thunderbit <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Run Thunderbit's Markdown distillation endpoint | `thunderbit distill run https://example.com/article` |
| Run Thunderbit's structured extraction endpoint | `thunderbit extract run https://example.com/product --schema-file product-schema.json` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `thunderbit auth login` |
| Clear stored credentials and browser sessions | `thunderbit auth logout` |
| Check authentication status across profiles | `thunderbit auth status --table` |
| Refresh OAuth access token using stored refresh token | `thunderbit auth refresh --table` |
| Test authentication by verifying credentials work across profiles | `thunderbit auth test --table` |
| List all profiles and show which is the default | `thunderbit auth profiles list --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `thunderbit` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `thunderbit` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **distill** -- Distill web pages into Markdown
- **extract** -- Extract structured JSON from web pages
- **auth** -- Manage thunderbit authentication
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
