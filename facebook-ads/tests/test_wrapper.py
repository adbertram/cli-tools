"""Official CLI delegation tests. No credentials, network mutations or ad spend."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from importlib import metadata

import click
from meta.cli import cli
import pytest

from facebook_ads_cli import client
from facebook_ads_cli.config import get_cli_executable


def run_wrapper(args, **kwargs):
    return subprocess.run([sys.executable, "-m", "facebook_ads_cli.main", *args], capture_output=True, check=False, **kwargs)


def native_leaves(command=cli, path=()):
    if isinstance(command, click.Group):
        ctx = click.Context(command)
        for name in command.list_commands(ctx):
            yield from native_leaves(command.get_command(ctx, name), (*path, name))
    else:
        yield path


LEAVES = list(native_leaves())


def test_official_dependency_and_private_executable_provisioned():
    distribution = metadata.distribution("meta-ads")
    assert distribution.version == "1.2.0"
    assert any(entry.name == "meta" and entry.value == "meta.cli:cli" for entry in distribution.entry_points)
    assert get_cli_executable() == Path(sys.executable).parent / "meta"
    assert get_cli_executable().is_file() and os.access(get_cli_executable(), os.X_OK)
    assert len(LEAVES) == 55


@pytest.mark.parametrize("arguments", [[], ["--help"], ["--version"], ["unknown-command"]])
def test_native_root_output_and_exit_parity(arguments, tmp_path):
    expected = subprocess.run([str(get_cli_executable()), *arguments], cwd=tmp_path, capture_output=True, check=False)
    actual = run_wrapper(["run", "--", *arguments], cwd=tmp_path)
    assert (actual.returncode, actual.stdout, actual.stderr) == (expected.returncode, expected.stdout, expected.stderr)


@pytest.mark.parametrize("path", LEAVES, ids=[" ".join(path) for path in LEAVES])
def test_every_native_command_and_option_help_forwarded(path, tmp_path):
    expected = subprocess.run([str(get_cli_executable()), *path, "--help"], cwd=tmp_path, capture_output=True, check=False)
    actual = run_wrapper(["run", "--", *path, "--help"], cwd=tmp_path)
    assert expected.returncode == 0
    assert (actual.returncode, actual.stdout, actual.stderr) == (expected.returncode, expected.stdout, expected.stderr)


def test_upstream_auth_status_is_delegated_without_wrapper_profiles(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key not in {"ACCESS_TOKEN", "AD_ACCOUNT_ID", "BUSINESS_ID"}}
    expected = subprocess.run([str(get_cli_executable()), "auth", "status"], cwd=tmp_path, env=environment, capture_output=True, check=False)
    actual = run_wrapper(["run", "--", "auth", "status"], cwd=tmp_path, env=environment)
    assert (actual.returncode, actual.stdout, actual.stderr) == (expected.returncode, expected.stdout, expected.stderr)
    assert actual.returncode == 3
    assert b"Set the ACCESS_TOKEN environment variable" in actual.stderr
    assert not actual.stdout


def test_standard_wrapper_help_version_and_native_boundary():
    result = run_wrapper(["--help"])
    assert result.returncode == 0 and b"run" in result.stdout
    result = run_wrapper(["--version"])
    assert result.returncode == 0 and b"0.2.0" in result.stdout
    result = run_wrapper(["run", "--", "--version"])
    assert result.returncode == 0 and b"1.2.0" in result.stdout


def test_complete_argv_preserved_without_shell_or_whitelist(monkeypatch):
    seen = []
    monkeypatch.setattr(client, "get_cli_executable", lambda: Path("/private/upstream/meta"))
    monkeypatch.setattr(client.os, "execv", lambda executable, args: seen.append((executable, args)))
    arguments = ["--output", "json", "ads", "future-command", "--new-option", "literal $(touch /nope)", "", "--", "--no-cache"]
    client.execute(arguments)
    assert seen == [("/private/upstream/meta", ["/private/upstream/meta", *arguments])]


@pytest.mark.parametrize("error,code", [(FileNotFoundError(), 127), (PermissionError(), 126)])
def test_missing_or_nonexecutable_dependency_fails_clearly(monkeypatch, capsys, error, code):
    def fail(*args):
        raise error
    monkeypatch.setattr(client.os, "execv", fail)
    with pytest.raises(SystemExit) as caught:
        client.execute(["--help"])
    assert caught.value.code == code
    captured = capsys.readouterr()
    assert not captured.out
    assert "canonical CLI installer" in captured.err


def fake_launcher(tmp_path, body):
    executable = tmp_path / "meta-test"
    executable.write_text(f"#!{sys.executable}\n" + body)
    executable.chmod(0o700)
    script = ("from pathlib import Path; from facebook_ads_cli import client; "
              f"client.get_cli_executable=lambda: Path({str(executable)!r}); "
              "from facebook_ads_cli.main import main; main()")
    return [sys.executable, "-c", script, "run", "--"]


def test_binary_streams_large_stdin_exit_and_native_args(tmp_path):
    command = fake_launcher(tmp_path, "import sys,json\n"
                            "payload=sys.stdin.buffer.read()\n"
                            "sys.stdout.buffer.write(payload + b'\\x00END')\n"
                            "sys.stderr.write(json.dumps(sys.argv[1:]))\n"
                            "raise SystemExit(19)\n")
    arguments = ["--no-cache", "future-subcommand", "--help", "space value", ""]
    payload = (b"binary\x00\xff\n" * 100000)
    result = subprocess.run([*command, *arguments], input=payload, capture_output=True, check=False)
    assert result.returncode == 19
    assert result.stdout == payload + b"\x00END"
    assert json.loads(result.stderr) == arguments


def test_native_signal_exit_is_preserved(tmp_path):
    command = fake_launcher(tmp_path, "import os,signal\nos.kill(os.getpid(), signal.SIGTERM)\n")
    result = subprocess.run(command, capture_output=True, check=False)
    assert result.returncode == -signal.SIGTERM
    assert not result.stdout and not result.stderr


def test_wrapper_does_not_import_or_initialize_old_auth():
    source = Path(__file__).resolve().parents[1] / "facebook_ads_cli"
    assert not (source / "catalog.py").exists()
    assert not (source / "commands").exists()
    assert "BaseConfig" not in (source / "config.py").read_text()
    assert "create_auth_app" not in (source / "main.py").read_text()
