"""Copilot Studio capacity pre-check for a Power Platform environment.

Single source of truth for the deterministic, fail-fast entitlement gate that
blocks attaching tools or knowledge to a Copilot Studio agent when the target
environment has no Copilot Studio capacity.

An environment is entitled to attach tools/knowledge when EITHER:

* P1 — Copilot Studio capacity is allocated to the environment
  (``GET /licensing/environments/{id}/allocations``), i.e. any
  ``currencyAllocations`` entry whose ``currencyType`` is one of
  :data:`COPILOT_STUDIO_CURRENCIES` has ``allocated > 0``; OR
* P2 — the environment is covered by an Enabled pay-as-you-go billing policy
  (``GET /licensing/billingPolicies`` + each policy's ``/environments``).

A 404 on the allocations endpoint means "no allocation record" (P1 false, not an
error). Any other non-200/404 response on allocations, or any non-200 on a
policy's ``/environments`` lookup, means the signal is undeterminable and raises
:class:`~copilot_cli.client.ClientError` (fail loud). Capacity is the only gate:
user/tenant licenses are intentionally NOT consulted.

``client.py`` deliberately does not import this module at its top level, so this
module can import ``ClientError`` and ``get_access_token`` from ``client`` at
module scope without a circular import. The command modules import this module
directly.
"""
from __future__ import annotations

from typing import Optional

import httpx

from .client import ClientError, get_access_token
from .config import get_config

# Copilot Studio "Copilot Credits" currency types. An environment is entitled
# via P1 only if one of these currencies has a positive allocation.
COPILOT_STUDIO_CURRENCIES = ("MCSMessages", "MCSSessions", "VAConversations")

_POWER_PLATFORM_RESOURCE = "https://api.powerplatform.com"
_ALLOCATIONS_URL = (
    "https://api.powerplatform.com/licensing/environments/{environment_id}"
    "/allocations?api-version=2024-10-01"
)
_BILLING_POLICIES_URL = (
    "https://api.powerplatform.com/licensing/billingPolicies"
    "?api-version=2022-03-01-preview"
)
_BILLING_POLICY_ENVIRONMENTS_URL = (
    "https://api.powerplatform.com/licensing/billingPolicies/{billing_policy_id}"
    "/environments?api-version=2022-03-01-preview"
)


class CapacityError(ClientError):
    """Raised when an environment lacks Copilot Studio capacity for attach."""

    pass


def _power_platform_headers() -> dict[str, str]:
    """Authorization headers for the Power Platform licensing API."""
    token = get_access_token(_POWER_PLATFORM_RESOURCE)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _environment_has_allocation(environment_id: str, http_client: httpx.Client) -> bool:
    """P1: Copilot Studio capacity allocated to the environment.

    Returns True if any ``currencyAllocations`` entry whose ``currencyType`` is
    in :data:`COPILOT_STUDIO_CURRENCIES` has ``allocated > 0``. A 404 means no
    allocation record (P1 false). Any other non-200 status is undeterminable and
    raises :class:`~copilot_cli.client.ClientError`.
    """
    url = _ALLOCATIONS_URL.format(environment_id=environment_id)
    response = http_client.get(url, headers=_power_platform_headers(), timeout=60.0)

    if response.status_code == 404:
        # No allocation record for this environment (confirmed for Developer
        # envs). P1 is false; this is not an error.
        return False
    if response.status_code != 200:
        raise ClientError(
            "Could not determine Copilot Studio capacity for environment "
            f"'{environment_id}': allocations API returned HTTP "
            f"{response.status_code}."
        )

    data = response.json()
    allocations = data.get("currencyAllocations", []) or []
    for allocation in allocations:
        currency_type = allocation.get("currencyType")
        allocated = allocation.get("allocated", 0) or 0
        if currency_type in COPILOT_STUDIO_CURRENCIES and allocated > 0:
            return True
    return False


def _extract_policy_environment_ids(payload: dict) -> list[str]:
    """Extract environment ids from a billing policy ``/environments`` payload.

    The response shape is defensive: ``{"value": [...]}`` where each item is
    either a string id or an object carrying the id under ``id``,
    ``environmentId``, or ``name`` (optionally nested under ``properties``).
    """
    env_ids: list[str] = []
    for item in payload.get("value", []) or []:
        if isinstance(item, str):
            env_ids.append(item)
            continue
        if isinstance(item, dict):
            for key in ("id", "environmentId", "name"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    env_ids.append(value)
                    break
            else:
                props = item.get("properties")
                if isinstance(props, dict):
                    for key in ("id", "environmentId", "name"):
                        value = props.get(key)
                        if isinstance(value, str) and value:
                            env_ids.append(value)
                            break
    return env_ids


def _environment_in_billing_policy(environment_id: str, http_client: httpx.Client) -> bool:
    """P2: environment covered by an Enabled pay-as-you-go billing policy.

    Lists billing policies, and for each policy with ``status == "Enabled"``
    fetches its covered environments and matches the target id
    case-insensitively. A non-200 on the policy list or on a policy's
    ``/environments`` lookup is undeterminable and raises
    :class:`~copilot_cli.client.ClientError`.
    """
    target = environment_id.casefold()

    response = http_client.get(
        _BILLING_POLICIES_URL, headers=_power_platform_headers(), timeout=60.0
    )
    if response.status_code != 200:
        raise ClientError(
            "Could not determine billing policy coverage for environment "
            f"'{environment_id}': billingPolicies API returned HTTP "
            f"{response.status_code}."
        )

    policies = response.json().get("value", []) or []
    for policy in policies:
        if policy.get("status") != "Enabled":
            continue
        billing_policy_id = policy.get("billingPolicyId") or policy.get("id")
        if not billing_policy_id:
            continue

        envs_url = _BILLING_POLICY_ENVIRONMENTS_URL.format(
            billing_policy_id=billing_policy_id
        )
        envs_response = http_client.get(
            envs_url, headers=_power_platform_headers(), timeout=60.0
        )
        if envs_response.status_code != 200:
            raise ClientError(
                "Could not determine billing policy coverage for environment "
                f"'{environment_id}': billing policy '{billing_policy_id}' "
                f"environments lookup returned HTTP {envs_response.status_code}."
            )

        covered_ids = _extract_policy_environment_ids(envs_response.json())
        if any(covered.casefold() == target for covered in covered_ids):
            return True

    return False


def environment_supports_tools_and_knowledge(environment_id: str) -> bool:
    """Return whether the environment can have tools/knowledge attached.

    Evaluates P1 (Copilot Studio capacity allocation) first, then P2
    (pay-as-you-go billing policy coverage) only if P1 is false. Raises
    :class:`~copilot_cli.client.ClientError` if the signal is undeterminable.
    """
    with httpx.Client(timeout=60.0) as http_client:
        if _environment_has_allocation(environment_id, http_client):
            return True
        return _environment_in_billing_policy(environment_id, http_client)


def resolve_environment_id() -> str:
    """Resolve the target Power Platform environment id (GUID).

    Order:
        1. ``get_config().environment_id`` (DATAVERSE_ENVIRONMENT_ID /
           POWERPLATFORM_ENVIRONMENT_ID), used directly when set.
        2. Otherwise match ``get_config().dataverse_url`` against the
           ``instanceUrl`` of a known environment via the BAP environments list.

    Raises:
        ClientError: If the environment id cannot be determined.
    """
    config = get_config()

    environment_id = config.environment_id
    if environment_id:
        return environment_id

    dataverse_url = config.dataverse_url
    if dataverse_url:
        from .client import get_client

        target = _normalize_instance_url(dataverse_url)
        client = get_client()
        for record in client.list_environments():
            props = record.get("properties", {}) or {}
            linked = props.get("linkedEnvironmentMetadata", {}) or {}
            instance_url = linked.get("instanceUrl", "")
            if instance_url and _normalize_instance_url(instance_url) == target:
                return _environment_id_from_record(record)

    raise ClientError(
        "Could not determine the Power Platform environment id. "
        "Set DATAVERSE_ENVIRONMENT_ID in the active copilot profile, or ensure "
        "DATAVERSE_URL matches a known environment."
    )


def _normalize_instance_url(url: str) -> str:
    """Normalize a Dataverse instance URL for case-insensitive host matching."""
    return url.strip().rstrip("/").casefold()


def _environment_id_from_record(record: dict) -> str:
    """Extract the environment GUID from a BAP environment record.

    BAP env records carry the GUID in the top-level ``name`` field; strip any
    ``/providers/...`` prefix to match how environment commands resolve ids.
    """
    env_id = record.get("name", "")
    if "/providers/" in env_id:
        env_id = env_id.rsplit("/", 1)[-1]
    return env_id


def _resolve_environment_display_name(environment_id: str) -> str:
    """Best-effort human-readable environment name for the error message.

    Falls back to the GUID if the display name cannot be read. This fallback is
    for the message only and never affects the entitlement decision.
    """
    from .client import get_client

    try:
        record = get_client().get_environment(environment_id)
        display_name = record.get("properties", {}).get("displayName")
        if display_name:
            return display_name
    except Exception:
        pass
    return environment_id


def ensure_tools_and_knowledge_entitled(
    environment_id: str,
    *,
    action: str,
    env_display_name: Optional[str] = None,
) -> None:
    """Raise :class:`CapacityError` if the environment cannot attach tools/knowledge.

    Args:
        environment_id: The target environment GUID.
        action: Short phrase describing the attempted action (e.g.
            ``"attach tools"`` / ``"attach knowledge"``), used in the message.
        env_display_name: Optional pre-resolved display name. Resolved via the
            BAP API when omitted.

    Raises:
        CapacityError: If the environment has no Copilot Studio capacity and is
            not covered by a pay-as-you-go billing policy.
        ClientError: If the entitlement signal is undeterminable.
    """
    if environment_supports_tools_and_knowledge(environment_id):
        return

    display_name = env_display_name or _resolve_environment_display_name(environment_id)
    raise CapacityError(_capacity_error_message(display_name, environment_id, action))


def _capacity_error_message(display_name: str, guid: str, action: str) -> str:
    """Build the actionable not-entitled error message.

    The first sentence (capacity/billing facts) and the three remediation lines
    with the admin URL are verbatim per the command contract. ``action`` only
    tailors a short leading clause.
    """
    lines = [
        f"Cannot {action}.",
        f"Environment '{display_name}' ({guid}) has no Copilot Studio capacity "
        "(Copilot Credits) allocated and is not covered by a pay-as-you-go "
        "billing policy, so tools and knowledge cannot be attached.",
        "",
        "To fix this, do one of the following:",
        "  1. Allocate prepaid Copilot Studio capacity to this environment in the "
        "Power Platform admin center (Licensing > Copilot Studio): "
        "https://admin.powerplatform.microsoft.com",
        "  2. Link the environment to a pay-as-you-go billing policy (requires an "
        "Azure subscription).",
        "  3. Use an environment that already has Copilot Studio capacity.",
    ]
    return "\n".join(lines)
