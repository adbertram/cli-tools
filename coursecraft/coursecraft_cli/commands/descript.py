"""Descript integration command module."""
import json
import subprocess
import typer
from pathlib import Path
from typing import Optional

from ..client import get_client, ClientError
from ..output import print_success, print_error, print_info

app = typer.Typer(help="Descript video export integration")

def _run_descript_command(args: list[str], timeout: int = 60) -> dict | list | None:
    """
    Run a descript CLI command and return parsed JSON output.

    Args:
        args: Command arguments (excluding 'descript')
        timeout: Command timeout in seconds

    Returns:
        Parsed JSON response or None if no JSON output

    Raises:
        ClientError: If command fails
    """
    full_args = ["descript"] + args

    try:
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            raise ClientError(f"descript CLI error: {result.stderr.strip()}")

        # Parse JSON from output
        output = result.stdout.strip()
        if not output:
            return None

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # Some commands return plain text
            return None

    except subprocess.TimeoutExpired:
        raise ClientError("descript CLI command timed out")
    except FileNotFoundError:
        raise ClientError("descript CLI is not installed or not in PATH")


def _find_project_by_name(project_name: str) -> str:
    """
    Find a Descript project ID by name.

    Args:
        project_name: Name to search for (case-insensitive contains match)

    Returns:
        Project ID (UUID)

    Raises:
        ClientError: If project not found or multiple matches
    """
    # Use descript projects list with filter
    result = _run_descript_command([
        "projects", "list",
        "--filter", f"name:contains:{project_name}"
    ])

    if not result or len(result) == 0:
        raise ClientError(f"No Descript project found matching '{project_name}'")

    if len(result) > 1:
        names = [p.get("name", "unknown") for p in result]
        raise ClientError(
            f"Multiple projects match '{project_name}': {', '.join(names)}. "
            "Please use a more specific name."
        )

    return result[0]["id"]


def _get_first_video_asset(project_id: str) -> tuple[str, str]:
    """
    Get the first video asset from a project.

    Args:
        project_id: Descript project UUID

    Returns:
        Tuple of (asset_id, asset_name)

    Raises:
        ClientError: If no assets found
    """
    result = _run_descript_command([
        "compositions", "assets", project_id
    ])

    if not result or len(result) == 0:
        raise ClientError(f"No video assets found in project {project_id}")

    # Return first asset
    asset = result[0]
    return asset["id"], asset.get("name", "video")


@app.command("export")
def export_clip(
    project: str = typer.Argument(..., help="Descript project name (partial match supported)"),
    module: int = typer.Option(..., "--module", "-m", help="Module number (e.g., 1, 2, 3)"),
    clip: int = typer.Option(..., "--clip", "-c", help="Clip number (e.g., 1, 2, 3)"),
    course: Optional[str] = typer.Option(None, "--course", help="Course slug (defaults to active course)"),
    clips_root: Path = typer.Option(..., "--clips-root", help="Root directory containing <course>/clips folders"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be done without exporting"),
):
    """
    Export a Descript composition to the course clips folder.

    Finds the Descript project by name, locates the composition matching
    the module/clip pattern (e.g., "m2c1"), and exports the full composition
    (with slides, edits, etc.) via the Descript app's local export.

    Requires Descript to be running with the project open.

    Examples:
        # Export to active course
        coursecraft descript export "Advanced Features of Cursor AI" -m 2 -c 1 --clips-root /path/to/courses

        # Export with specific course
        coursecraft descript export "Advanced Features of Cursor AI" -m 2 -c 1 --course advanced-features-cursor-ai --clips-root /path/to/courses

        # Dry run to preview
        coursecraft descript export "Advanced Features of Cursor AI" -m 2 -c 1 --clips-root /path/to/courses --dry-run
    """
    try:
        # Resolve course
        if not course:
            client = get_client()
            active_courses = client.list_records("Courses", "{Active}=TRUE()")
            if not active_courses:
                raise ClientError("No active course found. Use --course to specify.")
            course = active_courses[0].get("fields", {}).get("Course ID")
            if not course:
                raise ClientError("Active course has no Course ID slug")
            print_info(f"Using active course: {course}")

        # Build output path
        output_dir = clips_root / course / "clips"
        if not output_dir.exists():
            raise ClientError(f"Clips folder does not exist: {output_dir}")

        output_file = output_dir / f"m{module}c{clip}.mp4"
        composition_name = f"m{module}c{clip}"

        # Find project
        print_info(f"Finding Descript project matching '{project}'...")
        project_id = _find_project_by_name(project)
        print_info(f"Found project: {project_id}")

        if dry_run:
            print_info(f"[DRY RUN] Would export composition '{composition_name}' to: {output_file}")
            return

        # Export composition via descript CLI
        print_info(f"Exporting composition '{composition_name}' to {output_file}...")
        export_args = [
            "compositions", "export",
            project_id,
            "--composition", composition_name,
            "-o", str(output_file),
        ]

        result = subprocess.run(
            ["descript"] + export_args,
            capture_output=False,
            text=True,
            timeout=600
        )

        if result.returncode != 0:
            raise ClientError("Export failed")

        # Verify file exists
        if output_file.exists():
            size_mb = output_file.stat().st_size / (1024 * 1024)
            print_success(f"Exported successfully: {output_file} ({size_mb:.1f} MB)")
        else:
            raise ClientError("Export completed but file not found")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "export": [
        "custom"
    ]
}
