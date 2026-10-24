"""Complete native Meta CLI passthrough with inherited process streams."""

import os
import sys

from .config import get_cli_executable


def execute(args):
    """Replace this process so upstream owns arguments, streams and exit status."""
    executable = get_cli_executable()
    try:
        os.execv(str(executable), [str(executable), *args])
    except FileNotFoundError:
        sys.stderr.write("Official Meta Ads CLI is missing from the wrapper environment. "
                         "Reinstall facebook-ads with the canonical CLI installer.\n")
        raise SystemExit(127) from None
    except OSError:
        sys.stderr.write("Official Meta Ads CLI could not execute. "
                         "Reinstall facebook-ads with the canonical CLI installer.\n")
        raise SystemExit(126) from None
