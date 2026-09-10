"""`ebay listings search` command contract against a mocked SoldComps client.

Downstream callers (eBayManager's pricing scripts, ebayArbitrage's market
adapter, the ebay-listing and is-it-worth-it skills) consume this command's JSON
unmodified, so these tests pin the option surface, the request the command
makes, the JSON rows it prints, and the two capability-removal errors.
"""

import json

import pytest
from typer.testing import CliRunner

from ebay_cli.commands import search as search_commands
from ebay_cli.main import app
from ebay_cli.models.search_result import SearchResult


runner = CliRunner()


SOLD_ROW = SearchResult(
    item_id="226554128899",
    title="LEGO Star Wars 75192 Millennium Falcon UCS",
    price="612.00",
    currency="USD",
    shipping_price="24.50",
    status="sold",
    date_sold="2026-08-30",
    condition="Used",
    format="Buy It Now",
    seller="brickseller99",
    url="https://www.ebay.com/itm/226554128899",
    image_url="https://i.ebayimg.com/thumbs/abc.jpg",
)

ACTIVE_ROW = SearchResult(
    item_id="127992747834",
    title="LEGO bulk lot 5 lbs",
    price="41.25",
    currency="USD",
    shipping_price="0.00",
    status="active",
    time_left="6d 4h left",
    condition="Used",
    format="Auction",
    bids=7,
    seller="bulkbricks",
    url="https://www.ebay.com/itm/127992747834",
)


class RecordingClient:
    """Stands in for SoldCompsClient and records the call it received."""

    def __init__(self, rows):
        self.rows = rows
        self.sold_calls = []
        self.active_calls = []
        self.closed = False

    def search_sold(self, **kwargs):
        self.sold_calls.append(kwargs)
        return self.rows

    def search_active(self, **kwargs):
        self.active_calls.append(kwargs)
        return self.rows

    def close(self):
        self.closed = True


@pytest.fixture
def stub_client(monkeypatch):
    """Install a recording client and hand it back to the test."""

    def install(rows):
        client = RecordingClient(rows)
        monkeypatch.setattr(
            search_commands, "get_soldcomps_client", lambda profile=None: client
        )
        return client

    return install


def test_sold_search_prints_the_rows_callers_parse(stub_client):
    client = stub_client([SOLD_ROW])
    result = runner.invoke(app, ["listings", "search", "LEGO 75192", "--sold", "--limit", "5"])

    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows == [
        {
            "item_id": "226554128899",
            "title": "LEGO Star Wars 75192 Millennium Falcon UCS",
            "price": "612.00",
            "currency": "USD",
            "shipping_price": "24.50",
            "status": "sold",
            "date_sold": "2026-08-30",
            "condition": "Used",
            "format": "Buy It Now",
            "seller": "brickseller99",
            "url": "https://www.ebay.com/itm/226554128899",
            "image_url": "https://i.ebayimg.com/thumbs/abc.jpg",
        }
    ]
    assert client.closed is True


def test_sold_search_passes_every_option_through(stub_client):
    client = stub_client([SOLD_ROW])
    result = runner.invoke(
        app,
        [
            "listings", "search", "LEGO 75192",
            "--sold",
            "--us-only",
            "--min-price", "10",
            "--max-price", "500",
            "--category", "19006",
            "--condition", "used",
            "--sort", "price",
            "--limit", "25",
        ],
    )

    assert result.exit_code == 0, result.output
    assert client.sold_calls == [
        {
            "keywords": "LEGO 75192",
            "min_price": 10.0,
            "max_price": 500.0,
            "category": "19006",
            "condition": "used",
            "us_only": True,
            "limit": 25,
            "sort_order": "pricePlusPostageLowest",
        }
    ]
    assert client.active_calls == []


def test_active_search_uses_the_uncached_active_path(stub_client):
    client = stub_client([ACTIVE_ROW])
    result = runner.invoke(
        app,
        ["listings", "search", "LEGO bulk lot", "--active", "--format", "auction", "--limit", "5"],
    )

    assert result.exit_code == 0, result.output
    assert client.sold_calls == []
    assert client.active_calls[0]["listing_format"] == "auction"
    assert client.active_calls[0]["sort_order"] == "timeNewlyListed"
    rows = json.loads(result.stdout)
    assert rows[0]["status"] == "active"
    assert rows[0]["time_left"] == "6d 4h left"
    assert rows[0]["bids"] == 7


def test_desc_price_sort_reaches_the_client(stub_client):
    client = stub_client([SOLD_ROW])
    result = runner.invoke(
        app, ["listings", "search", "LEGO 75192", "--sold", "--sort", "price", "--desc"]
    )
    assert result.exit_code == 0, result.output
    assert client.sold_calls[0]["sort_order"] == "pricePlusPostageHighest"


def test_table_output_still_renders_sold_columns(stub_client):
    stub_client([SOLD_ROW])
    result = runner.invoke(app, ["listings", "search", "LEGO 75192", "--sold", "--table"])
    assert result.exit_code == 0, result.output
    assert "612.00" in result.stdout
    assert "2026-08-30" in result.stdout


def test_filter_and_properties_still_apply(stub_client):
    stub_client([SOLD_ROW])
    result = runner.invoke(
        app,
        [
            "listings", "search", "LEGO 75192", "--sold",
            "--filter", "status:eq:sold",
            "--properties", "item_id,price",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"item_id": "226554128899", "price": "612.00"}]


# ------------------------------------------------------- capability removals


def test_no_sold_explains_that_unsold_comps_are_gone(stub_client):
    client = stub_client([SOLD_ROW])
    result = runner.invoke(
        app, ["listings", "search", "LEGO 75192", "--completed", "--no-sold"]
    )

    assert result.exit_code == 1
    assert "Unsold completed listings are no longer available" in result.output
    assert "--sold" in result.output
    assert client.sold_calls == []


def test_a_bare_completed_search_hits_the_same_removal_error(stub_client):
    """`--completed` with no `--sold` is the same unsold+sold request."""
    client = stub_client([SOLD_ROW])
    result = runner.invoke(app, ["listings", "search", "LEGO 75192"])

    assert result.exit_code == 1
    assert "Unsold completed listings are no longer available" in result.output
    assert client.sold_calls == []


def test_sort_ending_on_active_listings_names_the_removed_order(stub_client):
    client = stub_client([ACTIVE_ROW])
    result = runner.invoke(
        app, ["listings", "search", "LEGO 75192", "--active", "--sort", "ending"]
    )

    assert result.exit_code == 1
    assert "ending soonest" in result.output
    assert client.active_calls == []


def test_sort_ending_on_sold_comps_names_the_removed_order(stub_client):
    client = stub_client([SOLD_ROW])
    result = runner.invoke(
        app, ["listings", "search", "LEGO 75192", "--sold", "--sort", "ending"]
    )

    assert result.exit_code == 1
    assert "ending soonest" in result.output
    assert client.sold_calls == []


def test_sold_cannot_be_combined_with_active(stub_client):
    stub_client([SOLD_ROW])
    result = runner.invoke(app, ["listings", "search", "LEGO 75192", "--active", "--sold"])
    assert result.exit_code == 1
    assert "cannot be combined with --active" in result.output


def test_format_is_rejected_outside_active_search(stub_client):
    stub_client([SOLD_ROW])
    result = runner.invoke(
        app, ["listings", "search", "LEGO 75192", "--sold", "--format", "bin"]
    )
    assert result.exit_code == 1
    assert "--format only applies with --active" in result.output


def test_a_client_error_exits_one_with_the_actionable_message(monkeypatch):
    from ebay_cli.soldcomps_client import SoldCompsError

    class FailingClient:
        def search_sold(self, **kwargs):
            raise SoldCompsError("SoldComps rejected the API key (HTTP 401).")

        def close(self):
            pass

    monkeypatch.setattr(
        search_commands, "get_soldcomps_client", lambda profile=None: FailingClient()
    )
    result = runner.invoke(app, ["listings", "search", "LEGO 75192", "--sold"])
    assert result.exit_code == 1
    assert "rejected the API key" in result.output
