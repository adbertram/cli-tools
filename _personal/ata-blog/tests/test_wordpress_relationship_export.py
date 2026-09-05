from __future__ import annotations

import json
import math
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
        payload: Any,
        total: int,
        total_pages: int,
        status_code: int = 200,
    ) -> None:
        self.url = url
        self.text = ""
        self.status_code = status_code
        self._payload = payload
        self.headers = {
            "X-WP-Total": str(total),
            "X-WP-TotalPages": str(total_pages),
        }

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


def _post(
    post_id: int,
    *,
    slug: str | None = None,
    author: int = 1,
    categories: list[int] | None = None,
    tags: list[int] | None = None,
    status: str = "publish",
) -> dict[str, Any]:
    return {
        "id": post_id,
        "slug": slug or f"post-{post_id}",
        "author": author,
        "categories": [1] if categories is None else categories,
        "tags": [9] if tags is None else tags,
        "status": status,
        "modified": "2026-08-30T12:34:56",
    }


def _author(author_id: int, slug: str) -> dict[str, Any]:
    return {
        "id": author_id,
        "slug": slug,
        "name": "Adam Bertram" if author_id == 1 else "Jane Operator",
        "description": "Author biography",
        "url": f"https://example.test/{slug}",
        "link": f"https://example.test/author/{slug}/",
        "avatar_urls": {
            "24": f"https://example.test/{slug}-24.jpg",
            "48": f"https://example.test/{slug}-48.jpg",
            "96": f"https://example.test/{slug}-96.jpg",
        },
    }


def _term(term_id: int, slug: str) -> dict[str, Any]:
    return {
        "id": term_id,
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "description": "",
    }


def _paged_response(
    *,
    url: str,
    items: list[dict[str, Any]],
    page: int,
    page_size: int,
) -> FakeResponse:
    total = len(items)
    total_pages = math.ceil(total / page_size)
    start = (page - 1) * page_size
    return FakeResponse(
        url=url,
        payload=items[start : start + page_size],
        total=total,
        total_pages=total_pages,
    )


def _fixture_data(post_count: int = 1_330) -> dict[str, list[dict[str, Any]]]:
    posts = [
        _post(
            post_id,
            author=7 if post_id == post_count else 1,
            categories=[2, 1, 2] if post_id == 1 else [1],
            tags=[] if post_id <= 11 else ([9, 9] if post_id == 12 else [9]),
        )
        for post_id in range(1, post_count + 1)
    ]
    return {
        "posts": posts,
        "users": [_author(1, "adam-bertram"), _author(7, "jane-operator")],
        "categories": [_term(1, "automation"), _term(2, "powershell"), _term(99, "unused")],
        "tags": [_term(9, "how-to"), _term(88, "unused-tag")],
    }


def _route_for(data: dict[str, list[dict[str, Any]]]) -> Callable[[str, dict[str, Any]], FakeResponse]:
    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        params = kwargs["params"]
        page = int(params["page"])
        page_size = int(params["per_page"])
        resource = url.rstrip("/").rsplit("/", 1)[-1]
        items = data[resource]
        if resource == "users":
            include = {int(value) for value in params["include"].split(",")}
            items = [item for item in items if item["id"] in include]
        return _paged_response(
            url=url,
            items=items,
            page=page,
            page_size=page_size,
        )

    return route


def test_relationship_export_paginates_1330_posts_and_preserves_relationships(monkeypatch):
    monkeypatch.setattr(wordpress_admin, "WP_REST_PAGE_SIZE", 100)
    data = _fixture_data()
    session = FakeSession(_route_for(data))

    payload = wordpress_admin._build_relationship_export(session=session)

    assert payload["schema_version"] == 1
    assert payload["producer"] == {
        "tool": "ata-blog",
        "command": "ata-blog wordpress-admin relationships export",
        "source": "WordPress REST API",
        "api_namespace": "wp/v2",
        "resources": {
            "posts": {
                "resource": "posts",
                "endpoint": "/wp-json/wp/v2/posts",
                "page_size": 100,
                "page_count": 14,
                "reported_count": 1330,
                "exported_count": 1330,
                "stability_check": "page_1_replay",
            },
            "authors": {
                "resource": "users",
                "endpoint": "/wp-json/wp/v2/users",
                "page_size": 100,
                "page_count": 1,
                "reported_count": 2,
                "exported_count": 2,
                "stability_check": "page_1_replay",
            },
            "categories": {
                "resource": "categories",
                "endpoint": "/wp-json/wp/v2/categories",
                "page_size": 100,
                "page_count": 1,
                "reported_count": 3,
                "exported_count": 3,
                "stability_check": "page_1_replay",
            },
            "tags": {
                "resource": "tags",
                "endpoint": "/wp-json/wp/v2/tags",
                "page_size": 100,
                "page_count": 1,
                "reported_count": 2,
                "exported_count": 2,
                "stability_check": "page_1_replay",
            },
        },
    }
    assert payload["counts"] == {
        "posts": 1330,
        "authors": 2,
        "categories": 3,
        "tags": 2,
        "posts_without_tags": 11,
        "referenced_author_ids": 2,
        "referenced_category_ids": 2,
        "referenced_tag_ids": 1,
    }
    assert payload["posts"][0] == {
        "wp_id": 1,
        "slug": "post-1",
        "author_id": 1,
        "category_ids": [2, 1],
        "tag_ids": [],
        "status": "publish",
        "modified": "2026-08-30T12:34:56",
    }
    assert payload["posts"][11]["tag_ids"] == [9]
    assert payload["posts"][-1]["author_id"] == 7
    assert payload["authors"][-1]["slug"] == "jane-operator"
    assert payload["categories"][-1]["category_id"] == 99
    assert payload["tags"][-1]["tag_id"] == 88
    assert {method for method, _url, _kwargs in session.calls} == {"GET"}
    post_pages = [
        kwargs["params"]["page"]
        for _method, url, kwargs in session.calls
        if url.endswith("/posts")
    ]
    assert post_pages == [*range(1, 15), 1]


@pytest.mark.parametrize(
    ("resource", "mutation", "message"),
    [
        ("posts", lambda rows: rows.__setitem__(1, {**rows[1], "id": rows[0]["id"]}), "duplicate wp_id"),
        ("posts", lambda rows: rows.__setitem__(1, {**rows[1], "slug": rows[0]["slug"]}), "duplicate slug"),
        ("users", lambda rows: rows.append({**rows[0]}), "duplicate author_id"),
        ("categories", lambda rows: rows.append({**rows[0]}), "duplicate category_id"),
        ("tags", lambda rows: rows.append({**rows[0]}), "duplicate tag_id"),
    ],
)
def test_relationship_export_rejects_duplicate_ids_and_slugs(resource, mutation, message):
    data = _fixture_data(post_count=2)
    mutation(data[resource])

    with pytest.raises(RuntimeError, match=message):
        wordpress_admin._build_relationship_export(session=FakeSession(_route_for(data)))


@pytest.mark.parametrize(
    ("resource", "missing_id", "message"),
    [
        ("users", 7, "missing referenced author IDs: 7"),
        ("categories", 1, "missing referenced category IDs: 1"),
        ("tags", 9, "missing referenced tag IDs: 9"),
    ],
)
def test_relationship_export_rejects_missing_referenced_entities(resource, missing_id, message):
    data = _fixture_data(post_count=2)
    if resource == "tags":
        data["posts"][0]["tags"] = [9]
    data[resource] = [item for item in data[resource] if item["id"] != missing_id]

    with pytest.raises(RuntimeError, match=message):
        wordpress_admin._build_relationship_export(session=FakeSession(_route_for(data)))


def test_relationship_export_rejects_partial_middle_page(monkeypatch):
    monkeypatch.setattr(wordpress_admin, "WP_REST_PAGE_SIZE", 100)
    data = _fixture_data(post_count=201)
    normal_route = _route_for(data)

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        response = normal_route(url, kwargs)
        if url.endswith("/posts") and kwargs["params"]["page"] == 2:
            response._payload = response._payload[:-1]
        return response

    with pytest.raises(RuntimeError, match="partial pagination.*posts page 2"):
        wordpress_admin._build_relationship_export(session=FakeSession(route))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda post: post.pop("modified"), "shape drift.*posts"),
        (lambda post: post.__setitem__("status", "draft"), "non-published post"),
        (lambda post: post.__setitem__("categories", [True]), "categories.*positive integer"),
    ],
)
def test_relationship_export_rejects_post_shape_and_status_drift(mutation, message):
    data = _fixture_data(post_count=1)
    mutation(data["posts"][0])

    with pytest.raises(RuntimeError, match=message):
        wordpress_admin._build_relationship_export(session=FakeSession(_route_for(data)))


def test_relationship_export_rejects_page_count_drift():
    data = _fixture_data(post_count=2)
    normal_route = _route_for(data)

    def route(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        response = normal_route(url, kwargs)
        if url.endswith("/posts"):
            response.headers["X-WP-TotalPages"] = "2"
        return response

    with pytest.raises(RuntimeError, match="pagination metadata mismatch.*posts"):
        wordpress_admin._build_relationship_export(session=FakeSession(route))


def test_relationship_export_command_emits_one_json_object_with_clean_stderr(monkeypatch):
    payload = {
        "schema_version": 1,
        "producer": {"tool": "ata-blog"},
        "counts": {"posts": 0},
        "posts": [],
        "authors": [],
        "categories": [],
        "tags": [],
    }
    monkeypatch.setattr(wordpress_admin, "_build_relationship_export", lambda: payload)

    result = CliRunner().invoke(wordpress_admin.app, ["relationships", "export"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == payload
    assert result.stdout.count("{") >= 1
    assert result.stderr == ""


def test_relationship_export_command_reports_failure_only_on_stderr(monkeypatch):
    def fail() -> dict[str, Any]:
        raise RuntimeError("relationship export failed")

    monkeypatch.setattr(wordpress_admin, "_build_relationship_export", fail)

    result = CliRunner().invoke(wordpress_admin.app, ["relationships", "export"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "relationship export failed" in result.stderr
