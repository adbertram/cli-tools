"""Ideas commands for MindMeister CLI.

Note: The MindMeister API does not support adding/editing/deleting ideas directly.
These commands provide workarounds using the import functionality.
"""
import json
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error


app = typer.Typer(help="Manage ideas/nodes in MindMeister maps", no_args_is_help=True)


@app.command("list")
def ideas_list(
    map_id: str = typer.Argument(..., help="The map ID to list ideas from"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    tree: bool = typer.Option(False, "--tree", help="Display as tree structure"),
):
    """
    List all ideas/nodes in a map.

    Examples:
        mindmeister ideas list 123456
        mindmeister ideas list 123456 --table
        mindmeister ideas list 123456 --tree
    """
    try:
        client = get_client()
        ideas = client.get_ideas(map_id)

        if tree:
            _print_tree(ideas)
        elif table:
            # Flatten for table display
            rows = []
            for idea in ideas:
                rows.append({
                    "id": idea.get("id", ""),
                    "title": (idea.get("title", "") or "")[:50],
                    "parent": idea.get("parent", "-"),
                    "closed": "Yes" if idea.get("closed") == "true" else "No",
                })
            print_table(rows, ["id", "title", "parent", "closed"], ["ID", "Title", "Parent", "Closed"])
        else:
            print_json(ideas)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("toggle-closed")
def ideas_toggle_closed(
    map_id: str = typer.Argument(..., help="The map ID"),
    idea_id: str = typer.Argument(..., help="The idea/node ID to toggle"),
    closed: Optional[bool] = typer.Option(None, "--closed/--open", help="Set specific state"),
):
    """
    Toggle or set the collapsed state of a branch.

    Examples:
        mindmeister ideas toggle-closed 123456 789  # Toggle
        mindmeister ideas toggle-closed 123456 789 --closed  # Collapse
        mindmeister ideas toggle-closed 123456 789 --open  # Expand
    """
    try:
        client = get_client()
        result = client.toggle_idea_closed(map_id, idea_id, closed)
        state = "collapsed" if closed else "expanded" if closed is False else "toggled"
        print_success(f"Branch {idea_id} {state}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create-map")
def ideas_create_map(
    title: str = typer.Argument(..., help="Title for the root node and map"),
    children: Optional[List[str]] = typer.Option(
        None, "--child", "-c", help="Add first-level child nodes (can be repeated)"
    ),
    json_structure: Optional[str] = typer.Option(
        None, "--json", "-j", help="JSON structure for hierarchical map"
    ),
):
    """
    Create a new map with ideas/nodes.

    This uses the import workaround since the API doesn't support adding ideas directly.

    Examples:
        # Simple map with children
        mindmeister ideas create-map "My Project" -c "Phase 1" -c "Phase 2" -c "Phase 3"

        # Hierarchical map from JSON
        mindmeister ideas create-map "Root" --json '{"Root": {"Branch1": ["Leaf1", "Leaf2"]}}'
    """
    try:
        client = get_client()

        if json_structure:
            try:
                structure = json.loads(json_structure)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON: {e}")
                raise typer.Exit(1)
            new_map = client.create_map_from_structure(structure)
        elif children:
            new_map = client.create_map_with_children(title, list(children))
        else:
            # Create map with just a title (empty)
            new_map = client.create_map(title)

        print_success(f"Created map: {new_map.id}")
        print_json(new_map)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("import")
def ideas_import(
    file_path: str = typer.Argument(..., help="Path to FreeMind (.mm) or other mind map file"),
):
    """
    Import a mind map from a file.

    Supported formats: .mm (FreeMind), .mmap, .xmind

    Examples:
        mindmeister ideas import my_mindmap.mm
        mindmeister ideas import project.xmind
    """
    try:
        import os

        if not os.path.exists(file_path):
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        filename = os.path.basename(file_path)

        with open(file_path, "rb") as f:
            content = f.read()

        client = get_client()
        new_map = client.import_map(content, filename)

        print_success(f"Imported map: {new_map.id}")
        print_json(new_map)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create-annotated")
def ideas_create_annotated(
    file_path: str = typer.Argument(..., help="Path to JSON file with annotated node structure"),
):
    """
    Create a mind map with notes/comments on each node from a JSON file.

    The JSON file should contain a list with a root node object. Each node can have:
    - title: Node display text (required)
    - note: Note/comment for the node (optional)
    - children: List of child nodes (optional)

    Example JSON structure:
    [
      {
        "title": "Root Topic",
        "note": "Description of the root",
        "children": [
          {
            "title": "Branch 1",
            "note": "What this branch covers",
            "children": [
              {"title": "Leaf", "note": "Leaf node description"}
            ]
          }
        ]
      }
    ]

    Examples:
        mindmeister ideas create-annotated my_mindmap.json
    """
    try:
        import os

        if not os.path.exists(file_path):
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        with open(file_path, "r") as f:
            try:
                nodes = json.load(f)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON: {e}")
                raise typer.Exit(1)

        if not isinstance(nodes, list):
            print_error("JSON must be a list containing the root node")
            raise typer.Exit(1)

        client = get_client()
        new_map = client.create_annotated_map(nodes)

        print_success(f"Created annotated map: {new_map.id}")
        print_json(new_map)

    except Exception as e:
        raise typer.Exit(handle_error(e))


def _print_tree(ideas: List[dict], indent: int = 0):
    """Print ideas as a tree structure."""
    # Build parent->children map
    children_map: dict = {}
    root = None

    for idea in ideas:
        idea_id = idea.get("id", "")
        parent_id = idea.get("parent")

        if parent_id:
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(idea)
        else:
            root = idea

    def print_node(node: dict, prefix: str = "", is_last: bool = True):
        """Recursively print a node and its children."""
        node_id = node.get("id", "")
        title = (node.get("title", "") or "").replace("\n", " ")[:60]
        closed_marker = " [collapsed]" if node.get("closed") == "true" else ""

        # Print current node
        connector = "└── " if is_last else "├── "
        typer.echo(f"{prefix}{connector}{title}{closed_marker}")

        # Print children
        node_children = children_map.get(node_id, [])
        for i, child in enumerate(node_children):
            child_is_last = i == len(node_children) - 1
            new_prefix = prefix + ("    " if is_last else "│   ")
            print_node(child, new_prefix, child_is_last)

    if root:
        title = (root.get("title", "") or "").replace("\n", " ")[:60]
        typer.echo(title)
        root_children = children_map.get(root.get("id", ""), [])
        for i, child in enumerate(root_children):
            is_last = i == len(root_children) - 1
            print_node(child, "", is_last)
    else:
        typer.echo("No root node found")


COMMAND_CREDENTIALS = {
    "create-annotated": [
        "custom"
    ],
    "create-map": [
        "custom"
    ],
    "import": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "toggle-closed": [
        "custom"
    ]
}
