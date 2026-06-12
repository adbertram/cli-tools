import requests
from pathlib import Path

from manus_cli import client as client_module
from manus_cli import config as config_module


class FakeConfig:
    base_url = "https://api.manus.ai"
    api_key = "test-key"

    @staticmethod
    def get_missing_credentials():
        return []


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or ""
        self.reason = "OK"

    def json(self):
        return self._payload


def make_client(monkeypatch):
    monkeypatch.setattr(client_module, "get_config", lambda profile=None: FakeConfig())
    return client_module.ManusClient()


def test_v2_methods_use_documented_endpoints_and_header(monkeypatch):
    client = make_client(monkeypatch)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/v2/task.detail"):
            return FakeResponse({"ok": True, "task": {"id": "task-1", "status": "running"}})
        if url.endswith("/v2/task.list"):
            return FakeResponse({"ok": True, "data": []})
        if url.endswith("/v2/task.listMessages"):
            return FakeResponse({"ok": True, "messages": []})
        if url.endswith("/v2/task.delete"):
            return FakeResponse({"ok": True, "id": "task-1", "deleted": True})
        if url.endswith("/v2/task.confirmAction"):
            return FakeResponse({"ok": True, "task_id": "task-1", "confirmed": True})
        return FakeResponse({"ok": True, "task_id": "task-1"})

    monkeypatch.setattr(requests, "request", fake_request)

    create_response = client.create_task(
        message={"content": "hello"},
        agent_profile="manus-1.6-max",
        share_visibility="team",
    )
    task = client.get_task("task-1")
    task_list = client.list_tasks(limit=3, cursor="cursor-1", order="asc", scope="project", project_id="proj-1")
    send_response = client.send_message("task-1", {"content": "follow-up"}, agent_profile="manus-1.6-lite")
    message_list = client.list_messages("task-1", limit=25, cursor="cursor-2", order="asc", verbose=True)
    update_response = client.update_task("task-1", title="Updated", visible_in_task_list=False)
    stop_response = client.stop_task("task-1")
    delete_response = client.delete_task("task-1")
    confirm_response = client.confirm_action("task-1", "evt-1", {"approved": True})

    assert create_response["task_id"] == "task-1"
    assert task["id"] == "task-1"
    assert task_list["data"] == []
    assert send_response["task_id"] == "task-1"
    assert message_list["messages"] == []
    assert update_response["task_id"] == "task-1"
    assert stop_response["ok"] is True
    assert delete_response == {"ok": True, "id": "task-1", "deleted": True}
    assert confirm_response == {"ok": True, "task_id": "task-1", "confirmed": True}

    expected_urls = [
        "/v2/task.create",
        "/v2/task.detail",
        "/v2/task.list",
        "/v2/task.sendMessage",
        "/v2/task.listMessages",
        "/v2/task.update",
        "/v2/task.stop",
        "/v2/task.delete",
        "/v2/task.confirmAction",
    ]
    assert [url.removeprefix("https://api.manus.ai") for _, url, _ in calls] == expected_urls

    create_method, _, create_kwargs = calls[0]
    assert create_method == "POST"
    assert create_kwargs["headers"]["x-manus-api-key"] == "test-key"
    assert create_kwargs["json"] == {
        "message": {"content": "hello"},
        "agent_profile": "manus-1.6-max",
        "interactive_mode": False,
        "hide_in_task_list": False,
        "share_visibility": "team",
    }

    _, _, detail_kwargs = calls[1]
    assert detail_kwargs["params"] == {"task_id": "task-1"}

    _, _, list_kwargs = calls[2]
    assert list_kwargs["params"] == {
        "limit": 3,
        "order": "asc",
        "cursor": "cursor-1",
        "scope": "project",
        "project_id": "proj-1",
    }

    _, _, send_kwargs = calls[3]
    assert send_kwargs["json"] == {
        "task_id": "task-1",
        "message": {"content": "follow-up"},
        "agent_profile": "manus-1.6-lite",
    }

    _, _, messages_kwargs = calls[4]
    assert messages_kwargs["params"] == {
        "task_id": "task-1",
        "limit": 25,
        "order": "asc",
        "cursor": "cursor-2",
        "verbose": "true",
    }

    _, _, update_kwargs = calls[5]
    assert update_kwargs["json"] == {
        "task_id": "task-1",
        "title": "Updated",
        "enable_visible_in_task_list": False,
    }

    _, _, stop_kwargs = calls[6]
    assert stop_kwargs["json"] == {"task_id": "task-1"}

    _, _, delete_kwargs = calls[7]
    assert delete_kwargs["json"] == {"task_id": "task-1"}

    _, _, confirm_kwargs = calls[8]
    assert confirm_kwargs["json"] == {
        "task_id": "task-1",
        "event_id": "evt-1",
        "input": {"approved": True},
    }


def test_wait_for_task_returns_task_and_messages_on_stopped_status(monkeypatch):
    client = make_client(monkeypatch)
    monkeypatch.setattr(client, "get_task", lambda task_id: {"id": task_id, "status": "running"})
    monkeypatch.setattr(
        client,
        "list_messages",
        lambda **kwargs: {
            "messages": [
                {
                    "id": "status-1",
                    "type": "status_update",
                    "status_update": {
                        "agent_status": "stopped",
                        "brief": "Finished successfully",
                    },
                },
                {
                    "id": "assistant-1",
                    "type": "assistant_message",
                    "assistant_message": {"content": "done"},
                },
            ]
        },
    )

    result = client.wait_for_task("task-1", poll_interval=0.01, max_wait=1.0)

    assert result["task"] == {"id": "task-1", "status": "running"}
    assert result["messages"][0]["status_update"]["agent_status"] == "stopped"
    assert result["latest_status"]["id"] == "status-1"


def test_wait_for_task_raises_error_details_from_messages(monkeypatch):
    client = make_client(monkeypatch)
    monkeypatch.setattr(client, "get_task", lambda task_id: {"id": task_id, "status": "error"})
    monkeypatch.setattr(
        client,
        "list_messages",
        lambda **kwargs: {
            "messages": [
                {
                    "id": "status-1",
                    "type": "status_update",
                    "status_update": {"agent_status": "error"},
                },
                {
                    "id": "error-1",
                    "type": "error_message",
                    "error_message": {"content": "Model quota exhausted"},
                },
            ]
        },
    )

    try:
        client.wait_for_task("task-1", poll_interval=0.01, max_wait=1.0)
    except client_module.ClientError as exc:
        assert str(exc) == "Task task-1 failed: Model quota exhausted"
    else:  # pragma: no cover - defensive failure
        raise AssertionError("Expected ClientError")


def test_wait_for_task_keeps_polling_through_queued_waiting(monkeypatch):
    client = make_client(monkeypatch)
    monkeypatch.setattr(client, "get_task", lambda task_id: {"id": task_id, "status": "waiting"})

    message_batches = [
        {"messages": []},
        {
            "messages": [
                {
                    "id": "status-1",
                    "type": "status_update",
                    "status_update": {"agent_status": "waiting", "brief": "Queued"},
                }
            ]
        },
        {
            "messages": [
                {
                    "id": "status-2",
                    "type": "status_update",
                    "status_update": {"agent_status": "stopped", "brief": "Finished"},
                }
            ]
        },
    ]
    calls = {"count": 0}

    def fake_list_messages(**kwargs):
        batch = message_batches[min(calls["count"], len(message_batches) - 1)]
        calls["count"] += 1
        return batch

    monkeypatch.setattr(client, "list_messages", fake_list_messages)

    result = client.wait_for_task("task-1", poll_interval=0.01, max_wait=1.0)

    assert calls["count"] == 3
    assert result["latest_status"]["status_update"]["agent_status"] == "stopped"
    assert result["task"] == {"id": "task-1", "status": "waiting"}


def test_wait_for_task_returns_on_waiting_with_confirmable_event(monkeypatch):
    client = make_client(monkeypatch)
    monkeypatch.setattr(client, "get_task", lambda task_id: {"id": task_id, "status": "waiting"})
    monkeypatch.setattr(
        client,
        "list_messages",
        lambda **kwargs: {
            "messages": [
                {
                    "id": "status-1",
                    "type": "status_update",
                    "status_update": {
                        "agent_status": "waiting",
                        "brief": "Needs confirmation",
                        "status_detail": {
                            "waiting_for_event_id": "evt-1",
                            "waiting_for_event_type": "messageAskUser",
                        },
                    },
                }
            ]
        },
    )

    result = client.wait_for_task("task-1", poll_interval=0.01, max_wait=1.0)

    detail = result["latest_status"]["status_update"]["status_detail"]
    assert detail["waiting_for_event_id"] == "evt-1"
    assert detail["waiting_for_event_type"] == "messageAskUser"


def test_wait_for_task_times_out_on_queued_waiting_status(monkeypatch):
    client = make_client(monkeypatch)
    monkeypatch.setattr(client, "get_task", lambda task_id: {"id": task_id, "status": "waiting"})
    monkeypatch.setattr(client, "list_messages", lambda **kwargs: {"messages": []})

    try:
        client.wait_for_task("task-1", poll_interval=0.01, max_wait=0.05)
    except client_module.ClientError as exc:
        assert "timed out after 0.05 seconds" in str(exc)
    else:  # pragma: no cover - defensive failure
        raise AssertionError("Expected ClientError")


def test_config_test_connection_uses_v2_auth_header(monkeypatch, tmp_path):
    calls = []

    class Response:
        ok = True
        status_code = 200

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(config_module, "resolve_tool_dir", lambda _: tmp_path)

    config = config_module.Config()
    config._set("API_KEY", "test-key")
    config._set("BASE_URL", "https://api.manus.ai")

    assert config.test_connection() == {"api_test": "passed"}
    assert calls == [
        (
            "https://api.manus.ai/v2/task.list",
            {
                "headers": {"x-manus-api-key": "test-key"},
                "params": {"limit": 1},
                "timeout": 10,
            },
        )
    ]


def test_config_migrates_legacy_v1_base_url(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "resolve_tool_dir", lambda _: tmp_path)

    config = config_module.Config()
    config._set("BASE_URL", "https://api.manus.ai/v1")

    migrated = config_module.Config()

    assert migrated.base_url == "https://api.manus.ai"


def test_config_storage_dir_uses_profile_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "resolve_tool_dir", lambda _: tmp_path)

    config = config_module.Config()

    assert config.storage_dir == config.get_profile_data_dir()
