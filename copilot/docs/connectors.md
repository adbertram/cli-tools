# Connectors

Power Platform uses three related concepts for integrations:

- **Connectors** - API wrappers/proxies defining available actions (e.g., Asana, SharePoint, Office 365)
- **Connections** - Authenticated credentials (OAuth tokens, API keys) — see [connections.md](connections.md)
- **Connection References** - Solution-aware pointers to connections — see [connections.md](connections.md)

This document covers managed (Microsoft) and custom connectors.

## Managed Connector Commands

List and inspect managed (Microsoft) connectors - built-in connectors published by Microsoft and third-party ISVs. These are read-only.

### List Managed Connectors

```bash
copilot managed-connector list                         # All managed connectors (JSON)
copilot managed-connector list                 # Formatted table
copilot managed-connector list --filter "sharepoint"   # Filter by name
copilot managed-connector list --filter "microsoft"    # Filter by publisher
```

| Option | Description |
|--------|-------------|
| `-f, --filter` | Filter by name or publisher |
| `-r, --raw` | Output raw JSON including all metadata |

### Get Managed Connector Details

```bash
copilot managed-connector get shared_office365              # Show operations as table
copilot managed-connector get shared_asana
copilot managed-connector get shared_asana --include-deprecated     # Include deprecated operations
copilot managed-connector get shared_asana --include-internal       # Include internal operations
copilot managed-connector get shared_asana --raw                    # Raw JSON output
copilot managed-connector get shared_asana --openapi                # Export OpenAPI definition
copilot managed-connector get shared_asana --openapi --output ./asana-spec.json
```

| Option | Description |
|--------|-------------|
| `-d, --include-deprecated` | Include deprecated operations (hidden by default) |
| `-i, --include-internal` | Include internal-visibility operations (cannot be used as agent tools) |
| `-r, --raw` | Output raw JSON connector definition |
| `--openapi, --swagger` | Output OpenAPI/Swagger definition |
| `-o, --output` | Write OpenAPI definition to file |

## Custom Connector Commands

Create, manage, and inspect custom connectors - user-created connectors that wrap custom APIs.

### List Custom Connectors

```bash
copilot custom-connector list                          # All custom connectors (JSON)
copilot custom-connector list                  # Formatted table
copilot custom-connector list --filter "myapi"         # Filter by name
```

| Option | Description |
|--------|-------------|
| `-f, --filter` | Filter by name |
| `-r, --raw` | Output raw JSON including all metadata |

### Get Custom Connector Details

```bash
copilot custom-connector get <connector-id>
copilot custom-connector get <connector-id> --raw
copilot custom-connector get <connector-id> --openapi
copilot custom-connector get <connector-id> --openapi --output ./api-spec.json
```

| Option | Description |
|--------|-------------|
| `-d, --include-deprecated` | Include deprecated operations |
| `-i, --include-internal` | Include internal-visibility operations |
| `-r, --raw` | Output raw JSON connector definition |
| `--openapi, --swagger` | Output OpenAPI/Swagger definition |
| `-o, --output` | Write OpenAPI definition to file |

### Create Custom Connector

Create a new custom connector from an OpenAPI 2.0 (Swagger) definition.

```bash
# Basic connector (non-OAuth)
copilot custom-connector create --name "My API" --swagger-file ./api.json

# With description and custom branding
copilot custom-connector create --name "My API" \
    --swagger-file ./api.json \
    --description "My custom API connector" \
    --icon-brand-color "#ff6600"

# OAuth connector with credentials
copilot custom-connector create --name "My API" \
    --swagger-file ./api.json \
    --oauth-client-id "client123" \
    --oauth-client-secret "secret456"

# With custom code script
copilot custom-connector create --name "My API" \
    --swagger-file ./api.json \
    --script ./code.csx \
    --oauth-client-id "client123" \
    --oauth-client-secret "secret456"

# Then create a connection
copilot connections create --connector-id <connector-id> --name "My Connection" --oauth
```

**Requirements:**
- OpenAPI definition must be in OpenAPI 2.0 (Swagger) format (not 3.0)
- File must be valid JSON or YAML
- Definition size must be less than 1 MB
- Must include: `swagger`, `info`, `host`, `basePath`, `schemes`

| Option | Description |
|--------|-------------|
| `-n, --name` | **(Required)** Display name for the connector |
| `-f, --swagger-file` | **(Required)** Path to OpenAPI 2.0 (Swagger) file |
| `-d, --description` | Connector description |
| `--icon-brand-color` | Icon brand color in hex format (default: #007ee5) |
| `--environment, --env` | Environment ID (uses config if not provided) |
| `--oauth-client-id` | OAuth 2.0 Client ID (required for OAuth connectors) |
| `--oauth-client-secret` | OAuth 2.0 Client Secret (required for OAuth connectors) |
| `--oauth-redirect-url` | Custom OAuth redirect URL |
| `-x, --script` | Path to C# script file (.csx) for custom code |
| `--script-operations` | Comma-separated operationIds that use the script |

**OAuth Redirect URLs:**

After creating an OAuth connector, register one of these redirect URLs in your OAuth app settings:
- **Specific**: `https://global.consent.azure-apim.net/redirect/<connector-id>`
- **Wildcard** (if supported): `https://global.consent.azure-apim.net/redirect/*`

### Update Custom Connector

```bash
# Update OpenAPI definition
copilot custom-connector update <connector-id> --swagger-file ./api-v2.json

# Add custom code script
copilot custom-connector update <connector-id> --script ./code.csx

# Update description
copilot custom-connector update <connector-id> --description "Updated description"
```

| Option | Description |
|--------|-------------|
| `-f, --swagger-file` | Path to OpenAPI 2.0 (Swagger) file |
| `-d, --description` | Connector description |
| `--icon-brand-color` | Icon brand color in hex format |
| `--oauth-client-id` | OAuth 2.0 Client ID |
| `--oauth-client-secret` | OAuth 2.0 Client Secret |
| `-x, --script` | Path to C# script file (.csx) |
| `--script-operations` | Comma-separated operationIds that use the script |

### Register Custom Connector in Dataverse

Register a custom connector created via Power Apps API in Dataverse for proper connection reference linking.

```bash
copilot custom-connector register <connector-id> --swagger-file ./api.json
copilot custom-connector register <connector-id> -f ./api.json --force
```

### Delete Custom Connector

```bash
# Delete with confirmation prompt
copilot custom-connector delete <connector-id>

# Delete without confirmation
copilot custom-connector delete <connector-id> --force

# Delete with cascade (removes connections, references, and agent tools)
copilot custom-connector delete <connector-id> --cascade --force
```

| Option | Description |
|--------|-------------|
| `--environment, --env` | Environment ID (uses config if not provided) |
| `--cascade` | Also delete connections, references, and agent tools |
| `-f, --force` | Skip confirmation prompt |

**Warning:** Deleting a connector will break any flows or agents that depend on it.
