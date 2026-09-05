from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import requests
from typer.testing import CliRunner

from ata_blog_cli.commands import wordpress_admin


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        text: str = "",
        payload: Any = None,
        status_code: int = 200,
    ) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, route: Callable[[str, dict[str, Any]], FakeResponse]) -> None:
        self.route = route
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self.route(url, kwargs)


def _redirection_item(
    rule_id: int,
    *,
    enabled: bool = True,
    status: int = 301,
    source: str | None = None,
    target: str | None = None,
    query_mode: str = "exact",
    ignore_case: bool = True,
    regex: bool = False,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "enabled": enabled,
        "match_type": "url",
        "regex": regex,
        "action_code": status,
        "url": source or f"/old-{rule_id}/",
        "action_data": {"url": target or f"/new-{rule_id}/"},
        "match_data": {
            "source": {
                "flag_query": query_mode,
                "flag_case": ignore_case,
                "flag_regex": regex,
                "flag_trailing": True,
            }
        },
    }


def _permalink_debug_html(*, status: int = 301, copy_query: int = 1) -> str:
    return f"""
    <html><body>
      <textarea name="debug-data[settings]">Array
      (
        [screen-options] => Array
        (
          [per_page] => 2
        )
        [general] => Array
        (
          [redirect] => {status}
          [copy_query_redirect] => {copy_query}
          [extra_redirects] => 1
        )
      )</textarea>
      <textarea name="debug-data[uris]">Array ( [1] => custom-one )</textarea>
      <textarea name="debug-data[custom-redirects]"></textarea>
    </body></html>
    """


def _permalink_editor_html(total: int, rows: list[tuple[str, str, str]]) -> str:
    rendered_rows = "".join(
        f"""
        <tr>
          <td>
            <input type="text" class="widefat custom_uri" name="uri[{rule_id}]"
              data-element-id="{rule_id}" value="{source}" />
            <a class="small post_permalink" href="{target}">view</a>
          </td>
        </tr>
        """
        for rule_id, source, target in rows
    )
    return (
        "<html><body><span class=\"displaying-num\">"
        f"{total:,} items</span><table>{rendered_rows}</table></body></html>"
    )


def _complete_route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
    if "tools.php?page=redirection.php" in url:
        return FakeResponse(
            url=url,
            text='<script>var wpApiSettings = {"nonce":"nonce-123"};</script>',
        )
    if "/wp-json/redirection/v1/redirect" in url:
        page = kwargs["params"]["page"]
        pages = {
            0: [
                _redirection_item(
                    1,
                    enabled=False,
                    status=302,
                    query_mode="ignore",
                    ignore_case=False,
                    regex=True,
                ),
                _redirection_item(2),
            ],
            1: [_redirection_item(3, query_mode="pass")],
        }
        return FakeResponse(url=url, payload={"items": pages[page], "total": 3})
    if "section=debug" in url:
        return FakeResponse(url=url, text=_permalink_debug_html())
    if "page=permalink-manager" in url:
        page = int(kwargs["params"]["paged"])
        pages = {
            1: [
                ("1", "custom-one", "https://example.test/custom-one/"),
                ("2", "custom-two", "https://example.test/custom-two/"),
            ],
            2: [("3", "custom-three", "https://example.test/custom-three/")],
        }
        return FakeResponse(url=url, text=_permalink_editor_html(3, pages[page]))
    raise AssertionError(f"Unexpected GET {url} {kwargs}")


def test_redirect_export_paginates_both_plugins_and_preserves_metadata(monkeypatch):
    monkeypatch.setattr(wordpress_admin, "REDIRECTION_PAGE_SIZE", 2)
    session = FakeSession(_complete_route)

    payload = wordpress_admin._build_redirect_export(session=session)

    assert payload["counts"] == {
        "redirection": {"reported": 3, "exported": 3},
        "permalink_manager": {"reported": 3, "exported": 3},
        "total": 6,
    }
    assert payload["records"][0] == {
        "source_plugin": "redirection",
        "rule_id": "1",
        "enabled": False,
        "match_mode": "regex",
        "match_type": "url",
        "http_status": 302,
        "source": "/old-1/",
        "target": "/new-1/",
        "query_mode": "ignore",
        "case_sensitive": True,
    }
    assert payload["records"][2]["query_mode"] == "pass"
    assert payload["records"][3] == {
        "source_plugin": "permalink-manager",
        "rule_id": "1",
        "enabled": True,
        "match_mode": "permalink_override",
        "match_type": "url",
        "http_status": 301,
        "source": "custom-one",
        "target": "https://example.test/custom-one/",
        "query_mode": "pass",
        "case_sensitive": False,
    }
    assert {method for method, _url, _kwargs in session.calls} == {"GET"}
    assert [kwargs["params"]["page"] for _method, url, kwargs in session.calls if "/redirection/v1/redirect" in url] == [0, 1, 0]
    assert [kwargs["params"]["paged"] for _method, url, kwargs in session.calls if "section=uri_editor" in url] == [1, 2, 1]


@pytest.mark.parametrize("plugin", ["redirection", "permalink-manager"])
def test_redirect_export_rejects_duplicate_rule_ids(monkeypatch, plugin):
    monkeypatch.setattr(wordpress_admin, "REDIRECTION_PAGE_SIZE", 2)

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        response = _complete_route(url, kwargs)
        if plugin == "redirection" and "/redirection/v1/redirect" in url and kwargs["params"]["page"] == 1:
            return FakeResponse(url=url, payload={"items": [_redirection_item(2)], "total": 3})
        if plugin == "permalink-manager" and "section=uri_editor" in url and kwargs["params"]["paged"] == 2:
            return FakeResponse(
                url=url,
                text=_permalink_editor_html(
                    3, [("2", "duplicate", "https://example.test/duplicate/")]
                ),
            )
        return response

    with pytest.raises(RuntimeError, match="duplicate rule ID"):
        wordpress_admin._build_redirect_export(session=FakeSession(route))


@pytest.mark.parametrize("plugin", ["redirection", "permalink-manager"])
def test_redirect_export_rejects_malformed_records(monkeypatch, plugin):
    monkeypatch.setattr(wordpress_admin, "REDIRECTION_PAGE_SIZE", 2)

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        response = _complete_route(url, kwargs)
        if plugin == "redirection" and "/redirection/v1/redirect" in url and kwargs["params"]["page"] == 0:
            malformed = _redirection_item(1)
            malformed.pop("match_data")
            return FakeResponse(url=url, payload={"items": [malformed], "total": 1})
        if plugin == "permalink-manager" and "section=uri_editor" in url and kwargs["params"]["paged"] == 1:
            return FakeResponse(
                url=url,
                text='<html><span class="displaying-num">1 item</span><input class="custom_uri" data-element-id="1" value="orphan" /></html>',
            )
        return response

    with pytest.raises(RuntimeError, match="malformed"):
        wordpress_admin._build_redirect_export(session=FakeSession(route))


def test_redirect_export_propagates_api_failure(monkeypatch):
    monkeypatch.setattr(wordpress_admin, "REDIRECTION_PAGE_SIZE", 2)

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        if "/wp-json/redirection/v1/redirect" in url:
            return FakeResponse(url=url, status_code=401)
        return _complete_route(url, kwargs)

    with pytest.raises(requests.HTTPError, match="401"):
        wordpress_admin._build_redirect_export(session=FakeSession(route))


@pytest.mark.parametrize("plugin", ["redirection", "permalink-manager"])
def test_redirect_export_rejects_count_mismatch(monkeypatch, plugin):
    monkeypatch.setattr(wordpress_admin, "REDIRECTION_PAGE_SIZE", 2)

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        response = _complete_route(url, kwargs)
        if plugin == "redirection" and "/redirection/v1/redirect" in url and kwargs["params"]["page"] == 1:
            return FakeResponse(url=url, payload={"items": [], "total": 3})
        if plugin == "permalink-manager" and "section=uri_editor" in url and kwargs["params"]["paged"] == 2:
            return FakeResponse(url=url, text=_permalink_editor_html(3, []))
        return response

    with pytest.raises(RuntimeError, match="count mismatch"):
        wordpress_admin._build_redirect_export(session=FakeSession(route))


@pytest.mark.parametrize("plugin", ["redirection", "permalink-manager"])
def test_redirect_export_fails_if_plugin_disappears_mid_export(monkeypatch, plugin):
    monkeypatch.setattr(wordpress_admin, "REDIRECTION_PAGE_SIZE", 2)
    seen_page_zero = 0
    seen_debug = 0

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        nonlocal seen_page_zero, seen_debug
        if "/wp-json/redirection/v1/redirect" in url and kwargs["params"]["page"] == 0:
            seen_page_zero += 1
            if plugin == "redirection" and seen_page_zero == 2:
                return FakeResponse(url=url, status_code=404)
        if "section=debug" in url:
            seen_debug += 1
            if plugin == "permalink-manager" and seen_debug == 2:
                return FakeResponse(url=url, text="<html>plugin unavailable</html>")
        return _complete_route(url, kwargs)

    expected = "Redirection" if plugin == "redirection" else "Permalink Manager"
    with pytest.raises((RuntimeError, requests.HTTPError), match=expected):
        wordpress_admin._build_redirect_export(session=FakeSession(route))


def test_redirect_export_command_emits_json_only(monkeypatch):
    payload = {
        "schema_version": 1,
        "counts": {
            "redirection": {"reported": 0, "exported": 0},
            "permalink_manager": {"reported": 0, "exported": 0},
            "total": 0,
        },
        "records": [],
    }
    monkeypatch.setattr(wordpress_admin, "_build_redirect_export", lambda: payload)

    result = CliRunner().invoke(wordpress_admin.app, ["redirects", "export"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == payload
    assert result.stderr == ""


def test_redirect_export_command_reports_auth_failure_on_stderr(monkeypatch):
    def fail() -> dict[str, Any]:
        raise RuntimeError("authentication failed")

    monkeypatch.setattr(wordpress_admin, "_build_redirect_export", fail)

    result = CliRunner().invoke(wordpress_admin.app, ["redirects", "export"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "authentication failed" in result.stderr
