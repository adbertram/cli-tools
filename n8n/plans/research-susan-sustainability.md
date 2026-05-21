# Technical Research: Susan Sustainability Fixes

## Files Analyzed

| File | Key Functions | Relevant Lines | Notes |
|------|---|---|---|
| `n8n_cli/commands/logs.py` | `logs_set_level()` - plist modification pattern | 299-372 | SSH + `sudo python3 -c` with plistlib for env var updates |
| `n8n_cli/commands/server.py` | `_restart_n8n()` - LaunchDaemon restart | 32-46 | unload/load via launchctl + `wait_for_ready()` polling (60s timeout) |
| `n8n_cli/n8n_api.py` | Data table CRUD operations | 436-516 | `list_data_table_rows(limit)`, `insert_data_table_rows(rows)`, `delete_data_table_rows(row_ids)` |
| `n8n_cli/n8n_api.py` | Workflow operations | 768-789 | `get_workflow()`, `update_workflow()`, `create_workflow()` |
| `n8n_cli/commands/data_tables.py` | CLI wrapper for data tables | 185-330 | `tables_rows`, `tables_insert`, `tables_delete_rows`, `tables_update_rows` |
| `n8n_cli/commands/workflows.py` | CLI wrapper for workflows | 19-340 | `workflows_create`, `workflows_update`, `workflows_export`, `workflows_activate/deactivate` |
| `n8n_cli/main.py` | CLI app structure | 1-62 | Typer app with command groups |

## APIs/Tools Verified

| Tool/API | Command/Method | Verified Signature | Notes |
|---|---|---|---|
| `list_data_table_rows()` | `api.list_data_table_rows(table_id, limit=100)` | Returns `List[Dict]` | Rows include `id`, `createdAt`, `updatedAt` auto-fields |
| `delete_data_table_rows()` | `api.delete_data_table_rows(table_id, row_ids)` | Accepts `List[str]` | Uses DELETE with `{"rowIds": row_ids}` |
| `insert_data_table_rows()` | `api.insert_data_table_rows(table_id, rows)` | Accepts `List[Dict]` | Payload: `{"returnType": "count", "data": rows}` |
| `update_data_table_rows()` | `api.update_data_table_rows(table_id, row_id, data)` | PATCH with filter | Filter by column eq row_id |
| `get_workflow()` | `api.get_workflow(workflow_id)` | Returns full workflow Dict | GET `/workflows/{id}` |
| `create_workflow()` | `api.create_workflow(name, nodes, connections, ...)` | Returns workflow Dict with `id` | Settings: saveManualExecutions=true |
| `update_workflow()` | `api.update_workflow(workflow_id, data)` | Uses `_writable_payload()` | PUT `/workflows/{id}` |
| `logs_set_level()` | SSH + plistlib pattern | logs.py:341-358 | Template for all plist modifications |
| `_restart_n8n()` | Unload → sleep(2) → Load → wait_for_ready() | server.py:32-46 | 60s timeout, 2s poll interval |

## Integration Map

```
[R1] Buffer Fix
├─ Target: Simple Memory node in Susan workflow (sessionKey parameter)
├─ Method: workflows node update OR direct workflow JSON patch
└─ Effect: Per-execution buffer isolation, memory table serves as 7-day activity source

[R2+R4] Memory Pruning + Dedup (n8n Sub-Workflow)
├─ Trigger: scheduleTrigger (nightly 2 AM)
├─ Read: n8n-manager data-tables rows list (table m4cUmSY4VapzXha8)
├─ Process: Code node with TTL logic + content-hash dedup
├─ Delete: n8n-manager data-tables rows delete (expired + duplicate IDs)
└─ Notify: Slack message to #susan-logs

[R3+R6] Plist Config (CLI + Server Restart)
├─ New: n8n_cli/commands/server_config.py
├─ Pattern: SSH + plistlib (from logs.py:341-358)
├─ Vars: EXECUTIONS_DATA_MAX_AGE, EXECUTIONS_DATA_PRUNE_MAX_COUNT, N8N_WORKFLOW_HISTORY_PRUNE_TIME
└─ Restart: _restart_n8n() from server.py

[R5] Read Memory Filtering
├─ Target: Read Memory tool node in Susan workflow
├─ Method: Update $fromAI() params and toolDescription
└─ Effect: Susan can request memories by category and recency

[R7] Weekly Summarization (n8n Sub-Workflow)
├─ Trigger: scheduleTrigger (weekly, Sundays 6 AM)
├─ Read: Query memory table for last 7 days
├─ Summarize: Call Gemini LLM with grouped memories
├─ Insert: New row with category "weekly_summary"
└─ Optional: DM summary to Adam via Slack
```

## Patterns to Follow

1. **Plist modification** (logs.py:341-358): SSH + `sudo python3 -c` with inline plistlib. Read → Update dict → Write → Restart.
2. **Data table row ops** (data_tables.py:185-330): List with limit/filter, delete by row ID list, insert with column dicts.
3. **Workflow creation** (workflows.py:107-232): `create_workflow(name, nodes, connections)`, activate separately.
4. **Server restart** (server.py:32-46): Unload → sleep(2) → Load → wait_for_ready(60s).
5. **Sub-workflow invocation** (Susan workflow): `executeWorkflow` node type already used 3 times in Susan.

## Susan Workflow Structure

- **41 nodes**, 4 entry points (Slack, Email, Schedule, Manual triggers)
- **Simple Memory**: sessionKey="susan-session" (static), contextWindowLength=10
- **LLM**: Google Gemini Chat Model (gemini-pro-latest)
- **15+ tools** connected to Susan agent
- **Sub-workflows**: CM Fetch, CM Process, Email Reply (via executeWorkflow nodes)

## Memory Table Schema

**Table ID:** `m4cUmSY4VapzXha8` ("Susan's Memory")

| Column | Type | Auto? | Notes |
|--------|------|-------|-------|
| timestamp | string | No | Mixed formats: YYYY-MM-DD and YYYY-MM-DDTHH:MM:SSZ |
| category | string | No | Values: session, agent_gap, routing, preference, pattern, test |
| content | string | No | Free-form text, 1-3 sentences |
| id | integer | Yes | Auto-generated, use for deletion |
| createdAt | string | Yes | ISO 8601 |
| updatedAt | string | Yes | ISO 8601 |

**Distribution (22 rows):** session(6), agent_gap(12), routing(1), preference(2), test(1)

## Files to Create/Modify

1. **NEW**: `n8n_cli/commands/server_config.py` — Server config command group
2. **MODIFY**: `n8n_cli/main.py` — Register server config commands
3. **CREATE via n8n API**: Memory Maintenance sub-workflow
4. **CREATE via n8n API**: Weekly Summary sub-workflow
5. **PATCH via CLI**: Susan workflow Simple Memory node (sessionKey)
6. **PATCH via CLI**: Susan workflow Read Memory node (toolDescription, $fromAI params)

## Key Constraints

- Row IDs from data table are integers but `delete_data_table_rows()` expects `List[str]` — cast at call site
- Timestamp column has inconsistent formats — use `createdAt` (auto, always ISO 8601) for TTL calculations instead
- n8n sub-workflows need to use HTTP Request or n8n-manager nodes to interact with data tables (not direct API)
- Gemini stays as the LLM — don't swap to Claude Code Model
