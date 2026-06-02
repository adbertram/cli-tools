"""iMessage client using SQLite for reads and AppleScript for writes."""
import re
import platform
from typing import Dict, List, Optional, Any

from .config import get_config
from .db import MessageDB, DatabaseError
from .applescript import run_applescript, escape_applescript_string, AppleScriptError
from .models import (
    Contact,
    Conversation,
    ConversationDetail,
    Message,
    MessageDetail,
    SendResult,
    AuthStatus,
    create_contact,
    create_conversation,
    create_conversation_detail,
    create_message,
    create_message_detail,
    create_send_result,
    create_auth_status,
)


class ClientError(Exception):
    """Custom exception for iMessage client errors."""
    pass


class ImessageClient:
    """iMessage client - SQLite for reads, AppleScript for writes."""

    def __init__(self):
        self.config = get_config()
        self._db: Optional[MessageDB] = None

    @property
    def db(self) -> MessageDB:
        if self._db is None:
            try:
                self._db = MessageDB()
            except DatabaseError as e:
                raise ClientError(str(e))
        return self._db

    def _detect_recipient_type(self, recipient: str) -> str:
        """Auto-detect if recipient is phone number or email."""
        # Strip whitespace
        recipient = recipient.strip()
        # Phone number patterns
        if re.match(r'^[\+]?[\d\s\-\(\)\.]+$', recipient) and len(re.sub(r'[^\d]', '', recipient)) >= 7:
            return "phone"
        # Email pattern
        if '@' in recipient:
            return "email"
        # Default to phone
        return "phone"

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number for AppleScript."""
        # Strip all non-digit chars except leading +
        digits = re.sub(r'[^\d+]', '', phone)
        if not digits.startswith('+') and len(digits) == 10:
            digits = '+1' + digits  # Assume US
        return digits

    # ==================== Auth Methods ====================

    def auth_status(self) -> AuthStatus:
        """Check system status: Messages app, database, contacts access."""
        messages_available = False
        db_accessible = False
        contacts_accessible = False
        macos_version = None

        # Check macOS version
        try:
            macos_version = platform.mac_ver()[0]
        except Exception:
            pass

        # Check Messages app availability
        try:
            result = run_applescript('tell application "System Events" to return (name of processes) contains "Messages"')
            messages_available = True  # If osascript works, Messages scripting is available
        except AppleScriptError:
            pass

        # Check database access
        try:
            db_accessible = self.db.is_accessible()
        except (ClientError, DatabaseError):
            pass

        # Check contacts access via AppleScript
        try:
            run_applescript('tell application "Contacts" to return count of people')
            contacts_accessible = True
        except AppleScriptError:
            pass

        authenticated = db_accessible  # Primary requirement

        return create_auth_status({
            "authenticated": authenticated,
            "messages_app_available": messages_available,
            "messages_db_accessible": db_accessible,
            "contacts_accessible": contacts_accessible,
            "macos_version": macos_version,
        })

    def auth_login(self, **kwargs) -> Dict[str, Any]:
        """Open System Settings for granting permissions."""
        try:
            run_applescript(
                'tell application "System Settings" to activate'
            )
            return {
                "success": True,
                "message": "System Settings opened. Grant Full Disk Access to your terminal app for database access.",
            }
        except AppleScriptError as e:
            return {
                "success": False,
                "message": f"Failed to open System Settings: {e}",
            }

    def auth_logout(self) -> Dict[str, Any]:
        """No-op for iMessage (no session to clear)."""
        return {
            "success": True,
            "message": "No session to clear (iMessage uses system-level access).",
        }

    # ==================== Contact Methods ====================

    def list_contacts(self, limit: int = 100) -> List[Contact]:
        """List contacts from macOS Contacts app via AppleScript."""
        try:
            script = f'''
                tell application "Contacts"
                    set output to ""
                    set totalPeople to count of people
                    set maxPeople to {limit}
                    if totalPeople < maxPeople then
                        set maxPeople to totalPeople
                    end if
                    if maxPeople > 0 then
                        set personList to people 1 thru maxPeople
                    else
                        set personList to {{}}
                    end if
                    repeat with p in personList
                        set personId to id of p
                        set personName to name of p
                        set phoneList to ""
                        repeat with ph in phones of p
                            set phoneList to phoneList & value of ph & "|"
                        end repeat
                        set emailList to ""
                        repeat with em in emails of p
                            set emailList to emailList & value of em & "|"
                        end repeat
                        set orgName to ""
                        try
                            set orgName to organization of p
                        end try
                        set output to output & personId & "\\t" & personName & "\\t" & phoneList & "\\t" & emailList & "\\t" & orgName & "\\n"
                    end repeat
                    return output
                end tell
            '''
            result = run_applescript(script, timeout=60)

            contacts = []
            for line in result.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 5:
                    contact_id = parts[0].strip()
                    name = parts[1].strip()
                    phones = [p.strip() for p in parts[2].split("|") if p.strip()]
                    emails = [e.strip() for e in parts[3].split("|") if e.strip()]
                    org = parts[4].strip() if parts[4].strip() else None

                    # Split name into first/last
                    name_parts = name.split(" ", 1)
                    first_name = name_parts[0] if name_parts else name
                    last_name = name_parts[1] if len(name_parts) > 1 else None

                    contacts.append(create_contact({
                        "id": contact_id,
                        "name": name,
                        "first_name": first_name,
                        "last_name": last_name,
                        "phones": phones,
                        "emails": emails,
                        "organization": org,
                    }))

            return contacts
        except AppleScriptError as e:
            raise ClientError(f"Failed to list contacts: {e}")

    def get_contact(self, contact_id: str) -> Contact:
        """Get a specific contact by ID."""
        try:
            escaped_id = escape_applescript_string(contact_id)
            script = f'''
                tell application "Contacts"
                    set p to first person whose id is "{escaped_id}"
                    set personId to id of p
                    set personName to name of p
                    set phoneList to ""
                    repeat with ph in phones of p
                        set phoneList to phoneList & value of ph & "|"
                    end repeat
                    set emailList to ""
                    repeat with em in emails of p
                        set emailList to emailList & value of em & "|"
                    end repeat
                    set orgName to ""
                    try
                        set orgName to organization of p
                    end try
                    return personId & "\\t" & personName & "\\t" & phoneList & "\\t" & emailList & "\\t" & orgName
                end tell
            '''
            result = run_applescript(script, timeout=30)
            parts = result.split("\t")
            if len(parts) < 5:
                raise ClientError(f"Unexpected contact data format")

            name = parts[1].strip()
            name_parts = name.split(" ", 1)

            return create_contact({
                "id": parts[0].strip(),
                "name": name,
                "first_name": name_parts[0] if name_parts else name,
                "last_name": name_parts[1] if len(name_parts) > 1 else None,
                "phones": [p.strip() for p in parts[2].split("|") if p.strip()],
                "emails": [e.strip() for e in parts[3].split("|") if e.strip()],
                "organization": parts[4].strip() if parts[4].strip() else None,
            })
        except AppleScriptError as e:
            raise ClientError(f"Failed to get contact: {e}")

    # ==================== Conversation Methods ====================

    def list_conversations(self, limit: int = 50) -> List[Conversation]:
        """List recent conversations from chat.db."""
        try:
            raw = self.db.get_conversations(limit=limit)
            return [create_conversation(c) for c in raw]
        except DatabaseError as e:
            raise ClientError(str(e))

    def get_conversation(self, conversation_id: str, message_limit: int = 50) -> ConversationDetail:
        """Get conversation with messages."""
        try:
            raw = self.db.get_conversation(conversation_id, message_limit=message_limit)
            return create_conversation_detail(raw)
        except DatabaseError as e:
            raise ClientError(str(e))

    # ==================== Message Methods ====================

    def list_messages(self, limit: int = 50, contact: Optional[str] = None) -> List[Message]:
        """List recent messages, optionally filtered by contact."""
        try:
            raw = self.db.get_messages(limit=limit, handle_filter=contact)
            return [create_message(m) for m in raw]
        except DatabaseError as e:
            raise ClientError(str(e))

    def get_message(self, message_id: str) -> MessageDetail:
        """Get a specific message by ID."""
        try:
            raw = self.db.get_message(message_id)
            return create_message_detail(raw)
        except DatabaseError as e:
            raise ClientError(str(e))

    def send_message(self, recipient: str, text: str) -> SendResult:
        """Send a message via AppleScript."""
        recipient_type = self._detect_recipient_type(recipient)

        if recipient_type == "phone":
            normalized = self._normalize_phone(recipient)
        else:
            normalized = recipient.strip()

        escaped_text = escape_applescript_string(text)
        escaped_recipient = escape_applescript_string(normalized)

        script = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{escaped_recipient}" of targetService
                send "{escaped_text}" to targetBuddy
            end tell
        '''
        try:
            run_applescript(script, timeout=30)
            return create_send_result({
                "success": True,
                "recipient": normalized,
                "message": text,
                "service": "iMessage",
            })
        except AppleScriptError as e:
            raise ClientError(f"Failed to send message to {recipient}: {e}")


# Singleton
_client: Optional[ImessageClient] = None


def get_client() -> ImessageClient:
    global _client
    if _client is None:
        _client = ImessageClient()
    return _client
