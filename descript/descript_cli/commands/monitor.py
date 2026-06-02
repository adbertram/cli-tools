"""Network monitor commands for Descript CLI.

Start/stop a CDP network monitor to capture Descript API calls
for endpoint discovery and debugging.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path



import typer

from ..monitor import MONITOR_DIR, PID_FILE, LOG_FILE
from cli_tools_shared.output import print_json, print_success, print_error, print_info, handle_error

app = typer.Typer(help="Monitor Descript network activity via CDP", no_args_is_help=True)


def _get_monitor_pid() -> int | None:
    """Get the running monitor's PID, or None if not running."""
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


@app.command("start")
def monitor_start(
    foreground: bool = typer.Option(False, "--foreground", "-F", help="Run in foreground instead of background"),
):
    """
    Start monitoring Descript network activity.

    Captures all API calls made by the Descript app for endpoint
    discovery and debugging. Writes to ~/.descript/monitor.log.

    Example:
        descript monitor start
        descript monitor start --foreground
    """
    try:
        # Check if already running
        pid = _get_monitor_pid()
        if pid:
            print_error(f"Monitor already running (PID {pid}). Run 'descript monitor stop' first.")
            raise typer.Exit(1)

        MONITOR_DIR.mkdir(parents=True, exist_ok=True)

        if foreground:
            print_info(f"Monitoring... Log: {LOG_FILE}")
            print_info("Press Ctrl+C to stop")
            from ..monitor import run_monitor
            run_monitor(LOG_FILE)
        else:
            # Launch as background process
            # Resolve the venv Python — sys.executable may point to
            # a framework Python on macOS when run via an entry_point script.
            venv_python = Path(sys.executable)
            pkg_dir = Path(__file__).resolve().parent.parent.parent
            candidate = pkg_dir / ".venv" / "bin" / "python"
            if candidate.exists():
                venv_python = candidate

            proc = subprocess.Popen(
                [str(venv_python), "-m", "descript_cli.monitor_runner"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            PID_FILE.write_text(str(proc.pid))
            print_success(f"Monitor started (PID {proc.pid})")
            print_info(f"Log: {LOG_FILE}")
            print_info("Run 'descript monitor stop' to stop")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stop")
def monitor_stop():
    """
    Stop the network monitor.

    Example:
        descript monitor stop
    """
    try:
        pid = _get_monitor_pid()
        if not pid:
            print_error("Monitor is not running")
            raise typer.Exit(1)

        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        print_success(f"Monitor stopped (PID {pid})")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def monitor_status():
    """
    Check if the monitor is running.

    Example:
        descript monitor status
    """
    try:
        pid = _get_monitor_pid()
        log_size = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0

        status = {
            "running": pid is not None,
            "pid": pid,
            "log_file": str(LOG_FILE),
            "log_size_bytes": log_size,
        }

        print_json(status)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("tail")
def monitor_tail(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
):
    """
    Show recent monitor log output.

    Example:
        descript monitor tail
        descript monitor tail -n 100
        descript monitor tail --follow
    """
    try:
        if not LOG_FILE.exists():
            print_error(f"No log file found at {LOG_FILE}")
            raise typer.Exit(1)

        if follow:
            os.execlp("tail", "tail", "-f", str(LOG_FILE))
        else:
            os.execlp("tail", "tail", f"-n{lines}", str(LOG_FILE))

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "start": [
        "custom"
    ],
    "status": [
        "custom"
    ],
    "stop": [
        "custom"
    ],
    "tail": [
        "custom"
    ]
}
