"""Bounded byte capture for owned, noninteractive read subprocesses (POSIX)."""
from dataclasses import dataclass
import math
import os
import select
import selectors
import signal
import subprocess
import sys
import time

from .exceptions import ClientError


class BoundedReadError(ClientError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.category = 'transient'
        self.status = None
        self.retry_after_seconds = None
        self.cleanup_failed = False


@dataclass(frozen=True)
class ReadResult:
    stdout: bytes
    returncode: int
    stderr_bytes: int


def run_bounded_read(argv, *, timeout_seconds, max_stdout_bytes, max_stderr_bytes=65536, on_start=None, on_poll=None):
    """Retain raw stdout bytes; count/discard stderr, never put argv in errors.

    Wall deadline includes draining and child exit. A separate 0.75s allowance
    bounds kill/reap cleanup. The unreaped leader reserves its PID/PGID until
    the owned group is killed, including on normal completion.
    """
    if type(argv) not in (list, tuple) or not argv or any(type(x) is not str or not x or '\0' in x for x in argv):
        raise BoundedReadError('read_process_arguments_invalid')
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
        raise BoundedReadError('read_process_timeout_invalid')
    if any(type(n) is not int or not 0 < n <= 32 * 1024 * 1024 for n in (max_stdout_bytes, max_stderr_bytes)):
        raise BoundedReadError('read_process_byte_bound_invalid')
    if any(callback is not None and not callable(callback) for callback in (on_start, on_poll)):
        raise BoundedReadError('read_process_callback_invalid')
    return _run(argv, timeout_seconds, max_stdout_bytes, max_stderr_bytes, on_start=on_start, on_poll=on_poll)


class _ExitWatch:
    """Non-reaping check that the owned leader has exited, so its PID/PGID stay reserved.

    os.waitid with WNOWAIT where the platform has it. macOS gained os.waitid only in
    Python 3.13; before that a kqueue EVFILT_PROC NOTE_EXIT watch answers the same question
    without reaping. Registering on our own unreaped child fails with ESRCH only once it is
    already a zombie, which is an exit.
    """

    def __init__(self, pid):
        self.pid = pid
        self.exited = False
        self.kqueue = None
        if not hasattr(os, 'waitid'):
            self.kqueue = select.kqueue()
            try:
                self.kqueue.control([select.kevent(pid, select.KQ_FILTER_PROC, select.KQ_EV_ADD, select.KQ_NOTE_EXIT)], 0, 0)
            except ProcessLookupError:
                self.exited = True

    def poll(self):
        if not self.exited:
            if self.kqueue is None:
                self.exited = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
            else:
                self.exited = bool(self.kqueue.control(None, 1, 0))
        return self.exited

    def close(self):
        if self.kqueue is not None:
            self.kqueue.close()


def _group_has_no_live_members(pgid):
    # Existing browser inspection includes argv and lacks a deadline. This fixed
    # numeric-only system ps is independently bounded and never spawns children.
    try:
        result=_run(['/bin/ps','-axo','pgid=,stat='],.25,131072,4096,numeric_inspection=True,cleanup_seconds=.25)
        if result.returncode!=0 or not result.stdout.strip():return False
        for line in result.stdout.decode('ascii').splitlines():
            columns=line.split()
            if len(columns)!=2 or not columns[0].isdigit() or not columns[1]:return False
            if int(columns[0])==pgid and not columns[1].startswith('Z'):return False
        return True
    except (BoundedReadError,OSError,UnicodeError):
        return False


def _run(argv, timeout_seconds, max_stdout_bytes, max_stderr_bytes, *, numeric_inspection=False,cleanup_seconds=.75,on_start=None,on_poll=None):
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
    except OSError:
        raise BoundedReadError('read_process_start_failed') from None
    output = bytearray()
    stderr_bytes = 0
    failure = None
    selector = None
    exited = None
    watch = None
    try:
        watch = _ExitWatch(process.pid)
        if on_start is not None:on_start(process.pid, deadline)
        selector = selectors.DefaultSelector()
        for stream, name in ((process.stdout, 'stdout'), (process.stderr, 'stderr')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while True:
            if on_poll is not None:on_poll(deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BoundedReadError('read_process_deadline_exceeded')
            # WNOWAIT prevents PID reuse before cleanup signals the owned group.
            exited = True if watch.poll() else None
            if not selector.get_map() and exited is not None:
                break
            for key, _ in selector.select(min(remaining, 0.05)):
                current = len(output) if key.data == 'stdout' else stderr_bytes
                bound = max_stdout_bytes if key.data == 'stdout' else max_stderr_bytes
                try:
                    chunk = os.read(key.fd, min(4096, bound - current + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if current + len(chunk) > bound:
                    raise BoundedReadError('read_process_' + key.data + '_exceeds_bound')
                if key.data == 'stdout':
                    output.extend(chunk)
                else:
                    stderr_bytes += len(chunk)
    except BaseException as error:
        failure = error
        raise
    finally:
        cleanup_deadline=time.monotonic()+cleanup_seconds
        if selector is not None:selector.close()
        if watch is not None:watch.close()
        process.stdout.close()
        process.stderr.close()
        cleanup_unconfirmed=False
        try:
            if numeric_inspection:
                if exited is None:process.kill()
            else:os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:pass
        except PermissionError:
            # Darwin returns EPERM for zombie-only groups. Leader-exited alone
            # is insufficient; independently refuse any live/unknown member.
            cleanup_unconfirmed=not (sys.platform=='darwin' and exited is not None and _group_has_no_live_members(process.pid))
        try:
            process.wait(timeout=max(.001,cleanup_deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            cleanup_unconfirmed=True
        if cleanup_unconfirmed:
            if isinstance(failure, BoundedReadError):failure.cleanup_failed=True
            elif failure is not None and hasattr(failure,'cleanup_failed'):
                try:failure.cleanup_failed=True
                except (AttributeError,TypeError):pass
            elif failure is None:raise BoundedReadError('read_process_cleanup_unconfirmed') from None
    return ReadResult(bytes(output), process.returncode, stderr_bytes)
