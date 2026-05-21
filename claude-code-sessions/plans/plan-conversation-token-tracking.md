# Implementation Plan: Conversation-Aware Token Tracking

## Summary
The current CLI tracks tokens only at the session level without recognizing conversation boundaries within sessions. This implementation adds conversation-aware token tracking by detecting conversation boundaries from parent_uuid chains, assigning sequential conversation IDs (1, 2, 3...), and displaying both session and conversation token totals throughout the CLI.

## Why This Approach
This is the simplest solution because it:
- **Reuses existing parent_uuid chains** - no JSONL schema changes needed
- **Modifies existing parsers** - extends parse_session_summary() and extract_timeline_from_session() rather than duplicating logic
- **Follows established patterns** - uses same filter infrastructure, client method patterns, and model extension approach
- **Leverages compute-on-parse** - conversation IDs computed during parsing, not stored

**Alternatives considered:**
- Store conversation_id in JSONL: Rejected - requires schema change and backfill
- Two-pass parsing: Rejected - one pass sufficient (detect boundaries while accumulating tokens)
- UUID-based conversation IDs: Rejected - sequential numbers clearer for users

## Prerequisites
- Existing CLI with token tracking infrastructure (calculate_turn_cost, parse_session_summary, extract_timeline_from_session)
- Parent_uuid field in Message model (already exists)
- Filter infrastructure (apply_filters) operational
- Existing session files for testing (per user requirement)

## Implementation Steps

### Step 1: Extend SessionSummary Model
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/models/session.py`
**Action:** Add conversation tracking fields after line 24 (after total_cache_creation_tokens):
```python
conversation_count: int = 1  # Number of conversations in session (default 1)
current_conversation_id: int = 1  # Latest conversation number (1, 2, 3...)
```
**Reference:** Research lines 95-109 (SessionSummary model extension pattern)
**Verify:** Run `python -c "from src.claude_code_sessions.models.session import SessionSummary; print(SessionSummary.__fields__.keys())"` - should include 'conversation_count' and 'current_conversation_id'

### Step 2: Extend TimelineEntry Model
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/models/timeline.py`
**Action:** Add conversation fields after line 40 (after session_total):
```python
conversation_id: int = 1  # Sequential conversation number (1, 2, 3...)
conversation_total: Optional[int] = None  # Cumulative conversation cost up to this point
```
**Reference:** Research lines 112-126 (TimelineEntry model extension pattern)
**Verify:** Run `python -c "from src.claude_code_sessions.models.timeline import TimelineEntry; print(TimelineEntry.__fields__.keys())"` - should include 'conversation_id' and 'conversation_total'

### Step 3: Extend Message Model
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/models/message.py`
**Action:** Add conversation_id field after line 11 (after parent_uuid):
```python
conversation_id: Optional[int] = None  # Computed during parsing
```
**Reference:** Research lines 127-132 (Message model extension pattern)
**Verify:** Run `python -c "from src.claude_code_sessions.models.message import Message; print(Message.__fields__.keys())"` - should include 'conversation_id'

### CHECKPOINT: Verify Model Extensions
**Run:** `pytest tests/models/ -v` (if tests exist) or manually import all three models
**Expected:** All models import successfully with new fields, no import errors

### Step 4: Add Conversation Detection Helper Function
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/parsers.py`
**Action:** Add helper function before parse_session_summary() (around line 135):
```python
def detect_conversation_boundaries(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Detect conversation boundaries from parent_uuid chains.
    Returns mapping of message uuid -> conversation_id.

    New conversations start when:
    - First message (parent_uuid is None)
    - parent_uuid breaks the chain (references non-existent message)
    """
    conversation_map = {}
    current_conversation_id = 0
    seen_uuids = set()

    for entry in entries:
        entry_type = entry.get('type')
        if entry_type not in ('user', 'assistant'):
            continue

        uuid = entry.get('uuid')
        parent_uuid = entry.get('parentUuid')

        # Start new conversation if parent breaks chain
        if parent_uuid is None or parent_uuid not in seen_uuids:
            current_conversation_id += 1

        conversation_map[uuid] = current_conversation_id
        seen_uuids.add(uuid)

    return conversation_map
```
**Reference:** Research lines 160-181 (conversation detection pattern)
**Verify:** Test with simple list of entries with broken parent_uuid chains

### Step 5: Modify parse_session_summary() for Conversation Tracking
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/parsers.py`
**Action:** Update parse_session_summary() function (lines 139-224):

1. Collect all entries first (before line 158):
```python
all_entries = list(iter_session_lines(session_path))
conversation_map = detect_conversation_boundaries(all_entries)
```

2. Track current conversation ID during iteration (add after line 162):
```python
current_conversation_id = 0
```

3. Update current_conversation_id when processing messages (inside message loop around line 184):
```python
uuid = entry.get('uuid')
if uuid and uuid in conversation_map:
    current_conversation_id = conversation_map[uuid]
```

4. Set conversation fields in returned SessionSummary (around line 220):
```python
conversation_count = max(conversation_map.values()) if conversation_map else 1
current_conversation_id = current_conversation_id or 1
```

**Reference:** Research lines 134-158 (token tracking modification pattern)
**Verify:** Run `claude-code-sessions sessions list --output-format json` - check that conversation_count and current_conversation_id appear in output

### CHECKPOINT: Verify Session Summary Changes
**Run:** `claude-code-sessions sessions list --limit 5 --output-format json | jq '.[0] | {session_id, conversation_count, current_conversation_id}'`
**Expected:** JSON output shows conversation_count >= 1 and current_conversation_id matches expected value for known multi-conversation sessions

### Step 6: Add Conversation Detection to parse_message()
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/parsers.py`
**Action:** Update parse_message() function (lines 278-320) to accept conversation_map parameter:

1. Update signature (line 278):
```python
def parse_message(
    entry: Dict[str, Any],
    tool_results: Dict[str, Dict],
    conversation_map: Optional[Dict[str, int]] = None
) -> Message:
```

2. Set conversation_id field (after line 315 where parent_uuid is set):
```python
uuid = entry.get('uuid')
conversation_id = conversation_map.get(uuid, 1) if conversation_map else None
```

3. Include conversation_id in Message construction (around line 318)

**Reference:** Research lines 127-132 (Message model expects conversation_id)
**Verify:** Check parse_message returns Message with conversation_id populated

### Step 7: Update parse_full_session() to Pass Conversation Map
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/parsers.py`
**Action:** Update parse_full_session() function (lines 323-434):

1. Generate conversation_map at start (after line 328):
```python
all_entries = list(iter_session_lines(session_path))
conversation_map = detect_conversation_boundaries(all_entries)
```

2. Pass conversation_map to parse_message() calls (lines 337, 389):
```python
message = parse_message(entry, tool_results, conversation_map)
```

**Reference:** Research lines 9-10 (parse_full_session integration)
**Verify:** Run `claude-code-sessions sessions get <session-id> --output-format json | jq '.messages[0].conversation_id'` - should show conversation ID

### Step 8: Add Conversation Tracking to extract_timeline_from_session()
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/parsers.py`
**Action:** Update extract_timeline_from_session() function (lines 940-1316):

1. Generate conversation_map at start (after reading all entries around line 945):
```python
all_entries = list(iter_session_lines(session_path))
conversation_map = detect_conversation_boundaries(all_entries)
```

2. Add conversation tracking variables (around line 1296 where cumulative_total starts):
```python
cumulative_total = 0
conversation_totals = {}  # Dict[int, int] - conversation_id -> cumulative total
seen_turns = set()
```

3. When creating TimelineEntry objects (around lines 1048-1093), set conversation_id:
```python
uuid = entry.get('uuid')
conversation_id = conversation_map.get(uuid, 1) if conversation_map else 1
```

4. In cumulative calculation loop (lines 1296-1314), track both session_total and conversation_total:
```python
for entry in timeline:
    if entry.turn_cost and entry.turn_cost > 0:
        turn_key = f"{entry.timestamp}:{entry.event_type.value}"

        if turn_key not in seen_turns:
            cumulative_total += entry.turn_cost

            # Track conversation total
            conv_id = entry.conversation_id
            if conv_id not in conversation_totals:
                conversation_totals[conv_id] = 0
            conversation_totals[conv_id] += entry.turn_cost

            seen_turns.add(turn_key)

        entry.session_total = cumulative_total if cumulative_total > 0 else None
        entry.conversation_total = conversation_totals.get(entry.conversation_id, 0) or None
```

**Reference:** Research lines 183-207 (conversation_total tracking pattern)
**Verify:** Run `claude-code-sessions timeline get <session-id> --output-format json | jq '.[0] | {conversation_id, conversation_total, session_total}'` - should show both totals

### CHECKPOINT: Verify Timeline Token Tracking
**Run:** `claude-code-sessions timeline get <multi-conversation-session-id> --output-format json | jq '.[] | select(.conversation_id == 2) | {event_type, turn_cost, conversation_total, session_total}' | head -20`
**Expected:** conversation_total resets at conversation boundary, session_total continues cumulative

### Step 9: Create ConversationSummary Model
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/models/conversation.py` (new file)
**Action:** Create new model:
```python
"""Conversation summary model for Claude Code sessions."""
from typing import Optional
from .base import CLIModel


class ConversationSummary(CLIModel):
    """Summary of a conversation within a session."""

    # Identifiers
    session_id: str
    project: str
    conversation_id: int  # Sequential number (1, 2, 3...)

    # Message counts
    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_call_count: int = 0

    # Timestamps
    created_at: str  # First message timestamp
    ended_at: Optional[str] = None  # Last message timestamp

    # Token usage for this conversation only
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
```
**Reference:** Research lines 281-306 (ConversationSummary model pattern)
**Verify:** Import model successfully: `python -c "from src.claude_code_sessions.models.conversation import ConversationSummary; print(ConversationSummary)"`

### Step 10: Add parse_conversation_summaries() Parser Function
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/parsers.py`
**Action:** Add new function after parse_session_summary() (around line 225):
```python
def parse_conversation_summaries(
    session_path: Path,
    project_name: str
) -> List[ConversationSummary]:
    """
    Parse conversation summaries from a session file.
    Groups messages by conversation_id and returns token totals per conversation.
    """
    from .models.conversation import ConversationSummary

    all_entries = list(iter_session_lines(session_path))
    conversation_map = detect_conversation_boundaries(all_entries)

    if not conversation_map:
        return []

    # Initialize conversation data structures
    conversations = {}  # conversation_id -> data dict

    for entry in all_entries:
        entry_type = entry.get('type')
        uuid = entry.get('uuid')

        if uuid not in conversation_map:
            continue

        conv_id = conversation_map[uuid]

        # Initialize conversation if first time seeing it
        if conv_id not in conversations:
            conversations[conv_id] = {
                'session_id': session_path.stem,
                'project': project_name,
                'conversation_id': conv_id,
                'message_count': 0,
                'user_message_count': 0,
                'assistant_message_count': 0,
                'tool_call_count': 0,
                'created_at': None,
                'ended_at': None,
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_cache_read_tokens': 0,
                'total_cache_creation_tokens': 0,
            }

        conv_data = conversations[conv_id]

        # Update timestamps
        timestamp = entry.get('timestamp', '')
        if not conv_data['created_at']:
            conv_data['created_at'] = timestamp
        conv_data['ended_at'] = timestamp

        # Count messages
        if entry_type == 'user':
            conv_data['message_count'] += 1
            conv_data['user_message_count'] += 1
        elif entry_type == 'assistant':
            conv_data['message_count'] += 1
            conv_data['assistant_message_count'] += 1

            # Accumulate tokens
            usage = entry.get('message', {}).get('usage', {})
            conv_data['total_input_tokens'] += usage.get('input_tokens', 0)
            conv_data['total_output_tokens'] += usage.get('output_tokens', 0)
            conv_data['total_cache_read_tokens'] += usage.get('cache_read_input_tokens', 0)
            conv_data['total_cache_creation_tokens'] += usage.get('cache_creation_input_tokens', 0)
        elif entry_type == 'tool_use':
            conv_data['tool_call_count'] += 1

    # Convert to ConversationSummary objects
    return [ConversationSummary(**data) for data in conversations.values()]
```
**Reference:** Research lines 252-279 (client list method pattern)
**Verify:** Test function returns list of ConversationSummary objects with proper token counts

### Step 11: Add list_conversations() Client Method
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/client.py`
**Action:** Add new method after list_sessions() (around line 225):
```python
def list_conversations(
    self,
    project: str,
    session_id: Optional[str] = None,
    limit: int = 100,
    filters: Optional[List[str]] = None,
) -> List[ConversationSummary]:
    """
    List conversations across sessions or within a specific session.

    Args:
        project: Project name
        session_id: Optional session ID to filter conversations
        limit: Maximum number of conversations to return
        filters: Optional filter expressions

    Returns:
        List of conversation summaries
    """
    from .parsers import parse_conversation_summaries
    from .models.conversation import ConversationSummary

    project_dir = self._get_project_sessions_dir(project)
    if not project_dir.exists():
        return []

    conversations = []

    # Get session files
    session_files = sorted(project_dir.glob("*.jsonl"), reverse=True)

    # Filter by session_id if provided
    if session_id:
        session_files = [f for f in session_files if f.stem == session_id]

    for session_file in session_files:
        conv_summaries = parse_conversation_summaries(session_file, project)
        conversations.extend(conv_summaries)

        if len(conversations) >= limit:
            break

    # Sort by created_at (most recent first)
    conversations.sort(key=lambda c: c.created_at, reverse=True)

    return conversations[:limit]
```
**Reference:** Research lines 252-279 (list_conversations method pattern)
**Verify:** Run test: `python -c "from src.claude_code_sessions.client import ClaudeCodeSessionsClient; client = ClaudeCodeSessionsClient(); print(len(client.list_conversations('<project>')))"`

### CHECKPOINT: Verify Conversation Parsing
**Run:** Test list_conversations() method programmatically with known session
**Expected:** Returns list of ConversationSummary objects with accurate token counts per conversation

### Step 12: Add conversations list Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/conversations.py` (new file)
**Action:** Create new command file:
```python
"""Conversations command for listing conversations within sessions."""
import typer
from typing import Optional, List

from ..client import ClaudeCodeSessionsClient
from ..formatters import format_output
from ..filters import apply_filters
from ..error_handler import handle_error


app = typer.Typer()


@app.command("list")
def list_conversations(
    project: Optional[str] = typer.Option(None, help="Project name"),
    session_id: Optional[str] = typer.Option(None, "--session-id", help="Filter to specific session"),
    output_format: str = typer.Option("table", "--output-format", "-o", help="Output format (table or json)"),
    limit: int = typer.Option(100, "--limit", help="Maximum number of conversations to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", help="Filter expression (field:operator:value)"),
):
    """List conversations across sessions or within a specific session."""
    try:
        client = ClaudeCodeSessionsClient()

        # Get project from config if not provided
        if not project:
            project = client.config.get("default_project", "")
            if not project:
                typer.echo(handle_error("No project specified and no default project configured"))
                raise typer.Exit(code=1)

        # List conversations
        conversations = client.list_conversations(
            project=project,
            session_id=session_id,
            limit=limit,
        )

        # Convert to dictionaries for filtering and output
        items = [conv.model_dump() for conv in conversations]

        # Apply filters
        if filter:
            items = apply_filters(items, filter)

        # Output
        typer.echo(format_output(items, output_format))

    except Exception as e:
        typer.echo(handle_error(str(e)))
        raise typer.Exit(code=1)
```
**Reference:** Research lines 209-232 (command filter pattern)
**Verify:** Run `claude-code-sessions conversations list --help` - should show command with options

### Step 13: Register conversations Command in Main CLI
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/cli.py`
**Action:** Import and register conversations command (similar to existing commands):
```python
from .commands import conversations

app.add_typer(conversations.app, name="conversations", help="Manage conversations within sessions")
```
**Reference:** Existing command registration pattern in cli.py
**Verify:** Run `claude-code-sessions --help` - should show 'conversations' command

### Step 14: Add --conversation-id Filter to timeline list Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/timeline.py`
**Action:** Update list_timeline() function (lines 58-133):

1. Add conversation_id parameter (after session_id around line 64):
```python
conversation_id: Optional[str] = typer.Option(None, "--conversation-id", help="Filter by conversation ID (requires --session-id)")
```

2. Add validation (before calling client.list_timeline around line 85):
```python
if conversation_id and not session_id:
    typer.echo(handle_error("--conversation-id requires --session-id"))
    raise typer.Exit(code=1)
```

3. Add conversation_id filter (after session_id filter around line 90):
```python
if conversation_id:
    # Extract numeric ID from 'conversation-N' format
    try:
        conv_num = int(conversation_id.split('-')[1])
        items = [item for item in items if item.get('conversation_id') == conv_num]

        if not items:
            typer.echo(handle_error(f"{conversation_id} not found in session {session_id}"))
            raise typer.Exit(code=1)
    except (IndexError, ValueError):
        typer.echo(handle_error(f"Invalid conversation ID format: {conversation_id} (expected 'conversation-N')"))
        raise typer.Exit(code=1)
```

**Reference:** Research lines 209-227 (filter pattern with validation)
**Verify:** Run `claude-code-sessions timeline list --session-id <id> --conversation-id conversation-1` - should filter to conversation 1

### Step 15: Add --conversation-id Filter to timeline consolidated Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/timeline.py`
**Action:** Update consolidated_timeline() function (lines 137-206):

1. Add conversation_id parameter (after session_id around line 143):
```python
conversation_id: Optional[str] = typer.Option(None, "--conversation-id", help="Filter by conversation ID (requires --session-id)")
```

2. Add same validation and filtering logic as in step 14

**Reference:** Research lines 209-227 (same pattern as timeline list)
**Verify:** Run `claude-code-sessions timeline consolidated --session-id <id> --conversation-id conversation-2` - should filter properly

### Step 16: Add --conversation-id Filter to timeline get Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/timeline.py`
**Action:** Update get_timeline() function (add conversation_id parameter and filtering):

1. Add parameter
2. Add conversation_id filtering after retrieving timeline entries

**Reference:** Same pattern as steps 14-15
**Verify:** Run `claude-code-sessions timeline get <session-id> --conversation-id conversation-1` - should filter entries

### Step 17: Update Timeline Table Formatter for Conversation Tokens
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/formatters.py`
**Action:** Update timeline table formatter to show both session_total and conversation_total:

1. Locate timeline-specific formatting logic
2. Update token display column to show format: "Session: X | Conv: Y" when both values present

**Reference:** Discovery line 48 (show both with labels)
**Verify:** Run `claude-code-sessions timeline list --session-id <id> --output-format table` - should show both totals

### Step 18: Add --conversation-id Filter to tool_calls list Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/tool_calls.py`
**Action:** Add conversation_id parameter and filtering (same pattern as timeline):

1. Add parameter with validation
2. Add filtering logic after session_id filter

**Reference:** Research lines 227-250 (command option pattern)
**Verify:** Run `claude-code-sessions tool-calls list --session-id <id> --conversation-id conversation-1` - should filter

### Step 19: Add --conversation-id Filter to todos list Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/todos.py`
**Action:** Add conversation_id parameter and filtering (same pattern as timeline)

**Reference:** Same pattern as previous steps
**Verify:** Run `claude-code-sessions todos list --session-id <id> --conversation-id conversation-1` - should filter

### Step 20: Add --conversation-id Filter to skills list Command
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/skills.py`
**Action:** Add conversation_id parameter and filtering (same pattern as timeline)

**Reference:** Same pattern as previous steps
**Verify:** Run `claude-code-sessions skills list --session-id <id> --conversation-id conversation-1` - should filter

### CHECKPOINT: Verify All Filters Work
**Run:** Test each command with --conversation-id filter on a known multi-conversation session
**Expected:** All commands properly filter by conversation, show error when conversation not found

### Step 21: Update sessions list Command Display
**File:** `<cli-tools-root>/claude-code-sessions/src/claude_code_sessions/commands/sessions.py`
**Action:** Verify that sessions list shows conversation_count and current_conversation_id in JSON output (should already work with model changes)

**Reference:** Discovery line 51 (keep current behavior - total session tokens)
**Verify:** Run `claude-code-sessions sessions list --output-format json | jq '.[0] | {session_id, conversation_count, total_input_tokens}'` - should show conversation_count

### Step 22: Integration Test with Existing Session
**File:** N/A (testing step)
**Action:** Test full workflow with an existing multi-conversation session:

1. Identify a session with /clear command (creates conversation boundary)
2. Run `claude-code-sessions sessions get <session-id> --output-format json | jq '.conversation_count'`
3. Run `claude-code-sessions conversations list --session-id <session-id>`
4. Run `claude-code-sessions timeline list --session-id <session-id> --conversation-id conversation-1`
5. Verify token totals are accurate per conversation

**Reference:** Discovery line 107 (use existing sessions for testing)
**Verify:** All commands return expected results with proper conversation boundaries and token attribution

## Testing Strategy

### Unit Testing
1. **test_detect_conversation_boundaries()** - Test conversation detection with various parent_uuid patterns:
   - Single conversation (no breaks)
   - Multiple conversations (broken chains)
   - Conversations with /clear command boundaries

2. **test_parse_conversation_summaries()** - Test conversation summary parsing:
   - Token accumulation per conversation
   - Message counts per conversation
   - Timestamp tracking

3. **test_conversation_token_attribution()** - Test token tracking in extract_timeline_from_session():
   - conversation_total resets at boundaries
   - session_total continues cumulative
   - turn_cost deduplication works correctly

### Integration Testing
1. Test with real session files (per user requirement)
2. Verify conversation boundaries match expected /clear points
3. Verify token totals sum correctly (conversation totals should sum to session total)
4. Test filtering with --conversation-id across all commands

### Edge Case Testing
1. Session with single conversation (conversation_count = 1)
2. Session with many conversations (10+ /clear commands)
3. Empty session files
4. Sessions with only system messages
5. Filtering by non-existent conversation ID (should error)

## What's NOT Included
- **JSONL schema changes** - conversation_id computed during parsing, not stored in files
- **Backfilling existing data** - conversation detection happens on-the-fly
- **Conversation renaming/merging** - conversations identified by sequence only
- **Subagent conversation tracking** - subagents tracked separately (per requirement)
- **Conversation-level caching** - cache tokens tracked at session level only
- **UI/visualization** - CLI output only, no graphical representation

## Success Criteria
- [ ] SessionSummary model includes conversation_count and current_conversation_id fields
- [ ] TimelineEntry model includes conversation_id and conversation_total fields
- [ ] Message model includes conversation_id field
- [ ] parse_session_summary() correctly detects conversation boundaries and populates new fields
- [ ] extract_timeline_from_session() tracks both session_total and conversation_total
- [ ] sessions list command shows conversation_count in JSON output
- [ ] conversations list command works and shows per-conversation token totals
- [ ] timeline list/consolidated/get commands accept --conversation-id filter
- [ ] --conversation-id requires --session-id (error if used alone)
- [ ] Error message shown when filtering by non-existent conversation
- [ ] All commands include conversation_id in JSON output
- [ ] Table formatter shows "Session: X | Conv: Y" format for timeline
- [ ] Token totals accurate: sum of conversation totals equals session total
- [ ] tool_calls, todos, skills commands support --conversation-id filter
- [ ] Subagent tokens tracked separately (not affected by conversation boundaries)
- [ ] Integration tests pass with existing session files
