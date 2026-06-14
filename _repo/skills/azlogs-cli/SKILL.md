---
name: azlogs-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute azlogs operations using the `azlogs` CLI tool.
  Download, parse, and analyze Azure Web App logs via Kudu API.
  Triggers: azlogs, azlogs cli, azure logs, azure web app logs, download azure logs, query log entries, azlogs packages, azlogs entries, log analysis report, kudu logs
---

<objective>
Execute azlogs operations using the `azlogs` CLI. All azlogs interactions should use this CLI.
</objective>

<quick_start>
The `azlogs` CLI follows this pattern:
```bash
azlogs <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `azlogs auth status` |
| Download fresh logs | `azlogs packages download` |
| Download logs (last 3 days) | `azlogs packages download --since 3d` |
| List downloaded packages | `azlogs packages list --table` |
| List error entries | `azlogs entries list PACKAGE --filter "level:eq:ERROR"` |
| Query entries by service | `azlogs entries list PACKAGE --filter "service:ilike:%name%"` |
| Generate HTML report | `azlogs report generate PACKAGE --open` |
| Re-parse a package | `azlogs packages parse PACKAGE --since 12h` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `azlogs` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Check Azure CLI authentication status
- **packages** -- Manage downloaded log packages (download, list, get, parse, validate, delete)
- **entries** -- Query parsed log entries from packages (list, get)
- **report** -- Generate HTML log analysis reports
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
