---
name: descript-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute descript operations using the `descript` CLI tool.
  CLI interface for Descript API -- manage projects, compositions, video exports, and network monitoring.
  Triggers: descript, descript cli, descript projects, descript compositions, descript export, export descript video, list descript projects, descript assets, descript monitor
---

<objective>
Execute descript operations using the `descript` CLI. All descript interactions should use this CLI.
</objective>

<quick_start>
The `descript` CLI follows this pattern:
```bash
descript <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List projects | `descript projects list --table` |
| Get project details | `descript projects get PROJECT_ID` |
| List compositions | `descript compositions list PROJECT_ID --table` |
| List video assets | `descript compositions assets PROJECT_ID --table` |
| Export raw asset | `descript compositions export PROJECT_ID ASSET_ID -o output.mp4` |
| Export composition | `descript compositions export PROJECT_ID --composition m2c1 -o m2c1.mp4` |
| Check auth | `descript auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `descript` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication (login extracts JWT from running Descript app, status checks token)
- **projects** — List and inspect Descript projects (find project IDs)
- **compositions** — Manage compositions within projects (list, get, export video, list assets)
- **monitor** — Monitor Descript app network activity for debugging (start, stop, status, tail)
</principle>

<principle name="Composition Export Wait">
Full composition exports render through the Descript desktop app and can take awhile. The CLI waits up to 30 minutes after the save dialog is accepted before timing out.
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
