---
name: usps-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute usps operations using the `usps` CLI tool.
  CLI interface for USPS Tracking API -- track packages by tracking number.
  Triggers: usps, usps cli, usps tracking, track package, track usps, usps package, package tracking, where is my package, shipping status usps
---

<objective>
Execute usps operations using the `usps` CLI. All usps interactions should use this CLI.
</objective>

<quick_start>
The `usps` CLI follows this pattern:
```bash
usps <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Track a package | `usps tracking get TRACKING_NUMBER` |
| Track a package (table) | `usps tracking get TRACKING_NUMBER --table` |
| Track multiple packages | `usps tracking list NUM1 NUM2 NUM3 --table` |
| Filter delivered packages | `usps tracking list NUM1 NUM2 --filter "status:eq:Delivered"` |
| Check auth status | `usps auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `usps` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage USPS API authentication (OAuth 2.0 client credentials)
- **tracking** — Track packages: get single package info, list/batch-track multiple packages
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
