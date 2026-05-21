# Technical Research: Conversation Token Tracking

## Files Analyzed

| File | Key Functions | Relevant Lines | Notes |
|------|---------------|-----------------|-------|
| parsers.py | parse_session_summary() | 139-224 | Parses total session tokens without conversation awareness; token accumulators at lines 158-162 |
| parsers.py | extract_timeline_from_session() | 940-1316 | Implements turn-cost calculation and cumulative session_total; tokens per entry at lines 1048-1093 |
| parsers.py | parse_message() | 278-320 | Extracts messages with parent_uuid field (line 315); base for conversation chain detection |
| parsers.py | parse_full_session() | 323-434 | Builds messages list with parent_uuid (line 315) and subagents dict grouped by parentUuid (lines 391-404) |
| parsers.py | load_session_todos() | 437-476 | Loads todos; no conversation context yet |
| parsers.py | extract_skill_invocations_from_session() | 712-765 | Extracts skills from user messages via regex; no conversation context |
| parsers.py | calculate_turn_cost() | 914-937 | Implements Claude Max cost formula (input + output + cache_creation + cache_read*0.1); used in token attribution |
| models/session.py | SessionSummary | 9-24 | Current fields: total_input_tokens, total_output_tokens, total_cache_* (no conversation_count or current_conversation_id) |
| models/message.py | Message | 7-15 | Has uuid and parent_uuid fields; base model for conversation chain detection |
| models/timeline.py | TimelineEntry | 18-40 | Has session_id (not conversation_id); no conversation_total field yet |
| client.py | list_sessions() | 171-225 | Calls parse_session_summary() for each session file; builds SessionSummary list |
| client.py | get_session() | 227-255 | Calls parse_full_session(); returns full Session with messages (has parent_uuid) |
| client.py | list_timeline() | 616-669 | Calls extract_timeline_from_session() across all project sessions; combines timelines |
| client.py | get_timeline() | 588-614 | Calls extract_timeline_from_session() for single session; returns TimelineEntry list with session_total |
| client.py | list_tool_calls() | 403-476 | Calls extract_tool_calls_from_session() or extract_tool_calls_with_subagents(); builds ToolCallSummary list |
| client.py | list_todos() | 673-711 | Calls load_session_todos() for each session; no conversation context |
| client.py | list_subagent_activity() | 300-371 | Extracts subagent data per session; no conversation context |
| client.py | list_skills() | 499-562 | Extracts skill invocations per session; no conversation context |
| commands/timeline.py | list_timeline() | 58-133 | Supports --session-id filter (line 88-89); model shows filtering pattern |
| commands/timeline.py | consolidated_timeline() | 137-206 | Requires --session-id; shows client-side filtering with apply_filters() (lines 170-171) |
| commands/sessions.py | list_sessions() | 11-58 | Shows client-side filtering pattern with apply_filters() (lines 36-37) |
| commands/tool_calls.py | list_tool_calls() | 12-70 | Shows --subagent-id filter pattern (lines 49-51); automatic include_subagents toggle (lines 39-40) |
| commands/subagent_activity.py | list_subagent_activity() | 11-61 | Calls client.list_subagent_activity(); applies filters client-side |
| commands/todos.py | list_todos() | 11-52 | Shows filter pattern; calls client.list_todos() |
| commands/skills.py | list_skills() | 11-52 | Shows filter pattern; calls client.list_skills() |
| filters.py | apply_filters() | 47-92 | Client-side filtering engine; supports multiple operators (eq, ne, gt, contains, etc.) |

## APIs/Tools Verified

| Tool/API | Command/Method | Verified Signature | Notes |
|----------|----------------|-------------------|-------|
| iter_session_lines() | parsers.py:119 | `(session_path: Path) -> Iterator[Dict[str, Any]]` | Reads JSONL line by line, handles parse errors |
| parse_session_summary() | parsers.py:139 | `(session_path: Path, project_name: str) -> Optional[SessionSummary]` | Returns summary with token counts; called by list_sessions() |
| extract_timeline_from_session() | parsers.py:940 | `(session_path: Path, project_name: str) -> List[TimelineEntry]` | Returns timeline with cumulative session_total; used by get_timeline() and list_timeline() |
| calculate_turn_cost() | parsers.py:914 | `(input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) -> int` | Formula: input + output + cache_creation + (cache_read * 0.1) |
| parse_message() | parsers.py:278 | `(entry: Dict[str, Any], tool_results: Dict[str, Dict]) -> Message` | Extracts Message with parent_uuid field |
| apply_filters() | filters.py:47 | `(data: List[Dict], filter_strings: Optional[List[str]]) -> List[Dict]` | Client-side filtering; supports 'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'nin', 'like', 'ilike', 'contains', 'startswith', 'endswith', 'null', 'notnull' |
| TimelineEntry.model_dump() | models/timeline.py:18 | Returns dict with all fields | Used for JSON output and filtering |
| SessionSummary.model_dump() | models/session.py:9 | Returns dict with all fields | Used for JSON output and filtering |

## Integration Map

### Token Tracking Flow
```
extract_timeline_from_session()
  ├─ iter_session_lines()          [reads JSONL entries]
  ├─ calculate_turn_cost()          [computes effective cost per turn]
  └─ TimelineEntry                  [stores turn_cost and session_total]

parse_session_summary()
  ├─ iter_session_lines()           [reads JSONL entries]
  └─ extract token usage            [accumulates total_input/output/cache tokens]

list_sessions() [client.py:171]
  └─ parse_session_summary()        [for each session file]

list_timeline() [client.py:616]
  ├─ extract_timeline_from_session() [for each session file]
  └─ combine all timelines          [across project sessions]
```

### Filter Pattern Flow
```
Command (e.g., timeline list)
  ├─ client.list_timeline()
  │   └─ returns List[TimelineEntry]
  └─ convert to dicts: [e.model_dump() for e in timeline]
     ├─ apply --session-id filter (client-side, line 88-89)
     ├─ apply --filter via apply_filters() (lines 96-97)
     └─ output JSON or table
```

### Conversation Detection Pattern
```
Conversation boundaries detected by:
  1. parent_uuid field in Message (line 315 in parse_message)
  2. When parent_uuid is null or breaks chain → new conversation
  3. /clear command creates system message, next user has broken parentUuid
  4. Conversation ID: Sequential (conversation-1, conversation-2, etc.)
  
Current usage:
  - parse_message() reads parent_uuid at line 315
  - parse_full_session() reads parent_uuid at line 393 (for subagent grouping)
  - Message.parent_uuid is Optional[str] (line 11 in models/message.py)
```

## Patterns to Follow

### 1. SessionSummary Model Extension (models/session.py:9)
**Current pattern (lines 20-24):**
```python
# Token usage totals
total_input_tokens: int = 0
total_output_tokens: int = 0
total_cache_read_tokens: int = 0
total_cache_creation_tokens: int = 0
```

**Add fields after total_cache_creation_tokens:**
```python
conversation_count: int = 1  # Number of conversations in session (default 1)
current_conversation_id: int = 0  # Latest conversation number (0-based index into conversation_count)
```
Reference: User Q&A Wave 1 - SessionSummary model should have conversation_count and current_conversation_id

### 2. TimelineEntry Model Extension (models/timeline.py:18)
**Current pattern (lines 39-40):**
```python
# Computed cost metrics for Claude Max tracking
turn_cost: Optional[int] = None  # Effective tokens for this API turn
session_total: Optional[int] = None  # Cumulative session cost up to this point
```

**Add after session_total:**
```python
conversation_id: int = 0  # Sequential conversation number (1, 2, 3...)
conversation_total: Optional[int] = None  # Cumulative conversation cost up to this point
```
Reference: User Q&A - conversation_id always in JSON output for all commands

### 3. Message Model Extension (models/message.py:7)
**Add after parent_uuid:**
```python
conversation_id: Optional[int] = None  # Computed during parsing (no field needed in JSONL)
```
Note: This is computed during parsing, not stored in JSONL. User specified "Compute during parsing (no model change needed)" - but adding optional field for consistency in output

### 4. Token Tracking in parse_session_summary() (parsers.py:139)
**Current pattern (lines 158-162, 184-189):**
```python
# Token accumulators at initialization
total_input_tokens = 0
total_output_tokens = 0
total_cache_read_tokens = 0
total_cache_creation_tokens = 0

# Extract from assistant messages
if entry_type == 'assistant':
    usage = message.get('usage', {})
    total_input_tokens += usage.get('input_tokens', 0)
    total_output_tokens += usage.get('output_tokens', 0)
    total_cache_read_tokens += usage.get('cache_read_input_tokens', 0)
    total_cache_creation_tokens += usage.get('cache_creation_input_tokens', 0)
```

**Modify to track conversations:**
- Add conversation detection logic before token accumulation
- When parent_uuid breaks or is null, increment conversation counter
- Track conversation_count and current_conversation_id
- Return these in SessionSummary

Reference: User Q&A - "Modify existing parser" - don't create new function

### 5. Conversation Detection Logic (parsers.py)
**Pattern to implement:**
```python
# Track conversations as we iterate through entries
current_conversation_id = 0
conversation_count = 0
last_parent_uuid = None

for entry in iter_session_lines(session_path):
    if entry_type in ('user', 'assistant'):
        parent_uuid = entry.get('parentUuid')
        
        # New conversation if parent breaks chain or is first entry
        if parent_uuid != last_parent_uuid:
            if parent_uuid is None or last_parent_uuid is None:
                conversation_count += 1
                current_conversation_id = conversation_count
        
        last_parent_uuid = parent_uuid
```

Reference: Discovery document - "New conversations start when parentUuid is null or breaks the chain"

### 6. Token Attribution to Conversations in extract_timeline_from_session() (parsers.py:940)
**Current pattern (lines 1296-1314):**
```python
# Calculate cumulative session_total
cumulative_total = 0
seen_turns = set()

for entry in timeline:
    if entry.turn_cost and entry.turn_cost > 0:
        turn_key = f"{entry.timestamp}:{entry.event_type.value}"
        
        if turn_key not in seen_turns:
            cumulative_total += entry.turn_cost
            seen_turns.add(turn_key)
        
        entry.session_total = cumulative_total if cumulative_total > 0 else None
```

**Pattern to follow for conversation_total:**
- Add parallel conversation tracking (conversation_cumulative_total dict or reset per conversation)
- Same deduplication logic (turn_key check) applies
- Set entry.conversation_total alongside entry.session_total
- Set entry.conversation_id during timeline entry creation

Reference: User Q&A - "Show both with labels (Session: X | Conv: Y format)" - the timeline entry will have both fields

### 7. Filter Pattern in Commands (commands/timeline.py:88-89)
**Current pattern:**
```python
# Apply session_id filter
if session_id:
    items = [item for item in items if item.get('session_id') == session_id]
```

**Pattern for conversation_id filter to replicate:**
```python
# Apply conversation_id filter (requires session_id first)
if conversation_id and session_id:
    items = [item for item in items if 
             item.get('session_id') == session_id and 
             item.get('conversation_id') == int(conversation_id.split('-')[1])]
elif conversation_id and not session_id:
    raise typer.Exit("--conversation-id requires --session-id")
```

Reference: User Q&A - "--conversation-id requires --session-id first"

### 8. Command Option Pattern (commands/tool_calls.py:20)
**Current subagent_id filter pattern (lines 20-21, 49-51):**
```python
# In command definition:
subagent_id: Optional[str] = typer.Option(None, "--subagent-id", help="Filter to tool calls...")

# In command execution:
if subagent_id:
    items = [item for item in items if item.get('parent_tool_call_id') == subagent_id]
```

**Pattern for --conversation-id to replicate:**
```python
# In command definition:
conversation_id: Optional[str] = typer.Option(None, "--conversation-id", help="Filter by conversation ID (requires --session-id)")

# Validation:
if conversation_id and not session_id:
    handle_error("--conversation-id requires --session-id")
```

Reference: User Q&A - Full ID format required ('conversation-1', 'conversation-2')

### 9. Client List Method Pattern (client.py:171-225)
**Current list_sessions() pattern:**
```python
def list_sessions(
    self,
    project: str,
    limit: int = 100,
    since: Optional[str] = None,
    filters: Optional[List[str]] = None,
) -> List[SessionSummary]:
    # Get project dir
    # Parse since filter
    # Iterate session files
    # Call parse_session_summary() for each
    # Apply time filtering
    # Sort by last_activity (most recent first)
    # Return limited list
```

**Pattern for new list_conversations() method to implement:**
- Iterate over sessions (like list_sessions does)
- For each session, call parse_full_session() to get messages
- Detect conversation boundaries based on parent_uuid
- Return list of ConversationSummary objects
- Include: session_id, conversation_id, token counts per conversation, message_count, etc.

Reference: User Q&A - "New list_conversations() method"

### 10. Conversation Summary Model (to create)
**New model pattern based on existing summaries:**

Create `models/conversation.py` following SessionSummary pattern:
```python
class ConversationSummary(CLIModel):
    """Summary of a conversation within a session."""
    
    id: int  # conversation-1, conversation-2 (stored as int 1, 2)
    session_id: str
    project: str
    conversation_id: int  # Sequential number
    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_call_count: int
    created_at: str  # First message timestamp
    ended_at: str  # Last message timestamp
    # Token usage for this conversation only
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
```

Reference: User Q&A - conversation tracking separate from session tracking

### 11. Subagent Token Tracking (parsers.py:1244-1291)
**Current pattern (lines 1244-1254):**
```python
# Extract token usage from the message
usage = message.get('usage', {})
input_tokens = usage.get('input_tokens', 0)
output_tokens = usage.get('output_tokens', 0)
cache_read_tokens = usage.get('cache_read_input_tokens', 0)
cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
total_input_tokens = input_tokens + cache_read_tokens + cache_creation_tokens

# Calculate effective turn cost
turn_cost = calculate_turn_cost(
    input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
)
```

**Note:** Subagent tool calls (TimelineEventType.SUBAGENT_TOOL) already have separate token tracking. No change needed - per user Q&A: "Subagent tokens tracked separately"

### 12. Error Handling for Missing Conversations (commands/timeline.py)
**Pattern to implement:**

When filtering by --conversation-id in consolidated_timeline or other commands:
```python
if conversation_id and conversation_id not in valid_conversation_ids:
    raise typer.Exit(handle_error(f"conversation-{conversation_id} not found in session"))
```

Reference: User Q&A - "Error with message: 'conversation-5 not found in session'"

## Implementation Dependencies

1. **No changes to JSONL format required** - parentUuid already exists in Message JSONL entries
2. **Conversation detection is computational** - derived from parent_uuid chains during parsing
3. **Token attribution follows existing logic** - same turn_cost and deduplication rules apply
4. **Filter engine ready** - apply_filters() supports all needed operators
5. **Client pattern established** - list_* and get_* methods follow consistent pattern
6. **Timeline entry structure flexible** - can add conversation_id and conversation_total fields

## Key Observations

- **Token tracking already sophisticated:** calculate_turn_cost() handles cache discounting, duplicate detection prevents double-counting, cumulative session_total properly handles multiple tools per turn
- **Message parent_uuid already captured:** parse_message() reads it at line 315, making conversation detection possible without JSONL schema changes
- **Filter infrastructure robust:** apply_filters() handles OR/AND logic, type casting, multiple operators - ready for conversation_id filter
- **Subagent tracking separate by design:** SubagentSummary and TimelineEntry.SUBAGENT_TOOL already segregate subagent tokens from main conversation
- **Session is not conversation:** Current SessionSummary aggregates ALL tokens; new fields will indicate multi-conversation sessions
- **Timeline cumulative cost works per-session:** extract_timeline_from_session() resets per session file; need conversation-level reset within same session

## Commands Requiring --conversation-id Filter Implementation

1. **timeline list** - Add --conversation-id with --session-id dependency
2. **timeline consolidated** - Add --conversation-id with --session-id dependency
3. **timeline get** - Already takes session_id; add --conversation-id filter
4. **messages (new or via session get)** - Filter messages by conversation
5. **todos list** - Optional: filter todos by conversation (per user requirements)
6. **tool_calls list** - Optional: filter tool calls by conversation (per user requirements)
7. **subagent_activity list** - No change: subagents separate (per user Q&A)
8. **skills list** - Optional: filter skills by conversation

Reference: Discovery document lists "commands needing filters" - this adds conversation_id to existing infrastructure

