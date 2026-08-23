"""Tests for the Source-CLI Sort Standard on `poshmark listings search`.

Poshmark honors its ``?sort_by=`` URL parameter server-side, so ``--sort``/
``--desc`` resolve to a Poshmark ``sort_by`` value that the client threads into
the search URL. The value mapping was verified live against the Poshmark search
"Sort By" dropdown (its ``items`` attribute plus each value's ``--selected``
menu label):

    newest    -> added_desc    ("Just In")
    price     -> price_asc     ("Price Low to High")
    price -d  -> price_desc    ("Price High to Low")
    relevance -> relevance_v2  ("Relevance")

Poshmark's ``best_match`` value is the "Just Shared" sort (NOT relevance), and it
exposes no oldest-first (``added_asc``) sort, so ``newest --desc`` is rejected.

These tests cover:
  - ``_resolve_sort`` mapping + validation (default newest, case-insensitive,
    fail-fast on unknown, ``--desc`` rejection for newest/relevance)
  - the ``listings search`` command surface: unknown ``--sort`` exits non-zero,
    and each valid ``--sort``/``--desc`` threads the correct ``sort_by`` into the
    client
  - the client builds the search URL with the resolved ``sort_by`` parameter
"""

import pytest
import typer
from typer.testing import CliRunner

import cli_tools_shared.data_cache as data_cache
from poshmark_cli import client as client_module
from poshmark_cli import main


runner = CliRunner()


# --- _resolve_sort: mapping + fail-fast validation ---------------------------


def test_resolve_sort_default_newest_maps_to_added_desc():
    assert main._resolve_sort("newest") == "added_desc"


def test_resolve_sort_price_natural_maps_to_price_asc():
    assert main._resolve_sort("price") == "price_asc"


def test_resolve_sort_price_desc_maps_to_price_desc():
    assert main._resolve_sort("price", desc=True) == "price_desc"


def test_resolve_sort_relevance_maps_to_relevance_v2():
    assert main._resolve_sort("relevance") == "relevance_v2"


def test_resolve_sort_is_case_insensitive():
    assert main._resolve_sort("NEWEST") == "added_desc"
    assert main._resolve_sort("Price") == "price_asc"
    assert main._resolve_sort("Relevance") == "relevance_v2"


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
    """Poshmark has no oldest-first sort, so `newest --desc` is rejected."""
    with pytest.raises(typer.BadParameter) as exc:
        main._resolve_sort("newest", desc=True)
    assert "newest" in str(exc.value)


# --- command surface: sort_by threading + fail-fast --------------------------


class _FakeClient:
    """Records the sort_by threaded into search; never touches the network."""

    def __init__(self):
        self.calls = []

    def search(self, query, limit=100, sort_by="added_desc"):
        self.calls.append({"query": query, "limit": limit, "sort_by": sort_by})
        return []

    def close(self):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(main, "get_client", lambda: fake)
    return fake


def _search(*args):
    """Invoke the real `poshmark listings search` path through the top-level app."""
    return runner.invoke(main.app, ["listings", "search", "widget", *args])


def test_list_default_discovers_listing_urls_newest_first(fake_client):
    result = runner.invoke(main.app, ["listings", "list", "--limit", "7"])
    assert result.exit_code == 0
    assert fake_client.calls == [
        {"query": "", "limit": 7, "sort_by": "added_desc"}
    ]


def test_search_unknown_sort_exits_nonzero(fake_client):
    """`listings search --sort bogus` exits non-zero without a network call."""
    result = _search("--sort", "bogus")
    assert result.exit_code != 0
    assert fake_client.calls == []


def test_search_default_sort_threads_added_desc(fake_client):
    result = _search()
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == "added_desc"


def test_search_price_threads_price_asc(fake_client):
    result = _search("--sort", "price")
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == "price_asc"


def test_search_price_desc_threads_price_desc(fake_client):
    result = _search("--sort", "price", "--desc")
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == "price_desc"


def test_search_relevance_threads_relevance_v2(fake_client):
    result = _search("--sort", "relevance")
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == "relevance_v2"


def test_search_short_flags_thread_price_desc(fake_client):
    result = _search("-s", "price", "-d")
    assert result.exit_code == 0
    assert fake_client.calls[-1]["sort_by"] == "price_desc"


def test_search_newest_desc_exits_nonzero(fake_client):
    result = _search("--sort", "newest", "--desc")
    assert result.exit_code != 0
    assert fake_client.calls == []


def test_search_relevance_desc_exits_nonzero(fake_client):
    result = _search("--sort", "relevance", "--desc")
    assert result.exit_code != 0
    assert fake_client.calls == []


# --- client: sort_by is written into the Poshmark search URL -----------------


class _FakePage:
    def wait_for_selector(self, *args, **kwargs):
        pass

    def evaluate(self, js):
        # SCROLL_JS returns a height int; the extract JS returns the listing list.
        return 0 if "scrollBy" in js else []


class _FakeBrowser:
    def __init__(self):
        self.requested_url = None

    def get_page(self, url):
        self.requested_url = url
        return _FakePage()

    def close(self):
        pass


def test_client_search_builds_url_with_sort_by(monkeypatch):
    """The client interpolates the resolved sort_by into the search URL."""
    # Disable the response cache so the real method runs and we can read the URL.
    monkeypatch.setattr(data_cache, "is_cache_enabled", lambda: False)
    fake_browser = _FakeBrowser()

    posh = client_module.PoshmarkClient()
    posh._browser = fake_browser

    posh.search("nike shoes", limit=3, sort_by="price_desc")

    assert fake_browser.requested_url is not None
    assert "sort_by=price_desc" in fake_browser.requested_url
    assert "query=nike+shoes" in fake_browser.requested_url
