from bs4 import BeautifulSoup

from shopsalvationarmy_cli.client import ShopSalvationArmyClient
from shopsalvationarmy_cli.commands.search import COMMAND_CREDENTIALS


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


def test_search_commands_are_public_no_auth_commands():
    assert COMMAND_CREDENTIALS == {
        "categories": ["no_auth"],
        "get": ["no_auth"],
        "query": ["no_auth"],
    }


def test_should_parse_current_price_and_destination_required_shipping_fields():
    item = parse_item(
        """
        <h1>Active LEGO Lot</h1>
        <span class="detail__status-label">
            <span class="label label-info">Active</span>
        </span>
        <span class="detail__price--current Bidding_Current_Price awe-rt-CurrentPrice">
            $<span class="NumberPart">42.00</span>
        </span>
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
        <input type="hidden" id="fromPostalCode" value="90404" />
        <input type="hidden" id="weight" value="38.00000000000000" />
        <input type="hidden" id="length" value="24.00000000000000" />
        <input type="hidden" id="width" value="16.00000000000000" />
        <input type="hidden" id="height" value="21.00000000000000" />
        <input type="hidden" id="listingId" value="123" />
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
    assert item["shipping_params"] == {
        "from_postal_code": "90404",
        "weight": "38.00000000000000",
        "length": "24.00000000000000",
        "width": "16.00000000000000",
        "height": "21.00000000000000",
        "listing_id": "123",
        "carriers": ["usps", "ups"],
    }


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


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
