# Tools

Manage agent tools available in your environment: AI Builder prompts, REST APIs, MCP servers, and AI Builder models. Use these to build the catalog of capabilities that can later be attached to agents (see [agents.md](agents.md) for attaching tools to a specific agent).

For connectors, see [connectors.md](connectors.md).

## Tool Commands

The `copilot tool` command manages agent tools that can be added to Copilot Studio agents.

### List Tools

```bash
copilot tool list                              # List all tools (JSON)
copilot tool list                      # Formatted table
copilot tool list --installed          # Only installed tools
copilot tool list --type prompt        # AI Builder prompts only
copilot tool list --type mcp           # MCP servers only
copilot tool list --filter "excel"     # Search by name
```

| Option | Description |
|--------|-------------|
| `-T, --type` | Filter by type: `prompt`, `mcp` |
| `-i, --installed` | Show only tools installed in your environment |
| `-f, --filter` | Filter by name (case-insensitive) |

**Output Columns:**
- **Name** - Tool display name
- **Type** - Tool type (Prompt, MCP)
- **Publisher** - Tool publisher
- **Installed** - Whether the tool is installed in your environment
- **Deps** - Number of dependent components (for installed tools)
- **ID** - Unique identifier

### Remove Tool

Remove a custom tool (prompt or REST API) from the environment.

```bash
copilot tool remove <tool-id>                      # Auto-detect type
copilot tool remove <tool-id> --type prompt        # Specify type
copilot tool remove <tool-id> --type restapi       # Specify type
copilot tool remove <tool-id> --force              # Skip confirmation
```

| Option | Description |
|--------|-------------|
| `-T, --type` | Tool type: `prompt`, `restapi` (auto-detected if not specified) |
| `-f, --force` | Skip confirmation prompt |

**Note:** When removing REST APIs, associated AIPlugin wrappers are automatically deleted.

## Prompt Commands (AI Builder)

Manage AI Builder prompts that can be used as agent tools.

```bash
# List prompts
copilot tool prompt list                        # All prompts (JSON)
copilot tool prompt list                # Formatted table
copilot tool prompt list --custom       # Custom prompts only
copilot tool prompt list --system       # System prompts only
copilot tool prompt list --filter "classify"    # Filter by name

# Get prompt details
copilot tool prompt get <prompt-id>             # Metadata
copilot tool prompt get <prompt-id> --text      # Prompt text and configuration

# Update prompt
copilot tool prompt update <prompt-id> --text "New prompt text..."
copilot tool prompt update <prompt-id> --file prompt.txt
copilot tool prompt update <prompt-id> --model gpt-4o
copilot tool prompt update <prompt-id> --input-type content=text
copilot tool prompt update <prompt-id> -i content=text -i summary=document
copilot tool prompt update <prompt-id> --file prompt.txt --no-publish
```

**Update Options:**
| Option | Description |
|--------|-------------|
| `-t, --text` | New prompt text (inline) |
| `-f, --file` | Path to file containing new prompt text |
| `-m, --model` | Model type (e.g., gpt-41-mini, gpt-4o, gpt-4o-mini) |
| `-i, --input-type` | Change input type: INPUT_ID=TYPE (e.g., content=text). Valid types: text, document. Can be repeated. |
| `--no-publish` | Skip republishing (changes won't be live) |

### Prompt Permissions

Manage access permissions for AI Builder prompts. This is essential when prompts need to be accessed by service principals (e.g., for agent flows) or shared with other users.

```bash
# Grant read access to a prompt for a service principal
copilot tool prompt permissions grant <prompt-id> --principal <user-id> --level read

# Grant full access
copilot tool prompt permissions grant <prompt-id> -p <user-id> -l full

# List all principals with access to a prompt
copilot tool prompt permissions list <prompt-id>
copilot tool prompt permissions list <prompt-id>

# Revoke access from a principal
copilot tool prompt permissions revoke <prompt-id> --principal <user-id>
```

**Grant Options:**
| Option | Description |
|--------|-------------|
| `-p, --principal` | **(Required)** User or service principal ID (GUID) to grant access to |
| `-l, --level` | Access level: `read`, `write`, `delete`, `share`, `assign`, `full` (default: `read`) |

**Access Levels:**
| Level | AccessMask | Description |
|-------|------------|-------------|
| `read` | ReadAccess | Read-only access (sufficient for prompt execution) |
| `write` | WriteAccess | Edit access |
| `delete` | DeleteAccess | Delete access |
| `share` | ShareAccess | Re-share capability |
| `assign` | AssignAccess | Assign ownership |
| `full` | All of above | Full access |

**Revoke Options:**
| Option | Description |
|--------|-------------|
| `-p, --principal` | **(Required)** User or service principal ID (GUID) to revoke access from |

**Common Use Case - Agent Flow with AI Builder Prompt:**

When a Copilot Studio agent flow uses the "Run a prompt" action with service principal authentication, the service principal must have ReadAccess to the prompt:

```bash
# 1. Find your prompt ID
copilot tool prompt list

# 2. Find your service principal's application user ID
# (This is the systemuser ID in Dataverse, not the Entra app ID)

# 3. Grant read access
copilot tool prompt permissions grant <prompt-id> --principal <sp-user-id> --level read

# 4. Verify the permission was granted
copilot tool prompt permissions list <prompt-id>
```

## REST API Commands

List and view REST API tools (custom connectors defined with OpenAPI specs).

```bash
# List REST APIs
copilot tool restapi list                       # All REST APIs (JSON)
copilot tool restapi list               # Formatted table
copilot tool restapi list --filter "podio"

# Get REST API details
copilot tool restapi get <connector-id>
```

## MCP Server Commands

List, create, and manage Model Context Protocol servers.

```bash
# List MCP servers (catalog connectors)
copilot tool mcp list                           # All MCP servers (JSON)
copilot tool mcp list --table                   # Formatted table

# Get MCP server details (catalog connector)
copilot tool mcp get <server-id>

# Create a custom MCP server registration (Dataverse)
copilot tool mcp create -n "My MCP Server" -u "https://mcp.example.com/sse"
copilot tool mcp create -n "My Server" -u "https://example.com/mcp" -d "Description" --instructions "Usage notes"

# Remove a custom MCP server registration
copilot tool mcp remove <mcp-server-id>
copilot tool mcp remove <mcp-server-id> --force   # Skip confirmation
```

## Prompt Auth Commands

Create authentication credentials for running AI Builder prompts programmatically.

### Create Prompt Auth

```bash
# Create authentication for running prompts
copilot prompt auth create

# With custom name
copilot prompt auth create --name "My Prompt Runner"
```

This command creates all the resources needed to run prompts programmatically:
1. An App Registration in Microsoft Entra ID
2. A client secret for authentication
3. A Service Principal for the application
4. An Application User in Dataverse
5. The "Basic User" security role assignment

| Option | Description |
|--------|-------------|
| `-n, --name` | Display name (default: `Copilot-Prompt-Auth`) |

**Use Cases:**
- Running AI Builder prompts from Copilot Studio agent flows
- Executing prompts via Power Automate flows with service principal auth
- Automated prompt execution without interactive user login

**Important Requirements:**
1. Save the credentials securely - the client secret is shown only once
2. **Grant FULL access** to your prompt for the application user:
   ```bash
   copilot prompt permissions grant <prompt-id> --principal <application-user-id> --level full
   ```
   **Note:** Use the `applicationUserId` from the output (not the Azure client ID).

**Example Output:**
```json
{
  "name": "Copilot-Prompt-Auth",
  "tenantId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "clientId": "12345678-1234-1234-1234-123456789abc",
  "clientSecret": "abc123...xyz789",
  "applicationUserId": "87654321-4321-4321-4321-cba987654321"
}
```

After creation, grant prompt access:
```bash
copilot prompt permissions grant <prompt-id> \
  --principal 87654321-4321-4321-4321-cba987654321 \
  --level full
```

## Model Commands

Manage AI Builder models in the active environment.

### List Models

```bash
copilot model list
copilot model list --table
```

### Get Model

```bash
copilot model get <model-id>
copilot model get <model-id> --table
```

### Enable Model

Activate (publish) an AI Builder model so it can be invoked.

```bash
copilot model enable <model-id>
```

### Disable Model

Deactivate an AI Builder model.

```bash
copilot model disable <model-id>
```
