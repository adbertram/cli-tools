"""Tests for the Source-CLI Sort Standard on `mercari listings search`.

Mercari's search SPA translates a numeric ``?sortBy=`` URL code into the
``searchFacetQuery`` GraphQL criteria, so ``--sort``/``--desc`` resolve to a
Mercari ``sortBy`` code that the client threads into the ``/search`` URL params.
The code mapping was verified live against the fired ``searchFacetQuery``
criteria and the returned result order (top items' ``productQuery`` ``created``
timestamps were strictly descending for code 2):

    newest    -> 2      created-time descending (newest listed first)
    price     -> 3      price ascending  (low -> high)
    price -d  -> 4      price descending (high -> low)
    relevance -> None   omit sortBy => best-match (codes 0/1 == best match)

Mercari US search exposes no oldest-first (created-ascending) code, so
``newest --desc`` is rejected fail-fast (never silently returns newest-first).

These tests cover:
  - ``_resolve_sort`` mapping + validation (default newest, case-insensitive,
    fail-fast on unknown, ``--desc`` rejection for newest/relevance)
  - the ``listings search`` command surface: unknown ``--sort`` exits non-zero
    without a browser call, and each valid ``--sort``/``--desc`` threads the
    correct numeric ``sort_by`` into the client
  - the client's ``build_search_params`` writes the resolved ``sortBy`` code
    into the GraphQL search params (and omits it for relevance)
"""

import pytest
import typer
from typer.testing import CliRunner

from cli_tools_shared import data_cache
from mercari_cli import client as client_module
from mercari_cli import main


runner = CliRunner()


# --- get_item: public item pages must never gate on a seller login -----------


def test_get_item_uses_public_shell_not_authenticated_shell(monkeypatch):
    """`listings get` is a PUBLIC lookup: it drives the public app shell (like
    `search`) so item detail keeps working headlessly on the persistent
    ``cf_clearance`` cookie alone, even after the seller session expires. It
    must NEVER route through the authenticated `/mypage/` shell.
    """
    # Force the @cached wrapper to call through to the real method.
    monkeypatch.setattr(data_cache, "is_cache_enabled", lambda: False)

    calls = {}
    item = client_module.MercariClient.__new__(client_module.MercariClient)

    def fake_app_shell(url):
        calls["app_shell_url"] = url
        return "PAGE"

    def fail_authenticated_shell():
        raise AssertionError("get_item must not use the authenticated shell")

    def fake_capture(page, route, operation, accept, timeout=45):
        assert page == "PAGE"
        calls["route"] = route
        calls["operation"] = operation
        return [{"data": {"item": {"id": "m77772659994"}}}]

    monkeypatch.setattr(item, "_app_shell", fake_app_shell)
    monkeypatch.setattr(item, "_authenticated_shell", fail_authenticated_shell)
    monkeypatch.setattr(item, "_capture", fake_capture)
    monkeypatch.setattr(
        client_module, "normalize_item_detail", lambda raw: {"id": raw["id"]}
    )

    result = item.get_item("https://www.mercari.com/us/item/m77772659994/")

    assert result == {"id": "m77772659994"}
    assert calls["app_shell_url"] == client_module.HOME_URL
    assert calls["operation"] == "productQuery"
    assert calls["route"] == "/us/item/m77772659994/"


# --- _resolve_sort: mapping + fail-fast validation ---------------------------


def test_resolve_sort_default_newest_maps_to_2():
    assert main._resolve_sort("newest") == 2


def test_resolve_sort_price_natural_maps_to_3():
    assert main._resolve_sort("price") == 3


def test_resolve_sort_price_desc_maps_to_4():
    assert main._resolve_sort("price", desc=True) == 4


def test_resolve_sort_relevance_maps_to_none():
    assert main._resolve_sort("relevance") is None


def test_resolve_sort_is_case_insensitive():
    assert main._resolve_sort("NEWEST") == 2
    assert main._resolve_sort("Price") == 3
    assert main._resolve_sort("Relevance") is None


def test_resolve_sort_rejects_unknown_field():
    """Unknown --sort fails fast, lists valid values, and never falls back."""
    with pytest.raises(typer.BadParameter) as exc:
        main._resolve_sort("bogus")
    message = str(exc.value)
    assert "bogus" in message
    assert "newest" in message
    assert "price" in message
    assert "relevance" in message


def test_resolve_sort_rejects_desc_with_relevance():
    with pytest.raises(typer.BadParameter) as exc:
        main._resolve_sort("relevance", desc=True)
    assert "relevance" in str(exc.value)


def test_resolve_sort_rejects_desc_with_newest():
    """Mercari US search has no oldest-first sort, so `newest --desc` is rejected."""
    with pytest.raises(typer.BadParameter) as exc:
        main._resolve_sort("newest", desc=True)
    assert "newest" in str(exc.value)


# --- command surface: sort_by threading + fail-fast --------------------------


class _FakeClient:
    """Records the sort_by threaded into search; never touches the browser."""

    def __init__(self):
        self.calls = []

    def search_items(
        self,
        keyword,
        limit=100,
        status=None,
        condition=None,
        min_price=None,
        max_price=None,
        sort_by=None,
        category_ids=None,
        brand_ids=None,
    ):
        self.calls.append({"keyword": keyword, "sort_by": sort_by})
        return []

    def close(self):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(main, "get_client", lambda: fake)
    return fake


def test_search_unknown_sort_exits_nonzero(fake_client):
    """`listings search --sort bogus` exits non-zero without a browser call."""
    result = runner.invoke(main.listings_app, ["search", "widget", "--sort", "bogus"])
    assert result.exit_code != 0
    assert fake_client.calls == []


def test_search_default_sort_threads_newest_code(fake_client):
    result = runner.invoke(main.listings_app, ["search", "widget"])
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == 2


def test_search_price_threads_code_3(fake_client):
    result = runner.invoke(main.listings_app, ["search", "widget", "--sort", "price"])
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == 3


def test_search_price_desc_threads_code_4(fake_client):
    result = runner.invoke(
        main.listings_app, ["search", "widget", "--sort", "price", "--desc"]
    )
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == 4


def test_search_relevance_threads_none(fake_client):
    result = runner.invoke(
        main.listings_app, ["search", "widget", "--sort", "relevance"]
    )
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] is None


def test_search_short_flags_thread_price_desc(fake_client):
    result = runner.invoke(main.listings_app, ["search", "widget", "-s", "price", "-d"])
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == 4


def test_search_newest_desc_exits_nonzero(fake_client):
    result = runner.invoke(
        main.listings_app, ["search", "widget", "--sort", "newest", "--desc"]
    )
    assert result.exit_code != 0
    assert fake_client.calls == []


def test_search_relevance_desc_exits_nonzero(fake_client):
    result = runner.invoke(
        main.listings_app, ["search", "widget", "--sort", "relevance", "--desc"]
    )
    assert result.exit_code != 0
    assert fake_client.calls == []


# --- client: sortBy code is written into the Mercari search params -----------


def test_build_search_params_newest_writes_sortby_2():
    """`newest` maps into the GraphQL search params as sortBy=2 (created desc)."""
    params = client_module.build_search_params("lego", sort_by=2)
    assert ("keyword", "lego") in params
    assert ("sortBy", "2") in params


def test_build_search_params_price_desc_writes_sortby_4():
    params = client_module.build_search_params("lego", sort_by=4)
    assert ("sortBy", "4") in params


def test_build_search_params_relevance_omits_sortby():
    """`relevance` resolves to None, so no sortBy param is sent (best-match)."""
    params = client_module.build_search_params("lego", sort_by=None)
    assert not any(key == "sortBy" for key, _ in params)
