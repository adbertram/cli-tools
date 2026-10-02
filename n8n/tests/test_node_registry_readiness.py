from types import SimpleNamespace

import requests

from n8n_cli import server as server_runtime
from n8n_cli.commands import logs, server, server_config
from n8n_cli.n8n_api import N8nApiClient


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def test_wait_for_node_registry_does_not_accept_rest_only_readiness(monkeypatch):
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    client._get_session_cookie = lambda: "n8n-auth=test"
    statuses = iter([404, 200])
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(next(statuses))

    monkeypatch.setattr(requests, "get", fake_get)

    assert client.wait_for_node_registry(timeout=1, poll_interval=0) is True
    assert [url for url, _ in calls] == [
        "http://example.test/types/nodes.json",
        "http://example.test/types/nodes.json",
    ]
    assert all(call[1]["headers"] == {"cookie": "n8n-auth=test"} for call in calls)


def test_wait_for_restart_readiness_checks_rest_before_node_registry(monkeypatch):
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    calls = []

    def wait_for_ready(*, timeout, poll_interval):
        calls.append(("basic", timeout, poll_interval))

    def wait_for_node_registry(*, timeout, poll_interval):
        calls.append(("node_registry", timeout, poll_interval))

    monkeypatch.setattr(client, "wait_for_ready", wait_for_ready)
    monkeypatch.setattr(client, "wait_for_node_registry", wait_for_node_registry)

    assert client.wait_for_restart_readiness(timeout=60, poll_interval=0) is True
    assert calls == [("basic", 60, 0), ("node_registry", 60, 0)]


def test_shared_restart_waits_for_restart_readiness(monkeypatch):
    calls = []
    server_calls = []

    class FakeApi:
        def wait_for_restart_readiness(self, timeout):
            calls.append(("restart_readiness", timeout))

    monkeypatch.setattr(
        server_runtime,
        "run_on_server_raw",
        lambda command, **_kwargs: (
            server_calls.append(command) or SimpleNamespace(returncode=0, stderr="")
        ),
    )
    monkeypatch.setattr(server_runtime.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server_runtime, "get_n8n_api_client", FakeApi)

    server_runtime.restart_n8n()

    assert server_calls == [
        f"sudo launchctl unload {server_runtime.N8N_PLIST}",
        f"sudo launchctl load {server_runtime.N8N_PLIST}",
    ]
    assert calls == [("restart_readiness", 60)]


def test_server_restart_reports_ready_after_shared_restart(monkeypatch):
    restart_calls = []
    success_messages = []

    monkeypatch.setattr(server, "restart_n8n", lambda: restart_calls.append("restart"))
    monkeypatch.setattr(server, "print_info", lambda _message: None)
    monkeypatch.setattr(server, "print_success", success_messages.append)

    server.restart()

    assert restart_calls == ["restart"]
    assert success_messages == ["n8n restarted and ready"]


def test_server_config_restart_uses_selected_plist(monkeypatch):
    restart_calls = []

    monkeypatch.setattr(server_config, "run_on_server", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(server_config, "print_info", lambda _message: None)
    monkeypatch.setattr(server_config, "print_success", lambda _message: None)
    monkeypatch.setattr(
        server_config,
        "restart_n8n",
        lambda **kwargs: restart_calls.append(kwargs),
    )

    server_config.config_set(
        "EXECUTIONS_DATA_MAX_AGE",
        "168",
        plist_path="/tmp/custom-n8n.plist",
    )

    assert restart_calls == [{"plist_path": "/tmp/custom-n8n.plist"}]


def test_log_config_restart_uses_selected_plist(monkeypatch):
    restart_calls = []

    monkeypatch.setattr(logs, "run_on_server", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(logs, "print_info", lambda _message: None)
    monkeypatch.setattr(
        logs,
        "restart_n8n",
        lambda **kwargs: restart_calls.append(kwargs),
    )

    logs.logs_set_level(
        "info",
        log_format=None,
        log_output=None,
        db_logging=None,
        restart=True,
        plist_path="/tmp/custom-n8n.plist",
    )

    assert restart_calls == [{"plist_path": "/tmp/custom-n8n.plist"}]
