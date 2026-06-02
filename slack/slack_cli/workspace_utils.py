"""Utilities for working with multiple Slack workspaces."""
from typing import Callable, List, Dict, Optional
from .client import get_all_workspace_clients, SlackClient
from .config import get_config
from cli_tools_shared.output import print_warning


def run_across_workspaces(
    operation: Callable[[SlackClient], List[Dict]],
    workspace_id: Optional[str] = None,
    item_key: str = "items",
) -> tuple[List[Dict], bool]:
    """
    Run an operation across all workspaces or a specific one.

    Args:
        operation: A function that takes a SlackClient and returns a list of items
        workspace_id: If provided, query only this workspace. If None, query all workspaces.
        item_key: Key name for the items in the result (for error messages)

    Returns:
        Tuple of (combined results list, whether multiple workspaces were queried)
    """
    if workspace_id:
        # Query specific workspace
        from .client import get_client_for_workspace_id
        client = get_client_for_workspace_id(workspace_id)
        items = operation(client)
        # Add workspace info to each item
        for item in items:
            item["_workspace"] = client.workspace_name
            item["_workspace_id"] = client.workspace_id
        return items, False

    # Run across all workspaces (default behavior)
    all_items = []
    clients = get_all_workspace_clients()

    if not clients:
        return [], True

    for client in clients:
        try:
            items = operation(client)
            # Add workspace info to each item
            for item in items:
                item["_workspace"] = client.workspace_name
                item["_workspace_id"] = client.workspace_id
            all_items.extend(items)
        except Exception as e:
            print_warning(f"Failed to fetch {item_key} from {client.workspace_name}: {e}")

    return all_items, True


def get_workspace_column_info(multi_workspace: bool) -> tuple[List[str], List[str]]:
    """
    Get column info for workspace-aware tables.

    Args:
        multi_workspace: Whether multiple workspaces were queried (True when no --workspace specified)

    Returns:
        Tuple of (column keys to prepend, column headers to prepend)
    """
    if multi_workspace:
        return ["_workspace"], ["Workspace"]
    return [], []


def enrich_items_with_workspace(
    items: List[Dict],
    client: SlackClient,
) -> List[Dict]:
    """
    Add workspace info to a list of items.

    Args:
        items: List of item dictionaries
        client: The SlackClient that fetched these items

    Returns:
        The same list with _workspace and _workspace_id added to each item
    """
    for item in items:
        item["_workspace"] = client.workspace_name
        item["_workspace_id"] = client.workspace_id
    return items
