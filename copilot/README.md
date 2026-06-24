# Copilot CLI Guide

## DESCRIPTION

The `copilot` CLI provides a command-line interface for Microsoft Copilot Studio agents via Dataverse API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Overview

The Copilot CLI provides access to:
- **Auth** - Manage CLI authentication (login, status, logout, profiles)
- **Agents** - Create, update, delete, publish, and test agents
- **Channels** - List/inspect agent channels and get Direct Line tokens (Teams enablement and secret retrieval are portal-only — see [Channels](#channels))
- **Topics** - Manage conversation flows (list, create, update, delete, enable/disable)
- **Agent Tools** - Connect connectors, prompts, flows, HTTP endpoints, or sub-agents as tools
- **Knowledge** - Add file-based and Azure AI Search knowledge sources
- **Analytics** - Query Application Insights telemetry for troubleshooting
- **Transcripts** - View conversation history for debugging
- **Connectors** - Manage managed and custom Power Platform connectors (API definitions)
- **Connections** - Manage authenticated credentials and connection references
- **Tools** - Manage AI Builder prompts, REST APIs, MCP servers, and AI Builder models
- **Solutions** - Manage solutions, publishers, and solution components
- **Agent Flows** - Create, manage, export/import, test, and delete Copilot Studio agent flows
- **Power Automate Flows** - List and view Power Automate cloud flows
- **Environments** - List, view, create, delete, and configure Power Platform environments

## Installation

### 1. Install the CLI

From the cloned cli-tools repo:
```bash
cd <cli-tools-root>/copilot
uv tool install -e . --force --refresh
```

For development (editable install):
```bash
cd <cli-tools-root>/copilot
pip install -e .
```

### 2. Install Azure CLI

The `copilot` CLI uses Azure CLI to obtain Dataverse tokens. Install it from [aka.ms/installazurecli](https://aka.ms/installazurecli), or use one of:

```bash
# macOS
brew install azure-cli

# Windows (PowerShell, admin)
winget install -e --id Microsoft.AzureCLI

# Linux (Debian/Ubuntu)
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

### 3. Configure credentials

Profiles live under the cli-tools user profile directory, not the repo. Copy
the template into place:

```bash
# macOS / Linux
mkdir -p ~/.local/share/cli-tools/copilot/authentication_profiles/default
cp .env.example ~/.local/share/cli-tools/copilot/authentication_profiles/default/.env
# edit the copy and set DATAVERSE_URL=https://yourorg.crm.dynamics.com
```

```powershell
# Windows
New-Item -ItemType Directory -Force "$env:APPDATA\cli-tools\copilot\authentication_profiles\default"
Copy-Item .env.example "$env:APPDATA\cli-tools\copilot\authentication_profiles\default\.env"
```

Secrets (`AZURE_CLIENT_SECRET`, `M365_SDK_CLIENT_SECRET`,
`DIRECTLINE_SECRET`) live in the CLI-tools secret manager. The profile
`.env` contains only `secret://...` placeholders. Set them with:

```bash
copilot config set-secret AZURE_CLIENT_SECRET
```

Then run the guided login (see [docs/auth.md](docs/auth.md) for details):
```bash
copilot auth login
```

The CLI reads only the canonical cli-tools profile layout. Older profile files
must be moved into `~/.local/share/cli-tools/copilot/authentication_profiles/`
before running the tool.

### 4. Verify

```bash
copilot whoami
```

If that prints your user info, you're ready to go.

## Quick Start

```bash
# 1. Log in (Azure CLI must be installed)
az login
export DATAVERSE_URL=https://yourorg.api.crm.dynamics.com

# 2. Verify authentication
copilot auth status

# 3. List your agents
copilot agent list --table
```

For full authentication setup including profiles, see [docs/auth.md](docs/auth.md).

## Command Groups

Common command-group entry points:

```bash
copilot cache clear
copilot powerautomate-flow list --table
copilot agent-flow list --table
copilot managed-connector list --limit 10
copilot custom-connector list --limit 10
copilot connection-references list --table
copilot user-licenses list --user-id user@contoso.com
```

Additional examples:

```bash
copilot tool list --type mcp --table
copilot tool mcp tools list --url "https://mcp.example.com/sse" --limit 10
copilot environment list --table
copilot solution list --table
```

### Capacity requirement for attaching tools and knowledge

Before attaching a tool or knowledge source, the CLI runs a deterministic, fail-fast
capacity pre-check on the target Power Platform environment. The attach is blocked
(non-zero exit, no mutation) when the environment has **no Copilot Studio capacity**.
This guards:

```bash
copilot agent tool add --agentId <id> --toolType <type> --id <tool-id>
copilot agent knowledge add <agent-id> --component <component-id>
copilot agent knowledge upload <agent-id> --file <path> --name <name>
copilot agent knowledge azure-ai-search add <agent-id> --name ... --endpoint ... --index ... --api-key ...
```

An environment is entitled when **either** prepaid Copilot Studio capacity (Copilot
Credits — `MCSMessages`, `MCSSessions`, or `VAConversations`) is allocated to it,
**or** it is covered by an Enabled pay-as-you-go billing policy. When not entitled,
the command exits with an error naming the environment and three fixes: allocate
prepaid capacity in the [Power Platform admin center](https://admin.powerplatform.microsoft.com)
(Licensing → Copilot Studio), link a pay-as-you-go billing policy, or use an
environment that already has capacity. `copilot agent create` / `update` are not
gated (they take no inline tool/knowledge payload).

## Channels

The `copilot agent channel` subgroup is **read-only**:

```bash
copilot agent channel list <agent-id> --table     # list channels for an agent
copilot agent channel get <agent-id> directline    # inspect one channel
copilot agent channel get-token <agent-id>          # mint a short-lived Direct Line token
```

Enabling a channel and retrieving the Web/Direct Line secret have **no supported Microsoft API** — the Power Platform "PVA Bots" REST API covers only quarantine operations, and even Microsoft's Copilot Studio Kit requires the secret to be entered by hand. These stay manual Copilot Studio portal steps:

- **Enable Microsoft Teams:** publish the agent (`copilot agent publish <id>`), then in Copilot Studio go to **Channels → Teams and Microsoft 365 Copilot → Add channel**. Org-wide availability needs admin approval. See the [Microsoft docs](https://learn.microsoft.com/microsoft-copilot-studio/publication-add-bot-to-microsoft-teams).
- **Get the Direct Line / Web channel secret:** in Copilot Studio go to **Settings → Security → Web channel security** and copy **Secret 1** or **Secret 2**. Teams-only licenses can't generate secrets. See the [Microsoft docs](https://learn.microsoft.com/microsoft-copilot-studio/configure-web-security).

**For web embeds, prefer a token over the secret.** `copilot agent channel get-token <agent-id>` returns a short-lived Direct Line token without exposing the secret. If you must use the secret, exchange it for a token server-side via `POST https://directline.botframework.com/v3/directline/tokens/generate` — never embed the raw secret in browser code.

## Documentation

| Topic | Doc |
|-------|-----|
| Configuration paths, profile storage, secret placeholders | [docs/configuration.md](docs/configuration.md) |
| Authentication, profiles, login/logout, user info | [docs/auth.md](docs/auth.md) |
| Agents, agent tools, knowledge, analytics, transcripts | [docs/agents.md](docs/agents.md) |
| Topics (conversation flows) and YAML examples | [docs/topics.md](docs/topics.md) |
| Topic YAML schema reference | [docs/topic-yaml-schema.md](docs/topic-yaml-schema.md) |
| Tools: AI Builder prompts, REST APIs, MCP servers, models, prompt auth | [docs/tools.md](docs/tools.md) |
| Managed and custom connectors | [docs/connectors.md](docs/connectors.md) |
| Connections and connection references | [docs/connections.md](docs/connections.md) |
| Solutions, publishers, deployment, cross-environment migration | [docs/solutions.md](docs/solutions.md) |
| Agent flows and Power Automate flows | [docs/flows.md](docs/flows.md) |
| Power Platform environments | [docs/environments.md](docs/environments.md) |
| Troubleshooting, debug workflow, exit codes | [docs/troubleshooting.md](docs/troubleshooting.md) |

## Development

Run the local test suite with uv:

```bash
uv run pytest
```

## Requirements

- **Python**: 3.10 or higher
- **Azure CLI**: Required for authentication (`az login`)
- **Dependencies** (installed automatically):
  - `typer>=0.9.0` - CLI framework
  - `python-dotenv>=1.0.0` - Environment variable management
  - `httpx>=0.25.0` - HTTP client
  - `msal>=1.28.0` - Microsoft authentication
  - `PyYAML>=6.0.0` - YAML parsing
  - `microsoft-agents-copilotstudio-client>=0.6.1` - Copilot Studio SDK
