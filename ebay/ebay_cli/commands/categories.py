"""Categories commands for eBay CLI.

Uses the eBay Taxonomy API to search and browse eBay marketplace categories.
API Docs: https://developer.ebay.com/api-docs/commerce/taxonomy/resources/methods

The Taxonomy API uses authorization code grant (user-level access).
The default category tree ID for EBAY_US is 0.
"""
COMMAND_CREDENTIALS = {
    "conditions": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "list": ["oauth_authorization_code"],
    "search": ["oauth_authorization_code"],
    "tree": ["oauth_authorization_code"],
}

from typing import Any, Optional, List

import typer
import requests

from ..config import get_config
from cli_tools_shared.output import print_json, print_table, handle_error, print_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError


app = typer.Typer(help="Search and browse eBay marketplace categories")


# Default category tree IDs for common marketplaces
# See: https://developer.ebay.com/api-docs/commerce/taxonomy/static/supportedmarketplaces.html
MARKETPLACE_TREE_IDS = {
    "EBAY_US": "0",
    "EBAY_GB": "3",
    "EBAY_AU": "15",
    "EBAY_DE": "77",
    "EBAY_CA": "2",
    "EBAY_FR": "71",
    "EBAY_IT": "101",
    "EBAY_ES": "186",
}


class TaxonomyClient:
    """Client for eBay Taxonomy API using client credentials grant."""

    def __init__(self, profile: Optional[str] = None, config: Optional[Any] = None):
        self.config = config or get_config(profile=profile)
        self._access_token = None

    def _get_app_token(self) -> str:
        """Get an application access token using client credentials grant."""
        if self._access_token:
            return self._access_token

        if not self.config.client_id or not self.config.client_secret:
            raise Exception(
                "Missing CLIENT_ID or CLIENT_SECRET. Run 'ebay auth login' to authenticate."
            )

        # Request token using client credentials grant
        token_url = self.config.OAUTH_TOKEN_URL
        auth = (self.config.client_id, self.config.client_secret)
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        response = requests.post(token_url, auth=auth, data=data)
        if not response.ok:
            raise Exception(f"Failed to get application token: {response.text}")

        result = response.json()
        self._access_token = result.get("access_token")
        return self._access_token

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to the Taxonomy API."""
        token = self._get_app_token()
        base_url = self.config.api_base_url
        url = f"{base_url}{endpoint}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }

        response = requests.get(url, headers=headers, params=params)

        if not response.ok:
            try:
                error_data = response.json()
                errors = error_data.get("errors", [])
                if errors:
                    error_msg = errors[0].get("message", response.text)
                else:
                    error_msg = response.text
            except Exception:
                error_msg = response.text
            raise Exception(f"API request failed ({response.status_code}): {error_msg}")

        return response.json()

    def get_category_suggestions(self, query: str, tree_id: str = "0") -> dict:
        """
        Get category suggestions for a search query.

        Args:
            query: Search query string (free-form text)
            tree_id: Category tree ID (default: 0 for EBAY_US)

        Returns:
            CategorySuggestionResponse with categorySuggestions array
        """
        endpoint = f"/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions"
        params = {"q": query}
        return self._make_request(endpoint, params)

    def get_category_subtree(self, category_id: str, tree_id: str = "0") -> dict:
        """
        Get the subtree below a category.

        Args:
            category_id: Category ID to get subtree for
            tree_id: Category tree ID (default: 0 for EBAY_US)

        Returns:
            CategorySubtree with categorySubtreeNode
        """
        endpoint = f"/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_subtree"
        params = {"category_id": category_id}
        return self._make_request(endpoint, params)

    def get_item_aspects_for_category(self, category_id: str, tree_id: str = "0") -> dict:
        """
        Get item aspects (specifics) for a leaf category.

        Args:
            category_id: Leaf category ID
            tree_id: Category tree ID (default: 0 for EBAY_US)

        Returns:
            GetCategoriesAspects with aspects array
        """
        endpoint = f"/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category"
        params = {"category_id": category_id}
        return self._make_request(endpoint, params)


def _build_category_path(ancestors: list, category_name: str) -> str:
    """Build a full category path from ancestors and current category name."""
    # Ancestors are ordered from immediate parent up to root, so reverse them
    path_parts = []
    for ancestor in reversed(ancestors):
        path_parts.append(ancestor.get("categoryName", ""))
    path_parts.append(category_name)
    return " > ".join(path_parts)


def _flatten_subtree(node: dict, parent_path: str = "") -> list:
    """Flatten a category tree node recursively into a list."""
    result = []
    category = node.get("category", {})
    cat_id = category.get("categoryId", "")
    cat_name = category.get("categoryName", "")
    level = node.get("categoryTreeNodeLevel", 0)
    is_leaf = node.get("leafCategoryTreeNode", False)

    path = f"{parent_path} > {cat_name}" if parent_path else cat_name

    result.append({
        "categoryId": cat_id,
        "categoryName": cat_name,
        "level": level,
        "isLeaf": is_leaf,
        "path": path,
    })

    children = node.get("childCategoryTreeNodes", [])
    for child in children:
        result.extend(_flatten_subtree(child, path))

    return result


@app.command("list")
def categories_list(
    query: str = typer.Argument(..., help="Search query (e.g., 'trading card storage', 'lego parts')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID (EBAY_US, EBAY_GB, EBAY_AU, etc.)"
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of results to display"),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value). E.g., level:gt:3, categoryName:ilike:%lego%"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output (e.g., categoryId,categoryName)"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    List eBay categories matching a keyword query.

    Returns leaf category suggestions based on your search query.
    Use the category ID when creating listings.

    This is an alias for 'ebay categories search'.

    Examples:
        ebay categories list "trading card storage"
        ebay categories list "lego parts" --table
        ebay categories list "vintage toys" --limit 5
        ebay categories list "electronics" --marketplace EBAY_GB
        ebay categories list "lego" --filter "level:gt:3"
        ebay categories list "lego" --properties "categoryId,categoryName"
    """
    categories_search(query=query, table=table, marketplace=marketplace, limit=limit, filters=filters, properties=properties, profile=profile)


@app.command("search", hidden=True)
def categories_search(
    query: str = typer.Argument(..., help="Search query (e.g., 'trading card storage', 'lego parts')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID (EBAY_US, EBAY_GB, EBAY_AU, etc.)"
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of results to display"),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value). E.g., level:gt:3, categoryName:ilike:%lego%"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output (e.g., categoryId,categoryName)"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """
    Search for eBay categories by keyword.

    Returns leaf category suggestions based on your search query.
    Use the category ID when creating listings.

    Examples:
        ebay categories search "trading card storage"
        ebay categories search "lego parts" --table
        ebay categories search "vintage toys" --limit 5
        ebay categories search "electronics" --marketplace EBAY_GB
    """
    try:
        tree_id = MARKETPLACE_TREE_IDS.get(marketplace.upper(), "0")
        client = TaxonomyClient(profile=profile)
        result = client.get_category_suggestions(query, tree_id)

        suggestions = result.get("categorySuggestions", [])
        if not suggestions:
            print_error(f"No categories found for '{query}'")
            raise typer.Exit(1)

        # Limit results
        suggestions = suggestions[:limit]

        # Transform for output
        categories = []
        for suggestion in suggestions:
            category = suggestion.get("category", {})
            ancestors = suggestion.get("categoryTreeNodeAncestors", [])
            cat_id = category.get("categoryId", "")
            cat_name = category.get("categoryName", "")
            level = suggestion.get("categoryTreeNodeLevel", 0)

            path = _build_category_path(ancestors, cat_name)

            categories.append({
                "categoryId": cat_id,
                "categoryName": cat_name,
                "level": level,
                "path": path,
            })

        # Apply client-side filters
        if filters:
            try:
                validate_filters(filters)
                categories = apply_filters(categories, filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter
        if properties:
            try:
                categories = validate_and_filter_properties(categories, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            table_data = []
            for cat in categories:
                # Truncate path for table display
                path = cat.get("path", "")
                if len(path) > 60:
                    path = "..." + path[-57:]
                table_data.append({
                    "id": cat.get("categoryId", ""),
                    "name": cat.get("categoryName", ""),
                    "path": path,
                })

            print_table(
                table_data,
                ["id", "name", "path"],
                ["Category ID", "Name", "Full Path"],
            )
        else:
            print_json({
                "query": query,
                "marketplace": marketplace,
                "categoryTreeId": tree_id,
                "total": len(categories),
                "categories": categories,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def categories_get(
    category_id: str = typer.Argument(..., help="Category ID to get details for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID (EBAY_US, EBAY_GB, EBAY_AU, etc.)"
    ),
    aspects: bool = typer.Option(False, "--aspects", "-a", help="Include required/recommended item aspects"),
):
    """
    Get details for a specific category ID.

    Returns category details including the full path and whether it's a leaf category.
    Use --aspects to see required and recommended item specifics for listings.

    Examples:
        ebay categories get 183448
        ebay categories get 183448 --table
        ebay categories get 261328 --aspects
    """
    try:
        tree_id = MARKETPLACE_TREE_IDS.get(marketplace.upper(), "0")
        client = TaxonomyClient()

        # Get subtree to retrieve category info
        result = client.get_category_subtree(category_id, tree_id)
        node = result.get("categorySubtreeNode", {})
        category = node.get("category", {})
        is_leaf = node.get("leafCategoryTreeNode", False)
        level = node.get("categoryTreeNodeLevel", 0)

        # Get child categories if not a leaf
        children = []
        if not is_leaf:
            child_nodes = node.get("childCategoryTreeNodes", [])
            for child in child_nodes:
                child_cat = child.get("category", {})
                children.append({
                    "categoryId": child_cat.get("categoryId", ""),
                    "categoryName": child_cat.get("categoryName", ""),
                    "isLeaf": child.get("leafCategoryTreeNode", False),
                })

        # Build response
        output = {
            "categoryId": category.get("categoryId", ""),
            "categoryName": category.get("categoryName", ""),
            "level": level,
            "isLeaf": is_leaf,
            "childCategories": children if not is_leaf else None,
            "categoryTreeId": tree_id,
        }

        # Get aspects if requested and it's a leaf category
        aspects_data = None
        if aspects and is_leaf:
            try:
                aspects_result = client.get_item_aspects_for_category(category_id, tree_id)
                aspect_list = aspects_result.get("aspects", [])

                # Separate required and recommended aspects
                required = []
                recommended = []
                for aspect in aspect_list:
                    aspect_info = {
                        "name": aspect.get("localizedAspectName", ""),
                        "dataType": aspect.get("aspectConstraint", {}).get("aspectDataType", ""),
                        "mode": aspect.get("aspectConstraint", {}).get("aspectMode", ""),
                    }
                    # Get some example values
                    values = aspect.get("aspectValues", [])
                    if values:
                        example_values = [v.get("localizedValue", "") for v in values[:5]]
                        aspect_info["exampleValues"] = example_values

                    constraint = aspect.get("aspectConstraint", {})
                    if constraint.get("aspectRequired"):
                        required.append(aspect_info)
                    else:
                        recommended.append(aspect_info)

                aspects_data = {
                    "required": required,
                    "recommended": recommended[:10],  # Limit recommended to avoid huge output
                }
            except Exception:
                aspects_data = {"error": "Failed to retrieve aspects"}

        if aspects_data:
            output["aspects"] = aspects_data

        if table:
            # Basic info table
            info_data = [{
                "id": output.get("categoryId", ""),
                "name": output.get("categoryName", ""),
                "level": str(output.get("level", "")),
                "isLeaf": "Yes" if output.get("isLeaf") else "No",
            }]

            print_table(
                info_data,
                ["id", "name", "level", "isLeaf"],
                ["Category ID", "Name", "Level", "Leaf Category"],
            )

            # Child categories table
            if children:
                print(f"\nChild Categories ({len(children)}):")
                child_data = []
                for child in children[:20]:  # Limit to 20
                    child_data.append({
                        "id": child.get("categoryId", ""),
                        "name": child.get("categoryName", ""),
                        "isLeaf": "Yes" if child.get("isLeaf") else "No",
                    })
                print_table(
                    child_data,
                    ["id", "name", "isLeaf"],
                    ["ID", "Name", "Leaf"],
                )

            # Aspects
            if aspects_data and "required" in aspects_data:
                if aspects_data["required"]:
                    print(f"\nRequired Aspects ({len(aspects_data['required'])}):")
                    for asp in aspects_data["required"]:
                        values = asp.get("exampleValues", [])
                        values_str = ", ".join(values[:3]) if values else ""
                        print(f"  - {asp['name']}: {values_str}...")
                if aspects_data.get("recommended"):
                    print(f"\nRecommended Aspects ({len(aspects_data['recommended'])}):")
                    for asp in aspects_data["recommended"][:5]:
                        values = asp.get("exampleValues", [])
                        values_str = ", ".join(values[:3]) if values else ""
                        print(f"  - {asp['name']}: {values_str}...")
        else:
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("tree")
def categories_tree(
    category_id: str = typer.Argument(
        None,
        help="Parent category ID to browse (omit for root-level categories)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID (EBAY_US, EBAY_GB, EBAY_AU, etc.)"
    ),
    depth: int = typer.Option(1, "--depth", "-d", help="How many levels deep to show (1-3)"),
    flat: bool = typer.Option(False, "--flat", help="Flatten hierarchy into a single list"),
):
    """
    Browse the category tree from a parent category.

    Shows child categories of the specified parent. Use this to drill down
    into the category hierarchy to find the right leaf category for your item.

    Examples:
        ebay categories tree                    # Show top-level categories
        ebay categories tree 220                # Browse Toys & Hobbies
        ebay categories tree 220 --table        # Show as table
        ebay categories tree 220 --depth 2      # Show 2 levels deep
        ebay categories tree 183448 --flat      # Flatten hierarchy
    """
    try:
        tree_id = MARKETPLACE_TREE_IDS.get(marketplace.upper(), "0")
        client = TaxonomyClient()

        # Clamp depth
        depth = max(1, min(depth, 3))

        if not category_id:
            # For root level, we need to get the whole tree and just show level 1
            # This is expensive, so we limit it
            # Actually, let's use a well-known root category instead
            # Root category ID for EBAY_US is special - use a search approach
            print_error("Please specify a category ID. Use 'ebay categories search <query>' to find categories.")
            raise typer.Exit(1)

        result = client.get_category_subtree(category_id, tree_id)
        root_node = result.get("categorySubtreeNode", {})

        def collect_nodes(node: dict, current_depth: int, max_depth: int) -> list:
            """Collect nodes up to max_depth levels."""
            if current_depth > max_depth:
                return []

            category = node.get("category", {})
            is_leaf = node.get("leafCategoryTreeNode", False)
            level = node.get("categoryTreeNodeLevel", 0)

            item = {
                "categoryId": category.get("categoryId", ""),
                "categoryName": category.get("categoryName", ""),
                "level": level,
                "depth": current_depth,
                "isLeaf": is_leaf,
            }

            result_nodes = [item]

            if not is_leaf and current_depth < max_depth:
                children = node.get("childCategoryTreeNodes", [])
                for child in children:
                    result_nodes.extend(collect_nodes(child, current_depth + 1, max_depth))

            return result_nodes

        # Collect starting from children of the root node (depth 1)
        nodes = []
        root_children = root_node.get("childCategoryTreeNodes", [])
        for child in root_children:
            nodes.extend(collect_nodes(child, 1, depth))

        # If no children, show the node itself (it's a leaf)
        if not nodes and root_node:
            category = root_node.get("category", {})
            nodes = [{
                "categoryId": category.get("categoryId", ""),
                "categoryName": category.get("categoryName", ""),
                "level": root_node.get("categoryTreeNodeLevel", 0),
                "depth": 0,
                "isLeaf": root_node.get("leafCategoryTreeNode", False),
            }]

        if table:
            if not nodes:
                print("No categories found.")
                return

            table_data = []
            for node in nodes:
                indent = "  " * (node.get("depth", 1) - 1) if not flat else ""
                table_data.append({
                    "id": node.get("categoryId", ""),
                    "name": f"{indent}{node.get('categoryName', '')}",
                    "isLeaf": "Yes" if node.get("isLeaf") else "No",
                })

            print_table(
                table_data,
                ["id", "name", "isLeaf"],
                ["Category ID", "Name", "Leaf"],
            )
        else:
            root_cat = root_node.get("category", {})
            output = {
                "parentCategoryId": category_id,
                "parentCategoryName": root_cat.get("categoryName", ""),
                "categoryTreeId": tree_id,
                "depth": depth,
                "total": len(nodes),
                "categories": nodes,
            }
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("conditions")
def categories_conditions(
    category_id: str = typer.Argument(..., help="Category ID to get valid conditions for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    marketplace: str = typer.Option(
        "EBAY_US",
        "--marketplace",
        "-m",
        help="eBay marketplace ID (EBAY_US, EBAY_GB, EBAY_AU, etc.)"
    ),
):
    """
    List valid item conditions for a category.

    Uses the eBay Metadata API to retrieve which condition values are
    accepted when listing items in the specified category.

    Examples:
        ebay categories conditions 261329
        ebay categories conditions 261329 --table
        ebay categories conditions 183448
    """
    try:
        from ..client import get_client
        from ..models.listing import CONDITION_ID_TO_ENUM

        client = get_client()
        result = client.get_item_condition_policies(
            marketplace_id=marketplace,
            category_ids=[category_id],
        )

        policies = result.get("itemConditionPolicies", [])
        if not policies:
            print_error(f"No condition policies found for category {category_id}")
            raise typer.Exit(1)

        policy = policies[0]
        conditions = policy.get("itemConditions", [])
        condition_required = policy.get("itemConditionRequired", False)

        # Enrich with enum names
        enriched = []
        for cond in conditions:
            cond_id = cond.get("conditionId", "")
            enriched.append({
                "conditionId": cond_id,
                "conditionEnum": CONDITION_ID_TO_ENUM.get(cond_id, "UNKNOWN"),
                "description": cond.get("conditionDescription", ""),
            })

        if table:
            print_table(
                enriched,
                ["conditionId", "conditionEnum", "description"],
                ["Condition ID", "Enum Value", "Description"],
            )
        else:
            print_json({
                "categoryId": category_id,
                "marketplace": marketplace,
                "conditionRequired": condition_required,
                "conditions": enriched,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))
