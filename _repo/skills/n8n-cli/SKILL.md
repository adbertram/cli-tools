---
name: "n8n-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Use this skill for ALL n8n CLI operations. DO NOT run `n8n` CLI commands or guess flag syntax without loading this skill first. Covers workflows, nodes, executions, credentials, data tables, server/logs, auth, and profiles. Triggers: n8n, n8n cli, n8n workflows, n8n executions, n8n credentials, n8n nodes, n8n data tables, list n8n workflows, n8n server logs, my n8n, trigger n8n workflow, n8n execution history, install n8n node"
---

<objective>
Execute n8n operations using the `n8n` CLI. All n8n interactions should use this CLI.
</objective>

<quick_start>
The `n8n` CLI follows this pattern:
```bash
n8n <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List workflows | `n8n workflows list --table` |
| Get workflow detail | `n8n workflows get <workflow_id>` |
| Trigger a workflow | `n8n workflows execute <workflow_id>` |
| Query recent executions | `n8n executions list --filter created_at:gte:2026-04-11 --table` |
| Get execution detail | `n8n executions get <execution_id>` |
| List credentials | `n8n credentials list --table` |
| List data-table rows | `n8n data-tables rows <table_id> --table` |
| Check server version | `n8n server version` |
| Check auth status | `n8n auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `n8n` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- login, logout, status, refresh, test credentials
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** -- manage the local response cache
- **workflows** -- list, get, create, update, delete, activate, deactivate, export, execute, assign-error-handler, node
- **nodes** -- test, create, deploy, remove, install, list, get community node packages
- **credentials** -- list, get, create, delete, rename, schema for server credentials
- **data-tables** -- CRUD on n8n Data Tables (list, get, create, delete, columns, rows, insert, update-rows, delete-rows)
- **executions** -- query execution history (list, get, events via SSH)
- **server** -- upgrade, version, restart, logs, config
</principle>

<principle name="Filter Syntax">
All list commands support `--filter/-f` using `field:op:value` syntax.
Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `like`, `ilike`, `null`, `notnull`, `contains`, `startswith`, `endswith`.
Examples: `--filter name:contains:sync`, `--filter active:eq:true`, `--filter created_at:gte:2026-04-11`.
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
