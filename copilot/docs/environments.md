# Environments

Manage Power Platform environments — list, view, create, delete, rename, and configure environment-level settings.

## Environment Commands

### List Environments

```bash
copilot environment list                        # All environments (JSON)
copilot environment list --table                # Formatted table
copilot environment list --filter "dev"         # Filter by name
```

| Option | Description |
|--------|-------------|
| `-f, --filter` | Filter by name (case-insensitive) |

### Get Environment Details

```bash
copilot environment get <environment-id>
copilot environment get Default-<tenant-id>
```

### Select Environment

Set the active environment for all CLI operations. Updates the `.env` file with the selected environment's Dataverse URL and environment ID.

```bash
copilot environment select <environment-id>
copilot environment select 12345678-1234-1234-1234-123456789012
```

After selecting an environment, all subsequent CLI commands target it without needing to specify it explicitly.

### Show Current Environment

Show which environment the CLI is currently targeting.

```bash
copilot environment current
copilot environment current --table
```

### Create Environment

Create a new environment, optionally with a Dataverse database.

```bash
copilot environment create --name "Testing"
copilot environment create --name "Dev Environment" --type Developer
copilot environment create --name "EU Sandbox" --location europe --type Sandbox
copilot environment create --name "Empty Env" --no-dataverse
```

| Option | Description |
|--------|-------------|
| `-n, --name` | Display name (required) |
| `-l, --location` | Azure region (default: `unitedstates`). Use `locations` to list. |
| `-t, --type` | `Sandbox`, `Production`, `Developer`, `Trial`, or `Teams` (default: `Sandbox`) |
| `-d, --description` | Description |
| `--no-dataverse` | Skip Dataverse provisioning |
| `--language` | Dataverse base language code (default: `1033`) |
| `--currency` | Dataverse currency code (default: `USD`) |

### Delete Environment

Permanently delete an environment **and all its data** (apps, flows, agents, Dataverse tables, records).

```bash
copilot environment delete <environment-id>
copilot environment delete <environment-id> --force            # Skip confirmation
copilot environment delete <environment-id> --force --wait     # Wait until fully deleted
```

| Option | Description |
|--------|-------------|
| `-f, --force` | Skip confirmation prompt |
| `-w, --wait` | Poll until deletion completes |
| `-T, --timeout` | Max seconds to wait when using `--wait` (default: `300`) |

### Rename Environment

Change an environment's display name (the ID stays the same).

```bash
copilot environment rename <environment-id> "New Name"
copilot environment rename <environment-id> "Dev Environment" --table
```

### List Locations

List Azure regions where new environments can be created.

```bash
copilot environment locations
copilot environment locations --table
```

### Get Environment Settings

Retrieve all (or selected) environment management settings.

```bash
copilot environment settings <environment-id>
copilot environment settings <environment-id> --select copilotStudio_ConnectedAgents,copilotStudio_CodeInterpreter
copilot environment settings <environment-id> --table
```

| Option | Description |
|--------|-------------|
| `-s, --select` | Comma-separated list of setting names to return (default: all) |

### Update Environment Settings

Update one or more environment management settings via PATCH. Use `settings` first to discover valid keys.

```bash
copilot environment update <environment-id> --setting copilotStudio_ConnectedAgents=true
copilot environment update <environment-id> -s copilotStudio_CodeInterpreter=true -s copilotStudio_ConnectedAgents=false
copilot environment update <environment-id> --setting enableIpBasedStorageAccessSignatureRule=true
```

Values are auto-typed: `true`/`false` → bool, digits → int, otherwise string.
