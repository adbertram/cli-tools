"""Auth commands for the Grok Bot Sessions CLI.

``login`` adopts the session the Grok Bot desktop app already holds: the CLI
cannot mint a token and never writes credential material to a profile. The
shared auth app supplies ``logout``, ``profiles``, ``status``, and ``test`` in
the canonical per-profile JSON shape.
"""
import typer
from cli_tools_shared import create_auth_app
from cli_tools_shared.output import handle_error, print_info, print_success

from ..client import ClientError, GrokBotClient
from ..config import get_config


def _adopt_login(config, force: bool) -> None:
    """Verify the adopted Grok Bot session and explain what login can do."""
    print_info(
        "grokbot-sessions adopts the session Grok Bot's desktop app already holds. "
        "It cannot mint a token, so there is nothing to enter here."
    )
    if force:
        print_info("--force re-verifies the adopted session; the Grok Bot app still owns it.")
    client = GrokBotClient(config=config)
    try:
        status = client.adopt_status()
        agents = client.list_agents(limit=1)
    except ClientError as exc:
        # Credential failures keep the shared exit code (2), matching every
        # other command's auth-failure behavior.
        raise typer.Exit(handle_error(exc))
    print_success(
        f"Adopted Grok Bot session ({status['account']}): live API reachable, "
        f"{len(agents)} agent(s) visible via {status['api_base']} "
        f"(client version {status['client_version']})."
    )


app = create_auth_app(get_config, tool_name="grokbot-sessions", login_handler=_adopt_login)
