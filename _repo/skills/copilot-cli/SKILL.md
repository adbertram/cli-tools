---
name: copilot-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute Copilot Studio operations using the `copilot` CLI tool.
  CLI interface for Microsoft Copilot Studio agents via Dataverse API.
  Triggers: copilot, copilot cli, copilot studio, copilot agent, manage copilot agents,
  copilot studio agents, copilot topics, copilot knowledge, copilot tools,
  copilot connectors, power platform copilot, copilot flows, copilot solutions,
  copilot prompts, copilot models, copilot environment, copilot connections
---

<objective>
Execute Copilot Studio operations using the `copilot` CLI. All Copilot Studio interactions should use this CLI.
</objective>

<quick_start>
The `copilot` CLI follows this pattern:
```bash
copilot <command-group> <action> [arguments] [options]
```

| Command | Description |
|---------|-------------|
| `copilot agent list --table` | List all agents with formatted output |
| `copilot agent get <id>` | Get agent details by GUID |
| `copilot agent create --name "Name"` | Create a new agent |
| `copilot agent prompt <id> -m "msg"` | Send a message to an agent |
| `copilot agent publish <id>` | Publish agent changes |
| `copilot agent knowledge list <id>` | List agent knowledge sources |
| `copilot agent tool list -a <id>` | List tools attached to an agent |
| `copilot agent topic list -a <id>` | List agent topics |
| `copilot solution list --table` | List solutions |
| `copilot auth status` | Check authentication status |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `copilot` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **whoami** — Current user info (ID, business unit, org)
- **auth** — Login, logout, status, refresh, test credentials
- **auth** -- Authentication commands and nested `auth profiles` management
- **agent** — Core agent CRUD, publish, prompt; subgroups: knowledge, topic, trigger, tool, transcript, analytics, auth, model
- **solution** — Solution lifecycle (create, export, import); subgroups: agent, connection-reference, custom-connector, component, publisher
- **powerautomate-flow** — List/inspect Power Automate cloud flows
- **agent-flow** — Agent flow lifecycle (create, export, import, test, enable/disable); subgroups: runs, scaffold
- **tool** — Discover tools (prompts, MCP, connectors); subgroups: restapi, mcp
- **prompt** — AI Builder prompt lifecycle (create, update, run, publish); subgroups: permissions, auth
- **model** — AI Builder model management (list, enable, disable)
- **managed-connector** — Browse Microsoft's built-in connector catalog
- **custom-connector** — Custom connector lifecycle (create from OpenAPI, validate, register, remove)
- **connections** — Manage authenticated connections (credentials); subgroup: onedrive
- **connection-references** — Solution-aware connection pointers (create, update, remove)
- **environment** — Power Platform environment management (list, select, create, delete)
- **admin** — Auth identity management (app registrations, service principals)
- **user-licenses** — Check M365 license assignments via Microsoft Graph
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<gotchas>
<gotcha name="JSON examples in instructions or response-format files">
**`copilot agent update <id> --instructions-file <f>` and `--response-format-file <f>` write into TemplateLine fields whose default template format is Power Fx.** Power Fx treats `{ ... }` as a record literal, so a JSON example inside the file (e.g. `{ "summary_markdown": "..." }`) breaks `copilot agent publish` with:

```
Unexpected character in expression '
  "summary_markdown": "..."
```

The CLI handles this automatically: when content contains `{`, the emitted YAML adds `template: { kind: TemplateEngineOptions, format: Mustache }` so the publisher uses Mustache (which uses `{{ ... }}` for expressions) and a single `{` is plain text. **No escaping is needed in the source content.** Keep JSON shape examples written naturally.

If you ever see "Unexpected character in expression" on `copilot agent publish` for an agent whose response-format file or instructions file contains `{`, suspect the Mustache opt-in is missing — check `client.py` `build_gpt_component_yaml`.
</gotcha>
</gotchas>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
