"""WordPress admin command group."""
import typer

from . import plugins
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="WordPress admin commands")

COMMAND_CREDENTIALS = {
    "plugins": ["username_password"],
    "security-scan": ["username_password"],
    "health-report": ["username_password"],
}

app.add_typer(plugins.app, name="plugins", help="Manage WordPress plugins")


def get_client():
    from ..client import get_client as _get_client
    return _get_client()


@app.command("security-scan")
def security_scan(
    active_only: bool = typer.Option(False, "--active-only", help="Scan only active plugins plus all themes"),
    table: bool = typer.Option(False, "--table", "-t", help="Display affected components as a table"),
):
    """Scan installed plugins and themes for known vulnerabilities."""
    try:
        result = get_client().security_scan(active_only=active_only)
        if table:
            rows = [
                {
                    "type": item["component_type"],
                    "slug": item["slug"],
                    "version": item["installed_version"],
                    "status": item["status"],
                    "vulnerabilities": item["affected_vulnerability_count"],
                }
                for item in result["affected_components"]
            ]
            print_table(rows, ["type", "slug", "version", "status", "vulnerabilities"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("health-report")
def health_report(
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as a table"),
):
    """Emit a structured WordPress maintenance health report."""
    try:
        result = get_client().health_report()
        if table:
            rows = [
                {"area": "plugins", "metric": "total", "value": result["plugins"]["count"]},
                {"area": "plugins", "metric": "active", "value": result["plugins"]["active_count"]},
                {"area": "plugins", "metric": "updates_available", "value": result["plugins"]["updates_available_count"]},
                {"area": "plugins", "metric": "closed", "value": result["plugins"]["closed_count"]},
                {"area": "plugins", "metric": "unverified", "value": result["plugins"]["unverified_count"]},
                {"area": "themes", "metric": "total", "value": result["themes"]["count"]},
                {"area": "themes", "metric": "active", "value": len(result["themes"]["active"])},
                {"area": "wordpress", "metric": "core_status", "value": result["wordpress"]["status"]},
                {"area": "php", "metric": "version_status", "value": result["php"]["status"]},
            ]
            print_table(rows, ["area", "metric", "value"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))
