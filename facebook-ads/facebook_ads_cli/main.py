"""Standard wrapper shell with complete native Meta command passthrough."""

import sys

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.output import command

from . import __version__
from .client import execute

# Shared app creation normalizes help/cache flags. Keep native argv outside that
# preprocessing so even future upstream options pass through byte-for-byte.
_original_argv = sys.argv
if _original_argv[1:3] == ["run", "--"]:
    sys.argv = _original_argv[:1]
app = create_app(name="facebook-ads", help="Wrapper for Meta's official Ads CLI. Use run -- <native arguments>.",
                 version=__version__, cache_support=False)
sys.argv = _original_argv


@app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@command
def run(ctx: typer.Context):
    """Run Meta's official CLI. Use `run -- --help` for the complete native tree."""
    execute(ctx.args)


def main():
    """Preserve arguments after the explicit native passthrough boundary."""
    if sys.argv[1:3] == ["run", "--"]:
        execute(sys.argv[3:])
    else:
        run_app(app)


if __name__ == "__main__":
    main()
