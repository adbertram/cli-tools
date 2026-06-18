# {ToolName} CLI

## DESCRIPTION

A command-line interface for {ServiceName}. {Brief description of what users can do with this CLI}.

Use this CLI when you need scriptable, JSON-first access to {ServiceName} from agents, automation, or terminal workflows.

## Docs

- Service/API docs: {service_url}

## Installation

```bash
cd <cli-tools-root>/{toolname}
uv tool install -e . --force --refresh
```

After installation, the `{toolname}` command will be available in your terminal.

## Quick Start

```bash
# {Optional auth login example when auth exists}
# {toolname} auth login

{toolname} {command_group} list --limit 10
{toolname} {command_group} list --limit 10 --table
{toolname} {command_group} get RESOURCE_ID --table
```

## Commands

### Authentication

{Include this section only when the scaffold creates auth commands.}

```bash
{toolname} auth login
{toolname} auth login --force
{toolname} auth status
{toolname} auth test
{toolname} auth logout
```

### Profiles

{Include this section only when the scaffold creates auth commands.}

```bash
{toolname} auth profiles list
{toolname} auth profiles get default
{toolname} auth profiles create PROFILE_NAME
{toolname} auth profiles select PROFILE_NAME
{toolname} auth profiles delete PROFILE_NAME
```

### {CommandGroup}

```bash
{toolname} {command_group} list --limit 25
{toolname} {command_group} list --limit 25 --table
{toolname} {command_group} list --filter "status:eq:active"
{toolname} {command_group} list --properties "id,name"
{toolname} {command_group} get RESOURCE_ID --table
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

### JSON Output Example

```bash
{toolname} {command_group} list --limit 2
```

```json
[
  {
    "id": "123",
    "name": "Example Item",
    "status": "active"
  }
]
```

### Table Output Example

```bash
{toolname} {command_group} list --limit 5 --table
```

```
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Id       ┃ Name          ┃ Status ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ 123      │ Example Item  │ active │
└──────────┴───────────────┴────────┘
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution (when cache is enabled) |

{Remove options only when the scaffold truly does not generate them.}

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/{toolname}/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/{toolname}/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional non-authentication configuration
BASE_URL=https://api.example.com
CACHE_ENABLED=true
CACHE_TTL=3600
```

Authentication profile variables (CLI-managed runtime auth state):

```bash
ACTIVE=true
ACCESS_TOKEN=<managed-by-cli>
REFRESH_TOKEN=<managed-by-cli>
TOKEN_EXPIRES_AT=2026-01-01T00:00:00Z
```

Reusable raw credentials belong in the CLI-tools secret manager, not in `.env` files. If the CLI persists secret-manager references into the active profile, they look like:

```bash
API_KEY=secret://{toolname}-api-key
PERSONAL_ACCESS_TOKEN=secret://{toolname}-personal-access-token
CLIENT_ID=secret://{toolname}-client-id
CLIENT_SECRET=secret://{toolname}-client-secret
USERNAME=secret://{toolname}-username
PASSWORD=secret://{toolname}-password
```

Include the auth-profile block only when the scaffold creates auth commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

```bash
{toolname} {command_group} list --properties "id,name" | jq '.[].id'
{toolname} {command_group} list --limit 200 > output.json
```

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"`.

Do not document or implement `auth status --validate`, wrapped `items` payloads, or other legacy command shapes that no longer exist.

### {Use Case 3 Title}

```bash
{toolname} {command} {subcommand} | jq '.items[].id'
```

### Script-Friendly JSON Output

```bash
# Get specific field from results
{toolname} {group} list | jq '.items[].id'

# Process multiple items
{toolname} {group} list | jq -r '.items[] | "\(.id): \(.name)"'
```

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - {additional dependencies}

## License

MIT

---

## Template Instructions

When creating a new CLI README:

1. **Replace all placeholders** - Search for `{` and replace with actual values
2. **Add command groups** - Copy the CommandGroup section for each command group in your CLI
3. **Update options table** - Include only options your CLI actually supports
4. **Add real examples** - Replace example commands with actual working commands
5. **Update configuration** - List all environment variables your CLI uses
6. **Add dependencies** - List all packages from pyproject.toml
7. **Remove this section** - Delete this "Template Instructions" section from the final README

### Placeholder Reference

| Placeholder | Example |
|-------------|---------|
| `{ToolName}` | ShopGoodwill |
| `{toolname}` | shopgoodwill |
| `{TOOLNAME}` | SHOPGOODWILL |
| `{ServiceName}` | ShopGoodwill.com |
| `{service_url}` | https://shopgoodwill.com |
| `{CommandGroup1}` | Search |
| `{group}` | search |
| `{resource}` | item |
| `{resource_id}` | 123456789 |
