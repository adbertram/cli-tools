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
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `copilot` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **whoami** — Current user info (ID, business unit, org)
- **auth** — Login, logout, status, refresh, test credentials
- **auth** -- Authentication commands and nested `auth profiles` management
- **agent** — Core agent CRUD, publish, prompt; subgroups: knowledge, topic, trigger, tool, transcript, analytics, auth, model, channel
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

<gotcha name="Progress profile: discover profile, then preflight Azure CLI identity before file-producing commands">
Copilot auth profile names are local runtime state. Do not infer the Progress
profile name from the tenant or this skill; first run
`copilot auth profiles list --table`, then use the discovered profile name for
the whole command batch. The Progress profile should set
`AZURE_CLI_EXPECTED_USER` to `psdxautomation@progress.com` and the tenant to
`db266a67-cbe0-4d26-ae1a-d0581fe03535`. Before redirecting data commands such
as `copilot agent model list --profile "$profile"` or
`copilot agent list --profile "$profile"` into JSON files, run a shaped auth
preflight and preserve the producer status:

```bash
profile="${profile:?set profile from copilot auth profiles list --table}"

if copilot auth status --profile "$profile" >"$auth_out" 2>"$auth_err"; then
  auth_rc=0
else
  auth_rc=$?
fi

if [ "$auth_rc" -ne 0 ]; then
  if [ "$auth_rc" -eq 2 ] && rg -q -F '"authenticated": false' "$auth_out"; then
    printf 'COPILOT_AUTH_UNAUTHENTICATED profile=%s rc=%s\n' \
      "$profile" "$auth_rc" >&2
    cat "$auth_out" >&2
    exit 0
  fi
  printf 'COPILOT_AUTH_STATUS_FAILED rc=%s\n' "$auth_rc" >&2
  cat "$auth_err" >&2
  exit "$auth_rc"
fi
```

When running multiple `copilot` producers in one shell batch, capture each
producer status immediately after that command and carry the first non-zero
status to the final `exit`. Do not let later reporting commands such as
`wc`, `printf`, `head`, `jq`, or `ls` mask a failed producer command.
</gotcha>

<gotcha name="agent list: JSON is default, no --format flag">
`copilot agent list` emits JSON. JSON is already the default. Do not add `--format json`,
`--json`, or any output flag not listed for the leaf command. `copilot agent --help`
is group help only; before adding flags, inspect `usage.json` at
`commands.agent.commands.list.options` or run `copilot agent list --help`.
Use `--table` only when human-readable output is requested.
</gotcha>

<gotcha name="agent channel: read-only; Teams enablement and Direct Line secret are portal-only">
**The `copilot agent channel` subgroup is read-only — `list`, `get`, and `get-token` only.** There is no CLI command, and no supported Microsoft API, to *enable* a channel or *retrieve* the Web/Direct Line channel secret. The official Power Platform "PVA Bots" REST API exposes only quarantine operations, and Microsoft's own Copilot Studio Kit requires the Direct Line secret to be pasted in by hand. Enabling Teams and reading the secret are manual Copilot Studio portal actions:

- **Enable Microsoft Teams** (no API): publish the agent first (`copilot agent publish <id>`), then in Copilot Studio open **Channels** → **Teams and Microsoft 365 Copilot** → **Add channel**. Org-wide availability needs admin approval. Docs: https://learn.microsoft.com/microsoft-copilot-studio/publication-add-bot-to-microsoft-teams
- **Get the Direct Line / Web channel secret** (no API): in Copilot Studio open **Settings** → **Security** → **Web channel security**, then copy **Secret 1** or **Secret 2**. Teams-only licenses can't generate secrets (tokens are auto-managed). Docs: https://learn.microsoft.com/microsoft-copilot-studio/configure-web-security
- **For web embeds, prefer a token over the secret.** Run `copilot agent channel get-token <agent>` to mint a short-lived Direct Line token (no secret exposure), or exchange a secret for a token server-side via `POST https://directline.botframework.com/v3/directline/tokens/generate`. Never put the Direct Line secret in browser code.
</gotcha>

<gotcha name="tool/knowledge add: deterministic Copilot Studio capacity pre-check">
**Before attaching a tool or knowledge source, the CLI runs a fail-fast capacity pre-check on the target Power Platform environment. If the environment has no Copilot Studio capacity, the attach is blocked with a non-zero exit BEFORE any mutation.** This guards `copilot agent tool add`, `copilot agent knowledge add`, `copilot agent knowledge upload` (including its `--force` replace, whose existing-source delete is also blocked), and `copilot agent knowledge azure-ai-search add`. (`copilot agent create`/`update` are NOT gated — they take no inline tool/knowledge payload.)

An environment is entitled to attach tools/knowledge if EITHER:
- Prepaid Copilot Studio capacity (Copilot Credits) is allocated to it — one of the currencies `MCSMessages`, `MCSSessions`, or `VAConversations` has a positive allocation (`GET https://api.powerplatform.com/licensing/environments/{id}/allocations`); OR
- It is covered by an Enabled pay-as-you-go billing policy (`GET https://api.powerplatform.com/licensing/billingPolicies` + each policy's `/environments`).

When not entitled, the command exits non-zero with a `CapacityError` whose message names the environment and lists three fixes: allocate prepaid capacity in the Power Platform admin center (Licensing > Copilot Studio, https://admin.powerplatform.microsoft.com), link a pay-as-you-go billing policy, or use an environment that already has capacity. This is an environment-capacity policy, not a CLI defect — do not retry; allocate capacity or switch environments. A 404 on the allocations endpoint means "no allocation" (Developer environments), so the env is treated as not entitled. Any other non-200/404 on allocations, or a non-200 on a policy's `/environments` lookup, is undeterminable and raises an error (the signal cannot be confirmed) rather than silently allowing the attach. The target environment id is resolved from `DATAVERSE_ENVIRONMENT_ID`/`POWERPLATFORM_ENVIRONMENT_ID`, or matched from `DATAVERSE_URL`; if neither resolves, the command fails with a clear message.
</gotcha>
</gotchas>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
