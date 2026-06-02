"""Credential mapping for shipping-labels commands implemented in orders.py."""

COMMAND_CREDENTIALS = {
    "create": ["oauth_authorization_code"],
    "void": ["oauth_authorization_code"],
    "cancel": ["oauth_authorization_code"],
    "download": ["oauth_authorization_code"],
}
