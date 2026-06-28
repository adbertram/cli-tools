"""usage.json regeneration workflow tests."""

from __future__ import annotations

import json
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


def test_regenerate_usage_json_fetches_each_path_help_once(tmp_path):
    """Each live path's --help runs once for discovery and once for regeneration.

    Duplicate fetches double the subprocess count, which matters because CLI
    startup can stall under bursty host contention and each extra invocation
    is another timeout opportunity.
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
    # ("items"); leaf paths at max depth are discovered from the parent help.
    # Regeneration then fetches each live path ("items", "items list")
    # exactly once — a duplicate-fetch regression doubles these counts.
    assert calls.count("--help") == 1
    assert calls.count("items --help") == 2
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
                                    "fake items list --limit 5",
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


def test_update_workflow_uses_regenerate_usage_json_script():
    skill_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    workflow = (skill_root / "workflows" / "update-cli.md").read_text()

    assert SCRIPT in workflow
    assert "/create-cli-tool-skill update <name>" not in workflow
