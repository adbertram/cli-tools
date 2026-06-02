"""Usage tracking commands for Gemini CLI."""
from enum import Enum
import typer

from ..usage import get_usage_summary, get_model_breakdown, clear_usage_data
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error

app = typer.Typer(help="View API usage statistics")


class UsageSource(str, Enum):
    local = "local"
    cloud = "cloud"


def format_tokens(count: int) -> str:
    """Format token count with K/M suffixes."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def format_cost(cost: float) -> str:
    """Format cost as currency."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _show_local(days: int, table: bool, by_model: bool, daily: bool):
    """Show locally tracked usage."""
    if by_model:
        models = get_model_breakdown(days)

        if not models:
            print_info(f"No local usage recorded in the last {days} days")
            return

        if table:
            table_data = []
            for model, stats in sorted(models.items(), key=lambda x: x[1]["total_tokens"], reverse=True):
                table_data.append({
                    "model": model,
                    "requests": stats["requests"],
                    "input_tokens": format_tokens(stats["prompt_tokens"]),
                    "output_tokens": format_tokens(stats["completion_tokens"]),
                    "total_tokens": format_tokens(stats["total_tokens"]),
                    "est_cost": format_cost(stats["estimated_cost"]),
                })
            print_table(
                table_data,
                ["model", "requests", "input_tokens", "output_tokens", "total_tokens", "est_cost"],
                ["Model", "Requests", "Input", "Output", "Total", "Est. Cost"]
            )
        else:
            print_json(models)
        return

    summary = get_usage_summary(days)

    if summary["totals"]["requests"] == 0:
        print_info(f"No local usage recorded in the last {days} days")
        return

    if daily and summary["daily"]:
        if table:
            table_data = []
            for day in summary["daily"]:
                table_data.append({
                    "date": day["date"],
                    "requests": day["requests"],
                    "input_tokens": format_tokens(day["prompt_tokens"]),
                    "output_tokens": format_tokens(day["completion_tokens"]),
                    "total_tokens": format_tokens(day["total_tokens"]),
                    "est_cost": format_cost(day["estimated_cost"]),
                })
            print_table(
                table_data,
                ["date", "requests", "input_tokens", "output_tokens", "total_tokens", "est_cost"],
                ["Date", "Requests", "Input", "Output", "Total", "Est. Cost"]
            )
        else:
            print_json(summary["daily"])
        return

    # Default: show totals
    totals = summary["totals"]

    if table:
        print(f"\nLocal Usage (Last {days} days)\n")
        print(f"  Requests:      {totals['requests']}")
        print(f"  Input tokens:  {format_tokens(totals['prompt_tokens'])}")
        print(f"  Output tokens: {format_tokens(totals['completion_tokens'])}")
        print(f"  Total tokens:  {format_tokens(totals['total_tokens'])}")
        if totals['cached_tokens'] > 0:
            print(f"  Cached tokens: {format_tokens(totals['cached_tokens'])}")
        print(f"  Est. cost:     {format_cost(totals['estimated_cost'])}")
        print()
    else:
        print_json({
            "source": "local",
            "period_days": summary["period_days"],
            "requests": totals["requests"],
            "prompt_tokens": totals["prompt_tokens"],
            "completion_tokens": totals["completion_tokens"],
            "total_tokens": totals["total_tokens"],
            "cached_tokens": totals["cached_tokens"],
            "estimated_cost": totals["estimated_cost"],
        })


def _show_cloud(days: int, table: bool, by_model: bool, daily: bool):
    """Show cloud usage from Cloud Monitoring (all API consumers)."""
    from ..cloud_usage import query_cloud_usage, query_cloud_usage_daily

    if daily:
        daily_data = query_cloud_usage_daily(days)

        if not daily_data:
            print_info(f"No cloud usage data found in the last {days} days")
            return

        if table:
            table_data = []
            for day in daily_data:
                table_data.append({
                    "date": day["date"],
                    "requests": day["requests"],
                    "input_tokens": format_tokens(day["input_tokens"]),
                })
            print_table(
                table_data,
                ["date", "requests", "input_tokens"],
                ["Date", "Requests", "Input Tokens"]
            )
        else:
            print_json(daily_data)
        return

    result = query_cloud_usage(days)

    if not result["models"]:
        print_info(f"No cloud usage data found in the last {days} days")
        return

    has_cost = "total_cost" in result.get("totals", {})

    if by_model or table:
        table_data = []
        columns = ["model", "requests", "input_tokens"]
        headers = ["Model", "Requests", "Input Tokens"]

        if has_cost:
            columns.append("cost")
            headers.append("Cost")

        for model_name, stats in sorted(
            result["models"].items(),
            key=lambda x: x[1]["input_tokens"],
            reverse=True,
        ):
            row = {
                "model": model_name,
                "requests": stats["requests"],
                "input_tokens": format_tokens(stats["input_tokens"]),
            }
            if has_cost and "total_cost" in stats:
                row["cost"] = format_cost(stats["total_cost"])
            elif has_cost:
                row["cost"] = "-"
            table_data.append(row)

        if table:
            # Add totals row
            totals_row = {
                "model": "TOTAL",
                "requests": result["totals"]["requests"],
                "input_tokens": format_tokens(result["totals"]["input_tokens"]),
            }
            if has_cost:
                totals_row["cost"] = format_cost(result["totals"]["total_cost"])
            table_data.append(totals_row)

            print_table(table_data, columns, headers)
        else:
            print_json(result["models"])
    else:
        print_json(result)


@app.command("show")
def usage_show(
    days: int = typer.Option(30, "--days", "-d", help="Number of days to show"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    by_model: bool = typer.Option(False, "--by-model", "-m", help="Show breakdown by model"),
    daily: bool = typer.Option(False, "--daily", help="Show daily breakdown"),
    source: UsageSource = typer.Option(
        UsageSource.local, "--source", "-s",
        help="Data source: local (CLI tracking) or cloud (Cloud Monitoring)"
    ),
):
    """
    Show API usage statistics.

    Use --source local for CLI-only tracking (default).
    Use --source cloud for ALL Gemini usage across all API consumers via Cloud Monitoring.

    Example:
        gemini usage show
        gemini usage show --source cloud --table
        gemini usage show --source cloud --by-model --table
        gemini usage show --source cloud --daily --table --days 7
        gemini usage show --days 7 --by-model --table
    """
    try:
        if source == UsageSource.cloud:
            _show_cloud(days, table, by_model, daily)
        else:
            _show_local(days, table, by_model, daily)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("setup")
def usage_setup(
    table_id: str = typer.Argument(..., help="BigQuery billing table ID (project.dataset.table)"),
    save_anyway: bool = typer.Option(
        False,
        "--save-anyway",
        help="Save the table ID even if connection verification fails",
    ),
):
    """
    Configure BigQuery billing export for cloud cost tracking.

    This connects your CLI to Google Cloud's billing export so you can
    see cost data alongside token usage from Cloud Monitoring.

    Prerequisites:
        1. Enable billing export in GCP Console:
           Billing > Billing export > BigQuery export > Enable
        2. Run: gcloud auth application-default login
    """
    from ..config import get_config
    from ..cloud_usage import verify_bigquery_connection

    try:
        config = get_config()
        current = config.bigquery_billing_table

        if current:
            print_info(f"Current BigQuery table: {current}")

        # Validate format
        parts = table_id.split(".")
        if len(parts) != 3:
            print_error("Table ID must be in format: project_id.dataset_id.table_name")
            raise typer.Exit(1)

        print_info("Verifying connection...")
        result = verify_bigquery_connection(table_id)

        if result["connected"]:
            config.save_bigquery_billing_table(table_id)
            print_success(result["message"])
            print_info("You can now use: gemini usage show --source cloud --table")
        else:
            print_error(f"Connection failed: {result['error']}")
            if save_anyway:
                config.save_bigquery_billing_table(table_id)
                print_success("Table ID saved")
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("clear")
def usage_clear(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Clear all local usage data.

    Example:
        gemini usage clear
        gemini usage clear --yes
    """
    try:
        if not confirm:
            confirmed = typer.confirm("Clear all local usage data? This cannot be undone.")
            if not confirmed:
                print_info("Cancelled")
                return

        clear_usage_data()
        print_success("Local usage data cleared")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "clear": [
        "custom"
    ],
    "setup": [
        "custom"
    ],
    "show": [
        "custom"
    ]
}
