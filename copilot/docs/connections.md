# Connections & Connection References

Manage Power Platform connections (authenticated credentials) and connection references (solution-aware pointers to connections). For connector definitions, see [connectors.md](connectors.md).

- **Connections** — authenticated credentials (OAuth tokens, API keys) stored per-user
- **Connection References** — solution-aware pointers to connections, stored in Dataverse for portability across environments

## Connection Commands

### Get Connection

Get details for a specific connection by ID.

```bash
copilot connections get 12345678-1234-1234-1234-123456789abc
copilot connections get abc123 --env Default-xxx
```

Returns the connection's connector ID, display name, authentication status, and creation time.

### List Connections

```bash
# List all connections in the environment
copilot connections list

# Filter to a specific connector
copilot connections list --connector-id shared_office365
copilot connections list -c shared_asana
```

| Option | Description |
|--------|-------------|
| `-c, --connector-id` | Filter to a specific connector (e.g., shared_office365). If omitted, lists all connections. |

### Test Connection Authentication

```bash
copilot connections test --connector-id shared_office365
copilot connections test -c shared_commondataserviceforapps
copilot connections test -c shared_podio --connection-id abc123
```

| Option | Description |
|--------|-------------|
| `-c, --connector-id` | **(Required)** The connector ID |
| `--connection-id` | Test a specific connection ID (tests all if not provided) |

### Re-authenticate Connection (OAuth)

Re-authenticate an existing OAuth connection that has expired or is in an error state. Opens a browser window for the user to complete the OAuth consent flow.

```bash
# Re-authenticate a connection (auto-discovers connector from connection)
copilot connections auth 12345678-1234-1234-1234-123456789abc

# Re-authenticate with explicit connector ID
copilot connections auth 12345678-1234-1234-1234-123456789abc \
    -c shared_podio-20items-2c-20comments-20-26-20files-20api-acfe62f0142ebcd5

# Re-authenticate without waiting for completion (for automation)
copilot connections auth 12345678-1234-1234-1234-123456789abc --force
```

| Option | Description |
|--------|-------------|
| `<connection-id>` | **(Required)** The connection's unique identifier (GUID) |
| `-c, --connector-id` | Connector ID (auto-discovered from connection if not provided) |
| `--environment, --env` | Power Platform environment ID (uses DATAVERSE_ENVIRONMENT_ID if not specified) |
| `-f, --force` | Skip confirmation prompts and don't wait for OAuth authentication to complete |

**Behavior:**
1. Verifies the connection exists and retrieves its current status
2. Checks if the connector uses OAuth authentication (exits with warning if not)
3. Gets the OAuth consent link for the existing connection
4. Opens the consent page in your default browser
5. Polls for connection status until "Connected" (unless `--force` is used)

**For Non-OAuth Connectors:**

If the connection uses API key or other non-OAuth authentication, the command will show a warning and exit. To update credentials for non-OAuth connectors:
1. Delete the existing connection: `copilot connections delete <id> -c <connector>`
2. Create a new connection with updated credentials

**Missing OAuth Client ID:**

If the connector uses OAuth but has no client ID configured, the command will show an error with instructions:

```
Error: OAuth client ID is not configured for this connector.

To fix this, update the connector with OAuth credentials:

  copilot custom-connector update <connector-id> \
      --oauth-client-id YOUR_CLIENT_ID \
      --oauth-client-secret YOUR_CLIENT_SECRET

Then run this auth command again.
```

### Create Connection

Create a new connection for a connector. Different connectors require different authentication methods.

```bash
# OAuth connector (Asana, SharePoint, Dynamics 365, etc.)
# Creates connection and opens browser for OAuth flow
copilot connections create -c shared_asana -n "My Asana" --oauth

# OAuth connector for automation (skip prompts, don't wait for auth)
copilot connections create -c shared_asana -n "My Asana" --oauth --force

# Azure AI Search (API key authentication)
copilot connections create -c shared_azureaisearch -n "My Search" \
    --parameters '{"endpoint": "https://mysearch.search.windows.net", "api_key": "xxx"}'

# API key connector (SendGrid, etc.)
copilot connections create -c shared_sendgrid -n "SendGrid" \
    --parameters '{"api_key": "SG.xxx"}'

# Generic connector with parameters
copilot connections create -c shared_sql -n "SQL Server" \
    --parameters '{"server": "myserver.database.windows.net", "database": "mydb"}'
```

| Option | Description |
|--------|-------------|
| `-c, --connector-id` | **(Required)** The connector ID (e.g., shared_asana, shared_office365) |
| `-n, --name` | **(Required)** Display name for the connection |
| `-p, --parameters` | JSON string of connection parameters (connector-specific) |
| `--oauth` | Initiate OAuth flow - creates connection and opens browser |
| `-f, --force` | Skip confirmation prompts and don't wait for OAuth authentication to complete |
| `--environment, --env` | Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified. |

**Authentication Methods:**
- **OAuth** (`--oauth`): For connectors like Asana, SharePoint, Dynamics 365. Creates connection and opens browser for authentication.
- **API Key** (`--parameters`): For connectors with API key auth. Provide credentials in JSON format.
- **Azure AI Search**: Special handling for `{"endpoint": "...", "api_key": "..."}` parameters.

### Delete Connection

Delete a connection and optionally cascade delete dependent resources.

**Note:** `copilot connections remove` is an alias for `copilot connections delete`.

```bash
# Basic deletion
copilot connections delete <connection-id> -c shared_asana
copilot connections delete <connection-id> -c shared_office365 --force
copilot connections delete <connection-id> -c shared_azureaisearch --env Default-xxx

# Cascade deletion - also delete connection references
copilot connections delete <connection-id> -c shared_asana --include-connection-references
copilot connections delete <connection-id> -c shared_asana --include-refs  # Short form

# Cascade deletion - also delete agent tools using this connection
copilot connections delete <connection-id> -c shared_asana --include-agent-tools
copilot connections delete <connection-id> -c shared_asana --include-tools  # Short form

# Cascade delete everything (tools, connection refs, and connection)
copilot connections delete <connection-id> -c shared_asana --include-refs --include-tools
```

| Option | Description |
|--------|-------------|
| `-c, --connector-id` | **(Required)** The connector ID |
| `--environment, --env` | Power Platform environment ID |
| `--include-connection-references, --include-refs` | Also delete connection references pointing to this connection |
| `--include-agent-tools, --include-tools` | Also delete agent connector tools using this connection |
| `-f, --force` | Skip confirmation prompt |

**Cascade Deletion:**
- When using cascade options, the CLI will first identify all dependent resources
- Shows counts and names before deletion for confirmation
- Deletion order: agent tools → connection references → connection
- Each dependent resource is deleted individually with status feedback

**Connection Statuses:**
| Status | Description |
|--------|-------------|
| `Connected` | Connection is authenticated and ready to use |
| `Error` | Connection has an authentication or configuration issue |
| `Unauthenticated` | Connection needs to be authenticated (complete OAuth flow or check credentials) |

### Bind Connection to Agent

Bind a connection to a Copilot Studio agent, enabling the agent's connector tools to authenticate with external services. This is the same operation performed by clicking "Connect" in the Copilot Studio UI when a connector tool needs authentication.

```bash
# Bind an Asana connection to an agent
copilot connections bind <agent-id> \
    --connector-id shared_asana \
    --connection-id abcdef01-2345-6789-abcd-ef0123456789

# Bind a custom connector connection
copilot connections bind <agent-id> \
    -c shared_asana-20tasks-20api-5fd251d00e-f825669a42b5e533 \
    --connection-id abcdef01-2345-6789-abcd-ef0123456789

# With explicit environment
copilot connections bind <agent-id> -c shared_asana \
    --connection-id <conn-guid> --env Default-tenant-id
```

| Option | Description |
|--------|-------------|
| `<agent-id>` | **(Required)** The bot (agent) ID to bind the connection to (GUID) |
| `-c, --connector-id` | **(Required)** The connector's unique identifier (e.g., shared_asana) |
| `--connection-id` | **(Required)** The connection's unique identifier (GUID) |
| `--environment, --env` | Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified. |

**Requirements:**
- The bot must exist and have at least one connector tool configured
- The connection must exist and be in a "Connected" (authenticated) state
- The connector ID must match the connector used by the tool
- Appropriate Power Platform API permissions (see below)

**Important - API Permissions:**

This command uses the Power Platform user-connections API, which requires elevated permissions not available through standard Azure CLI authentication. If you receive a 403 "not authorized" error, you may need to:

1. **Use an Azure App Registration** with the "Power Platform API" permissions:
   - `CopilotStudio.Copilots.Invoke` (delegated permission)
   - Configure via: Azure Portal > App Registration > API Permissions > Add permission > APIs my organization uses > Power Platform API

2. **Alternatively**, bind connections through the Copilot Studio web interface:
   - Navigate to your agent > Settings > Connection Settings > Select connection > Manage

**Note:** After binding, remember to publish the agent to make changes live: `copilot agent publish <agent-id>`

## Connection Reference Commands

Manage connection references (solution-aware pointers to connections). Connection references allow flows and agents to reference a connection without being directly tied to it, making solutions portable across environments.

### Create Connection Reference

Create a new connection reference that points to an authenticated connection.

You must have an authenticated connection before creating a connection reference. Use `copilot connections list` to find available connections. The connector is automatically derived from the connection.

```bash
# First, find your connection ID
copilot connections list

# Create a connection reference linked to that connection
copilot connection-references create \
    --name "Asana Production" \
    --connection-id 12345678-1234-1234-1234-123456789abc

# With description
copilot connection-references create \
    --name "Asana Production" \
    --connection-id 12345678-1234-1234-1234-123456789abc \
    --description "Production Asana connection for content workflows"
```

| Option | Description |
|--------|-------------|
| `-n, --name` | (Required) Display name for the connection reference |
| `-c, --connection-id` | (Required) Connection ID to link to an authenticated connection |
| `-d, --description` | Description for the connection reference |

### List Connection References

```bash
copilot connection-references list              # All connection references (JSON)
copilot connection-references list      # Formatted table
```

### Get Connection Reference

```bash
copilot connection-references get <connection-ref-id>
```

### Update Connection Reference

Update which connection a reference points to, or change its display name.

```bash
# Update the connection it points to
copilot connection-references update <ref-id> --connection-id <new-conn-id>

# Update the display name
copilot connection-references update <ref-id> --name "Production Asana"

# Update both
copilot connection-references update <ref-id> -c <conn-id> -n "New Name"
```

| Option | Description |
|--------|-------------|
| `-c, --connection-id` | New connection ID to associate with this reference |
| `-n, --name` | New display name for the connection reference |

### Remove Connection Reference

Remove a connection reference from Dataverse. This does NOT delete the underlying connection.

```bash
copilot connection-references remove <connection-ref-id>
copilot connection-references remove <connection-ref-id> --force
```

| Option | Description |
|--------|-------------|
| `-f, --force` | Skip confirmation prompt |

**Note:** System-managed connection references (with 'msdyn_' prefix) cannot be removed.
