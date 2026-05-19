"""Server config commands - manage n8n plist environment variables."""
import typer

from cli_tools_shared.output import print_error, print_info, print_success, print_table, print_warning, handle_error
from ..server import run_on_server

app = typer.Typer(help="Manage n8n server configuration (plist env vars)", no_args_is_help=True)

N8N_PLIST = "/Library/LaunchDaemons/com.n8n.server.plist"

VALID_KEYS = {
    "EXECUTIONS_DATA_PRUNE": {"desc": "Enable execution pruning", "default": "true"},
    "EXECUTIONS_DATA_MAX_AGE": {"desc": "Max execution age in hours", "default": "336 (14 days)"},
    "EXECUTIONS_DATA_PRUNE_MAX_COUNT": {"desc": "Max execution count to keep", "default": "10000"},
    "N8N_WORKFLOW_HISTORY_PRUNE_TIME": {"desc": "Workflow history retention in hours", "default": "-1 (keeps all)"},
}


def _shell_quote(s: str) -> str:
    """Quote a string for use in a shell command (single-quote wrapping)."""
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"


@app.command("show")
def config_show(
    plist_path: str = typer.Option(N8N_PLIST, "--plist", help="LaunchDaemon plist path on server"),
):
    """
    Show current n8n server pruning configuration.

    Example:
        n8n server config show
    """
    try:
        print_info("Reading server configuration from plist...")
        plist_content = run_on_server(f"sudo cat {plist_path}", timeout=15)

        import plistlib
        plist = plistlib.loads(plist_content.encode())
        env_vars = plist.get("EnvironmentVariables", {})

        rows = []
        for key, meta in VALID_KEYS.items():
            current = env_vars.get(key)
            rows.append({
                "variable": key,
                "current": current if current is not None else f"(not set — default: {meta['default']})",
                "description": meta["desc"],
            })

        print_table(rows, ["variable", "current", "description"], ["Variable", "Current Value", "Description"])

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help=f"Config key: {', '.join(VALID_KEYS.keys())}"),
    value: str = typer.Argument(..., help="Value to set"),
    restart: bool = typer.Option(True, "--restart/--no-restart", help="Restart n8n after changing config"),
    plist_path: str = typer.Option(N8N_PLIST, "--plist", help="LaunchDaemon plist path on server"),
):
    """
    Set an n8n server configuration variable in the LaunchDaemon plist.

    Examples:
        n8n server config set EXECUTIONS_DATA_MAX_AGE 168
        n8n server config set N8N_WORKFLOW_HISTORY_PRUNE_TIME 720 --no-restart
    """
    if key not in VALID_KEYS:
        print_error(f"Invalid key: '{key}'. Must be one of: {', '.join(VALID_KEYS.keys())}")
        raise typer.Exit(1)

    try:
        script = f'''
import plistlib

with open("{plist_path}", "rb") as f:
    plist = plistlib.load(f)

env = plist.setdefault("EnvironmentVariables", {{}})
env["{key}"] = "{value}"

with open("{plist_path}", "wb") as f:
    plistlib.dump(plist, f)

print("  {key} = {value}")
'''
        print_info(f"Setting {key}={value}...")
        cmd = f"sudo python3 -c {_shell_quote(script)}"
        output = run_on_server(cmd, timeout=15)
        print(output, end="")

        if restart:
            print_info("Restarting n8n...")
            from .server import _restart_n8n
            _restart_n8n()
            print_success(f"Config updated and n8n restarted")
        else:
            print_warning("Config updated but n8n NOT restarted. Run: n8n server restart")

    except Exception as e:
        raise typer.Exit(handle_error(e))
