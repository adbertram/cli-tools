---
name: nextdoor-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute nextdoor operations using the `nextdoor` CLI tool.
  CLI interface for Nextdoor (browser automation) -- feed, notifications, me, and search.
  Triggers: nextdoor, nextdoor cli, nextdoor feed, nextdoor notifications, nextdoor search, nextdoor login, nextdoor auth profiles, check nextdoor auth
---

<objective>
Execute nextdoor operations using the `nextdoor` CLI. All Nextdoor interactions should use this CLI.
</objective>

<quick_start>
The `nextdoor` CLI follows this pattern:
```bash
nextdoor <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `nextdoor auth status` |
| Login to Nextdoor | `nextdoor auth login` |
| List feed | `nextdoor feed list` |
| List notifications | `nextdoor notifications list` |
| Get current user | `nextdoor me get` |
| Search | `nextdoor search list <query>` |
| List profiles | `nextdoor auth profiles list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `nextdoor` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, status, profiles)
- **feed** -- View neighborhood feed
- **me** -- Get current user profile and neighborhood info
- **notifications** -- View recent notifications
- **search** -- Search neighborhood content
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
