"""WordPress admin command group."""
import typer

from . import plugins

app = typer.Typer(help="WordPress admin commands")

COMMAND_CREDENTIALS = {
    "plugins": ["custom"],
}

app.add_typer(plugins.app, name="plugins", help="Manage WordPress plugins")
