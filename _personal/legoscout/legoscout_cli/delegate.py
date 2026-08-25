"""Hand a command's real arguments to the module that already implements it.

Every ported module kept its argparse `main()` verbatim, so the behaviour behind
a command is the behaviour the retired script had. The Typer layer declares the
same flags -- so `--help` is honest and `test-cli-tool.sh` can see them -- and
then rebuilds the argv that `main()` expects.
"""
from __future__ import annotations

import sys

import typer


def run(module, argv):
    """Call `module.main()` with `argv`, and turn its exit code into Typer's.

    `sys.exit("a message")` is Python's documented way to print that message on
    stderr and exit 1, and 24 call sites across 12 of these modules use it for
    argument validation. `int(code)` on one raised ValueError, which the
    `@command` decorator then reported as
    `Error: invalid literal for int() with base 10: 'pass exactly one of
    --apply / --dry-run'`. Every argument error in the whole CLI printed that
    instead of the sentence the module wrote. A string code is a MESSAGE, not a
    number, so it is printed and the exit status is 1.
    """
    saved = sys.argv
    sys.argv = [module.__name__.rsplit(".", 1)[-1], *argv]
    try:
        code = module.main()
    except SystemExit as exc:
        code = exc.code
    finally:
        sys.argv = saved
    if code is None or code is False or code == 0:
        return
    if isinstance(code, int):
        raise typer.Exit(code)
    print(code, file=sys.stderr)
    raise typer.Exit(1)


def flag(argv, name, value):
    """Append `--name` when `value` is true."""
    if value:
        argv.append(name)
    return argv


def option(argv, name, value):
    """Append `--name <value>` when `value` is not None."""
    if value is not None:
        argv.extend([name, str(value)])
    return argv
