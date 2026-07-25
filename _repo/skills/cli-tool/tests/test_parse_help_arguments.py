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
