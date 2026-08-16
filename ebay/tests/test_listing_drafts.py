"""Tests for true Seller Hub draft creation."""

import csv
import io
import json
from unittest.mock import MagicMock, patch

from ebay_cli.client import EbayClient
from ebay_cli.commands import listings
from ebay_cli.draft_feed import extract_feed_result
from ebay_cli.main import app


def test_legacy_create_without_publish_fails_before_any_api_call(monkeypatch, runner):
    get_client = MagicMock()
    monkeypatch.setattr(listings, "get_client", get_client)

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "create",
            "--sku",
            "SKU-LEGACY",
            "--fulfillment-policy",
            "policy-123",
        ],
    )

    assert result.exit_code == 1
    assert "ebay seller listings drafts create" in result.stderr
    get_client.assert_not_called()


def test_drafts_create_rejects_exact_sentinel_price_before_any_api_call(
    monkeypatch, runner
):
    get_client = MagicMock()
    monkeypatch.setattr(listings, "get_client", get_client)

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "drafts",
            "create",
            "--category",
            "47140",
            "--price",
            "99999.00",
        ],
    )

    assert result.exit_code == 1
    assert "Draft price 99999.00 is not allowed." in result.stderr
    get_client.assert_not_called()


def test_drafts_create_preserves_price_and_never_publishes(monkeypatch, runner):
    client = MagicMock()
    client.create_feed_task.return_value = "task-123"
    client.get_feed_task.return_value = {
        "taskId": "task-123",
        "status": "COMPLETED",
        "feedType": "FX_LISTING",
        "schemaVersion": "1.0",
        "uploadSummary": {"successCount": 1, "failureCount": 0},
    }
    client.download_feed_result.return_value = {
        "content": b"<VerifyAddItemResponse><Ack>Success</Ack></VerifyAddItemResponse>",
        "content_type": "application/xml",
        "content_disposition": 'attachment; filename="result.xml"',
    }
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "drafts",
            "create",
            "--sku",
            "SKU-DRAFT",
            "--category",
            "47140",
            "--title",
            "Test Draft Shoe",
            "--price",
            "11.00",
            "--quantity",
            "1",
            "--image-url",
            "https://example.com/image.png",
            "--condition-id",
            "NEW",
            "--description",
            "<p>Draft description</p>",
            "--format",
            "FixedPrice",
        ],
    )

    assert result.exit_code == 0
    client.create_feed_task.assert_called_once_with(
        feed_type="FX_LISTING",
        schema_version="1.0",
        marketplace_id="EBAY_US",
    )
    upload_call = client.upload_feed_file.call_args
    assert upload_call.args[0] == "task-123"
    assert upload_call.kwargs["filename"] == "ebay-draft.csv"

    csv_text = upload_call.kwargs["content"].decode("utf-8")
    assert "99999" not in csv_text
    assert "Payment" not in csv_text
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert len(rows) == 6
    header = rows[4]
    draft = dict(zip(header, rows[5]))
    assert draft[header[0]] == "Draft"
    assert draft["Start price"] == "11.00"
    assert draft["Custom label (SKU)"] == "SKU-DRAFT"

    client.create_offer.assert_not_called()
    client.publish_offer.assert_not_called()
    client.withdraw_offer.assert_not_called()

    payload = json.loads(result.stdout)
    assert payload["task_id"] == "task-123"
    assert payload["task_status"] == "COMPLETED"
    assert payload["task"]["uploadSummary"] == {
        "successCount": 1,
        "failureCount": 0,
    }
    assert payload["result_file"]["content"] == (
        "<VerifyAddItemResponse><Ack>Success</Ack></VerifyAddItemResponse>"
    )
    assert payload["draft_identifiers"] == [{"custom_label": "SKU-DRAFT"}]
    assert payload["errors"] == []


def test_drafts_create_returns_result_errors(monkeypatch, runner):
    client = MagicMock()
    client.create_feed_task.return_value = "task-error"
    client.get_feed_task.return_value = {
        "taskId": "task-error",
        "status": "COMPLETED_WITH_ERROR",
        "feedType": "FX_LISTING",
        "schemaVersion": "1.0",
        "uploadSummary": {"successCount": 0, "failureCount": 1},
    }
    client.download_feed_result.return_value = {
        "content": (
            b"<VerifyAddItemResponse><Ack>Failure</Ack><Errors>"
            b"<ShortMessage>Invalid category.</ShortMessage>"
            b"<LongMessage>The category is not valid.</LongMessage>"
            b"<ErrorCode>17</ErrorCode><SeverityCode>Error</SeverityCode>"
            b"</Errors></VerifyAddItemResponse>"
        ),
        "content_type": "application/xml",
        "content_disposition": 'attachment; filename="result.xml"',
    }
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "drafts",
            "create",
            "--category",
            "47140",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["task_status"] == "COMPLETED_WITH_ERROR"
    assert payload["draft_identifiers"] == []
    assert payload["errors"] == [
        {
            "error_code": "17",
            "severity": "Error",
            "short_message": "Invalid category.",
            "long_message": "The category is not valid.",
        }
    ]


def test_drafts_create_help_has_no_payment_policy(runner):
    result = runner.invoke(
        app,
        ["seller", "listings", "drafts", "create", "--help"],
    )

    assert result.exit_code == 0
    assert "--category" in result.stdout
    assert "--payment-policy" not in result.stdout


def test_extract_feed_result_captures_error_message_without_space_in_header():
    """Regression test: eBay's real BAF result CSV uses the header
    'ErrorMessage' (no space), but CSV_ERROR_FIELDS previously only mapped
    'error message' (with a space). The message was silently dropped from
    the CLI's structured output even though the raw CSV contained it.

    Reproduces the exact result file eBay returned in production for
    `ebay seller listings drafts create --category 183448 ...` on
    2026-08-04 (task-40-11325169945).
    """
    csv_content = (
        "Line Number,Action,Status,ErrorCode,ErrorMessage,WarningCode,"
        "WarningMessage,Code,Message,ItemID,ReferenceID,ApplicationData,"
        "StartTime,EndTime,CustomLabel,CorrelationID\n"
        "2,Draft,Failure,BAF.Error.5,Unable to find Task Action Id for task "
        "Draft,,,,,,,,,,EBAY-20260804123553,\n"
    )

    identifiers, errors = extract_feed_result(
        csv_content, custom_label="EBAY-20260804123553"
    )

    assert identifiers == [{"custom_label": "EBAY-20260804123553"}]
    assert len(errors) == 1
    assert errors[0]["error_code"] == "BAF.Error.5"
    assert errors[0]["long_message"] == (
        "Unable to find Task Action Id for task Draft"
    )


def test_extract_feed_result_attaches_hint_for_known_baf_error_5():
    """BAF.Error.5 'Unable to find Task Action Id for task Draft' is a known,
    deterministic eBay platform limitation (eBay Developer Support: 'eBay does
    not offer a dedicated API for creating draft listings'). The CLI must
    surface an actionable hint instead of a bare, unexplained error code.
    """
    csv_content = (
        "Line Number,Action,Status,ErrorCode,ErrorMessage\n"
        "2,Draft,Failure,BAF.Error.5,Unable to find Task Action Id for task "
        "Draft\n"
    )

    _, errors = extract_feed_result(csv_content, custom_label=None)

    assert len(errors) == 1
    assert "hint" in errors[0]
    assert "no dedicated API for creating draft listings" in errors[0]["hint"]
    assert "Seller Hub" in errors[0]["hint"]


def test_extract_feed_result_does_not_hint_unrelated_errors():
    """The hint must only attach to the recognized BAF.Error.5/Draft
    signature, not to every error — an unrelated error code or message
    must pass through unchanged."""
    csv_content = (
        "Line Number,Action,Status,ErrorCode,ErrorMessage\n"
        "2,Add,Failure,21916984,Invalid category ID.\n"
    )

    _, errors = extract_feed_result(csv_content, custom_label=None)

    assert len(errors) == 1
    assert "hint" not in errors[0]
    assert errors[0]["long_message"] == "Invalid category ID."


def test_drafts_create_surfaces_hint_for_baf_error_5(monkeypatch, runner):
    """End-to-end: when eBay's feed task completes with the known BAF.Error.5
    Draft-not-supported failure, `ebay seller listings drafts create` must
    print the actionable hint in its JSON output, not just the bare code."""
    client = MagicMock()
    client.create_feed_task.return_value = "task-baf5"
    client.get_feed_task.return_value = {
        "taskId": "task-baf5",
        "status": "COMPLETED_WITH_ERROR",
        "feedType": "FX_LISTING",
        "uploadSummary": {"successCount": 0, "failureCount": 1},
    }
    client.download_feed_result.return_value = {
        "content": (
            b"Line Number,Action,Status,ErrorCode,ErrorMessage\n"
            b"2,Draft,Failure,BAF.Error.5,Unable to find Task Action Id for "
            b"task Draft\n"
        ),
        "content_type": "application/octet-stream",
        "content_disposition": 'attachment; filename="result.csv"',
    }
    monkeypatch.setattr(listings, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "listings",
            "drafts",
            "create",
            "--category",
            "183448",
            "--sku",
            "EBAY-TEST",
            "--price",
            "0.99",
            "--format",
            "Auction",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"] == [
        {
            "error_code": "BAF.Error.5",
            "long_message": "Unable to find Task Action Id for task Draft",
            "hint": payload["errors"][0]["hint"],
        }
    ]
    assert "no dedicated API for creating draft listings" in (
        payload["errors"][0]["hint"]
    )


def test_feed_task_client_uses_fx_listing_contract(mock_config):
    with patch("ebay_cli.client.TokenManager") as token_manager:
        token_manager.return_value.is_expired.return_value = False
        client = EbayClient(config=mock_config)

    response = MagicMock()
    response.ok = True
    response.status_code = 202
    response.content = b""
    response.headers = {
        "Location": "/sell/feed/v1/task/task-123",
    }

    with patch("ebay_cli.client.requests.request", return_value=response) as request:
        task_id = client.create_feed_task(
            feed_type="FX_LISTING",
            schema_version="1.0",
            marketplace_id="EBAY_US",
        )

    assert task_id == "task-123"
    assert request.call_args.kwargs["method"] == "POST"
    assert request.call_args.kwargs["url"].endswith("/sell/feed/v1/task")
    assert request.call_args.kwargs["json"] == {
        "feedType": "FX_LISTING",
        "schemaVersion": "1.0",
    }
    assert request.call_args.kwargs["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"


def test_feed_upload_uses_file_form_part_without_json_content_type(mock_config):
    with patch("ebay_cli.client.TokenManager") as token_manager:
        token_manager.return_value.is_expired.return_value = False
        client = EbayClient(config=mock_config)

    response = MagicMock()
    response.ok = True
    response.status_code = 200
    response.content = b""
    response.headers = {}

    with patch("ebay_cli.client.requests.request", return_value=response) as request:
        client.upload_feed_file(
            "task-123",
            filename="ebay-draft.csv",
            content=b"draft-feed",
        )

    assert request.call_args.kwargs["url"].endswith(
        "/sell/feed/v1/task/task-123/upload_file"
    )
    assert request.call_args.kwargs["files"] == {
        "file": ("ebay-draft.csv", b"draft-feed", "text/csv"),
    }
    assert "Content-Type" not in request.call_args.kwargs["headers"]
    assert request.call_args.kwargs["json"] is None
