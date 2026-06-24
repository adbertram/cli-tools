---
name: n8n-cli-tool-node-converter-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute n8n-cli-tool-node-converter operations using the `n8n-cli-tool-node-converter` CLI tool.
  Convert standardized CLI tools into n8n community node packages.
  Triggers: n8n-cli-tool-node-converter, n8n node converter, convert cli to n8n, generate n8n node, n8n community node, cli to n8n node
---

<objective>
Execute n8n-cli-tool-node-converter operations using the `n8n-cli-tool-node-converter` CLI. All CLI-to-n8n-node conversion should use this CLI.
</objective>

<quick_start>
The `n8n-cli-tool-node-converter` CLI follows this pattern:
```bash
n8n-cli-tool-node-converter <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check config status | `n8n-cli-tool-node-converter auth status` |
| List available CLI tools | `n8n-cli-tool-node-converter tools list --table` |
| Inspect a CLI tool | `n8n-cli-tool-node-converter tools get TOOL_NAME --table` |
| Generate n8n node | `n8n-cli-tool-node-converter nodes generate TOOL_NAME` |
| List generated packages | `n8n-cli-tool-node-converter nodes list --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `n8n-cli-tool-node-converter` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Configure CLI tools and output directories (login, logout, status)
- **tools** -- List and inspect available CLI tools (list, get)
- **nodes** -- Generate and manage n8n node packages (generate, list, get)
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
