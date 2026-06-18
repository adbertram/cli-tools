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

<gotcha name="agent prompt: Power Platform cloud is auto-resolved (do not set POWERPLATFORM_CLOUD_URL)">
**For integrated-auth agents ("Authenticate with Microsoft"), `copilot agent prompt` uses the M365 Agents SDK and derives the Power Platform cloud automatically from the environment's Dataverse host** — no cloud config is needed for normal commercial tenants (`*.crm.dynamics.com` → public cloud `api.powerplatform.com`). Sovereign clouds are mapped from the Dataverse host too: GCC (`*.crm9.dynamics.com`), GCC High (`*.crm.microsoftdynamics.us`), DoD (`*.crm.appsplatform.us`), China (`*.crm.dynamics.cn`).

Do NOT set `POWERPLATFORM_CLOUD_URL` to force a cloud — that legacy profile value held a Direct Line *island-gateway* host and is ignored for SDK cloud selection. Forcing the SDK's `Other` cloud with a host-only value caused `M365 SDK request failed: ... PowerPlatformCloud is Other` (error code `-65003`); this is fixed by the auto-resolver.

Override only for a cloud the host table cannot classify: set `POWERPLATFORM_CLOUD` to a `PowerPlatformCloud` enum name understood by the SDK (`Prod`, `Gov`, `High`, `DoD`, `Mooncake`). A free-form base address is intentionally NOT accepted because the SDK's `Other` base-address path cannot build a valid connection URL.
</gotcha>

<gotcha name="agent prompt: 405 'App-only S2S access is not enabled' (use delegated auth)">
**If `copilot agent prompt` reaches the agent but fails with HTTP `405` while the active profile has a service-principal secret (`AZURE_CLIENT_SECRET`/`M365_SDK_CLIENT_SECRET`), the environment does not allow app-only (service principal) access to Copilot Studio conversations.** The Direct-to-Engine endpoint returns `App-only S2S access is not enabled for this environment.`

Fix: use delegated (user) auth — run with a profile that has no service-principal secret so the device-code sign-in flow runs — or have an admin enable app-only S2S access for the environment. This is an environment/tenant policy, not a CLI defect; the CLI now prints this cause and fix when it detects the condition.
</gotcha>

<gotcha name="auth status: unauthenticated profile exits 2 with JSON status data">
`copilot auth status --profile default` can exit `2` for an unauthenticated
profile while still returning structured JSON that includes `"authenticated":
false`. Treat that as status data, not an unhandled tool failure, when the probe
is intentionally checking auth state. Wrap the command per the cli-tool
`Shape Expected Auth Status Probes` rule and validate both exit status `2` and
the unauthenticated evidence before exiting `0`.
</gotcha>

<gotcha name="agent list: JSON is default, no --format flag">
`copilot agent list` emits JSON. JSON is already the default. Do not add `--format json`,
`--json`, or any output flag not listed for the leaf command. `copilot agent --help`
is group help only; before adding flags, inspect `usage.json` at
`commands.agent.commands.list.options` or run `copilot agent list --help`.
Use `--table` only when human-readable output is requested.
</gotcha>
</gotchas>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
