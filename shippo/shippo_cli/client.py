"""Shippo API client using the official Shippo Python SDK.

This client wraps the Shippo SDK to provide:
- Pydantic model responses for CLI-friendly output
- Limit/filter parameters passed to API level
- Consistent error handling
- Exponential retry with jitter for transient API failures
"""
import random
import time
from typing import Callable, Dict, List, Optional, Any, TypeVar

import shippo
from shippo.models import components, operations

from cli_tools_shared.exceptions import ClientError

T = TypeVar("T")


# HTTP status codes worth retrying
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    """Determine whether an exception from the Shippo SDK is retryable."""
    # httpx and SDK errors that carry a status code
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status and int(status) in RETRYABLE_STATUS_CODES:
        return True
    # Connection / timeout errors from httpx (used by the Shippo SDK)
    exc_name = type(exc).__name__
    if exc_name in ("ConnectError", "TimeoutException", "ReadTimeout", "ConnectTimeout", "PoolTimeout"):
        return True
    return False

from .config import get_config
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from .models import (
    Address,
    Parcel,
    Rate,
    Shipment,
    Transaction,
    TrackingInfo,
    Refund,
    CarrierAccount,
    create_address,
    create_parcel,
    create_rate,
    create_shipment,
    create_transaction,
    create_tracking_info,
    create_refund,
    create_carrier_account,
)


def _apply_model_filters(items, filters):
    """Apply client-side filters to a list of Pydantic models.

    Converts models to dicts, applies filters, then returns matching models.
    """
    if not filters or not items:
        return items
    from pydantic import BaseModel
    dicts = []
    for item in items:
        if isinstance(item, BaseModel):
            dicts.append(item.model_dump())
        else:
            dicts.append(item)
    filtered_dicts = apply_filters(dicts, filters)
    # Return original model objects that match the filtered dicts
    # Use index-based matching since order is preserved
    filtered_set = set(id(d) for d in filtered_dicts)
    result = []
    for item, d in zip(items, dicts):
        if id(d) in filtered_set:
            result.append(item)
    return result


class ShippoClient:
    """Client for interacting with Shippo API using the official SDK."""

    # Retry configuration
    MAX_RETRIES = 3
    BASE_DELAY = 1.0
    MAX_DELAY = 30.0
    JITTER = 0.5

    def __init__(self):
        """Initialize Shippo client from configuration."""
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'shippo auth login' to authenticate."
            )

        # Initialize Shippo SDK client
        self.sdk = shippo.Shippo(api_key_header=self.config.api_key)

    def _retry(self, fn: Callable[[], T], operation: str) -> T:
        """Execute *fn* with exponential backoff and jitter on transient errors.

        Args:
            fn: Zero-argument callable that performs the SDK call.
            operation: Human-readable label used in error messages.

        Returns:
            The value returned by *fn*.

        Raises:
            ClientError: After all retry attempts are exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc) and attempt < self.MAX_RETRIES:
                    delay = min(
                        self.BASE_DELAY * (2 ** attempt) + random.uniform(0, self.JITTER),
                        self.MAX_DELAY,
                    )
                    time.sleep(delay)
                    continue
                break
        raise ClientError(f"Failed to {operation}: {last_exc}")

    # ==================== Address Methods ====================

    def list_addresses(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Address]:
        """
        List addresses from the API.

        Args:
            limit: Maximum number of addresses to return (passed to API)
            filters: Optional filter strings (not yet supported by Shippo API)

        Returns:
            List of Address models
        """
        response = self._retry(
            lambda: self.sdk.addresses.list(results=limit),
            "list addresses",
        )

        addresses = []
        if response and hasattr(response, 'results') and response.results:
            for addr in response.results:
                addresses.append(create_address(addr))

        # Apply client-side filtering
        if filters:
            addresses = _apply_model_filters(addresses, filters)

        return addresses

    def get_address(self, address_id: str) -> Address:
        """
        Get a specific address by ID.

        Args:
            address_id: The Shippo address object ID

        Returns:
            Address model
        """
        response = self._retry(
            lambda: self.sdk.addresses.get(address_id=address_id),
            "get address",
        )
        return create_address(response)

    def create_address(
        self,
        name: str,
        street1: str,
        city: str,
        state: str,
        zip_code: str,
        country: str = "US",
        company: Optional[str] = None,
        street2: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        is_residential: bool = True,
        validate: bool = False,
    ) -> Address:
        """
        Create a new address.

        Args:
            name: Full name
            street1: Street address line 1
            city: City
            state: State/province code
            zip_code: Postal/zip code
            country: Country code (default: US)
            company: Company name
            street2: Street address line 2
            phone: Phone number
            email: Email address
            is_residential: Whether address is residential
            validate: Whether to validate the address

        Returns:
            Created Address model
        """
        request = components.AddressCreateRequest(
            name=name,
            street1=street1,
            city=city,
            state=state,
            zip=zip_code,
            country=country,
            company=company,
            street2=street2,
            phone=phone,
            email=email,
            is_residential=is_residential,
            validate=validate,
        )
        response = self._retry(
            lambda: self.sdk.addresses.create(request=request),
            "create address",
        )
        return create_address(response)

    def validate_address(self, address_id: str) -> Address:
        """
        Validate an existing address.

        Args:
            address_id: The Shippo address object ID

        Returns:
            Address model with validation_results populated
        """
        response = self._retry(
            lambda: self.sdk.addresses.validate(address_id=address_id),
            "validate address",
        )
        return create_address(response)

    # ==================== Shipment Methods ====================

    def list_shipments(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Shipment]:
        """
        List shipments from the API.

        Args:
            limit: Maximum number of shipments to return (passed to API)
            filters: Optional filter strings

        Returns:
            List of Shipment models
        """
        request = operations.ListShipmentsRequest(results=limit)
        response = self._retry(
            lambda: self.sdk.shipments.list(request=request),
            "list shipments",
        )

        shipments = []
        if response and hasattr(response, 'results') and response.results:
            for ship in response.results:
                shipments.append(create_shipment(ship))

        # Apply client-side filtering
        if filters:
            shipments = _apply_model_filters(shipments, filters)

        return shipments

    def get_shipment(self, shipment_id: str) -> Shipment:
        """
        Get a specific shipment by ID.

        Args:
            shipment_id: The Shippo shipment object ID

        Returns:
            Shipment model with rates
        """
        response = self._retry(
            lambda: self.sdk.shipments.get(shipment_id=shipment_id),
            "get shipment",
        )
        return create_shipment(response)

    def create_shipment(
        self,
        # From address fields
        from_name: str,
        from_street1: str,
        from_city: str,
        from_state: str,
        from_zip: str,
        from_country: str = "US",
        from_phone: Optional[str] = None,
        from_email: Optional[str] = None,
        # To address fields
        to_name: str = "",
        to_street1: str = "",
        to_street2: Optional[str] = None,
        to_city: str = "",
        to_state: str = "",
        to_zip: str = "",
        to_country: str = "US",
        to_phone: Optional[str] = None,
        to_email: Optional[str] = None,
        # Parcel fields (with defaults)
        length: float = 7.0,
        width: float = 4.0,
        height: float = 1.0,
        weight: float = 8.0,
        distance_unit: str = "in",
        mass_unit: str = "oz",
        # Customs fields (for international shipments)
        customs_item_description: Optional[str] = None,
        customs_item_value: Optional[float] = None,
        customs_item_quantity: int = 1,
        customs_signer: Optional[str] = None,
        # Options
        async_mode: bool = False,
    ) -> Shipment:
        """
        Create a new shipment and get rates.

        Args:
            from_*: Origin address fields
            to_*: Destination address fields
            length, width, height: Parcel dimensions (default: 7x4x1)
            weight: Parcel weight (default: 8 oz)
            distance_unit: Unit for dimensions (default: in)
            mass_unit: Unit for weight (default: oz)
            customs_item_description: Description of goods (for international)
            customs_item_value: Value of goods in USD (for international)
            customs_item_quantity: Number of items (default: 1)
            customs_signer: Name of person certifying customs info
            async_mode: Whether to create async (default: False)

        Returns:
            Shipment model with rates
        """
        # Build address objects
        address_from = components.AddressCreateRequest(
            name=from_name,
            street1=from_street1,
            city=from_city,
            state=from_state,
            zip=from_zip,
            country=from_country,
            phone=from_phone,
            email=from_email,
        )

        address_to = components.AddressCreateRequest(
            name=to_name,
            street1=to_street1,
            street2=to_street2,
            city=to_city,
            state=to_state,
            zip=to_zip,
            country=to_country,
            phone=to_phone,
            email=to_email,
        )

        # Build parcel
        parcel = components.ParcelCreateRequest(
            length=str(length),
            width=str(width),
            height=str(height),
            weight=str(weight),
            distance_unit=components.DistanceUnitEnum(distance_unit.lower()),
            mass_unit=components.WeightUnitEnum(mass_unit.lower()),
        )

        # Build customs declaration for international shipments
        customs_declaration = None
        is_international = to_country.upper() != from_country.upper()
        if is_international and customs_item_description and customs_item_value:
            customs_item = components.CustomsItemCreateRequest(
                description=customs_item_description,
                quantity=customs_item_quantity,
                net_weight=str(weight),
                mass_unit=components.WeightUnitEnum(mass_unit.lower()),
                value_amount=str(customs_item_value),
                value_currency="USD",
                origin_country=from_country.upper(),
            )
            customs_declaration = components.CustomsDeclarationCreateRequest(
                contents_type=components.CustomsDeclarationContentsTypeEnum.MERCHANDISE,
                non_delivery_option=components.CustomsDeclarationNonDeliveryOptionEnum.RETURN,
                certify=True,
                certify_signer=customs_signer or from_name,
                items=[customs_item],
            )

        # Create shipment request
        request = components.ShipmentCreateRequest(
            address_from=address_from,
            address_to=address_to,
            parcels=[parcel],
            customs_declaration=customs_declaration,
            async_=async_mode,
        )

        response = self._retry(
            lambda: self.sdk.shipments.create(request=request),
            "create shipment",
        )
        return create_shipment(response)

    # ==================== Rate Methods ====================

    def list_rates(
        self,
        shipment_id: str,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Rate]:
        """
        List rates for a shipment.

        Args:
            shipment_id: The Shippo shipment object ID
            limit: Maximum number of rates to return
            filters: Optional filter strings (e.g., "provider:usps")

        Returns:
            List of Rate models
        """
        response = self._retry(
            lambda: self.sdk.rates.list_shipment_rates(
                shipment_id=shipment_id,
                results=limit,
            ),
            "list rates",
        )

        rates = []
        if response and hasattr(response, 'results') and response.results:
            for rate in response.results:
                rates.append(create_rate(rate))

        # Apply client-side filtering if needed
        if filters:
            rates = self._filter_rates(rates, filters)

        return rates

    def _filter_rates(self, rates: List[Rate], filters: List[str]) -> List[Rate]:
        """Apply client-side filtering to rates."""
        filtered = rates
        for f in filters:
            parts = f.split(":")
            if len(parts) >= 2:
                field = parts[0].lower()
                value = parts[1].lower()
                if field == "provider":
                    filtered = [r for r in filtered if r.provider.lower() == value]
                elif field == "service":
                    filtered = [r for r in filtered if r.servicelevel and r.servicelevel.token and value in r.servicelevel.token.lower()]
        return filtered

    def get_rate(self, rate_id: str) -> Rate:
        """
        Get a specific rate by ID.

        Args:
            rate_id: The Shippo rate object ID

        Returns:
            Rate model
        """
        response = self._retry(
            lambda: self.sdk.rates.get(rate_id=rate_id),
            "get rate",
        )
        return create_rate(response)

    # ==================== Transaction (Label) Methods ====================

    def list_transactions(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Transaction]:
        """
        List transactions (labels) from the API.

        Args:
            limit: Maximum number of transactions to return (passed to API)
            filters: Optional filter strings (e.g., "status:success")

        Returns:
            List of Transaction models
        """
        # Build request with filters if provided
        request = operations.ListTransactionsRequest(results=limit)

        # Apply API-level filters
        if filters:
            for f in filters:
                parts = f.split(":")
                if len(parts) >= 2:
                    field = parts[0].lower()
                    value = parts[1]
                    if field == "status":
                        request.object_status = value.upper()
                    elif field == "tracking_status":
                        request.tracking_status = value.upper()

        response = self._retry(
            lambda: self.sdk.transactions.list(request=request),
            "list transactions",
        )

        transactions = []
        if response and hasattr(response, 'results') and response.results:
            for txn in response.results:
                transactions.append(create_transaction(txn))

        # Apply client-side filtering for non-API filter fields
        if filters:
            non_api_filters = []
            for f in filters:
                parts = f.split(":")
                field = parts[0].lower() if parts else ""
                if field not in ("status", "tracking_status"):
                    non_api_filters.append(f)
                if non_api_filters:
                    transactions = _apply_model_filters(transactions, non_api_filters)

        return transactions

    def get_transaction(self, transaction_id: str) -> Transaction:
        """
        Get a specific transaction by ID.

        Args:
            transaction_id: The Shippo transaction object ID

        Returns:
            Transaction model
        """
        response = self._retry(
            lambda: self.sdk.transactions.get(transaction_id=transaction_id),
            "get transaction",
        )
        return create_transaction(response)

    def create_transaction(
        self,
        rate_id: str,
        label_file_type: str = "PDF",
        async_mode: bool = False,
        metadata: Optional[str] = None,
    ) -> Transaction:
        """
        Create a transaction (purchase a label) from a rate.

        Args:
            rate_id: The Shippo rate object ID
            label_file_type: Label format (PDF, PNG, ZPLII)
            async_mode: Whether to create async
            metadata: Optional metadata string

        Returns:
            Transaction model with label URL
        """
        request = components.TransactionCreateRequest(
            rate=rate_id,
            label_file_type=components.LabelFileTypeEnum(label_file_type),
            async_=async_mode,
            metadata=metadata,
        )
        response = self._retry(
            lambda: self.sdk.transactions.create(request=request),
            "create transaction",
        )
        return create_transaction(response)

    # ==================== Refund Methods ====================

    def create_refund(self, transaction_id: str) -> Refund:
        """
        Request a refund for a transaction (void a label).

        Args:
            transaction_id: The Shippo transaction object ID

        Returns:
            Refund model
        """
        response = self._retry(
            lambda: self.sdk.refunds.create(transaction=transaction_id),
            "create refund",
        )
        return create_refund(response)

    # ==================== Tracking Methods ====================

    def get_tracking(
        self,
        tracking_number: str,
        carrier: str = "usps",
    ) -> TrackingInfo:
        """
        Get tracking information for a shipment.

        Args:
            tracking_number: The tracking number
            carrier: Carrier token (default: usps)

        Returns:
            TrackingInfo model
        """
        response = self._retry(
            lambda: self.sdk.tracking_status.get(
                tracking_number=tracking_number,
                carrier=carrier,
            ),
            "get tracking",
        )
        return create_tracking_info(response)

    def register_tracking(
        self,
        tracking_number: str,
        carrier: str = "usps",
        metadata: Optional[str] = None,
    ) -> TrackingInfo:
        """
        Register a tracking number for webhook updates.

        Args:
            tracking_number: The tracking number
            carrier: Carrier token (default: usps)
            metadata: Optional metadata string

        Returns:
            TrackingInfo model
        """
        request = components.TracksRequest(
            tracking_number=tracking_number,
            carrier=carrier,
            metadata=metadata,
        )
        response = self._retry(
            lambda: self.sdk.tracking_status.create(request=request),
            "register tracking",
        )
        return create_tracking_info(response)

    # ==================== Carrier Account Methods ====================

    def list_carrier_accounts(
        self,
        limit: int = 100,
        carrier: Optional[str] = None,
        include_service_levels: bool = False,
        filters: Optional[List[str]] = None,
    ) -> List[CarrierAccount]:
        """
        List carrier accounts configured in the Shippo account.

        Args:
            limit: Maximum number of accounts to return (passed to API)
            carrier: Filter by carrier token (e.g., "usps", "fedex")
            include_service_levels: Include service levels for each account
            filters: Optional filter strings

        Returns:
            List of CarrierAccount models
        """
        request = operations.ListCarrierAccountsRequest(
            results=limit,
            service_levels=include_service_levels,
        )

        # Apply carrier filter at API level if provided
        if carrier:
            try:
                carrier_enum = components.CarriersEnum(carrier.lower())
                request.carrier = carrier_enum
            except ValueError:
                # Invalid carrier token, let API handle it
                pass

        response = self._retry(
            lambda: self.sdk.carrier_accounts.list(request=request),
            "list carrier accounts",
        )

        accounts = []
        if response and hasattr(response, 'results') and response.results:
            for account in response.results:
                accounts.append(create_carrier_account(account))

        # Apply client-side filtering
        if filters:
            accounts = _apply_model_filters(accounts, filters)

        return accounts

    def get_carrier_account(self, account_id: str) -> CarrierAccount:
        """
        Get a specific carrier account by ID.

        Args:
            account_id: The Shippo carrier account object ID

        Returns:
            CarrierAccount model
        """
        response = self._retry(
            lambda: self.sdk.carrier_accounts.get(carrier_account_id=account_id),
            "get carrier account",
        )
        return create_carrier_account(response)


# Module-level client instance - singleton pattern
_client: Optional[ShippoClient] = None


def get_client() -> ShippoClient:
    """Get or create the global Shippo client instance."""
    global _client
    if _client is None:
        _client = ShippoClient()
    return _client
