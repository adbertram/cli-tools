---
name: "snagit-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute snagit operations using the `snagit` CLI tool. CLI for managing Snagit capture files (.snagx format) -- list, view, and export captures. Triggers: snagit, snagit cli, snagit captures, snagit screenshots, export snagit, view snagit capture, list snagit files, snagx files, snagit images"
---

<objective>
Execute snagit operations using the `snagit` CLI. All snagit interactions should use this CLI.
</objective>

<quick_start>
The `snagit` CLI follows this pattern:
```bash
snagit capture <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List all captures | `snagit capture list --table` |
| List from custom folder | `snagit capture list --path ~/Pictures/Snagit/Archive` |
| View a capture image | `snagit capture view capture.snagx` |
| Export PNG from capture | `snagit capture export capture.snagx` |
| Export to specific path | `snagit capture export capture.snagx -o ~/Desktop/image.png` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `snagit` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **capture** — Manage .snagx capture files: list captures, view extracted images, export PNGs
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
