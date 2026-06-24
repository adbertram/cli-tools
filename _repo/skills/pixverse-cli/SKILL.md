---
name: pixverse-cli
description: >-
  Execute pixverse operations using the `pixverse` CLI tool.
  CLI interface for Pixverse API.
  Triggers: pixverse, pixverse cli, pixverse videos, pixverse auth, pixverse cache, generate pixverse video, check pixverse video status
---

<objective>
Execute pixverse operations using the `pixverse` CLI. All pixverse interactions should use this CLI.
</objective>

<quick_start>
The `pixverse` CLI follows this pattern:
```bash
pixverse <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Submit a text-to-video generation job | `pixverse videos text "A neon city skyline at dusk"` |
| Get the current job status for a PixVerse video generation | `pixverse videos status VIDEO_ID` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `pixverse auth login` |
| Clear stored credentials and browser sessions | `pixverse auth logout` |
| Check authentication status across profiles | `pixverse auth status --table` |
| Refresh OAuth access token using stored refresh token | `pixverse auth refresh --table` |
| Test authentication by verifying credentials work across profiles | `pixverse auth test --table` |
| List all profiles and show which is the default | `pixverse auth profiles list --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `pixverse` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `pixverse` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **videos** -- Generate and inspect PixVerse videos
- **auth** -- Manage pixverse authentication
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
