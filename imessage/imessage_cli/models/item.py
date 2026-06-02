"""iMessage CLI models."""
from enum import Enum
from typing import List, Optional
from pydantic import Field
from .base import CLIModel


class MessageService(str, Enum):
    """Message service type."""
    IMESSAGE = "iMessage"
    SMS = "SMS"


class Contact(CLIModel):
    """Contact from macOS Contacts app."""
    id: str = Field(frozen=True)
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phones: List[str] = []
    emails: List[str] = []
    organization: Optional[str] = None


class Conversation(CLIModel):
    """iMessage conversation (chat)."""
    id: str = Field(frozen=True)
    guid: Optional[str] = None
    chat_identifier: Optional[str] = None
    display_name: str
    handle_id: Optional[str] = None
    service: str = "iMessage"
    last_message_text: Optional[str] = None
    last_message_date: Optional[str] = None
    last_message_is_from_me: Optional[bool] = None
    is_read: Optional[bool] = None


class ConversationDetail(CLIModel):
    """Conversation with messages."""
    id: str = Field(frozen=True)
    guid: Optional[str] = None
    chat_identifier: Optional[str] = None
    display_name: str
    service: str = "iMessage"
    messages: List[dict] = []
    message_count: int = 0


class Message(CLIModel):
    """iMessage message."""
    id: str = Field(frozen=True)
    guid: Optional[str] = None
    text: Optional[str] = None
    date: Optional[str] = None
    is_from_me: bool = False
    is_read: Optional[bool] = None
    service: Optional[str] = None
    has_attachment: bool = False
    handle_id: Optional[str] = None
    mime_type: Optional[str] = None
    attachment_filename: Optional[str] = None


class MessageDetail(CLIModel):
    """Detailed message with additional fields."""
    id: str = Field(frozen=True)
    guid: Optional[str] = None
    text: Optional[str] = None
    date: Optional[str] = None
    is_from_me: bool = False
    is_read: Optional[bool] = None
    service: Optional[str] = None
    has_attachment: bool = False
    handle_id: Optional[str] = None
    mime_type: Optional[str] = None
    attachment_filename: Optional[str] = None
    date_read: Optional[str] = None
    date_delivered: Optional[str] = None
    associated_message_type: Optional[int] = None


class SendResult(CLIModel):
    """Result of sending a message."""
    success: bool
    recipient: str
    message: str
    service: Optional[str] = None


class AuthStatus(CLIModel):
    """Authentication/system status."""
    authenticated: bool
    messages_app_available: bool = False
    messages_db_accessible: bool = False
    contacts_accessible: bool = False
    macos_version: Optional[str] = None


# Factory functions
def create_contact(data: dict) -> Contact:
    return Contact(**data)

def create_conversation(data: dict) -> Conversation:
    return Conversation(**data)

def create_conversation_detail(data: dict) -> ConversationDetail:
    return ConversationDetail(**data)

def create_message(data: dict) -> Message:
    return Message(**data)

def create_message_detail(data: dict) -> MessageDetail:
    return MessageDetail(**data)

def create_send_result(data: dict) -> SendResult:
    return SendResult(**data)

def create_auth_status(data: dict) -> AuthStatus:
    return AuthStatus(**data)
