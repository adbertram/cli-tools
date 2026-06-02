"""Transaction rules commands for Monarch CLI."""
import json
from functools import wraps
from typing import Optional, List

import typer

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_error, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage transaction rules")

COMMAND_CREDENTIALS = {
    cmd: ["username_password"] for cmd in ("list", "get", "create", "update", "delete")
}

# ----- helpers -----

_RULE_OUTPUT_KEYS = (
    "id", "merchantCriteria", "amountCriteria", "categoryIds", "accountIds",
    "setCategoryAction", "setMerchantAction", "addTagsAction",
    "splitTransactionsAction", "setHideFromReportsAction", "reviewStatusAction",
    "sendNotificationAction", "needsReviewByUserAction",
    "unassignNeedsReviewByUserAction", "linkGoalAction",
    "merchantCriteriaUseOriginalStatement", "recentApplicationCount", "lastAppliedAt",
)
_LIST_VALUED_KEYS = {"merchantCriteria", "categoryIds", "accountIds", "addTagsAction"}

# Action key -> (gate, formatter) for the rules-list table summary.
_ACTION_SUMMARY_SPECS = (
    ("setCategoryAction", "truthy",   lambda v: f"category={v.get('name')}"),
    ("setMerchantAction", "truthy",   lambda v: f"merchant={v.get('name')}"),
    ("addTagsAction",     "truthy",   lambda v: f"tags={','.join(t.get('name', '') for t in v)}"),
    ("setHideFromReportsAction", "not_none", lambda v: f"hideFromReports={v}"),
    ("reviewStatusAction",       "truthy",   lambda v: f"reviewStatus={v}"),
    ("sendNotificationAction",   "truthy",   lambda v: "notify=true"),
    ("splitTransactionsAction",  "truthy",   lambda v: "split=true"),
)
_GATES = {"truthy": bool, "not_none": lambda v: v is not None}


def _typer_error_boundary(func):
    """Map any non-Exit exception to a typer.Exit through handle_error."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except Exception as e:  # noqa: BLE001 — CLI boundary
            raise typer.Exit(handle_error(e))
    return wrapper


def _normalize_rule(rule: dict) -> dict:
    """Project a raw rule into a stable, flat-ish dict for CLI output."""
    return {
        k: ((rule.get(k) or []) if k in _LIST_VALUED_KEYS else rule.get(k))
        for k in _RULE_OUTPUT_KEYS
    }


def _summarize_criteria(criteria) -> str:
    if not criteria:
        return ""
    items = criteria if isinstance(criteria, list) else [criteria]
    return "; ".join(f"{c.get('operator', '')}={c.get('value', '')}" for c in items)


def _summarize_action(rule: dict) -> str:
    parts = []
    for key, gate, fmt in _ACTION_SUMMARY_SPECS:
        value = rule.get(key)
        if _GATES[gate](value):
            parts.append(fmt(value))
    return "; ".join(parts)


def _render_rule(rule: dict, *, table: bool) -> None:
    """Print a single rule as JSON or as a field/value table."""
    normalized = _normalize_rule(rule)
    if not table:
        print_json(normalized)
        return
    rows = [
        {"field": k, "value": v if isinstance(v, str) else json.dumps(v)}
        for k, v in normalized.items()
    ]
    print_table(rows, ["field", "value"], ["Field", "Value"])


def _parse_merchant_criteria(values: Optional[List[str]]) -> Optional[List[dict]]:
    """Parse one or more 'operator:value' (or bare 'value' → contains) tokens."""
    if not values:
        return None
    out = []
    for raw in values:
        op, sep, val = raw.partition(":")
        if not sep:
            op, val = "contains", raw
        op = op.strip() or "contains"
        val = val.strip()
        if not val:
            raise typer.BadParameter(f"Empty merchant criteria value in '{raw}'")
        out.append({"operator": op, "value": val})
    return out


def _parse_amount_criteria(spec: Optional[str], is_expense: Optional[bool]) -> Optional[dict]:
    """Parse '--amount op:value' or '--amount between:lower:upper'."""
    if spec is None:
        return None
    parts = spec.split(":")
    if len(parts) < 2:
        raise typer.BadParameter(
            "amount criteria must be 'operator:value' or 'between:lower:upper'"
        )
    op = parts[0].strip()
    try:
        if op == "between":
            if len(parts) != 3:
                raise typer.BadParameter("between criteria must be 'between:lower:upper'")
            crit: dict = {"operator": "between", "valueRange": {
                "lower": float(parts[1]), "upper": float(parts[2])}}
        else:
            crit = {"operator": op, "value": float(parts[1])}
    except ValueError as exc:
        raise typer.BadParameter(f"amount values must be numbers: {exc}")
    if is_expense is not None:
        crit["isExpense"] = is_expense
    return crit


# ----- commands -----

@app.command("list")
@_typer_error_boundary
def rules_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum rules to return"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f",
        help="Filter: field:op:value (e.g., id:eq:RULE_ID)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include",
    ),
):
    """
    List all transaction rules.

    Filter Examples:
        monarch rules list --filter "id:eq:RULE_ID"
    """
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    rows = [_normalize_rule(r) for r in get_client().get_transaction_rules()[:limit]]
    if filter:
        rows = apply_filters(rows, filter)
    if properties:
        keep = {p.strip() for p in properties.split(",")}
        rows = [{k: v for k, v in r.items() if k in keep} for r in rows]

    if not table:
        print_json(rows)
        return

    print_table(
        [
            {
                "id": r.get("id", ""),
                "merchant": _summarize_criteria(r.get("merchantCriteria") or []),
                "amount": _summarize_criteria(r.get("amountCriteria")),
                "action": _summarize_action(r),
            }
            for r in rows
        ],
        ["id", "merchant", "amount", "action"],
        ["ID", "Merchant", "Amount", "Action"],
    )


@app.command("get")
@_typer_error_boundary
def rules_get(
    rule_id: str = typer.Argument(..., help="Rule ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific transaction rule."""
    rule = get_client().get_transaction_rule(rule_id)
    if rule is None:
        print_error(f"Rule not found: {rule_id}")
        raise typer.Exit(1)
    _render_rule(rule, table=table)


@app.command("create")
@_typer_error_boundary
def rules_create(
    merchant: Optional[List[str]] = typer.Option(
        None, "--merchant", "-m",
        help="Merchant criterion 'operator:value' (e.g., contains:amazon). Repeatable.",
    ),
    amount: Optional[str] = typer.Option(
        None, "--amount", "-a",
        help="Amount criterion. Forms: 'op:value' (gt:20) or 'between:lower:upper' (between:50:200).",
    ),
    expense: Optional[bool] = typer.Option(
        None, "--expense/--income",
        help="When --amount is set, apply only to expenses (default) or income.",
    ),
    category_id: Optional[List[str]] = typer.Option(
        None, "--category-id",
        help="Filter criterion: only match transactions currently in this category ID. Repeatable.",
    ),
    account_id: Optional[List[str]] = typer.Option(
        None, "--account-id",
        help="Filter criterion: only match transactions on this account ID. Repeatable.",
    ),
    set_category: Optional[str] = typer.Option(
        None, "--set-category", help="Action: set this category ID on matching transactions.",
    ),
    set_merchant: Optional[str] = typer.Option(
        None, "--set-merchant", help="Action: set this merchant ID on matching transactions.",
    ),
    add_tag: Optional[List[str]] = typer.Option(
        None, "--add-tag", help="Action: add this tag ID. Repeatable.",
    ),
    use_original_statement: bool = typer.Option(
        False, "--use-original-statement",
        help="Match merchant criteria against the original bank statement text.",
    ),
    apply_to_existing: bool = typer.Option(
        False, "--apply-to-existing",
        help="Apply the new rule retroactively to existing transactions.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display created rule as table"),
):
    """
    Create a new transaction rule.

    A rule needs at least one criterion (--merchant, --amount, --category-id, or --account-id)
    and at least one action (--set-category, --set-merchant, --add-tag).

    Examples:
        monarch rules create --merchant contains:amazon --set-category 12345
        monarch rules create --amount gt:1000 --expense --set-category 67890
        monarch rules create --merchant equals:"Whole Foods" --add-tag TAG_ID
    """
    merchant_criteria = _parse_merchant_criteria(merchant)
    amount_criteria = _parse_amount_criteria(amount, expense)

    if not any([merchant_criteria, amount_criteria, category_id, account_id]):
        print_error(
            "Rule needs at least one criterion: --merchant, --amount, --category-id, or --account-id"
        )
        raise typer.Exit(2)
    if not any([set_category, set_merchant, add_tag]):
        print_error(
            "Rule needs at least one action: --set-category, --set-merchant, or --add-tag"
        )
        raise typer.Exit(2)

    rule = get_client().create_transaction_rule(
        merchant_criteria=merchant_criteria,
        amount_criteria=amount_criteria,
        category_ids=category_id or None,
        account_ids=account_id or None,
        set_category_action=set_category,
        set_merchant_action=set_merchant,
        add_tags_action=add_tag or None,
        merchant_criteria_use_original_statement=use_original_statement,
        apply_to_existing_transactions=apply_to_existing,
    )
    _render_rule(rule, table=table)


@app.command("update")
@_typer_error_boundary
def rules_update(
    rule_id: str = typer.Argument(..., help="Rule ID to update"),
    merchant: Optional[List[str]] = typer.Option(
        None, "--merchant", "-m",
        help="Replace merchant criteria. 'operator:value', repeatable.",
    ),
    amount: Optional[str] = typer.Option(
        None, "--amount", "-a",
        help="Replace amount criterion. 'operator:value' or 'between:lower:upper'.",
    ),
    expense: Optional[bool] = typer.Option(
        None, "--expense/--income",
        help="When --amount is set, apply only to expenses or income.",
    ),
    category_id: Optional[List[str]] = typer.Option(
        None, "--category-id", help="Replace category filter IDs. Repeatable.",
    ),
    account_id: Optional[List[str]] = typer.Option(
        None, "--account-id", help="Replace account filter IDs. Repeatable.",
    ),
    set_category: Optional[str] = typer.Option(
        None, "--set-category", help="Set the setCategory action. Pass empty string to clear.",
    ),
    set_merchant: Optional[str] = typer.Option(
        None, "--set-merchant", help="Set the setMerchant action. Pass empty string to clear.",
    ),
    add_tag: Optional[List[str]] = typer.Option(
        None, "--add-tag", help="Replace addTags action with these tag IDs. Repeatable.",
    ),
    use_original_statement: Optional[bool] = typer.Option(
        None, "--use-original-statement/--no-use-original-statement",
        help="Toggle 'match against original statement text'.",
    ),
    apply_to_existing: Optional[bool] = typer.Option(
        None, "--apply-to-existing/--no-apply-to-existing",
        help="Toggle retroactive application.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display updated rule as table"),
):
    """
    Update an existing transaction rule. Only the fields you pass are sent.

    Examples:
        monarch rules update RULE_ID --set-category NEW_CAT_ID
        monarch rules update RULE_ID --merchant contains:netflix
        monarch rules update RULE_ID --apply-to-existing
    """
    rule = get_client().update_transaction_rule(
        rule_id=rule_id,
        merchant_criteria=_parse_merchant_criteria(merchant),
        amount_criteria=_parse_amount_criteria(amount, expense),
        category_ids=category_id or None,
        account_ids=account_id or None,
        # Empty-string sentinel clears the action server-side; None leaves it untouched.
        set_category_action=None if set_category is None else (set_category or None),
        set_merchant_action=None if set_merchant is None else (set_merchant or None),
        add_tags_action=add_tag or None,
        merchant_criteria_use_original_statement=use_original_statement,
        apply_to_existing_transactions=apply_to_existing,
    )
    _render_rule(rule, table=table)


@app.command("delete")
@_typer_error_boundary
def rules_delete(
    rule_id: str = typer.Argument(..., help="Rule ID to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
):
    """
    Delete a transaction rule.

    Examples:
        monarch rules delete RULE_ID --force
    """
    if not force and not typer.confirm(f"Delete rule {rule_id}?"):
        typer.echo("Aborted", err=True)
        raise typer.Exit(1)
    get_client().delete_transaction_rule(rule_id)
    print_json({"id": rule_id, "deleted": True})
