"""Parse playwright page snapshot YAML to extract ServiceNow data.

playwright page snapshot returns JSON with a 'file' key pointing to a YAML
accessibility tree. This module provides functions to extract structured data
from that YAML text.

The YAML is an accessibility tree with patterns like:
    - link "Description , RITM0352332" [ref=e123] [cursor=pointer]:
        - /url: "?id=ticket&table=sc_req_item&sys_id=abc123"
        - text: Description text
    - generic [ref=e456]: Work in Progress
"""
import re
from typing import Dict, List, Optional


def extract_tickets_from_list(snapshot_text: str) -> List[Dict]:
    """Extract tickets from the My Requests page snapshot.

    The table rows follow this pattern:
        - row "description text , RITM_NUMBER ...":
            - cell "description , RITM_NUMBER ...":
                - link "description , RITM_NUMBER" [ref=...]:
                    - /url: "?id=ticket&table=sc_req_item&sys_id=SYS_ID"
                    - text: description text
                - generic [ref=...]:
                    - generic [ref=...]: RITM_NUMBER
                    - generic [ref=...]: Requestor_Name
            - cell "State_Text" [ref=...]:
                - generic [ref=...]: State_Text
            - cell "time_ago" [ref=...]:

    Returns:
        List of dicts with keys: number, description, state, updated,
        requested_for, sys_id, url
    """
    tickets = []
    seen_ids = set()
    lines = snapshot_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for link lines that contain RITM numbers and ticket URLs
        link_match = re.match(r'^\s*- link "(.+?)"\s+\[ref=', line)
        if link_match:
            link_text = link_match.group(1)

            # Check if the next line has a ticket URL
            if i + 1 < len(lines):
                url_line = lines[i + 1]
                url_match = re.search(
                    r'\?id=ticket&table=sc_req_item&sys_id=([a-f0-9]+)',
                    url_line
                )
                if url_match:
                    sys_id = url_match.group(1)
                    if sys_id in seen_ids:
                        i += 1
                        continue
                    seen_ids.add(sys_id)

                    # Parse the link text: "description , RITM_NUMBER"
                    # The comma separates description from RITM number
                    ritm_match = re.search(r'(RITM\d+)', link_text)
                    number = ritm_match.group(1) if ritm_match else ""

                    # Description is the part before the comma+RITM
                    desc_match = re.match(r'^(.+?)\s*,\s*RITM\d+', link_text)
                    description = desc_match.group(1).strip() if desc_match else link_text.strip()

                    # Look for the text child for possibly better description
                    if i + 2 < len(lines):
                        text_line = lines[i + 2]
                        text_match = re.match(r'^\s*- text:\s*(.+)', text_line)
                        if text_match:
                            description = text_match.group(1).strip()

                    # Now scan forward for requestor name, state, and updated time
                    requested_for = None
                    state = None
                    updated = None

                    # Look in the next ~15 lines for the sibling generic/cell elements
                    for j in range(i + 1, min(i + 20, len(lines))):
                        child = lines[j]

                        # Requestor name: in a generic inside the cell, after the RITM generic
                        # Pattern: generic [ref=...]: Requestor_Name
                        # We look for generics that contain a name (not RITM, not state)
                        gen_match = re.match(
                            r'^\s*- generic \[ref=\w+\]:\s*(.+)', child
                        )
                        if gen_match:
                            val = gen_match.group(1).strip()
                            # Skip RITM numbers
                            if re.match(r'^RITM\d+$', val):
                                continue
                            # Check for state values
                            if val in (
                                "Open", "Work in Progress",
                                "Closed Complete", "Closed Incomplete",
                                "Closed Skipped",
                            ):
                                state = val
                                continue
                            # If we haven't found requestor yet and it looks like a name
                            if requested_for is None and not re.match(r'^\d', val):
                                requested_for = val

                        # State: in a cell element
                        # Pattern: - cell "State_Text" [ref=...]
                        cell_match = re.match(
                            r'^\s*- cell "(.+?)"\s+\[ref=', child
                        )
                        if cell_match:
                            cell_val = cell_match.group(1).strip()
                            if cell_val in (
                                "Open", "Work in Progress",
                                "Closed Complete", "Closed Incomplete",
                                "Closed Skipped",
                            ):
                                state = cell_val

                        # Updated time: in the last cell or in a time element
                        # Pattern: - cell "4 days ago" or - time [ref=...]: / - text: 4d ago
                        if cell_match:
                            cell_val = cell_match.group(1).strip()
                            if re.match(r'^\d+\s*\w*\s*ago$', cell_val):
                                updated = cell_val

                        # Also check time elements (ServiceNow uses <time>)
                        time_match = re.match(r'^\s*- time\s+\[ref=', child)
                        if time_match:
                            # The text is on the next line
                            if j + 1 < len(lines):
                                time_text = re.match(
                                    r'^\s*- text:\s*(.+)', lines[j + 1]
                                )
                                if time_text:
                                    updated = time_text.group(1).strip()

                        # Stop scanning if we hit another row
                        row_match = re.match(r'^\s*- row ', child)
                        if row_match and j > i + 2:
                            break

                    tickets.append({
                        "number": number,
                        "description": description,
                        "state": state,
                        "updated": updated,
                        "requested_for": requested_for,
                        "sys_id": sys_id,
                        "url": f"?id=ticket&table=sc_req_item&sys_id={sys_id}",
                    })

        i += 1

    return tickets


def extract_ticket_detail(snapshot_text: str) -> Dict:
    """Extract ticket detail from a ticket detail page snapshot.

    The detail page has key/value patterns like:
        - text: Number
        - generic [ref=...]: RITM0352332
        ...
        - text: State
        - generic [ref=...]: Work in Progress
        ...
        - heading "Title text" [level=2]
        ...
        - paragraph [ref=...]: Requested for
        - link "Requested for Person Name" [ref=...]: Person Name
        ...

    Returns:
        Dict with keys: number, description, state, created, updated,
        requested_for, assignment_group, assigned_to, priority,
        approval_status, sys_id
    """
    detail = {}
    lines = snapshot_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Number: "- text: Number" followed by "- generic [ref=...]: RITM..."
        if line == '- text: Number':
            val = _next_generic_value(lines, i)
            if val:
                detail['number'] = val

        # Created date
        elif line == '- text: Created':
            val = _next_generic_value(lines, i)
            if val:
                detail['created'] = val

        # Updated date
        elif line == '- text: Updated':
            val = _next_generic_value(lines, i)
            if val:
                detail['updated'] = val

        # State
        elif line == '- text: State':
            val = _next_generic_value(lines, i)
            if val:
                detail['state'] = val

        # Title/Description heading
        heading_match = re.match(
            r'^- heading "(.+?)"\s+\[level=2\]', line
        )
        if heading_match:
            detail['description'] = heading_match.group(1).strip()

        # Requested for: paragraph label then link with name
        if re.match(r'^- paragraph \[ref=\w+\]:\s*Requested for$', line):
            link_val = _next_link_text(lines, i)
            if link_val:
                detail['requested_for'] = link_val

        # Assignment group: paragraph label then generic with value
        if re.match(r'^- paragraph \[ref=\w+\]:\s*Assignment group$', line):
            val = _next_generic_value(lines, i)
            if val:
                # Strip surrounding quotes if present
                detail['assignment_group'] = val.strip('"')

        # Assigned to: paragraph label then link with name
        if re.match(r'^- paragraph \[ref=\w+\]:\s*Assigned to$', line):
            link_val = _next_link_text(lines, i)
            if link_val:
                detail['assigned_to'] = link_val

        # Priority: paragraph label then generic with value
        if re.match(r'^- paragraph \[ref=\w+\]:\s*Priority$', line):
            val = _next_generic_value(lines, i)
            if val:
                detail['priority'] = val

        # Approval status: look for "Request is approved" or "Request is waiting..."
        if 'Request is approved' in line or 'Request is waiting for approval' in line:
            approval_match = re.search(r'(Request is .+)', line)
            if approval_match:
                detail['approval_status'] = approval_match.group(1).strip()

        # Extract sys_id from any ticket URL on the page
        sys_match = re.search(
            r'\?id=ticket&table=sc_req_item&sys_id=([a-f0-9]+)', line
        )
        if sys_match and 'sys_id' not in detail:
            detail['sys_id'] = sys_match.group(1)

        i += 1

    return detail


def extract_comments(snapshot_text: str) -> List[Dict]:
    """Extract comments/activity from a ticket detail page snapshot.

    Activity items in the "Ticket history" list follow this pattern:
        - list "Ticket history" [ref=...]:
            - listitem [ref=...]:
                - img "Author Name ..." [ref=...]:
                - generic [ref=...]:
                    - generic [ref=...]:
                        - generic [ref=...]:
                            - text: Author Name
                            - generic [ref=...]:
                                - ...
                                - time [ref=...]:
                                    - text: 3d ago
                                - ...
                                - generic [ref=...]: Additional comments
                    - paragraph [ref=...]: The actual comment text here

    Returns:
        List of dicts with keys: author, timestamp, type, text
    """
    comments = []
    lines = snapshot_text.split('\n')

    # Find the ticket history list
    in_history = False
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect start of ticket history list
        if re.search(r'list "Ticket history"', line):
            in_history = True
            i += 1
            continue

        if in_history:
            # Each listitem is one activity entry
            if re.match(r'^\s*- listitem\s+\[ref=', line):
                comment = _extract_single_comment(lines, i)
                if comment:
                    comments.append(comment)

            # End of history list (same or lower indentation non-listitem)
            indent = len(line) - len(line.lstrip())
            if indent <= 4 and not re.match(r'^\s*- listitem', line) and line.strip() and not re.search(r'list "Ticket history"', line):
                # We may have left the list
                if not line.strip().startswith('-'):
                    in_history = False

        i += 1

    return comments


def _extract_single_comment(lines: List[str], start: int) -> Optional[Dict]:
    """Extract a single comment from a listitem block starting at start index."""
    author = None
    timestamp = None
    comment_type = None
    text = None

    # Get the indentation of the listitem to know its scope
    listitem_line = lines[start]
    listitem_indent = len(listitem_line) - len(listitem_line.lstrip())

    # First pass: find the author from the first "- text:" line that is NOT a
    # known label and is NOT a timestamp (appears after "- time").
    # The accessibility tree puts the author name as the first text child.
    found_time = False
    for j in range(start + 1, min(start + 30, len(lines))):
        child = lines[j]
        child_stripped = child.strip()
        child_indent = len(child) - len(child.lstrip())

        if child_indent <= listitem_indent and j > start + 1 and child_stripped:
            break

        if re.match(r'^\s*- time\s+\[ref=', child):
            found_time = True
            continue

        if author is None and not found_time:
            text_match = re.match(r'^\s*- text:\s*(.+)', child)
            if text_match:
                val = text_match.group(1).strip()
                if val not in ('Additional comments', 'Work notes', 'Customer'):
                    author = val

    # Second pass: extract timestamp, type, and text
    for j in range(start + 1, min(start + 30, len(lines))):
        child = lines[j]
        child_stripped = child.strip()
        child_indent = len(child) - len(child.lstrip())

        if child_indent <= listitem_indent and j > start + 1 and child_stripped:
            break

        # Timestamp from time element
        if timestamp is None:
            time_match = re.match(r'^\s*- time\s+\[ref=', child)
            if time_match:
                # The text is on the next line
                if j + 1 < len(lines):
                    time_text = re.match(
                        r'^\s*- text:\s*(.+)', lines[j + 1]
                    )
                    if time_text:
                        timestamp = time_text.group(1).strip()

        # Comment type (e.g., "Additional comments")
        gen_match = re.match(r'^\s*- generic \[ref=\w+\]:\s*(.+)', child)
        if gen_match:
            val = gen_match.group(1).strip()
            if val in ('Additional comments', 'Work notes', 'Customer'):
                comment_type = val

        # Comment text from paragraph
        para_match = re.match(r'^\s*- paragraph \[ref=\w+\]:\s*(.+)', child)
        if para_match:
            text = para_match.group(1).strip()

    if text and author:
        return {
            "author": author,
            "timestamp": timestamp or "",
            "type": comment_type,
            "text": text,
        }
    return None


def extract_catalog_items(snapshot_text: str) -> List[Dict]:
    """Extract catalog items from a topic/category page or home page snapshot.

    Catalog items appear as links whose URLs contain:
        - ?id=sc_cat_item&sys_id=...  (request forms)
        - ?id=kb_article&sysparm_article=...  (knowledge base articles)

    Before each link, a generic element may contain "Request" or "Article".
    After the link, a generic element contains the description.

    Returns:
        List of dicts with keys: name, type, description, url, sys_id
    """
    items = []
    seen_ids = set()
    lines = snapshot_text.split('\n')

    # Patterns for catalog-style URLs
    _URL_PATTERNS = [
        (re.compile(r'\?id=sc_cat_item&sys_id=([a-f0-9]+)'), 'sc_cat_item'),
        (re.compile(r'\?id=kb_article&sysparm_article=(\w+)'), 'kb_article'),
    ]

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for links to catalog items
        link_match = re.match(r'^\s*- link "(.+?)"\s+\[ref=', line)
        if link_match:
            link_text = link_match.group(1)

            # Check for catalog item URL on the next line
            if i + 1 < len(lines):
                url_line = lines[i + 1]
                item_id = None
                url_str = None

                for pattern, url_type in _URL_PATTERNS:
                    m = pattern.search(url_line)
                    if m:
                        item_id = m.group(1)
                        url_str = m.group(0)
                        break

                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)

                    name = link_text.strip()

                    # Get text child for potentially cleaner name
                    if i + 2 < len(lines):
                        text_match = re.match(
                            r'^\s*- text:\s*(.+)', lines[i + 2]
                        )
                        if text_match:
                            name = text_match.group(1).strip()

                    # Strip leading type prefix from link text (e.g. "Article How to...")
                    for prefix in ('Article ', 'Request '):
                        if name.startswith(prefix):
                            name = name[len(prefix):]
                            break

                    # Look backwards for item type (Request/Article)
                    item_type = None
                    for j in range(max(0, i - 8), i):
                        gen_match = re.match(
                            r'^\s*- generic \[ref=\w+\]:\s*(Request|Article)',
                            lines[j]
                        )
                        if gen_match:
                            item_type = gen_match.group(1)

                    # Look forward for description
                    description = None
                    for j in range(i + 2, min(i + 8, len(lines))):
                        gen_match = re.match(
                            r'^\s*- generic \[ref=\w+\]:\s*(.+)', lines[j]
                        )
                        if gen_match:
                            val = gen_match.group(1).strip()
                            if val not in ('Request', 'Article') and len(val) > 5:
                                description = val
                                break

                    items.append({
                        "name": name,
                        "type": item_type,
                        "description": description,
                        "url": url_str,
                        "sys_id": item_id,
                    })

        i += 1

    return items


def extract_home_tickets(snapshot_text: str) -> List[Dict]:
    """Extract tickets from the home page Active Items section.

    Home page tickets appear in an "Asks" tabpanel:
        - tabpanel "Asks" [ref=...]:
            - list [ref=...]:
                - listitem [ref=...]:
                    - generic [ref=...]:
                        - link "Description text with RITM_NUMBER" [ref=...]:
                            - /url: "?id=ticket&table=sc_req_item&sys_id=SYS_ID"
                            - heading "Description" [level=3]
                        - generic [ref=...]:
                            - generic [ref=...]: RITM_NUMBER
                            - generic [ref=...]: Requestor_Name

    Returns:
        List of dicts with keys: number, description, sys_id, requested_for, url
    """
    tickets = []
    seen_ids = set()
    lines = snapshot_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for links containing ticket URLs on the home page
        link_match = re.match(r'^\s*- link "(.+?)"\s+\[ref=', line)
        if link_match:
            link_text = link_match.group(1)

            # Check for ticket URL
            if i + 1 < len(lines):
                url_line = lines[i + 1]
                url_match = re.search(
                    r'\?id=ticket&table=sc_req_item&sys_id=([a-f0-9]+)',
                    url_line
                )
                if url_match:
                    sys_id = url_match.group(1)
                    if sys_id in seen_ids:
                        i += 1
                        continue
                    seen_ids.add(sys_id)

                    # Extract RITM number from link text
                    ritm_match = re.search(r'(RITM\d+)', link_text)
                    number = ritm_match.group(1) if ritm_match else ""

                    # Description: heading child or link text minus RITM
                    description = link_text.strip()
                    # Try to get cleaner description from heading
                    for j in range(i + 1, min(i + 5, len(lines))):
                        heading_match = re.match(
                            r'^\s*- heading "(.+?)"\s+\[level=3\]',
                            lines[j]
                        )
                        if heading_match:
                            description = heading_match.group(1).strip()
                            break

                    # Look for RITM and requestor in generic children
                    requested_for = None
                    for j in range(i + 2, min(i + 12, len(lines))):
                        gen_match = re.match(
                            r'^\s*- generic \[ref=\w+\]:\s*(.+)', lines[j]
                        )
                        if gen_match:
                            val = gen_match.group(1).strip()
                            if re.match(r'^RITM\d+$', val):
                                if not number:
                                    number = val
                            elif not re.match(r'^\d', val) and requested_for is None:
                                requested_for = val

                    tickets.append({
                        "number": number,
                        "description": description,
                        "sys_id": sys_id,
                        "requested_for": requested_for,
                        "url": f"?id=ticket&table=sc_req_item&sys_id={sys_id}",
                    })

        i += 1

    return tickets


def extract_search_results(snapshot_text: str) -> List[Dict]:
    """Extract search results from the ServiceNow search results page.

    The Employee Center search page (``?id=search&q=...``) renders results
    inside a flat ``list`` whose children are ``listitem > group`` blocks.
    Each group contains:

        - text: <Type> [KB#] [categories...]     ← metadata line
        - link "<Title>":                         ← result title
            - /url: javascript:void(0)
        - [button "Request in chat"]              ← optional
        - text: <description snippet> <time ago>  ← description

    The link URLs are ``javascript:void(0)`` (SPA navigation), so there are
    no sys_id values available from the search page itself.  Type is inferred
    from the metadata line: lines starting with ``Article`` are knowledge
    articles; lines starting with ``Request`` are catalog request items.

    Returns:
        List of dicts with keys: name, type, description, url, sys_id
    """
    items = []
    lines = snapshot_text.split('\n')

    # Regexes account for optional [ref=eN] markers injected by _inject_refs.
    _GROUP_RE = re.compile(r'^(\s*)- group(?:\s+"[^"]*")?\s*(?:\[ref=\w+\])?:')
    _LINK_RE = re.compile(r'^- link "(.+?)"\s*(?:\[ref=\w+\])?')
    _TEXT_RE = re.compile(r'^- text\s*(?:\[ref=\w+\])?:\s*(.+)')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect a group inside a listitem -- this is one search result.
        group_match = _GROUP_RE.match(line)
        if not group_match:
            i += 1
            continue

        group_indent = len(group_match.group(1))

        # Collect child lines belonging to this group (deeper indentation).
        children = []
        j = i + 1
        while j < len(lines):
            child = lines[j]
            if not child.strip():
                j += 1
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= group_indent:
                break
            children.append(child)
            j += 1

        # Parse the group's children to extract a search result.
        item_type = None
        kb_number = None
        name = None
        description = None
        has_link = False

        for ci, child in enumerate(children):
            stripped = child.strip()

            # Link line -- the result title.
            link_match = _LINK_RE.match(stripped)
            if link_match and not has_link:
                # Skip attachment links (have real URLs to sys_attachment.do)
                # by checking the next line for javascript:void(0).
                if ci + 1 < len(children):
                    next_stripped = children[ci + 1].strip()
                    if 'javascript:void(0)' in next_stripped:
                        name = link_match.group(1).strip()
                        has_link = True
                elif name is None:
                    name = link_match.group(1).strip()
                    has_link = True
                continue

            # Text lines -- metadata (before the link) or description (after).
            text_match = _TEXT_RE.match(stripped)
            if text_match:
                val = text_match.group(1).strip()

                if not has_link:
                    # Metadata line before the link.
                    if val.startswith('Article '):
                        item_type = 'Article'
                        kb_match = re.search(r'(KB\d+)', val)
                        if kb_match:
                            kb_number = kb_match.group(1)
                    elif val.startswith('Request'):
                        item_type = 'Request'
                else:
                    # Description line after the link.
                    if description is None:
                        # Strip surrounding quotes added by the YAML serializer.
                        desc_val = val.strip('"')
                        # Strip trailing "N months/days ago" timestamp.
                        desc_val = re.sub(
                            r'\s+\d+\s+(?:months?|days?|hours?|minutes?|weeks?|years?)\s+ago\s*$',
                            '', desc_val
                        )
                        # Strip leading/trailing "..." from snippet.
                        desc_val = re.sub(r'^\.\.\.\s*', '', desc_val)
                        desc_val = re.sub(r'\s*\.\.\.\s*$', '', desc_val)
                        desc_val = desc_val.strip()
                        if desc_val:
                            description = desc_val
                continue

        # Only emit an item if we found a link (title).
        if name:
            items.append({
                "name": name,
                "type": item_type,
                "description": description,
                "url": None,
                "sys_id": kb_number,
            })

        i = j  # Skip past the group we just processed.

    return items


def find_element_ref(snapshot_text: str, pattern: str) -> Optional[str]:
    """Find an element reference matching a pattern in the snapshot.

    Searches for a line matching the pattern and extracts [ref=XXX].

    Args:
        snapshot_text: The snapshot YAML text
        pattern: Regex pattern to search for in lines

    Returns:
        The ref value (e.g., "e123") or None
    """
    for line in snapshot_text.split('\n'):
        if re.search(pattern, line):
            ref_match = re.search(r'\[ref=(\w+)\]', line)
            if ref_match:
                return ref_match.group(1)
    return None


def find_combobox_ref(snapshot_text: str) -> Optional[str]:
    """Find the combobox ref on the My Requests page for view switching.

    Looks for the View combobox specifically (label contains "View").

    Returns:
        The ref value for the combobox element, or None
    """
    # Match combobox with a quoted label containing "View"
    ref = find_element_ref(snapshot_text, r'- combobox ".*View.*"\s+\[ref=')
    if ref:
        return ref
    # Fallback: any combobox with a label
    ref = find_element_ref(snapshot_text, r'- combobox ".+?"\s+\[ref=')
    if ref:
        return ref
    # Fallback: bare combobox
    return find_element_ref(snapshot_text, r'- combobox\s+\[ref=')


def find_comment_textbox_ref(snapshot_text: str) -> Optional[str]:
    """Find the comment textbox ref on the ticket detail page.

    Looks for a textbox with placeholder like "Type your message here".

    Returns:
        The ref value for the comment textbox, or None
    """
    ref = find_element_ref(snapshot_text, r'textbox.*[Tt]ype your message')
    if ref:
        return ref
    # Fallback: look for any textbox in the activity area
    return find_element_ref(snapshot_text, r'textbox.*\[ref=')


def find_post_button_ref(snapshot_text: str) -> Optional[str]:
    """Find the Post button ref on the ticket detail page.

    Returns:
        The ref value for the Post button, or None
    """
    return find_element_ref(snapshot_text, r'button "Post"')


def find_close_button_ref(snapshot_text: str) -> Optional[str]:
    """Find the Close Ticket button ref on the ticket detail page.

    Returns:
        The ref value for the Close Ticket button, or None
    """
    return find_element_ref(snapshot_text, r'button "Close Ticket"')


# Keep the generic scaffolded function for backward compatibility
def extract_items_from_snapshot(snapshot_text: str) -> List[Dict]:
    """Extract items from a playwright page snapshot YAML.

    This is a generic fallback; prefer the specific extract_* functions.
    """
    return extract_tickets_from_list(snapshot_text)


def find_form_field_ref(snapshot_text: str, label: str, field_type: str) -> Optional[str]:
    """Find a form field ref by its label and expected ARIA role.

    Searches the snapshot for a form element whose accessible name matches
    the given label.  Supports textbox, combobox, checkbox, and textarea
    (which renders as a textbox in the ARIA tree).

    Args:
        snapshot_text: The snapshot YAML text with [ref=eN] markers.
        label: The field label to match (case-insensitive substring).
        field_type: Template field type: text, textarea, dropdown, checkbox,
                    reference, date, checkbox_group.

    Returns:
        The ref value (e.g., "e42") or None.
    """
    # Map template field types to ARIA roles to search for
    role_candidates = {
        "text": ["textbox"],
        "textarea": ["textbox", "application"],
        "dropdown": ["combobox", "listbox"],
        "reference": ["textbox", "combobox"],
        "checkbox": ["checkbox", "switch"],
        "checkbox_group": ["checkbox"],
        "date": ["textbox"],
    }
    roles = role_candidates.get(field_type, ["textbox", "combobox"])
    label_lower = label.lower()

    for role in roles:
        # Try exact match first (case-insensitive): role "Label" [ref=...]
        pattern = rf'- {role} "([^"]*)"[^[]*\[ref=(\w+)\]'
        for m in re.finditer(pattern, snapshot_text):
            name = m.group(1)
            ref = m.group(2)
            if name.lower() == label_lower:
                return ref

    # Fallback to substring match if exact match fails
    for role in roles:
        pattern = rf'- {role} "([^"]*)"[^[]*\[ref=(\w+)\]'
        for m in re.finditer(pattern, snapshot_text):
            name = m.group(1)
            ref = m.group(2)
            if label_lower in name.lower():
                return ref

    # Fallback for unlabeled elements (e.g., TinyMCE rich text editors):
    # Match "- text ...: Label\n  - <role> [ref=...]" where the label is a
    # preceding text node.  The ARIA snapshot renders TinyMCE as:
    #   - text [ref=eN]: Description
    #   - application [ref=eM]:
    for role in roles:
        pattern = rf'- text [^:]*:\s*{re.escape(label)}\s*\n\s*- {role} \[ref=(\w+)\]'
        m = re.search(pattern, snapshot_text, re.IGNORECASE)
        if m:
            return m.group(1)

    return None


def find_submit_button_ref(snapshot_text: str) -> Optional[str]:
    """Find the Submit button ref on a catalog item form.

    Returns:
        The ref value for the Submit button, or None.
    """
    # Try exact "Submit" first
    ref = find_element_ref(snapshot_text, r'button "Submit"')
    if ref:
        return ref
    # Try "Order Now" (some forms use this)
    ref = find_element_ref(snapshot_text, r'button "Order Now"')
    if ref:
        return ref
    return None


def extract_ritm_from_snapshot(snapshot_text: str) -> Optional[str]:
    """Extract an RITM number from a confirmation/detail page snapshot.

    After form submission, the page typically shows the new RITM number.

    Returns:
        The RITM number (e.g., "RITM0352332") or None.
    """
    # Look for RITM pattern anywhere in the snapshot
    m = re.search(r'(RITM\d+)', snapshot_text)
    if m:
        return m.group(1)
    return None


def find_checkbox_ref_by_label(snapshot_text: str, label: str) -> Optional[str]:
    """Find a checkbox ref by its label text (for checkbox_group fields).

    In checkbox groups, each option is a separate checkbox element with
    its own label/name.

    Args:
        snapshot_text: The snapshot YAML text.
        label: The checkbox option label to match.

    Returns:
        The ref value or None.
    """
    label_lower = label.lower()
    pattern = r'- checkbox "([^"]*)"[^[]*\[ref=(\w+)\]'
    # Try exact match first (case-insensitive)
    for m in re.finditer(pattern, snapshot_text):
        name = m.group(1)
        ref = m.group(2)
        if name.lower() == label_lower:
            return ref
    # Fallback to substring match
    for m in re.finditer(pattern, snapshot_text):
        name = m.group(1)
        ref = m.group(2)
        if label_lower in name.lower():
            return ref
    return None


def extract_select2_options(snapshot_text: str) -> List[str]:
    """Extract option text values from an open Select2 dropdown results list.

    When a Select2 dropdown is open, the results appear in the accessibility
    tree as ``option`` elements inside a ``listbox``, or as ``listitem``
    elements.  This function extracts the text of each option.

    The ARIA snapshot renders Select2 results as one of:
        - option "Option Text" [ref=eN]
        - listitem [ref=eN]: Option Text

    Returns:
        List of option text strings (excluding placeholder/empty entries).
    """
    options = []
    for line in snapshot_text.split('\n'):
        stripped = line.strip()

        # Match: - option "Option Text" [ref=eN]
        opt_match = re.match(r'^- option "(.+?)"\s*\[ref=', stripped)
        if opt_match:
            val = opt_match.group(1).strip()
            if val and val not in ('', 'Searching…', 'Loading…', 'No matches found'):
                options.append(val)
            continue

        # Match Select2 result items: - listitem [ref=eN]: Option Text
        # These appear inside the select2-results list
        li_match = re.match(r'^- listitem\s+\[ref=\w+\]:\s*(.+)', stripped)
        if li_match:
            val = li_match.group(1).strip()
            if val and val not in ('', 'Searching…', 'Loading…', 'No matches found'):
                options.append(val)
            continue

    return options


def _next_generic_value(lines: List[str], start: int) -> Optional[str]:
    """Find the next generic element value after a given line index."""
    for j in range(start + 1, min(start + 4, len(lines))):
        child = lines[j].strip()
        # Match: - generic [ref=...]: value
        gen_match = re.match(r'^- generic\s+"?([^"]*)"?\s*\[ref=\w+\]', child)
        if gen_match:
            val = gen_match.group(1).strip()
            if val:
                return val
        # Also match: - generic [ref=...]: value (value after colon)
        gen_match2 = re.match(r'^- generic\s+\[ref=\w+\]:\s*(.+)', child)
        if gen_match2:
            return gen_match2.group(1).strip()
        # Match: - generic "value" [ref=...]:
        gen_match3 = re.match(r'^- generic "(.+?)"\s+\[ref=\w+\]', child)
        if gen_match3:
            return gen_match3.group(1).strip()
    return None


def _next_link_text(lines: List[str], start: int) -> Optional[str]:
    """Find the next link text value after a given line index."""
    for j in range(start + 1, min(start + 4, len(lines))):
        child = lines[j].strip()
        # Match: - link "Label Person Name" [ref=...]: Person Name
        link_match = re.match(r'^- link ".+?"\s+\[ref=\w+\].*:\s*(.+)', child)
        if link_match:
            return link_match.group(1).strip()
        # Match: - link "Person Name" [ref=...]
        link_match2 = re.match(r'^- link "(.+?)"\s+\[ref=', child)
        if link_match2:
            return link_match2.group(1).strip()
    return None


def parse_form_fields(snapshot_text: str) -> List[Dict]:
    """Parse form fields from a catalog item form snapshot.

    Walks the main region of the accessibility tree, tracking label text
    nodes and "required" markers, and emits one record per form element
    encountered. Distinguishes:

    - ``dropdown``  --  combobox, no preceding "Lookup using list" link
    - ``reference`` --  combobox preceded by a "Lookup using list" link
    - ``textarea``  --  ``application`` role (TinyMCE rich-text editor)
    - ``text``      --  textbox
    - ``checkbox``  --  checkbox
    - ``date``      --  textbox (not detectable from snapshot alone)

    Combobox labels sometimes contain the currently-selected value appended
    (e.g. ``"Impact Low"`` when Low is the default).  The parser strips the
    trailing value when a preceding text label exists.

    Args:
        snapshot_text: The accessibility tree YAML text with [ref=eN] markers.

    Returns:
        List of field dicts with keys: label, type, required, ref, key_suggestion.
    """
    lines = snapshot_text.splitlines()
    fields: List[Dict] = []

    # Find the main region start so we skip header/nav fields
    main_start = None
    for i, line in enumerate(lines):
        if re.match(r"^- main \[", line.strip()):
            main_start = i
            break
    if main_start is None:
        main_start = 0

    # Patterns
    label_pat = re.compile(r'^\s*-?\s*text(?:\s+\[ref=\w+\])?:\s*(.*)$')
    combobox_pat = re.compile(r'-\s*combobox "([^"]*)"[^[]*\[ref=(\w+)\]')
    textbox_pat = re.compile(r'-\s*textbox "([^"]*)"[^[]*\[ref=(\w+)\]')
    checkbox_pat = re.compile(r'-\s*checkbox "([^"]*)"[^[]*\[ref=(\w+)\]')
    application_pat = re.compile(r'-\s*application\s*\[ref=(\w+)\]')
    lookup_link_pat = re.compile(r'link "Lookup using list"')
    required_marker = "asterisk (Indicates required)"

    current_label: Optional[str] = None
    current_required = False
    pending_lookup_link = False
    seen_labels = set()
    seen_refs = set()

    def _suggest_key(label: str) -> str:
        key = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
        return key[:60] or "field"

    def _clean_label(raw: str) -> str:
        return raw.replace(required_marker, "").strip()

    for i in range(main_start, len(lines)):
        line = lines[i]

        # Track label text nodes
        m = label_pat.search(line)
        if m:
            text = m.group(1).strip()
            if text:
                if required_marker in text:
                    current_required = True
                    current_label = _clean_label(text)
                else:
                    current_required = False
                    current_label = text
                pending_lookup_link = False
            continue

        # Track lookup link occurrence (means next combobox is a reference)
        if lookup_link_pat.search(line):
            pending_lookup_link = True
            continue

        # Combobox -> dropdown or reference
        m = combobox_pat.search(line)
        if m:
            name = m.group(1).strip()
            ref = m.group(2)
            # Prefer the preceding text label over the combobox name if
            # the combobox name looks like "Label Value" (contains label).
            if current_label and name.lower().startswith(current_label.lower()):
                label = current_label
            else:
                label = name or current_label or ""
            if label and ref not in seen_refs:
                field_type = "reference" if pending_lookup_link else "dropdown"
                fields.append({
                    "label": label,
                    "type": field_type,
                    "required": current_required,
                    "ref": ref,
                    "key_suggestion": _suggest_key(label),
                })
                seen_refs.add(ref)
                seen_labels.add(label.lower())
            current_required = False
            pending_lookup_link = False
            current_label = None
            continue

        # Checkbox
        m = checkbox_pat.search(line)
        if m:
            name = m.group(1).strip() or current_label or ""
            ref = m.group(2)
            if name and ref not in seen_refs:
                fields.append({
                    "label": name,
                    "type": "checkbox",
                    "required": current_required,
                    "ref": ref,
                    "key_suggestion": _suggest_key(name),
                })
                seen_refs.add(ref)
                seen_labels.add(name.lower())
            current_required = False
            current_label = None
            continue

        # Application (TinyMCE textarea) -- takes its label from preceding text
        m = application_pat.search(line)
        if m:
            ref = m.group(1)
            label = current_label or "Description"
            if ref not in seen_refs:
                fields.append({
                    "label": label,
                    "type": "textarea",
                    "required": current_required,
                    "ref": ref,
                    "key_suggestion": _suggest_key(label),
                })
                seen_refs.add(ref)
                seen_labels.add(label.lower())
            current_required = False
            current_label = None
            continue

        # Textbox -> text field (only if we have a preceding label)
        m = textbox_pat.search(line)
        if m:
            name = m.group(1).strip() or current_label or ""
            ref = m.group(2)
            # Skip generic/search boxes that already have their own labels
            # matching known header widgets
            skip_names = {"click here to find self-help articles, request forms, content from myprogress and more.."}
            if name.lower() in skip_names:
                continue
            if name and ref not in seen_refs:
                fields.append({
                    "label": name,
                    "type": "text",
                    "required": current_required,
                    "ref": ref,
                    "key_suggestion": _suggest_key(name),
                })
                seen_refs.add(ref)
                seen_labels.add(name.lower())
            current_required = False
            current_label = None
            continue

    return fields
