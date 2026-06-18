"""Unit tests for cli_test_utils.parse_help_options.

Typer renders a paired boolean flag (``--flag/--no-flag``) as two long forms
on a single Rich help row. The option parser must capture only the primary
long flag and a clean help string, never folding the ``--no-...`` secondary
form (or its column padding) into the help text. Regression coverage for the
coursecraft usage.json regeneration that previously produced help values such
as ``"--no-content-done   Set or clear ..."``.
"""

import cli_test_utils


# parse_help_options receives section text after extract_help_sections has
# already stripped the Rich "│" borders, so these fixtures omit the borders and
# include the wrapped continuation line that the parser joins back together.


def test_parse_help_options_paired_boolean_help_is_clean():
    section = (
        "--content-done            --no-content-done             Set or clear the\n"
        "                                                        clip flag\n"
    )

    options = cli_test_utils.parse_help_options(section)

    assert len(options) == 1
    option = options[0]
    assert option["name"] == "--content-done"
    assert option["type"] == "bool"
    assert option["help"] == "Set or clear the clip flag"
    assert "--no-content-done" not in option["help"]


def test_parse_help_options_paired_boolean_with_short_flag():
    section = "--active   -a   --no-active             Mark the record active\n"

    options = cli_test_utils.parse_help_options(section)

    assert len(options) == 1
    option = options[0]
    assert option["name"] == "--active"
    assert option["short"] == "-a"
    assert option["help"] == "Mark the record active"


def test_parse_help_options_single_value_option_unaffected():
    section = "--limit   -l   INTEGER   Maximum rows [default: 10]\n"

    options = cli_test_utils.parse_help_options(section)

    assert len(options) == 1
    option = options[0]
    assert option["name"] == "--limit"
    assert option["short"] == "-l"
    assert option["type"] == "INTEGER"
    assert option["help"] == "Maximum rows"
    assert option["default"] == "10"


def test_parse_help_options_single_boolean_flag_unaffected():
    section = "--verbose   -v   Enable verbose output\n"

    options = cli_test_utils.parse_help_options(section)

    assert len(options) == 1
    option = options[0]
    assert option["name"] == "--verbose"
    assert option["short"] == "-v"
    assert option["type"] == "bool"
    assert option["help"] == "Enable verbose output"
