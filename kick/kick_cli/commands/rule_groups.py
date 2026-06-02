"""Rule groups commands for Kick CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_info

app = typer.Typer(help="Manage Kick rule groups")

# Nested app for rules subcommands
rules_app = typer.Typer(help="Manage rules within rule groups")
app.add_typer(rules_app, name="rules")


@app.command("list")
def rule_groups_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of rule groups to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
    rule_type: str = typer.Option("transaction", "--type", help="Filter by rule type (transaction, accounting, transfer, split, all)"),
    include_rules: bool = typer.Option(False, "--include-rules", "-r", help="Include rules in output"),
):
    """
    List all rule groups.

    Examples:
        kick rule-groups list
        kick rule-groups list --table
        kick rule-groups list --type all
        kick rule-groups list --include-rules
    """
    try:
        client = get_client()
        result = client.list_rule_groups()
        rule_groups = result.get("ruleGroups", [])
        transaction_counts = result.get("transactionCounts", {})

        # Filter by type (defaults to transaction)
        if rule_type != "all":
            rule_groups = [g for g in rule_groups if g.get("type") == rule_type]

        # Apply client-side filtering
        if filter:
            rule_groups = apply_filters(rule_groups, filter)

        # Apply limit
        rule_groups = rule_groups[:limit]

        if table:
            table_data = []
            for group in rule_groups:
                rules = group.get("rules", [])
                # Calculate total transactions affected by rules in this group
                total_txns = sum(
                    transaction_counts.get(rule["id"], 0) for rule in rules
                )
                table_data.append({
                    "id": group.get("id", "")[:12] + "...",
                    "name": group.get("name", ""),
                    "type": group.get("type", ""),
                    "icon": group.get("icon", ""),
                    "rules": len(rules),
                    "transactions": total_txns,
                    "default": "Yes" if group.get("isDefault") else "No",
                })

            print_table(
                table_data,
                ["id", "name", "type", "icon", "rules", "transactions", "default"],
                ["ID", "Name", "Type", "Icon", "Rules", "Txns", "Default"],
            )
            print_info(f"Showing {len(rule_groups)} rule groups")
        else:
            if include_rules:
                print_json(rule_groups)
            else:
                # Strip rules for cleaner output
                clean_groups = []
                for group in rule_groups:
                    clean = {k: v for k, v in group.items() if k != "rules"}
                    clean["ruleCount"] = len(group.get("rules", []))
                    clean_groups.append(clean)
                print_json(clean_groups)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def rule_groups_get(
    group_id: str = typer.Argument(..., help="The rule group UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    include_rules: bool = typer.Option(True, "--include-rules/--no-rules", help="Include rules in output"),
):
    """
    Get details for a specific rule group.

    Examples:
        kick rule-groups get 43b5276c-57a5-4c5f-bf76-c71675d8662a
        kick rule-groups get 43b5276c-57a5-4c5f-bf76-c71675d8662a --table
        kick rule-groups get 43b5276c-57a5-4c5f-bf76-c71675d8662a --no-rules
    """
    try:
        client = get_client()
        group = client.get_rule_group(group_id)

        if table:
            summary = [{
                "id": group.get("id", ""),
                "name": group.get("name", ""),
                "type": group.get("type", ""),
                "icon": group.get("icon", ""),
                "rules": len(group.get("rules", [])),
                "default": "Yes" if group.get("isDefault") else "No",
            }]

            print_table(
                summary,
                ["id", "name", "type", "icon", "rules", "default"],
                ["ID", "Name", "Type", "Icon", "Rules", "Default"],
            )
        else:
            if not include_rules:
                group = {k: v for k, v in group.items() if k != "rules"}
                group["ruleCount"] = len(group.get("rules", []))
            print_json(group)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("add")
def rule_groups_add(
    name: str = typer.Argument(..., help="Name for the rule group"),
    rule_type: str = typer.Option("transaction", "--type", "-t", help="Rule group type (transaction, accounting, transfer, split)"),
    icon: str = typer.Option("briefcase", "--icon", "-i", help="Icon identifier (briefcase, bank, etc.)"),
    order: Optional[int] = typer.Option(None, "--order", "-o", help="Order position (auto-calculated if not provided)"),
):
    """
    Create a new rule group.

    Examples:
        kick rule-groups add "My Rules"
        kick rule-groups add "Accounting Rules" --type accounting --icon bank
        kick rule-groups add "Transfer Rules" --type transfer --order 5
    """
    try:
        client = get_client()

        # Validate rule type
        valid_types = ["transaction", "accounting", "transfer", "split"]
        if rule_type not in valid_types:
            from cli_tools_shared.output import print_error
            print_error(f"Invalid type '{rule_type}'. Must be one of: {', '.join(valid_types)}")
            raise typer.Exit(1)

        group = client.create_rule_group(
            name=name,
            rule_type=rule_type,
            icon=icon,
            order=order,
        )

        from cli_tools_shared.output import print_success
        print_success(f"Created rule group '{group.get('name')}' (ID: {group.get('id')})")
        print_json(group)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def rule_groups_delete(
    group_id: str = typer.Argument(..., help="The rule group UUID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a rule group.

    Examples:
        kick rule-groups delete 019b6ff1-0d3b-76ad-8063-22dd79ef4402
        kick rule-groups delete 019b6ff1-0d3b-76ad-8063-22dd79ef4402 --force
    """
    try:
        client = get_client()

        # Get the group first to show its name
        group = client.get_rule_group(group_id)
        group_name = group.get("name", group_id)
        rule_count = len(group.get("rules", []))

        if not force:
            # Confirm deletion
            if rule_count > 0:
                confirm = typer.confirm(
                    f"Delete rule group '{group_name}' with {rule_count} rules?"
                )
            else:
                confirm = typer.confirm(f"Delete rule group '{group_name}'?")

            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client.delete_rule_group(group_id)

        from cli_tools_shared.output import print_success
        print_success(f"Deleted rule group '{group_name}'")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@rules_app.command("add")
def rules_add(
    group_id: str = typer.Option(..., "--group", "-g", help="Rule group UUID to add the rule to"),
    counterparty: str = typer.Option(..., "--counterparty", "-c", help="Counterparty name to match"),
    entity: str = typer.Option(..., "--entity", "-e", help="Entity name or ID to match"),
    category: Optional[str] = typer.Option(None, "--category", help="Category name or ID to set"),
    apply_existing: bool = typer.Option(False, "--apply-existing", help="Apply rule to existing transactions"),
):
    """
    Add a new rule to a rule group.

    Examples:
        kick rule-groups rules add -g 43b5276c-... -c "Verizon" -e "Example LLC" --category "Utilities"
        kick rule-groups rules add -g 43b5276c-... -c "Amazon" -e "My Business" --category "Shopping" --apply-existing
    """
    try:
        client = get_client()

        if not category:
            from cli_tools_shared.output import print_error
            print_error("Action required: --category")
            raise typer.Exit(1)

        # Build lookups
        result = client.list_rule_groups()
        counterparties = {cp["name"].lower(): cp for cp in result.get("counterparties", [])}

        workspaces = client.get_workspaces()
        entities_lookup = {}
        all_entity_ids = []
        for ws_data in workspaces:
            for ent in ws_data["workspace"].get("entities", []):
                entities_lookup[ent["name"].lower()] = ent
                entities_lookup[str(ent["id"])] = ent
                all_entity_ids.append(ent["id"])

        categories_list = client.list_categories(include_subcategories=True)
        categories_lookup = {cat["label"].lower(): cat for cat in categories_list}
        for cat in categories_list:
            categories_lookup[cat["id"]] = cat

        # Build conditions
        conditions = []

        # Entity condition (required by API)
        ent = entities_lookup.get(entity.lower()) or entities_lookup.get(entity)
        if not ent:
            from cli_tools_shared.output import print_error
            print_error(f"Entity '{entity}' not found")
            raise typer.Exit(1)
        conditions.append({
            "conditionType": "entity",
            "value": [ent["id"]],
            "transferDirection": None,
        })

        # Counterparty condition
        cp = counterparties.get(counterparty.lower())
        if not cp:
            from cli_tools_shared.output import print_error
            print_error(f"Counterparty '{counterparty}' not found. Available: {', '.join(sorted(counterparties.keys())[:10])}...")
            raise typer.Exit(1)
        conditions.append({
            "conditionType": "counterparty",
            "value": cp["id"],
            "transferDirection": None,
        })

        # Build actions
        actions = []

        cat = categories_lookup.get(category.lower()) or categories_lookup.get(category)
        if not cat:
            from cli_tools_shared.output import print_error
            print_error(f"Category '{category}' not found")
            raise typer.Exit(1)
        actions.append({
            "actionType": "category",
            "value": cat["id"],
            "order": 0,
            "transferDirection": None,
        })

        # Create the rule
        rule = client.create_rule(
            group_id=group_id,
            conditions=conditions,
            actions=actions,
            apply_to_existing=apply_existing,
        )

        from cli_tools_shared.output import print_success
        print_success(f"Created rule (ID: {rule.get('id')})")
        print_json(rule)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@rules_app.command("delete")
def rules_delete(
    rule_id: str = typer.Argument(..., help="The rule UUID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a rule.

    Examples:
        kick rule-groups rules delete 019b6ffa-3522-73e9-b3c2-84b3b2f18032
        kick rule-groups rules delete 019b6ffa-3522-73e9-b3c2-84b3b2f18032 --force
    """
    try:
        client = get_client()

        # Find the rule to show details before deletion
        result = client.list_rule_groups()
        rule_info = None
        for group in result.get("ruleGroups", []):
            for rule in group.get("rules", []):
                if rule["id"] == rule_id:
                    rule_info = {
                        "id": rule_id,
                        "groupName": group.get("name", ""),
                        "conditions": len(rule.get("conditions", [])),
                        "actions": len(rule.get("actions", [])),
                    }
                    break
            if rule_info:
                break

        if not rule_info:
            from cli_tools_shared.output import print_error
            print_error(f"Rule {rule_id} not found")
            raise typer.Exit(1)

        if not force:
            confirm = typer.confirm(
                f"Delete rule from group '{rule_info['groupName']}' "
                f"({rule_info['conditions']} conditions, {rule_info['actions']} actions)?"
            )
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client.delete_rule(rule_id)

        from cli_tools_shared.output import print_success
        print_success(f"Deleted rule {rule_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@rules_app.command("conditions")
def rules_conditions(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List available rule condition types.

    Examples:
        kick rule-groups rules conditions
        kick rule-groups rules conditions --table
    """
    # Condition types discovered from Kick API
    conditions = [
        {
            "type": "entity",
            "description": "Match transactions by business entity (kick entities list)",
            "value_type": "array of entity IDs",
            "example": "[16044, 16045]",
        },
        {
            "type": "counterparty",
            "description": "Match by counterparty/vendor (kick rule-groups list --include-rules)",
            "value_type": "counterparty UUID",
            "example": "019194f3-1be6-7fb3-84e0-e73fee5b02e8",
        },
        {
            "type": "amount",
            "description": "Match transactions by amount range",
            "value_type": "amount object",
            "example": '{"min": 100, "max": 500}',
        },
        {
            "type": "category",
            "description": "Match by existing category (kick categories list)",
            "value_type": "category UUID",
            "example": "01956661-459c-74c3-94d8-b52a43fbae24",
        },
        {
            "type": "date",
            "description": "Match transactions by date range",
            "value_type": "date object",
            "example": '{"from": "2024-01-01", "to": "2024-12-31"}',
        },
        {
            "type": "financial_accounts",
            "description": "Match by financial account (kick entities get <id>)",
            "value_type": "array of account IDs",
            "example": "[12345]",
        },
    ]

    if table:
        print_table(
            conditions,
            ["type", "description", "value_type"],
            ["Type", "Description", "Value Type"],
        )
        print_info(f"{len(conditions)} condition types available")
    else:
        print_json(conditions)


@rules_app.command("actions")
def rules_actions(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List available rule action types.

    Examples:
        kick rule-groups rules actions
        kick rule-groups rules actions --table
    """
    # Action types discovered from Kick API
    actions = [
        {
            "type": "category",
            "description": "Set the transaction category (kick categories list)",
            "value_type": "category UUID",
            "example": "01956661-459c-74c3-94d8-b52a43fbae24",
        },
        {
            "type": "entity",
            "description": "Set the transaction entity (kick entities list)",
            "value_type": "entity ID",
            "example": "16044",
        },
        {
            "type": "counterparty",
            "description": "Set or override counterparty (kick rule-groups list --include-rules)",
            "value_type": "counterparty UUID",
            "example": "019194f3-1be6-7fb3-84e0-e73fee5b02e8",
        },
        {
            "type": "memo",
            "description": "Set a memo/note on the transaction",
            "value_type": "string",
            "example": "Monthly subscription",
        },
    ]

    if table:
        print_table(
            actions,
            ["type", "description", "value_type"],
            ["Type", "Description", "Value Type"],
        )
        print_info(f"{len(actions)} action types available")
    else:
        print_json(actions)


@rules_app.command("list")
def rules_list(
    group_id: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by rule group UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    rule_type: str = typer.Option("transaction", "--type", help="Filter by rule group type (transaction, accounting, transfer, split, all)"),
):
    """
    List all rules across rule groups.

    Examples:
        kick rule-groups rules list
        kick rule-groups rules list --table
        kick rule-groups rules list --group 43b5276c-57a5-4c5f-bf76-c71675d8662a
        kick rule-groups rules list --type all
    """
    try:
        client = get_client()
        result = client.list_rule_groups()
        rule_groups = result.get("ruleGroups", [])
        counterparties = {cp["id"]: cp for cp in result.get("counterparties", [])}
        transaction_counts = result.get("transactionCounts", {})

        # Build entity lookup from workspaces
        entities_lookup = {}
        workspaces = client.get_workspaces()
        for ws_data in workspaces:
            for entity in ws_data["workspace"].get("entities", []):
                entities_lookup[entity["id"]] = entity.get("name", str(entity["id"]))

        # Build category lookup
        categories_lookup = {}
        categories = client.list_categories(include_subcategories=True)
        for cat in categories:
            categories_lookup[cat["id"]] = cat.get("label", cat["id"][:8])

        # Filter by type (defaults to transaction)
        if rule_type != "all":
            rule_groups = [g for g in rule_groups if g.get("type") == rule_type]

        # Filter by group ID if specified
        if group_id:
            rule_groups = [g for g in rule_groups if g.get("id") == group_id]

        # Flatten rules from all groups
        all_rules = []
        for group in rule_groups:
            for rule in group.get("rules", []):
                rule_copy = dict(rule)
                rule_copy["groupName"] = group.get("name", "")
                rule_copy["groupType"] = group.get("type", "")
                rule_copy["transactionCount"] = transaction_counts.get(rule["id"], 0)
                all_rules.append(rule_copy)

        if table:
            table_data = []
            for rule in all_rules:
                # Get condition summary
                conditions = rule.get("conditions", [])
                condition_summary = []
                for cond in conditions:
                    cond_type = cond.get("conditionType", "")
                    cond_value = cond.get("value", "")
                    if cond_type == "counterparty":
                        cp = counterparties.get(cond_value, {})
                        condition_summary.append(cp.get("name", str(cond_value)[:8]))
                    elif cond_type == "entity":
                        entity_ids = cond_value if isinstance(cond_value, list) else [cond_value]
                        entity_names = [entities_lookup.get(eid, str(eid)) for eid in entity_ids]
                        condition_summary.append(", ".join(entity_names))
                    else:
                        condition_summary.append(f"{cond_type}:{str(cond_value)[:12]}")

                # Get action summary
                actions = rule.get("actions", [])
                action_summary = []
                for action in actions:
                    action_type = action.get("actionType", "")
                    action_value = action.get("value", "")
                    if action_type == "category":
                        cat_name = categories_lookup.get(action_value, str(action_value)[:8])
                        action_summary.append(cat_name)
                    else:
                        action_summary.append(f"{action_type}:{str(action_value)[:8]}")

                table_data.append({
                    "id": rule.get("id", "")[:12] + "...",
                    "group": rule.get("groupName", ""),
                    "type": rule.get("groupType", ""),
                    "conditions": " + ".join(condition_summary)[:35],
                    "action": ", ".join(action_summary)[:25],
                    "txns": rule.get("transactionCount", 0),
                    "order": rule.get("order", 0),
                })

            print_table(
                table_data,
                ["id", "group", "type", "conditions", "action", "txns", "order"],
                ["ID", "Group", "Type", "Conditions", "Action", "Txns", "Order"],
            )
            print_info(f"Showing {len(all_rules)} rules")
        else:
            print_json(all_rules)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "add": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "rules": [
        "custom"
    ]
}
