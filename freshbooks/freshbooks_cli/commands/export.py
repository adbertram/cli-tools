"""FreshBooks archive command."""
from pathlib import Path
import typer
from cli_tools_shared.output import command, print_json
from ..client import get_client
from ..exporter import Exporter

app = typer.Typer(help="Export accessible FreshBooks data without changing source records")
COMMAND_CREDENTIALS = {"run": ["oauth"]}


@app.command("run")
@command
def export_run(
    output: Path = typer.Option(..., "--output", "-o", help="Private export directory; must be new unless --resume is set"),
    resume: bool = typer.Option(False, "--resume", help="Verify and reuse saved response files, then retry missing reads"),
):
    """Archive raw pages, details, PDFs and a coverage manifest for every business.

    Unsupported resources and failed reads are recorded in manifest.json.
    Partial exports exit 2 after writing their summary. No invoices are sent.
    """
    result = Exporter(get_client(), output, resume=resume).run()
    print_json(result)
    if result["status"] != "complete":
        raise typer.Exit(2)
