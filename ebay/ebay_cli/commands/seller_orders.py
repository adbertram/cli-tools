"""Credential mapping for seller-orders commands implemented in orders.py."""

COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "fulfillments": ["oauth_authorization_code"],
}
