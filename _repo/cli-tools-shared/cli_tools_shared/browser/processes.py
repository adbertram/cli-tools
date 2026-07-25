"""Process-table helpers for persistent browser profiles."""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
import errno
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ProcessTableUnavailableError(RuntimeError):
    """Raised when the host sandbox forbids process-table inspection."""


@dataclass(frozen=True)
class ProcessCommand:
    pid: int
    ppid: int
    stat: str
    command: str


def _process_table_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and exc.errno in {errno.EACCES, errno.EPERM}:
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        output = f"{exc.stdout or ''}\n{exc.stderr or ''}".lower()
        return "operation not permitted" in output or "permission denied" in output
    return False


def list_process_commands() -> list[ProcessCommand]:
    """Return process-table rows with parent PID and command text."""
    try:
        result = subprocess.run(
            ["ps", "ax", "-o", "pid=,ppid=,stat=,command="],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if _process_table_error(exc):
            raise ProcessTableUnavailableError(
                "Process table inspection is unavailable in this environment. "
                "Close any Chrome window using this CLI profile, or run the command "
                "from a shell allowed to inspect local processes."
            ) from exc
        raise RuntimeError(f"Failed to inspect process table: {exc}") from exc

    rows: list[ProcessCommand] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError(f"Failed to parse process-table row: {raw_line!r}") from exc
        stat = parts[2] if len(parts) >= 3 else ""
        command = parts[3] if len(parts) == 4 else ""
        rows.append(ProcessCommand(pid=pid, ppid=ppid, stat=stat, command=command))
    return rows


def command_user_data_dir(command: str) -> str | None:
    for pattern in (
        r"(?:^|\s)--user-data-dir=(?P<value>\"[^\"]+\"|'[^']+'|\S+)(?:\s|$)",
        r"(?:^|\s)--user-data-dir\s+(?P<value>\"[^\"]+\"|'[^']+'|\S+)(?:\s|$)",
    ):
        match = re.search(pattern, command)
        if not match:
            continue
        value = match.group("value")
        if value.startswith(("'", '"')) and value.endswith(("'", '"')):
            return value[1:-1]
        return value
    return None


def is_chromium_process_command(command: str) -> bool:
    """Return whether ``command`` invokes a Chrome/Chromium executable.

    A profile path in arbitrary shell, Python, or Node command text is not
    browser ownership evidence. Cleanup may signal only browser executables,
    never wrappers whose source text happens to contain Chrome launch flags.
    """
    # ``ps ... command=`` does not quote macOS app-bundle executable paths, so
    # shlex sees ``/Applications/Google`` instead of the real executable
    # ``.../Google Chrome``. Launch flags are the reliable boundary in that
    # representation. Keep shlex for normally quoted/POSIX command lines.
    executable_prefix = command.split(" --", 1)[0]
    if executable_prefix.startswith((
        "/Applications/Google Chrome",
        "/Applications/Chromium",
    )):
        name = Path(executable_prefix).name.lower()
    else:
        try:
            executable = shlex.split(command, posix=os.name != "nt")[0]
        except (IndexError, ValueError):
            return False
        name = Path(executable).name.lower()
    return "chrome" in name or "chromium" in name


def protected_process_ids(
    processes: Iterable[ProcessCommand],
    *,
    current_pid: int | None = None,
    parent_pid: int | None = None,
) -> set[int]:
    """Return the current process and its ancestor chain.

    Inline shell wrappers can contain target browser literals inside heredocs.
    Excluding the ancestry prevents process-table probes from selecting their
    own shell, Python, or runner process when those command lines mention the
    profile path being inspected.
    """
    current = os.getpid() if current_pid is None else current_pid
    parent = os.getppid() if parent_pid is None else parent_pid
    ppid_by_pid = {proc.pid: proc.ppid for proc in processes}
    protected: set[int] = set()

    for start in (current, parent):
        pid = start
        while pid and pid not in protected:
            protected.add(pid)
            pid = ppid_by_pid.get(pid, 0)
    return protected


def profile_process_pids(
    user_data_dir: str | Path,
    *,
    processes: Iterable[ProcessCommand] | None = None,
    current_pid: int | None = None,
    parent_pid: int | None = None,
) -> list[int]:
    """Return live process PIDs using exactly this Chrome user-data-dir."""
    rows = list(list_process_commands() if processes is None else processes)
    protected = protected_process_ids(
        rows,
        current_pid=current_pid,
        parent_pid=parent_pid,
    )
    profile = str(user_data_dir)
    pids: list[int] = []
    for proc in rows:
        if proc.pid in protected:
            continue
        if proc.stat.startswith("Z"):
            continue
        if (
            is_chromium_process_command(proc.command)
            and command_user_data_dir(proc.command) == profile
        ):
            pids.append(proc.pid)
    return pids


def _pid_running(pid: int) -> bool:
    for process in list_process_commands():
        if process.pid == pid:
            return not process.stat.startswith("Z")
    return False


def pid_is_running(pid: int) -> bool:
    """Return whether a PID exists without reading the full process table."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise RuntimeError(f"Failed to inspect process {pid}: {exc}") from exc
    return True


def terminate_process(
    pid: int,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
) -> None:
    """Terminate one process and fail if it remains alive."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise RuntimeError(f"Failed to stop browser process {pid}: {exc}") from exc

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_running(pid):
            return
        time.sleep(poll_interval)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise RuntimeError(f"Failed to force-stop browser process {pid}: {exc}") from exc

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_running(pid):
            return
        time.sleep(poll_interval)

    raise RuntimeError(f"Browser process {pid} did not exit")


def terminate_profile_processes(
    user_data_dir: str | Path,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
) -> list[int]:
    """Terminate live processes using exactly this Chrome user-data-dir."""
    pids = profile_process_pids(user_data_dir)
    for pid in pids:
        terminate_process(pid, timeout=timeout, poll_interval=poll_interval)
    return pids
