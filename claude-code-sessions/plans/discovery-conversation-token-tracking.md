# Discovery: Conversation-Aware Token Tracking

## Codebase Context

### Key Files
- `parsers.py` (lines 158-225) - `parse_session_summary()` tracks total tokens across ALL messages without conversation awareness
- `parsers.py` (lines 914-937) - `calculate_turn_cost()` implements Claude Max token cost calculation
- `parsers.py` (lines 940-1316) - `extract_timeline_from_session()` implements token tracking per timeline entry
- `models/session.py` - `SessionSummary` model with `total_input_tokens`, `total_output_tokens` fields
- `models/message.py` - `Message` model with `parent_uuid` field that creates conversation chains
- `models/timeline.py` - `TimelineEntry` with token tracking fields

### Conversation Detection Pattern
- Messages are chained via `parentUuid` field
- New conversations start when `parentUuid` is `null` or breaks the chain
- The `/clear` command creates a system message, then next user message has broken parentUuid chain

### Current Filter Support
- All list commands support `--filter` parameter
- `timeline list` has `--session-id` filter
- No `--conversation-id` filter exists anywhere
- `tool-calls list` has `--subagent-id` filter (recently added)

### Commands Needing Filters
- `commands/sessions.py` - list/get commands
- `commands/timeline.py` - list/consolidated/get commands
- `commands/todos.py` - list/get commands
- `commands/tool_calls.py` - list/get commands
- `commands/subagent_activity.py` - list/get commands
- `commands/skills.py` - list/get commands

## Q&A Results

### Wave: Clarify Task

**Q:** Should conversation IDs be auto-generated sequential numbers (1, 2, 3) or use the UUID of the first user message in each conversation?
**A:** Sequential (1, 2, 3...)

**Q:** The SessionSummary model shows total tokens for the whole session. Should we add conversation_count and current_conversation_id fields to this model?
**A:** Yes, add both fields

**Q:** parse_session_summary() sums tokens across all messages. Should conversation-aware tracking modify this function or create a new one?
**A:** Modify existing parser

### Wave: Success Criteria

**Q:** For timeline view, when filtering by conversation, should session_total reset to 0 at each conversation boundary or show cumulative since conversation start?
**A:** Show both with labels (Session: X | Conv: Y format)

**Q:** The sessions list command shows token totals in table format. Should this display 'Current Conversation' tokens or 'Total Session' tokens by default?
**A:** Total session (existing) - keep current behavior

### Wave: Technical Decisions

**Q:** How should token attribution behave across conversation boundaries?
**A:** User wants accurate token count by conversation - implementation detail left to developer

**Q:** Should --conversation-id accept full ID (conversation-1) or support shortcuts?
**A:** Full ID only - must specify 'conversation-1', 'conversation-2'

**Q:** The Message model has parent_uuid but no conversation_id. Should we add it as a field or compute it on-the-fly?
**A:** Compute during parsing (no model change needed)

**Q:** When a session has multiple conversations, should parse_full_session() return all conversations or just the current/latest one?
**A:** All conversations with boundaries marked

### Wave: Edge Cases

**Q:** What if a session has no /clear commands (single conversation)?
**A:** conversation_count = 1 - treat entire session as conversation-1

**Q:** Should subagent tokens count toward the main conversation's token total?
**A:** Track separately - show 'Main: X | Subagents: Y' breakdown

**Q:** When adding --conversation-id filter, should it require --session-id?
**A:** Yes, requires --session-id first, then conversation

**Q:** What should happen if user requests --conversation-id that doesn't exist?
**A:** Error with message: "conversation-5 not found in session"

### Wave: Implementation Preferences

**Q:** For parsing conversation detection, single pass or two passes?
**A:** Developer's choice (user doesn't care)

**Q:** Should we add a new list_conversations() client method or extend list_sessions()?
**A:** New list_conversations() method

**Q:** Should conversation_id be visible in JSON output for all commands?
**A:** Always include - add conversation_id field to all message/timeline output

### Wave: Risk Assessment

**Q:** Will conversation boundaries affect deduplication logic?
**A:** User defers to implementation - handle appropriately based on current code

**Q:** Does conversation-aware tracking affect Claude Max cost formula?
**A:** User unsure - keep formula same, change aggregation per conversation

**Q:** Should conversation filtering apply to subagent data?
**A:** No, subagents separate - filtering independent of conversation

### Wave: Testing

**Q:** For testing, use existing sessions or create synthetic fixtures?
**A:** Use existing sessions for testing

## Key Decisions

1. **Conversation IDs**: Sequential numbers (1, 2, 3...)
2. **Model changes**: Add `conversation_count` and `current_conversation_id` to SessionSummary
3. **Parser approach**: Modify existing `parse_session_summary()` function
4. **Token display**: Show both session and conversation totals with labels
5. **Default display**: Keep total session tokens as default
6. **Filter behavior**: `--conversation-id` requires `--session-id`
7. **Error handling**: Error message when conversation not found
8. **JSON output**: Always include conversation_id field
9. **Subagents**: Track separately from conversation tokens, filtering independent
10. **Testing**: Use existing session files
