"""Nextdoor client regressions.

These tests cover the deterministic client logic (record normalization,
GraphQL routing/payloads, auth-wall detection, and error handling) without a
live Nextdoor session. Cookie loading is mocked so the persistent-profile
browser is never launched.
"""

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import requests

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserCookie,
    RequestsRetryPolicy,
)

from nextdoor_cli import client as client_module
from nextdoor_cli import main as main_module
from nextdoor_cli.client import (
    CLASSIFIED_SORT_MAP,
    FEED_SORT_MAP,
    NextdoorClient,
    normalize_classified_item,
    normalize_feed_item,
    normalize_notification,
    normalize_search_result,
    _is_login_wall,
)
from nextdoor_cli.main import _resolve_sort, app


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Load a captured GraphQL ``data`` object fixture."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ---- Pure normalizers (real captured shapes) --------------------------------


FEED_RECORD_KEYS = {
    "id",
    "type",
    "post_type",
    "title",
    "price",
    "author",
    "created_at",
    "url",
    "body",
}


def test_normalize_feed_item_post_uses_subject_title():
    raw = {
        "feedItemType": "POST",
        "contentId": 489406804,
        "post": {
            "id": "post_489406804",
            "postType": "USER",
            "subject": "(HAHAHAHAHAHAH)",
            "body": "the body",
            "author": {"displayName": "Adam B."},
            "createdAt": {"epochMillis": "1782249537865"},
            "detailLink": {"href": "/p/m_wcBjjgGRwy?view=detail"},
        },
    }
    assert normalize_feed_item(raw) == {
        "id": 489406804,
        "type": "POST",
        "post_type": "USER",
        "title": "(HAHAHAHAHAHAH)",
        "price": None,
        "author": "Adam B.",
        "created_at": "2026-06-23T21:18:57.865000+00:00",
        "url": "https://nextdoor.com/p/m_wcBjjgGRwy?view=detail",
        "body": "the body",
    }


def test_normalize_feed_item_permalink_slug_is_not_derived_from_content_id():
    # The permalink slug is opaque and only exists in the payload — it is NOT
    # the numeric contentId. Guards against anyone "reconstructing" the URL.
    raw = {
        "feedItemType": "POST",
        "contentId": 497961402,
        "post": {"detailLink": {"href": "/p/Wg398DknXZ_z?view=detail"}},
    }
    record = normalize_feed_item(raw)
    assert record["url"] == "https://nextdoor.com/p/Wg398DknXZ_z?view=detail"
    assert "497961402" not in record["url"]


def test_normalize_feed_item_classified_post_uses_classified_content():
    # A For Sale & Free listing that surfaces in the general feed keeps its
    # title/body/price on post.classified; post.subject/body are empty strings.
    raw = {
        "feedItemType": "POST",
        "contentId": 497000001,
        "post": {
            "postType": "USER",
            "subject": "",
            "body": "",
            "detailLink": {"href": "/p/SrCkgS_fR53Q?view=detail"},
            "classified": {
                "title": "Pokemon Card Tins Collection",
                "price": "150",
                "currency": "USD",
                "description": "Pokemon TCG Bundle",
            },
        },
    }
    record = normalize_feed_item(raw)
    assert record["title"] == "Pokemon Card Tins Collection"
    assert record["price"] == "150"
    assert record["body"] == "Pokemon TCG Bundle"
    assert record["url"] == "https://nextdoor.com/p/SrCkgS_fR53Q?view=detail"


def test_normalize_feed_item_promo_uses_sponsor_name():
    raw = {
        "feedItemType": "PROMO",
        "contentId": 6658602269397747960,
        "promo": {
            "promoType": "NAMPLUS_AD",
            "creative": {"sponsorName": {"text": "Homeaglow"}},
        },
    }
    record = normalize_feed_item(raw)
    assert record["id"] == 6658602269397747960
    assert record["type"] == "PROMO"
    assert record["title"] == "Homeaglow"
    # A PROMO ad slot has no permalink, author, body or timestamp — truthfully
    # None rather than a synthesized value.
    assert record["url"] is None
    assert record["author"] is None
    assert record["body"] is None
    assert record["created_at"] is None


def test_normalize_feed_item_unknown_type_has_no_content_fields():
    raw = {"feedItemType": "MYSTERY", "contentId": 1, "post": {"subject": "ignored"}}
    record = normalize_feed_item(raw)
    assert set(record) == FEED_RECORD_KEYS
    assert record["id"] == 1
    assert record["type"] == "MYSTERY"
    assert all(record[key] is None for key in FEED_RECORD_KEYS - {"id", "type"})


def test_normalize_feed_item_rejects_wrong_typed_nested_object():
    raw = {"feedItemType": "POST", "contentId": 1, "post": {"classified": "nope"}}
    with pytest.raises(ClientError) as exc:
        normalize_feed_item(raw)
    assert "classified" in str(exc.value)


# ---- Classified grid records (real captured StyledText shapes) --------------


def _grid_node(title_text, styles, **item_overrides):
    item = {
        "__typename": "SearchResultGridItem",
        "contentId": "e0a5a7da",
        "title": {"text": title_text, "styles": styles},
        "subtitle": {"text": "9 hr ago · 8.7 mi · Evansville"},
        "image": {"image": {"url": "https://us1-photo.nextdoor.com/x.jpeg"}},
        "url": "https://nextdoor.com/for_sale_and_free/e0a5a7da/?init_source=search",
    }
    item.update(item_overrides)
    return {"itemType": "ORGANIC", "item": item}


def _run(start, length, strikethrough=False):
    return {"start": start, "length": length, "attributes": {"isStrikethrough": strikethrough}}


def test_normalize_classified_item_splits_price_from_title():
    record = normalize_classified_item(
        _grid_node("$150\nPokemon Card Tins Collection", [_run(0, 4), _run(4, 1), _run(5, 28)])
    )
    assert record == {
        "id": "e0a5a7da",
        "type": "ORGANIC",
        "title": "Pokemon Card Tins Collection",
        "price": "$150",
        "original_price": None,
        "variant": None,
        "subtitle": "9 hr ago · 8.7 mi · Evansville",
        "image_url": "https://us1-photo.nextdoor.com/x.jpeg",
        "url": "https://nextdoor.com/for_sale_and_free/e0a5a7da/?init_source=search",
    }


def test_normalize_classified_item_unpriced_listing_is_single_line():
    record = normalize_classified_item(_grid_node("Garage sale", [_run(0, 11)]))
    assert record["title"] == "Garage sale"
    assert record["price"] is None
    assert record["original_price"] is None


def test_normalize_classified_item_free_listing_keeps_free_marker():
    record = normalize_classified_item(
        _grid_node("FREE\nMowing", [_run(0, 4), _run(4, 1), _run(5, 6)])
    )
    assert record["title"] == "Mowing"
    assert record["price"] == "FREE"


def test_normalize_classified_item_discount_uses_strikethrough_run():
    # "$175 $250" — the struck-through run is the ORIGINAL price; the rest is
    # the current price. The style runs decide, not currency string guessing.
    record = normalize_classified_item(
        _grid_node(
            "$175 $250\nWoods RM59 finishing mower",
            [_run(0, 4), _run(4, 1), _run(5, 4, strikethrough=True), _run(9, 1), _run(10, 26)],
        )
    )
    assert record["title"] == "Woods RM59 finishing mower"
    assert record["price"] == "$175"
    assert record["original_price"] == "$250"


def test_normalize_classified_item_sponsored_slot_has_no_listing_fields():
    raw = {
        "itemType": "CLASSIFIEDS_GAM_ITEM",
        "item": {"__typename": "ClassifiedSponsoredPost", "targetingInfo": {}},
    }
    record = normalize_classified_item(raw)
    assert record["type"] == "CLASSIFIEDS_GAM_ITEM"
    assert record["id"] is None
    assert record["title"] is None
    assert record["url"] is None


def test_normalize_classified_item_variant_line_becomes_variant_field():
    # Real captured shape that used to crash the whole classifieds query:
    # a price line, a title line, and a "Color: ..." variant line.
    record = normalize_classified_item(
        _grid_node(
            "$260\nNew YETI Tundra 45 Hard Cooler\nColor: Rescue Red/Navy/White",
            [_run(0, 4)],
        )
    )
    assert record["title"] == "New YETI Tundra 45 Hard Cooler"
    assert record["price"] == "$260"
    assert record["original_price"] is None
    assert record["variant"] == "Color: Rescue Red/Navy/White"


def test_normalize_classified_item_two_line_title_has_no_variant():
    record = normalize_classified_item(
        _grid_node("$150\nPokemon Card Tins Collection", [_run(0, 4)])
    )
    assert record["variant"] is None


def test_normalize_classified_item_extra_variant_lines_are_newline_joined():
    record = normalize_classified_item(_grid_node("$5\nWidget\nColor: Red\nSize: L", [_run(0, 2)]))
    assert record["title"] == "Widget"
    assert record["variant"] == "Color: Red\nSize: L"


def test_normalize_search_result_non_grid_title_is_verbatim():
    # SearchResult nodes (neighbors/businesses/events/posts) carry a plain
    # title. No price split is attempted on them, so a newline in a post title
    # can never be mistaken for a price line.
    raw = {
        "__typename": "SearchResult",
        "contentId": "2118747",
        "contentType": "localEvent",
        "title": {"text": "Bierstube Bootcamp"},
        "subtitle": {"text": "Saturday, Jul 25 • 8:00 PM\nGermania Maennerchor"},
        "url": "https://nextdoor.com/local_events/CDGKh7Xxdd3M/?is=search",
    }
    assert normalize_search_result("LOCAL_EVENT", raw) == {
        "id": "2118747",
        "section": "LOCAL_EVENT",
        "type": "localEvent",
        "title": "Bierstube Bootcamp",
        "price": None,
        "subtitle": "Saturday, Jul 25 • 8:00 PM\nGermania Maennerchor",
        "url": "https://nextdoor.com/local_events/CDGKh7Xxdd3M/?is=search",
    }


def test_normalize_search_result_classified_grid_node_is_unwrapped_and_priced():
    node = _grid_node("$20\nPink Squishy Toy with Case", [_run(0, 3), _run(3, 1), _run(4, 25)])
    node["__typename"] = "SearchResultItem"
    node["item"]["contentType"] = "classified"
    record = normalize_search_result("CLASSIFIED", node)
    assert record["section"] == "CLASSIFIED"
    assert record["type"] == "classified"
    assert record["title"] == "Pink Squishy Toy with Case"
    assert record["price"] == "$20"


def test_normalize_notification_uses_type_title_badges():
    raw = {"type": "saved_bookmarks", "title": "Bookmarks", "badges": None, "__typename": "Shortcut"}
    assert normalize_notification(raw) == {
        "id": "saved_bookmarks",
        "label": "Bookmarks",
        "badges": None,
    }


# ---- Fixture-driven operation tests (real captured responses) ---------------


def test_get_feed_against_real_fixture(monkeypatch):
    data = _load_fixture("PersonalizedFeed")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.get_feed(limit=50)

    # 6 POST + 2 PROMO items in the captured feed.
    assert len(rows) == 8
    assert {r["type"] for r in rows} == {"POST", "PROMO"}
    assert all(set(r.keys()) == FEED_RECORD_KEYS for r in rows)
    assert all(r["id"] is not None for r in rows)
    posts = [r for r in rows if r["type"] == "POST"]
    promos = [r for r in rows if r["type"] == "PROMO"]
    assert len(posts) == 6 and len(promos) == 2
    # Every real post exposes a working opaque-slug permalink, a timestamp and
    # an author — the fields the feed used to drop entirely.
    assert all(r["url"].startswith("https://nextdoor.com/p/") for r in posts)
    assert all(r["created_at"].startswith("2026-") for r in posts)
    assert all(r["author"] for r in posts)
    # The slug is never the numeric contentId.
    assert all(r["id"] not in r["url"] for r in posts)
    # Classified listings leaking into the general feed expose title + price.
    listings = [r for r in posts if r["price"] is not None]
    assert {"Pokemon Card Tins Collection"} <= {r["title"] for r in listings}
    assert "150" in {r["price"] for r in listings}
    # A news post carries the NEWS_ARTICLE subtype.
    assert "NEWS_ARTICLE" in {r["post_type"] for r in posts}
    # PROMO ad slots have a sponsor name but no permalink.
    assert all(r["title"] for r in promos)
    assert all(r["url"] is None for r in promos)


def test_list_classifieds_against_real_fixture(monkeypatch):
    data = _load_fixture("searchClassifiedV2")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.list_classifieds(limit=20)

    # The captured For Sale & Free page returns 20 grid nodes: 17 real
    # listings plus 3 sponsored slots.
    assert len(rows) == 20
    organic = [r for r in rows if r["type"] == "ORGANIC"]
    assert len(organic) == 17
    # Every real listing has a direct listing URL — the whole point of this command.
    assert all(
        r["url"].startswith("https://nextdoor.com/for_sale_and_free/") for r in organic
    )
    assert all(r["id"] and r["id"] in r["url"] for r in organic)
    assert all(r["title"] for r in organic)
    titles = {r["title"] for r in organic}
    assert "Pokemon Card Tins Collection" in titles
    prices = {r["title"]: r["price"] for r in organic}
    assert prices["Pokemon Card Tins Collection"] == "$150"
    # An unpriced listing reports None, not an invented price.
    assert prices["Garage sale"] is None
    assert prices["Mowing"] == "FREE"
    # A discounted listing splits current vs struck-through original price.
    discounted = [r for r in organic if r["original_price"]]
    assert {"Woods RM59 finishing mower", "KitchenAid Microwave"} == {
        r["title"] for r in discounted
    }
    assert {"$175", "$75"} == {r["price"] for r in discounted}
    assert {"$250", "$150"} == {r["original_price"] for r in discounted}
    # Sponsored slots are reported truthfully with no listing identity.
    sponsored = [r for r in rows if r["type"] != "ORGANIC"]
    assert len(sponsored) == 3
    assert all(r["id"] is None and r["url"] is None for r in sponsored)


def test_get_classified_against_real_fixture(monkeypatch):
    data = _load_fixture("ClassifiedFeedItem")
    client = _make_client(monkeypatch)
    captured = {}

    def fake_graphql(operation, variables=None):
        captured["operation"] = operation
        captured["variables"] = variables
        return data

    monkeypatch.setattr(client, "_graphql", fake_graphql)

    record = client.get_classified("e0a5a7da-7c11-410a-b185-930cca2a1818")

    assert captured["operation"] == "ClassifiedFeedItem"
    assert captured["variables"]["classifiedId"] == "e0a5a7da-7c11-410a-b185-930cca2a1818"
    assert record["id"] == "e0a5a7da-7c11-410a-b185-930cca2a1818"
    assert record["title"] == "Pokemon Card Tins Collection"
    # The detail operation exposes the raw numeric price plus its currency.
    assert record["price"] == "150"
    assert record["currency"] == "USD"
    assert record["original_price"] is None
    assert record["status"] == "ACTIVE"
    assert record["is_sold"] is False
    # ...and the named category, which the grid card only carries as a numeric id.
    assert record["category"] == "Toys & games"
    assert record["seller"] == "Aaron Bartholomew"
    assert record["distance_miles"] == 8.65
    assert record["location"] == "Nextdoor Indian Woods"
    assert record["created_at"] == "2026-07-25T05:38:20.942000+00:00"
    assert record["expires_at"].startswith("2026-08-24T")
    assert record["photo_urls"] == [
        "https://us1-photo.nextdoor.com/post_photos/fc/0c/fc0c10ef47365f4aeba0911d9dff05f6.jpeg"
    ]
    # The canonical listing URL comes from Nextdoor's own shareText.
    assert record["url"].startswith(
        "https://nextdoor.com/for_sale_and_free/e0a5a7da-7c11-410a-b185-930cca2a1818/"
    )
    assert record["description"].startswith("Pokémon TCG Bundle")


def test_get_classified_missing_listing_fails_loudly(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client, "_graphql", lambda op, variables=None: {"classifiedFeedItem": None}
    )
    with pytest.raises(ClientError) as exc:
        client.get_classified("does-not-exist")
    assert "classifiedFeedItem" in str(exc.value)


def test_search_against_real_fixture(monkeypatch):
    data = _load_fixture("search_lego")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.search("lego", limit=50)

    # The captured 'lego' search spans every content section Nextdoor returns.
    assert {r["section"] for r in rows} == {
        "CLASSIFIED",
        "USER",
        "LOCAL_EVENT",
        "BUSINESS",
        "POST",
    }
    assert len(rows) == 27
    content = [r for r in rows if r["type"] is not None]
    assert {r["type"] for r in content} == {
        "classified",
        "user",
        "localEvent",
        "business",
        "post",
    }
    # Every real result carries a direct URL.
    assert all(r["url"].startswith("https://nextdoor.com/") for r in content)
    # Classified results in search get the same price split as the grid.
    listings = [r for r in content if r["type"] == "classified"]
    assert {"Pink Squishy Toy with Case", "$20"} <= {
        r["title"] for r in listings
    } | {r["price"] for r in listings}
    # Post results link to opaque post slugs.
    posts = [r for r in content if r["type"] == "post"]
    assert all("/p/" in r["url"] for r in posts)


def test_search_limit_caps_flattened_results(monkeypatch):
    data = _load_fixture("search_lego")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    assert len(client.search("lego", limit=4)) == 4


def test_get_notifications_against_real_fixture(monkeypatch):
    data = _load_fixture("dashboardBadges")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    rows = client.get_notifications()

    assert rows == [
        {"id": "saved_bookmarks", "label": "Bookmarks", "badges": None},
        {"id": "events", "label": "Events", "badges": None},
        {"id": "interests", "label": "Interests", "badges": None},
    ]


def test_get_me_against_real_fixture(monkeypatch):
    data = _load_fixture("getMe")
    client = _make_client(monkeypatch)
    monkeypatch.setattr(client, "_graphql", lambda op, variables=None: data)

    user = client.get_me()

    # get_me returns the raw, rich user object (data.me.user).
    assert user["id"] == "user_57902626"
    assert user["legacyUserId"] == "57902626"
    assert user["name"]["displayName"] == "Adam Bertram"
    assert user["__typename"] == "UserProfile"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<!DOCTYPE html><html><body>Please log in</body></html>", True),
        ('<!doctype html><a href="/login/?next=/news_feed/">Login</a>', True),
        ('{"data": {"me": null}}', False),
        ("", False),
    ],
)
def test_is_login_wall(text, expected):
    assert _is_login_wall(text) is expected


# ---- Client transport (mocked session) --------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=None):
        self.status_code = status_code
        self._json_body = json_body
        if text is not None:
            self.text = text
        elif json_body is not None:
            self.text = json.dumps(json_body)
        else:
            self.text = ""
        self.headers = {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


def _make_client(monkeypatch, *, cookies=None):
    """Build a NextdoorClient with credentials present and cookies mocked."""
    cookies = cookies or [
        BrowserCookie(name="ndp_session_id", value="sess", domain=".nextdoor.com", path="/", expires=-1),
        BrowserCookie(name="csrftoken", value="csrf-abc", domain=".nextdoor.com", path="/", expires=-1),
    ]

    class _Config:
        base_url = "https://nextdoor.com/api/gql"

        def has_credentials(self):
            return True

        def get_missing_credentials(self):
            return []

        def get_browser(self):
            raise AssertionError("browser must not launch in mocked tests")

    monkeypatch.setattr(
        BrowserAuthState,
        "from_config",
        classmethod(lambda cls, cfg: BrowserAuthState(cookies=tuple(cookies))),
    )
    return NextdoorClient(config=_Config())


def test_missing_credentials_raises():
    class _Config:
        base_url = "https://nextdoor.com/api/gql"

        def has_credentials(self):
            return False

        def get_missing_credentials(self):
            return ["BROWSER_SESSION"]

    with pytest.raises(ClientError) as exc:
        NextdoorClient(config=_Config())
    assert "auth login" in str(exc.value)


def test_session_carries_cookies_and_csrf_header(monkeypatch):
    client = _make_client(monkeypatch)
    session = client.session
    assert session.cookies.get("ndp_session_id") == "sess"
    assert session.cookies.get("csrftoken") == "csrf-abc"
    assert session.headers["x-csrftoken"] == "csrf-abc"


def test_graphql_routes_operation_in_path_and_body(monkeypatch):
    client = _make_client(monkeypatch)
    captured = {}

    def fake_request(method, url, json=None):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = json
        return _FakeResponse(json_body={"data": {"me": {"user": {"id": "u1"}}}})

    monkeypatch.setattr(client.session, "request", fake_request)
    data = client._graphql("getMe")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://nextdoor.com/api/gql/getMe"
    assert captured["body"]["operationName"] == "getMe"
    assert (
        captured["body"]["extensions"]["persistedQuery"]["sha256Hash"]
        == client_module.PERSISTED_QUERIES["getMe"]
    )
    assert data == {"me": {"user": {"id": "u1"}}}


def test_graphql_unknown_operation_raises(monkeypatch):
    client = _make_client(monkeypatch)
    with pytest.raises(ClientError) as exc:
        client._graphql("NotARealOp")
    assert "Unknown Nextdoor GraphQL operation" in str(exc.value)


def test_graphql_login_wall_raises_auth_error(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(status_code=403, text="<!DOCTYPE html><body>Log in</body>"),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "auth login --force" in str(exc.value)


def test_graphql_null_me_raises_auth_error(monkeypatch):
    # Nextdoor answers an unauthenticated persisted query with HTTP 200 and
    # data.me == null (no 401/403, no GraphQL error). This must fail loudly.
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": None, "requestId": "x"}}),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "not authenticated" in str(exc.value).lower()
    assert "auth login --force" in str(exc.value)


def test_get_feed_raises_auth_error_on_null_me(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": None}}),
    )
    with pytest.raises(ClientError) as exc:
        client.get_feed()
    assert "not authenticated" in str(exc.value).lower()


def test_graphql_auth_error_in_errors_array(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"errors": [{"message": "Unauthorized session"}]}),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "auth login --force" in str(exc.value)


def test_graphql_generic_error_surfaces(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"errors": [{"message": "Bad request"}]}),
    )
    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "GraphQL error" in str(exc.value)


def test_get_feed_normalizes_items(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={
                "data": {
                    "me": {
                        "personalizedFeed": {
                            "feedItems": [
                                {"feedItemType": "POST", "contentId": 1, "post": {"subject": "Hi"}}
                            ]
                        }
                    }
                }
            }
        ),
    )
    rows = client.get_feed(limit=5)
    assert len(rows) == 1
    assert set(rows[0]) == FEED_RECORD_KEYS
    assert rows[0]["id"] == 1
    assert rows[0]["type"] == "POST"
    assert rows[0]["title"] == "Hi"


def test_get_me_raises_on_empty_user(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": {"user": None}}}),
    )
    with pytest.raises(ClientError) as exc:
        client.get_me()
    assert "logged out" in str(exc.value).lower()


def test_get_me_raises_auth_error_on_null_me(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(json_body={"data": {"me": None}}),
    )
    # data.me == null is the unauthenticated signal — surfaced as a clear,
    # actionable auth error before required_path is reached.
    with pytest.raises(ClientError) as exc:
        client.get_me()
    assert "not authenticated" in str(exc.value).lower()


def test_get_notifications_normalizes_records(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={
                "data": {
                    "me": {
                        "shortcuts": [
                            {"type": "events", "title": "Events", "badges": 3, "__typename": "Shortcut"}
                        ]
                    }
                }
            }
        ),
    )
    rows = client.get_notifications()
    assert rows == [{"id": "events", "label": "Events", "badges": 3}]


def test_optional_list_rejects_non_list(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **k: _FakeResponse(
            json_body={"data": {"me": {"personalizedFeed": {"feedItems": "oops"}}}}
        ),
    )
    with pytest.raises(ClientError) as exc:
        client.get_feed()
    assert "list" in str(exc.value).lower()


# ---- Global search wiring ---------------------------------------------------


def _search_response(views):
    return {"data": {"searchFeedV2": {"query": "lego", "searchResultView": views}}}


def test_search_sends_the_real_search_operation(monkeypatch):
    client = _make_client(monkeypatch)
    captured = {}

    def fake_request(method, url, json=None):
        captured["url"] = url
        captured["body"] = json
        return _FakeResponse(
            json_body=_search_response(
                [
                    {
                        "type": "POST",
                        "searchResultItems": {
                            "edges": [
                                {
                                    "node": {
                                        "__typename": "SearchResult",
                                        "contentId": "1",
                                        "contentType": "post",
                                        "title": {"text": "Lego lot"},
                                        "url": "https://nextdoor.com/p/abc?view=detail",
                                    }
                                }
                            ]
                        },
                    }
                ]
            )
        )

    monkeypatch.setattr(client.session, "request", fake_request)
    rows = client.search("lego")

    assert captured["url"] == "https://nextdoor.com/api/gql/search"
    assert captured["body"]["operationName"] == "search"
    assert (
        captured["body"]["extensions"]["persistedQuery"]["sha256Hash"]
        == client_module.PERSISTED_QUERIES["search"]
    )
    args = captured["body"]["variables"]["mainSearchArgs"]
    assert args["query"] == "lego"
    assert args["searchTrackingContext"] == client_module.SEARCH_TRACKING_CONTEXT
    # The first result section must not be excluded, or the top matches vanish.
    assert captured["body"]["variables"]["excludeFirstSection"] is False
    assert rows == [
        {
            "id": "1",
            "section": "POST",
            "type": "post",
            "title": "Lego lot",
            "price": None,
            "subtitle": None,
            "url": "https://nextdoor.com/p/abc?view=detail",
        }
    ]


# ---- Search expired-session detection ---------------------------------------
#
# searchFeedV2 is a top-level field: Nextdoor answers it with HTTP 200 + empty
# result views even when logged out (no me field, no GraphQL error, no login
# wall), so an empty result is ambiguous. search() disambiguates by running a
# me-scoped PersonalizedFeed liveness probe ONLY when nothing came back;
# _graphql raises the standard re-auth error when data.me is null.


def test_search_logged_out_empty_raises_reauth_error(monkeypatch):
    client = _make_client(monkeypatch)

    def fake_request(method, url, json=None):
        operation = json["operationName"]
        if operation == "search":
            return _FakeResponse(json_body=_search_response([]))
        if operation == "PersonalizedFeed":
            return _FakeResponse(json_body={"data": {"me": None, "requestId": "x"}})
        raise AssertionError(f"unexpected operation {operation}")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(ClientError) as exc:
        client.search("lego")
    assert "not authenticated" in str(exc.value).lower()
    assert "nextdoor auth login --force" in str(exc.value)


def test_search_logged_in_genuine_empty_returns_empty(monkeypatch):
    # Logged in but no matches: the probe confirms a live session (me not
    # null), so search returns [] without raising.
    client = _make_client(monkeypatch)

    def fake_request(method, url, json=None):
        operation = json["operationName"]
        if operation == "search":
            return _FakeResponse(json_body=_search_response([]))
        if operation == "PersonalizedFeed":
            return _FakeResponse(
                json_body={"data": {"me": {"personalizedFeed": {"feedItems": []}}}}
            )
        raise AssertionError(f"unexpected operation {operation}")

    monkeypatch.setattr(client.session, "request", fake_request)

    assert client.search("zzz-no-such-thing") == []


def test_search_non_empty_skips_liveness_probe(monkeypatch):
    client = _make_client(monkeypatch)
    operations = []

    def fake_request(method, url, json=None):
        operation = json["operationName"]
        operations.append(operation)
        if operation == "search":
            return _FakeResponse(
                json_body=_search_response(
                    [
                        {
                            "type": "BUSINESS",
                            "searchResultItems": {
                                "edges": [
                                    {
                                        "node": {
                                            "__typename": "SearchResult",
                                            "contentId": "9",
                                            "contentType": "business",
                                            "title": {"text": "Plumber"},
                                            "url": "https://nextdoor.com/page/plumber",
                                        }
                                    }
                                ]
                            },
                        }
                    ]
                )
            )
        raise AssertionError(f"probe must not run for non-empty results: {operation}")

    monkeypatch.setattr(client.session, "request", fake_request)

    assert [r["title"] for r in client.search("plumber")] == ["Plumber"]
    assert operations == ["search"]


# ---- Classifieds wiring -----------------------------------------------------


def _classified_page(edges, has_next_page, end_cursor=None):
    page_info = {"hasNextPage": has_next_page}
    if end_cursor is not None:
        page_info["endCursor"] = end_cursor
    return {
        "data": {
            "searchClassifiedFeed": {
                "searchResultView": [
                    {"searchResultItemsV2": {"pageInfo": page_info, "edges": edges}}
                ]
            }
        }
    }


def _classified_edge(index):
    return {
        "node": {
            "itemType": "ORGANIC",
            "item": {
                "__typename": "SearchResultGridItem",
                "contentId": f"listing-{index}",
                "title": {"text": f"$5\nItem {index}", "styles": []},
                "url": f"https://nextdoor.com/for_sale_and_free/listing-{index}/",
            },
        }
    }


def test_list_classifieds_sends_persisted_query_and_sort(monkeypatch):
    client = _make_client(monkeypatch)
    captured = {}

    def fake_request(method, url, json=None):
        captured["url"] = url
        captured["body"] = json
        return _FakeResponse(json_body=_classified_page([_classified_edge(0)], False))

    monkeypatch.setattr(client.session, "request", fake_request)
    rows = client.list_classifieds(query="lego", limit=5)

    assert captured["url"] == "https://nextdoor.com/api/gql/searchClassifiedV2"
    assert captured["body"]["operationName"] == "searchClassifiedV2"
    assert (
        captured["body"]["extensions"]["persistedQuery"]["sha256Hash"]
        == client_module.PERSISTED_QUERIES["searchClassifiedV2"]
    )
    args = captured["body"]["variables"]["classifiedSearchArgs"]
    assert args["query"] == "lego"
    assert args["searchTrackingContext"] == client_module.CLASSIFIED_TRACKING_CONTEXT
    # Default sort is the server-side newest-first order.
    assert args["filters"]["sortOrder"] == "SORT_BY_TIME"
    # The first page must not carry a cursor.
    assert "cursor" not in args
    assert rows[0]["url"] == "https://nextdoor.com/for_sale_and_free/listing-0/"


def test_list_classifieds_relevance_uses_distance_and_date(monkeypatch):
    client = _make_client(monkeypatch)
    captured = {}

    def fake_graphql(operation, variables=None):
        captured["variables"] = variables
        return {"searchClassifiedFeed": {"searchResultView": []}}

    monkeypatch.setattr(client, "_graphql", fake_graphql)
    monkeypatch.setattr(client, "_assert_session_authenticated", lambda: None)

    client.list_classifieds(sort_order="SORT_BY_DISTANCE_AND_DATE")
    assert (
        captured["variables"]["classifiedSearchArgs"]["filters"]["sortOrder"]
        == "SORT_BY_DISTANCE_AND_DATE"
    )


def test_list_classifieds_rejects_unknown_sort_order(monkeypatch):
    client = _make_client(monkeypatch)
    with pytest.raises(ClientError) as exc:
        client.list_classifieds(sort_order="NOT_A_REAL_ORDER")
    assert "sortOrder" in str(exc.value)


def test_list_classifieds_pages_with_cursor_until_limit(monkeypatch):
    # The grid returns ~20 nodes per page, so a larger --limit must follow the
    # endCursor instead of silently returning one short page.
    client = _make_client(monkeypatch)
    cursors = []
    pages = [
        _classified_page([_classified_edge(i) for i in range(3)], True, "cursor-1"),
        _classified_page([_classified_edge(i) for i in range(3, 6)], True, "cursor-2"),
    ]

    def fake_graphql(operation, variables=None):
        cursors.append(variables["classifiedSearchArgs"].get("cursor"))
        return pages[len(cursors) - 1]["data"]

    monkeypatch.setattr(client, "_graphql", fake_graphql)
    rows = client.list_classifieds(limit=5)

    assert cursors == [None, "cursor-1"]
    assert len(rows) == 5
    assert [r["id"] for r in rows] == [f"listing-{i}" for i in range(5)]


def test_list_classifieds_stops_when_server_has_no_next_page(monkeypatch):
    client = _make_client(monkeypatch)
    calls = []

    def fake_graphql(operation, variables=None):
        calls.append(variables)
        return _classified_page([_classified_edge(0)], False)["data"]

    monkeypatch.setattr(client, "_graphql", fake_graphql)
    rows = client.list_classifieds(limit=50)

    assert len(calls) == 1
    assert len(rows) == 1


def test_list_classifieds_reuses_one_request_id_across_pages(monkeypatch):
    client = _make_client(monkeypatch)
    request_ids = []
    pages = [
        _classified_page([_classified_edge(0)], True, "cursor-1"),
        _classified_page([_classified_edge(1)], False),
    ]

    def fake_graphql(operation, variables=None):
        args = variables["classifiedSearchArgs"]
        request_ids.append(args["requestId"])
        return pages[len(request_ids) - 1]["data"]

    monkeypatch.setattr(client, "_graphql", fake_graphql)
    client.list_classifieds(limit=10)

    assert len(request_ids) == 2
    assert len(set(request_ids)) == 1


def test_list_classifieds_logged_out_empty_raises_reauth_error(monkeypatch):
    client = _make_client(monkeypatch)

    def fake_request(method, url, json=None):
        operation = json["operationName"]
        if operation == "searchClassifiedV2":
            return _FakeResponse(
                json_body={"data": {"searchClassifiedFeed": {"searchResultView": []}}}
            )
        if operation == "PersonalizedFeed":
            return _FakeResponse(json_body={"data": {"me": None}})
        raise AssertionError(f"unexpected operation {operation}")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(ClientError) as exc:
        client.list_classifieds()
    assert "not authenticated" in str(exc.value).lower()


# ---- Retry wiring (shared RequestsRetryPolicy) ------------------------------


def _zero_delay_policy(max_retries=2):
    """A policy that retries without ever sleeping for a measurable time."""
    return RequestsRetryPolicy(max_retries=max_retries, base_delay=0, max_delay=0, jitter=0)


def test_request_retries_retryable_status_then_succeeds(monkeypatch):
    client = _make_client(monkeypatch)
    client._retry_policy = _zero_delay_policy()

    responses = [
        _FakeResponse(status_code=503),
        _FakeResponse(json_body={"data": {"me": {"user": {"id": "u1"}}}}),
    ]
    calls = {"n": 0}

    def fake_request(method, url, json=None):
        calls["n"] += 1
        return responses.pop(0)

    monkeypatch.setattr(client.session, "request", fake_request)

    data = client._graphql("getMe")

    assert calls["n"] == 2  # retried once after the 503
    assert data == {"me": {"user": {"id": "u1"}}}


def test_request_wraps_persistent_network_error(monkeypatch):
    client = _make_client(monkeypatch)
    client._retry_policy = _zero_delay_policy(max_retries=1)

    def fake_request(method, url, json=None):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(ClientError) as exc:
        client._graphql("getMe")
    assert "Nextdoor request failed after retries" in str(exc.value)


# ---- Source-CLI Sort Standard -----------------------------------------------
#
# Both listing surfaces expose a genuine SERVER-SIDE recency sort. The feed's
# captured response advertises RECENT_POSTS in its own sortOrderOptions and
# accepts the choice via mainFeedArgs.sortOrder; the For Sale & Free grid sends
# SORT_BY_TIME ("Newest") / SORT_BY_DISTANCE_AND_DATE ("Most Relevant") through
# classifiedSearchArgs.filters.sortOrder. Unknown values fail fast; '--desc'
# reverses the fetched page.


def test_resolve_feed_sort_default_newest_maps_to_recent_posts():
    assert _resolve_sort(FEED_SORT_MAP, "newest", desc=False) == "RECENT_POSTS"


def test_resolve_feed_sort_is_case_insensitive():
    assert _resolve_sort(FEED_SORT_MAP, "NEWEST", desc=False) == "RECENT_POSTS"


def test_resolve_feed_sort_relevance_maps_to_for_you():
    assert _resolve_sort(FEED_SORT_MAP, "relevance", desc=False) == "FOR_YOU"


def test_resolve_feed_sort_newest_desc_still_recent_posts():
    # --desc keeps the same server sort (RECENT_POSTS); the caller reverses the
    # fetched page for oldest-first.
    assert _resolve_sort(FEED_SORT_MAP, "newest", desc=True) == "RECENT_POSTS"


def test_resolve_classified_sort_maps_to_grid_server_values():
    assert _resolve_sort(CLASSIFIED_SORT_MAP, "newest", desc=False) == "SORT_BY_TIME"
    assert (
        _resolve_sort(CLASSIFIED_SORT_MAP, "relevance", desc=False)
        == "SORT_BY_DISTANCE_AND_DATE"
    )


@pytest.mark.parametrize("sort_map", [FEED_SORT_MAP, CLASSIFIED_SORT_MAP])
def test_resolve_sort_rejects_unknown_value(sort_map):
    with pytest.raises(typer.BadParameter) as exc:
        _resolve_sort(sort_map, "bogus", desc=False)
    message = str(exc.value)
    assert "Invalid --sort 'bogus'" in message
    # The error lists the valid vocabulary (fail-fast, no silent fallback).
    for value in sort_map:
        assert value in message


@pytest.mark.parametrize("sort_map", [FEED_SORT_MAP, CLASSIFIED_SORT_MAP])
def test_resolve_sort_relevance_desc_rejected(sort_map):
    with pytest.raises(typer.BadParameter) as exc:
        _resolve_sort(sort_map, "relevance", desc=True)
    assert "desc is not supported" in str(exc.value).lower()


def test_get_feed_sends_recent_posts_sort_order_by_default(monkeypatch):
    client = _make_client(monkeypatch)
    captured = {}

    def fake_graphql(operation, variables=None):
        captured["operation"] = operation
        captured["variables"] = variables
        return {"me": {"personalizedFeed": {"feedItems": []}}}

    monkeypatch.setattr(client, "_graphql", fake_graphql)

    client.get_feed(limit=5)
    assert captured["operation"] == "PersonalizedFeed"
    assert captured["variables"]["mainFeedArgs"]["sortOrder"] == "RECENT_POSTS"

    client.get_feed(limit=5, sort_order="FOR_YOU")
    assert captured["variables"]["mainFeedArgs"]["sortOrder"] == "FOR_YOU"


def test_get_feed_rejects_unknown_sort_order(monkeypatch):
    client = _make_client(monkeypatch)
    # Guard fires before any network call; no _graphql stub needed.
    with pytest.raises(ClientError) as exc:
        client.get_feed(sort_order="NOT_A_REAL_ORDER")
    assert "sortOrder" in str(exc.value)


class _FakeFeedClient:
    """A stand-in client that records the sort_order and returns fixed rows."""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def get_feed(self, limit, sort_order="RECENT_POSTS"):
        self.calls.append({"limit": limit, "sort_order": sort_order})
        return list(self._rows)

    def close(self):
        pass


def _fake_feed_rows():
    # Server returns RECENT_POSTS order: newest first.
    return [
        {"id": 3, "type": "POST", "title": "newest"},
        {"id": 2, "type": "POST", "title": "middle"},
        {"id": 1, "type": "POST", "title": "oldest"},
    ]


def test_feed_command_default_is_newest_first(monkeypatch):
    fake = _FakeFeedClient(_fake_feed_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["feed"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [r["id"] for r in rows] == [3, 2, 1]
    # Default sort resolves to the server-side chronological order.
    assert fake.calls == [{"limit": 10, "sort_order": "RECENT_POSTS"}]


def test_feed_command_desc_reverses_to_oldest_first(monkeypatch):
    fake = _FakeFeedClient(_fake_feed_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["feed", "--desc"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [r["id"] for r in rows] == [1, 2, 3]
    # --desc still uses the RECENT_POSTS server sort; reversal is client-side.
    assert fake.calls[0]["sort_order"] == "RECENT_POSTS"


def test_feed_command_relevance_uses_for_you(monkeypatch):
    fake = _FakeFeedClient(_fake_feed_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["feed", "--sort", "relevance"])
    assert result.exit_code == 0
    assert fake.calls[0]["sort_order"] == "FOR_YOU"


def test_feed_command_bogus_sort_exits_nonzero_without_client(monkeypatch):
    def _no_client():
        raise AssertionError("client must not be built for an invalid --sort")

    monkeypatch.setattr(main_module, "get_client", _no_client)

    result = CliRunner().invoke(app, ["feed", "--sort", "bogus"])
    assert result.exit_code != 0
    assert "Invalid --sort 'bogus'" in result.output


# ---- classifieds list command ----------------------------------------------


class _FakeClassifiedsClient:
    """A stand-in client that records call args and returns fixed listing rows."""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def list_classifieds(self, query, limit, sort_order="SORT_BY_TIME"):
        self.calls.append({"query": query, "limit": limit, "sort_order": sort_order})
        return list(self._rows)

    def close(self):
        pass


def _fake_listing_rows():
    return [
        {
            "id": f"listing-{i}",
            "type": "ORGANIC",
            "title": f"Item {i}",
            "price": f"${i}",
            "original_price": None,
            "subtitle": f"{i} hr ago · 1.0 mi · Evansville",
            "image_url": "https://us1-photo.nextdoor.com/x.jpeg",
            "url": f"https://nextdoor.com/for_sale_and_free/listing-{i}/",
        }
        for i in (3, 2, 1)
    ]


def test_classifieds_list_default_is_newest_first(monkeypatch):
    fake = _FakeClassifiedsClient(_fake_listing_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["classifieds", "list"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [r["id"] for r in rows] == ["listing-3", "listing-2", "listing-1"]
    assert fake.calls == [{"query": "", "limit": 25, "sort_order": "SORT_BY_TIME"}]


def test_classifieds_list_passes_query_limit_and_relevance(monkeypatch):
    fake = _FakeClassifiedsClient(_fake_listing_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app, ["classifieds", "list", "lego", "--limit", "3", "--sort", "relevance"]
    )
    assert result.exit_code == 0
    assert fake.calls == [
        {"query": "lego", "limit": 3, "sort_order": "SORT_BY_DISTANCE_AND_DATE"}
    ]


def test_classifieds_list_desc_reverses_fetched_pages(monkeypatch):
    fake = _FakeClassifiedsClient(_fake_listing_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["classifieds", "list", "--desc"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert [r["id"] for r in rows] == ["listing-1", "listing-2", "listing-3"]
    assert fake.calls[0]["sort_order"] == "SORT_BY_TIME"


def test_classifieds_list_properties_and_filter(monkeypatch):
    fake = _FakeClassifiedsClient(_fake_listing_rows())
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(
        app,
        ["classifieds", "list", "--filter", "title:eq:Item 2", "--properties", "id,url"],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"id": "listing-2", "url": "https://nextdoor.com/for_sale_and_free/listing-2/"}
    ]


class _FakeClassifiedDetailClient:
    def __init__(self, record):
        self._record = record
        self.calls = []

    def get_classified(self, classified_id):
        self.calls.append(classified_id)
        return dict(self._record)

    def close(self):
        pass


def test_classifieds_get_returns_the_listing_record(monkeypatch):
    record = {
        "id": "e0a5a7da",
        "title": "Pokemon Card Tins Collection",
        "price": "150",
        "url": "https://nextdoor.com/for_sale_and_free/e0a5a7da/?init_source=share",
    }
    fake = _FakeClassifiedDetailClient(record)
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["classifieds", "get", "e0a5a7da"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == record
    assert fake.calls == ["e0a5a7da"]


def test_classifieds_get_supports_table_and_properties(monkeypatch):
    fake = _FakeClassifiedDetailClient(
        {"id": "e0a5a7da", "title": "Pokemon Card Tins Collection", "price": "150"}
    )
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    table_result = CliRunner().invoke(app, ["classifieds", "get", "e0a5a7da", "--table"])
    assert table_result.exit_code == 0
    assert "Pokemon Card Tins Collection" in table_result.output

    props_result = CliRunner().invoke(
        app, ["classifieds", "get", "e0a5a7da", "--properties", "id,price"]
    )
    assert props_result.exit_code == 0
    assert json.loads(props_result.stdout) == [{"id": "e0a5a7da", "price": "150"}]


def test_classifieds_list_bogus_sort_exits_nonzero_without_client(monkeypatch):
    def _no_client():
        raise AssertionError("client must not be built for an invalid --sort")

    monkeypatch.setattr(main_module, "get_client", _no_client)

    result = CliRunner().invoke(app, ["classifieds", "list", "--sort", "bogus"])
    assert result.exit_code != 0
    assert "Invalid --sort 'bogus'" in result.output


# ---- search command ---------------------------------------------------------


class _FakeSearchClient:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def search(self, query, limit):
        self.calls.append({"query": query, "limit": limit})
        return list(self._rows)

    def close(self):
        pass


def test_search_command_passes_query_and_limit(monkeypatch):
    rows = [
        {
            "id": "1",
            "section": "CLASSIFIED",
            "type": "classified",
            "title": "Lego lot",
            "price": "$40",
            "subtitle": "1 day ago · 2.0 mi · Evansville",
            "url": "https://nextdoor.com/for_sale_and_free/1/",
        }
    ]
    fake = _FakeSearchClient(rows)
    monkeypatch.setattr(main_module, "get_client", lambda: fake)

    result = CliRunner().invoke(app, ["search", "lego", "--limit", "7"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == rows
    assert fake.calls == [{"query": "lego", "limit": 7}]
