# Implementation Plan: Susan Long-Term Sustainability Fixes (R1-R8)

## Summary

Susan, the n8n AI agent running hourly 24/7, has no bounds on memory growth, buffer contamination between runs, execution history bloat, or data quality decay. This plan implements all 8 sustainability fixes (R1-R8) via: a two-line node patch to the Susan workflow, a new `server config` CLI group for plist env var management, two new n8n sub-workflows (nightly maintenance + weekly summary), and a node parameter patch for the Read Memory tool.

## Why This Approach

- R1 (buffer fix) and R5 (read memory filtering) are node parameter patches using the existing `n8n workflows node update` CLI — no new code.
- R2 (memory pruning) and R4 (deduplication) are combined into one "Susan Memory Maintenance" n8n sub-workflow — fewer moving parts than two separate workflows.
- R3 (execution pruning) and R6 (workflow history cap) use plist env vars via a new `server config` CLI group that follows the exact pattern from `logs.py`.
- R7 (weekly summarization) is a standalone n8n workflow on a Sunday schedule.
- R8 (DB monitoring) is explicitly skipped per user decision.
- Alternatives considered: Python-side pruning script (rejected — requires local scheduler and SSH complexity that n8n sub-workflows avoid), adding config commands directly to `server.py` (rejected — `server.py` already uses the sub-group pattern for `logs.py`, consistency requires a parallel `server_config.py`).

**Note on research file:** The research file (`research-susan-sustainability.md`) lists `n8n_cli/main.py` as the file to modify for registering server config commands. The plan is correct: registration belongs in `n8n_cli/commands/server.py` (following the same pattern used for `logs`), not `main.py`. The research file entry is a documentation artifact; the plan takes precedence.

## Prerequisites

- venv active: `source .venv/bin/activate`
- Susan workflow ID: `U7cK5XlQqmgG9CWlrB6wM`
- Memory table ID: `m4cUmSY4VapzXha8`
- n8n server accessible at `http://100.117.198.37:5678`
- Plist path on adam-server: `/Library/LaunchDaemons/com.n8n.server.plist`
- n8n Gemini credential name: already configured in Susan (no change)
- Adam's Slack user ID: `U0F2BD3QS` (confirmed from Susan's existing "Send Adam a Slack DM" node)

---

## Implementation Steps

### Step 1: Create `n8n_cli/commands/server_config.py`

**File:** `n8n_cli/commands/server_config.py`

**Action:** Create a new Typer sub-group following the exact pattern from `logs.py`. The file needs two commands: `show` (read plist EnvironmentVariables and display relevant pruning vars) and `set` (write one key=value to plist EnvironmentVariables and restart).

Key details:
- Import `_shell_quote` defined locally (copy the 4-line helper from `logs.py:51-54` — it is a private local function, not importable from `logs.py` without creating a circular dep).
- Import `run_on_server` from `..server`.
- Import `_restart_n8n` from `..commands.server` — wait, `_restart_n8n` is a private function in `server.py`. Instead, inline the same restart logic (unload → sleep(2) → load → `api.wait_for_ready(60)`) or import `_restart_n8n` directly since both files are in `n8n_cli/commands/`. Use a direct import: `from .server import _restart_n8n`.
- Plist default: `/Library/LaunchDaemons/com.n8n.server.plist`

Valid keys to support for `set`:
```
EXECUTIONS_DATA_PRUNE           true/false
EXECUTIONS_DATA_MAX_AGE         integer (hours)
EXECUTIONS_DATA_PRUNE_MAX_COUNT integer (count)
N8N_WORKFLOW_HISTORY_PRUNE_TIME integer (hours)
```

`show` command: Read plist via SSH, parse with plistlib, print a table of the 4 pruning variables (name, current value, default if unset, description).

`set` command signature:
```
n8n server config set KEY VALUE [--no-restart]
```
Validates KEY is in the allowed set, writes to plist via SSH + plistlib (same script pattern as `logs.py:341-358`), then calls `_restart_n8n()` unless `--no-restart`.

**File content outline:**
```python
"""Server config commands - manage n8n plist environment variables."""
import time
import typer
from typing import Optional

from ..n8n_api import get_n8n_api_client, N8nApiError
from ..output import print_json, print_error, print_info, print_success, print_table, handle_error
from ..server import run_on_server
from .server import _restart_n8n

app = typer.Typer(help="Manage n8n server configuration (plist env vars)", no_args_is_help=True)

N8N_PLIST = "/Library/LaunchDaemons/com.n8n.server.plist"

VALID_KEYS = {
    "EXECUTIONS_DATA_PRUNE": {"desc": "Enable execution pruning", "default": "true"},
    "EXECUTIONS_DATA_MAX_AGE": {"desc": "Max execution age in hours", "default": "336 (14 days)"},
    "EXECUTIONS_DATA_PRUNE_MAX_COUNT": {"desc": "Max execution count to keep", "default": "10000"},
    "N8N_WORKFLOW_HISTORY_PRUNE_TIME": {"desc": "Workflow history retention in hours", "default": "(not set — keeps all)"},
}

def _shell_quote(s: str) -> str:
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"

@app.command("show")
def config_show(plist_path: str = typer.Option(N8N_PLIST, "--plist")):
    """Show current n8n server pruning configuration."""
    ...

@app.command("set")
def config_set(
    key: str = typer.Argument(...),
    value: str = typer.Argument(...),
    restart: bool = typer.Option(True, "--restart/--no-restart"),
    plist_path: str = typer.Option(N8N_PLIST, "--plist"),
):
    """Set an n8n server configuration variable in the LaunchDaemon plist."""
    ...
```

**Verify:** `n8n server config --help` shows `show` and `set` subcommands.

---

### Step 2: Register `server_config` in `server.py`

**File:** `n8n_cli/commands/server.py`

**Action:** Add two lines after the existing `from . import logs` and `app.add_typer(logs.app, ...)`:
```python
from . import server_config
app.add_typer(server_config.app, name="config", help="Manage n8n server configuration")
```

**Verify:** `n8n server --help` shows `config` in the Commands list.

---

### CHECKPOINT: Verify Steps 1-2

**Run:** `source .venv/bin/activate && n8n server config --help`

**Expected:** Shows `show` and `set` subcommands with no import errors.

---

### Step 3: Apply Execution Pruning Config (R3)

**Action:** Use the new CLI to set execution pruning to 7-day/5000-count limits, then verify via `show`. Set all three values before restarting once at the end for efficiency:

```bash
source .venv/bin/activate
n8n server config set EXECUTIONS_DATA_PRUNE true --no-restart
n8n server config set EXECUTIONS_DATA_MAX_AGE 168 --no-restart
n8n server config set EXECUTIONS_DATA_PRUNE_MAX_COUNT 5000 --no-restart
n8n server restart
```

Rationale for values: 168h = 7 days (down from 14-day default), 5000 max count (down from 10k default). Hourly runs = ~168 executions/week; 5000 gives ~30 weeks buffer before count kicks in.

**Verify:** `n8n server config show` displays the 3 set values.

---

### Step 4: Apply Workflow History Cap (R6)

**Action:** Set workflow history retention to 720 hours (30 days):

```bash
source .venv/bin/activate
n8n server config set N8N_WORKFLOW_HISTORY_PRUNE_TIME 720 --no-restart
n8n server restart
```

Rationale: 30 days is enough to revert accidental changes; Susan currently has 40 history versions and no pruning.

**Verify:** `n8n server config show` displays `N8N_WORKFLOW_HISTORY_PRUNE_TIME = 720`.

---

### CHECKPOINT: Verify Steps 3-4

**Run:** `source .venv/bin/activate && n8n server config show`

**Expected:** All 4 vars show their set values. Server is up and responding.

---

### Step 5: Fix Buffer Isolation (R1)

**Action:** Patch the Simple Memory node in Susan's workflow to use per-execution session key.

Current node name in Susan: `"Simple Memory"` (verify with `n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.type | contains("memory")) | .name'` before executing).

Write the params to a temp file to avoid shell quoting issues:

```bash
source .venv/bin/activate
cat > /tmp/simple-memory-params.json << 'EOF'
{"sessionKey": "={{ $execution.id }}"}
EOF
n8n workflows node update U7cK5XlQqmgG9CWlrB6wM "Simple Memory" \
  --params "$(cat /tmp/simple-memory-params.json)"
```

This changes `sessionKey` from the static `"susan-session"` to a per-execution expression, so each hourly run gets a clean buffer with no cross-contamination from previous runs.

**Verify:**
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.name == "Simple Memory") | .parameters.sessionKey'
```
Expected output: `"={{ $execution.id }}"`

---

### Step 6: Update Read Memory Node (R5)

**Action:** Patch the Read Memory tool node in Susan's workflow to add category filtering and recency guidance. Write the params to a temp file to avoid shell quoting issues.

First confirm the node's exact name:
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.name | test("Read Memory|memory"; "i")) | .name'
```

Then write params to a temp file and apply (replace `"Read Memory"` with the confirmed node name if different):

```bash
source .venv/bin/activate
cat > /tmp/read-memory-params.json << 'EOF'
{
  "toolDescription": "Query Susan's long-term memory table. Use category filter to narrow results. Categories: session (recent activity), agent_gap (gaps between sessions), preference (user preferences), pattern (behavioral patterns), routing (channel routing rules), weekly_summary (weekly summaries). Use recency filter (e.g. last 7 days) for activity questions. Default limit 20.",
  "additionalFields": {
    "limit": "={{ $fromAI(\"limit\", \"Number of memory rows to fetch. Default 20, max 100.\", \"number\", 20) }}"
  }
}
EOF
n8n workflows node update U7cK5XlQqmgG9CWlrB6wM "Read Memory" \
  --params "$(cat /tmp/read-memory-params.json)"
```

Note: The `additionalFields.limit` param structure matches the confirmed schema from Susan's existing Read Memory node (which uses `additionalFields.limit` with `$fromAI()`). Inspect the current node params first to confirm:
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.name == "Read Memory") | .parameters'
```
Then apply only the parameters that the node accepts (at minimum: `toolDescription` and `additionalFields.limit` with `$fromAI()`).

**Verify:**
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.name == "Read Memory") | .parameters.toolDescription'
```
Expected: Updated description containing "category" and "weekly_summary".

---

### Step 6b: Update Susan's System Prompt to Read Memory at Startup (R5 / Discovery R1)

**Action:** Update Susan's AI agent node system prompt (system message) to include an explicit instruction to query memory for the last 7 days at the start of every scheduled run. This guarantees Susan has context about all activity up to a week old regardless of channel.

First confirm the agent node name:
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.type | test("agent|Agent"; "i")) | .name'
```

Then write the system message addition to a temp file. The patch appends to the existing `systemMessage` field — fetch the current value first, then append:

```bash
source .venv/bin/activate
# 1. Get the current system message
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq -r '.nodes[] | select(.type | test("agent"; "i")) | .parameters.systemMessage' > /tmp/susan-current-system-prompt.txt

# 2. Review the current prompt
cat /tmp/susan-current-system-prompt.txt

# 3. Write the patch — append the memory startup instruction
cat > /tmp/agent-params.json << 'EOF'
{
  "systemMessage": "<EXISTING_CONTENT_PLUS_THE_FOLLOWING_APPENDED>\n\n## Memory Startup Requirement\nAt the start of every scheduled run, you MUST query your memory table (using the Read Memory tool) for entries from the last 7 days before taking any other action. This establishes context about recent activity across all channels. Use limit 50 and review all returned entries to avoid duplicate work and maintain continuity."
}
EOF
```

**IMPORTANT:** Before applying, manually edit `/tmp/agent-params.json` to replace `<EXISTING_CONTENT_PLUS_THE_FOLLOWING_APPENDED>` with the actual current system prompt content (from step 1 above) plus the new appended section. Then apply:

```bash
n8n workflows node update U7cK5XlQqmgG9CWlrB6wM "Susan" \
  --params "$(cat /tmp/agent-params.json)"
```

Replace `"Susan"` with the confirmed agent node name from the first command.

**Verify:**
```bash
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq -r '.nodes[] | select(.type | test("agent"; "i")) | .parameters.systemMessage' | tail -20
```
Expected: Last lines include the memory startup requirement instruction.

---

### CHECKPOINT: Verify Steps 5-6b

**Run:** Review the updated Susan workflow in n8n UI (do not trigger Susan manually from CLI to avoid an unintended scheduled run firing).

Check nodes directly:

```bash
source .venv/bin/activate
# Simple Memory sessionKey
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.name == "Simple Memory") | .parameters.sessionKey'

# Read Memory toolDescription
n8n workflows get U7cK5XlQqmgG9CWlrB6wM | jq '.nodes[] | select(.name == "Read Memory") | .parameters.toolDescription'
```

**Note:** Avoid using `n8n workflows execute U7cK5XlQqmgG9CWlrB6wM` at this checkpoint — it would trigger Susan's full agent loop and could cause unintended side effects (emails, Slack messages, etc.). Verify via n8n UI executions tab after the next natural scheduled run instead.

---

### Step 7: Create "Susan Memory Maintenance" Workflow (R2 + R4)

**Action:** Build the workflow using CLI commands step by step. The workflow fetches memory rows using the `n8n-nodes-n8n-manager.n8NManagerTool` community node (already installed on the server and confirmed in Susan's workflow), applies TTL and deduplication logic in a Code node, conditionally deletes expired/duplicate rows only when there are IDs to delete (via an IF node), and posts a summary to `#susan-logs`.

**TTL rules:**
```
session:        7 days   (168 hours)
agent_gap:      30 days  (720 hours)
preference:     90 days  (2160 hours)
pattern:        90 days  (2160 hours)
routing:        14 days  (336 hours)
test:           0 days   (delete immediately — always expired)
weekly_summary: 365 days (8760 hours)
```

Deduplication: within each category, rows with identical `content` (case-insensitive trimmed) — keep the newest (highest `id`), delete the rest.

**Note on `timestamp` column:** The table schema requires `timestamp` to be included in every inserted row. It is a user-managed string column (not auto-generated) with mixed formats in existing data. Always include it when inserting rows.

#### Step 7a: Create the empty workflow

```bash
source .venv/bin/activate
cat > /tmp/susan-memory-maintenance-empty.json << 'EOF'
{"name": "Susan Memory Maintenance", "nodes": [], "connections": {}}
EOF
n8n workflows create /tmp/susan-memory-maintenance-empty.json \
  --name "Susan Memory Maintenance"
# Save the returned workflow ID as MAINT_WF_ID for subsequent steps
```

#### Step 7b: Add nodes

```bash
source .venv/bin/activate
# 1. Schedule trigger (nightly 2 AM)
n8n workflows node add $MAINT_WF_ID n8n-nodes-base.scheduleTrigger \
  --name "Schedule Trigger" \
  --params '{"rule":{"interval":[{"field":"cronExpression","expression":"0 2 * * *"}]}}'

# 2. Fetch memory rows using n8n-manager community node
n8n workflows node add $MAINT_WF_ID n8n-nodes-n8n-manager.n8NManager \
  --name "Fetch Memory Rows" \
  --resource data-tables \
  --operation rows \
  --params '{"table_id":"m4cUmSY4VapzXha8","additionalFields":{"limit":500}}' \
  --after "Schedule Trigger"

# 3. Code node: compute expiredIds and duplicateIds
cat > /tmp/maintenance-code-params.json << 'EOF'
{
  "jsCode": "const rows = $input.all()[0].json.rows || [];\nconst now = new Date();\n\nconst TTL_HOURS = {\n  session: 168,\n  agent_gap: 720,\n  preference: 2160,\n  pattern: 2160,\n  routing: 336,\n  test: 0,\n  weekly_summary: 8760,\n};\n\n// Expired IDs\nconst expiredIds = rows\n  .filter(r => {\n    const created = new Date(r.createdAt);\n    const ageHours = (now - created) / 3600000;\n    const ttl = TTL_HOURS[r.category] ?? 720;\n    return ageHours >= ttl;\n  })\n  .map(r => String(r.id));\n\n// Deduplicate: group by category+normalized_content, keep newest\nconst seen = {};\nconst duplicateIds = [];\nconst sorted = [...rows].sort((a, b) => b.id - a.id);\nfor (const row of sorted) {\n  const key = `${row.category}::${row.content.trim().toLowerCase()}`;\n  if (seen[key]) {\n    duplicateIds.push(String(row.id));\n  } else {\n    seen[key] = true;\n  }\n}\n\nconst deleteIds = [...new Set([...expiredIds, ...duplicateIds])];\nreturn [{ json: { deleteIds, expiredCount: expiredIds.length, dupCount: duplicateIds.length } }];"
}
EOF
n8n workflows node add $MAINT_WF_ID n8n-nodes-base.code \
  --name "Compute Delete IDs" \
  --params "$(cat /tmp/maintenance-code-params.json)" \
  --after "Fetch Memory Rows"

# 4. IF node: only proceed with delete if deleteIds is non-empty
cat > /tmp/maintenance-if-params.json << 'EOF'
{
  "conditions": {
    "options": {"caseSensitive": true},
    "conditions": [
      {
        "leftValue": "={{ $json.deleteIds.length }}",
        "rightValue": 0,
        "operator": {"type": "number", "operation": "gt"}
      }
    ]
  }
}
EOF
n8n workflows node add $MAINT_WF_ID n8n-nodes-base.if \
  --name "Has Rows to Delete" \
  --params "$(cat /tmp/maintenance-if-params.json)" \
  --after "Compute Delete IDs"

# 5. Delete rows node (n8n-manager) — connected on true branch
cat > /tmp/maintenance-delete-params.json << 'EOF'
{
  "table_id": "m4cUmSY4VapzXha8",
  "additionalFields": {
    "rowIds": "={{ $('Compute Delete IDs').first().json.deleteIds }}"
  }
}
EOF
n8n workflows node add $MAINT_WF_ID n8n-nodes-n8n-manager.n8NManager \
  --name "Delete Expired Rows" \
  --resource data-tables \
  --operation delete \
  --params "$(cat /tmp/maintenance-delete-params.json)"

# 6. Slack node: post summary to #susan-logs
cat > /tmp/maintenance-slack-params.json << 'EOF'
{
  "select": "channel",
  "channelId": {"__rl": true, "value": "susan-logs", "mode": "name"},
  "text": "={{ 'Susan Memory Maintenance complete. Deleted: ' + $('Compute Delete IDs').first().json.deleteIds.length + ' rows (' + $('Compute Delete IDs').first().json.expiredCount + ' expired, ' + $('Compute Delete IDs').first().json.dupCount + ' duplicates).' }}"
}
EOF
n8n workflows node add $MAINT_WF_ID n8n-nodes-base.slack \
  --name "Post Summary to Slack" \
  --params "$(cat /tmp/maintenance-slack-params.json)"
```

#### Step 7c: Connect nodes

```bash
source .venv/bin/activate
n8n workflows node connect $MAINT_WF_ID --from "Schedule Trigger" --to "Fetch Memory Rows"
n8n workflows node connect $MAINT_WF_ID --from "Fetch Memory Rows" --to "Compute Delete IDs"
n8n workflows node connect $MAINT_WF_ID --from "Compute Delete IDs" --to "Has Rows to Delete"
# True branch (output-index 0) → delete
n8n workflows node connect $MAINT_WF_ID --from "Has Rows to Delete" --to "Delete Expired Rows" --output-index 0
# Both true and false branches → Slack summary
n8n workflows node connect $MAINT_WF_ID --from "Delete Expired Rows" --to "Post Summary to Slack"
n8n workflows node connect $MAINT_WF_ID --from "Has Rows to Delete" --to "Post Summary to Slack" --output-index 1
```

#### Step 7d: Activate

```bash
source .venv/bin/activate
n8n workflows activate $MAINT_WF_ID
```

**Verify:**
```bash
n8n workflows list | jq '.[] | select(.name == "Susan Memory Maintenance") | {id, active}'
```
Expected: `active: true`

---

### Step 8: Create "Susan Weekly Summary" Workflow (R7)

**Action:** Build the weekly summary workflow step by step using CLI commands. This workflow runs on Sundays, fetches recent memory, summarizes with Gemini, inserts a `weekly_summary` row, and posts to `#susan-logs`.

#### Step 8a: Create the empty workflow

```bash
source .venv/bin/activate
cat > /tmp/susan-weekly-summary-empty.json << 'EOF'
{"name": "Susan Weekly Summary", "nodes": [], "connections": {}}
EOF
n8n workflows create /tmp/susan-weekly-summary-empty.json \
  --name "Susan Weekly Summary"
# Save the returned workflow ID as WEEKLY_WF_ID for subsequent steps
```

#### Step 8b: Add nodes

```bash
source .venv/bin/activate
# 1. Schedule trigger (Sundays 6 AM)
n8n workflows node add $WEEKLY_WF_ID n8n-nodes-base.scheduleTrigger \
  --name "Schedule Trigger" \
  --params '{"rule":{"interval":[{"field":"cronExpression","expression":"0 6 * * 0"}]}}'

# 2. Fetch memory rows using n8n-manager community node
n8n workflows node add $WEEKLY_WF_ID n8n-nodes-n8n-manager.n8NManager \
  --name "Fetch Memory Rows" \
  --resource data-tables \
  --operation rows \
  --params '{"table_id":"m4cUmSY4VapzXha8","additionalFields":{"limit":500}}' \
  --after "Schedule Trigger"

# 3. Code node: filter last 7 days and format for LLM
cat > /tmp/weekly-filter-params.json << 'EOF'
{
  "jsCode": "const rows = $input.all()[0].json.rows || [];\nconst now = new Date();\nconst sevenDaysAgo = new Date(now - 7 * 24 * 3600 * 1000);\n\nconst recent = rows.filter(r => new Date(r.createdAt) >= sevenDaysAgo);\n\nconst byCategory = {};\nfor (const row of recent) {\n  if (!byCategory[row.category]) byCategory[row.category] = [];\n  byCategory[row.category].push(`[${row.createdAt}] ${row.content}`);\n}\n\nconst formatted = Object.entries(byCategory)\n  .map(([cat, entries]) => `### ${cat}\\n${entries.join('\\n')}`)\n  .join('\\n\\n');\n\nreturn [{ json: { formatted, rowCount: recent.length, today: now.toISOString().split('T')[0] } }];"
}
EOF
n8n workflows node add $WEEKLY_WF_ID n8n-nodes-base.code \
  --name "Filter Last 7 Days" \
  --params "$(cat /tmp/weekly-filter-params.json)" \
  --after "Fetch Memory Rows"

# 4. Gemini LLM node: summarize grouped memories
cat > /tmp/weekly-gemini-params.json << 'EOF'
{
  "modelName": "models/gemini-pro",
  "messages": {
    "values": [
      {
        "role": "user",
        "content": "={{ 'You are summarizing Susan\\'s memory activity from the past week. Below are memory entries grouped by category. Write a concise summary (3-5 sentences per category that has entries) covering key patterns, preferences learned, and notable activity. Skip empty categories.\\n\\n' + $json.formatted }}"
      }
    ]
  }
}
EOF
n8n workflows node add $WEEKLY_WF_ID n8n-nodes-base.googleGemini \
  --name "Summarize with Gemini" \
  --params "$(cat /tmp/weekly-gemini-params.json)" \
  --after "Filter Last 7 Days"

# 5. Insert weekly_summary row using n8n-manager community node
# Note: timestamp column is required by the table schema
cat > /tmp/weekly-insert-params.json << 'EOF'
{
  "table_id": "m4cUmSY4VapzXha8",
  "additionalFields": {
    "data": "={{ JSON.stringify([{\"category\":\"weekly_summary\",\"content\":$json.text,\"timestamp\":$('Filter Last 7 Days').first().json.today}]) }}"
  }
}
EOF
n8n workflows node add $WEEKLY_WF_ID n8n-nodes-n8n-manager.n8NManager \
  --name "Insert Weekly Summary" \
  --resource data-tables \
  --operation insert \
  --params "$(cat /tmp/weekly-insert-params.json)" \
  --after "Summarize with Gemini"

# 6. Slack node: post to #susan-logs (not a DM — keeps an auditable log channel)
cat > /tmp/weekly-slack-params.json << 'EOF'
{
  "select": "channel",
  "channelId": {"__rl": true, "value": "susan-logs", "mode": "name"},
  "text": "={{ '*Susan Weekly Summary* (' + $('Filter Last 7 Days').first().json.today + '):\\n' + $('Summarize with Gemini').first().json.text }}"
}
EOF
n8n workflows node add $WEEKLY_WF_ID n8n-nodes-base.slack \
  --name "Post to susan-logs" \
  --params "$(cat /tmp/weekly-slack-params.json)" \
  --after "Insert Weekly Summary"
```

#### Step 8c: Connect nodes

```bash
source .venv/bin/activate
n8n workflows node connect $WEEKLY_WF_ID --from "Schedule Trigger" --to "Fetch Memory Rows"
n8n workflows node connect $WEEKLY_WF_ID --from "Fetch Memory Rows" --to "Filter Last 7 Days"
n8n workflows node connect $WEEKLY_WF_ID --from "Filter Last 7 Days" --to "Summarize with Gemini"
n8n workflows node connect $WEEKLY_WF_ID --from "Summarize with Gemini" --to "Insert Weekly Summary"
n8n workflows node connect $WEEKLY_WF_ID --from "Insert Weekly Summary" --to "Post to susan-logs"
```

#### Step 8d: Activate

```bash
source .venv/bin/activate
n8n workflows activate $WEEKLY_WF_ID
```

**Verify:**
```bash
n8n workflows list | jq '.[] | select(.name == "Susan Weekly Summary") | {id, active}'
```
Expected: `active: true`

---

### CHECKPOINT: Verify Steps 7-8

**Run:** Execute each maintenance workflow manually to confirm they don't error:

```bash
source .venv/bin/activate
# Get workflow IDs from the list
n8n workflows list | jq '.[] | select(.name | test("Susan Memory|Susan Weekly")) | {id, name}'

# Execute each (replace IDs with actual values from above)
n8n workflows execute <maintenance-workflow-id>
n8n workflows execute <weekly-summary-workflow-id>
```

**Expected:** Both executions complete with `status: success`. Check n8n UI executions tab for node-by-node result. Confirm a `weekly_summary` row appears in the memory table:
```bash
n8n data-tables rows m4cUmSY4VapzXha8 --filter "category:eq:weekly_summary"
```

---

## Testing Strategy

1. **R1 (Buffer)**: After patch, wait for the next scheduled Susan run. Confirm each execution has a distinct `sessionKey` in the Simple Memory node (visible in execution data via `n8n executions get <id> --include-data`).

2. **R3+R6 (Plist config)**: `n8n server config show` displays all 4 vars with set values. Wait 24h and check that `execution_data` table size is not growing unbounded.

3. **R5 (Read Memory)**: In a Susan chat, ask a question that would normally pull 100 memory rows. Confirm Susan uses `limit: 20` default and/or filters by category.

4. **R2+R4 (Memory Maintenance)**: Execute the maintenance workflow manually, check Slack `#susan-logs` for a pruning summary message with row counts.

5. **R7 (Weekly Summary)**: Execute the weekly summary workflow manually, confirm a new `weekly_summary` row appears in the memory table (`n8n data-tables rows m4cUmSY4VapzXha8 --filter "category:eq:weekly_summary"`).

---

## What's NOT Included

- R8 (DB monitoring): Explicitly skipped per user decision. Pruning controls growth; react if SQLite size becomes a problem.
- Gemini LLM swap: Stays on `gemini-pro-latest`.
- Memory table column schema changes: `createdAt` is used as-is for TTL; no migration needed.
- Old `test` category rows: The TTL=0 rule in the maintenance workflow will delete them on the first nightly run.

---

## Success Criteria

- [ ] `n8n server config show` displays `EXECUTIONS_DATA_MAX_AGE=168`, `EXECUTIONS_DATA_PRUNE_MAX_COUNT=5000`, `N8N_WORKFLOW_HISTORY_PRUNE_TIME=720`
- [ ] Susan Simple Memory node has `sessionKey: "={{ $execution.id }}"` (not static "susan-session")
- [ ] Read Memory node toolDescription mentions categories including "weekly_summary"
- [ ] Susan agent node system prompt includes the memory startup requirement instruction
- [ ] "Susan Memory Maintenance" workflow exists, is active, and runs without error when triggered manually
- [ ] "Susan Weekly Summary" workflow exists, is active, and inserts a `weekly_summary` row when triggered manually
- [ ] `n8n server config --help` shows `show` and `set` subcommands

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `n8n_cli/commands/server_config.py` | CREATE — new Typer sub-group with `show` and `set` commands |
| `n8n_cli/commands/server.py` | MODIFY — add 2 lines to register `server_config` as `config` sub-group |
| Susan workflow (via CLI) | PATCH — Simple Memory `sessionKey`, Read Memory `toolDescription` + params, agent system prompt |
| "Susan Memory Maintenance" workflow | CREATE via CLI node-by-node — nightly TTL pruning + dedup |
| "Susan Weekly Summary" workflow | CREATE via CLI node-by-node — weekly Gemini summary to `#susan-logs` |

---

## Implementation Corrections

### Correction 1 — Circular Import Fix (Step 2)
**Step:** 2 (Register server_config in server.py)
**Issue:** `server_config.py` imported `_restart_n8n` from `server.py` at module level, but `server.py` imports `server_config` — creating a circular import.
**Fix:** Changed `_restart_n8n` import to a lazy import inside the `config_set()` function body.

### Correction 2 — Internal REST API Auth Failure (Steps 7-8)
**Step:** 7b, 8b (Workflow HTTP Request nodes)
**Issue:** Plan used n8n-manager community node for fetching rows, but the actual implementation switched to HTTP Request nodes targeting the internal REST API (`/rest/projects/{pid}/data-tables/...`) which requires session cookie auth, not API key headers.
**Fix:** Switched all HTTP Request nodes to the public API (`/api/v1/data-tables/...`) which accepts `X-N8N-API-KEY` header authentication.

### Correction 3 — API Limit Exceeds Maximum (Steps 7-8)
**Step:** 7b, 8b (Fetch Memory Rows nodes)
**Issue:** Plan specified `limit: 500` but n8n public API maximum is 250.
**Fix:** Changed limit to 250 in both workflows.

### Correction 4 — DELETE Method Not Supported on Public API (Step 7)
**Step:** 7b (Delete Expired Rows node)
**Issue:** The public API (`/api/v1/data-tables/.../rows`) does not support the DELETE method for bulk row deletion. The internal REST API format also changed (now requires `filter` query param instead of `rowIds` body).
**Fix:** Used n8n-manager community node (`n8n-nodes-n8n-manager.n8NManager`) with operation `delete-rows` for the delete step. This shells out to the CLI which handles the API format internally. Rows are split via SplitInBatches and deleted one-per-item.

### Correction 5 — Slack Channel Does Not Exist (Steps 7-8)
**Step:** 7b, 8b (Slack notification nodes)
**Issue:** Plan referenced `#susan-logs` channel which does not exist in the Slack workspace.
**Fix:** Changed to DM Adam directly using Slack user ID `U0F2BD3QS` with `conversationType: "dm"`.

### Correction 6 — Insert Body Format Wrong (Step 8)
**Step:** 8b (Insert Weekly Summary node)
**Issue:** HTTP Request node sent a JSON array `[{...}]` but the n8n public API requires `{"data": [{...}]}` wrapper.
**Fix:** Wrapped the insert payload in `{data: [...]}` object.

### Correction 7 — System Prompt Location (Step 6b)
**Step:** 6b (Update Susan's system prompt)
**Issue:** Plan assumed `systemMessage` was at `parameters.systemMessage` but it's actually at `parameters.options.systemMessage` in the Susan agent node.
**Fix:** Read the correct path and used `options.systemMessage` for the node update.

### Correction 8 — Gemini Node Type (Step 8)
**Step:** 8b (Summarize with Gemini node)
**Issue:** Plan used `n8n-nodes-base.googleGemini` which doesn't exist. n8n uses LangChain-based LLM nodes.
**Fix:** Used `@n8n/n8n-nodes-langchain.chainLlm` (Basic LLM Chain) with a `@n8n/n8n-nodes-langchain.lmChatGoogleGemini` sub-node connected via `ai_languageModel` connection type. Credential: `googlePalmApi` id `Jl8ZtxGiW3UysVF4`.

### Known Bug Discovered — `data-tables delete-rows` CLI Command
**Impact:** The `n8n data-tables rows delete` CLI command is broken. The n8n server API format changed — now requires a `filter` query parameter instead of `rowIds` in the request body. The maintenance workflow works around this via the n8n-manager community node. This CLI bug needs a separate fix.
