"""Order commands for Brickfreedom CLI."""
import typer
from typing import List, Optional

from cli_tools_shared.activity_log import get_activity_logger
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.filter_map import FilterMap

activity_logger = get_activity_logger("brickfreedom")

COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "post": [
        "browser_session"
    ],
    "process": [
        "browser_session"
    ],
    "processed": [
        "browser_session"
    ],
    "tracking": [
        "browser_session"
    ]
}

app = typer.Typer(help="Manage Brickfreedom orders", no_args_is_help=True)


@app.command("list")
def order_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (PAID, PACKED, SHIPPED, etc.)"),
    platform: Optional[str] = typer.Option(None, "--platform", help="Filter by platform (bricklink, brickowl)"),
    picked: Optional[bool] = typer.Option(None, "--picked", help="Filter by picked status"),
    page: int = typer.Option(1, "--page", help="Page number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List orders from BrickFreedom orders page.

    Example:
        brickfreedom order list
        brickfreedom order list --status PAID
        brickfreedom order list --platform bricklink --table
        brickfreedom order list --picked true
        brickfreedom order list --filter status:eq:PAID
    """
    try:
        activity_logger.info("Command order list")
        client = get_client()
        result = client.list_orders(
            status=status,
            platform=platform,
            picked=picked,
            page_num=page,
        )
        client.close()

        orders = result.orders

        # Apply additional client-side filters from --filter
        if filter:
            from ..models import create_order
            orders = [create_order(o) for o in apply_filters([o.model_dump(mode="json") for o in orders], filter)]

        # Apply limit
        orders = orders[:limit]

        if table:
            rows = [
                {
                    "order_id": o.order_id,
                    "platform": o.platform.value[:2].upper(),
                    "buyer": o.buyer_name[:20] + "..." if len(o.buyer_name) > 20 else o.buyer_name,
                    "date": o.date_ordered,
                    "lots": o.unique_count,
                    "items": o.total_count,
                    "total": o.cost.grand_total,
                    "status": o.status.value,
                }
                for o in orders
            ]
            print_table(
                rows,
                ["order_id", "platform", "buyer", "date", "lots", "items", "total", "status"],
                ["Order ID", "PL", "Buyer", "Date", "Lots", "Items", "Total", "Status"],
            )
        else:
            from ..models import OrderList
            print_json(OrderList(orders=orders, page=result.page))

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def order_get(
    order_id: str = typer.Argument(..., help="Marketplace order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific order by marketplace order ID.

    Example:
        brickfreedom order get 30070421
    """
    try:
        activity_logger.info("Command order get order_id=%s", order_id)
        client = get_client()
        result = client.get_order(order_id)
        client.close()

        if table:
            rows = [
                {"field": "Order ID", "value": result.order_id},
                {"field": "Platform", "value": result.platform.value},
                {"field": "Buyer", "value": result.buyer_name},
                {"field": "Date", "value": result.date_ordered},
                {"field": "Status", "value": result.status.value},
                {"field": "Lots", "value": str(result.unique_count)},
                {"field": "Items", "value": str(result.total_count)},
                {"field": "Subtotal", "value": result.cost.subtotal},
                {"field": "Shipping", "value": result.cost.shipping},
                {"field": "Total", "value": result.cost.grand_total},
                {"field": "Picked", "value": "Yes" if result.picked else "No"},
                {"field": "Shipped", "value": "Yes" if result.shipped else "No"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("processed")
def order_processed(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List processed orders ready for shipping (from order-postage page).

    Example:
        brickfreedom order processed
        brickfreedom order processed --table
    """
    try:
        activity_logger.info("Command order processed")
        client = get_client()
        result = client.list_processed_orders()
        client.close()
        orders = result.orders

        if filter:
            from ..models import create_processed_order
            orders = [
                create_processed_order(o)
                for o in apply_filters([o.model_dump(mode="json") for o in orders], filter)
            ]

        orders = orders[:limit]

        if table:
            rows = [
                {
                    "order_id": o.order_id,
                    "platform": o.marketplace.value[:2].upper(),
                    "name": o.name[:20] + "..." if len(o.name) > 20 else o.name,
                    "lots": o.lots,
                    "items": o.items,
                    "total": o.total,
                    "tracking": o.tracking_id if o.tracking_id else "-",
                }
                for o in orders
            ]
            print_table(
                rows,
                ["order_id", "platform", "name", "lots", "items", "total", "tracking"],
                ["Order ID", "PL", "Customer", "Lots", "Items", "Total", "Tracking"],
            )
        else:
            from ..models import ProcessedOrderList
            print_json(ProcessedOrderList(orders=orders))

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("process")
def order_process(
    order_ids: List[str] = typer.Argument(..., help="Marketplace order IDs to mark as processed"),
):
    """
    Mark one or more orders as processed by marketplace order ID.

    Example:
        brickfreedom order process 30070421
        brickfreedom order process 30070421 30070422 30070423
    """
    try:
        activity_logger.info("Command order process count=%s", len(order_ids))
        client = get_client()
        result = client.mark_orders_as_processed(order_ids)
        client.close()
        print_json(result)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("post")
def order_post(
    order_ids: List[str] = typer.Argument(..., help="Marketplace order IDs to post (mark as shipped)"),
):
    """
    Post one or more orders (mark as shipped on marketplace).

    All orders must have tracking numbers before posting.

    Example:
        brickfreedom order post 30070421
        brickfreedom order post 30070421 30070422
    """
    try:
        activity_logger.info("Command order post count=%s", len(order_ids))
        client = get_client()
        result = client.post_orders(order_ids)
        client.close()
        print_json(result)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("tracking")
def order_tracking(
    order_id: str = typer.Argument(..., help="Marketplace order ID"),
    tracking: str = typer.Argument(..., help="Tracking number to set"),
):
    """
    Set tracking number for an order on order-postage page.

    Example:
        brickfreedom order tracking 30070421 9400111899223847012345
    """
    try:
        activity_logger.info("Command order tracking order_id=%s", order_id)
        client = get_client()
        result = client.update_tracking(order_id, tracking)
        client.close()
        print_json(result)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
