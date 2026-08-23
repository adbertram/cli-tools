"""usage.json regeneration workflow tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys


SCRIPT = "scripts/regenerate-usage-json"


def _fake_cli_source() -> str:
    return """#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]

call_log = os.environ.get("FAKE_CLI_CALL_LOG")
if call_log:
    with open(call_log, "a") as handle:
        handle.write(" ".join(args) + "\\n")

if args == ["--help"]:
    print("Usage: fake [OPTIONS] COMMAND [ARGS]...")
    print("╭─ Commands ─────────────╮")
    print("│ items     Manage items │")
    print("╰────────────────────────╯")
elif args == ["items", "--help"]:
    print("Usage: fake items [OPTIONS] COMMAND [ARGS]...")
    print("╭─ Commands ───────────╮")
    print("│ list     List items  │")
    print("╰──────────────────────╯")
elif args == ["items", "list", "--help"]:
    print("Usage: fake items list [OPTIONS]")
    print("List fake items.")
    print("╭─ Options ─────────────────────────────────────────────╮")
    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")
    print("│ --help                              Show this message and exit. │")
    print("╰───────────────────────────────────────────────────────╯")
else:
    print(f"Unexpected args: {args}", file=sys.stderr)
    raise SystemExit(2)
"""


def _write_fake_cli_fixture(tmp_path):
    fake_cli = tmp_path / "fake"
    fake_cli.write_text(_fake_cli_source())
    fake_cli.chmod(0o755)
    usage_json = tmp_path / "usage.json"
    usage_json.write_text(
        json.dumps({"tool": "fake", "description": "Fake CLI", "commands": {}, "total_commands": 0})
    )
    return fake_cli, usage_json


def _write_fake_cli_with_typer_027_arguments(tmp_path):
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    fake_cli.write_text(
        _fake_cli_source().replace(
            '    print("List fake items.")',
            '    print("List fake items.")\n'
            '    print("╭─ Arguments ───────────────────────────────────────────╮")\n'
            '    print("│ *  task_id   <str>  Task ID to stop [required]       │")\n'
            '    print("│    prompt    <str>  Follow-up prompt text             │")\n'
            '    print("╰───────────────────────────────────────────────────────╯")',
        )
    )
    return fake_cli, usage_json


def test_regenerate_usage_json_runs_without_external_pythonpath(tmp_path):
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["changed"] is True
    generated = json.loads(usage_json.read_text())
    assert generated["total_commands"] == 1
    assert generated["commands"]["items"]["commands"]["list"]["options"] == [
        {
            "name": "--limit",
            "type": "INTEGER",
            "required": False,
            "help": "Max rows",
            "short": "-l",
            "default": "10",
        }
    ]


def test_regenerate_usage_json_normalizes_typer_027_argument_metavars(tmp_path):
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_with_typer_027_arguments(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(usage_json.read_text())
    assert generated["commands"]["items"]["commands"]["list"]["arguments"] == [
        {
            "name": "task_id",
            "type": "TEXT",
            "required": True,
            "help": "Task ID to stop",
        },
        {
            "name": "prompt",
            "type": "PROMPT",
            "required": False,
            "help": "Follow-up prompt text",
        },
    ]


def test_regenerate_usage_json_check_is_stable_after_generate(tmp_path):
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)

    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    generate = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert generate.returncode == 0, generate.stderr
    assert json.loads(generate.stdout)["changed"] is True
    assert "discovered_at" in json.loads(usage_json.read_text())

    check = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--check",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert check.returncode == 0, check.stdout
    assert json.loads(check.stdout)["changed"] is False


def test_regenerate_usage_json_uses_existing_binary_for_cli_suffixed_tool(tmp_path):
    skill_root = Path(__file__).resolve().parents[1]
    fake_cli, _ = _write_fake_cli_fixture(tmp_path)
    fixture_skill_root = tmp_path / "repo" / "_repo" / "skills" / "cli-tool"
    fixture_scripts = fixture_skill_root / "scripts"
    fixture_tests = fixture_skill_root / "tests"
    fixture_scripts.mkdir(parents=True)
    fixture_tests.mkdir()
    shutil.copy2(skill_root / SCRIPT, fixture_scripts / "regenerate-usage-json")
    shutil.copy2(skill_root / "tests" / "cli_test_utils.py", fixture_tests)
    shutil.copy2(skill_root / "tests" / "cli_test_config.toml", fixture_tests)

    usage_json = (
        fixture_skill_root.parent / "playwright-cli" / "usage.json"
    )
    usage_json.parent.mkdir()
    usage_json.write_text(
        json.dumps(
            {
                "tool": "playwright-cli",
                "binary": str(fake_cli),
                "description": "Fake npm CLI",
                "commands": {},
                "total_commands": 0,
            }
        )
    )
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")}

    generate = subprocess.run(
        [
            sys.executable,
            str(fixture_skill_root / SCRIPT),
            "playwright-cli",
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert generate.returncode == 0, generate.stderr
    assert json.loads(generate.stdout)["changed"] is True
    assert json.loads(usage_json.read_text())["binary"] == str(fake_cli)

    check = subprocess.run(
        [
            sys.executable,
            str(fixture_skill_root / SCRIPT),
            "playwright-cli",
            "--check",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert check.returncode == 0, check.stderr
    assert json.loads(check.stdout)["changed"] is False


def test_regenerate_usage_json_fetches_each_path_help_once(tmp_path):
    """Each path's --help runs exactly once across discovery and regeneration.

    Discovery records every --help it runs, and regeneration reuses that text
    instead of re-fetching it. Duplicate fetches double the subprocess count,
    which matters because CLI startup can stall under bursty host contention
    and each extra invocation is another timeout opportunity.
    """
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    call_log = tmp_path / "calls.log"

    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "FAKE_CLI_CALL_LOG": str(call_log),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text().splitlines()
    # Discovery runs --help on the root and on groups it recurses into
    # ("items"); leaf paths at max depth ("items list") are discovered from
    # the parent help. Regeneration reuses discovery's "items" help and
    # fetches only the not-yet-seen leaf — a regression that re-fetches
    # "items" bumps its count to 2.
    assert calls.count("--help") == 1
    assert calls.count("items --help") == 1
    assert calls.count("items list --help") == 1


def test_regenerate_usage_json_drops_enrichment_with_removed_options(tmp_path):
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    usage_json.write_text(
        json.dumps(
            {
                "tool": "fake",
                "description": "Fake CLI",
                "commands": {
                    "items": {
                        "commands": {
                            "list": {
                                "help": "List fake items with --status.",
                                "examples": [
                                    "fake items list --status active",
                                    "fake items list --status inactive",
                                ],
                                "usage_instructions": "Use --status to filter old item state.",
                            }
                        }
                    }
                },
                "total_commands": 1,
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(usage_json.read_text())
    node = generated["commands"]["items"]["commands"]["list"]
    assert node["help"] == "List fake items."
    assert "examples" not in node
    assert "usage_instructions" not in node


def _write_fake_cli_with_richer_list_options(tmp_path):
    """Fake CLI whose ``items list`` options add a path- and text-typed option.

    Used to reproduce the coursecraft ``demos update`` examples-loss bug with
    a multi-line Examples array that mixes a filesystem path and a quoted
    value ending in an ellipsis alongside one example referencing a
    renamed/removed option.
    """
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    fake_cli.write_text(
        _fake_cli_source().replace(
            '    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")',
            '    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")\n'
            '    print("│ --output-path              PATH     Export file path │")\n'
            '    print("│ --notes                    TEXT     Free-form notes │")',
        )
    )
    return fake_cli, usage_json


def test_regenerate_usage_json_keeps_valid_examples_when_only_one_is_stale(tmp_path):
    """One renamed/removed option must not discard every other example.

    Regression for the coursecraft `demos update` bug: the CLI renamed
    `--tested-approved` to `--ai-tested`, so one old example line went stale.
    The all-or-nothing staleness gate then dropped the *entire* examples
    array -- including still-accurate examples that happened to reference a
    filesystem path (`--output-path`) and a quoted value ending in an
    ellipsis (`--notes "Weekly export..."`). Only the genuinely stale example
    (`--status`, an option that does not exist on this fake CLI) should be
    dropped; the rest must survive in their original order.
    """
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_with_richer_list_options(tmp_path)
    usage_json.write_text(
        json.dumps(
            {
                "tool": "fake",
                "description": "Fake CLI",
                "commands": {
                    "items": {
                        "commands": {
                            "list": {
                                "examples": [
                                    "fake items list --limit 5",
                                    "fake items list --output-path /path/to/export.json",
                                    'fake items list --notes "Weekly export..."',
                                    "fake items list --status active",
                                ],
                            }
                        }
                    }
                },
                "total_commands": 1,
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(usage_json.read_text())
    node = generated["commands"]["items"]["commands"]["list"]
    assert node["examples"] == [
        "fake items list --limit 5",
        "fake items list --output-path /path/to/export.json",
        'fake items list --notes "Weekly export..."',
    ]


def test_regenerate_usage_json_refreshes_examples_from_live_help(tmp_path):
    """Live help examples replace stale values that use unchanged options."""
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    fake_cli.write_text(
        _fake_cli_source().replace(
            '    print("List fake items.")',
            '    print("List fake items.")\n'
            '    print("Examples:")\n'
            '    print("# Filter by ID")\n'
            '    print("fake items list --filter \\\"id:eq:69\\\"")\n'
            '    print("fake items list --filter \\\"name:contains:Setup\\\"")',
        ).replace(
            '    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")',
            '    print("│ --filter           -f      TEXT     Filter rows │")\n'
            '    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")',
        )
    )
    usage_json.write_text(
        json.dumps(
            {
                "tool": "fake",
                "description": "Fake CLI",
                "commands": {
                    "items": {
                        "commands": {
                            "list": {
                                "examples": [
                                    'fake items list --filter "fields.Name:contains:Setup"'
                                ]
                            }
                        }
                    }
                },
                "total_commands": 1,
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(usage_json.read_text())
    assert generated["commands"]["items"]["commands"]["list"]["examples"] == [
        'fake items list --filter "id:eq:69"',
        'fake items list --filter "name:contains:Setup"',
    ]


def _write_fake_cli_with_custom_negative_flag(tmp_path):
    """Fake CLI whose boolean option uses a non-mechanical secondary flag name.

    Mirrors kick's ``--include-rules/--no-rules``: the real secondary flag is
    not the mechanical ``--no-include-rules`` a naive checker would assume.
    Used to reproduce a live false positive found while auditing other
    <tool>-cli skills for the coursecraft examples-loss bug.
    """
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    fake_cli.write_text(
        _fake_cli_source().replace(
            '    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")',
            '    print("│ --limit            -l      INTEGER  Max rows [default: 10] │")\n'
            '    print("│ --include-archived      --no-archived   Include archived items │")',
        )
    )
    return fake_cli, usage_json


def test_regenerate_usage_json_keeps_example_using_custom_negative_flag(tmp_path):
    """A custom-named secondary boolean flag must not be flagged stale.

    Regression for a live false positive found while auditing other
    <tool>-cli skills for the coursecraft examples-loss bug: kick's
    `--include-rules/--no-rules`, mindmeister's `--closed/--open`, and
    twelvelabs's `--skip-duplicate/--force-upload` all declare a secondary
    flag name that is not the mechanical `--no-<primary>` form.
    live_option_tokens must recognize the CLI's actual declared secondary
    token (recovered by parse_help_option_secondary_tokens), or a
    still-accurate example referencing it gets wrongly dropped as stale.
    """
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_with_custom_negative_flag(tmp_path)
    usage_json.write_text(
        json.dumps(
            {
                "tool": "fake",
                "description": "Fake CLI",
                "commands": {
                    "items": {
                        "commands": {
                            "list": {
                                "examples": [
                                    "fake items list --limit 5",
                                    "fake items list --no-archived",
                                ],
                            }
                        }
                    }
                },
                "total_commands": 1,
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(usage_json.read_text())
    node = generated["commands"]["items"]["commands"]["list"]
    assert node["examples"] == [
        "fake items list --limit 5",
        "fake items list --no-archived",
    ]
    assert node["options"][1] == {
        "name": "--include-archived",
        "type": "bool",
        "required": False,
        "help": "Include archived items",
        "takes_value": False,
        "secondary": "--no-archived",
    }


def test_regenerate_usage_json_refreshes_help_when_options_are_unchanged(tmp_path):
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    fake_cli.write_text(
        _fake_cli_source().replace(
            '    print("List fake items.")',
            '    print("List fake items.")\n    print("Second sentence.")',
        )
    )
    usage_json.write_text(
        json.dumps(
            {
                "tool": "fake",
                "description": "Fake CLI",
                "commands": {
                    "items": {
                        "commands": {
                            "list": {
                                "help": "Old list help.",
                            }
                        }
                    }
                },
                "total_commands": 1,
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["changed"] is True
    generated = json.loads(usage_json.read_text())
    node = generated["commands"]["items"]["commands"]["list"]
    assert node["help"] == "List fake items. Second sentence."


def test_regenerate_usage_json_drops_examples_for_renamed_command(tmp_path):
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    fake_cli, usage_json = _write_fake_cli_fixture(tmp_path)
    usage_json.write_text(
        json.dumps(
            {
                "tool": "fake",
                "description": "Fake CLI",
                "commands": {
                    "items": {
                        "commands": {
                            "list": {
                                "examples": [
                                    "fake things list",
                                    "fake things list --limit 5",
                                ],
                            }
                        }
                    }
                },
                "total_commands": 1,
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(skill_root / SCRIPT),
            "fake",
            "--cli-executable",
            str(fake_cli),
            "--usage-json",
            str(usage_json),
            "--discovered-at",
            "2026-01-01T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    generated = json.loads(usage_json.read_text())
    node = generated["commands"]["items"]["commands"]["list"]
    assert "examples" not in node


def test_update_workflow_uses_regenerate_usage_json_script():
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    workflow = (skill_root / "workflows" / "update-cli.md").read_text()

    assert SCRIPT in workflow
    assert "/create-cli-tool-skill update <name>" not in workflow

    simplify = workflow.index("## Step 6: Final Code Simplification")
    refresh = workflow.index(f"{SCRIPT} <name>")
    full_test = workflow.index("scripts/test-cli-tool.sh --cli-name <name>")
    final_check = workflow.index(f"{SCRIPT} <name> --check")

    assert simplify < refresh < full_test < final_check
