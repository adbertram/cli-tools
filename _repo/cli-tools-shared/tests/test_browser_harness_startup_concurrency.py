import threading

import pytest

from browser_harness import _ipc as ipc
from browser_harness import admin
from browser_harness import daemon


def test_daemon_uses_parent_resolved_ws_without_second_http_discovery(monkeypatch):
    expected = "ws://127.0.0.1:51312/devtools/browser/verified"
    monkeypatch.setenv("BU_CDP_RESOLVED_WS", expected)
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(
        daemon.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daemon repeated CDP HTTP discovery")
        ),
    )

    assert daemon.get_ws_url() == expected


def test_startup_lock_serializes_same_daemon_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "_RUNTIME", tmp_path)
    monkeypatch.setattr(ipc, "BH_RUNTIME_DIR", str(tmp_path))
    first_has_lock = threading.Event()
    release_first = threading.Event()
    second_has_lock = threading.Event()

    def first():
        with ipc.startup_lock("stockx-default"):
            first_has_lock.set()
            assert release_first.wait(timeout=2)

    def second():
        assert first_has_lock.wait(timeout=2)
        with ipc.startup_lock("stockx-default"):
            second_has_lock.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()

    assert first_has_lock.wait(timeout=2)
    assert not second_has_lock.wait(timeout=0.1)
    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_has_lock.is_set()


def test_ensure_daemon_stops_child_that_misses_startup_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "_RUNTIME", tmp_path)
    monkeypatch.setattr(ipc, "BH_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(admin, "daemon_alive", lambda name=None: False)
    monkeypatch.setattr(admin, "_log_tail", lambda name=None: None)

    class Process:
        def __init__(self):
            self.running = True
            self.terminated = False

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

        def wait(self, timeout=None):
            return 0

    process = Process()
    monkeypatch.setattr(admin.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(RuntimeError, match="daemon stockx-default didn't come up"):
        admin.ensure_daemon(wait=0, name="stockx-default", env={})

    assert process.terminated is True
