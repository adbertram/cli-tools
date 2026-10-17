"""Tests for `ebay seller messages reply` parent message identification.

eBay's Trading API AddMemberMessageRTQ requires ParentMessageID to be the
message's ExternalMessageID (the id the buyer-facing APIs use), not the
internal MessageID printed by `messages list` / `messages get`. Passing the
internal id makes the call fail with "Invalid Parent Message Id."
"""

from unittest.mock import MagicMock

import pytest

from ebay_cli.commands import messages
from ebay_cli.main import app

# The two identifiers eBay returns for the same buyer question.
INTERNAL_MESSAGE_ID = "213147487941"
EXTERNAL_MESSAGE_ID = "6442143160019"

GET_MY_MESSAGES_RESPONSE = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyMessagesResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <Messages>
    <Message>
      <MessageID>{INTERNAL_MESSAGE_ID}</MessageID>
      <ExternalMessageID>{EXTERNAL_MESSAGE_ID}</ExternalMessageID>
      <Sender>testbuyer</Sender>
      <RecipientUserID>testseller</RecipientUserID>
      <Subject>Sorter dimensions</Subject>
      <Text>How big is the sorter?</Text>
      <ReceiveDate>2026-09-10T12:00:00.000Z</ReceiveDate>
      <ItemID>123456789012</ItemID>
    </Message>
  </Messages>
</GetMyMessagesResponse>
"""

ADD_MEMBER_MESSAGE_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<AddMemberMessageRTQResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
</AddMemberMessageRTQResponse>
"""


def _client_with(monkeypatch, my_messages_response: str) -> MagicMock:
    client = MagicMock()
    client.get_my_messages.return_value = my_messages_response
    client.add_member_message_reply.return_value = ADD_MEMBER_MESSAGE_RESPONSE
    monkeypatch.setattr(messages, "get_client", lambda: client)
    return client


def _reply(runner):
    return runner.invoke(
        app,
        [
            "seller",
            "messages",
            "reply",
            INTERNAL_MESSAGE_ID,
            "--body",
            "About 11 x 11 x 13 inches.",
        ],
    )


def test_reply_sends_external_message_id_as_parent_message_id(monkeypatch, runner):
    """The internal MessageID from list/get must never reach ParentMessageID."""
    client = _client_with(monkeypatch, GET_MY_MESSAGES_RESPONSE)

    result = _reply(runner)

    assert result.exit_code == 0, result.stderr
    assert client.get_my_messages.call_args.kwargs["message_ids"] == [INTERNAL_MESSAGE_ID]
    kwargs = client.add_member_message_reply.call_args.kwargs
    assert kwargs["parent_message_id"] == EXTERNAL_MESSAGE_ID
    assert kwargs["parent_message_id"] != INTERNAL_MESSAGE_ID
    assert kwargs["recipient_id"] == "testbuyer"
    assert kwargs["item_id"] == "123456789012"


@pytest.mark.parametrize(
    "external_element",
    ["<ExternalMessageID></ExternalMessageID>", ""],
    ids=["empty-element", "absent-element"],
)
def test_reply_falls_back_to_internal_message_id_without_external_id(
    monkeypatch, runner, external_element
):
    """A message with no ExternalMessageID still replies using the id given on the CLI."""
    response = GET_MY_MESSAGES_RESPONSE.replace(
        f"<ExternalMessageID>{EXTERNAL_MESSAGE_ID}</ExternalMessageID>", external_element
    )
    client = _client_with(monkeypatch, response)

    result = _reply(runner)

    assert result.exit_code == 0, result.stderr
    assert (
        client.add_member_message_reply.call_args.kwargs["parent_message_id"]
        == INTERNAL_MESSAGE_ID
    )
