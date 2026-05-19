"""Report commands — generate HTML reports from log packages."""
import typer

from ..client import get_client
from cli_tools_shared.output import print_json, print_success, handle_error


app = typer.Typer(help="Generate log analysis reports", no_args_is_help=True)


@app.command("generate")
def report_generate(
    name: str = typer.Argument(..., help="Package name to generate report for"),
    open_browser: bool = typer.Option(False, "--open", "-o", help="Open report in browser"),
):
    """
    Generate or regenerate an HTML report for a log package.

    Creates report.html alongside the merged output with:
    - Summary metrics (entry count, error count, time span)
    - Issues section (grouped errors and warnings)
    - Entity and level breakdowns
    - Hourly activity histogram
    - Top services with error/warning badges

    Examples:
        azlogs report generate 2026-02-10_09-40-16
        azlogs report generate 2026-02-10_09-40-16 --open
    """
    try:
        client = get_client()
        report_path = client.generate_report(name)
        print_success(f"Report generated: {report_path}")

        # Output the path as JSON for scripting
        print_json({"report_path": report_path})

        if open_browser:
            import webbrowser
            webbrowser.open(f"file://{report_path}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "generate": [
        "custom"
    ]
}
