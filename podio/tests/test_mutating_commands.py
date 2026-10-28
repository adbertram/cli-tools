"""Wire-level tests for app delete, view, space member, file replace and item share.

A real pypodio2 Client over a real HttpTransport is used; only the socket-level
``_http.request`` is faked, so the HTTP method, URL and JSON body each command
sends are asserted exactly (nothing reaches the Podio API).
"""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pypodio2.client import Client
from pypodio2.transport import HttpTransport

from podio_cli.commands import app as app_cmd, file, item, space, view

runner = CliRunner()


class _Response(dict):
    def __init__(self, status):
        super().__init__()
        self.status = status


@pytest.fixture
def wire(monkeypatch):
    """Patch every command module's get_client with a fake-socket client."""
    calls = []
    state = {"status": 200, "data": b"{}"}

    transport = HttpTransport("https://api.podio.com", headers_factory=lambda: {})

    def fake_request(url, method, body=None, headers=None):
        calls.append({"method": method, "url": url, "body": json.loads(body) if body else None})
        return _Response(state["status"]), state["data"]

    transport._http.request = fake_request
    client = Client(transport)
    for module in (app_cmd, file, item, space, view):
        monkeypatch.setattr(module, "get_client", lambda: client)
    return calls, state


def _tty(monkeypatch, value):
    """Make the confirmation guard see an interactive (True) or piped (False) stdin.

    CliRunner swaps sys.stdin during invoke, so the guard's own ``sys`` is patched.
    """
    fake_sys = SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: value))
    monkeypatch.setattr("podio_cli.output.sys", fake_sys)


# --- app delete ---

def test_app_delete_with_yes_issues_delete(wire):
    calls, _ = wire
    result = runner.invoke(app_cmd.app, ["delete", "55", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == [{"method": "DELETE", "url": "https://api.podio.com/app/55", "body": None}]
    assert json.loads(result.stdout) == {"app_id": 55, "deleted": True}


def test_app_delete_refuses_without_yes_when_not_interactive(wire, monkeypatch):
    calls, _ = wire
    _tty(monkeypatch, False)
    result = runner.invoke(app_cmd.app, ["delete", "55"])
    assert result.exit_code == 1
    assert "Refusing to delete app 55" in result.stderr
    assert "--yes" in result.stderr
    assert calls == []


def test_app_delete_prompt_declined_does_not_delete(wire, monkeypatch):
    calls, _ = wire
    _tty(monkeypatch, True)
    result = runner.invoke(app_cmd.app, ["delete", "55"], input="n\n")
    assert result.exit_code == 1
    assert "Aborted" in result.stderr
    assert calls == []


def test_app_delete_prompt_accepted_deletes(wire, monkeypatch):
    calls, _ = wire
    _tty(monkeypatch, True)
    result = runner.invoke(app_cmd.app, ["delete", "55"], input="y\n")
    assert result.exit_code == 0
    assert [c["method"] for c in calls] == ["DELETE"]


def test_app_delete_api_error_is_not_reported_as_success(wire):
    calls, state = wire
    state.update(status=404, data=b'{"error":"not_found","error_description":"Object not found"}')
    result = runner.invoke(app_cmd.app, ["delete", "55", "-y"])
    assert result.exit_code != 0
    assert '"deleted": true' not in result.stdout


# --- view ---

def test_view_list_calls_documented_endpoint_and_applies_list_options(wire):
    calls, state = wire
    state["data"] = json.dumps([
        {"view_id": 1, "name": "Open", "items": 3},
        {"view_id": 2, "name": "Done", "items": 9},
    ]).encode()
    result = runner.invoke(view.app, ["list", "77", "--filter", "name:eq:Open", "--properties", "view_id,name"])
    assert result.exit_code == 0, result.output
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.podio.com/view/app/77/?include_standard_views=false"
    assert json.loads(result.stdout) == [{"view_id": 1, "name": "Open"}]


def test_view_list_include_standard_views_and_limit(wire):
    calls, state = wire
    state["data"] = json.dumps([{"view_id": 1, "name": "A"}, {"view_id": 2, "name": "B"}]).encode()
    result = runner.invoke(view.app, ["list", "77", "--include-standard-views", "--limit", "1"])
    assert result.exit_code == 0
    assert calls[0]["url"].endswith("include_standard_views=true")
    assert [v["view_id"] for v in json.loads(result.stdout)] == [1]


def test_view_get_calls_documented_endpoint(wire):
    calls, state = wire
    state["data"] = b'{"sort_by": "created_on", "sort_desc": true, "filters": []}'
    result = runner.invoke(view.app, ["get", "77", "last"])
    assert result.exit_code == 0, result.output
    assert calls == [{"method": "GET", "url": "https://api.podio.com/view/app/77/last", "body": None}]
    assert json.loads(result.stdout)["sort_by"] == "created_on"


def test_view_create_from_file(wire, tmp_path):
    calls, state = wire
    state["data"] = b'{"view_id": 99}'
    definition = {"name": "Open items", "private": False, "sort_by": "created_on", "sort_desc": True}
    path = tmp_path / "view.json"
    path.write_text(json.dumps(definition))
    result = runner.invoke(view.app, ["create", "77", "--json-file", str(path)])
    assert result.exit_code == 0, result.output
    assert calls == [{"method": "POST", "url": "https://api.podio.com/view/app/77/", "body": definition}]
    assert json.loads(result.stdout)["view_id"] == 99


def test_view_create_from_stdin(wire):
    calls, state = wire
    state["data"] = b'{"view_id": 99}'
    result = runner.invoke(view.app, ["create", "77"], input='{"name": "From stdin"}')
    assert result.exit_code == 0, result.output
    assert calls[0]["body"] == {"name": "From stdin"}


@pytest.mark.parametrize("payload", ["not json", "[1, 2]"])
def test_view_create_rejects_invalid_definition(wire, payload):
    calls, _ = wire
    result = runner.invoke(view.app, ["create", "77"], input=payload)
    assert result.exit_code == 1
    assert calls == []


def test_view_create_missing_file(wire, tmp_path):
    calls, _ = wire
    result = runner.invoke(view.app, ["create", "77", "--json-file", str(tmp_path / "nope.json")])
    assert result.exit_code == 1
    assert calls == []


def test_view_delete_with_yes(wire):
    calls, _ = wire
    result = runner.invoke(view.app, ["delete", "88", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == [{"method": "DELETE", "url": "https://api.podio.com/view/88", "body": None}]
    assert json.loads(result.stdout) == {"view_id": 88, "deleted": True}


def test_view_delete_refuses_without_yes_when_not_interactive(wire, monkeypatch):
    calls, _ = wire
    _tty(monkeypatch, False)
    result = runner.invoke(view.app, ["delete", "88"])
    assert result.exit_code == 1
    assert "Refusing to delete view 88" in result.stderr
    assert calls == []


# --- space member ---

def test_space_member_list_calls_v2_endpoint(wire):
    calls, state = wire
    state["data"] = json.dumps([
        {"profile": {"user_id": 1, "name": "A"}, "role": "admin", "employee": True, "grants": 0},
        {"profile": {"user_id": 2, "name": "B"}, "role": "light", "employee": False, "grants": 2},
    ]).encode()
    result = runner.invoke(space.app, ["member", "list", "123", "--filter", "role:eq:admin"])
    assert result.exit_code == 0, result.output
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.podio.com/space/123/member/v2/?limit=100&offset=0"
    assert [m["profile"]["user_id"] for m in json.loads(result.stdout)] == [1]


def test_space_member_list_passes_documented_query_params(wire):
    calls, state = wire
    state["data"] = b"[]"
    result = runner.invoke(
        space.app, ["member", "list", "123", "--limit", "5", "--offset", "10", "--member-type", "admin", "--query", "ada"]
    )
    assert result.exit_code == 0
    assert calls[0]["url"] == (
        "https://api.podio.com/space/123/member/v2/?limit=5&offset=10&member_type=admin&query=ada"
    )


def test_space_member_get_calls_v2_endpoint(wire):
    calls, state = wire
    state["data"] = b'{"profile": {"user_id": 5}, "role": "light", "employee": false, "grants": 1}'
    result = runner.invoke(space.app, ["member", "get", "123", "5"])
    assert result.exit_code == 0, result.output
    assert calls == [{"method": "GET", "url": "https://api.podio.com/space/123/member/5/v2", "body": None}]
    assert json.loads(result.stdout)["role"] == "light"


def test_space_member_add_posts_documented_body(wire):
    calls, _ = wire
    result = runner.invoke(
        space.app,
        ["member", "add", "123", "--email", "a@example.com", "--email", "b@example.com", "--role", "light", "--message", "Hi"],
    )
    assert result.exit_code == 0, result.output
    assert calls == [{
        "method": "POST",
        "url": "https://api.podio.com/space/123/member/",
        "body": {"role": "light", "mails": ["a@example.com", "b@example.com"], "message": "Hi"},
    }]


def test_space_member_add_omits_message_when_absent(wire):
    calls, _ = wire
    result = runner.invoke(space.app, ["member", "add", "123", "-e", "a@example.com", "--role", "admin"])
    assert result.exit_code == 0
    assert calls[0]["body"] == {"role": "admin", "mails": ["a@example.com"]}


def test_space_member_add_rejects_unknown_role_and_missing_email(wire):
    calls, _ = wire
    assert runner.invoke(space.app, ["member", "add", "123", "-e", "a@example.com", "--role", "owner"]).exit_code == 2
    assert runner.invoke(space.app, ["member", "add", "123", "--role", "admin"]).exit_code == 2
    assert calls == []


def test_space_member_add_api_error_exits_nonzero(wire):
    _, state = wire
    state.update(status=403, data=b'{"error":"forbidden","error_description":"User limit reached"}')
    result = runner.invoke(space.app, ["member", "add", "123", "-e", "a@example.com", "--role", "admin"])
    assert result.exit_code != 0
    assert "Added" not in result.stderr


# --- file replace ---

def test_file_replace_new_file_in_path_old_file_in_body(wire):
    calls, _ = wire
    result = runner.invoke(file.app, ["replace", "222", "111"])
    assert result.exit_code == 0, result.output
    assert calls == [{
        "method": "POST",
        "url": "https://api.podio.com/file/222/replace",
        "body": {"old_file_id": 111},
    }]
    assert json.loads(result.stdout)["replaced"] is True


def test_file_replace_api_error_exits_nonzero(wire):
    _, state = wire
    state.update(status=400, data=b'{"error":"bad","error_description":"Only attachments can be replaced"}')
    result = runner.invoke(file.app, ["replace", "222", "111"])
    assert result.exit_code != 0
    assert '"replaced": true' not in result.stdout


# --- item share ---

def test_item_share_posts_grant_with_mail_contact_identifiers(wire):
    calls, state = wire
    state["data"] = b'{"invitable": [{"profile_id": 5}]}'
    result = runner.invoke(
        item.app,
        ["share", "900", "--email", "a@example.com", "--email", "b@example.com", "--access", "edit", "--message", "Look"],
    )
    assert result.exit_code == 0, result.output
    assert calls == [{
        "method": "POST",
        "url": "https://api.podio.com/grant/item/900",
        "body": {
            "people": [{"type": "mail", "id": "a@example.com"}, {"type": "mail", "id": "b@example.com"}],
            "access_level": "edit",
            "message": "Look",
        },
    }]
    assert json.loads(result.stdout)["response"] == {"invitable": [{"profile_id": 5}]}


def test_item_share_omits_message_when_absent(wire):
    calls, _ = wire
    result = runner.invoke(item.app, ["share", "900", "-e", "a@example.com", "--access", "view"])
    assert result.exit_code == 0
    assert calls[0]["body"] == {"people": [{"type": "mail", "id": "a@example.com"}], "access_level": "view"}


def test_item_share_rejects_unknown_access_and_missing_email(wire):
    calls, _ = wire
    assert runner.invoke(item.app, ["share", "900", "-e", "a@example.com", "--access", "comment"]).exit_code == 2
    assert runner.invoke(item.app, ["share", "900", "--access", "view"]).exit_code == 2
    assert calls == []


def test_item_share_api_error_exits_nonzero(wire):
    _, state = wire
    state.update(status=403, data=b'{"error":"forbidden","error_description":"nope"}')
    result = runner.invoke(item.app, ["share", "900", "-e", "a@example.com", "--access", "view"])
    assert result.exit_code != 0
    assert "shared with" not in result.stderr


TRUST_LEVEL_403 = (
    b'{"error":"forbidden","error_description":"Only available for clients with a trust level of 2 '
    b'or higher. To get your API client upgraded to a higher trust level contact support at '
    b'https://support.sharefile.com."}'
)


@pytest.mark.parametrize(
    "module, args",
    [
        (item, ["share", "900", "-e", "a@example.com", "--access", "view"]),
        (app_cmd, ["delete", "55", "--yes"]),
        (space, ["member", "add", "77", "-e", "a@example.com", "--role", "light"]),
    ],
    ids=["item-share", "app-delete", "space-member-add"],
)
def test_trust_level_403_reports_web_app_requirement(wire, module, args):
    _, state = wire
    state.update(status=403, data=TRUST_LEVEL_403)
    result = runner.invoke(module.app, args)
    assert result.exit_code == 1
    assert "trust level" in result.stderr
    assert "Podio web app" in result.stderr
    assert "Permission denied" not in result.stderr
    assert result.stdout == ""
