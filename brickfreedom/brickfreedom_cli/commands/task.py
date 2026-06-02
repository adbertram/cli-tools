"""Task commands for Brickfreedom CLI."""
import typer
from typing import List, Optional
from enum import Enum

from cli_tools_shared.activity_log import get_activity_logger
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.filter_map import FilterMap

activity_logger = get_activity_logger("brickfreedom")

COMMAND_CREDENTIALS = {
    "add": [
        "browser_session"
    ],
    "complete": [
        "browser_session"
    ],
    "create": [
        "browser_session"
    ],
    "delete": [
        "browser_session"
    ],
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

app = typer.Typer(help="Manage Brickfreedom tasks", no_args_is_help=True)


class TaskType(str, Enum):
    """Task type for filtering and creating structured tasks."""
    CUSTOMER_REPLACEMENT_PART = "customer-replacement-part"
    MISSING_PART = "missing-part"


@app.command("list")
def task_list(
    task_type: Optional[TaskType] = typer.Option(None, "--type", help="Filter by task type: customer-replacement-part, missing-part"),
    order_id: Optional[str] = typer.Option(None, "--order-id", "-o", help="Filter by order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    debug_unparsed: bool = typer.Option(False, "--debug-unparsed", help="Print raw task rows that did not match any known missing-part format (to stderr, prefixed with '[unparsed] ')"),
):
    """
    List tasks from My Tasks section on dashboard.

    Example:
        brickfreedom task list
        brickfreedom task list --table
        brickfreedom task list --filter completed:eq:false
        brickfreedom task list --type customer-replacement-part
        brickfreedom task list --type customer-replacement-part --order-id 30176576
    """
    try:
        activity_logger.info("Command task list")
        client = get_client()
        result = client.list_tasks()
        client.close()

        tasks = result.tasks

        # Apply client-side filters using standard filter system
        if filter:
            from ..models import create_task
            tasks = [create_task(t) for t in apply_filters([t.model_dump(mode="json") for t in tasks], filter)]

        # Filter by task type
        if task_type == TaskType.CUSTOMER_REPLACEMENT_PART:
            from ..models import ReplacementPartTask, ReplacementPartTaskList
            replacement_tasks = []
            for task in tasks:
                parsed = ReplacementPartTask.from_task_text(task.index, task.text, task.completed)
                if parsed:
                    # Apply order_id filter if specified
                    if order_id:
                        if parsed.order_id == order_id:
                            replacement_tasks.append(parsed)
                    else:
                        replacement_tasks.append(parsed)

            # Apply limit
            replacement_tasks = replacement_tasks[:limit]

            if table:
                rows = [
                    {
                        "index": t.index,
                        "platform": t.platform.value[:2].upper(),
                        "customer": t.customer_name[:20],
                        "order": t.order_id,
                        "part": t.item_no,
                        "color": t.color[:15],
                        "qty": t.qty,
                        "loc": t.location or "",
                        "done": "✓" if t.completed else "",
                    }
                    for t in replacement_tasks
                ]
                print_table(rows, ["index", "platform", "customer", "order", "part", "color", "qty", "loc", "done"],
                           ["#", "PL", "Customer", "Order", "Part", "Color", "Qty", "Loc", "Done"])
            else:
                print_json(ReplacementPartTaskList(tasks=replacement_tasks))
            return

        if task_type == TaskType.MISSING_PART:
            import sys
            from ..models import MissingPart, MissingPartList
            missing_parts = []
            unparsed_texts: List[str] = []
            for task in tasks:
                parsed = MissingPart.from_task_text(task.index, task.text, task.completed)
                if parsed:
                    # Apply order_id filter if specified
                    if order_id:
                        if parsed.order_id == order_id:
                            missing_parts.append(parsed)
                    else:
                        missing_parts.append(parsed)
                else:
                    unparsed_texts.append(task.text)

            unparsed_count = len(unparsed_texts)
            if unparsed_count:
                print(
                    f"[brickfreedom] WARNING: {unparsed_count} task row(s) did not match any known missing-part format and were dropped. "
                    f"Run `brickfreedom task list --type missing-part --debug-unparsed` to see them.",
                    file=sys.stderr,
                )
            if debug_unparsed:
                for raw in unparsed_texts:
                    print(f"[unparsed] {raw}", file=sys.stderr)

            # Apply limit
            missing_parts = missing_parts[:limit]

            if table:
                rows = [
                    {
                        "index": p.index,
                        "platform": p.platform.value,
                        "order": p.order_id,
                        "part": p.item_number,
                        "color": p.color_name[:15],
                        "qty": p.quantity,
                        "loc": p.location,
                        "done": "✓" if p.completed else "",
                    }
                    for p in missing_parts
                ]
                print_table(rows, ["index", "platform", "order", "part", "color", "qty", "loc", "done"],
                           ["#", "Platform", "Order", "Part", "Color", "Qty", "Loc", "Done"])
            else:
                result_model = MissingPartList(parts=missing_parts)
                # Emit unparsed_count as an additive top-level field on the JSON output.
                # Use the same dump shape print_json would use (no by_alias) to preserve
                # the existing JSON shape exactly.
                payload = result_model.model_dump()
                payload["unparsed_count"] = unparsed_count
                print_json(payload)
            return

        # Filter by order_id (search in text) if no type specified
        if order_id:
            tasks = [t for t in tasks if order_id in t.text]

        # Apply limit
        tasks = tasks[:limit]

        if table:
            rows = [
                {
                    "index": t.index,
                    "text": t.text[:60] + "..." if len(t.text) > 60 else t.text,
                    "completed": "✓" if t.completed else "",
                }
                for t in tasks
            ]
            print_table(rows, ["index", "text", "completed"], ["#", "Task", "Done"])
        else:
            # Return filtered result
            from ..models import TaskList
            print_json(TaskList(tasks=tasks))

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def task_get(
    index: int = typer.Argument(..., help="Task index (1-based)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific task by index.

    Example:
        brickfreedom task get 1
        brickfreedom task get 2 --table
    """
    try:
        activity_logger.info("Command task get index=%s", index)
        client = get_client()
        result = client.list_tasks()
        client.close()

        tasks = result.tasks
        if index < 1 or index > len(tasks):
            raise ClientError(f"Task {index} not found. There are {len(tasks)} tasks.")

        task = tasks[index - 1]

        if table:
            rows = [
                {
                    "index": task.index,
                    "text": task.text,
                    "completed": "✓" if task.completed else "",
                }
            ]
            print_table(rows, ["index", "text", "completed"], ["#", "Task", "Done"])
        else:
            print_json(task)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
@app.command("add", hidden=True)
def task_create(
    text: Optional[str] = typer.Argument(None, help="Task text to create (not needed for --type)"),
    task_type: Optional[TaskType] = typer.Option(None, "--type", "-t", help="Task type: customer-replacement-part"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Platform: bricklink or brickowl (required for customer-replacement-part)"),
    customer_name: Optional[str] = typer.Option(None, "--customer-name", help="Customer name (required for customer-replacement-part)"),
    order_id: Optional[str] = typer.Option(None, "--order-id", help="Order ID (required for customer-replacement-part)"),
    item_no: Optional[str] = typer.Option(None, "--item-no", help="Item/part number (required for customer-replacement-part)"),
    item_name: Optional[str] = typer.Option(None, "--item-name", help="Item name (required for customer-replacement-part)"),
    color: Optional[str] = typer.Option(None, "--color", help="Color name (required for customer-replacement-part)"),
    qty: int = typer.Option(1, "--qty", help="Quantity (default: 1)"),
    location: Optional[str] = typer.Option(None, "--location", help="Bin location (required for customer-replacement-part)"),
):
    """
    Create a new task in My Tasks.

    Example:
        brickfreedom task create "Ship pending orders"
        brickfreedom task add "Reply to customer"

        # Create structured replacement part task:
        brickfreedom task create --type customer-replacement-part \\
            --platform bricklink \\
            --customer-name "John Doe" \\
            --order-id "30176576" \\
            --item-no "3024" \\
            --item-name "Plate 1 x 1" \\
            --color "Light Bluish Gray" \\
            --qty 10 \\
            --location "I-BB001"

        # Create structured missing part task:
        brickfreedom task create --type missing-part \\
            --platform bricklink \\
            --order-id "30823995" \\
            --item-no "75270-1" \\
            --item-name "Instruction Book" \\
            --qty 1 \\
            --location "F-INS"

        # Missing part with color:
        brickfreedom task create --type missing-part \\
            --platform bricklink \\
            --order-id "30823995" \\
            --item-no "3008" \\
            --item-name "Brick 1 x 8" \\
            --color "Light Aqua" \\
            --qty 2 \\
            --location "C-0961"
    """
    try:
        activity_logger.info("Command task create")
        task_text = text

        # Handle customer-replacement-part type
        if task_type == TaskType.CUSTOMER_REPLACEMENT_PART:
            # Validate required fields
            missing = []
            if not platform:
                missing.append("--platform")
            elif platform.lower() not in ("bricklink", "brickowl"):
                raise ClientError(f"Invalid platform '{platform}'. Must be 'bricklink' or 'brickowl'")
            if not customer_name:
                missing.append("--customer-name")
            if not order_id:
                missing.append("--order-id")
            if not item_no:
                missing.append("--item-no")
            if not item_name:
                missing.append("--item-name")
            if not color:
                missing.append("--color")
            if not location:
                missing.append("--location")

            if missing:
                raise ClientError(f"Missing required options for customer-replacement-part: {', '.join(missing)}")

            # Format the task text using the model
            from ..models import ReplacementPartTask
            task_text = ReplacementPartTask.format_task_text(
                platform=platform.lower(),
                customer_name=customer_name,
                order_id=order_id,
                item_no=item_no,
                item_name=item_name,
                color=color,
                qty=qty,
                location=location
            )
        # Handle missing-part type
        elif task_type == TaskType.MISSING_PART:
            # Validate required fields
            missing = []
            if not platform:
                missing.append("--platform")
            elif platform.lower() not in ("bricklink", "brickowl"):
                raise ClientError(f"Invalid platform '{platform}'. Must be 'bricklink' or 'brickowl'")
            if not order_id:
                missing.append("--order-id")
            if not item_no:
                missing.append("--item-no")
            if not item_name:
                missing.append("--item-name")
            if not location:
                missing.append("--location")

            if missing:
                raise ClientError(f"Missing required options for missing-part: {', '.join(missing)}")

            # Format the task text using the model
            from ..models import MissingPart
            task_text = MissingPart.format_task_text(
                platform=platform.lower(),
                order_id=order_id,
                item_no=item_no,
                item_name=item_name,
                qty=qty,
                location=location,
                color=color
            )
        elif not text:
            raise ClientError("Task text is required (or use --type with options)")

        client = get_client()
        result = client.create_task(task_text)
        client.close()
        print_json(result)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("complete")
def task_complete(
    index: Optional[int] = typer.Argument(None, help="Task index (1-based) to mark complete"),
    bulk: bool = typer.Option(False, "--bulk", "-b", help="Mark all tasks as complete"),
    match_platform: Optional[str] = typer.Option(
        None,
        "--match-platform",
        help="Match a missing-part task by platform (bricklink|brickowl). Re-resolves the current task index by content. Cannot be combined with positional index.",
    ),
    match_order_id: Optional[str] = typer.Option(
        None,
        "--match-order-id",
        help="Match a missing-part task by marketplace order ID. Cannot be combined with positional index.",
    ),
    match_item_number: Optional[str] = typer.Option(
        None,
        "--match-item-number",
        help="Match a missing-part task by LEGO item number. Cannot be combined with positional index.",
    ),
    match_quantity: Optional[int] = typer.Option(
        None,
        "--match-quantity",
        help="Match a missing-part task by quantity (use to disambiguate when multiple rows match). Cannot be combined with positional index.",
    ),
):
    """
    Mark a task as complete by 1-based index, by content match, or --bulk.

    Three modes:

    1. Positional index (interactive use, fragile for scripts):
        brickfreedom task complete 1

    2. Bulk:
        brickfreedom task complete --bulk

    3. Match by missing-part attributes (stable for scripts — re-resolves the
       current index right before completing, so prior list-shifting completions
       cannot mark the wrong task):

        brickfreedom task complete \\
            --match-platform bricklink \\
            --match-order-id 30823995 \\
            --match-item-number 75270-1

       Add --match-quantity to disambiguate if multiple rows match.

    Exit codes for match mode:
      - 0: exactly one match, completed.
      - 1: zero matches OR multiple matches (ambiguous). JSON error printed to
           stdout describing the failure; resolve by passing more --match-* flags.
    """
    try:
        activity_logger.info("Command task complete")
        match_flags = {
            "platform": match_platform,
            "order_id": match_order_id,
            "item_number": match_item_number,
            "quantity": match_quantity,
        }
        any_match_flag = any(v is not None for v in match_flags.values())

        if any_match_flag:
            # Match mode: cannot mix with positional or --bulk.
            if index is not None or bulk:
                raise ClientError(
                    "--match-* flags cannot be combined with a positional index or --bulk. "
                    "Use either positional, --bulk, or --match-* (not multiple)."
                )
            _complete_by_match(match_flags)
            return

        client = get_client()
        if bulk:
            result = client.mark_all_completed()
        elif index is not None:
            result = client.complete_task(index)
        else:
            raise ClientError("Provide a task index, use --bulk, or use --match-* flags to complete a task")
        client.close()
        print_json(result)
    except typer.Exit:
        # _complete_by_match emits its own structured JSON before raising
        # typer.Exit — let that propagate untouched so the exit code is
        # preserved and we don't double-print an error message.
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _complete_by_match(match_flags: dict) -> None:
    """Complete a single missing-part task selected by content match.

    Re-fetches the live task list (bypassing the @cached layer) so the resolved
    index always reflects the dashboard's current row order. Fail-fast on zero
    or multiple matches — never auto-disambiguate.
    """
    import os
    from ..models import MissingPart

    client = get_client()
    try:
        # Bypass the @cached layer so prior completions in this session can't leave
        # us looking at a stale snapshot. The @cached decorator short-circuits
        # when CACHE_ENABLED is false.
        prior_cache_env = os.environ.get("CACHE_ENABLED")
        os.environ["CACHE_ENABLED"] = "false"
        try:
            task_list = client.list_tasks()
        finally:
            if prior_cache_env is None:
                os.environ.pop("CACHE_ENABLED", None)
            else:
                os.environ["CACHE_ENABLED"] = prior_cache_env
        tasks = task_list.tasks

        # Parse missing-part tasks and apply match filter.
        candidates = []
        for task in tasks:
            if task.completed:
                continue
            parsed = MissingPart.from_task_text(task.index, task.text, task.completed)
            if parsed is None:
                continue
            if match_flags["platform"] is not None:
                if parsed.platform.value.lower() != match_flags["platform"].lower():
                    continue
            if match_flags["order_id"] is not None:
                if parsed.order_id != match_flags["order_id"]:
                    continue
            if match_flags["item_number"] is not None:
                if parsed.item_number != match_flags["item_number"]:
                    continue
            if match_flags["quantity"] is not None:
                if parsed.quantity != match_flags["quantity"]:
                    continue
            candidates.append(parsed)

        criteria = {k: v for k, v in match_flags.items() if v is not None}

        if len(candidates) == 0:
            print_json({
                "success": False,
                "error": "no matching missing-part task",
                "matchCriteria": criteria,
            })
            raise typer.Exit(1)

        if len(candidates) > 1:
            print_json({
                "success": False,
                "error": f"ambiguous match — {len(candidates)} tasks matched",
                "matchCriteria": criteria,
                "matches": [
                    {
                        "index": c.index,
                        "platform": c.platform.value,
                        "orderId": c.order_id,
                        "itemNumber": c.item_number,
                        "quantity": c.quantity,
                    }
                    for c in candidates
                ],
            })
            raise typer.Exit(1)

        matched = candidates[0]
        # Call the live complete_task path. It re-reads the DOM at click time so
        # the resolved index here is what gets clicked.
        result = client.complete_task(matched.index)

        # Emit a JSON result that includes the resolved task identity.
        payload = result.model_dump()
        payload.update({
            "index": matched.index,
            "platform": matched.platform.value,
            "orderId": matched.order_id,
            "itemNumber": matched.item_number,
            "quantity": matched.quantity,
        })
        print_json(payload)
    finally:
        client.close()


@app.command("delete")
def task_delete(
    index: Optional[int] = typer.Argument(None, help="Task index (1-based) to delete"),
    completed: bool = typer.Option(False, "--completed", "-c", help="Delete all completed tasks"),
):
    """
    Delete a completed task by index, or all completed tasks with --completed.

    Task must be completed before it can be deleted.

    Example:
        brickfreedom task delete 1
        brickfreedom task delete --completed
    """
    try:
        activity_logger.info("Command task delete")
        client = get_client()
        if completed:
            result = client.delete_all_completed()
        elif index is not None:
            result = client.delete_task(index)
        else:
            raise ClientError("Provide a task index or use --completed to delete all completed tasks")
        client.close()
        print_json(result)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
