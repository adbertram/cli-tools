"""Parse playwright page snapshot YAML to extract ServiceNow data.

The base implementations are loaded from preserved bytecode. The ticket
*detail-page* parsers (`extract_ticket_detail`, `extract_comments`,
`_extract_single_comment`) are overridden below with source maintained against
the live Employee Center detail-page accessibility tree, which nests labels and
values differently than the older snapshot format the bytecode targeted.

The list/catalog/search/form parsers in the bytecode remain authoritative and
are not changed here.
"""

import re
from typing import Dict, List, Optional

from ._bytecode import load_module_bytecode

load_module_bytecode(__name__, globals())


# ---------------------------------------------------------------------------
# Detail-page parsers (validated against the live ESC ticket detail aria tree).
#
# The aria snapshot emits each label as e.g. ``- text [ref=eN]: State`` with an
# immediate deeper-indented duplicate echo line, and the value in a following
# sibling carrier (``- time "<exact>" [ref]``, ``- link "<name>" [ref]``, or a
# nested ``- text [ref]: <value>``). A field's value lives within the enclosing
# field-group block, which sits one indent level above the label's paragraph.
# ---------------------------------------------------------------------------

_INDENT_RE = re.compile(r"^(\s*)-\s")
_LABEL_RE = re.compile(r"^\s*-\s+(?:text|paragraph)(?:\s+\[ref=\w+\])?:\s*(.+?)\s*$")
_TEXT_VAL_RE = re.compile(r"^\s*-\s+text(?:\s+\[ref=\w+\])?:\s*(.+?)\s*$")
_GENERIC_VAL_RE = re.compile(r"^\s*-\s+generic\s+\[ref=\w+\]:\s*(.+?)\s*$")
_TIME_RE = re.compile(r'^\s*-\s+time\s+"([^"]*)"\s*\[ref=\w+\]')
_LINK_RE = re.compile(r'^\s*-\s+link\s+"(.+?)"\s+\[ref=\w+\]')
_HEADING_RE = re.compile(r'^\s*-\s+heading\s+"(.+?)"\s+\[ref=\w+\]')
_PARAGRAPH_RE = re.compile(r"^\s*-\s+paragraph(?:\s+\[ref=\w+\])?:")
_LISTITEM_RE = re.compile(r'^\s*-\s+listitem(\s|"|$)')
_SYSID_RE = re.compile(r"\?id=ticket&table=sc_req_item&sys_id=([a-f0-9]+)")
_APPROVAL_RE = re.compile(r"(Request is .+)")
_ADD_CONTACTS_RE = re.compile(r'^\s*-\s+heading\s+"Add contacts"\s+\[ref=\w+\]')
# Each existing contact is named by its "Remove <Name>" button. A leading
# zero-width control glyph (the icon) may precede "Remove".
_REMOVE_CONTACT_RE = re.compile(r'^\s*-\s+button\s+"[^"]*?Remove\s+(.+?)"\s+\[ref=\w+\]')

_DETAIL_LABELS = {
    "Number": "number",
    "Created": "created",
    "Updated": "updated",
    "State": "state",
    "Requested for": "requested_for",
    "Assignment group": "assignment_group",
    "Assigned to": "assigned_to",
    "Priority": "priority",
}
_ALL_LABEL_TEXTS = set(_DETAIL_LABELS)
_PERSON_LABELS = {"requested_for", "assigned_to"}
_DATE_LABELS = {"created", "updated"}
_COMMENT_TYPES = ("Additional comments", "Work notes", "Customer")


def _indent(line: str) -> int:
    """Return the indent depth of a snapshot element line, or -1 if not one."""
    m = _INDENT_RE.match(line)
    return len(m.group(1)) if m else -1


def _is_text_echo(lines: List[str], j: int) -> bool:
    """True when line ``j`` is a duplicate child echo of the text line above it.

    The aria tree renders a parent ``- text [ref]: X`` followed by a deeper
    ``- text [ref]: X`` with identical content. Keep the parent, drop the child.
    """
    if j == 0:
        return False
    cur = _TEXT_VAL_RE.match(lines[j])
    prev = _TEXT_VAL_RE.match(lines[j - 1])
    if cur and prev and cur.group(1).strip() == prev.group(1).strip():
        return _indent(lines[j]) > _indent(lines[j - 1])
    return False


def _value_after_label(lines: List[str], label_idx: int, key: str) -> Optional[str]:
    """Find the value for a detail label by scanning its enclosing field block."""
    label_indent = _indent(lines[label_idx])
    label_text = _LABEL_RE.match(lines[label_idx]).group(1).strip()
    boundary = label_indent - 4
    window_end = min(label_idx + 14, len(lines))
    for j in range(label_idx + 1, window_end):
        line = lines[j]
        ind = _indent(line)
        if ind != -1 and ind <= boundary:
            break
        other = _LABEL_RE.match(line)
        if other:
            other_text = other.group(1).strip()
            if other_text in _ALL_LABEL_TEXTS and other_text != label_text:
                break
        if key in _DATE_LABELS:
            tm = _TIME_RE.match(line)
            if tm:
                return tm.group(1).strip()
        if key in _PERSON_LABELS:
            km = _LINK_RE.match(line)
            if km:
                name = km.group(1).strip()
                if name.startswith(label_text):
                    name = name[len(label_text):].strip()
                if name:
                    return name
        if _is_text_echo(lines, j):
            continue
        vm = _TEXT_VAL_RE.match(line) or _GENERIC_VAL_RE.match(line)
        if vm:
            val = vm.group(1).strip()
            if val and val != label_text and val not in _COMMENT_TYPES:
                return val
    return None


def extract_ticket_detail(snapshot_text: str) -> Dict:
    """Extract ticket detail fields from a ticket detail page snapshot."""
    detail: Dict = {}
    lines = snapshot_text.split("\n")
    for i, line in enumerate(lines):
        lm = _LABEL_RE.match(line)
        if lm:
            label = lm.group(1).strip()
            if label in _DETAIL_LABELS and _DETAIL_LABELS[label] not in detail:
                key = _DETAIL_LABELS[label]
                val = _value_after_label(lines, i, key)
                if val:
                    detail[key] = val
                continue

        hm = _HEADING_RE.match(line)
        if hm and "description" not in detail:
            text = hm.group(1).strip()
            if not text.startswith("My Request"):
                detail["description"] = text

        if "Request is approved" in line or "Request is waiting for approval" in line:
            am = _APPROVAL_RE.search(line)
            if am:
                detail["approval_status"] = am.group(1).strip()

        sm = _SYSID_RE.search(line)
        if sm and "sys_id" not in detail:
            detail["sys_id"] = sm.group(1)

    contacts = _extract_contacts(lines)
    if contacts:
        detail["contacts"] = contacts

    return detail


def _extract_contacts(lines: List[str]) -> List[str]:
    """Extract the existing contact names from the "Add contacts" section.

    Each current contact has a ``button "… Remove <Name>"`` control; the name is
    the most reliable carrier in the accessibility tree.
    """
    contacts: List[str] = []
    in_section = False
    section_indent = None
    for line in lines:
        if _ADD_CONTACTS_RE.match(line):
            in_section = True
            section_indent = _indent(line)
            continue
        if in_section:
            ind = _indent(line)
            if ind != -1 and ind <= section_indent - 2:
                break
            rm = _REMOVE_CONTACT_RE.match(line)
            if rm:
                name = rm.group(1).strip()
                if name and name not in contacts:
                    contacts.append(name)
    return contacts


def extract_comments(snapshot_text: str) -> List[Dict]:
    """Extract comments/activity from a ticket detail page snapshot.

    Activity items live in the ``list "Ticket history"`` block; each top-level
    ``listitem`` is one entry with an author, exact timestamp, comment type, and
    body. System rows (ticket creation, "Start") and contentless rows are
    skipped.
    """
    lines = snapshot_text.split("\n")
    start = None
    hist_indent = None
    for i, line in enumerate(lines):
        if 'list "Ticket history"' in line:
            start = i
            hist_indent = _indent(line)
            break
    if start is None:
        return []

    items: List[int] = []
    for i in range(start + 1, len(lines)):
        ind = _indent(lines[i])
        if ind == -1:
            continue
        if ind <= hist_indent:
            break
        if ind == hist_indent + 2 and _LISTITEM_RE.match(lines[i]):
            items.append(i)

    comments: List[Dict] = []
    for idx, s in enumerate(items):
        end = items[idx + 1] if idx + 1 < len(items) else len(lines)
        comment = _extract_single_comment(lines, s, end)
        if comment:
            comments.append(comment)
    return comments


def _extract_single_comment(lines: List[str], start: int, end: int) -> Optional[Dict]:
    """Extract a single comment from a ``listitem`` block (lines[start:end])."""
    author: Optional[str] = None
    timestamp: Optional[str] = None
    ctype = ""
    body_parts: List[str] = []
    in_paragraph = False
    para_indent = None
    body_text_indent = None

    for j in range(start, end):
        line = lines[j]
        ind = _indent(line)

        tm = _TIME_RE.match(line)
        if tm:
            if timestamp is None:
                timestamp = tm.group(1).strip()
            in_paragraph = False
            continue

        if _PARAGRAPH_RE.match(line):
            in_paragraph = True
            para_indent = ind
            body_text_indent = None
            continue

        if in_paragraph:
            if ind != -1 and ind <= para_indent:
                in_paragraph = False
            else:
                btext = _TEXT_VAL_RE.match(line)
                if btext:
                    # Only keep text at the shallowest level in the paragraph;
                    # deeper text nodes are word-wrap fragments / echoes of the
                    # parent text and would duplicate the body.
                    if body_text_indent is None:
                        body_text_indent = ind
                    if ind == body_text_indent:
                        body_parts.append(btext.group(1).strip())
                continue

        # Header zone (before the timestamp): the author display name is the
        # text node that sits next to the timestamp. Avatar initials appear
        # earlier under an image node; the real name is captured as the last
        # header text seen before the timestamp.
        tv = _TEXT_VAL_RE.match(line)
        if tv:
            val = tv.group(1).strip()
            if val in _COMMENT_TYPES:
                ctype = val
                continue
            if _is_text_echo(lines, j):
                continue
            if timestamp is None:
                author = val

    if author in (None, "Start"):
        return None
    text = "\n".join(body_parts).strip()
    if not text and not ctype:
        return None
    if not ctype and text.endswith("Created"):
        return None
    return {
        "author": author,
        "timestamp": timestamp or "",
        "type": ctype,
        "text": text,
    }
