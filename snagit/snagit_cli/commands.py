"""Capture commands for Snagit CLI."""
COMMAND_CREDENTIALS = {
    "export": [
        "no_auth"
    ],
    "list": [
        "no_auth"
    ],
    "view": [
        "no_auth"
    ]
}

import typer
from typing import Optional

from cli_tools_shared.output import print_json, print_table, handle_error
from .client import get_client

app = typer.Typer(help="Manage Snagit capture files")


@app.command("list")
def capture_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to Snagit captures folder"),
):
    """
    List all .snagx capture files.

    Examples:
        snagit capture list
        snagit capture list --table
        snagit capture list --path ~/Pictures/Snagit/Archive
    """
    try:
        client = get_client(path)
        captures = client.list_captures()

        if not captures:
            typer.echo("No .snagx capture files found.")
            return

        if table:
            table_data = []
            for capture in captures:
                table_data.append({
                    "filename": capture["filename"],
                    "size_mb": f"{capture['size_mb']} MB",
                    "modified": capture["modified_human"],
                })

            print_table(
                table_data,
                ["filename", "size_mb", "modified"],
                ["Filename", "Size", "Modified"],
            )
        else:
            print_json({"captures": captures, "count": len(captures)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("view")
def capture_view(
    filename: str = typer.Argument(..., help="Filename or path to .snagx file"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to Snagit captures folder"),
):
    """
    Extract a .snagx capture file and output the path to the main image.

    Extracts the .snagx archive and outputs the path to the main PNG image.
    The extracted files are kept in a temp directory for viewing.

    Examples:
        snagit capture view capture.snagx
        snagit capture view /full/path/to/capture.snagx
    """
    try:
        client = get_client(path)
        result = client.view_capture(filename)

        # Output just the image path - this allows Claude to read the file
        typer.echo(result['image_path'])

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("export")
def capture_export(
    filename: str = typer.Argument(..., help="Filename or path to .snagx file"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output path for PNG file (default: ./<filename>.png)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to Snagit captures folder"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Export the main PNG image from a .snagx capture file.

    Extracts only the main PNG image from the .snagx archive.
    If no output path is specified, saves to current directory with capture name.

    Examples:
        snagit capture export capture.snagx
        snagit capture export capture.snagx --output ./image.png
        snagit capture export capture.snagx --output ./exports/
        snagit capture export /full/path/to/capture.snagx -o ~/Desktop/
    """
    try:
        client = get_client(path)
        result = client.export_capture(filename, output)

        if table:
            table_data = [{
                "filename": result["filename"],
                "output_path": result["output_path"],
                "size": f"{result['size_mb']} MB",
            }]

            print_table(
                table_data,
                ["filename", "output_path", "size"],
                ["Filename", "Output Path", "Size"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
