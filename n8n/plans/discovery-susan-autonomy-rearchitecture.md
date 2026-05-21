# Discovery: Susan Autonomy Rearchitecture

## Codebase Context

### Key Files and Data

- **Susan workflow** (`U7cK5XlQqmgG9CWlrB6wM`) — Active, 45 nodes. Triggers: `Incoming Slack Message` (slackTrigger), `Incoming Email` (emailReadImap), `Schedule Trigger` (hourly), `Manual Trigger`. LLM: Google Gemini Pro (latest).
- **"Susan's Responsibilities" table** (`j1I3Rcvck8hQVNhS`) — 2 columns: `description` (string), `helpful_agents` (string). 8 rows with responsibilities ranging from blog comments to GeekLife orders.
- **"Susan's Delegated Agent Sessions" table** (`ASkF5cZWE7SZNibd`) — Tracks Claude Code agent sessions by agent name, session ID, description, start time, last activity.
- **Invoke Claude Code Agent sub-workflow** (`RbZYt9fY7G16RRCl`) — Handles session management, staleness detection (24h TTL), Gemini-generated session summaries.
- **`/opt/claude-agents/Susan/CLAUDE.md`** — Susan's Claude Code agent instructions. References the n8n mirror workflow ID, lists agent-side duties (email, content, reminders, accounting).
- **`/opt/claude-agents/Susan/AGENTS.md`** — Describes the n8n mirror relationship.

### Existing Patterns

- **Hourly trigger flow**: `Schedule Trigger` → `Get Susan's Tasks` (reads all rows from Responsibilities table) → `Standardize Incoming Channel` (builds `HOURLY WORK CHECK` message with all tasks listed) → `Susan` agent (Gemini).
- **Incoming channel normalization**: `Standardize Incoming Channel` code node detects source type (hourly_work, comment_review, slack, email) and builds a structured header.
- **Current hourly behavior**: All 8 responsibility rows are dumped into a single prompt. Susan is expected to "perform these tasks" and send a summary. No scheduling intelligence, no state tracking per responsibility.
- **Self-modification tools**: `Get My n8n Workflow`, `Update workflows in N8N`, `Activate Workflow`, `Deactivate Workflow`, `Execute Workflow` — all n8n-manager tools wired as AI tools.
- **Memory system**: File-based (`/opt/claude-agents/Susan/memories.json`), 20-entry cap, plain-text cues. Not shared between n8n (Gemini) and Claude Code agent instances.
- **Ask Adam tool**: `sendAndWait` Slack DM with double approval buttons — used for comment reviews today.
- **Session staleness**: 24-hour TTL hardcoded in `Check Staleness` node of the sub-workflow.
- **Available agents on server**: Accountant, ATABlogger, BrickBuddy, ClientContentWriter, CourseCraft, Devolutions-CIEM, EasyEntraExpert, eBayManager, Jerry, LegoSellerAssistant, PluralsightCourseReviewer, ProgressAutomationProject, Susan (14 agents).

### Integration Points

- Slack (Susan Slack Bot credential `tTBhVO3JjWS6PhOH`) for inbound messages and outbound replies/DMs.
- Email IMAP/SMTP (DreamHost, `susan@adamtheautomator.com`) for inbound and reply.
- WordPress tool (scheduled posts check).
- n8n-manager community node for self-modification.
- Claude Code node (`n8n-nodes-claudecode`) for spawning agent sessions.
- ATA Blog Comment sub-workflow (`ZjGzXMq9NGSrqMT1`).
- Public webhook base: `https://adam-server.tail2ab7e0.ts.net/n8n/webhook/`

### Initial Observations

- The "Responsibilities" table currently has no scheduling metadata — no `last_run`, no `next_run`, no `frequency`, no `status` fields. Susan cannot make intelligent timing decisions from it.
- The hourly trigger dumps ALL tasks to Susan at once with no state. There is no "did I already check this this hour?" logic.
- The current `helpful_agents` column is a free-text string with no machine-parseable structure.
- The `Ask Adam` tool uses blocking `sendAndWait` — Susan freezes execution waiting for a Slack button click.
- Susan's memory is siloed: the n8n Gemini agent has its own memory buffer + file-based memories, but the Claude Code agent has no access to n8n's memory.
- There is no mechanism today for Susan to create new sub-workflows programmatically.

## Q&A Results

### Wave: Clarify Task

**Q:** The 'Susan's Responsibilities' table only has 'description' and 'helpful_agents' columns. To make Susan's timing decisions intelligent, what scheduling metadata should we add?
**A:** Keep table simple, use memory — Don't change the table. Susan tracks what she's checked recently using her memory and decides timing herself.

**Q:** The hourly trigger currently dumps ALL 8 responsibilities into one prompt. Should the rearchitecture change how responsibilities are processed per trigger cycle?
**A:** Susan decides which to run — Pass all tasks but let Susan autonomously select which to check based on her memory of recent runs. She filters the list herself.

**Q:** Susan can modify existing workflows via n8n-manager tools but has no 'Create Workflow' capability. How should sub-workflow creation work?
**A:** Yes, add Create Workflow tool — Add an n8n-manager Create Workflow tool to Susan's toolset. She can scaffold new sub-workflows from scratch when she identifies a capability gap.

**Q:** The 'Ask Adam for Approval' tool blocks execution via sendAndWait. For autonomous long-running tasks, should this be blocking or non-blocking?
**A:** Both — blocking for urgent, async for others — Use sendAndWait for time-sensitive approvals (e.g., email replies), non-blocking for informational questions.

**Q:** Should new responsibilities be handled within the main Susan workflow, or should Susan dynamically create separate workflows?
**A:** Susan creates sub-workflows for complex tasks — Simple tasks stay in the Responsibilities table. Complex tasks that need their own trigger or multi-step logic get their own sub-workflow.

### Wave: Success Criteria

**Q:** What should Susan do when a responsibility has no helpful_agents defined?
**A:** Handle it herself — Susan attempts the task using her own tools. If she can't complete it, she asks Adam.

**Q:** What should Susan's Slack communication pattern be for autonomous scheduled runs?
**A:** Only message if something happened — Silent unless there's an action taken, a problem found, or something Adam needs to know. No 'all clear' messages.

### Wave: Technical Decisions

**Q:** Should Claude Code agent session TTL be changed from 24 hours?
**A:** Keep 24-hour default — Each responsibility run is essentially a new task. New session each time is clean.

**Q:** Should Susan's memory be unified?
**A:** Use n8n data table as primary memory — Replace file-based memories.json with a dedicated n8n data table that both the n8n agent and any Claude Code agent can access via API.

**Q:** Should the LLM backing Susan's n8n agent be changed?
**A:** Use the Claude Code CLI custom node — Replace Gemini with the Claude Code CLI node as Susan's primary LLM/agent executor.

**Q:** Should the 'helpful_agents' column be made more structured?
**A:** Link to agent registry table — Create a separate Agents table listing all /opt/claude-agents/ agents with descriptions. Responsibilities table references by agent ID.

**Q:** Should Susan have a dedicated Slack channel?
**A:** Keep using DMs — All Susan messages go to Adam's DM. Simple and direct.

**Q:** Should the single hourly trigger be replaced?
**A:** Susan self-schedules via n8n-manager — Susan manages her own trigger intervals. She can modify her own Schedule Trigger node timing as she learns what frequencies work best.

### Wave: Integration Impact

**Q:** Should Susan be able to create new Claude Code agents from scratch?
**A:** Susan should figure things out on her own if no agents — Handle the gap with her own tools rather than creating new agents.

**Q:** Should the Claude Code agent timeout (600s) be changed?
**A:** Keep 600s, use chunking — Keep the current timeout but Susan breaks long tasks into smaller chunks using session resume for continuity.

### Wave: Risks & Unknowns

**Q:** Should self-modification guardrails be added?
**A:** Change log in data table — Add a 'Susan's Change Log' data table. Susan writes every self-modification there before applying it. Audit trail, no blocking.

**Q:** Should execution isolation be added for concurrent runs?
**A:** No isolation needed — n8n handles concurrent executions by default. Keep the single workflow.

**Q:** How should Susan-created sub-workflows be tracked?
**A:** No tracking needed — Susan can discover workflows via the n8n-manager list tool. No explicit registry.

**Q:** Should Susan have write access to email (archiving, labeling)?
**A:** Full inbox management — Susan can archive, label, delete, and mark as read autonomously based on rules she learns.

### Wave: Implementation Preferences

**Q:** Should the Standardize Incoming Channel routing logic be formalized?
**A:** Separate entry-point nodes per source — Split the workflow into distinct entry paths that merge at a common point after source type is established.

**Q:** Should we pre-create missing Claude Code agents for responsibilities with null helpful_agents?
**A:** Susan handles them directly — No pre-creation needed. Susan handles responsibilities with no agent herself using her own tools.

**Q:** What's the recovery strategy if autonomous runs cause n8n issues?
**A:** Manual recovery only — If n8n goes down, Adam restarts it manually. Keep it simple.

## Key Decisions

1. **Table stays simple** — No scheduling columns. Susan uses her memory (n8n data table) to track what she's done recently.
2. **Susan self-filters** — All responsibilities presented, Susan decides which are due based on memory.
3. **Create Workflow tool added** — Susan can create sub-workflows for complex tasks.
4. **Dual ask-Adam mode** — Blocking sendAndWait for urgent, async for informational.
5. **Sub-workflow architecture** — Simple tasks via main workflow, complex tasks get their own sub-workflows.
6. **Self-sufficient** — Susan handles responsibilities with no agent herself, no pre-creation of agents.
7. **Silent unless actionable** — Only message Adam when something happened.
8. **24h session TTL** — No change to Claude Code agent session staleness.
9. **Unified memory via data table** — Replace file-based memories.json with n8n data table.
10. **Claude Code CLI as primary LLM** — Replace Gemini with Claude Code CLI node.
11. **Agent registry table** — New data table for agents, linked from Responsibilities.
12. **DMs only** — Keep Slack communication via DMs.
13. **Self-scheduling** — Susan modifies her own trigger intervals via n8n-manager.
14. **Change log audit trail** — Data table for logging self-modifications.
15. **No execution isolation** — Let n8n handle concurrency.
16. **No workflow registry** — Susan discovers via n8n-manager list.
17. **Full email management** — Susan gets full inbox control (archive, label, delete).
18. **Separate entry paths** — Formalize source detection with distinct entry-point nodes per trigger.
19. **600s timeout with chunking** — Keep current timeout, use session resume for continuity.
20. **Manual recovery** — No watchdog, Adam restarts manually if needed.
