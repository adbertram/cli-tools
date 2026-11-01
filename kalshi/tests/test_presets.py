import pytest
from cli_tools_shared.exceptions import ClientError

from kalshi_cli.presets import load_presets, resolve_series


def test_preset_name_resolves_to_series():
    series, preset = resolve_series("btc15m")
    assert series == "KXBTC15M"
    assert preset["reference_index"] == "BRTI"


def test_series_ticker_resolves_to_its_preset_case_insensitively():
    assert resolve_series("kxbtc15m")[0] == "KXBTC15M"
    assert resolve_series("kxbtc15m")[1] is load_presets()["btc15m"]


def test_unknown_series_is_uppercased_without_preset():
    assert resolve_series("kxethd") == ("KXETHD", None)


def test_empty_series_fails():
    with pytest.raises(ClientError):
        resolve_series("  ")
