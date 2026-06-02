"""SQLite database access for iMessage and Contacts."""
import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

# Apple epoch offset (seconds between Unix epoch 1970 and Apple epoch 2001)
APPLE_EPOCH_OFFSET = 978307200

# chat.db stores dates in nanoseconds since 2001-01-01
NANOSECONDS = 1_000_000_000


class DatabaseError(Exception):
    """Error accessing database."""
    pass


class MessageDB:
    """Read-only access to iMessage chat.db."""

    DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

    def __init__(self):
        if not os.path.exists(self.DB_PATH):
            raise DatabaseError(f"iMessage database not found at {self.DB_PATH}")

    def _connect(self) -> sqlite3.Connection:
        """Create a read-only connection."""
        try:
            uri = f"file:{self.DB_PATH}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as e:
            raise DatabaseError(
                f"Cannot open iMessage database: {e}. "
                "Grant Full Disk Access to your terminal in System Settings > Privacy & Security > Full Disk Access"
            )

    def _apple_date_to_iso(self, apple_date: Optional[int]) -> Optional[str]:
        """Convert Apple epoch nanoseconds to ISO datetime string."""
        if apple_date is None or apple_date == 0:
            return None
        try:
            unix_timestamp = (apple_date / NANOSECONDS) + APPLE_EPOCH_OFFSET
            dt = datetime.fromtimestamp(unix_timestamp)
            return dt.isoformat()
        except (OSError, ValueError, OverflowError):
            return None

    def _extract_text_from_attributed_body(self, blob: Optional[bytes]) -> Optional[str]:
        """Extract plain text from attributedBody blob (newer macOS)."""
        if blob is None:
            return None
        try:
            # The text is stored as a UTF-8 string within the blob
            # Common pattern: look for the text between known markers
            blob_str = blob.decode("utf-8", errors="replace")
            # Find text after "NSString" marker and before null bytes
            # Pattern: text starts after first readable section
            import re
            # Try to find readable text - attributedBody has the text embedded
            # The format is: streamtyped data with NSAttributedString
            # Text appears after \x01+ and before \x86 or similar markers
            matches = re.findall(r'[\x20-\x7e\xa0-\xff]{2,}', blob_str)
            if matches:
                # The longest match is usually the actual message text
                # Filter out common false positives
                filtered = [m for m in matches if not m.startswith(('NSNumber', 'NSDictionary', 'NSString', 'NSMutable', 'NSObject', 'NSAttributed', 'NSNull', 'NSValue', 'NSData', '__k'))]
                if filtered:
                    return max(filtered, key=len)
            return None
        except Exception:
            return None

    def get_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent conversations with latest message preview."""
        conn = self._connect()
        try:
            query = """
                SELECT
                    c.ROWID as id,
                    c.guid as guid,
                    c.chat_identifier as chat_identifier,
                    c.display_name as display_name,
                    c.service_name as service,
                    h.id as handle_id,
                    m.text as last_message_text,
                    m.attributedBody as last_message_body,
                    m.date as last_message_date,
                    m.is_from_me as last_message_is_from_me,
                    m.is_read as is_read
                FROM chat c
                LEFT JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
                LEFT JOIN handle h ON chj.handle_id = h.ROWID
                LEFT JOIN (
                    SELECT cmj.chat_id, m2.*
                    FROM chat_message_join cmj
                    JOIN message m2 ON cmj.message_id = m2.ROWID
                    WHERE m2.ROWID IN (
                        SELECT MAX(m3.ROWID)
                        FROM chat_message_join cmj2
                        JOIN message m3 ON cmj2.message_id = m3.ROWID
                        GROUP BY cmj2.chat_id
                    )
                ) m ON c.ROWID = m.chat_id
                ORDER BY m.date DESC NULLS LAST
                LIMIT ?
            """
            cursor = conn.execute(query, (limit,))
            rows = cursor.fetchall()

            conversations = []
            for row in rows:
                text = row["last_message_text"]
                if text is None and row["last_message_body"] is not None:
                    text = self._extract_text_from_attributed_body(row["last_message_body"])

                conversations.append({
                    "id": str(row["id"]),
                    "guid": row["guid"],
                    "chat_identifier": row["chat_identifier"],
                    "display_name": row["display_name"] or row["handle_id"] or row["chat_identifier"],
                    "handle_id": row["handle_id"],
                    "service": row["service"] or "iMessage",
                    "last_message_text": text,
                    "last_message_date": self._apple_date_to_iso(row["last_message_date"]),
                    "last_message_is_from_me": bool(row["last_message_is_from_me"]) if row["last_message_is_from_me"] is not None else None,
                    "is_read": bool(row["is_read"]) if row["is_read"] is not None else None,
                })

            return conversations
        finally:
            conn.close()

    def get_conversation(self, conversation_id: str, message_limit: int = 50) -> Dict[str, Any]:
        """Get a conversation with its recent messages."""
        conn = self._connect()
        try:
            # Get conversation info
            chat_query = """
                SELECT
                    c.ROWID as id,
                    c.guid as guid,
                    c.chat_identifier as chat_identifier,
                    c.display_name as display_name,
                    c.service_name as service
                FROM chat c
                WHERE c.ROWID = ?
            """
            chat_row = conn.execute(chat_query, (int(conversation_id),)).fetchone()
            if not chat_row:
                raise DatabaseError(f"Conversation {conversation_id} not found")

            # Get messages for this conversation
            msg_query = f"""
                SELECT
                    m.ROWID as id,
                    m.guid as guid,
                    m.text as text,
                    m.attributedBody as attributed_body,
                    m.date as date,
                    m.is_from_me as is_from_me,
                    m.is_read as is_read,
                    m.service as service,
                    m.cache_has_attachments as has_attachment,
                    h.id as handle_id,
                    a.mime_type as mime_type,
                    a.filename as attachment_filename
                FROM message m
                JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                {self._attachment_fields()}
                WHERE cmj.chat_id = ?
                ORDER BY m.date DESC
                LIMIT ?
            """
            msg_rows = conn.execute(msg_query, (int(conversation_id), message_limit)).fetchall()

            messages = []
            for row in msg_rows:
                messages.append(self._build_message(row))

            return {
                "id": str(chat_row["id"]),
                "guid": chat_row["guid"],
                "chat_identifier": chat_row["chat_identifier"],
                "display_name": chat_row["display_name"] or chat_row["chat_identifier"],
                "service": chat_row["service"] or "iMessage",
                "messages": list(reversed(messages)),  # chronological order
                "message_count": len(messages),
            }
        finally:
            conn.close()

    def _attachment_fields(self) -> str:
        """SQL fragment for attachment columns via LEFT JOIN."""
        return """
                    LEFT JOIN message_attachment_join maj ON m.ROWID = maj.message_id
                    LEFT JOIN attachment a ON maj.attachment_id = a.ROWID
        """

    def _build_message(self, row) -> Dict[str, Any]:
        """Build a message dict from a database row."""
        text = row["text"]
        if text is None and row["attributed_body"] is not None:
            text = self._extract_text_from_attributed_body(row["attributed_body"])

        msg = {
            "id": str(row["id"]),
            "guid": row["guid"],
            "text": text,
            "date": self._apple_date_to_iso(row["date"]),
            "is_from_me": bool(row["is_from_me"]),
            "is_read": bool(row["is_read"]) if row["is_read"] is not None else None,
            "service": row["service"],
            "has_attachment": bool(row["has_attachment"]),
            "handle_id": row["handle_id"],
            "mime_type": row["mime_type"],
            "attachment_filename": row["attachment_filename"],
        }
        return msg

    def get_messages(self, limit: int = 50, handle_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent messages, optionally filtered by handle (contact).

        When filtering by contact, uses chat_message_join to find ALL messages
        in conversations with that contact. This catches sent messages (is_from_me=1)
        that have handle_id=0 and would be missed by a handle-only JOIN.
        """
        conn = self._connect()
        try:
            limit_clause = "LIMIT ?" if limit > 0 else ""
            attachment_join = self._attachment_fields()
            if handle_filter:
                query = f"""
                    SELECT
                        m.ROWID as id,
                        m.guid as guid,
                        m.text as text,
                        m.attributedBody as attributed_body,
                        m.date as date,
                        m.is_from_me as is_from_me,
                        m.is_read as is_read,
                        m.service as service,
                        m.cache_has_attachments as has_attachment,
                        h.id as handle_id,
                        a.mime_type as mime_type,
                        a.filename as attachment_filename
                    FROM message m
                    JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                    JOIN chat c ON cmj.chat_id = c.ROWID
                    LEFT JOIN handle h ON m.handle_id = h.ROWID
                    {attachment_join}
                    WHERE c.chat_identifier LIKE ?
                    GROUP BY m.ROWID
                    ORDER BY m.date DESC
                    {limit_clause}
                """
                params = (f"%{handle_filter}%", limit) if limit > 0 else (f"%{handle_filter}%",)
                cursor = conn.execute(query, params)
            else:
                query = f"""
                    SELECT
                        m.ROWID as id,
                        m.guid as guid,
                        m.text as text,
                        m.attributedBody as attributed_body,
                        m.date as date,
                        m.is_from_me as is_from_me,
                        m.is_read as is_read,
                        m.service as service,
                        m.cache_has_attachments as has_attachment,
                        h.id as handle_id,
                        a.mime_type as mime_type,
                        a.filename as attachment_filename
                    FROM message m
                    LEFT JOIN handle h ON m.handle_id = h.ROWID
                    {attachment_join}
                    ORDER BY m.date DESC
                    {limit_clause}
                """
                params = (limit,) if limit > 0 else ()
                cursor = conn.execute(query, params)

            rows = cursor.fetchall()
            messages = []
            for row in rows:
                messages.append(self._build_message(row))

            return messages
        finally:
            conn.close()

    def get_message(self, message_id: str) -> Dict[str, Any]:
        """Get a specific message by ROWID."""
        conn = self._connect()
        try:
            query = f"""
                SELECT
                    m.ROWID as id,
                    m.guid as guid,
                    m.text as text,
                    m.attributedBody as attributed_body,
                    m.date as date,
                    m.is_from_me as is_from_me,
                    m.is_read as is_read,
                    m.service as service,
                    m.cache_has_attachments as has_attachment,
                    m.date_read as date_read,
                    m.date_delivered as date_delivered,
                    m.associated_message_type as associated_message_type,
                    h.id as handle_id,
                    a.mime_type as mime_type,
                    a.filename as attachment_filename
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                {self._attachment_fields()}
                WHERE m.ROWID = ?
            """
            row = conn.execute(query, (int(message_id),)).fetchone()
            if not row:
                raise DatabaseError(f"Message {message_id} not found")

            msg = self._build_message(row)
            msg["date_read"] = self._apple_date_to_iso(row["date_read"])
            msg["date_delivered"] = self._apple_date_to_iso(row["date_delivered"])
            msg["associated_message_type"] = row["associated_message_type"]
            return msg
        finally:
            conn.close()

    def is_accessible(self) -> bool:
        """Check if the database is readable."""
        try:
            conn = self._connect()
            conn.execute("SELECT 1 FROM message LIMIT 1")
            conn.close()
            return True
        except (DatabaseError, sqlite3.OperationalError):
            return False
