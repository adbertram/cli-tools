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


def test_parse_help_options_preserves_multi_character_short_flag():
    section = "--aspect-ratio   -ar   <1:1|16:9>   Aspect ratio [default: 16:9]\n"

    options = cli_test_utils.parse_help_options(section)

    assert len(options) == 1
    option = options[0]
    assert option["name"] == "--aspect-ratio"
    assert option["short"] == "-ar"
    assert option["type"] == "1:1|16:9"
    assert option["help"] == "Aspect ratio"
    assert option["default"] == "16:9"


def test_parse_help_options_lowercase_angle_metavars():
    section = (
        "*  --deck                    <path>   PowerPoint slide deck path [required]\n"
        "   --resolution              <str>    Final MP4 resolution [default: 1920x1080]\n"
        "   --framerate               <int>    Screen recording framerate [default: 30]\n"
        "   --slide-pause-seconds     <float>  Pause between slides [default: 0.75]\n"
    )

    options = cli_test_utils.parse_help_options(section)

    assert [option["type"] for option in options] == ["PATH", "TEXT", "INTEGER", "FLOAT"]
    assert options[0] == {
        "name": "--deck",
        "type": "PATH",
        "required": True,
        "help": "PowerPoint slide deck path",
    }
    assert options[1]["help"] == "Final MP4 resolution"
    assert options[1]["default"] == "1920x1080"
    assert options[2]["default"] == "30"
    assert options[3]["default"] == "0.75"


def test_parse_help_options_single_boolean_flag_unaffected():
    section = "--verbose   -v   Enable verbose output\n"

    options = cli_test_utils.parse_help_options(section)

    assert len(options) == 1
    option = options[0]
    assert option["name"] == "--verbose"
    assert option["short"] == "-v"
    assert option["type"] == "bool"
    assert option["help"] == "Enable verbose output"


# parse_help_option_secondary_tokens recovers the real secondary/negative flag
# a Typer paired boolean uses, since it is not always the mechanical
# "--no-<primary>" spelling parse_help_options discards. Regression coverage
# for a class of live false-positive staleness flags found while auditing
# other <tool>-cli usage.json files for the coursecraft examples-loss bug:
# kick's "--include-rules/--no-rules", mindmeister's "--closed/--open", and
# twelvelabs's "--skip-duplicate/--force-upload" all use a custom secondary
# name, so a checker that assumes "--no-include-rules" etc. wrongly treats
# still-valid examples referencing the real secondary flag as stale.


def test_parse_help_option_secondary_tokens_custom_negative_name():
    section = "--include-rules      --no-rules          Include rules in output [default: include-rules]\n"

    assert cli_test_utils.parse_help_option_secondary_tokens(section) == ["--no-rules"]


def test_parse_help_option_secondary_tokens_unrelated_pair_name():
    section = "--closed     --open          Set specific state\n"

    assert cli_test_utils.parse_help_option_secondary_tokens(section) == ["--open"]


def test_parse_help_option_secondary_tokens_mechanical_no_prefix_still_found():
    section = "--content-done            --no-content-done             Set or clear the clip flag\n"

    assert cli_test_utils.parse_help_option_secondary_tokens(section) == ["--no-content-done"]


def test_parse_help_option_secondary_tokens_single_flag_returns_nothing():
    section = "--limit   -l   INTEGER   Maximum rows [default: 10]\n"

    assert cli_test_utils.parse_help_option_secondary_tokens(section) == []


def test_parse_help_options_numeric_range_takes_value():
    section = '--limit  -l  <int range> [1<=x<=100] Maximum page rows [default: 100]\n'
    option, = cli_test_utils.parse_help_options(section)
    assert option == {
        'name': '--limit', 'short': '-l', 'type': 'INTEGER',
        'required': False, 'help': '[1<=x<=100] Maximum page rows', 'default': '100',
    }
    assert option.get('takes_value', True) is True


# A constrained numeric parameter can also reach the parser with its metavar
# unwrapped and upper-cased -- the live facebook CLI renders "groups posts
# list --limit" as "INTEGER RANGE [1<=x<=50]" and the live google CLI renders
# "searchconsole sitemaps list --limit" as "INTEGER RANGE [x>=1]", while
# americasthriftsupply renders "--page-delay" as "FLOAT RANGE [x>=0.0]". In
# that shape the RANGE word belongs to the metavar, so it must never be
# recorded as the start of the option's help text.


def test_parse_help_options_float_range_takes_value():
    section = "--threshold  -t  <float range> [0<=x<=1] Maximum similarity [default: 0.5]\n"

    option, = cli_test_utils.parse_help_options(section)

    assert option == {
        "name": "--threshold", "short": "-t", "type": "FLOAT",
        "required": False, "help": "[0<=x<=1] Maximum similarity", "default": "0.5",
    }
    assert option.get("takes_value", True) is True


def test_parse_help_options_bare_integer_range_metavar_takes_value():
    section = "--limit  -l  INTEGER RANGE [1<=x<=50]  Maximum number of results [default: 20]\n"

    option, = cli_test_utils.parse_help_options(section)

    assert option == {
        "name": "--limit", "short": "-l", "type": "INTEGER",
        "required": False, "help": "[1<=x<=50]  Maximum number of results", "default": "20",
    }
    assert option.get("takes_value", True) is True


def test_parse_help_options_bare_integer_range_open_ended_metavar_takes_value():
    section = "--limit  -l  INTEGER RANGE [x>=1]  Maximum number of sitemaps [default: 100]\n"

    option, = cli_test_utils.parse_help_options(section)

    assert option == {
        "name": "--limit", "short": "-l", "type": "INTEGER",
        "required": False, "help": "[x>=1]  Maximum number of sitemaps", "default": "100",
    }
    assert option.get("takes_value", True) is True


def test_parse_help_options_bare_float_range_metavar_takes_value():
    section = (
        "--page-delay  FLOAT RANGE [x>=0.0]  Seconds to wait between consecutive "
        "live page requests [default: 1.0]\n"
    )

    option, = cli_test_utils.parse_help_options(section)

    assert option == {
        "name": "--page-delay", "type": "FLOAT", "required": False,
        "help": "[x>=0.0]  Seconds to wait between consecutive live page requests",
        "default": "1.0",
    }
    assert option.get("takes_value", True) is True


def test_parse_help_options_uppercase_range_metavar_takes_value():
    section = "--limit  -l  <INTEGER RANGE> [1<=x<=100]  Maximum page rows [default: 100]\n"

    option, = cli_test_utils.parse_help_options(section)

    assert option["type"] == "INTEGER"
    assert option["help"] == "[1<=x<=100]  Maximum page rows"
    assert option.get("takes_value", True) is True


def test_parse_help_options_plain_range_word_in_help_is_kept():
    """Only a bracketed "TYPE RANGE [x]" metavar is stripped, never help text."""

    section = "--mode  -m  TEXT  RANGE settings for the crawler\n"

    option, = cli_test_utils.parse_help_options(section)

    assert option["type"] == "TEXT"
    assert option["help"] == "RANGE settings for the crawler"
