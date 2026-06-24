"""Compositions commands for Descript CLI."""
import os
import tempfile
from pathlib import Path
from typing import Optional, List

import typer

from ..client import get_client, ClientError
from ..platform import (
    PlatformCLIError,
    list_compositions_json,
    list_media_files_json,
    select_object_properties,
    select_properties,
)
from cli_tools_shared.filters import apply_filters, validate_filters
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
        output_data = list_compositions_json(project_id)

        if filter:
            try:
                validate_filters(filter)
            except Exception as e:
                print_error(str(e))
                raise typer.Exit(1)
            output_data = apply_filters(output_data, filter)

        output_data = select_properties(output_data[:limit], properties)

        if table:
            if output_data:
                headers = list(output_data[0].keys())
                display_headers = [h.replace("_", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No compositions found")
        else:
            print_json(output_data)

    except PlatformCLIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_composition(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    composition_id: str = typer.Argument(help="Composition ID (UUID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    Get a specific composition from a project.

    Example:
        descript compositions get <project-id> <composition-id>
    """
    try:
        compositions = list_compositions_json(project_id)

        match = [c for c in compositions if c.get("id") == composition_id]
        if not match:
            print_error(f"Composition {composition_id} not found in project")
            raise typer.Exit(1)

        output = select_object_properties(match[0], properties)

        if table:
            headers = list(output.keys())
            display_headers = [h.replace("_", " ").title() for h in headers]
            print_table([output], headers, display_headers)
        else:
            print_json(output)

    except PlatformCLIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("active")
def active_compositions(
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Only include active pages for this project UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show compositions currently visible in the Descript desktop app.

    Example:
        descript compositions active
        descript compositions active --project-id <project-id>
    """
    try:
        from ..app_export import get_visible_compositions

        records = get_visible_compositions()
        if project_id:
            records = [record for record in records if record.get("project_id") == project_id]

        output_data = []
        for record in records:
            compositions = list_compositions_json(record["project_id"])
            matches = [
                composition for composition in compositions
                if str(composition.get("id", "")).startswith(record["composition_prefix"])
            ]
            if not matches:
                raise ClientError(
                    "Active Descript page did not match any composition from the API: "
                    f'{record["project_id"]}/{record["composition_prefix"]}'
                )
            if len(matches) > 1:
                names = [str(composition.get("name", "")) for composition in matches]
                raise ClientError(
                    "Active Descript page matched multiple API compositions: "
                    f"{', '.join(names)}"
                )
            composition = matches[0]
            output_data.append({
                **record,
                "composition_id": composition.get("id"),
                "composition_name": composition.get("name"),
                "duration": composition.get("duration"),
            })

        if table:
            if output_data:
                headers = [
                    "project_id",
                    "composition_id",
                    "composition_name",
                    "visible_name",
                    "duration",
                ]
                display_headers = [h.replace("_", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No active Descript composition pages found")
        else:
            print_json(output_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except PlatformCLIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _resolve_composition(project_id: str, composition: str):
    """Resolve a composition name or ID to a (id, name) tuple."""
    compositions = list_compositions_json(project_id)
    match = [
        c for c in compositions
        if c.get("id") == composition or str(c.get("name", "")).lower() == composition.lower()
    ]
    if not match:
        match = [c for c in compositions if composition.lower() in str(c.get("name", "")).lower()]
    if not match:
        names = [str(c.get("name", "")) for c in compositions]
        raise ClientError(f"No composition matching '{composition}'. Available: {', '.join(names)}")
    if len(match) > 1:
        names = [str(c.get("name", "")) for c in match]
        raise ClientError(f"Multiple compositions match '{composition}': {', '.join(names)}. Be more specific.")
    return str(match[0].get("id")), str(match[0].get("name", ""))


@app.command("export")
def export_composition(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    asset_id: Optional[str] = typer.Argument(None, help="Video asset ID for raw export (use 'descript compositions assets' to find)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    composition: Optional[str] = typer.Option(None, "--composition", "-C", help="Composition name or ID to export via Descript app"),
    fps: int = typer.Option(30, "--fps", help="Frames per second"),
    width: int = typer.Option(1920, "--width", "-W", help="Max width"),
    height: int = typer.Option(1080, "--height", "-H", help="Max height"),
    fmt: str = typer.Option("mp4", "--format", help="Export format: 'mp4' (video) or 'wav' (audio-only)"),
    audio: bool = typer.Option(False, "--audio", help="Export audio only as WAV (alias for --format wav)"),
):
    """
    Export a video asset or composition as MP4, or its audio track as WAV.

    Two export modes:

    1. Asset export (raw recording via API media segment URLs):
       descript compositions export <project-id> <asset-id>
       Rate-limited or interrupted downloads can be resumed by rerunning the same command.

    2. Composition export (full video with slides via Descript app):
       descript compositions export <project-id> --composition m2c1 -o ./m2c1.mp4

    Composition export requires Descript to be launched with CDP on port 9222.
    If the target project is not open, the CLI auto-opens it via the
    descript://project/<project-id> deep link and waits for the project page.
    It automates the app's local export to produce the full rendered video.

    WAV audio export (--format wav or --audio) drives the same local export to a
    temporary .wav destination, then moves it to the target path. Descript picks
    the export format from the composition's content: an audio-only composition
    (e.g. a narration take) exports WAV directly, so the .wav destination matches
    and no native extension-mismatch sheet appears. The asset-export path (raw
    recording, second form) still extracts audio with ffmpeg from its API MP4.

    Example:
        descript compositions export <project-id> <asset-id>
        descript compositions export <project-id> --composition m2c1 -o ./m2c1.mp4
        descript compositions export <project-id> --composition slide_dictation --format wav -o ./slide_dictation.wav
        descript compositions export <project-id> <asset-id> --fps 60 --width 3840 --height 2160
    """
    try:
        client = get_client()

        produce_wav = audio or fmt.lower() == "wav"
        # The underlying export always renders MP4; WAV is extracted from it.
        video_fmt = "mp4" if produce_wav else fmt

        if composition:
            # Composition export via Descript app automation
            from ..app_export import export_composition_local

            comp_id, comp_name = _resolve_composition(project_id, composition)
            print_info(f"Found composition: {comp_name} ({comp_id})")

            if output is None:
                output = f"./{comp_name}.wav" if produce_wav else f"./{comp_name}.{video_fmt}"

            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if produce_wav:
                fd, _tmp = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                video_path = Path(_tmp)
            else:
                video_path = output_path
            result_path = export_composition_local(
                project_id, comp_id, comp_name, video_path,
            )

            if produce_wav:
                result_path.replace(output_path)
                size_mb = output_path.stat().st_size / (1024 * 1024)
                print_success(f"Exported audio to {output_path} ({size_mb:.1f} MB)")
            else:
                size_mb = result_path.stat().st_size / (1024 * 1024)
                print_success(f"Exported to {result_path} ({size_mb:.1f} MB)")

        elif asset_id:
            # Raw asset export via API
            from ..app_export import extract_audio_wav

            print_info(f"Getting export playlist for asset {asset_id[:8]}...")
            playlist = client.get_export_playlist(
                project_id, asset_id, fmt=video_fmt, fps=fps, width=width, height=height,
            )

            duration_s = playlist.end / 1_000_000
            total_segments = len(playlist.fragment_starts)

            if output is None:
                output = f"./{asset_id}.wav" if produce_wav else f"./{asset_id}.{video_fmt}"

            output_path = Path(output)
            video_path = output_path.with_suffix(f".{video_fmt}") if produce_wav else output_path
            print_info(f"Duration: {duration_s:.1f}s | Segments: {total_segments} | Output: {output_path}")

            def on_progress(downloaded, seg_idx, seg_total):
                mb = downloaded / (1024 * 1024)
                pct = (seg_idx / seg_total) * 100
                print(f"\r  Downloading: {pct:5.1f}% ({mb:.1f} MB, segment {seg_idx}/{seg_total})", end="", flush=True)

            result = client.download_export(playlist, str(video_path), progress_callback=on_progress)
            print()  # newline after progress

            if produce_wav:
                print_info(f"Extracting audio to {output_path}...")
                wav_path = extract_audio_wav(Path(result), output_path)
                Path(result).unlink()
                size_mb = wav_path.stat().st_size / (1024 * 1024)
                print_success(f"Exported audio to {wav_path} ({size_mb:.1f} MB)")
            else:
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


@app.command("delete")
def delete_composition(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    composition_id: Optional[str] = typer.Option(None, "--composition-id", help="Composition ID (UUID)"),
    composition: Optional[str] = typer.Option(None, "--composition", "-C", help="Composition name or ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt (for automation)"),
):
    """
    Delete a composition from a project via Descript app automation.

    Descript exposes no delete API (deleting a composition is an internal
    collaborative-document commit), so this drives the desktop app's own
    id-scoped sidebar context-menu Delete via CDP, then verifies the
    composition is gone. Requires Descript running with CDP on port 9222;
    the project auto-opens via its descript://project/<id> deep link.

    Provide the target as --composition-id (UUID) or --composition (name or ID).

    Example:
        descript compositions delete <project-id> --composition-id <id> --yes
        descript compositions delete <project-id> --composition m1c1 --yes
    """
    try:
        from ..app_export import delete_composition_local

        target = composition_id or composition
        if not target:
            print_error("Provide --composition-id or --composition.")
            raise typer.Exit(1)

        comp_id, comp_name = _resolve_composition(project_id, target)
        print_info(f"Target composition: {comp_name} ({comp_id})")

        if not yes:
            if not typer.confirm(
                f"Delete composition '{comp_name}' from Descript? This cannot be undone."
            ):
                print_info("Aborted.")
                raise typer.Exit(0)

        delete_composition_local(project_id, comp_id, comp_name)

        remaining = list_compositions_json(project_id)
        if any(c.get("id") == comp_id for c in remaining):
            print_error(
                f"Composition {comp_id} is still present after the delete attempt."
            )
            raise typer.Exit(1)

        print_success(f"Deleted composition '{comp_name}' ({comp_id}).")

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
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
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
        output_data = select_properties(list_media_files_json(project_id), properties)

        if table:
            if output_data:
                headers = list(output_data[0].keys())
                display_headers = [h.replace("_", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No video assets found")
        else:
            print_json(output_data)

    except PlatformCLIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "active": [
        "custom"
    ],
    "assets": [
        "custom"
    ],
    "delete": [
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
