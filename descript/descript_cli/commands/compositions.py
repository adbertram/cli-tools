"""Compositions commands for Descript CLI."""
from pathlib import Path
from typing import Optional, List

import typer

from ..client import get_client, ClientError
from cli_tools_shared.filters import validate_filters, apply_filters
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error

app = typer.Typer(help="Manage Descript project compositions", no_args_is_help=True)


@app.command("list")
def list_compositions(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List compositions in a project.

    Example:
        descript compositions list <project-id>
        descript compositions list <project-id> --table
        descript compositions list <project-id> --filter "name:m1c1"
    """
    try:
        client = get_client()
        compositions = client.list_compositions(project_id)

        # Apply client-side filtering
        if filter:
            for f in filter:
                if ":" in f:
                    field, value = f.split(":", 1)
                    compositions = [c for c in compositions if value.lower() in str(getattr(c, field, "")).lower()]

        compositions = compositions[:limit]

        output_data = [c.model_dump() for c in compositions]

        if properties:
            selected = [p.strip() for p in properties.split(",")]
            output_data = [{k: v for k, v in row.items() if k in selected} for row in output_data]

        if table:
            if output_data:
                headers = list(output_data[0].keys())
                display_headers = [h.replace("_", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No compositions found")
        else:
            print_json(output_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_composition(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    composition_id: str = typer.Argument(help="Composition ID (UUID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific composition from a project.

    Example:
        descript compositions get <project-id> <composition-id>
    """
    try:
        client = get_client()
        compositions = client.list_compositions(project_id)

        match = [c for c in compositions if c.id == composition_id]
        if not match:
            print_error(f"Composition {composition_id} not found in project")
            raise typer.Exit(1)

        output = match[0].model_dump()

        if table:
            headers = list(output.keys())
            display_headers = [h.replace("_", " ").title() for h in headers]
            print_table([output], headers, display_headers)
        else:
            print_json(output)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _resolve_composition(client, project_id: str, composition: str):
    """Resolve a composition name or ID to a (id, name) tuple."""
    compositions = client.list_compositions(project_id)
    match = [c for c in compositions if c.id == composition or c.name.lower() == composition.lower()]
    if not match:
        match = [c for c in compositions if composition.lower() in c.name.lower()]
    if not match:
        names = [c.name for c in compositions]
        raise ClientError(f"No composition matching '{composition}'. Available: {', '.join(names)}")
    if len(match) > 1:
        names = [c.name for c in match]
        raise ClientError(f"Multiple compositions match '{composition}': {', '.join(names)}. Be more specific.")
    return match[0].id, match[0].name


@app.command("export")
def export_composition(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    asset_id: Optional[str] = typer.Argument(None, help="Video asset ID for raw export (use 'descript compositions assets' to find)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    composition: Optional[str] = typer.Option(None, "--composition", "-C", help="Composition name or ID to export via Descript app"),
    fps: int = typer.Option(30, "--fps", help="Frames per second"),
    width: int = typer.Option(1920, "--width", "-W", help="Max width"),
    height: int = typer.Option(1080, "--height", "-H", help="Max height"),
    fmt: str = typer.Option("mp4", "--format", help="Export format"),
):
    """
    Export a video asset or composition as MP4.

    Two export modes:

    1. Asset export (raw recording via API):
       descript compositions export <project-id> <asset-id>

    2. Composition export (full video with slides via Descript app):
       descript compositions export <project-id> --composition m2c1 -o ./m2c1.mp4

    Composition export requires Descript to be running with the project open.
    It automates the app's local export to produce the full rendered video.

    Example:
        descript compositions export <project-id> <asset-id>
        descript compositions export <project-id> --composition m2c1 -o ./m2c1.mp4
        descript compositions export <project-id> <asset-id> --fps 60 --width 3840 --height 2160
    """
    try:
        client = get_client()

        if composition:
            # Composition export via Descript app automation
            from ..app_export import export_composition_local

            comp_id, comp_name = _resolve_composition(client, project_id, composition)
            print_info(f"Found composition: {comp_name} ({comp_id})")

            if output is None:
                output = f"./{comp_name}.{fmt}"

            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            result_path = export_composition_local(
                project_id, comp_id, comp_name, output_path,
            )
            size_mb = result_path.stat().st_size / (1024 * 1024)
            print_success(f"Exported to {result_path} ({size_mb:.1f} MB)")

        elif asset_id:
            # Raw asset export via API
            print_info(f"Getting export playlist for asset {asset_id[:8]}...")
            playlist = client.get_export_playlist(
                project_id, asset_id, fmt=fmt, fps=fps, width=width, height=height,
            )

            duration_s = playlist.end / 1_000_000
            total_segments = len(playlist.fragment_starts)

            if output is None:
                output = f"./{asset_id}.{fmt}"

            output_path = Path(output)
            print_info(f"Duration: {duration_s:.1f}s | Segments: {total_segments} | Output: {output_path}")

            def on_progress(downloaded, seg_idx, seg_total):
                mb = downloaded / (1024 * 1024)
                pct = (seg_idx / seg_total) * 100
                print(f"\r  Downloading: {pct:5.1f}% ({mb:.1f} MB, segment {seg_idx}/{seg_total})", end="", flush=True)

            result = client.download_export(playlist, str(output_path), progress_callback=on_progress)
            print()  # newline after progress

            size_mb = Path(result).stat().st_size / (1024 * 1024)
            print_success(f"Exported to {result} ({size_mb:.1f} MB)")

        else:
            print_error("Provide either an asset_id argument or --composition option.")
            raise typer.Exit(1)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("assets")
def list_assets(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List video assets in a project for export.

    Shows the raw video recordings available in the project.
    Use the asset ID with 'descript compositions export' to download.

    Example:
        descript compositions assets <project-id>
        descript compositions assets <project-id> --table
    """
    try:
        client = get_client()
        assets = client.list_video_assets(project_id)

        output_data = [a.model_dump() for a in assets]

        if table:
            if output_data:
                headers = list(output_data[0].keys())
                display_headers = [h.replace("_", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No video assets found")
        else:
            print_json(output_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "assets": [
        "custom"
    ],
    "export": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
