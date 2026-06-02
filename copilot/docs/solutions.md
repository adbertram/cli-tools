# Solutions

Manage Dataverse solutions, publishers, and solution components. Solutions package agents, flows, connections, and other components for deployment between environments.

## Solution Commands

### List Solutions

```bash
copilot solution list                           # Visible solutions (JSON)
copilot solution list                   # Formatted table
copilot solution list --unmanaged               # Only unmanaged solutions
copilot solution list --include-invisible       # Include internal/system solutions
```

| Option | Description |
|--------|-------------|
| `-u, --unmanaged` | Only show unmanaged solutions (solutions you can modify) |
| `--include-invisible` | Include solutions not visible in the Power Apps UI |

**Output Columns:**
- **Display Name** - Friendly name of the solution
- **Name** - Unique name (schema name)
- **Version** - Solution version
- **Managed** - Yes/No indicating if managed
- **Preferred** - Yes if this is the user's default solution for new components

### Get Solution Details

```bash
copilot solution get <solution-id>
```

### Update Solution

Update solution settings including the preferred solution.

```bash
copilot solution update <solution-id> --preferred      # Set as preferred solution
copilot solution update <solution-id> --no-preferred   # Unset as preferred solution
```

| Option | Description |
|--------|-------------|
| `--preferred/--no-preferred` | Set or unset this solution as the preferred solution for the current user |

**Note:** The preferred solution is the default location where new components are automatically added when created outside of a specific solution context.

### Create Solution

```bash
copilot solution create --name "My Solution" --unique-name MySolution --publisher MyPublisher
copilot solution create -n "My Solution" -u MySolution -p MyPublisher -v 1.0.0.0
copilot solution create -n "My Solution" -u MySolution -p MyPublisher -d "Description"
```

| Option | Description |
|--------|-------------|
| `-n, --name` | Display name for the solution (required) |
| `-u, --unique-name` | Unique name (no spaces, required) |
| `-p, --publisher` | Publisher's unique name or GUID (required) |
| `-v, --version` | Version (default: 1.0.0.0) |
| `-d, --description` | Optional description |

### Delete Solution

```bash
copilot solution delete <solution-id>
```

### Export Solution

Export a solution as a zip file for deployment to another environment.

```bash
# Export as unmanaged solution
copilot solution export MySolution -o MySolution.zip

# Export as managed solution
copilot solution export MySolution --managed -o MySolution_managed.zip

# With custom timeout for large solutions
copilot solution export MySolution -o MySolution.zip --timeout 600
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `solution` | The solution's unique name (not the display name) |

| Option | Description |
|--------|-------------|
| `-o, --output` | Output file path for the exported solution zip (required) |
| `-m, --managed` | Export as managed solution (default: unmanaged) |
| `-T, --timeout` | Maximum time to wait for export in seconds (default: 300) |

**Note:** Use the solution's unique name (schema name), not the display name. The unique name can be found with `copilot solution list`.

### Import Solution

Import a solution from a zip file.

```bash
# Basic import
copilot solution import MySolution.zip

# Stage and validate before import
copilot solution import MySolution.zip --stage

# Import with deployment settings
copilot solution import MySolution.zip -s settings.json

# Import and overwrite existing customizations
copilot solution import MySolution.zip --overwrite

# Import as solution upgrade
copilot solution import MySolution.zip --upgrade

# Skip confirmation prompt
copilot solution import MySolution.zip --force
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `file` | Path to the solution zip file to import |

| Option | Description |
|--------|-------------|
| `-s, --settings` | Path to deployment settings JSON file for connection mappings |
| `--overwrite` | Overwrite unmanaged customizations if they exist |
| `--publish-workflows` | Publish workflows after import |
| `--stage` | Stage and validate the solution before importing |
| `--upgrade` | Import as holding solution and apply upgrade |
| `-T, --timeout` | Maximum time to wait for import in seconds (default: 600) |
| `-F, --force` | Skip confirmation prompt |

### Create Deployment Settings

Generate a deployment settings template from a solution. This creates a JSON file listing connection references and environment variables that need to be configured for the target environment.

```bash
# Generate from existing solution zip
copilot solution create-settings -z MySolution.zip -o settings.json

# Export solution and generate settings
copilot solution create-settings -s MySolution -o settings.json
```

| Option | Description |
|--------|-------------|
| `-z, --zip` | Path to solution zip file to extract settings from |
| `-s, --solution` | Solution name to export and extract settings from |
| `-o, --output` | Output file path for the settings JSON (required) |

**Note:** Either `--zip` or `--solution` is required. If `--solution` is provided, the solution will be exported first.

**Deployment Settings Format:**

The generated settings file can be edited to map connections and environment variables for the target environment:

```json
{
  "ConnectionReferences": [
    {
      "LogicalName": "prefix_connectionrefname",
      "DisplayName": "My Connection",
      "ConnectorId": "/providers/Microsoft.PowerApps/apis/shared_asana",
      "ConnectionId": "",
      "_comment": "Set ConnectionId to the GUID of the connection in the target environment"
    }
  ],
  "EnvironmentVariables": [
    {
      "SchemaName": "prefix_VariableName",
      "DisplayName": "My Variable",
      "Type": "String",
      "Value": "",
      "_comment": "Set Value for the target environment"
    }
  ]
}
```

### Cross-Environment Migration Workflow

Complete workflow for migrating Copilot agents between environments:

```bash
# 1. Add agent to solution (if not already in one)
copilot solution agent add --solution MySolution --agent <agent-id>

# 2. Export solution from source environment
copilot solution export MySolution -o MySolution.zip

# 3. Generate deployment settings template
copilot solution create-settings -z MySolution.zip -o settings.json

# 4. Edit settings.json to map connections to target environment
# (Set ConnectionId values for each connection reference)

# 5. Switch to target environment
copilot environment set-default <target-env-id>

# 6. Import with settings (stage first for validation)
copilot solution import MySolution.zip -s settings.json --stage

# 7. For solution upgrades, use --upgrade flag
copilot solution import MySolution.zip -s settings.json --upgrade
```

## Solution Component Commands

### Add Agent to Solution

```bash
copilot solution add-agent --solution MySolution --agent <agent-id>
copilot solution add-agent -s MySolution -a <agent-id> --no-connection
copilot solution add-agent -s MySolution -a <agent-id> --no-required
```

| Option | Description |
|--------|-------------|
| `-s, --solution` | Solution's unique name (required) |
| `-a, --agent` | Agent's unique identifier (required) |
| `--no-connection` | Don't add bot's connection reference |
| `--no-required` | Don't add required dependent components |

### Remove Agent from Solution

```bash
copilot solution remove-agent --solution MySolution --agent <agent-id>
```

### Add/Remove Connection Reference

```bash
copilot solution add-connection --solution MySolution --connection <connection-ref-id>
copilot solution remove-connection --solution MySolution --connection <connection-ref-id>
```

## Publisher Commands

```bash
# List publishers
copilot solution publisher list
copilot solution publisher list

# Get publisher details
copilot solution publisher get <publisher-id>

# Create publisher
copilot solution publisher create \
    --name "My Publisher" \
    --unique-name MyPublisher \
    --prefix mypub \
    --option-prefix 10000
copilot solution publisher create -n "My Publisher" -u MyPublisher -x mypub -o 10000 -d "Description"

# Delete publisher
copilot solution publisher delete <publisher-id>
```

**Create Options:**
| Option | Description |
|--------|-------------|
| `-n, --name` | Display name (required) |
| `-u, --unique-name` | Unique name, no spaces (required) |
| `-x, --prefix` | Customization prefix, 2-8 lowercase letters (required) |
| `-o, --option-prefix` | Option value prefix, 10000-99999 (required) |
| `-d, --description` | Optional description |

## Connection Reference Listing

```bash
# List connection references in solutions
copilot solution connection list
copilot solution connection list
```

For full connection reference management, see [connections.md](connections.md).
