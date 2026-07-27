import pytest
from bs4 import BeautifulSoup

from shopsalvationarmy_cli.client import ClientError, ShopSalvationArmyClient
from shopsalvationarmy_cli.commands.search import COMMAND_CREDENTIALS


def make_client() -> ShopSalvationArmyClient:
    return ShopSalvationArmyClient(require_auth=False, config=object())


def test_sort_maps_canonical_fields_and_desc_to_site_codes():
    client = make_client()

    # newest is the default and natural = newest-first (site code 1);
    # --desc reverses to oldest (code 2).
    assert client._get_sort_param("newest") == "1"
    assert client._get_sort_param("newest", desc=True) == "2"

    # price natural = low -> high (code 3); --desc = high -> low (code 4).
    assert client._get_sort_param("price") == "3"
    assert client._get_sort_param("price", desc=True) == "4"

    # ending natural = soonest ending first (code 0).
    assert client._get_sort_param("ending") == "0"


def test_sort_field_lookup_is_case_insensitive():
    client = make_client()
    assert client._get_sort_param("NEWEST") == "1"
    assert client._get_sort_param("Price", desc=True) == "4"


def test_unknown_sort_value_raises_clear_error():
    client = make_client()
    with pytest.raises(ClientError) as exc:
        client._get_sort_param("bogus")
    message = str(exc.value)
    assert "bogus" in message
    # Error must list the valid canonical values (fail-fast, no silent fallback).
    assert "newest" in message
    assert "price" in message
    assert "ending" in message


def test_removed_directional_aliases_are_no_longer_accepted():
    client = make_client()
    for removed in ("oldest", "price_low", "price_high", "title_az", "id_high", "activity"):
        with pytest.raises(ClientError):
            client._get_sort_param(removed)


def test_ending_desc_is_rejected_without_site_equivalent():
    client = make_client()
    with pytest.raises(ClientError) as exc:
        client._get_sort_param("ending", desc=True)
    assert "ending" in str(exc.value).lower()


def parse_item(html: str) -> dict:
    client = ShopSalvationArmyClient(require_auth=False, config=object())
    return client._parse_item_page(BeautifulSoup(html, "html.parser"), "123")


def test_hidden_closed_message_does_not_mark_active_listing_ended():
    item = parse_item(
        """
        <h1>Active LEGO Lot</h1>
        <div class="alert alert-warning awe-rt-ListingClosedMessage awe-hidden">
            Bidding has ended on this item.
        </div>
        <span class="detail__status-label">
            <span class="label label-info">Active</span>
        </span>
        <span class="awe-rt-endingDTTM" data-initial-dttm="07/05/2026 19:10:00"></span>
        """
    )

    assert item["auction_status"] == "active"
    assert item["auction_end_date"] == "2026-07-05T19:10:00"


def test_visible_closed_message_marks_listing_ended():
    item = parse_item(
        """
        <h1>Ended LEGO Lot</h1>
        <div class="alert alert-warning awe-rt-ListingClosedMessage">
            Bidding has ended on this item.
        </div>
        <span class="detail__status-label">
            <span class="label label-default">Ended</span>
        </span>
        """
    )

    assert item["auction_status"] == "ended"


def test_long_description_is_not_truncated_and_keeps_trailing_spec_fields():
    # Listings put their structured spec fields at the END of the description,
    # so any parser-side truncation silently destroys the Model:/Includes: data.
    filler = "LEGO Technic set in sealed retail packaging. " * 20
    spec_tail = (
        "Brand:LEGO"
        "Model:Technic Car Lot (42169, 42151, 42173)"
        "Includes:LEGO Technic NEOM McLaren Formula E Team (42169)"
        "Condition:New"
    )
    item = parse_item(
        f"""
        <h1>LEGO Technic Lot</h1>
        <div class="detail__description">{filler}{spec_tail}</div>
        """
    )

    description = item["description"]
    assert description == f"{filler}{spec_tail}".strip()
    assert len(description) > 500
    assert "Model:Technic Car Lot (42169, 42151, 42173)" in description
    assert description.endswith("Condition:New")


# Verbatim <h1> subtree captured from
# https://www.shopthesalvationarmy.com/Listing/Details/562200044 with the
# client's own User-Agent. The watchlist controls are rendered INSIDE the
# heading, so a naive h1.get_text() appends their button labels to the title.
REAL_DETAIL_TITLE_H1 = """
<h1 class="detail__title">
    <span>Bulk LEGO Building Pieces &#8211; 35 lb Assorted Box [A71]</span>
    <a class="awe-refresh-alert awe-hidden" onclick="location.reload(true);"
       title="This listing has been edited since the page was last loaded.">
        <small class="glyphicon glyphicon-alert text-danger"></small>
    </a>
    <span class="addOrRemoveWatchlist" data-iswatching="False" data-watch-listingid="562200044">
        <button class="awe-rt-hideable awe-rt-ShowStatusActive btn btn-default btn-xs">
            <img class="icon__button--watchList" src="/Content/Images/bookmark-plus.svg"/>
            <span class="watchText__notWatching">Add to Watch List</span>
            <span class="watchText__isWatching">Watching</span>
        </button>
    </span>
    <a class="goToWatchListLink" href="/Account/Bidding/Watching">View Watchlist &gt;</a>
</h1>
"""


def test_detail_title_excludes_watchlist_control_text():
    # Consumers (e.g. LegoScout) match LEGO listings on this title, so trailing
    # UI text is a real matching hazard, not a cosmetic issue.
    item = parse_item(REAL_DETAIL_TITLE_H1)

    assert item["title"] == "Bulk LEGO Building Pieces – 35 lb Assorted Box [A71]"
    assert "Add to Watch List" not in item["title"]
    assert "Watching" not in item["title"]
    assert "View Watchlist" not in item["title"]


def test_detail_title_parse_does_not_mutate_the_caller_soup():
    # The controls are stripped from a detached copy; the rest of the parse and
    # any caller-side inspection must still see the original document.
    soup = BeautifulSoup(REAL_DETAIL_TITLE_H1, "html.parser")
    client = ShopSalvationArmyClient(require_auth=False, config=object())

    client._parse_item_page(soup, "562200044")

    assert soup.select_one(".addOrRemoveWatchlist") is not None
    assert soup.select_one(".goToWatchListLink") is not None


def test_detail_title_keeps_plain_heading_text_intact():
    item = parse_item("<h1 class='detail__title'><span>LEGO Technic Lot [B12]</span></h1>")

    assert item["title"] == "LEGO Technic Lot [B12]"


def test_search_commands_are_public_no_auth_commands():
    assert COMMAND_CREDENTIALS == {
        "categories": ["no_auth"],
        "get": ["no_auth"],
        "query": ["no_auth"],
    }


# Every fixture below mirrors the live markup of
# https://www.shopthesalvationarmy.com/Listing/Details/<id>: a `div.panel`
# wrapping a `div.panel-heading` of "Shipping Options" and a `ul.list-group`
# whose rows put the label and its price either side of a `</strong>`.
CALCULATOR_PANEL = """
        <div class="panel panel-default">
            <div class="panel-heading">Shipping Options</div>
            <ul class="list-group">
                <li class="list-group-item"><strong>Local Pick Up:</strong>&nbsp;&nbsp;$0.00</li>
                <li class="list-group-item">
                    <a href="#" class="btn btn-primary ct" data-carrier="USPS">Calculate USPS Shipping Rates</a>
                </li>
                <li class="list-group-item">
                    <a href="#" class="btn btn-primary ct" data-carrier="UPS">Calculate UPS Shipping Rates</a>
                </li>
            </ul>
        </div>
        <input type="hidden" id="fromPostalCode" value="90404" />
        <input type="hidden" id="weight" value="38.00000000000000" />
        <input type="hidden" id="length" value="24.00000000000000" />
        <input type="hidden" id="width" value="16.00000000000000" />
        <input type="hidden" id="height" value="21.00000000000000" />
        <input type="hidden" id="listingId" value="123" />
"""

# Listing 562200044: a flat shipping price quoted on the page, no calculator.
FLAT_RATE_PANEL = """
        <div class="panel panel-default">
            <div class="panel-heading">Shipping Options</div>
            <ul class="list-group">
                <li class="list-group-item"><strong>Local Pick Up:</strong>&nbsp;&nbsp;$0.00</li>
                <li class="list-group-item">
                    <strong>Standard Shipping:</strong>&nbsp;&nbsp;$46.00
                    <span class="small">($46.00 as additional item)</span>
                </li>
            </ul>
        </div>
"""


def test_should_parse_current_price_and_destination_required_shipping_fields():
    item = parse_item(
        f"""
        <h1>Active LEGO Lot</h1>
        <span class="detail__status-label">
            <span class="label label-info">Active</span>
        </span>
        <span class="detail__price--current Bidding_Current_Price awe-rt-CurrentPrice">
            $<span class="NumberPart">42.00</span>
        </span>
        {CALCULATOR_PANEL}
        <script>var ac = parseFloat("2.99");</script>
        """
    )

    assert item["current_price"] == 42.0
    assert item["local_pickup_price"] == 0.0
    assert item["shipping_additional_charge"] == 2.99
    assert item["shipping_quote_status"] == "destination_required"
    assert item["shipping_cost"] is None
    assert item["handling_cost"] is None
    assert item["shipping_total"] is None
    assert item["total_price"] is None
    assert item["shipping_options"] == {
        "local_pickup": True,
        "flat_rate": False,
        "carrier_calculator": True,
    }
    assert item["shipping_carriers"] == ["usps", "ups"]
    assert item["standard_shipping_price"] is None
    assert item["standard_shipping_label"] is None
    # shipping_params is only the live-quote request payload; the carrier list
    # is NOT carried here, so a failed quote cannot take it down with it.
    assert item["shipping_params"] == {
        "from_postal_code": "90404",
        "weight": "38.00000000000000",
        "length": "24.00000000000000",
        "width": "16.00000000000000",
        "height": "21.00000000000000",
        "listing_id": "123",
    }


def test_flat_standard_shipping_line_is_parsed_as_an_offered_option():
    # Listing 562200044 quotes a flat $46.00 right on the page and offers no
    # calculator. Dropping that line made the listing read as pickup-only.
    item = parse_item(f"<h1>LEGO Lot</h1>{FLAT_RATE_PANEL}")

    assert item["shipping_options"] == {
        "local_pickup": True,
        "flat_rate": True,
        "carrier_calculator": False,
    }
    assert item["local_pickup_price"] == 0.0
    assert item["standard_shipping_label"] == "Standard Shipping"
    assert item["standard_shipping_price"] == 46.0
    assert item["standard_shipping_additional_item_price"] == 46.0
    assert item["shipping_carriers"] == []
    assert item["shipping_params"] is None
    # No live-rate calculator exists here, so there is no quote to be missing.
    assert item["shipping_quote_status"] == "not_applicable"


def test_flat_rate_label_is_read_from_the_page_not_assumed():
    # Listing 562767137 labels the same row "UPS Ground:", so the flat rate
    # cannot be keyed off the literal string "Standard Shipping".
    item = parse_item(
        """
        <h1>LEGO Lot</h1>
        <div class="panel panel-default">
            <div class="panel-heading">Shipping Options</div>
            <ul class="list-group">
                <li class="list-group-item"><strong>Local Pick Up:</strong>&nbsp;&nbsp;$0.00</li>
                <li class="list-group-item"><strong>UPS Ground:</strong>&nbsp;&nbsp;$39.99</li>
            </ul>
        </div>
        """
    )

    assert item["shipping_options"]["flat_rate"] is True
    assert item["standard_shipping_label"] == "UPS Ground"
    assert item["standard_shipping_price"] == 39.99
    assert item["standard_shipping_additional_item_price"] is None


def test_pickup_only_listing_reports_no_shipping_option():
    item = parse_item(
        """
        <h1>LEGO Lot</h1>
        <div class="panel panel-default">
            <div class="panel-heading">Shipping Options</div>
            <ul class="list-group">
                <li class="list-group-item"><strong>Local Pick Up:</strong>&nbsp;&nbsp;$0.00</li>
            </ul>
        </div>
        """
    )

    assert item["shipping_options"] == {
        "local_pickup": True,
        "flat_rate": False,
        "carrier_calculator": False,
    }
    assert item["standard_shipping_price"] is None
    assert item["shipping_carriers"] == []
    assert item["shipping_quote_status"] == "not_applicable"


def test_carriers_survive_a_missing_quote_payload():
    # The calculator buttons prove shipping is offered. When the hidden quote
    # inputs are absent the RATE is unknown -- the listing must not collapse to
    # "seller does not ship".
    item = parse_item(f"<h1>LEGO Lot</h1>{CALCULATOR_PANEL.split('<input')[0]}")

    assert item["shipping_params"] is None
    assert item["shipping_carriers"] == ["usps", "ups"]
    assert item["shipping_options"]["carrier_calculator"] is True
    assert item["shipping_quote_status"] == "unavailable"


def test_listing_without_a_shipping_panel_reports_no_options():
    item = parse_item("<h1>LEGO Lot</h1>")

    assert item["shipping_options"] == {
        "local_pickup": False,
        "flat_rate": False,
        "carrier_calculator": False,
    }
    assert item["local_pickup_price"] is None
    assert item["standard_shipping_price"] is None
    assert item["shipping_carriers"] == []
    assert item["shipping_quote_status"] == "not_applicable"


def test_shipping_panel_parse_ignores_list_groups_outside_the_panel():
    # Detail pages carry other `ul.list-group` blocks (bid history, seller
    # info). Only the Shipping Options panel may feed the fulfillment summary.
    item = parse_item(
        f"""
        <h1>LEGO Lot</h1>
        <div class="panel panel-default">
            <div class="panel-heading">Payment Options</div>
            <ul class="list-group">
                <li class="list-group-item"><strong>Handling Fee:</strong>&nbsp;&nbsp;$9.99</li>
            </ul>
        </div>
        {FLAT_RATE_PANEL}
        """
    )

    assert item["standard_shipping_label"] == "Standard Shipping"
    assert item["standard_shipping_price"] == 46.0


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class FakeGetSession:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return FakeResponse("")


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, json, timeout):
        self.posts.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            '"[{\\"serviceName\\":\\"USPS Ground Advantage - Package\\",'
            '\\"serviceCode\\":\\"usps_ground_advantage\\",'
            '\\"shipmentCost\\":25.25,\\"otherCost\\":4.75}]"'
        )


def test_should_calculate_shipping_rates_from_internal_realtime_endpoint():
    client = ShopSalvationArmyClient(require_auth=False, config=object())
    client.session = FakeSession()

    rates = client.calculate_shipping(
        item_id="123",
        zip_code="10001",
        state="NY",
        city="New York",
        country="US",
        carrier="usps",
        shipping_params={
            "from_postal_code": "90404",
            "weight": "38.00000000000000",
            "length": "24.00000000000000",
            "width": "16.00000000000000",
            "height": "21.00000000000000",
            "listing_id": "123",
        },
    )

    assert rates == [
        {
            "serviceName": "USPS Ground Advantage - Package",
            "serviceCode": "usps_ground_advantage",
            "shipmentCost": 25.25,
            "otherCost": 4.75,
        }
    ]
    assert client.session.posts == [
        {
            "url": "https://www.shopthesalvationarmy.com/RealTime/GetLiveRates",
            "json": {
                "carrier": "usps",
                "weight": "38.00000000000000",
                "length": "24.00000000000000",
                "width": "16.00000000000000",
                "height": "21.00000000000000",
                "fromPostalCode": "90404",
                "toState": "NY",
                "toCountry": "US",
                "toPostalCode": "10001",
                "toCity": "New York",
                "listingId": "123",
            },
            "timeout": 30,
        }
    ]


def test_search_uses_site_full_text_query_parameter():
    client = ShopSalvationArmyClient(require_auth=False, config=object())
    client.session = FakeGetSession()

    result = client.search(query="Canon camera", price_max=50)

    assert len(client.session.urls) == 1
    requested_url = client.session.urls[0]
    assert "FullTextQuery=Canon+camera" in requested_url
    assert "Keywords=" not in requested_url
    assert result["url"] == requested_url
