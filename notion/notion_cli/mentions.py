"""Resolve Notion user mentions for comment rich_text payloads.

A mention is its own rich_text object, NOT text. A literal "@Name" string
inside comment text renders as plain text and notifies nobody. Only a
``{"type": "mention", "mention": {"type": "user", ...}}`` object produces a real
Notion notification, which is what this module builds.

Resolution is fail-fast by design: an unknown email, an ambiguous email, or a
bot user aborts before the comment is created. There is deliberately no
degrade-to-plain-text path — that silent failure is exactly what these mentions
exist to remove.
"""
import re
from typing import Dict, List

from .client import ClientError, NotFoundError

# Notion user IDs are UUIDs, accepted dashed or undashed.
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?"
    r"[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"
)


def build_user_mention(user_id: str) -> Dict:
    """Build the rich_text mention object for one user ID."""
    return {
        "type": "mention",
        "mention": {"type": "user", "user": {"id": user_id, "object": "user"}},
    }


def _require_person_id(user: Dict, identifier: str) -> str:
    """Return the user's ID, rejecting any non-person user."""
    user_type = user.get("type")
    if user_type != "person":
        name = user.get("name") or "unnamed"
        raise ClientError(
            f"--mention target '{identifier}' resolves to Notion user "
            f"{user.get('id', '')} ({name}) of type '{user_type}'. Only person "
            "users can be mentioned; Notion rejects a bot user ID and fails the "
            "whole comment request."
        )

    user_id = user.get("id")
    if not user_id:
        raise ClientError(
            f"Notion user response for '{identifier}' is missing an id"
        )
    return user_id


def _resolve_uuid(client, identifier: str) -> str:
    """Resolve a user UUID, verifying it is a real person user."""
    try:
        user = client.get_user(identifier)
    except NotFoundError as exc:
        raise ClientError(
            f"--mention user ID '{identifier}' does not exist in this Notion "
            f"workspace, or the integration cannot read it: {exc}"
        ) from exc
    return _require_person_id(user, identifier)


def _resolve_email(client, identifier: str) -> str:
    """Resolve an email address to a user ID via the full users listing."""
    target = identifier.strip().lower()
    users = client.list_users_all()

    matches = [
        u
        for u in users
        if ((u.get("person") or {}).get("email") or "").strip().lower() == target
    ]

    if not matches:
        raise ClientError(
            f"--mention email '{identifier}' matches no user in this Notion "
            "workspace. Run 'notion users list --table' to see mentionable "
            "users. If every person shows an empty email, the integration's "
            "'email' capability is off and emails cannot be matched; pass the "
            "user UUID instead."
        )

    if len(matches) > 1:
        listed = ", ".join(
            f"{u.get('name') or 'unnamed'} <{u.get('id', '')}>" for u in matches
        )
        raise ClientError(
            f"--mention email '{identifier}' matches {len(matches)} users: "
            f"{listed}. Pass the exact user UUID instead."
        )

    return _require_person_id(matches[0], identifier)


def resolve_mention_user_id(client, identifier: str) -> str:
    """
    Resolve one ``--mention`` value to a mentionable person user ID.

    Args:
        client: A NotionClient
        identifier: A user UUID or an email address

    Returns:
        The Notion user ID, in the canonical form the API returned

    Raises:
        ClientError: If the value is neither a UUID nor an email, matches no
            user, matches more than one user, or resolves to a bot user
    """
    value = identifier.strip()

    if not value:
        raise ClientError(
            "--mention requires a user UUID or an email address; got an empty value"
        )

    if "@" in value:
        return _resolve_email(client, value)

    if _UUID_PATTERN.match(value):
        return _resolve_uuid(client, value)

    raise ClientError(
        f"--mention value '{identifier}' is neither a Notion user UUID nor an "
        "email address. Pass an email (user@example.com) or a user UUID from "
        "'notion users list'."
    )


def resolve_mention_user_ids(client, identifiers) -> List[str]:
    """Resolve every ``--mention`` value, preserving the order given."""
    return [resolve_mention_user_id(client, i) for i in identifiers or []]
