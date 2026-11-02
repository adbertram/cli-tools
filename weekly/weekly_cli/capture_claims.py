"""Inspect identity claims in a token returned directly by the authenticated service."""
import base64
import json
from cli_tools_shared.exceptions import ClientError


def claims(token):
    try:
        encoded = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError, IndexError):
        raise ClientError('Weekly authentication returned an invalid identity token') from None
