"""Named cleanup uses only its own temporary IPC endpoint, never a browser."""
import os
import socket
import tempfile
from pathlib import Path

import pytest

from browser_harness import _ipc, admin, helpers
from cli_tools_shared.browser import driver


pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX Unix socket ownership proof")


def snapshot():
    return ({key: os.environ.get(key) for key in ("BH_RUNTIME_DIR", "BH_TMP_DIR", "BH_IPC_TIMEOUT")},
        {key: getattr(_ipc, key) for key in ("_RUNTIME", "_TMP", "BH_RUNTIME_DIR", "BH_TMP_DIR")},
        {key: getattr(helpers, key) for key in ("NAME", "SOCK")})


@pytest.fixture
def isolated_ipc(monkeypatch):
    # Restore cached globals even when a regression intentionally leaves them
    # bound incorrectly. Short paths stay inside macOS's AF_UNIX budget.
    for key in ("_RUNTIME", "_TMP", "BH_RUNTIME_DIR", "BH_TMP_DIR"):
        monkeypatch.setattr(_ipc, key, getattr(_ipc, key))
    for key in ("NAME", "SOCK"):
        monkeypatch.setattr(helpers, key, getattr(helpers, key))
    for key in ("BH_RUNTIME_DIR", "BH_TMP_DIR", "BH_IPC_TIMEOUT"):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)
    with tempfile.TemporaryDirectory(prefix="cleanup-ipc-", dir="/tmp") as temp:
        def runtime(session):
            path = Path(temp) / session
            path.mkdir(exist_ok=True)
            return path
        monkeypatch.setattr(driver, "_ensure_runtime_dir", runtime)
        monkeypatch.setattr(driver.os, "kill", lambda *args: pytest.fail("No process may be signaled"))
        yield


def services_with_cached_other(owner_name, other_name, monkeypatch):
    other = driver.BrowserHarnessService(other_name)
    other._bh.h  # TikTok's observer has connected before Whop is constructed.
    owner = driver.BrowserHarnessService(owner_name)  # Sets env, not cached IPC.
    monkeypatch.setattr(owner, "_stale_session_process_pids", lambda: [], raising=False)
    return owner, other


@pytest.mark.parametrize("owner_name,other_name", [("whop-rewards", "tiktok-clipper"),
    ("tiktok-clipper", "whop-rewards")])
def test_stale_cleanup_uses_owned_real_socket_and_preserves_other(owner_name, other_name, isolated_ipc, monkeypatch):
    owner, other = services_with_cached_other(owner_name, other_name, monkeypatch)
    sockets = []
    try:
        for service in (owner, other):
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(service._runtime_dir / "bu.sock"))
            listener.listen(4)
            sockets.append(listener)
        # The unrelated observer can connect before cleanup and must be able
        # to make another connection afterward, like the actual event drain.
        connection, _ = _ipc.connect(other.session)
        connection.close()
        before = snapshot()
        restarted = []
        def restart(name=None):
            connection, _ = _ipc.connect(name)
            try:
                restarted.append(connection.getpeername())
            finally:
                connection.close()
            _ipc.cleanup_endpoint(name)
        monkeypatch.setattr(admin, "restart_daemon", restart)
        checked = []
        monkeypatch.setattr(owner, "_cleanup_session_lock_files",
            lambda: checked.append((_ipc._RUNTIME, helpers.NAME)))
        owner._cleanup_stale_session()
        assert restarted == [str(owner._runtime_dir / "bu.sock")]
        assert not (owner._runtime_dir / "bu.sock").exists()
        assert (other._runtime_dir / "bu.sock").exists()
        assert checked == [(owner._runtime_dir, owner.session)]
        assert snapshot() == before
        connection, _ = _ipc.connect(other.session)
        connection.close()
    finally:
        for listener in sockets:
            listener.close()


@pytest.mark.parametrize("owner_name,other_name", [("whop-rewards", "tiktok-clipper"),
    ("tiktok-clipper", "whop-rewards")])
@pytest.mark.parametrize("failure_stage", ["restart", "profile_check"])
def test_stale_cleanup_exception_restores_original_ipc_context(owner_name, other_name, failure_stage, isolated_ipc, monkeypatch):
    owner, other = services_with_cached_other(owner_name, other_name, monkeypatch)
    before = snapshot()
    reached = []
    def checkpoint(stage):
        assert _ipc._RUNTIME == owner._runtime_dir
        assert helpers.NAME == owner.session
        reached.append(stage)
        if stage == failure_stage:
            raise RuntimeError("exact cleanup failure")
    monkeypatch.setattr(admin, "restart_daemon", lambda name=None: checkpoint("restart"))
    monkeypatch.setattr(owner, "_cleanup_session_lock_files", lambda: checkpoint("profile_check"))
    with pytest.raises(RuntimeError, match="exact cleanup failure"):
        owner._cleanup_stale_session()
    assert reached == (["restart"] if failure_stage == "restart" else ["restart", "profile_check"])
    assert snapshot() == before
