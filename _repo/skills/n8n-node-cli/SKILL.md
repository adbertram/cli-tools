---
name: n8n-node-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute n8n-node operations using the `n8n-node` CLI tool.
  Manage n8n community node packages -- convert CLI tools, deploy to adam-server, test nodes, manage credentials, and query logs.
  Triggers: n8n-node, n8n node, n8n node cli, convert cli to n8n node, deploy n8n node, test n8n node, n8n credentials, n8n logs, n8n executions, n8n community node
---

<objective>
Execute n8n-node operations using the `n8n-node` CLI. All n8n node package management should use this CLI.
</objective>

<quick_start>
The `n8n-node` CLI has both top-level commands and command groups:
```bash
n8n-node <command> [arguments] [options]
n8n-node <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Convert CLI tool to n8n node | `n8n-node convert-cli-tool TOOL_NAME` |
| Deploy node to server | `n8n-node deploy NODE_NAME` |
| Test an installed node | `n8n-node test NODE_NAME -r resource -o operation` |
| List available CLI tools | `n8n-node tools list --table` |
| List generated packages | `n8n-node nodes list --table` |
| List server credentials | `n8n-node credentials list --table` |
| View execution errors | `n8n-node logs executions --status error --table` |
| View app logs | `n8n-node logs app --lines 100` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `n8n-node` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **convert-cli-tool** -- Convert a CLI tool into an n8n node package (top-level)
- **test** -- Test an installed n8n node via webhook workflow (top-level)
- **deploy** -- Deploy a node package to adam-server (top-level)
- **auth** -- Configure directories (login, logout, status)
- **tools** -- List and inspect available CLI tools (list, get)
- **nodes** -- List and inspect generated packages (list, get)
- **credentials** -- Manage server credentials (list, create, delete, schema)
- **logs** -- Query logs and executions (executions, events, app, errors, all, config, set-level)
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
