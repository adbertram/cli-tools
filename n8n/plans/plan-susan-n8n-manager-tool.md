# Quick Plan: Add n8n-manager Tool to Susan Workflow

## Summary
Add the n8n-manager node package as an AI tool to Susan's workflow (U7cK5XlQqmgG9CWlrB6wM). This enables Susan to manage n8n resources programmatically with full control over all 6 resources (workflows, nodes, credentials, data tables, executions, logs), restricted via tool description to only modify her own workflow ID.

## Steps

1. **Add n8n-manager node as AI tool**
   - **File:** Susan workflow U7cK5XlQqmgG9CWlrB6wM
   - **Command:** `n8n workflows node add U7cK5XlQqmgG9CWlrB6wM n8n-nodes-n8n-manager.N8NManager --name "Manage n8n" --credential "N8N API Key" --params '{"toolDescription": "Manage n8n workflows, nodes, credentials, data tables, executions, and logs. IMPORTANT: You can only modify your own workflow (ID: U7cK5XlQqmgG9CWlrB6wM). Use this to add nodes, connect nodes, change parameters, and modify your own workflow structure. Available resources: workflows, nodes, credentials, data-tables, executions, logs. For all operations on workflows or nodes, ALWAYS use your workflow ID: U7cK5XlQqmgG9CWlrB6wM."}'`
   - **Verify:** Run `n8n workflows get U7cK5XlQqmgG9CWlrB6wM` and confirm the new node appears with name "Manage n8n"

2. **Connect node to Susan AI Agent**
   - **File:** Susan workflow U7cK5XlQqmgG9CWlrB6wM
   - **Command:** `n8n workflows connections add U7cK5XlQqmgG9CWlrB6wM "Manage n8n" Susan --connection-type ai_tool`
   - **Verify:** Run `n8n workflows get U7cK5XlQqmgG9CWlrB6wM` and confirm ai_tool connection exists from "Manage n8n" to "Susan"

3. **Update Susan's system prompt**
   - **File:** Susan workflow U7cK5XlQqmgG9CWlrB6wM node "Susan" (id: 6e8ee7fe-bce9-4d86-9b25-09635328cc31)
   - **Action:** Add section to system prompt via CLI:
     ```bash
     n8n workflows node update U7cK5XlQqmgG9CWlrB6wM 6e8ee7fe-bce9-4d86-9b25-09635328cc31 --params '{"options": {"systemMessage": "<EXISTING_PROMPT_PLUS_NEW_SECTION>"}}'
     ```
     New section to append:
     ```

     ## n8n Self-Management
     You have access to the n8n API via the "Manage n8n" tool. This gives you full control over your own workflow structure.

     ### Your Workflow ID
     Your workflow ID is: **U7cK5XlQqmgG9CWlrB6wM**

     ### What You Can Do
     - Add new nodes to your workflow
     - Connect nodes together
     - Modify node parameters
     - View and manage your own executions
     - Read n8n logs for debugging
     - Manage data tables
     - Update credentials (view only, for reference)

     ### Important Rules
     - ONLY modify your own workflow (U7cK5XlQqmgG9CWlrB6wM)
     - Do NOT modify other workflows
     - When adding tools or capabilities to yourself, use the Manage n8n tool
     - Always use your workflow ID when performing workflow or node operations

     ### Examples
     - "Add a new tool to your capabilities" → Use Manage n8n to add a node with ai_tool connection
     - "Connect this node to that node" → Use Manage n8n workflows > nodes > update to add connections
     - "Check your recent executions" → Use Manage n8n executions > getAll
     ```
   - **Verify:** Get the updated workflow and confirm the system prompt includes the n8n management section

## Verify
Run `n8n workflows get U7cK5XlQqmgG9CWlrB6wM` and confirm:
- Node "Manage n8n" exists with type "n8n-nodes-n8n-manager.n8NManager"
- Node has credential "N8N API Key" attached
- Node has ai_tool connection to "Susan" node
- Susan node's system prompt includes n8n self-management instructions

## Implementation Corrections

### Correction 1 - 2026-02-17
**Step:** 1
**Issue:** Node type was incorrectly specified as `n8n-nodes-n8n-manager.N8NManager`
**Fix:** Correct node type is `n8n-nodes-n8n-manager.n8NManager` (lowercase 'n8n' prefix)
**Reason:** Server returns the actual installed node type name

### Correction 2 - 2026-02-17
**Step:** 2
**Issue:** Plan specified `n8n workflows connections add` command which doesn't exist
**Fix:** Used `n8n workflows node connect --type ai_tool` after adding `--type` option to the CLI
**Reason:** The CLI only had `node connect` command which previously only supported "main" connections. Added `--type/-t` parameter to support ai_tool, ai_languageModel, ai_memory connection types.

### Correction 3 - 2026-02-17
**Step:** 3
**Issue:** Plan specified `n8n workflows node update` command which doesn't exist
**Fix:** Used workflow export → jq modification → `n8n workflows update --file` to update the system prompt
**Reason:** The CLI has no direct node update command; required exporting workflow JSON, modifying with jq, and re-importing
