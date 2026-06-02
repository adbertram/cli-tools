"""FreeMind XML format generator for MindMeister import.

FreeMind (.mm) is an XML-based mind map format that MindMeister can import.
This module generates FreeMind-compatible XML from idea structures.

Format spec: https://freemind.sourceforge.io/wiki/index.php/File_format
"""
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET
from xml.dom import minidom
import html
import time


def escape_xml_text(text: str) -> str:
    """Escape text for XML attribute values."""
    if not text:
        return ""
    # Replace newlines with spaces for single-line TEXT attributes
    text = text.replace("\n", " ").replace("\r", " ")
    return html.escape(text, quote=True)


def create_node_element(
    text: str,
    node_id: Optional[str] = None,
    position: Optional[str] = None,
    folded: bool = False,
    note: Optional[str] = None,
) -> ET.Element:
    """Create a FreeMind node element.

    Args:
        text: The node's display text
        node_id: Optional unique ID for the node
        position: "left" or "right" (only for first-level children)
        folded: Whether the node is collapsed
        note: Optional note/comment for the node

    Returns:
        XML Element representing the node
    """
    attribs = {"TEXT": escape_xml_text(text)}

    if node_id:
        attribs["ID"] = f"ID_{node_id}"

    if position:
        attribs["POSITION"] = position

    if folded:
        attribs["FOLDED"] = "true"

    # Add timestamps
    timestamp = str(int(time.time() * 1000))
    attribs["CREATED"] = timestamp
    attribs["MODIFIED"] = timestamp

    node = ET.Element("node", attribs)

    # Add note as richcontent child element
    if note:
        richcontent = ET.SubElement(node, "richcontent", {"TYPE": "NOTE"})
        html_elem = ET.SubElement(richcontent, "html")
        head = ET.SubElement(html_elem, "head")
        body = ET.SubElement(html_elem, "body")
        p = ET.SubElement(body, "p")
        p.text = note

    return node


def build_tree_from_flat_ideas(ideas: List[Dict]) -> Dict[str, Dict]:
    """Build a tree structure from flat list of ideas with parent references.

    Args:
        ideas: List of idea dicts with 'id', 'title', and optional 'parent' keys

    Returns:
        Dict mapping idea IDs to their data plus 'children' list
    """
    # Create lookup dict
    nodes = {}
    for idea in ideas:
        idea_id = str(idea.get("id", ""))
        nodes[idea_id] = {
            "id": idea_id,
            "title": idea.get("title", ""),
            "parent": idea.get("parent"),
            "closed": idea.get("closed", "false") == "true",
            "children": [],
        }

    # Build tree by adding children to parents
    root = None
    for idea_id, node in nodes.items():
        parent_id = node.get("parent")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        elif not parent_id:
            root = node

    return root


def ideas_to_freemind_xml(
    ideas: List[Dict],
    title: Optional[str] = None,
) -> str:
    """Convert a list of ideas to FreeMind XML format.

    Args:
        ideas: List of idea dicts. Each should have:
            - id: Unique identifier
            - title: Display text
            - parent: Parent idea ID (None for root)
            - closed: Whether branch is collapsed (optional)
        title: Override title for root node (uses first idea's title if not provided)

    Returns:
        FreeMind XML string
    """
    if not ideas:
        # Create empty map with just a root node
        root_title = title or "New Mind Map"
        map_elem = ET.Element("map", {"version": "1.0.1"})
        root_node = create_node_element(root_title, node_id="root")
        map_elem.append(root_node)
        return _prettify_xml(map_elem)

    # Build tree structure
    tree_root = build_tree_from_flat_ideas(ideas)

    if not tree_root:
        # Fallback: use first idea as root
        tree_root = {
            "id": ideas[0].get("id", "root"),
            "title": title or ideas[0].get("title", "Mind Map"),
            "closed": False,
            "children": [],
        }

    # Override root title if specified
    if title:
        tree_root["title"] = title

    # Create XML structure
    map_elem = ET.Element("map", {"version": "1.0.1"})

    def add_node_recursive(parent_elem: ET.Element, node_data: Dict, depth: int = 0):
        """Recursively add nodes to the XML tree."""
        # Determine position for first-level children
        position = None
        if depth == 1:
            # Alternate left/right for visual balance
            idx = list(parent_elem).index(parent_elem[-1]) if len(parent_elem) > 0 else 0
            position = "right" if idx % 2 == 0 else "left"

        node_elem = create_node_element(
            text=node_data.get("title", ""),
            node_id=node_data.get("id"),
            position=position,
            folded=node_data.get("closed", False),
        )

        # Add children
        for child in node_data.get("children", []):
            add_node_recursive(node_elem, child, depth + 1)

        parent_elem.append(node_elem)

    # Start with root node
    root_node = create_node_element(
        text=tree_root.get("title", "Mind Map"),
        node_id=tree_root.get("id", "root"),
        folded=tree_root.get("closed", False),
    )

    # Add children to root
    for i, child in enumerate(tree_root.get("children", [])):
        # Alternate position for first-level nodes
        position = "right" if i % 2 == 0 else "left"
        child_elem = create_node_element(
            text=child.get("title", ""),
            node_id=child.get("id"),
            position=position,
            folded=child.get("closed", False),
        )

        # Recursively add grandchildren
        for grandchild in child.get("children", []):
            _add_children_recursive(child_elem, grandchild)

        root_node.append(child_elem)

    map_elem.append(root_node)
    return _prettify_xml(map_elem)


def _add_children_recursive(parent_elem: ET.Element, node_data: Dict):
    """Recursively add child nodes (depth > 1, no position attribute)."""
    node_elem = create_node_element(
        text=node_data.get("title", ""),
        node_id=node_data.get("id"),
        folded=node_data.get("closed", False),
    )

    for child in node_data.get("children", []):
        _add_children_recursive(node_elem, child)

    parent_elem.append(node_elem)


def create_simple_mindmap(
    title: str,
    children: List[str],
) -> str:
    """Create a simple mind map with root and first-level children.

    Args:
        title: Root node text
        children: List of first-level child texts

    Returns:
        FreeMind XML string
    """
    ideas = [{"id": "root", "title": title, "parent": None}]

    for i, child_text in enumerate(children):
        ideas.append({
            "id": f"child_{i}",
            "title": child_text,
            "parent": "root",
        })

    return ideas_to_freemind_xml(ideas, title=title)


def create_hierarchical_mindmap(
    structure: Dict,
) -> str:
    """Create a mind map from a nested dictionary structure.

    Args:
        structure: Nested dict where keys are node titles and values are
                   either strings (leaf nodes) or nested dicts (branches).
                   Example: {"Root": {"Branch1": ["Leaf1", "Leaf2"], "Branch2": "Leaf3"}}

    Returns:
        FreeMind XML string
    """
    ideas = []
    id_counter = [0]  # Use list for mutable counter in nested function

    def process_node(title: str, children, parent_id: Optional[str] = None):
        node_id = f"node_{id_counter[0]}"
        id_counter[0] += 1

        ideas.append({
            "id": node_id,
            "title": title,
            "parent": parent_id,
        })

        if isinstance(children, dict):
            for child_title, grandchildren in children.items():
                process_node(child_title, grandchildren, node_id)
        elif isinstance(children, list):
            for item in children:
                if isinstance(item, str):
                    child_id = f"node_{id_counter[0]}"
                    id_counter[0] += 1
                    ideas.append({
                        "id": child_id,
                        "title": item,
                        "parent": node_id,
                    })
                elif isinstance(item, dict):
                    for child_title, grandchildren in item.items():
                        process_node(child_title, grandchildren, node_id)
        elif isinstance(children, str):
            child_id = f"node_{id_counter[0]}"
            id_counter[0] += 1
            ideas.append({
                "id": child_id,
                "title": children,
                "parent": node_id,
            })

    # Process the root structure
    for root_title, root_children in structure.items():
        process_node(root_title, root_children, None)
        break  # Only process first root

    return ideas_to_freemind_xml(ideas)


def create_annotated_mindmap(nodes: List[Dict]) -> str:
    """Create a mind map with notes/annotations on each node.

    Args:
        nodes: List of node dicts, each with:
            - title: Node display text (required)
            - note: Note/comment for the node (optional)
            - children: List of child node dicts (optional)

    Example:
        nodes = [{
            "title": "Root",
            "note": "This is the root node",
            "children": [
                {"title": "Child 1", "note": "First child description"},
                {"title": "Child 2", "children": [
                    {"title": "Grandchild", "note": "Leaf node"}
                ]}
            ]
        }]

    Returns:
        FreeMind XML string
    """
    if not nodes:
        return create_simple_mindmap("Empty Map", [])

    map_elem = ET.Element("map", {"version": "1.0.1"})
    id_counter = [0]

    def add_node(parent_elem: ET.Element, node_data: Dict, depth: int = 0):
        """Recursively add a node and its children."""
        node_id = f"node_{id_counter[0]}"
        id_counter[0] += 1

        # Determine position for first-level children
        position = None
        if depth == 1:
            idx = len(list(parent_elem))
            position = "right" if idx % 2 == 0 else "left"

        node_elem = create_node_element(
            text=node_data.get("title", ""),
            node_id=node_id,
            position=position,
            folded=node_data.get("folded", False),
            note=node_data.get("note"),
        )

        # Add children recursively
        for child in node_data.get("children", []):
            add_node(node_elem, child, depth + 1)

        parent_elem.append(node_elem)

    # Process the root node(s)
    for root_node in nodes:
        add_node(map_elem, root_node, depth=0)

    return _prettify_xml(map_elem)


def _prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(rough_string)
    # Remove XML declaration (FreeMind doesn't use it)
    pretty = reparsed.toprettyxml(indent="  ")
    # Remove the XML declaration line
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines = lines[1:]
    return "\n".join(lines).strip()
