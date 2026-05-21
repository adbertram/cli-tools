# Technical Research: Susan Autonomy Rearchitecture

## Files Analyzed

| File | Key Functions | Notes |
|------|---|---|
| Susan workflow (U7cK5XlQqmgG9CWlrB6wM) | 45 nodes, 4 triggers, LLM agent, 15+ tools | Full JSON exported and analyzed |
| Invoke Claude Code Agent (RbZYt9fY7G16RRCl) | 25 nodes for session management | Reusable pattern for agent dispatch |
| n8n_cli/n8n_api.py | REST API client methods (lines 150-516) | create/update/delete workflows, data tables, credentials |
| n8n_cli/commands/workflows.py | CLI commands | list, get, create, update, export, node operations |
| n8n_cli/commands/data_tables.py | CLI commands | create, list, get, rows, insert, update-rows, delete-rows |
| n8n-nodes/n8n-manager/README.md | Node operations (lines 1-91) | Workflows, Nodes, Credentials, Data Tables, Executions, Logs |
| references/nodes.md | Node development reference | Custom node patterns, credential types |
| references/api-reference.md | All 31 API endpoints | Request/response schemas |

## APIs/Tools Verified

| Tool/API | Command/Method | Verified | Notes |
|---|---|---|---|
| n8n workflows create | `n8n workflows create <file.json>` | Yes | POST /workflows, supports --name and --activate |
| n8n workflows update | `n8n workflows update WF_ID --file <file.json>` | Yes | PUT /workflows/{id} |
| n8n workflows export | `n8n workflows export WF_ID` | Yes | GET /workflows/{id} |
| n8n workflows node add | `n8n workflows node add WF_ID <node> -r <resource> -o <operation>` | Yes | Adds node with credentials/params |
| n8n workflows node connect | `n8n workflows node connect WF_ID --from <name> --to <name>` | Yes | Supports --output-index, --type ai_tool |
| n8n data-tables create | `n8n data-tables create "Name" --column "col:type"` | Yes | Types: string, number, date, boolean |
| n8n data-tables insert | `n8n data-tables insert TABLE_ID '[{"col":"val"}]'` | Yes | Returns count |
| n8n data-tables rows | `n8n data-tables rows TABLE_ID` | Yes | Supports --limit, --filter |
| n8n data-tables update-rows | `n8n data-tables update-rows TABLE_ID --row-id ID` | Yes | Deep merge of columns |
| n8n-manager Create Workflow | n8n-manager node operation | Yes | Available in n8n-manager v0.1.4 |
| n8n-manager Data Tables | n8n-manager node operation | Yes | Full CRUD on tables and rows |
| Claude Code CLI Node | n8n-nodes-claudecode.claudeCode v0.2.2 | Yes | new/resume sessions, 600s timeout |
| Claude Code Chat Model | n8n-nodes-claudecode-model.lmChatClaudeCode v0.1.2 | Yes | Full agentic LLM for agent chains |

## Integration Map

```
Susan Workflow (U7cK5XlQqmgG9CWlrB6wM)
├── Triggers (4 entry points)
│   ├── Incoming Slack Message (slackTrigger)
│   ├── Incoming Email (emailReadImap)
│   ├── Schedule Trigger (hourly)
│   └── Manual Trigger (testing)
│
├── Processing Nodes
│   ├── Channel Detection (Standardize Incoming Channel → code node)
│   ├── Image Handling (Has Slack/Email Image? → Download/Analyze)
│   └── Reminders (Get Slack Reminders → slackCustom tool)
│
├── Core Agent: Susan (@n8n/n8n-nodes-langchain.agent)
│   ├── LLM: Google Gemini Chat Model (TO BE REPLACED with Claude Code Chat Model)
│   ├── Memory: Simple Memory (contextWindowLength: 10)
│   └── Tools:
│       ├── List Available Agents (claudeCodeTool)
│       ├── Read Memories (toolCode - file-based memories.json)
│       ├── Save Memory (toolCode - same file)
│       ├── Send a message in Slack (slackTool)
│       ├── Ask Adam for Approval (slackTool with sendAndWait)
│       ├── Get My n8n Workflow (n8n-manager tool)
│       ├── Update workflows in N8N (n8n-manager tool)
│       ├── Activate Workflow (n8n-manager tool)
│       ├── Deactivate Workflow (n8n-manager tool)
│       ├── Execute Workflow (n8n-manager tool)
│       ├── Get many messages in Gmail (gmailTool)
│       ├── Invoke Claude Code Agent (toolWorkflow → RbZYt9fY7G16RRCl)
│       └── Reply via Email (toolWorkflow → Mnd60jujVIHSFXTM)
│
├── Sub-workflows
│   ├── ATA Blog Comment Processing (ZjGzXMq9NGSrqMT1)
│   ├── Invoke Claude Code Agent (RbZYt9fY7G16RRCl)
│   ├── Email Reply (Mnd60jujVIHSFXTM)
│   └── Blog Scheduled Posts Check (WordPress tool)
│
└── Data Tables
    ├── Susan's Responsibilities (j1I3Rcvck8hQVNhS) - 2 columns, 8 rows
    └── Susan's Delegated Agent Sessions (ASkF5cZWE7SZNibd) - 5 columns, 0 rows
```

## Current Workflow Node Inventory (45 nodes)

| # | Node Name | Type | Purpose | Credentials |
|---|---|---|---|---|
| 1 | Incoming Slack Message | slackTrigger | Slack message trigger | Susan Slack Bot |
| 2 | Is Human Message? | if | Filters bot messages | - |
| 3 | Has Slack Image? | if | Image detection | - |
| 4 | Download Slack File | httpRequest | Fetch Slack image | - |
| 5 | Prepare Slack Image | code | Format image | - |
| 6 | Analyze Image (Slack) | executeWorkflow | Image analysis | - |
| 7 | Incoming Email | emailReadImap | Email trigger | Susan IMAP |
| 8 | Format Email for Slack | code | Convert email format | - |
| 9 | Has Email Image? | if | Email image detection | - |
| 10 | Prepare Email Image | code | Extract attachment | - |
| 11 | Analyze Image (Email) | executeWorkflow | Image analysis | - |
| 12 | Schedule Trigger | scheduleTrigger | Hourly trigger | - |
| 13 | Set Source + Build Payload | code | Sets source='schedule' | - |
| 14 | Get Susan's Tasks | dataTable | Read responsibilities | - |
| 15 | Get Slack Reminders | slackCustom | Fetch reminders | Susan Slack Bot |
| 16 | Standardize Incoming Channel | code | Normalize all sources | - |
| 17 | Get scheduled ATA blog posts | wordpressTool | WordPress check | - |
| 18 | Simple Memory | memoryBufferWindow | Context (10 messages) | - |
| 19 | Google Gemini Chat Model | lmChatGoogleGemini | LLM | Google Gemini API |
| 20 | List Available Agents | claudeCodeTool | List agents | Claude Code CLI |
| 21 | Read Memories | toolCode | Read memories.json | - |
| 22 | Save Memory | toolCode | Write memories.json | - |
| 23 | Send a message in Slack | slackTool | Slack messaging | Susan Slack Bot |
| 24 | Ask Adam for Approval | slackTool | Blocking approval | Susan Slack Bot |
| 25 | Susan (Agent) | agent | Main LLM agent | - |
| 26 | Reply via Email | toolWorkflow | Email reply | - |
| 27 | Invoke Claude Code Agent | toolWorkflow | Agent sessions | - |
| 28 | Manual Trigger | manualTrigger | Test trigger | - |
| 29 | Get My n8n Workflow | n8n-manager | Get own workflow | N8N API Key |
| 30 | Update workflows in N8N | n8n-manager | Update workflow | N8N API Key |
| 31 | Activate Workflow | n8n-manager | Activate | N8N API Key |
| 32 | Deactivate Workflow | n8n-manager | Deactivate | N8N API Key |
| 33 | Execute Workflow | n8n-manager | Execute | N8N API Key |
| 34 | Call CM Fetch | executeWorkflow | Comment fetch | - |
| 35 | Has Actionable Comments? | if | Comment check | - |
| 36 | Format for AI Agent | code | Comment prompt | - |
| 37 | Is Comment Review? | if | Source check | - |
| 38 | Extract Decisions | code | Parse decisions JSON | - |
| 39 | Call CM Process | executeWorkflow | Comment processing | - |
| 40 | DM Confirmation | slack | Confirm to Adam | Slack |
| 41 | Standardize Outgoing Channel | code | Route reply | - |
| 42 | Route Reply | switch | Branch by type | - |
| 43 | Reply in Slack | slack | Slack reply | Susan Slack Bot |
| 44 | Reply via Email (Outgoing) | executeWorkflow | Email reply | - |
| 45 | Get WordPress posts | wordpressTool | Scheduled posts | - |

## Data Table Schemas

### Susan's Responsibilities (j1I3Rcvck8hQVNhS) - KEEP AS-IS
```
Columns: description (string), helpful_agents (string, nullable)
8 rows:
  1. All ATA blog comments ...              | "ATABlogger"
  2. Five ATA blog posts scheduled ...       | "ATABlogger"
  3. All Slack reminders ...                 | null
  4. Email inbox always processed ...        | null
  5. Client Content articles ...             | "ClientContentWriter"
  6. All BrickBuddy GitHub issues ...        | "BrickBuddy"
  7. Devolutions CIEM project improving ...  | null
  8. All GeekLife orders within 4 days ...   | "LegoSellerAssistant"
```

### Susan's Delegated Agent Sessions (ASkF5cZWE7SZNibd) - KEEP AS-IS
```
Columns: claude_code_agent_name, claude_code_agent_session_id,
         claude_code_agent_session_description, session_start_time, last_activity_time
0 rows (empty, ready for use)
```

### NEW: Susan's Memory (replaces memories.json)
```
Columns: date (string), category (string), content (string)
Categories: routing, preference, pattern, session, agent_gap, agent_improvement
Mirrors current memories.json structure
```

### NEW: Susan's Change Log (audit trail)
```
Columns: timestamp (date), change_type (string), object_id (string),
         object_name (string), description (string)
change_type values: workflow, node, memory, tool, trigger
```

### NEW: Agents Registry (structured agent lookup)
```
Columns: agent_name (string), description (string), path (string), is_active (boolean)
Seed from 14 agents in /opt/claude-agents/:
  ATABlogger, BrickBuddy, ClientContentWriter, LegoSellerAssistant,
  Accountant, CourseCraft, Devolutions-CIEM, EasyEntraExpert,
  eBayManager, Jerry, PluralsightCourseReviewer, ProgressAutomationProject, Susan
```

## n8n-manager Capabilities (Susan's Self-Modification Tools)

### Currently Wired to Susan
- Get My n8n Workflow (workflows > get)
- Update workflows in N8N (workflows > update)
- Activate Workflow (workflows > activate)
- Deactivate Workflow (workflows > deactivate)
- Execute Workflow (workflows > execute)

### Available but NOT Wired
- **Create Workflow** (workflows > create) ← NEEDS ADDING per Decision 3
- Delete Workflow (workflows > delete)
- List Workflows (workflows > list)
- Data Tables CRUD (all operations)
- Nodes list/get
- Credentials list/get/create/delete
- Executions query/events
- Logs read/config

## Claude Code Node Details

### Claude Code CLI (n8n-nodes-claudecode.claudeCode v0.2.2)
- Used in Invoke Claude Code Agent sub-workflow
- Parameters: prompt, outputFormat (json/text/markdown)
- Options: resumeSessionId, timeout (600s), workingDirectory, permissionMode
- Returns: session_id, messages array, result text

### Claude Code Chat Model (n8n-nodes-claudecode-model.lmChatClaudeCode v0.1.2)
- **REPLACEMENT for Gemini** per Decision 10
- Full agentic LLM node for n8n agent chains
- Same ai_languageModel connection type as Gemini
- Currently NOT wired to Susan (uses Gemini instead)

## Patterns to Follow

1. **Separate Entry Points** — Each trigger (Slack, Email, Schedule) gets its own normalization path before converging at agent input node.

2. **Data Table as Memory** — Replace toolCode nodes (Read/Save Memory) with n8n-manager dataTable operations. Both n8n agent and Claude Code agents access same table.

3. **Self-Modification Audit** — Before any n8n-manager write operation, Susan logs the change to Change Log data table.

4. **Dual Ask-Adam** — Blocking sendAndWait for urgent approvals; async Slack DM (no sendAndWait) for informational questions.

5. **Session Resume** — 24h TTL, lookup in Delegated Agent Sessions table, branch on stale/fresh. Chunking for >600s tasks via session resume.

6. **Agent Tool Pattern** — Each n8n-manager operation wired as separate langchain tool with descriptive toolDescription parameter.

## Critical Notes

1. Claude Code Chat Model (v0.1.2) is already installed — drop-in replacement for Gemini node
2. n8n-manager Create Workflow operation already available — just needs tool node wired to Susan
3. memories.json has 20-entry cap and is siloed — data table removes both limitations
4. Simple Memory contextWindowLength=10 should stay small — persistent memory via data table
5. Susan's Delegated Agent Sessions table (0 rows) is ready for use with existing sub-workflow
6. Comment review workflow is orthogonal — can optimize independently
7. No circular dependencies in 45-node workflow — safe for incremental refactoring
