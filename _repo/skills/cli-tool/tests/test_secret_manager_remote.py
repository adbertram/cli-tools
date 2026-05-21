"""Regression tests for remote secret-manager dispatch and locked-keychain handling."""

from __future__ import annotations

import os
import pty
import stat
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
SECRETS_SCRIPT = REPO_ROOT / "_repo" / "_secret-manager" / "secrets.sh"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _base_env(fake_bin: Path, tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(tmp_path / "home")
    return env


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
        ["bash", str(SECRETS_SCRIPT), "--remote-host", "example-host", "set", "example-secret", "topsecret"],
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
    assert "example-secret" in ssh_args
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

    master_fd, slave_fd = pty.openpty()
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

    result = subprocess.run(
        [
            "bash",
            str(SECRETS_SCRIPT),
            "--remote-host",
            "example-host",
            "--remote-unlock-secret",
            "adam-server-sudo",
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
    echo "security: SecKeychainItemCreateFromContent (/Users/adam/Library/Keychains/login.keychain-db): User interaction is not allowed." >&2
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
    env["CLI_TOOLS_SECRETS_REMOTE_CONTEXT"] = "1"
    env["CLI_TOOLS_SECRETS_REMOTE_HOST"] = "adam-server"

    result = subprocess.run(
        ["bash", str(SECRETS_SCRIPT), "set", "example-secret", "topsecret"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert (
        "remote host adam-server requires an interactive TTY to unlock keychain"
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
if [[ "${1:-}" == "add-generic-password" ]]; then
    echo "security: SecKeychainItemCreateFromContent (/Users/adam/Library/Keychains/login.keychain-db): User interaction is not allowed." >&2
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


def test_has_returns_missing_only_for_keychain_not_found_status(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "security",
        """#!/usr/bin/env bash
set -euo pipefail
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
