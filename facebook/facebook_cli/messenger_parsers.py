"""Parse playwright page snapshot YAML to extract Facebook Messenger data.

Parser functions for Messenger page snapshots. Patterns are determined
empirically from real snapshots. These parsers extract structured data
from the accessibility tree snapshot format used by the playwright CLI.
"""
import re
from typing import Dict, List


def extract_conversations_from_snapshot(snapshot_text: str) -> List[Dict]:
    """Extract Messenger conversations from a playwright page snapshot.

    Looks for conversation list items in the sidebar, each containing:
    - A link to /messages/t/<id>/
    - Contact name text
    - Message snippet/preview text

    Returns:
        List of dicts with keys: id, name, snippet.
    """
    conversations = []
    seen_ids = set()
    lines = snapshot_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for links to message threads: /messages/t/<id>/
        thread_match = re.search(r'/messages/t/(\d+)/', line)
        if thread_match:
            thread_id = thread_match.group(1)
            if thread_id not in seen_ids:
                # Extract name from the link text
                # Pattern: - link "Contact Name" [ref=...]:
                name = ""
                link_text_match = re.match(r'^\s*- link "(.+?)"\s+\[ref=', line)
                if link_text_match:
                    name = link_text_match.group(1)

                # Look nearby for snippet text in generic/text elements
                snippet = ""
                for j in range(i + 1, min(i + 10, len(lines))):
                    child = lines[j].strip()
                    # Stop at next link or same-level element
                    if child.startswith('- link ') or child.startswith('- /url:'):
                        break
                    # Match generic text content
                    gen_match = re.match(r'^-?\s*(?:generic|paragraph|text) \[ref=\w+\]:\s*(.+)$', child)
                    if gen_match:
                        val = gen_match.group(1).strip()
                        # Skip if it looks like a name (already captured) or timestamp
                        if val and val != name and not re.match(r'^\d+[hm]$', val):
                            snippet = val
                            break

                seen_ids.add(thread_id)
                conversations.append({
                    "id": thread_id,
                    "name": name or f"Conversation {thread_id}",
                    "snippet": snippet,
                })

        i += 1

    return conversations


def extract_messages_from_snapshot(snapshot_text: str) -> List[Dict]:
    """Extract messages from a Messenger conversation page snapshot.

    Looks for message content in the conversation view. Messages appear
    as text/paragraph elements within the message thread area.

    Returns:
        List of dicts with keys: text, sender (if identifiable).
    """
    messages = []
    lines = snapshot_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Messages in Messenger snapshots appear as text within message row elements
        # Look for patterns like: - paragraph [ref=...]: message text
        # or generic elements containing message content
        msg_match = re.match(r'^\s*-\s*(?:paragraph|text|generic)\s+\[ref=\w+\]:\s*(.+)$', line)
        if msg_match:
            text = msg_match.group(1).strip()
            # Filter out UI chrome (timestamps, reactions, navigation elements)
            if (text
                    and len(text) > 1
                    and not re.match(r'^(\d{1,2}:\d{2}\s*(AM|PM)?|Just now|\d+[hm]|Yesterday|\d+/\d+/\d+)$', text)
                    and text not in ('You', 'Seen', 'Sent', 'Delivered', 'Active now', 'Offline')
                    and not text.startswith('Reacted ')
                    and 'emoji' not in text.lower()):
                messages.append({
                    "text": text,
                })

        i += 1

    return messages
