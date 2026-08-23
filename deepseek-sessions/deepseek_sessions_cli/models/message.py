"""Message model for DeepSeek Harness sessions."""
from typing import List, Optional

from .base import CLIModel
from .tool_call import ToolCall


class Message(CLIModel):
    """A surfaced message in a session (user or assistant).

    dsh streams deltas as `text-chunks` / `reasoning-chunks` /
    `tool-call-chunks` rows and then writes one durable `assistant/message`
    holding the finished content. Only the durable messages become Message
    rows; the delta rows are ignored.
    """

    id: str
    conversation_id: Optional[int] = None
    type: str  # "user" or "assistant"
    timestamp: str
    turn: Optional[int] = None
    step: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    content: str
    reasoning: Optional[str] = None
    tool_calls: List[ToolCall] = []
