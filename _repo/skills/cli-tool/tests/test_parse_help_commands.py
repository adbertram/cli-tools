"""Unit tests for cli_test_utils.parse_help_commands.

Rich/Typer renders each Commands row as two aligned columns: the command name
in a fixed left column and its help text in a deeper column. When a command's
help is long enough to wrap, the overflow renders on continuation lines indented
to the *help* column. A column-blind parser matches the first lowercase token on
every line, so a continuation line such as ``like 'branch' matches`` yields a
phantom ``like`` command; the usage.json generator then runs ``<group> like
--help`` (exit 2) and aborts. Regression coverage for the pluralsight-author
``icons`` help, whose ``search`` row wraps across two continuation lines.
"""

import cli_test_utils


def test_wrapped_help_does_not_create_phantom_commands():
    # Mirrors the live `pluralsight-author icons --help` Commands box: the
    # `search` help wraps to two continuation lines, the first of which begins
    # with the lowercase word "like".
    help_text = "\n".join(
        [
            "╭─ Commands ─────────────────────────────────────────────────────╮",
            "│ list      List icons from the Author Kit icon library.         │",
            "│ search    Search icons by a single keyword matched across id,   │",
            "│           like 'branch' or 'lightbulb' matches; a multi-word    │",
            "│           --filter/--color.                                     │",
            "│ get       Get a single icon by ID.                             │",
            "│ download  Download an icon asset by ID.                        │",
            "╰────────────────────────────────────────────────────────────────╯",
        ]
    )

    commands = cli_test_utils.parse_help_commands(help_text)

    assert commands == ["list", "search", "get", "download"]
    assert "like" not in commands


def test_single_line_commands_unaffected():
    help_text = "\n".join(
        [
            "╭─ Commands ───────────────╮",
            "│ auth    Auth commands.   │",
            "│ items   Manage items.    │",
            "╰──────────────────────────╯",
        ]
    )

    assert cli_test_utils.parse_help_commands(help_text) == ["auth", "items"]


def test_two_independent_commands_sections_track_columns_separately():
    # A help screen with more than one Commands box: the column lock must reset
    # at each section so a deeper-indented first section does not reject a
    # shallower-indented second section's command rows.
    help_text = "\n".join(
        [
            "╭─ Commands ─────────────────────────╮",
            "│ longcommandname   Wraps its help    │",
            "│                   onto a new line.  │",
            "╰─────────────────────────────────────╯",
            "╭─ Commands ───────────────╮",
            "│ get   Get one.           │",
            "╰──────────────────────────╯",
        ]
    )

    assert cli_test_utils.parse_help_commands(help_text) == ["longcommandname", "get"]
