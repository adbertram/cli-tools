"""Main entry point for Cliclick CLI wrapper."""
from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

app = create_app(
    name="cliclick",
    help="CLI wrapper for cliclick mouse/keyboard automation",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import mouse, keyboard, scripts
from .commands import exec as exec_cmd

app.add_typer(mouse.app, name="mouse", help="Mouse control commands")
app.add_typer(keyboard.app, name="keyboard", help="Keyboard control commands")
app.add_typer(scripts.app, name="scripts", help="Manage automation scripts")
app.add_typer(exec_cmd.app, name="exec", help="Execute raw cliclick commands")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
