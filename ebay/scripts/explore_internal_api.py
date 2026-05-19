#!/usr/bin/env python3
"""
Experimental script to explore eBay's internal listing APIs.

This attempts to reverse-engineer the internal endpoints used by Seller Hub
to create and manage drafts. These are INTERNAL APIs and are NOT officially
supported - they may break at any time.

Usage:
    python scripts/explore_internal_api.py

Requires: The ebay CLI to be authenticated (run 'ebay auth login' first)
"""

import json
import sys
import uuid
from pathlib import Path

import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ebay_cli.config import get_config


class EbayInternalClient:
    """Client for exploring eBay's internal listing APIs."""

    def __init__(self):
        self.config = get_config()
        if not self.config.access_token:
            raise RuntimeError("Not authenticated. Run 'ebay auth login' first.")

        # Internal APIs use www.ebay.com, not api.ebay.com
        self.base_url = "https://www.ebay.com"

        # Generate a tracking ID like the browser does
        self.tracking_id = str(uuid.uuid4())

        self.headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Origin": "https://www.ebay.com",
            "Referer": "https://www.ebay.com/sl/prelist/home",
        }

    def _make_request(self, method: str, url: str, **kwargs) -> dict:
        """Make an HTTP request and return parsed response."""
        print(f"\n{'='*60}")
        print(f"{method} {url}")
        if kwargs.get("params"):
            print(f"Params: {kwargs['params']}")
        if kwargs.get("json"):
            print(f"Body: {json.dumps(kwargs['json'], indent=2)}")

        response = requests.request(method, url, headers=self.headers, **kwargs)

        print(f"\nStatus: {response.status_code}")

        try:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)[:3000]}")
            return {"status": response.status_code, "data": data}
        except Exception:
            print(f"Response (raw): {response.text[:1000]}")
            return {"status": response.status_code, "raw": response.text}

    def prelist_suggest(self, keyword: str) -> dict:
        """Get keyword suggestions and category info."""
        url = f"{self.base_url}/sl/prelist/api/suggest"
        params = {
            "keyword": keyword,
            "radixTrackingId": self.tracking_id,
        }
        return self._make_request("GET", url, params=params)

    def prelist_identify(self, title: str, category_id: str, category_path: list) -> dict:
        """Navigate to the identify page (find matching products)."""
        url = f"{self.base_url}/sl/prelist/identify"
        params = {
            "sr": "sug",
            "title": title,
            "caty": category_id,
            "isUid": "false",
            "radixTrackingId": self.tracking_id,
        }
        # Add category path
        for cat_id in category_path:
            params.setdefault("catyIdPath[]", []).append(cat_id)

        return self._make_request("GET", url, params=params)

    def prelist_beacon(self, data: dict) -> dict:
        """Send a beacon event (used for tracking/state)."""
        url = f"{self.base_url}/sl/prelist/api/beacon"
        return self._make_request("POST", url, json=data)

    def lstng_init(self, title: str, category_id: str, condition: str) -> dict:
        """Try to initialize a listing draft via /lstng endpoint."""
        # This is what the browser navigates to after prelist
        url = f"{self.base_url}/lstng"
        params = {
            "mode": "AddItem",
            "radixTrackingId": self.tracking_id,
        }
        # The actual draft creation might happen server-side when visiting this URL
        # Let's try to simulate that by calling potential API endpoints

        return self._make_request("GET", url, params=params)

    def try_lstng_gql_with_srt(self) -> dict:
        """
        Try GraphQL with a simulated SRT token.
        The browser includes an 'srt' parameter which might be a session token.
        """
        url = f"{self.base_url}/lstng/gql"

        # Try different queries that might exist
        queries = [
            {
                "operationName": "GetListingDraft",
                "query": "query GetListingDraft { listingDraft { id title } }",
            },
            {
                "operationName": "InitializeDraft",
                "query": "mutation InitializeDraft($input: InitDraftInput!) { initializeDraft(input: $input) { draftId } }",
                "variables": {"input": {"categoryId": "183448", "title": "Test"}},
            },
            {
                "operationName": "CreateDraft",
                "query": "mutation CreateDraft { createDraft { id } }",
            },
        ]

        results = []
        for query in queries:
            result = self._make_request("POST", url, json=query)
            results.append(result)

        return results

    def explore_prelist_flow(self):
        """Explore the full prelist flow that the browser uses."""
        print("\n" + "#" * 60)
        print("# STEP 1: Get keyword suggestions")
        print("#" * 60)

        suggest_result = self.prelist_suggest("LEGO bulk lot")

        if suggest_result.get("status") == 200:
            data = suggest_result.get("data", {})
            metadata = data.get("modules", {}).get("KEYWORDMETADATA", {})
            category_id = metadata.get("categoryId", "183448")
            category_path = metadata.get("defaultCategoryIdPath", [])

            print(f"\nExtracted category: {category_id}")
            print(f"Category path: {category_path}")

        print("\n" + "#" * 60)
        print("# STEP 2: Try direct /lstng initialization")
        print("#" * 60)

        # Try the lstng endpoint
        self.lstng_init("Test LEGO Bulk", "183448", "USED")

        print("\n" + "#" * 60)
        print("# STEP 3: Try GraphQL variants")
        print("#" * 60)

        self.try_lstng_gql_with_srt()

    def try_trading_api_draft(self):
        """
        Try using the Trading API to create a draft listing.
        The VerifyAddItem call can validate a listing without posting it.
        """
        print("\n" + "#" * 60)
        print("# TRADING API: VerifyAddItem (validates without listing)")
        print("#" * 60)

        # Trading API endpoint
        url = f"https://api.ebay.com/ws/api.dll"

        xml_request = """<?xml version="1.0" encoding="utf-8"?>
<VerifyAddItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <Item>
        <Title>Test LEGO Bulk Lot - API Test</Title>
        <Description>Test description for bulk LEGO lot.</Description>
        <PrimaryCategory>
            <CategoryID>183448</CategoryID>
        </PrimaryCategory>
        <StartPrice>9.99</StartPrice>
        <ConditionID>3000</ConditionID>
        <Country>US</Country>
        <Currency>USD</Currency>
        <DispatchTimeMax>3</DispatchTimeMax>
        <ListingDuration>Days_7</ListingDuration>
        <ListingType>Chinese</ListingType>
        <PaymentMethods>PayPal</PaymentMethods>
        <PayPalEmailAddress>test@test.com</PayPalEmailAddress>
        <Quantity>1</Quantity>
    </Item>
</VerifyAddItemRequest>"""

        headers = {
            "X-EBAY-API-IAF-TOKEN": self.config.access_token,
            "X-EBAY-API-CALL-NAME": "VerifyAddItem",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "Content-Type": "text/xml",
        }

        print(f"\nPOST {url}")
        print(f"Call: VerifyAddItem")

        response = requests.post(url, headers=headers, data=xml_request)

        print(f"\nStatus: {response.status_code}")
        print(f"Response: {response.text[:2000]}")

        return response

    def try_add_item_with_listing_type_draft(self):
        """
        Try AddItem with various flags that might create a draft.
        """
        print("\n" + "#" * 60)
        print("# TRADING API: AddItem with ScheduleTime (future = draft-like)")
        print("#" * 60)

        # Using ScheduleTime far in the future creates a "scheduled" listing
        # which is similar to a draft
        from datetime import datetime, timedelta

        # Schedule 7 days from now
        schedule_time = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        url = "https://api.ebay.com/ws/api.dll"

        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <Item>
        <Title>Test LEGO Bulk Lot - Scheduled API Test</Title>
        <Description>Test description for bulk LEGO lot created via API.</Description>
        <PrimaryCategory>
            <CategoryID>183448</CategoryID>
        </PrimaryCategory>
        <StartPrice>9.99</StartPrice>
        <ConditionID>3000</ConditionID>
        <Country>US</Country>
        <Currency>USD</Currency>
        <DispatchTimeMax>3</DispatchTimeMax>
        <ListingDuration>Days_7</ListingDuration>
        <ListingType>Chinese</ListingType>
        <Quantity>1</Quantity>
        <ScheduleTime>{schedule_time}</ScheduleTime>
        <ShippingDetails>
            <ShippingType>Flat</ShippingType>
            <ShippingServiceOptions>
                <ShippingServicePriority>1</ShippingServicePriority>
                <ShippingService>USPSPriority</ShippingService>
                <ShippingServiceCost>5.99</ShippingServiceCost>
            </ShippingServiceOptions>
        </ShippingDetails>
        <ReturnPolicy>
            <ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption>
        </ReturnPolicy>
    </Item>
</AddItemRequest>"""

        headers = {
            "X-EBAY-API-IAF-TOKEN": self.config.access_token,
            "X-EBAY-API-CALL-NAME": "AddItem",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1349",
            "Content-Type": "text/xml",
        }

        print(f"\nPOST {url}")
        print(f"Call: AddItem (Scheduled for {schedule_time})")

        response = requests.post(url, headers=headers, data=xml_request)

        print(f"\nStatus: {response.status_code}")
        print(f"Response: {response.text[:2000]}")

        return response


def main():
    print("=" * 60)
    print("eBay Internal API Explorer v2")
    print("=" * 60)
    print("\nAttempting to find a way to create drafts via API...")
    print()

    try:
        client = EbayInternalClient()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Explore the prelist flow
    client.explore_prelist_flow()

    # Try Trading API approaches
    client.try_trading_api_draft()

    # Note: Uncommenting this will actually create a scheduled listing!
    # client.try_add_item_with_listing_type_draft()

    print("\n" + "=" * 60)
    print("EXPLORATION COMPLETE")
    print("=" * 60)
    print("""
Findings:
1. Internal GraphQL (/lstng/gql) requires browser session cookies - OAuth alone fails with 503
2. The /sl/prelist/api/suggest endpoint works - it's used for category detection
3. Draft creation happens in the browser session, not via public API

Alternative approaches that DO work via API:
1. VerifyAddItem (Trading API) - Validates a listing without posting
2. AddItem with ScheduleTime - Creates a "scheduled" listing (not a draft, but close)
3. Inventory API offers - Stay as UNPUBLISHED until published (our current approach)

Conclusion:
- Seller Hub drafts are a UI-only feature with NO public API
- The closest alternatives are scheduled listings or Inventory API offers
- eBay Developer Support has confirmed this limitation
""")


if __name__ == "__main__":
    main()
