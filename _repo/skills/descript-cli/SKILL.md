---
name: descript-cli
description: >-
  MANDATORY: Use this skill for Descript service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
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
| Find project IDs for follow-up commands | `descript projects list --filter 'name:contains:NAME' --properties id,name` |
| List projects for visual inspection | `descript projects list --properties id,name --table` |
| Get project details | `descript projects get PROJECT_ID` |
| List composition IDs for follow-up commands | `descript compositions list PROJECT_ID --properties id,name` |
| List compositions for visual inspection | `descript compositions list PROJECT_ID --properties id,name --table` |
| Show active Descript composition pages | `descript compositions active` |
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
- **compositions** — Manage compositions within projects (list, get, active, export video, list assets)
- **monitor** — Monitor Descript app network activity for debugging (start, stop, status, tail)
</principle>

<principle name="Full ID Extraction">
Use default JSON output when an ID will be copied into a follow-up command. Do not copy project, composition, or asset IDs from table output that contains an ellipsis (`...` or `…`). Rich table rendering can shorten UUID cells when several columns are shown. For follow-up commands, first run a JSON command with `--properties id,name`, copy the full UUID from JSON, then call commands such as `descript compositions list PROJECT_ID`.
</principle>

<principle name="Composition Export Auto-Open">
Composition export requires Descript running with CDP on port 9222, but the target project does NOT need to be open. When the project page is not visible, the CLI auto-opens it via the `descript://project/<project-id>` deep link and polls CDP up to 60 seconds for the project page, failing loudly if it never appears. Do not manually open projects before exporting.
</principle>

<principle name="Composition Export macOS Privacy Grants">
Composition export needs TWO distinct macOS privacy grants for the RESPONSIBLE HOST APP of the calling process (TCC attributes grants to the app that launched the process — e.g. /Applications/Claude.app when run from Claude, or Terminal/iTerm for shells):

1. **Accessibility** (System Settings > Privacy & Security > Accessibility) — required for the System Events UI scripting that drives Descript's native save dialog. The CLI probes this before triggering the export and fails fast with grant guidance when missing (instead of spinning for the 300s save-dialog timeout).
2. **Full Disk Access** (System Settings > Privacy & Security > Full Disk Access) — required for the calling app.

Preflight consumers (e.g. the youtube-manager workflow) must ensure the host app has both grants before starting an export.

**Claude desktop gotcha:** the Accessibility list shows TWO Claude entries. Capital-C **Claude** is the desktop shell at /Applications/Claude.app; lowercase **claude** is the embedded Claude Code runtime bundle (~/Library/Application Support/Claude/claude-code/&lt;version&gt;/claude.app) that actually runs shell commands. TCC attributes the CLI's osascript calls to the lowercase **claude** bundle — granting only the capital-C Claude is not enough. Enable the lowercase **claude** entry (observed 2026-06-11: exports failed with -25211 while capital-C Claude was granted).
</principle>

<principle name="Composition Export Wait">
Full composition exports render through the Descript desktop app and can take awhile. The CLI waits up to 30 minutes after the save dialog is accepted before timing out, then verifies the exported file is nontrivial and stable before reporting success.
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
