---
name: fedex-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute fedex operations using the `fedex` CLI tool.
  CLI interface for FedEx API -- schedule pickups, check availability, and manage authentication profiles.
  Triggers: fedex, fedex cli, fedex pickup, schedule fedex pickup, fedex availability, cancel fedex pickup, fedex shipping
---

<objective>
Execute fedex operations using the `fedex` CLI. All fedex interactions should use this CLI.
</objective>

<quick_start>
The `fedex` CLI follows this pattern:
```bash
fedex <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check pickup availability | `fedex pickup availability` |
| Schedule pickup | `fedex pickup schedule --packages 2 --weight 10.5` |
| Cancel pickup | `fedex pickup cancel CODE --date 2024-01-15` |
| Check auth | `fedex auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `fedex` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage FedEx API authentication (login, logout, status, refresh, test)
- **pickup** — Schedule and manage pickups (availability, schedule, cancel)
- **auth** -- Authentication commands and nested `auth profiles` management
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
