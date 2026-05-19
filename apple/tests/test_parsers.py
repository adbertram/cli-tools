"""Unit tests for Apple purchase history normalization."""

from __future__ import annotations

from apple_cli.parsers import match_purchase_records, normalize_purchase_batch


def _sample_page_one() -> dict:
    return {
        "batchId": None,
        "nextBatchId": "next-batch-1",
        "query": {
            "batchId": None,
            "dsid": "123456789",
            "dsids": ["123456789"],
            "guid": "",
            "purchaseAmount": "",
            "weborder": "",
            "plis": [],
            "adamIds": [],
        },
        "purchases": [
            {
                "purchaseId": "purchase-1",
                "dsid": "123456789",
                "invoiceAmount": "$14.98",
                "plis": [
                    {
                        "itemId": "item-1",
                        "purchaseId": "purchase-1",
                        "storefrontId": "143441",
                        "adamId": "111",
                        "guid": "guid-1",
                        "title": "Apple One",
                        "amountPaid": "$9.99",
                        "pliDate": "2026-05-15T12:00:00Z",
                        "isFreePurchase": False,
                        "isCredit": False,
                        "localizedContent": {
                            "nameForDisplay": "Apple One",
                            "detailForDisplay": "Premier Plan",
                            "invoiceLine3": "Managed by Apple",
                            "artworkURL": "https://example.test/one.png",
                            "supportURL": "https://example.test/support",
                            "mediaType": "Subscription",
                            "subscriptionCoverageDescription": "May 2026 coverage",
                            "complete": True,
                            "imageType": "icon",
                            "localizedPotsEndOfCommitmentDate": "June 1, 2026",
                        },
                        "subscriptionInfo": "Renews monthly",
                        "lineItemType": "SUBSCRIPTION",
                        "estimatedTotal": "$9.99",
                    },
                    {
                        "itemId": "item-2",
                        "purchaseId": "purchase-1",
                        "storefrontId": "143441",
                        "adamId": "112",
                        "guid": "guid-2",
                        "title": "Bonus App",
                        "amountPaid": "$0.00",
                        "pliDate": "2026-05-15T12:01:00Z",
                        "isFreePurchase": True,
                        "isCredit": False,
                        "localizedContent": {
                            "nameForDisplay": "Bonus App",
                            "detailForDisplay": "Included download",
                            "invoiceLine3": "Included",
                            "artworkURL": "https://example.test/bonus.png",
                            "supportURL": "https://example.test/bonus-support",
                            "mediaType": "App",
                            "subscriptionCoverageDescription": "",
                            "complete": True,
                            "imageType": "icon",
                            "localizedPotsEndOfCommitmentDate": "",
                        },
                        "subscriptionInfo": None,
                        "lineItemType": "APP",
                        "estimatedTotal": "$0.00",
                    },
                    {
                        "itemId": "item-3",
                        "purchaseId": "purchase-1",
                        "storefrontId": "143441",
                        "adamId": "113",
                        "guid": "guid-3",
                        "title": "Movie Rental",
                        "amountPaid": "$4.99",
                        "pliDate": "2026-05-15T12:02:00Z",
                        "isFreePurchase": False,
                        "isCredit": False,
                        "localizedContent": {
                            "nameForDisplay": "Movie Rental",
                            "detailForDisplay": "Sci-Fi Night",
                            "invoiceLine3": "Rental",
                            "artworkURL": "https://example.test/movie.png",
                            "supportURL": "https://example.test/movie-support",
                            "mediaType": "Movie",
                            "subscriptionCoverageDescription": "",
                            "complete": True,
                            "imageType": "poster",
                            "localizedPotsEndOfCommitmentDate": "",
                        },
                        "subscriptionInfo": None,
                        "lineItemType": "MOVIE",
                        "estimatedTotal": "$4.99",
                    },
                ],
                "weborder": "WEB-1",
                "invoiceDate": "2026-05-15T12:05:00Z",
                "purchaseDate": "2026-05-15T12:00:00Z",
                "isPendingPurchase": False,
                "estimatedTotalAmount": "$14.98",
            }
        ],
    }


def _sample_page_two() -> dict:
    return {
        "batchId": "next-batch-1",
        "nextBatchId": "",
        "query": {
            "batchId": "next-batch-1",
            "dsid": "123456789",
            "dsids": ["123456789"],
            "guid": "",
            "purchaseAmount": "",
            "weborder": "",
            "plis": [],
            "adamIds": [],
        },
        "purchases": [
            {
                "purchaseId": "purchase-2",
                "dsid": "123456789",
                "invoiceAmount": "$4.99",
                "plis": [
                    {
                        "itemId": "item-4",
                        "purchaseId": "purchase-2",
                        "storefrontId": "143441",
                        "adamId": "114",
                        "guid": "guid-4",
                        "title": "Refunded App",
                        "amountPaid": "$4.99",
                        "pliDate": "2026-05-10T09:00:00Z",
                        "isFreePurchase": False,
                        "isCredit": True,
                        "localizedContent": {
                            "nameForDisplay": "Refunded App",
                            "detailForDisplay": "Refund processed",
                            "invoiceLine3": "Refund",
                            "artworkURL": "https://example.test/refund.png",
                            "supportURL": "https://example.test/refund-support",
                            "mediaType": "App",
                            "subscriptionCoverageDescription": "",
                            "complete": True,
                            "imageType": "icon",
                            "localizedPotsEndOfCommitmentDate": "",
                        },
                        "subscriptionInfo": "Cancelled",
                        "lineItemType": "APP",
                        "estimatedTotal": "$4.99",
                    }
                ],
                "weborder": "WEB-2",
                "invoiceDate": "2026-05-10T09:05:00Z",
                "purchaseDate": "2026-05-10T09:00:00Z",
                "isPendingPurchase": False,
                "estimatedTotalAmount": "$4.99",
            }
        ],
    }


def _sample_page_nullable_fields() -> dict:
    return {
        "batchId": "",
        "nextBatchId": "",
        "query": {
            "batchId": "",
            "dsid": "123456789",
            "dsids": ["123456789"],
            "guid": "",
            "purchaseAmount": "",
            "weborder": "",
            "plis": [],
            "adamIds": [],
        },
        "purchases": [
            {
                "purchaseId": "purchase-nullable",
                "dsid": "123456789",
                "invoiceAmount": None,
                "plis": [
                    {
                        "itemId": "item-nullable",
                        "purchaseId": "purchase-nullable",
                        "storefrontId": "143441",
                        "adamId": "999",
                        "guid": "guid-nullable",
                        "title": None,
                        "amountPaid": "$1.99",
                        "pliDate": "2026-05-01T09:00:00Z",
                        "isFreePurchase": False,
                        "isCredit": False,
                        "localizedContent": {
                            "nameForDisplay": "Nullable App",
                            "detailForDisplay": "Legacy purchase",
                            "invoiceLine3": None,
                            "artworkURL": None,
                            "supportURL": None,
                            "mediaType": "App",
                            "subscriptionCoverageDescription": None,
                            "complete": True,
                            "imageType": None,
                            "localizedPotsEndOfCommitmentDate": None,
                        },
                        "subscriptionInfo": None,
                        "lineItemType": "APP",
                        "estimatedTotal": None,
                    }
                ],
                "weborder": "WEB-NULL",
                "invoiceDate": None,
                "purchaseDate": None,
                "isPendingPurchase": False,
                "estimatedTotalAmount": "$1.99",
            }
        ],
    }


def _sample_page_empty_optional_fields() -> dict:
    return {
        "batchId": "",
        "nextBatchId": "",
        "query": {
            "batchId": "",
            "dsid": "123456789",
            "dsids": ["123456789"],
            "guid": "",
            "purchaseAmount": "",
            "weborder": "",
            "plis": [],
            "adamIds": [],
        },
        "purchases": [
            {
                "purchaseId": "purchase-empty",
                "dsid": "123456789",
                "invoiceAmount": "$0.00",
                "plis": [
                    {
                        "itemId": "item-empty",
                        "purchaseId": "purchase-empty",
                        "storefrontId": "143441",
                        "adamId": "777",
                        "guid": "guid-empty",
                        "title": "Video Partner Billing",
                        "amountPaid": "",
                        "pliDate": "2026-05-02T10:00:00Z",
                        "isFreePurchase": False,
                        "isCredit": False,
                        "localizedContent": {
                            "nameForDisplay": "Streaming Bundle",
                            "detailForDisplay": "",
                            "invoiceLine3": "Carrier billing",
                            "artworkURL": "https://example.test/bundle.png",
                            "supportURL": "https://example.test/bundle-support",
                            "mediaType": "",
                            "subscriptionCoverageDescription": None,
                            "complete": True,
                            "imageType": "icon",
                            "localizedPotsEndOfCommitmentDate": None,
                        },
                        "subscriptionInfo": None,
                        "lineItemType": "VideoPartnerBilling",
                        "estimatedTotal": "$0.00",
                    }
                ],
                "weborder": "WEB-EMPTY",
                "invoiceDate": "2026-05-02T10:05:00Z",
                "purchaseDate": "2026-05-02T10:00:00Z",
                "isPendingPurchase": False,
                "estimatedTotalAmount": "$0.00",
            }
        ],
    }


def test_normalize_purchase_batch_keeps_paid_free_credit_and_subscription_fields():
    records = normalize_purchase_batch(_sample_page_one()) + normalize_purchase_batch(_sample_page_two())

    assert [record["id"] for record in records] == [
        "purchase-1:item-1",
        "purchase-1:item-2",
        "purchase-1:item-3",
        "purchase-2:item-4",
    ]

    subscription = records[0]
    assert subscription["media_type"] == "Subscription"
    assert subscription["subscription_info"] == "Renews monthly"
    assert subscription["subscription_coverage_description"] == "May 2026 coverage"
    assert subscription["localized_pots_end_of_commitment_date"] == "June 1, 2026"
    assert subscription["signed_amount_paid_value"] == "9.99"

    free_item = records[1]
    assert free_item["is_free_purchase"] is True
    assert free_item["amount_paid_value"] == "0.00"
    assert free_item["signed_amount_paid_value"] == "0.00"

    credit_item = records[3]
    assert credit_item["is_credit"] is True
    assert credit_item["signed_amount_paid_value"] == "-4.99"
    assert credit_item["subscription_info"] == "Cancelled"


def test_match_purchase_records_handles_amount_date_and_query():
    records = normalize_purchase_batch(_sample_page_one()) + normalize_purchase_batch(_sample_page_two())

    refund_matches = match_purchase_records(
        records,
        amount="-4.99",
        date="2026-05-10",
        query="refund",
        limit=10,
    )
    assert [match["id"] for match in refund_matches] == ["purchase-2:item-4"]
    assert refund_matches[0]["matched_amount"] is True
    assert refund_matches[0]["score"] >= 10

    movie_matches = match_purchase_records(
        records,
        amount=None,
        date=None,
        query="sci-fi",
        limit=10,
    )
    assert [match["id"] for match in movie_matches] == ["purchase-1:item-3"]


def test_normalize_purchase_batch_allows_observed_nullable_fields():
    records = normalize_purchase_batch(_sample_page_nullable_fields())

    assert len(records) == 1
    record = records[0]
    assert record["title"] is None
    assert record["invoice_date"] is None
    assert record["purchase_date"] is None
    assert record["invoice_amount"] is None
    assert record["invoice_amount_value"] is None
    assert record["estimated_total"] is None
    assert record["estimated_total_value"] is None


def test_normalize_purchase_batch_allows_empty_optional_detail_media_and_amount():
    records = normalize_purchase_batch(_sample_page_empty_optional_fields())

    assert len(records) == 1
    record = records[0]
    assert record["detail"] is None
    assert record["media_type"] is None
    assert record["amount_paid"] is None
    assert record["amount_paid_value"] is None
    assert record["signed_amount_paid_value"] is None
    assert record["currency_symbol"] is None
