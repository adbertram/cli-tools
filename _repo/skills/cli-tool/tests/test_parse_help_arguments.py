"""Unit tests for Typer/Rich argument help parsing."""

import cli_test_utils


def test_parse_help_arguments_lowercase_angle_metavars_are_clean():
    section = (
        "*  task_id   <str>    Task ID to stop [required]\n"
        "*  count     <int>    Number of tasks [required]\n"
        "*  ratio     <float>  Completion ratio [required]\n"
        "*  source    <path>   Source file [required]\n"
    )

    arguments = cli_test_utils.parse_help_arguments(section)

    assert [argument["type"] for argument in arguments] == [
        "TEXT",
        "INTEGER",
        "FLOAT",
        "PATH",
    ]
    assert [argument["help"] for argument in arguments] == [
        "Task ID to stop",
        "Number of tasks",
        "Completion ratio",
        "Source file",
    ]


def test_parse_help_arguments_optional_angle_metavar_preserves_canonical_type():
    section = "prompt   <str>  Follow-up prompt text\n"

    arguments = cli_test_utils.parse_help_arguments(section)

    assert arguments == [
        {
            "name": "prompt",
            "type": "PROMPT",
            "required": False,
            "help": "Follow-up prompt text",
        }
    ]


def test_parse_help_arguments_unknown_angle_metavar_is_not_help_text():
    section = "*  item_id   <uuid>  Item ID [required]\n"

    arguments = cli_test_utils.parse_help_arguments(section)

    assert arguments == [
        {
            "name": "item_id",
            "type": "UUID",
            "required": True,
            "help": "Item ID",
        }
    ]


def test_parse_help_arguments_wrapped_help_line_joins_not_phantom_argument():
    # Mirrors the live `nextdoor classifieds list --help` Arguments box: a
    # long help description wraps to a continuation line with no name/type
    # columns. A parser that treats every physical line as its own argument
    # turns that continuation into a phantom second argument (observed as
    # {"name": "with --filter 'type:eq:ORGANIC,...'.", ...}).
    section = (
        "  query      <str>  Relevance keyword, NOT a filter (default: browse\n"
        "                    all results). Use it with --filter\n"
        "                    'type:eq:ORGANIC,title:contains:<keyword>'.\n"
    )

    arguments = cli_test_utils.parse_help_arguments(section)

    assert arguments == [
        {
            "name": "query",
            "type": "QUERY",
            "required": False,
            "help": (
                "Relevance keyword, NOT a filter (default: browse all "
                "results). Use it with --filter "
                "'type:eq:ORGANIC,title:contains:<keyword>'"
            ),
        }
    ]


def test_parse_help_arguments_wrapped_help_line_with_required_and_optional_mix():
    # Mirrors the live `brickstore part --help` Arguments box: a required
    # argument's row is prefixed with `*`, shifting the optional argument's
    # name column right relative to raw leading-whitespace but not relative
    # to the name token itself. Also covers a `[required]` marker rendered
    # alone on its own wrapped continuation line, as in
    # `copilot agent model set --help`.
    section = (
        "*    item_number      <str>  BrickLink part item ID, which can\n"
        "                             wrap across more than one line\n"
        "                             [required]\n"
        "     color            <str>  BrickStore color name\n"
    )

    arguments = cli_test_utils.parse_help_arguments(section)

    assert arguments == [
        {
            "name": "item_number",
            "type": "TEXT",
            "required": True,
            "help": "BrickLink part item ID, which can wrap across more than one line",
        },
        {
            "name": "color",
            "type": "COLOR",
            "required": False,
            "help": "BrickStore color name",
        },
    ]
