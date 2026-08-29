"""Tests for `shippo pickups create` and the Pickup model factory."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

import pytest
import typer
from typer.testing import CliRunner

import shippo_cli.commands.pickups as pickups_module
from shippo_cli.commands.pickups import app as pickups_app
from shippo_cli.models import Pickup, create_pickup


runner = CliRunner()

# Mirror the real mount (main.py registers the group under "pickups") so the
# subcommand name is exercised rather than Typer's single-command collapse.
app = typer.Typer()
app.add_typer(pickups_app, name="pickups")


class StubConfig:
    """Config double supplying FROM_* defaults."""

    def __init__(self, **overrides):
        defaults = {
            "from_name": "Adam Bertram",
            "from_company": "LEGO Seller Assistant",
            "from_street1": "123 Main St",
            "from_city": "Fishers",
            "from_state": "IN",
            "from_zip": "46037",
            "from_country": "US",
            "from_phone": "3175551234",
            "from_email": "seller@example.com",
        }
        defaults.update(overrides)
        for key, value in defaults.items():
            setattr(self, key, value)


class StubClient:
    """Client double recording the create_pickup call."""

    def __init__(self, pickup):
        self.pickup = pickup
        self.calls = []

    def create_pickup(self, **kwargs):
        self.calls.append(kwargs)
        return self.pickup


def make_pickup(**overrides) -> Pickup:
    fields = {
        "object_id": "pickup_123",
        "carrier_account": "carrier_acct_1",
        "transactions": ["txn_1"],
        "status": "CONFIRMED",
        "confirmation_code": "CONF-9",
        "confirmed_start_time": "2026-08-29T10:00:00-04:00",
        "confirmed_end_time": "2026-08-29T16:00:00-04:00",
        "cancel_by_time": "2026-08-29T09:00:00-04:00",
    }
    fields.update(overrides)
    return Pickup(**fields)


@pytest.fixture
def stub_env(monkeypatch):
    """Install stub client/config and return the client double."""

    def _install(pickup=None, config=None):
        client = StubClient(pickup if pickup is not None else make_pickup())
        monkeypatch.setattr(pickups_module, "get_client", lambda: client)
        monkeypatch.setattr(
            pickups_module, "get_config", lambda: config if config is not None else StubConfig()
        )
        return client

    return _install


BASE_ARGS = [
    "pickups", "create",
    "--carrier-account", "carrier_acct_1",
    "--transaction", "txn_1",
    "--start", "2026-08-29T10:00:00",
    "--end", "2026-08-29T16:00:00",
]


def test_create_passes_arguments_through_to_client(stub_env):
    client = stub_env()

    result = runner.invoke(
        app,
        BASE_ARGS + ["--transaction", "txn_2", "--location-type", "Side Door", "--building-type", "suite"],
    )

    assert result.exit_code == 0, result.output
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["carrier_account"] == "carrier_acct_1"
    assert call["transactions"] == ["txn_1", "txn_2"]
    assert call["building_location_type"] == "Side Door"
    assert call["building_type"] == "suite"
    # Naive input picks up the local offset so Shippo gets an unambiguous instant.
    assert call["requested_start_time"].tzinfo is not None
    assert call["requested_end_time"].tzinfo is not None
    assert call["requested_start_time"] < call["requested_end_time"]
    assert call["address"] == {
        "name": "Adam Bertram",
        "company": "LEGO Seller Assistant",
        "street1": "123 Main St",
        "street2": None,
        "city": "Fishers",
        "state": "IN",
        "zip": "46037",
        "country": "US",
        "phone": "3175551234",
        "email": "seller@example.com",
    }


def test_transaction_ids_pass_through_regardless_of_service_level(stub_env):
    """No client-side USPS service-eligibility filtering.

    The USPS restriction (Priority Mail Express / Priority Mail / international /
    return only) does not apply to DHL Express, so transaction IDs must reach
    the client unchanged and let Shippo decide.
    """
    client = stub_env()

    result = runner.invoke(
        app,
        [
            "pickups", "create",
            "--carrier-account", "dhl_express_acct",
            "--transaction", "txn_dhl_express_worldwide",
            "--transaction", "txn_usps_ground_advantage",
            "--transaction", "txn_usps_first_class",
            "--start", "2026-08-29T10:00:00",
            "--end", "2026-08-29T16:00:00",
        ],
    )

    assert result.exit_code == 0, result.output
    assert client.calls[0]["transactions"] == [
        "txn_dhl_express_worldwide",
        "txn_usps_ground_advantage",
        "txn_usps_first_class",
    ]


def test_no_transactions_fails(stub_env):
    client = stub_env()

    result = runner.invoke(
        app,
        [
            "pickups", "create",
            "--carrier-account", "carrier_acct_1",
            "--start", "2026-08-29T10:00:00",
            "--end", "2026-08-29T16:00:00",
        ],
    )

    assert result.exit_code != 0
    assert "--transaction" in result.output
    assert client.calls == []


def test_end_before_or_equal_start_fails(stub_env):
    client = stub_env()

    result = runner.invoke(
        app,
        [
            "pickups", "create",
            "--carrier-account", "carrier_acct_1",
            "--transaction", "txn_1",
            "--start", "2026-08-29T16:00:00",
            "--end", "2026-08-29T16:00:00",
        ],
    )

    assert result.exit_code != 0
    assert "--end must be after --start" in result.output
    assert client.calls == []


def test_unparseable_start_fails(stub_env):
    client = stub_env()

    result = runner.invoke(
        app,
        [
            "pickups", "create",
            "--carrier-account", "carrier_acct_1",
            "--transaction", "txn_1",
            "--start", "tomorrow morning",
            "--end", "2026-08-29T16:00:00",
        ],
    )

    assert result.exit_code != 0
    assert "--start" in result.output
    assert "tomorrow morning" in result.output
    assert client.calls == []


def test_other_location_type_requires_instructions(stub_env):
    client = stub_env()

    result = runner.invoke(app, BASE_ARGS + ["--location-type", "Other"])

    assert result.exit_code != 0
    assert "--instructions is required" in result.output
    assert client.calls == []


def test_other_location_type_with_instructions_succeeds(stub_env):
    client = stub_env()

    result = runner.invoke(
        app,
        BASE_ARGS + ["--location-type", "Other", "--instructions", "Behind the blue gate"],
    )

    assert result.exit_code == 0, result.output
    assert client.calls[0]["instructions"] == "Behind the blue gate"


def test_invalid_location_type_lists_valid_values(stub_env):
    client = stub_env()

    result = runner.invoke(app, BASE_ARGS + ["--location-type", "Garage"])

    assert result.exit_code != 0
    assert "Garage" in result.output
    assert "Front Door" in result.output
    assert "Shipping Dock" in result.output
    assert client.calls == []


def test_invalid_building_type_lists_valid_values(stub_env):
    client = stub_env()

    result = runner.invoke(app, BASE_ARGS + ["--building-type", "castle"])

    assert result.exit_code != 0
    assert "castle" in result.output
    assert "apartment" in result.output
    assert client.calls == []


def test_missing_from_address_fields_names_missing_keys(stub_env):
    client = stub_env(config=StubConfig(from_name=None, from_city=None, from_zip=None))

    result = runner.invoke(app, BASE_ARGS)

    assert result.exit_code != 0
    assert "FROM_NAME" in result.output
    assert "FROM_CITY" in result.output
    assert "FROM_ZIP" in result.output
    assert client.calls == []


def test_error_status_response_exits_non_zero_and_reports_every_message(stub_env):
    """A 201 carrying status ERROR is a failure, not a success."""
    stub_env(
        pickup=make_pickup(
            status="ERROR",
            confirmation_code=None,
            confirmed_start_time=None,
            confirmed_end_time=None,
            cancel_by_time=None,
            messages=[
                "Company name is required for pickup",
                "Pickup date must be today or tomorrow",
            ],
        )
    )

    result = runner.invoke(app, BASE_ARGS)

    assert result.exit_code == 1
    assert "Company name is required for pickup" in result.output
    assert "Pickup date must be today or tomorrow" in result.output


def test_error_status_without_messages_still_exits_non_zero(stub_env):
    stub_env(pickup=make_pickup(status="ERROR", messages=None))

    result = runner.invoke(app, BASE_ARGS)

    assert result.exit_code == 1
    assert "ERROR" in result.output


def test_confirmed_pickup_reports_confirmation_details(stub_env):
    stub_env()

    result = runner.invoke(app, BASE_ARGS)

    assert result.exit_code == 0, result.output
    assert "CONF-9" in result.output
    assert "cannot retrieve or cancel" in result.output


# ---------------------------------------------------------------------------
# create_pickup() factory
# ---------------------------------------------------------------------------


class StubPickupStatus(Enum):
    CONFIRMED = "CONFIRMED"


class StubBuildingLocationType(Enum):
    FRONT_DOOR = "Front Door"


@dataclass
class StubSdkAddress:
    name: str
    company: Optional[str]
    street1: str
    street2: Optional[str]
    city: str
    state: str
    zip: str
    country: str
    phone: Optional[str]
    email: Optional[str]


@dataclass
class StubSdkLocation:
    address: StubSdkAddress
    building_location_type: Any
    building_type: Any
    instructions: Optional[str]


@dataclass
class StubSdkPickup:
    object_id: str
    carrier_account: str
    location: StubSdkLocation
    transactions: List[str]
    requested_start_time: datetime
    requested_end_time: datetime
    confirmed_start_time: datetime
    confirmed_end_time: datetime
    cancel_by_time: datetime
    status: Any
    confirmation_code: str
    timezone: str
    messages: Optional[List[str]]
    metadata: Optional[str]
    is_test: bool
    object_created: datetime
    object_updated: datetime


def test_create_pickup_factory_converts_sdk_dataclass():
    start = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)

    sdk_pickup = StubSdkPickup(
        object_id="pickup_abc",
        carrier_account="carrier_acct_1",
        location=StubSdkLocation(
            address=StubSdkAddress(
                name="Adam Bertram",
                company="LEGO Seller Assistant",
                street1="123 Main St",
                street2=None,
                city="Fishers",
                state="IN",
                zip="46037",
                country="US",
                phone="3175551234",
                email="seller@example.com",
            ),
            building_location_type=StubBuildingLocationType.FRONT_DOOR,
            building_type=None,
            instructions=None,
        ),
        transactions=["txn_1", "txn_2"],
        requested_start_time=start,
        requested_end_time=end,
        confirmed_start_time=start,
        confirmed_end_time=end,
        cancel_by_time=start,
        status=StubPickupStatus.CONFIRMED,
        confirmation_code="CONF-9",
        timezone="America/Indiana/Indianapolis",
        messages=None,
        metadata="order 123",
        is_test=True,
        object_created=start,
        object_updated=end,
    )

    pickup = create_pickup(sdk_pickup)

    assert pickup.object_id == "pickup_abc"
    assert pickup.status == "CONFIRMED"
    assert pickup.transactions == ["txn_1", "txn_2"]
    assert pickup.requested_start_time == start.isoformat()
    assert pickup.requested_end_time == end.isoformat()
    assert pickup.confirmed_start_time == start.isoformat()
    assert pickup.cancel_by_time == start.isoformat()
    assert pickup.object_created == start.isoformat()
    assert pickup.object_updated == end.isoformat()
    assert pickup.is_test is True
    assert pickup.location is not None
    assert pickup.location.address is not None
    assert pickup.location.address.company == "LEGO Seller Assistant"
    assert pickup.location.building_location_type == "Front Door"
