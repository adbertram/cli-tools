---
name: mindmeister-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute mindmeister operations using the `mindmeister` CLI tool.
  CLI interface for MindMeister API -- manage mind maps, ideas/nodes, and exports.
  Triggers: mindmeister, mindmeister cli, mind map, mind maps, mindmeister maps, create mind map, mindmeister ideas, export mind map, mindmeister nodes
---

<objective>
Execute mindmeister operations using the `mindmeister` CLI. All mindmeister interactions should use this CLI.
</objective>

<quick_start>
The `mindmeister` CLI follows this pattern:
```bash
mindmeister <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `mindmeister auth status` |
| List all maps | `mindmeister maps list --table` |
| Get map with nodes | `mindmeister maps get MAP_ID` |
| Create empty map | `mindmeister maps create --title "My Map"` |
| Create map from JSON | `mindmeister maps create --json-file map.json` |
| List nodes as tree | `mindmeister ideas list MAP_ID --tree` |
| Create map with children | `mindmeister ideas create-map "Root" -c "Branch 1" -c "Branch 2"` |
| Export map | `mindmeister maps export MAP_ID` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `mindmeister` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage Personal Access Token authentication (login, logout, status)
- **maps** -- CRUD operations on mind maps (list, get, create, update, duplicate, delete, export)
- **ideas** -- Manage nodes within maps (list, toggle-closed, create-map, import, create-annotated)
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
