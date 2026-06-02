# Flows

The CLI manages two flow types:

- **Agent Flows** — Power Automate flows triggered by Copilot Studio agents (`copilot agent-flow`)
- **Power Automate Flows** — General cloud flows (automated, instant, business process) (`copilot powerautomate-flow`)

## Agent Flow Commands

Manage Copilot Studio agent flows - Power Automate flows with the "When an agent calls the flow" trigger.

### List Agent Flows

```bash
copilot agent-flow list                         # All agent flows (JSON)
copilot agent-flow list                 # Formatted table
```

### Get Agent Flow Details

```bash
copilot agent-flow get <flow-id>
```

### Create Agent Flow

Create a new Copilot Studio agent flow. The flow is created in Draft state with the "When an agent calls the flow" trigger.

```bash
# Create an empty agent flow
copilot agent-flow create --name "My Agent Flow"
copilot agent-flow create -n "My Flow" -d "Description here"

# Create from a flow definition file
copilot agent-flow create --name "My Flow" --file flow.yaml
copilot agent-flow create -n "My Flow" -f flow.yaml --include-connections
```

| Option | Description |
|--------|-------------|
| `-n, --name` | **(Required)** Display name for the agent flow |
| `-d, --description` | Description for the agent flow |
| `-f, --file` | YAML or JSON file containing flow definition to import |
| `-c, --include-connections` | Include connection references from the file (if using --file) |
| `--skip-validation` | Skip YAML validation (not recommended) |

**Supported Input Formats:**
1. **Full export format** (from `agent-flow export`): Contains name, workflowid, definition, and connectionReferences fields
2. **Definition-only format** (from `agent-flow export --definition-only`): Contains just the flow definition

### Remove Agent Flow

Delete an agent flow. For published flows, the flow is automatically deactivated before deletion.

```bash
copilot agent-flow remove <flow-id>             # Delete (with confirmation)
copilot agent-flow remove <flow-id> --force     # Delete without confirmation
```

| Option | Description |
|--------|-------------|
| `-f, --force` | Skip confirmation prompt and delete immediately |

**Warning:** This action is irreversible. The flow and all its run history will be permanently deleted.

**Note:** Some flows with null definitions cannot be deleted via the API. If you encounter an error about a null definition, delete the flow manually via Copilot Studio at https://copilotstudio.microsoft.com

### Update Agent Flow

```bash
copilot agent-flow update <flow-id> --name "New Name"
copilot agent-flow update <flow-id> --description "New description"
copilot agent-flow update <flow-id> -n "Name" -d "Description"
```

| Option | Description |
|--------|-------------|
| `-n, --name` | New name for the agent flow |
| `-d, --description` | New description for the agent flow |

### Export Agent Flow Definition

Export an agent flow's definition as YAML or JSON. The export includes the flow's triggers, actions, and connection references.

```bash
# Export as JSON (default)
copilot agent-flow export <flow-id>

# Export as YAML (human-readable)
copilot agent-flow export <flow-id> --yaml

# Save to file
copilot agent-flow export <flow-id> --yaml --output flow.yaml
copilot agent-flow export <flow-id> -y -o flow.yaml

# Export only the flow definition (no metadata)
copilot agent-flow export <flow-id> --definition-only --yaml

# Export raw clientdata (for debugging)
copilot agent-flow export <flow-id> --raw
```

| Option | Description |
|--------|-------------|
| `-y, --yaml` | Output as YAML instead of JSON |
| `-o, --output` | Write output to file instead of stdout |
| `-d, --definition-only` | Output only the flow definition (excludes metadata and connection references) |
| `-r, --raw` | Output the raw clientdata string without parsing |

**Output Structure:**
The export includes:
- `name` - Flow display name
- `workflowid` - Flow GUID
- `description` - Flow description
- `definition` - The flow definition containing triggers and actions
- `connectionReferences` - Connection references used by the flow

### Import Agent Flow Definition

Import/update an agent flow's definition from a YAML or JSON file. This is the reverse of the export command and allows you to modify a flow's definition programmatically.

```bash
# Import from YAML file
copilot agent-flow import <flow-id> --file flow.yaml

# Import from JSON file
copilot agent-flow import <flow-id> -f flow.json

# Also update connection references from the file
copilot agent-flow import <flow-id> -f flow.yaml --include-connections

# Dry run - validate without making changes
copilot agent-flow import <flow-id> -f flow.yaml --dry-run
```

| Option | Description |
|--------|-------------|
| `-f, --file` | **(Required)** Path to YAML or JSON file containing the flow definition |
| `-c, --include-connections` | Also update connection references from the file (default: preserve existing) |
| `--dry-run` | Parse and validate the file without updating the flow |

**Supported Input Formats:**

1. **Full export format** (from `agent-flow export`):
   ```yaml
   name: My Flow
   workflowid: 12345-...
   definition:
     $schema: https://schema.management.azure.com/...
     actions: ...
     triggers: ...
   connectionReferences:
     shared_connector: ...
   ```

2. **Definition-only format** (from `agent-flow export --definition-only`):
   ```yaml
   $schema: https://schema.management.azure.com/...
   actions:
     MyAction:
       type: OpenApiConnection
       ...
   triggers:
     manual:
       type: Request
       ...
   ```

**Workflow:**
```bash
# 1. Export existing flow
copilot agent-flow export <flow-id> --yaml --output flow.yaml

# 2. Edit the YAML file
# (modify actions, triggers, parameters, etc.)

# 3. Validate changes (dry run)
copilot agent-flow import <flow-id> -f flow.yaml --dry-run

# 4. Import the updated definition
copilot agent-flow import <flow-id> -f flow.yaml
```

### Validate Agent Flow Definition

Validate an agent flow YAML/JSON file without importing it. This checks for common errors before making changes.

```bash
# Validate a flow definition file
copilot agent-flow validate flow.yaml

# Treat warnings as errors (stricter validation)
copilot agent-flow validate flow.yaml --warnings-as-errors

# List all available validation rules
copilot agent-flow validate --list-rules
```

| Option | Description |
|--------|-------------|
| `-W, --warnings-as-errors` | Treat validation warnings as errors |
| `--list-rules` | List all available validation rules |

**Validation Checks:**
- Invalid parameters that don't exist in the API
- Connection reference format issues
- Missing required fields
- Expression syntax errors

**Exit Codes:**
- `0` - Validation passed (may include warnings)
- `1` - Validation failed with errors

### Test Agent Flow

Programmatically test an agent flow by resubmitting triggers or invoking manually. This mirrors the "Test" functionality in the Copilot Studio flow designer UI.

```bash
# Default: resubmit most recent trigger from history
copilot agent-flow test <flow-id>
copilot agent-flow test <flow-id> --wait

# Explicitly use run_history trigger type
copilot agent-flow test <flow-id> --trigger run_history --wait

# Resubmit a specific trigger history entry
copilot agent-flow test <flow-id> --trigger run_history --trigger-id <history-id> --wait

# Manual test with custom JSON body
copilot agent-flow test <flow-id> --trigger manual --body '{"text": "Hello"}'
copilot agent-flow test <flow-id> --trigger manual --body-file input.json --wait

# List trigger execution history
copilot agent-flow test <flow-id> --history

# Custom timeout (default: 300 seconds)
copilot agent-flow test <flow-id> --wait --timeout 60
```

**Trigger Types:**
| Type | Description |
|------|-------------|
| `run_history` | Resubmit from trigger history (default). Use `--trigger-id` to specify which entry. |
| `manual` | Invoke with custom JSON body. Requires `--body` or `--body-file`. |

| Option | Description |
|--------|-------------|
| `-h, --history` | List trigger execution history |
| `-T, --trigger` | Trigger type: `manual` or `run_history` (default: run_history) |
| `-i, --trigger-id` | For run_history: specific trigger history ID (omit for most recent) |
| `-b, --body` | For manual: JSON body |
| `--body-file` | For manual: file containing JSON body |
| `-w, --wait` | Wait for run completion and show results |
| `--timeout` | Timeout in seconds for --wait (default: 300) |

**Output with --wait:**

When using `--wait`, the command polls until the run completes and displays:
- Run summary (status, duration, start/end times)
- Error details (if failed)
- Action-by-action results with status icons (✓/✗/○)
- Failed action error messages and input/output links
- Full JSON run data

**Example Output:**
```
Fetching trigger history...
Using most recent trigger: 08584357666528512522017357289CU13
Resubmitting trigger 08584357666528512522017357289CU13...
✓ Trigger resubmitted
Waiting for run to appear...
Polling run 08584357657842167464441255419CU17...

Run completed with status: Succeeded

=== Run Summary ===
  id: 08584357657842167464441255419CU17
  status: Succeeded
  startTime: 2025-12-15T23:25:01.3909984Z
  endTime: 2025-12-15T23:25:02.3876409Z
  duration: 1.00s

=== Action Results ===
  ✓ Parse_trigger_input: Succeeded (0.02s)
  ✓ Run_a_prompt: Succeeded (0.85s)
  ✓ Respond_to_the_agent: Succeeded (0.01s)
```

**Workflow Example:**
```bash
# 1. Check trigger history to see what inputs are available
copilot agent-flow test <flow-id> --history

# 2. Resubmit a specific trigger and wait for results
copilot agent-flow test <flow-id> --trigger run_history --trigger-id <history-id> --wait

# 3. If a run fails, inspect the details
copilot agent-flow runs get <flow-id> <run-id>

# 4. Or test with custom input
copilot agent-flow test <flow-id> --trigger manual --body '{"text": "Test input"}' --wait
```

**Requirements:**
- Azure CLI authentication (`az login`)
- `DATAVERSE_ENVIRONMENT_ID` or `POWERPLATFORM_ENVIRONMENT_ID` environment variable set
- The flow must have at least one trigger history entry for run_history mode (use `--trigger manual` for flows without history)

### Agent Flow Runs

View flow run history and details.

#### List Runs

```bash
copilot agent-flow runs list <flow-id>
copilot agent-flow runs list <flow-id>
copilot agent-flow runs list <flow-id> -t -n 10
```

| Option | Description |
|--------|-------------|
| `-n, --top` | Maximum number of runs to return (default: 50) |

#### Get Run Details

```bash
copilot agent-flow runs get <flow-id> <run-id>
```

Shows detailed information about a specific run including action results, timing, and any errors.

#### Cancel a Run

```bash
copilot agent-flow runs cancel <flow-id> <run-id>
copilot agent-flow runs cancel <flow-id> <run-id> --yes
```

| Option | Description |
|--------|-------------|
| `-y, --yes` | Skip confirmation prompt (for non-interactive use) |

Sends a cancel request to the Power Automate Flow Management API for an in-progress run. A 4xx response from the API typically means the run already finished or does not exist (e.g. `WorkflowRunCanNotBeCancelled` when the run state is `Succeeded` or `Failed`).

## Power Automate Flow Commands

List and view Power Automate cloud flows (general flows, not agent-specific).

### List Flows

```bash
copilot powerautomate-flow list                 # All flows (JSON)
copilot powerautomate-flow list         # Formatted table
copilot powerautomate-flow list --category 5    # Instant flows only
copilot powerautomate-flow list --category 0    # Automated flows only
```

| Option | Description |
|--------|-------------|
| `-c, --category` | Filter by category: 0=Automated, 5=Instant, 6=Business Process |

**Flow Categories:**
- **0** - Automated (automated/scheduled flows)
- **5** - Instant (button/HTTP triggered flows)
- **6** - Business Process flows

### Get Flow Details

```bash
copilot powerautomate-flow get <flow-id>
```
