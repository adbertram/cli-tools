"""Commands for Microsoft Graph sharing URLs."""

import typer

from cli_tools_shared.output import command, print_info, print_json, print_success

from ..client import get_client


app = typer.Typer(help="Resolve and download sharing URLs", no_args_is_help=True)


@app.command("download")
@command
def shares_download(
    share_url: str = typer.Argument(..., help="OneDrive or SharePoint sharing URL"),
    local_path: str = typer.Argument(..., help="Local path to save the file"),
):
    """Resolve a sharing URL through Microsoft Graph and download the file."""
    print_info(f"Downloading to {local_path}...")
    result_path = get_client().download_shared_item(share_url, local_path)
    print_success(f"Downloaded: {result_path}")
    print_json({"path": result_path, "success": True})


COMMAND_CREDENTIALS = {"download": ["custom"]}
