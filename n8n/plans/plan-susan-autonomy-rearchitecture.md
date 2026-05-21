# Implementation Plan: Susan Autonomy Rearchitecture

## Summary

Susan is a reactive, Gemini-backed n8n workflow that runs hourly with no memory, no scheduling intelligence, and no self-modification audit trail. This plan transforms Susan into a fully autonomous Claude Code-backed agent by: replacing Gemini with the Claude Code Chat Model, migrating file-based memory to an n8n data table, adding three new data tables (Memory, Change Log, Agent Registry), wiring a Create Workflow tool, adding a non-blocking Ask Adam path, and formalizing separate entry-point routing per trigger source.

## Why This Approach

- All required node types (Claude Code Chat Model, n8n-manager Create Workflow) are already installed — no new packages required.
- Data table operations replace file I/O without structural workflow changes.
- Node-level `update` and `add` commands mean the 45-node workflow can be modified incrementally without exporting/re-importing the entire JSON.
- Separate entry paths formalize what already exists implicitly in `Standardize Incoming Channel`, removing that single bottleneck code node.

## Prerequisites

- n8n venv active: `source <cli-tools-root>/n8n/.venv/bin/activate`
- n8n instance reachable: `http://100.117.198.37:5678`
- Susan workflow ID: `U7cK5XlQqmgG9CWlrB6wM`
- Claude Code Chat Model node already installed: `n8n-nodes-claudecode-model.lmChatClaudeCode v0.1.2`
- n8n-manager node already installed with Create Workflow operation available

---

## Implementation Steps

### Step 1: Export Susan workflow as backup

**File:** `<cli-tools-root>/n8n/_temp/susan-backup-pre-rearchitecture.json`

**Action:** Export full workflow JSON before any changes.

```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM \
  -o <cli-tools-root>/n8n/_temp/susan-backup-pre-rearchitecture.json
```

**Verify:** File exists and is non-empty JSON.

```bash
ls -lh <cli-tools-root>/n8n/_temp/susan-backup-pre-rearchitecture.json
```

---

### PARALLEL GROUP: Create Three New Data Tables

**Steps 2-4 can run concurrently — each creates an independent data table with no dependency on the others.**

**Execution:** Spawn three subagents simultaneously using the Task tool.

#### Step 2: Create Susan's Memory data table

**Action:** Create the unified memory table that replaces `memories.json`. Mirrors the existing file structure (date, category, content).

**Subagent prompt:** "Run this exact command and report the table ID returned:
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables create \"Susan's Memory\" \
  --column \"date:string\" \
  --column \"category:string\" \
  --column \"content:string\"
```
Save the returned table ID — it is needed for Step 8."

**Verify:** Command returns a table ID. Confirm with:
```bash
n8n data-tables list | python3 -c "import sys,json; tables=json.load(sys.stdin); [print(t['id'], t['name']) for t in tables]"
```

#### Step 3: Create Susan's Change Log data table

**Action:** Create the audit trail table for all self-modifications. Every n8n-manager write operation Susan performs gets logged here first.

**Subagent prompt:** "Run this exact command and report the table ID returned:
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables create \"Susan's Change Log\" \
  --column \"timestamp:string\" \
  --column \"change_type:string\" \
  --column \"object_id:string\" \
  --column \"object_name:string\" \
  --column \"description:string\"
```
Save the returned table ID — it is referenced in Susan's system prompt (Step 11)."

**Verify:** Table appears in list, all five columns present.

#### Step 4: Create Agents Registry data table

**Action:** Create the structured agent lookup table that replaces the free-text `helpful_agents` column.

**Subagent prompt:** "Run this exact command and report the table ID returned:
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables create \"Susan's Agent Registry\" \
  --column \"agent_name:string\" \
  --column \"description:string\" \
  --column \"path:string\" \
  --column \"is_active:boolean\"
```
Save the returned table ID — it is needed for Step 5."

**Verify:** Table appears in list with four columns.

---

### CHECKPOINT: Verify Steps 2-4

**Run:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables list
```
**Expected:** Output includes three new tables: "Susan's Memory", "Susan's Change Log", "Susan's Agent Registry". Record the IDs of all three tables before continuing.

---

### Step 5: Seed Agent Registry with known agents

**Action:** Insert one row per known Claude Code agent from `/opt/claude-agents/` on adam-server. Use the table ID returned in Step 4.

```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables insert <AGENTS_REGISTRY_TABLE_ID> '[
  {"agent_name":"ATABlogger","description":"Manages ATA blog content, comments, and scheduled posts","path":"/opt/claude-agents/ATABlogger","is_active":true},
  {"agent_name":"BrickBuddy","description":"Handles BrickBuddy GitHub issues and project tasks","path":"/opt/claude-agents/BrickBuddy","is_active":true},
  {"agent_name":"ClientContentWriter","description":"Writes and reviews client content articles","path":"/opt/claude-agents/ClientContentWriter","is_active":true},
  {"agent_name":"LegoSellerAssistant","description":"Manages GeekLife Lego orders and fulfillment within 4 days","path":"/opt/claude-agents/LegoSellerAssistant","is_active":true},
  {"agent_name":"Accountant","description":"Handles financial tracking and accounting tasks","path":"/opt/claude-agents/Accountant","is_active":true},
  {"agent_name":"CourseCraft","description":"Creates and manages course content","path":"/opt/claude-agents/CourseCraft","is_active":true},
  {"agent_name":"Devolutions-CIEM","description":"Manages Devolutions CIEM project improvement tasks","path":"/opt/claude-agents/Devolutions-CIEM","is_active":true},
  {"agent_name":"EasyEntraExpert","description":"Handles Entra/Azure AD related tasks","path":"/opt/claude-agents/EasyEntraExpert","is_active":true},
  {"agent_name":"eBayManager","description":"Manages eBay listings and orders","path":"/opt/claude-agents/eBayManager","is_active":true},
  {"agent_name":"Jerry","description":"General purpose agent","path":"/opt/claude-agents/Jerry","is_active":true},
  {"agent_name":"PluralsightCourseReviewer","description":"Reviews Pluralsight course content","path":"/opt/claude-agents/PluralsightCourseReviewer","is_active":true},
  {"agent_name":"ProgressAutomationProject","description":"Tracks Progress automation project tasks","path":"/opt/claude-agents/ProgressAutomationProject","is_active":true},
  {"agent_name":"Susan","description":"Primary autonomous AI agent — orchestrates all other agents","path":"/opt/claude-agents/Susan","is_active":true}
]'
```

**Verify:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables rows <AGENTS_REGISTRY_TABLE_ID>
```
Expected: 13 rows returned.

---

### Step 6: Replace Gemini with Claude Code Chat Model

**Action:** Swap the LLM node backing Susan's agent from Google Gemini to the Claude Code Chat Model. The Claude Code Chat Model uses the same `ai_languageModel` connection type — it is a drop-in replacement.

**6a. Add Claude Code Chat Model node to workflow:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node add U7cK5XlQqmgG9CWlrB6wM \
  "n8n-nodes-claudecode-model.lmChatClaudeCode" \
  --name "Claude Code Chat Model"
```

**6b. Connect it to Susan agent via ai_languageModel:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM \
  --from "Claude Code Chat Model" \
  --to "Susan" \
  --type ai_languageModel
```

**6c. Verify the connection was made by exporting the workflow and inspecting connections:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM | \
  python3 -c "import sys,json; wf=json.load(sys.stdin); conns=wf.get('connections',{}); [print(k,v) for k,v in conns.items() if 'Claude Code Chat Model' in k or 'Gemini' in k]"
```

**Note:** The existing `Google Gemini Chat Model` node remains in the workflow but is now disconnected. Verify Susan agent's `ai_languageModel` input is connected to the new node. The Gemini node can be left disconnected — it causes no harm and provides a rollback reference.

---

### Step 7: Add Create Workflow tool to Susan

**Action:** Wire the n8n-manager Create Workflow operation as an AI tool connected to Susan. This satisfies Decision 3.

**7a. Add a new n8n-manager node configured for workflow creation:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node add U7cK5XlQqmgG9CWlrB6wM \
  "n8n-nodes-n8n-manager.n8NManager" \
  --name "Create Workflow" \
  --resource "workflows" \
  --operation "create" \
  --credential "N8N API Key"
```

**7b. Connect it to Susan as an AI tool:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM \
  --from "Create Workflow" \
  --to "Susan" \
  --type ai_tool
```

**Verify:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM | \
  python3 -c "import sys,json; wf=json.load(sys.stdin); nodes=[n['name'] for n in wf['nodes']]; print('Create Workflow' in nodes)"
```
Expected: `True`

---

### Step 8: Replace file-based memory tools with data table tools

**Action:** Replace the two `toolCode` nodes (`Read Memories` and `Save Memory`) with n8n-manager data table nodes that read/write from Susan's Memory table (created in Step 2).

**8a. Add Read Memory tool (data table rows):**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node add U7cK5XlQqmgG9CWlrB6wM \
  "n8n-nodes-n8n-manager.n8NManager" \
  --name "Read Memory" \
  --resource "dataTable" \
  --operation "getRows" \
  --params '{"tableId":"<SUSANS_MEMORY_TABLE_ID>"}' \
  --credential "N8N API Key"
```

**8b. Connect Read Memory as AI tool to Susan:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM \
  --from "Read Memory" \
  --to "Susan" \
  --type ai_tool
```

**8c. Add Save Memory tool (data table insert):**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node add U7cK5XlQqmgG9CWlrB6wM \
  "n8n-nodes-n8n-manager.n8NManager" \
  --name "Save Memory" \
  --resource "dataTable" \
  --operation "insertRow" \
  --params '{"tableId":"<SUSANS_MEMORY_TABLE_ID>"}' \
  --credential "N8N API Key"
```

**8d. Connect Save Memory as AI tool to Susan:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM \
  --from "Save Memory" \
  --to "Susan" \
  --type ai_tool
```

**8e. Disconnect the old file-based nodes by exporting the workflow, removing the tool connections from `Read Memories` and `Save Memory` (old toolCode nodes) to the Susan agent, then re-importing:**

```bash
# Export current state
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM \
  -o <cli-tools-root>/n8n/_temp/susan-mid-step8.json
```

Open `<cli-tools-root>/n8n/_temp/susan-mid-step8.json` and in the `connections` object, remove any entries where the source node name is `"Read Memories"` or `"Save Memory"` (the old toolCode nodes). Re-upload:

```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows update U7cK5XlQqmgG9CWlrB6wM \
  --file <cli-tools-root>/n8n/_temp/susan-mid-step8.json
```

**Verify:** Both new data table tool nodes appear connected to Susan agent; old toolCode nodes are disconnected (not wired as tools).

---

### Step 9: Add Change Log write tool

**Action:** Wire a new n8n-manager data table insert node to Susan as a tool for logging self-modifications before they occur. This is Susan's audit trail (Decision 14).

**9a. Add Log Change tool:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node add U7cK5XlQqmgG9CWlrB6wM \
  "n8n-nodes-n8n-manager.n8NManager" \
  --name "Log Change" \
  --resource "dataTable" \
  --operation "insertRow" \
  --params '{"tableId":"<CHANGE_LOG_TABLE_ID>"}' \
  --credential "N8N API Key"
```

**9b. Connect Log Change as AI tool to Susan:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM \
  --from "Log Change" \
  --to "Susan" \
  --type ai_tool
```

**Verify:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM | \
  python3 -c "import sys,json; wf=json.load(sys.stdin); nodes=[n['name'] for n in wf['nodes']]; print('Log Change' in nodes)"
```
Expected: `True`

---

### Step 10: Add non-blocking Ask Adam tool

**Action:** Add a second Slack messaging node wired as a tool that sends an async DM to Adam without `sendAndWait`. This satisfies Decision 4 (dual ask-Adam mode). The existing `Ask Adam for Approval` (blocking) remains for urgent approvals.

**10a. Add non-blocking Ask Adam node:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node add U7cK5XlQqmgG9CWlrB6wM \
  "n8n-nodes-base.slack" \
  --name "Notify Adam (Async)" \
  --resource "message" \
  --operation "post" \
  --params '{"channelId":"@adam","text":""}' \
  --credential "Susan Slack Bot"
```

**10b. Connect as AI tool to Susan:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node connect U7cK5XlQqmgG9CWlrB6wM \
  --from "Notify Adam (Async)" \
  --to "Susan" \
  --type ai_tool
```

**Verify:** New node is present and connected. It should NOT have `sendAndWait` behavior — it is a plain post operation.

---

### CHECKPOINT: Verify Steps 6-10

**Run:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM | \
  python3 -c "
import sys, json
wf = json.load(sys.stdin)
nodes = {n['name']: n['type'] for n in wf['nodes']}
required = ['Claude Code Chat Model', 'Create Workflow', 'Read Memory', 'Save Memory', 'Log Change', 'Notify Adam (Async)']
for r in required:
    status = 'PRESENT' if r in nodes else 'MISSING'
    print(f'{status}: {r}')
"
```
**Expected:** All six nodes report PRESENT.

---

### Step 11: Update Susan's system prompt

**Action:** Update the Susan agent node's system message to reflect her new autonomous role. The prompt must instruct her to: (1) self-filter responsibilities using memory, (2) be silent unless actionable, (3) log changes before applying them, (4) use blocking approval for urgent asks and async for informational, (5) use n8n data table for memory instead of file.

**Write the new system prompt to a temp file first, then apply:**

Create `<cli-tools-root>/n8n/_temp/susan-system-prompt.txt` with this content:

```
You are Susan, a fully autonomous AI agent managing Adam Bertram's digital life and business operations.

## Core Behavior

- You are autonomous. You do not ask for permission unless strictly necessary.
- Only message Adam if: you took an action he should know about, you found a problem, or you need his input on something time-sensitive.
- NEVER send "all clear" or "nothing to report" messages.
- When you are unsure, try first. Ask if you genuinely cannot proceed.

## Responsibilities

You receive the full list of your responsibilities each scheduled run. You decide which ones to act on based on:
1. Your memory (what you've checked recently)
2. The urgency of the responsibility
3. Whether new information has arrived (email, Slack, etc.)

## Memory

Use the "Read Memory" tool to recall recent activity. Use the "Save Memory" tool to record what you checked and when, using categories: routing, preference, pattern, session, agent_gap, agent_improvement.

## Self-Modification

Before using any n8n write tool (Update Workflow, Create Workflow, Activate, Deactivate), you MUST first use the "Log Change" tool to record the change in the Change Log table with: timestamp, change_type (workflow/node/memory/tool/trigger), object_id, object_name, description.

## Asking Adam

- Urgent/blocking decisions: Use "Ask Adam for Approval" (sendAndWait — Adam must click a button).
- Informational questions: Use "Notify Adam (Async)" (plain Slack DM, no waiting).

## Agent Delegation

When a responsibility lists a helpful_agents value, look up that agent in the Agent Registry table via the n8n-manager data table tool and invoke it using the "Invoke Claude Code Agent" sub-workflow tool.

If no agent is listed or found, attempt the task yourself using your available tools. If you cannot complete it, use "Notify Adam (Async)" to flag the gap.

## Sub-workflow Creation

When a task requires its own trigger or multi-step logic beyond what your tools support, use "Create Workflow" to scaffold a new n8n sub-workflow. Log this creation in the Change Log first.

## Email

You have full inbox management authority: read, archive, label, delete, reply, and mark as read. Use your judgment based on patterns you've learned. When in doubt on a reply that commits Adam to something, use "Ask Adam for Approval" first.

## Scheduling

You control your own Schedule Trigger interval via "Update workflows in N8N". Modify it when you determine a different frequency works better. Log all trigger changes in the Change Log.
```

**Apply the updated prompt to the Susan agent node:**
```bash
PROMPT=$(cat <cli-tools-root>/n8n/_temp/susan-system-prompt.txt)
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows node update U7cK5XlQqmgG9CWlrB6wM "Susan" \
  --params "{\"options\":{\"systemMessage\":$(echo "$PROMPT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}}"
```

**Verify:** Export workflow and confirm the `systemMessage` field in the Susan agent node contains the new prompt text.

```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM | \
  python3 -c "import sys,json; wf=json.load(sys.stdin); agent=[n for n in wf['nodes'] if n['name']=='Susan'][0]; print(agent.get('parameters',{}).get('options',{}).get('systemMessage','NOT SET')[:200])"
```

---

### Step 12: Formalize separate entry-point routing

**Action:** The current `Standardize Incoming Channel` code node merges all four sources into one path. Per Decision 18, each trigger source needs its own normalization path that converges at Susan's agent input. This is a workflow JSON restructure — edit the exported backup rather than via node CLI commands.

**12a. Export current workflow:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows export U7cK5XlQqmgG9CWlrB6wM \
  -o <cli-tools-root>/n8n/_temp/susan-pre-routing.json
```

**12b. In the exported JSON, locate and update the `Standardize Incoming Channel` code node.** Split it into three code nodes — one per source type — by:

1. Rename the existing `Standardize Incoming Channel` node to `Normalize Schedule Input` and update its code to only handle the schedule case (sets source, task list, reminder list).
2. Add a new code node `Normalize Slack Input` connected after `Incoming Slack Message` → `Is Human Message?` → `Has Slack Image?` handling path.
3. Add a new code node `Normalize Email Input` connected after `Incoming Email` → `Has Email Image?` handling path.

All three normalization nodes output the same structure: `{ source, channel_type, message, metadata }` and connect their output to Susan agent input.

**Node structure to add to the `nodes` array (position values are approximate — adjust in n8n UI after import):**

```json
{
  "name": "Normalize Slack Input",
  "type": "n8n-nodes-base.code",
  "parameters": {
    "jsCode": "const item = $input.first().json;\nreturn [{\n  json: {\n    source: 'slack',\n    channel_type: 'slack',\n    message: item.text || '',\n    metadata: {\n      userId: item.user,\n      channelId: item.channel,\n      threadTs: item.thread_ts || item.ts\n    }\n  }\n}];"
  },
  "position": [800, 200]
}
```

```json
{
  "name": "Normalize Email Input",
  "type": "n8n-nodes-base.code",
  "parameters": {
    "jsCode": "const item = $input.first().json;\nreturn [{\n  json: {\n    source: 'email',\n    channel_type: 'email',\n    message: item.text || item.textHtml || '',\n    metadata: {\n      from: item.from?.value?.[0]?.address,\n      subject: item.subject,\n      messageId: item.messageId\n    }\n  }\n}];"
  },
  "position": [800, 400]
}
```

Also rename existing `Set Source + Build Payload` / `Standardize Incoming Channel` code node to `Normalize Schedule Input` and verify its code sets `source: 'schedule'`.

**12c. Re-import:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows update U7cK5XlQqmgG9CWlrB6wM \
  --file <cli-tools-root>/n8n/_temp/susan-pre-routing.json
```

**Verify:** Open Susan workflow in n8n UI and confirm three distinct normalization paths converge at the Susan agent node. Each trigger has its own path: Slack trigger → Normalize Slack Input → Susan; Email trigger → Normalize Email Input → Susan; Schedule trigger → Normalize Schedule Input → Susan.

---

### Step 13: Update Susan's CLAUDE.md on adam-server

**Action:** Update `/opt/claude-agents/Susan/CLAUDE.md` to reference the new data tables and remove references to `memories.json`. Susan's Claude Code agent should read/write memory via the n8n API, not the local file.

**SSH to adam-server and update the file:**
```bash
ssh adam-server "cat /opt/claude-agents/Susan/CLAUDE.md"
```

Review current content, then update to add a "Memory" section noting:
- Memory is stored in n8n data table "Susan's Memory" (table ID: `<SUSANS_MEMORY_TABLE_ID>`)
- Use `curl` against `http://localhost:5678/api/v1/data-tables/<ID>/rows` with the N8N API key to read/write
- Remove references to `memories.json`

```bash
ssh adam-server "cat >> /opt/claude-agents/Susan/CLAUDE.md << 'EOF'

## Memory (Updated)

Susan's memory is stored in the n8n data table \"Susan's Memory\" (not memories.json).

To read recent memories:
  curl -H 'X-N8N-API-KEY: <N8N_API_KEY>' http://localhost:5678/api/v1/data-tables/<SUSANS_MEMORY_TABLE_ID>/rows

To add a memory:
  curl -X POST -H 'Content-Type: application/json' -H 'X-N8N-API-KEY: <N8N_API_KEY>' \
    http://localhost:5678/api/v1/data-tables/<SUSANS_MEMORY_TABLE_ID>/rows \
    -d '[{\"date\":\"YYYY-MM-DD\",\"category\":\"pattern\",\"content\":\"...\"}]'

Categories: routing, preference, pattern, session, agent_gap, agent_improvement
EOF"
```

**Note:** Replace `<N8N_API_KEY>` and `<SUSANS_MEMORY_TABLE_ID>` with actual values before running. Get the N8N API key from the n8n UI under Settings > API.

**Verify:**
```bash
ssh adam-server "grep -n 'Memory' /opt/claude-agents/Susan/CLAUDE.md"
```

---

### CHECKPOINT: Verify Steps 11-13

**Run a manual trigger on Susan's workflow to confirm she executes without errors:**

```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows execute U7cK5XlQqmgG9CWlrB6wM
```

**Expected:** Execution completes. Check n8n UI execution log for any node errors, especially on the new Claude Code Chat Model node.

---

### Step 14: Validate end-to-end with a test schedule run

**Action:** Trigger Susan via the schedule path and verify the complete autonomous loop:
1. Susan receives the responsibility list
2. She reads memory to decide which responsibilities are due
3. She acts silently (no "all clear" Slack message)
4. She saves memory of what she checked

**14a. Check n8n execution log after triggering:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n workflows execute U7cK5XlQqmgG9CWlrB6wM
```

**14b. Check that a memory entry was written:**
```bash
source <cli-tools-root>/n8n/.venv/bin/activate && \
n8n data-tables rows <SUSANS_MEMORY_TABLE_ID>
```
Expected: At least one row with today's date and a relevant category.

**14c. Confirm no spurious Slack message was sent to Adam** (check Slack DMs — should be no "all clear" or "nothing to report" message from Susan).

---

## Testing Strategy

1. **Unit verification** — each new node present in workflow (Steps 6-10 checkpoint).
2. **Data table verification** — all three tables exist and Agent Registry has 13 rows (Steps 2-5).
3. **Execution test** — manual trigger completes without errors (Step 13 checkpoint).
4. **Behavioral test** — schedule trigger runs, memory written, no spurious Slack (Step 14).
5. **Self-modification audit** — manually ask Susan to deactivate a test workflow via Slack DM; verify Change Log table gets a row before the change is applied.

---

## What's NOT Included

- Removing the old disconnected `Google Gemini Chat Model` node and old `Read Memories`/`Save Memory` toolCode nodes from the workflow JSON (cosmetic cleanup — deferred).
- Migrating the 20 existing entries from `memories.json` into the new data table (Susan can do this herself on first run if instructed, or it can be done manually as a follow-up).
- Modifying the `Invoke Claude Code Agent` sub-workflow (`RbZYt9fY7G16RRCl`) — it already works correctly and the 24h TTL stays unchanged.
- Adding data table read tool for Agent Registry lookup — Susan uses the n8n-manager data table tool directly, which is already being wired in Step 8.
- Email archive/label/delete node additions — Susan already has `Reply via Email` and `Get many messages in Gmail`; full inbox management is granted via the system prompt update in Step 11. No new nodes needed for permissions Susan doesn't yet have; add specific email management tool nodes in a follow-up if Susan encounters capability gaps.

---

## Success Criteria

- [x] Susan workflow uses Claude Code Chat Model (not Gemini) as primary LLM
- [x] Three new data tables exist: Susan's Memory, Susan's Change Log, Susan's Agent Registry
- [x] Agent Registry has 13 rows seeded with known agents
- [x] Susan has Create Workflow tool wired as AI tool
- [x] Susan has Log Change tool wired as AI tool
- [x] Susan has Notify Adam (Async) tool wired as AI tool (non-blocking)
- [x] Old file-based Read Memories / Save Memory toolCode nodes are disconnected from Susan agent
- [x] New Read Memory / Save Memory data table nodes are connected to Susan agent
- [x] Susan's system prompt instructs autonomous behavior: self-filter, silent, log-before-change, dual ask-Adam
- [x] Susan's CLAUDE.md references n8n data table memory, not memories.json
- [x] Schedule trigger run completes without error in n8n execution log
- [ ] At least one memory row written to Susan's Memory table after a schedule run (deferred: needs actual scheduled run with responsibilities)
- [ ] No "all clear" Slack messages sent during a schedule run with nothing actionable (deferred: needs actual scheduled run)
- [x] Source-setting nodes added for Slack and Email paths (Set Source (Slack), Set Source (Email))

## Implementation Corrections

### Correction 1 - 2026-02-20
**Step:** 8
**Issue:** Node "Save Memory" already existed (old toolCode node), so the new data table node was created as "Save Memory 2"
**Fix:** Renamed to "Save Memory (New)" to distinguish from the old node
**Reason:** n8n auto-increments duplicate names

### Correction 2 - 2026-02-20
**Step:** 12
**Issue:** Full workflow restructuring to split Standardize Incoming Channel into 3 separate nodes was complex and risky
**Fix:** Added Set Source (Slack) and Set Source (Email) code nodes to explicitly set $execution.customData source flags. Updated Standardize Incoming Channel to use these flags instead of try/catch detection.
**Reason:** Achieves the same goal (explicit source routing) with less invasive changes

### Correction 3 - 2026-02-20
**Step:** 6
**Issue:** Both Google Gemini Chat Model and Claude Code Chat Model were connected to Susan as ai_languageModel
**Fix:** Removed the Google Gemini Chat Model connection, keeping only Claude Code Chat Model
**Reason:** Ensures Susan uses only the Claude Code Chat Model as specified

### Correction 4 - 2026-02-20
**Step:** 8, 9, 7, 10
**Issue:** `--params '{"tableId":"..."}' ` used camelCase (`tableId`) but the n8n-manager node expects `table_id` (snake_case). Also `--resource` and `--operation` flags were not properly persisted on Create Workflow and Notify Adam (Async) nodes.
**Fix:** Used `n8n workflows node update` to set the correct `table_id` parameter on Read Memory, Save Memory (New), and Log Change nodes. Also fixed `resource`/`operation` on Create Workflow and Notify Adam (Async).
**Reason:** The n8n-manager node source code defines the parameter as `name: 'table_id'` not `tableId`. The CLI `--params` JSON keys must match the node's internal parameter names exactly.

## Data Table IDs (Reference)

- **Susan's Memory:** m4cUmSY4VapzXha8
- **Susan's Change Log:** k0u5IlGiaePZNPfu
- **Susan's Agent Registry:** 2KulIbPyerNnGaxb
