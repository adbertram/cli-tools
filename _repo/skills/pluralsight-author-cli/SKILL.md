---
name: pluralsight-author-cli
description: >-
  MANDATORY: Execute pluralsight-author operations using the `pluralsight-author` CLI tool.
  CLI interface for Pluralsight Author opportunities and Author Kit icons
  Triggers: pluralsight-author, pluralsight-author cli, pluralsight author, pluralsight author opportunities, pluralsight opportunities, list pluralsight author opportunities, get pluralsight author opportunity, search pluralsight author opportunities, pluralsight author icons, author kit icons, icon library, pluralsight author auth, pluralsight author cache
---

<objective>
Execute pluralsight-author operations using the `pluralsight-author` CLI. All Pluralsight Author opportunities and Author Kit icon-library interactions should use this CLI.
</objective>

<quick_start>
The `pluralsight-author` CLI follows this pattern:
```bash
pluralsight-author <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `pluralsight-author opportunities list` | List live Pluralsight Author opportunities. |
| `pluralsight-author opportunities get <slug>` | Fetch one opportunity by its slug. |
| `pluralsight-author search query <text>` | Search the opportunity dataset by keyword. |
| `pluralsight-author icons list` | List Author Kit icon-library records. |
| `pluralsight-author icons search <query>` | Search icons by name, category, color, or tag. |
| `pluralsight-author icons get <icon-id>` | Fetch one icon-library record. |
| `pluralsight-author icons download <icon-id> --output <path>` | Download one icon asset. |
| `pluralsight-author auth login` | Create or refresh the saved browser session required for live reads. |
| `pluralsight-author cache clear` | Clear cached responses before a fresh live read. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `pluralsight-author` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `pluralsight-author` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `opportunities`: Direct list/get access to the live Pluralsight Author opportunities dataset.
- `search`: Keyword search over the opportunity dataset.
- `icons`: Search, list, inspect, and download Author Kit icon-library assets.
- `auth`: Browser-session login, status, auth tests, and nested profile management.
- `cache`: Clear cached opportunity responses.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
