"""Regression tests for remote secret-manager dispatch and locked-keychain handling."""

from __future__ import annotations

import os
import pty
import stat
import subprocess
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
SECRETS_SCRIPT = REPO_ROOT / "_repo" / "_secret-manager" / "secrets.sh"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _default_keychain(home: Path) -> Path:
    return home / ".local" / "share" / "cli-tools" / "cli-tools.keychain-db"


def _base_env(
    fake_bin: Path, tmp_path: Path, *, create_default_keychain: bool = True
) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("XDG_DATA_HOME", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    home = tmp_path / "home"
    env["HOME"] = str(home)
    if create_default_keychain:
        keychain = _default_keychain(home)
        keychain.parent.mkdir(parents=True, exist_ok=True)
        keychain.touch()
    return env


def test_default_keychain_is_stored_under_cli_tools_user_profile(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    security_log = tmp_path / "security.log"

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_SECURITY_LOG:?}"
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "dump-keychain" ]]; then
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_SECURITY_LOG"] = str(security_log)

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "list"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    security_log_text = security_log.read_text()
    assert str(_default_keychain(Path(env["HOME"]))) in security_log_text
    assert "Library/Keychains/login.keychain-db" not in security_log_text


def test_default_keychain_is_created_when_missing(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    security_log = tmp_path / "security.log"

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_SECURITY_LOG:?}"
if [[ "${1:-}" == "create-keychain" ]]; then
    keychain="${@: -1}"
    mkdir -p "$(dirname "$keychain")"
    : >"$keychain"
    exit 0
fi
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "add-generic-password" ]]; then
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path, create_default_keychain=False)
    env["FAKE_SECURITY_LOG"] = str(security_log)

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "set", "example-secret", "topsecret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    keychain = _default_keychain(Path(env["HOME"]))
    security_log_text = security_log.read_text()
    assert keychain.exists()
    assert f"create-keychain -p  {keychain}" in security_log_text
    assert f"add-generic-password -U -s cli-tools -a example-secret -w topsecret {keychain}" in security_log_text


def test_set_accepts_tool_and_type_and_stores_canonical_secret_name(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    security_log = tmp_path / "security.log"

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_SECURITY_LOG:?}"
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "add-generic-password" ]]; then
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_SECURITY_LOG"] = str(security_log)

    result = subprocess.run(
        [
            "bash",
            str(SECRETS_SCRIPT),
            "set",
            "--tool",
            "venmo",
            "--type",
            "username",
            "topsecret",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "add-generic-password -U -s cli-tools -a venmo-username" in security_log.read_text()


def test_rename_moves_old_secret_to_tool_type_name_without_printing_value(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    security_log = tmp_path / "security.log"

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_SECURITY_LOG:?}"
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "find-generic-password" && "$*" == *" -w "* && "$*" == *" -a old-secret "* ]]; then
    printf 'topsecret'
    exit 0
fi
if [[ "${1:-}" == "find-generic-password" && "$*" == *" -a venmo-password "* ]]; then
    echo "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain." >&2
    exit 44
fi
if [[ "${1:-}" == "add-generic-password" ]]; then
    exit 0
fi
if [[ "${1:-}" == "delete-generic-password" && "$*" == *" -a old-secret "* ]]; then
    echo "password has been deleted." >&2
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_SECURITY_LOG"] = str(security_log)

    result = subprocess.run(
        [
            "bash",
            str(SECRETS_SCRIPT),
            "rename",
            "old-secret",
            "--tool",
            "venmo",
            "--type",
            "password",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    security_log_text = security_log.read_text()
    assert "add-generic-password -U -s cli-tools -a venmo-password -w topsecret" in security_log_text
    assert "delete-generic-password -s cli-tools -a old-secret" in security_log_text
    assert "topsecret" not in result.stdout
    assert "topsecret" not in result.stderr


def test_remote_host_set_copies_secret_payload_file_instead_of_streaming_ssh_stdin(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_log_dir = tmp_path / "logs"
    remote_log_dir.mkdir()

    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
log_dir="${FAKE_REMOTE_LOG_DIR:?}"
count_file="$log_dir/ssh_count"
count=0
if [[ -f "$count_file" ]]; then
    count="$(cat "$count_file")"
fi
count="$((count + 1))"
printf '%s' "$count" >"$count_file"
printf '%s\n' "$*" >>"$log_dir/ssh_args.log"
if [[ "$count" == "1" ]]; then
    printf '/tmp/fake-remote-dir\n'
    exit 0
fi
cat >"$log_dir/ssh_stdin.bin"
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_REMOTE_LOG_DIR:?}/scp_args.log"
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_REMOTE_LOG_DIR"] = str(remote_log_dir)

    result = subprocess.run(
        [
            "bash",
            str(SECRETS_SCRIPT),
            "--remote-host",
            "example-host",
            "set",
            "--tool",
            "venmo",
            "--type",
            "username",
            "topsecret",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    ssh_args = (remote_log_dir / "ssh_args.log").read_text()
    scp_args = (remote_log_dir / "scp_args.log").read_text()
    ssh_stdin = (remote_log_dir / "ssh_stdin.bin").read_text()

    assert "topsecret" not in ssh_args
    assert "topsecret" not in scp_args
    assert "CLI_TOOLS_SECRETS_REMOTE_CONTEXT=1" in ssh_args
    assert "CLI_TOOLS_SECRETS_REMOTE_HOST=example-host" in ssh_args
    assert "set" in ssh_args
    assert "venmo-username" in ssh_args
    assert "--tool" not in ssh_args
    assert "--type" not in ssh_args
    assert "example-host:/tmp/fake-remote-dir/secrets.sh" in scp_args
    assert "example-host:/tmp/fake-remote-dir/secret.value" in scp_args
    assert ssh_stdin == ""
    assert "topsecret" not in result.stdout
    assert "topsecret" not in result.stderr


def test_remote_host_set_with_tty_does_not_stream_secret_over_ssh_stdin(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_log_dir = tmp_path / "logs"
    remote_log_dir.mkdir()

    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
log_dir="${FAKE_REMOTE_LOG_DIR:?}"
count_file="$log_dir/ssh_count"
count=0
if [[ -f "$count_file" ]]; then
    count="$(cat "$count_file")"
fi
count="$((count + 1))"
printf '%s' "$count" >"$count_file"
printf '%s\n' "$*" >>"$log_dir/ssh_args.log"
if [[ "$count" == "1" ]]; then
    printf '/tmp/fake-remote-dir\n'
    exit 0
fi
cat >"$log_dir/ssh_stdin.bin"
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_REMOTE_LOG_DIR:?}/scp_args.log"
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_REMOTE_LOG_DIR"] = str(remote_log_dir)

    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as exc:
        pytest.skip(f"PTY allocation is unavailable on this host: {exc}")
    proc = subprocess.Popen(
        ["bash", str(SECRETS_SCRIPT), "--remote-host", "example-host", "set", "example-secret"],
        stdin=subprocess.PIPE,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        text=True,
    )

    assert proc.stdin is not None
    proc.stdin.write("topsecret")
    proc.stdin.close()
    os.close(slave_fd)

    tty_output_chunks: list[str] = []
    while True:
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        tty_output_chunks.append(chunk.decode())
    os.close(master_fd)

    returncode = proc.wait()
    tty_output = "".join(tty_output_chunks)

    assert returncode == 0, tty_output

    ssh_args = (remote_log_dir / "ssh_args.log").read_text()
    scp_args = (remote_log_dir / "scp_args.log").read_text()
    ssh_stdin = (remote_log_dir / "ssh_stdin.bin").read_text()

    assert "-tt" in ssh_args
    assert "topsecret" not in ssh_args
    assert "topsecret" not in scp_args
    assert "topsecret" not in tty_output
    assert "example-host:/tmp/fake-remote-dir/secret.value" in scp_args
    assert ssh_stdin == ""


def test_remote_host_unlock_secret_unlocks_keychain_in_remote_command(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_log_dir = tmp_path / "logs"
    remote_log_dir.mkdir()

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_REMOTE_LOG_DIR:?}/security_args.log"
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "find-generic-password" ]]; then
    printf 'unlock-password'
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
log_dir="${FAKE_REMOTE_LOG_DIR:?}"
count_file="$log_dir/ssh_count"
count=0
if [[ -f "$count_file" ]]; then
    count="$(cat "$count_file")"
fi
count="$((count + 1))"
printf '%s' "$count" >"$count_file"
printf '%s\n' "$*" >>"$log_dir/ssh_args.log"
if [[ "$count" == "1" ]]; then
    printf '/tmp/fake-remote-dir\n'
    exit 0
fi
cat >"$log_dir/ssh_stdin.bin"
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_REMOTE_LOG_DIR:?}/scp_args.log"
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_REMOTE_LOG_DIR"] = str(remote_log_dir)
    env["CLI_TOOLS_KEYCHAIN"] = str(tmp_path / "custom.keychain-db")

    result = subprocess.run(
        [
            "bash",
            str(SECRETS_SCRIPT),
            "--remote-host",
            "example-host",
            "--remote-unlock-secret",
            "cli-tools-remote-unlock",
            "set",
            "example-secret",
            "topsecret",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    ssh_args = (remote_log_dir / "ssh_args.log").read_text()
    scp_args = (remote_log_dir / "scp_args.log").read_text()
    ssh_stdin = (remote_log_dir / "ssh_stdin.bin").read_text()

    assert "security\\ unlock-keychain\\ -p" in ssh_args
    assert "\\$keychain_password" in ssh_args
    assert "example-host:/tmp/fake-remote-dir/keychain-password" in scp_args
    assert "example-host:/tmp/fake-remote-dir/secret.value" in scp_args
    assert "topsecret" not in ssh_args
    assert "topsecret" not in scp_args
    assert "topsecret" not in result.stdout
    assert "topsecret" not in result.stderr
    assert "unlock-password" not in ssh_args
    assert "unlock-password" not in scp_args
    assert "unlock-password" not in result.stdout
    assert "unlock-password" not in result.stderr
    assert ssh_stdin == ""


def test_remote_locked_keychain_without_tty_fails_clearly(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    security_log = tmp_path / "security.log"

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_SECURITY_LOG:?}"
if [[ "${1:-}" == "add-generic-password" ]]; then
    echo "security: SecKeychainItemCreateFromContent (/tmp/custom.keychain-db): User interaction is not allowed." >&2
    exit 1
fi
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)
    env["FAKE_SECURITY_LOG"] = str(security_log)
    env["CLI_TOOLS_KEYCHAIN"] = str(tmp_path / "custom.keychain-db")
    env["CLI_TOOLS_SECRETS_REMOTE_CONTEXT"] = "1"
    env["CLI_TOOLS_SECRETS_REMOTE_HOST"] = "example-host"

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "set", "example-secret", "topsecret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert (
        "remote host example-host requires an interactive TTY to unlock keychain"
        in result.stderr
    )
    security_log_text = security_log.read_text()
    assert "add-generic-password" in security_log_text
    assert "unlock-keychain" not in security_log_text


def test_set_fails_when_security_writes_error_to_stderr_with_zero_exit(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "add-generic-password" ]]; then
    echo "security: SecKeychainItemCreateFromContent (/tmp/custom.keychain-db): User interaction is not allowed." >&2
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "set", "example-secret", "topsecret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "User interaction is not allowed" in result.stderr


def test_get_fails_when_security_reports_missing_item_on_stderr_with_zero_exit(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "find-generic-password" ]]; then
    echo "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain." >&2
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "get", "example-secret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "The specified item could not be found in the keychain" in result.stderr
    assert result.stdout == ""


def test_delete_accepts_security_success_message_on_stderr(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
if [[ "${1:-}" == "delete-generic-password" ]]; then
    echo "password has been deleted." >&2
    exit 0
fi
echo "unexpected security command: $*" >&2
exit 99
""",
    )

    env = _base_env(fake_bin, tmp_path)

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "delete", "example-secret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_has_returns_missing_only_for_keychain_not_found_status(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "unlock-keychain" ]]; then
    exit 0
fi
case "${FAKE_SECURITY_MODE:?}" in
  missing)
    echo "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain." >&2
    exit 44
    ;;
  broken)
    echo "security: unexpected failure" >&2
    exit 5
    ;;
  *)
    echo "unexpected mode" >&2
    exit 99
    ;;
esac
""",
    )

    env = _base_env(fake_bin, tmp_path)

    env["FAKE_SECURITY_MODE"] = "missing"
    missing = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "has", "example-secret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert missing.returncode == 1

    env["FAKE_SECURITY_MODE"] = "broken"
    broken = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "has", "example-secret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert broken.returncode == 5
    assert "unexpected failure" in broken.stderr
