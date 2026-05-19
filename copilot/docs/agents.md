# Agents

Manage Copilot Studio agents — create, update, publish, test, attach tools and knowledge sources, query telemetry, and view conversation transcripts.

Topic management for agents lives in [topics.md](topics.md).

## Agent Commands

### List Agents

```bash
copilot agent list                      # List all agents (JSON)
copilot agent list              # List as formatted table
copilot agent list -t                   # Short form
```

### Get Agent Details

```bash
copilot agent get <agent-id>              # Get agent details
copilot agent get <agent-id> --components # Include all components (topics, tools, knowledge)
```

### Create Agent

```bash
copilot agent create --name "My Agent"
copilot agent create --name "My Agent" --description "A helpful assistant"
copilot agent create --name "My Agent" --instructions "You are a helpful assistant"
copilot agent create --name "My Agent" --instructions-file ./prompt.txt
copilot agent create --name "My Agent" --no-orchestration
```

| Option | Description |
|--------|-------------|
| `-n, --name` | Display name for the agent (required) |
| `-d, --description` | Description for the agent |
| `-i, --instructions` | System instructions/prompt |
| `--instructions-file` | Path to file containing instructions |
| `--orchestration/--no-orchestration` | Enable/disable generative AI orchestration |

### Update Agent

```bash
copilot agent update <agent-id> --name "New Name"
copilot agent update <agent-id> --description "New description"
copilot agent update <agent-id> --instructions "New system prompt"
copilot agent update <agent-id> --instructions-file ./prompt.txt
copilot agent update <agent-id> --no-orchestration
```

| Option | Description |
|--------|-------------|
| `-n, --name` | New display name |
| `-d, --description` | New description |
| `-i, --instructions` | New system instructions |
| `--instructions-file` | Path to file containing new instructions |
| `--orchestration/--no-orchestration` | Enable/disable orchestration |

### Publish Agent

```bash
copilot agent publish <agent-id>          # Make latest changes live
```

**Note:** Changes to agents are not live until published.

### Delete Agent

```bash
copilot agent remove <agent-id>           # Delete (with confirmation)
copilot agent remove <agent-id> --force   # Delete without confirmation
```

### Test Agent (Send Prompt)

Send a message to an agent and get a response. Requires Direct Line secret or Entra ID authentication.

```bash
# Using Direct Line secret
copilot agent prompt <agent-id> --message "Hello" --secret "your-secret"

# Using environment variable
export DIRECTLINE_SECRET=your-secret
copilot agent prompt <agent-id> -m "Hello"

# Using Entra ID authentication
copilot agent prompt <agent-id> -m "Hello" --entra-id \
    --client-id <app-client-id> --tenant-id <tenant-id> \
    --token-endpoint "https://{ENV}.environment.api.powerplatform.com/..."

# With file attachment
copilot agent prompt <agent-id> -m "Review this document" --file ./draft.docx --secret "xxx"

# Verbose output with human-readable text
copilot agent prompt <agent-id> -m "Hello" -s "xxx" --verbose
```

| Option | Description |
|--------|-------------|
| `-m, --message` | The message/prompt to send (required) |
| `-s, --secret` | Direct Line secret |
| `--entra-id` | Use Entra ID authentication |
| `--client-id` | Entra ID application client ID |
| `--tenant-id` | Entra ID tenant ID |
| `--token-endpoint` | Bot token endpoint URL |
| `-f, --file` | Path to file attachment |
| `-v, --verbose` | Show detailed progress |
| `--timeout` | Total timeout in seconds (default: 120) |
| `--max-polls` | Maximum polling attempts (default: 30) |
| `--poll-interval` | Seconds between polls (default: 3) |

**Environment Variables:**
- `DIRECTLINE_SECRET` - Direct Line secret
- `ENTRA_CLIENT_ID` - Entra ID client ID
- `ENTRA_TENANT_ID` - Entra ID tenant ID
- `ENTRA_SCOPE` - OAuth scope (default: https://api.powerplatform.com/.default)
- `BOT_TOKEN_ENDPOINT` - Bot token endpoint

## Agent Tool Commands

Tools extend an agent's capabilities by allowing it to invoke external operations during orchestration. Supported tool types:
- **Connector** - Power Platform connector operations (e.g., SharePoint, Outlook, Dynamics)
- **Prompt** - AI Builder prompts for text generation and analysis
- **Flow** - Power Automate flows for complex automation
- **HTTP** - Direct HTTP requests to external APIs
- **Agent** - Other Copilot agents as sub-agents

### List Agent Tools

```bash
copilot agent tool list --agentId <agent-id>              # List all tools
copilot agent tool list --agentId <agent-id>      # Formatted table
copilot agent tool list --agentId <agent-id> --category agent  # Only connected agents
```

| Option | Description |
|--------|-------------|
| `-a, --agentId` | Agent's unique identifier (required) |
| `--category` | Filter by category (e.g., `agent`) |

### Add Tool

Add tools of any type to an agent using the unified interface:

```bash
copilot agent tool add --agentId <agent-id> --toolType <type> --id <tool-id> [options]
```

**Core Options:**
| Option | Description |
|--------|-------------|
| `-a, --agentId` | Agent's unique identifier (required) |
| `-T, --toolType` | Tool type: `connector`, `prompt`, `flow`, `http`, `agent` (required) |
| `--id` | Tool identifier - format depends on tool type (required) |
| `-n, --name` | Display name for the tool |
| `-d, --description` | Description for AI orchestration |
| `--inputs` | JSON string defining input parameters |
| `--outputs` | JSON string defining output parameters |

**Type-Specific Options:**
| Option | Applies To | Description |
|--------|------------|-------------|
| `--connection-ref` | connector, flow | Connection reference name |
| `--no-history` | agent | Don't pass conversation history |
| `--method` | http | HTTP method (GET, POST, etc.) |
| `--headers` | http | JSON string of HTTP headers |
| `--body` | http | HTTP request body template |

#### Tool Type: Connector

Invoke Power Platform connector operations:

```bash
# Basic connector tool
copilot agent tool add -a <agent-id> --toolType connector \
    --id "shared_asana:GetTask" --name "Get Asana Task"

# With input parameters
copilot agent tool add -a <agent-id> --toolType connector \
    --id "shared_office365:SendEmail" --name "Send Email" \
    --inputs '{"to": "string", "subject": "string", "body": "string"}'
```

**ID Format:** `connector_id:operation_id` (e.g., `shared_asana:GetTask`)

#### Tool Type: Prompt

Invoke AI Builder prompts:

```bash
copilot agent tool add -a <agent-id> --toolType prompt \
    --id <prompt-guid> --name "Summarize Text"

copilot agent tool add -a <agent-id> --toolType prompt \
    --id "12345678-1234-1234-1234-123456789abc" \
    --name "Analyze Sentiment" \
    --description "Analyzes the sentiment of customer feedback"
```

**ID Format:** Prompt GUID

#### Tool Type: Flow

Invoke Power Automate flows:

```bash
copilot agent tool add -a <agent-id> --toolType flow \
    --id <flow-guid> --name "Process Order"

copilot agent tool add -a <agent-id> --toolType flow \
    --id "12345678-1234-1234-1234-123456789abc" \
    --name "Create Support Ticket" \
    --inputs '{"title": "string", "priority": "string"}'
```

**ID Format:** Flow GUID (auto-prefixed with `/providers/Microsoft.Flow/flows/`)

#### Tool Type: HTTP

Make direct HTTP requests:

```bash
# GET request
copilot agent tool add -a <agent-id> --toolType http \
    --id "https://api.example.com/data" --name "Fetch Data"

# POST request with headers and body
copilot agent tool add -a <agent-id> --toolType http \
    --id "https://api.example.com/submit" \
    --name "Submit Data" \
    --method POST \
    --headers '{"Content-Type": "application/json"}' \
    --body '{"key": "value"}'
```

**ID Format:** Full URL

#### Tool Type: Agent (Connected Agent)

Connect another agent as a sub-agent:

```bash
copilot agent tool add -a <parent-id> --toolType agent \
    --id <target-agent-id> --name "Expert Reviewer"

# Without passing conversation history
copilot agent tool add -a <parent-id> --toolType agent \
    --id <target-agent-id> --name "Specialized Helper" --no-history
```

**ID Format:** Target agent GUID

**Requirements for connected agents:**
- Must be in the same environment
- Must be published
- Must have "Let other agents connect" enabled in settings

### Update Agent Tool

Update a tool's configuration including name, description, availability, and user confirmation settings.

```bash
# Update name and description
copilot agent tool update <component-id> --name "New Tool Name"
copilot agent tool update <component-id> --description "Use this tool when..."

# Configure availability (dynamic orchestration vs topic-only)
copilot agent tool update <component-id> --available        # Agent can use anytime
copilot agent tool update <component-id> --not-available    # Only from topics

# Configure user confirmation
copilot agent tool update <component-id> --confirm          # Ask user before running
copilot agent tool update <component-id> --no-confirm       # Run without asking
copilot agent tool update <component-id> --confirm --confirm-message "Proceed with action?"

# Combined update
copilot agent tool update <component-id> -n "Name" -d "Description" --available --confirm
```

| Option | Description |
|--------|-------------|
| `-n, --name` | New display name for the tool |
| `-d, --description` | New description for AI orchestration (max 1024 chars) |
| `--available/--not-available` | Control tool availability for dynamic orchestration |
| `--confirm/--no-confirm` | Enable/disable user confirmation before running |
| `-m, --confirm-message` | Custom confirmation prompt message |

### Remove Agent Tool

```bash
copilot agent tool remove <component-id>           # Remove (with confirmation)
copilot agent tool remove <component-id> --force   # Remove without confirmation
```

## Knowledge Commands

There are two command groups for managing knowledge sources:

- **`copilot knowledge`** - Upload and manage knowledge files (standalone or agent-associated)
- **`copilot agent knowledge`** - Associate/disassociate knowledge sources with agents

Knowledge sources can be created as **standalone** (not associated with any agent) or **associated** with a specific agent. Standalone sources can later be associated with one or more agents.

### Knowledge File Commands

The `copilot knowledge` command group handles file uploads to Dataverse. Files can be uploaded as standalone or directly associated with an agent.

#### Upload Knowledge File

```bash
# Upload standalone knowledge (no agent association)
copilot knowledge upload --file ./guide.docx --name "Style Guide"

# Upload and associate with agent in one step
copilot knowledge upload --file ./guide.docx --name "Style Guide" --agent <agent-id>

# With custom description
copilot knowledge upload -f ./manual.pdf -n "Product Manual" -d "Custom description"
```

| Option | Description |
|--------|-------------|
| `-f, --file` | Path to file to upload (required) |
| `-n, --name` | Display name for knowledge source (required) |
| `-a, --agent` | Agent's unique identifier (optional - associates with agent) |
| `-d, --description` | Description (auto-generated if not provided) |

**Supported Files:**
- Documents: .docx, .doc, .pdf, .txt, .md
- Spreadsheets: .xlsx, .xls, .csv
- Presentations: .pptx, .ppt
- Any binary file up to 512MB

#### List Knowledge Sources

```bash
# List all knowledge sources
copilot knowledge list
copilot knowledge list

# List knowledge for specific agent
copilot knowledge list --agent <agent-id>

# List only unassociated (standalone) knowledge
copilot knowledge list --unassociated

# Filter by type
copilot knowledge list --type file
```

| Option | Description |
|--------|-------------|
| `-a, --agent` | Filter by agent (optional) |
| `-u, --unassociated` | List only standalone knowledge sources |
| `-t, --type` | Filter by source type (file, connector) |

#### Get Knowledge Source Details

```bash
copilot knowledge get <component-id>
```

#### Download Knowledge File

```bash
copilot knowledge download <component-id>
copilot knowledge download <component-id> --output ./downloaded.docx
```

| Option | Description |
|--------|-------------|
| `-o, --output` | Output file path (defaults to original filename) |

#### Remove Knowledge Source

Permanently deletes the knowledge source from Dataverse.

```bash
copilot knowledge remove <component-id>
copilot knowledge remove <component-id> --force
```

| Option | Description |
|--------|-------------|
| `-f, --force` | Skip confirmation prompt |

### Agent Knowledge Commands

The `copilot agent knowledge` commands manage the association between knowledge sources and agents.

#### List Agent Knowledge Sources

```bash
copilot agent knowledge list --agent <agent-id>
copilot agent knowledge list --agent <agent-id>
```

#### Associate Knowledge with Agent

Associate an existing knowledge source with an agent:

```bash
copilot agent knowledge add --agent <agent-id> --component <component-id>
copilot agent knowledge add -a <agent-id> -c <component-id>
```

| Option | Description |
|--------|-------------|
| `-a, --agent` | Agent's unique identifier (required) |
| `-c, --component` | Knowledge source component ID to associate (required) |

**Workflow Example:**
```bash
# 1. Upload standalone knowledge
copilot knowledge upload --file ./guide.docx --name "Style Guide"
# Returns: componentId: abc123...

# 2. Associate with an agent
copilot agent knowledge add --agent <agent-id> --component abc123...

# 3. Associate same knowledge with another agent
copilot agent knowledge add --agent <other-agent-id> --component abc123...
```

#### Add Azure AI Search Knowledge (Experimental)

```bash
copilot agent knowledge azure-ai-search add --agent <agent-id> \
    --name "Product Docs" \
    --endpoint https://mysearch.search.windows.net \
    --index products-index \
    --api-key <api-key>
```

#### Remove/Disassociate Knowledge from Agent

```bash
# Disassociate from agent (keeps the knowledge source)
copilot agent knowledge remove <component-id> --disassociate
copilot agent knowledge remove <component-id> --disassociate --force

# Delete entirely (removes knowledge source permanently)
copilot agent knowledge remove <component-id>
copilot agent knowledge remove <component-id> --force
```

| Option | Description |
|--------|-------------|
| `-d, --disassociate` | Only remove association, keep knowledge source |
| `-f, --force` | Skip confirmation prompt |

## Analytics Commands (Application Insights)

Query Application Insights telemetry for troubleshooting agent behavior.

### Get Analytics Configuration

```bash
copilot agent analytics get <agent-id>
```

### Enable/Disable Analytics

```bash
copilot agent analytics enable <agent-id>
copilot agent analytics disable <agent-id>
```

### Update Logging Options

```bash
copilot agent analytics update <agent-id>
```

### Query Telemetry

```bash
copilot agent analytics query <agent-id>                    # Last 24 hours (JSON output)
copilot agent analytics query <agent-id> --timespan 7d      # Last 7 days
copilot agent analytics query <agent-id> -t 1h              # Last hour
copilot agent analytics query <agent-id> --events           # Custom events only (faster)
copilot agent analytics query <agent-id> -t 1h -l 50        # Limit to 50 rows
copilot agent analytics query <agent-id>            # Human-readable output
```

| Option | Description |
|--------|-------------|
| `-t, --timespan` | Time range (e.g., `1h`, `24h`, `7d`, `30d`) - default: `24h` |
| `-e, --events` | Query only customEvents table (faster) |
| `-l, --limit` | Maximum rows to display (default: 100) |

## Transcript Commands

View conversation transcripts for debugging and troubleshooting.

### List Transcripts

```bash
copilot agent transcript list                             # List recent transcripts
copilot agent transcript list                     # Formatted table
copilot agent transcript list --agent "Agent Name"          # Filter by agent name
copilot agent transcript list --agent <agent-id>              # Filter by bot ID
copilot agent transcript list --limit 10                  # Limit results
```

| Option | Description |
|--------|-------------|
| `-a, --agent` | Filter by agent name or ID |
| `-l, --limit` | Maximum transcripts to return (default: 20) |

### Get Transcript Content

```bash
copilot agent transcript get <transcript-id>
```
