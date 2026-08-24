"""Fail-fast subprocess wrappers for talking to adam-server.

One execution path each: a non-zero exit raises `DeployError` immediately.
There is no retry, no swallowed error, no fallback -- a failed ssh/scp/git
call is a bug to surface, not a condition to work around.
"""
from __future__ import annotations

import shlex
import subprocess

from . import config


class DeployError(RuntimeError):
    """A local or remote command the deploy pipeline depends on failed."""


def run_local(argv: list[str], input: str | None = None) -> str:
    result = subprocess.run(argv, input=input, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeployError(
            "local command failed (%d): %s\n%s"
            % (result.returncode, " ".join(argv), result.stderr.strip()))
    return result.stdout


def run_remote(argv: list[str]) -> str:
    """Run one argv-safe command on adam-server: no shell-string assembly."""
    remote_cmd = " ".join(shlex.quote(a) for a in argv)
    return run_local(["ssh", config.REMOTE_HOST, remote_cmd])


def run_remote_script(script: str) -> str:
    """Run a multi-line bash script on adam-server via `ssh host bash -s`.

    For the pm2/release steps that need real shell control flow (loops,
    `set -euo pipefail`), the same shape CourseCraft's `deploy.sh` uses with
    a heredoc -- piped over stdin here instead.
    """
    return run_local(["ssh", config.REMOTE_HOST, "bash", "-s"], input=script)
