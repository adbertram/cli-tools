"""Venmo client wrapper around the venmo-api library.

The reverse-engineered venmo-api library (https://github.com/mmohades/Venmo)
exposes Venmo's private mobile API. This module wraps it for the CLI:

- Authentication via username + password + SMS OTP (handled in main.py's
  login_handler).
- Transaction history retrieval via UserApi.get_user_transactions().
- Output contract: records are returned as the raw Venmo API JSON payload
  (i.e. the `_json` attribute the venmo-api library hangs off each
  Transaction object). This is intentional: the CLI preserves the full,
  unfiltered transaction shape from the source by default. If Venmo adds
  fields server-side, downstream consumers see them immediately without
  a CLI release. We inject ONE convenience field at the top level:

    - `payment_id` — Venmo's durable payment id (also present at
      `payment.id`). The top-level `id` in the raw payload is Venmo's
      story_id, which is null for items returned by /stories/target-or-actor.
      `payment_id` is what end users actually use to look up a transaction
      (and what `--filter` users were filtering on under the old shape).
"""

from typing import Dict, List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .config import get_config


def transaction_to_record(txn) -> dict:
    """Return the raw Venmo API payload for a transaction, plus payment_id.

    The venmo-api library exposes the unmodified server JSON on
    `Transaction._json`. We pass it through verbatim and additionally surface
    `payment_id` at the top level as a convenience for lookups and filters.

    Raises:
        ClientError: if `_json` is missing on the Transaction object — that
            would indicate a breaking change in the upstream library.
    """
    raw = getattr(txn, "_json", None)
    if raw is None:
        raise ClientError(
            "venmo-api Transaction object is missing `_json`. The upstream "
            "library shape has changed; venmo_cli.client.transaction_to_record "
            "must be updated."
        )
    record = dict(raw)
    payment = raw.get("payment") or {}
    payment_id = payment.get("id")
    if payment_id is not None:
        record["payment_id"] = payment_id
    return record


class VenmoClient:
    """Client for interacting with the Venmo private mobile API."""

    def __init__(self, profile: Optional[str] = None):
        self.config = get_config(profile=profile)
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'venmo auth login' to authenticate."
            )
        # Lazy import so 'venmo --help' and 'venmo auth status' don't pay
        # the venmo-api import cost.
        from venmo_api import Client as VenmoApiClient

        self._venmo = VenmoApiClient(access_token=self.config.access_token)
        venmo_profile = self._venmo.my_profile()
        self._user_id = venmo_profile.id

    @cached
    def list_transactions(self, limit: int = 50, before_id: Optional[str] = None) -> List[dict]:
        """Return the most recent transactions visible to the authenticated user.

        Each record is the raw Venmo API JSON payload for one transaction with
        `payment_id` injected at the top level. See `transaction_to_record` for
        details.
        """
        page = self._venmo.user.get_user_transactions(
            user_id=self._user_id,
            limit=limit,
            before_id=before_id,
        )
        if page is None:
            return []
        return [transaction_to_record(txn) for txn in page]

    @cached
    def get_transaction(self, transaction_id: str) -> dict:
        """Look up a single transaction by payment_id in the most recent history page."""
        page = self._venmo.user.get_user_transactions(user_id=self._user_id, limit=500)
        if page is None:
            raise ClientError(f"Transaction '{transaction_id}' not found.")
        target = str(transaction_id)
        for txn in page:
            record = transaction_to_record(txn)
            if str(record.get("payment_id", "")) == target:
                return record
        raise ClientError(f"Transaction '{transaction_id}' not found in recent history.")


_clients: Dict[str, VenmoClient] = {}


def get_client(profile: Optional[str] = None) -> VenmoClient:
    """Get or create the Venmo client instance for an auth profile."""
    key = profile or "_default"
    if key not in _clients:
        _clients[key] = VenmoClient(profile=profile)
    return _clients[key]
