"""Tests for M365 Agents SDK Power Platform cloud resolution.

Covers ``agent.resolve_power_platform_cloud`` and the
``DATAVERSE_HOST_CLOUD_MAP`` data table that drives it. The resolver decides
which ``PowerPlatformCloud`` the M365 Agents SDK uses for ``agent prompt`` on
integrated-auth agents. The bug these tests guard against: forcing
``PowerPlatformCloud.OTHER`` (with a scheme-less host) for a normal commercial
tenant, which raises SDK error -65003.
"""

import pytest

from copilot_cli.commands import agent
from microsoft_agents.copilotstudio.client.power_platform_cloud import (
    PowerPlatformCloud,
)


# ---------------------------------------------------------------------------
# Commercial / public cloud (the repro environment + regional commercial orgs)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dataverse_url",
    [
        "https://org23192677.crm.dynamics.com/",  # exact repro environment
        "https://contoso.crm.dynamics.com",        # North America (unnumbered)
        "https://contoso.crm4.dynamics.com",       # EMEA regional
        "https://contoso.crm11.dynamics.com",      # UK regional
        "https://CONTOSO.CRM.DYNAMICS.COM/",       # case-insensitive
    ],
)
def test_commercial_hosts_resolve_to_public_cloud(dataverse_url):
    """Commercial Dataverse hosts must use the SDK default (public) cloud."""
    cloud, custom_base = agent.resolve_power_platform_cloud(dataverse_url)
    assert cloud is None
    assert custom_base is None


def test_repro_env_does_not_force_other_cloud():
    """Regression: the exact repro must not produce PowerPlatformCloud.OTHER."""
    cloud, custom_base = agent.resolve_power_platform_cloud(
        "https://org23192677.crm.dynamics.com/"
    )
    assert cloud is not PowerPlatformCloud.OTHER


# ---------------------------------------------------------------------------
# Sovereign clouds (derived from the Dataverse host, no custom base address)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dataverse_url,expected_cloud",
    [
        ("https://org.crm9.dynamics.com", PowerPlatformCloud.GOV),            # GCC
        ("https://org.crm.microsoftdynamics.us", PowerPlatformCloud.HIGH),    # GCC High
        ("https://org.crm.appsplatform.us", PowerPlatformCloud.DOD),          # DoD
        ("https://org.crm.dynamics.cn", PowerPlatformCloud.MOONCAKE),         # China
    ],
)
def test_sovereign_hosts_resolve_to_enum(dataverse_url, expected_cloud):
    cloud, custom_base = agent.resolve_power_platform_cloud(dataverse_url)
    assert cloud is expected_cloud
    assert custom_base is None


def test_sovereign_clouds_have_known_sdk_endpoints():
    """Every mapped sovereign enum must resolve to a real SDK endpoint host."""
    from microsoft_agents.copilotstudio.client.power_platform_environment import (
        PowerPlatformEnvironment,
    )

    for cloud_name in agent.DATAVERSE_HOST_CLOUD_MAP.values():
        cloud = PowerPlatformCloud[cloud_name]
        suffix = PowerPlatformEnvironment.get_endpoint_suffix(cloud, "")
        assert isinstance(suffix, str) and suffix, cloud_name


# ---------------------------------------------------------------------------
# Explicit cloud-name override (for clouds the host table does not classify)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "override,expected_cloud",
    [
        ("Gov", PowerPlatformCloud.GOV),
        ("gov", PowerPlatformCloud.GOV),          # enum value, case-insensitive
        ("GOV", PowerPlatformCloud.GOV),          # enum name
        ("High", PowerPlatformCloud.HIGH),
        ("DoD", PowerPlatformCloud.DOD),
        ("dod", PowerPlatformCloud.DOD),
        ("Mooncake", PowerPlatformCloud.MOONCAKE),
    ],
)
def test_cloud_name_override_returns_enum(override, expected_cloud):
    cloud, custom_base = agent.resolve_power_platform_cloud(
        "https://org.crm.dynamics.com", override=override
    )
    assert cloud is expected_cloud
    assert custom_base is None


def test_prod_override_returns_none_for_public_default():
    """An explicit Prod override collapses to cloud=None (SDK public default)."""
    cloud, custom_base = agent.resolve_power_platform_cloud(
        "https://org.crm9.dynamics.com",  # would otherwise be GOV
        override="Prod",
    )
    assert cloud is None
    assert custom_base is None


def test_override_never_uses_other_cloud():
    """The OTHER/base-address path is non-functional; override must avoid it."""
    for override in ("Gov", "High", "DoD", "Mooncake", "Prod"):
        cloud, _ = agent.resolve_power_platform_cloud(
            "https://org.crm.dynamics.com", override=override
        )
        assert cloud is not PowerPlatformCloud.OTHER


def test_sovereign_override_resolves_with_sdk(monkeypatch):
    """A cloud-name override must produce a usable audience AND connection URL."""
    from microsoft_agents.copilotstudio.client import ConnectionSettings
    from microsoft_agents.copilotstudio.client.power_platform_environment import (
        PowerPlatformEnvironment,
    )

    cloud, custom_base = agent.resolve_power_platform_cloud(
        "https://org.crm.dynamics.com", override="Gov"
    )
    settings = ConnectionSettings(
        environment_id="5f1c8ab0-08bc-e6e4-80b2-7bb918e41e0e",
        agent_identifier="cr1a2_agent",
        cloud=cloud,
        copilot_agent_type=None,
        custom_power_platform_cloud=custom_base,
    )
    audience = PowerPlatformEnvironment.get_token_audience(settings=settings)
    assert audience == "https://api.gov.powerplatform.microsoft.us/.default"
    url = PowerPlatformEnvironment.get_copilot_studio_connection_url(settings=settings)
    # Host must be a clean sovereign host (no embedded scheme / malformed value).
    assert "environment.api.gov.powerplatform.microsoft.us" in url
    assert "https://https" not in url


@pytest.mark.parametrize(
    "bad_override",
    [
        "api.powerplatform.com",                       # base address, not a cloud name
        "https://api.powerplatform.com",               # full URL, not a cloud name
        "us-il105.gateway.prod.island.powerapps.com",  # legacy Direct Line host
        "Commercial",                                   # not an SDK enum name
        "not-a-cloud",
    ],
)
def test_unknown_override_fails_loudly(bad_override):
    with pytest.raises(ValueError) as excinfo:
        agent.resolve_power_platform_cloud(
            "https://org.crm.dynamics.com", override=bad_override
        )
    assert agent.POWERPLATFORM_CLOUD_ENV in str(excinfo.value)


# ---------------------------------------------------------------------------
# Legacy POWERPLATFORM_CLOUD_URL must NOT influence cloud selection
# ---------------------------------------------------------------------------

def test_legacy_cloud_url_env_is_ignored(monkeypatch):
    """The legacy island-gateway env var must not force OTHER (the -65003 bug)."""
    monkeypatch.setenv(
        "POWERPLATFORM_CLOUD_URL", "us-il105.gateway.prod.island.powerapps.com"
    )
    monkeypatch.delenv(agent.POWERPLATFORM_CLOUD_ENV, raising=False)
    cloud, custom_base = agent.resolve_power_platform_cloud(
        "https://org23192677.crm.dynamics.com/"
    )
    assert cloud is None
    assert custom_base is None


# ---------------------------------------------------------------------------
# Missing / unidentifiable hosts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dataverse_url", [None, "", "not-a-url"])
def test_missing_host_defaults_to_public(dataverse_url):
    cloud, custom_base = agent.resolve_power_platform_cloud(dataverse_url)
    assert cloud is None
    assert custom_base is None


def test_unknown_non_commercial_host_fails_loudly():
    with pytest.raises(ValueError) as excinfo:
        agent.resolve_power_platform_cloud("https://org.example.gov")
    assert "org.example.gov" in str(excinfo.value)
