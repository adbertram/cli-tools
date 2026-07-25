"""Tests for the Source-CLI Sort Standard on `depop search`.

Covers the `resolve_sort` mapping/validation and the CLI-level rejection of
invalid `--sort` values. `resolve_sort` runs before any browser/network work,
so the CLI-level assertions need no Cloudflare-cleared session.
"""
import pytest
from typer.testing import CliRunner

from depop_cli.client import DEFAULT_SORT, SORT_VALUES, SortError, resolve_sort
from depop_cli.main import app

runner = CliRunner()


# --- resolve_sort: canonical mapping -------------------------------------

def test_default_sort_is_relevance():
    assert DEFAULT_SORT == "relevance"


def test_sort_values_are_price_and_relevance():
    assert set(SORT_VALUES) == {"price", "relevance"}


def test_price_natural_maps_to_price_ascending():
    assert resolve_sort("price") == "priceAscending"
    assert resolve_sort("price", desc=False) == "priceAscending"


def test_price_desc_maps_to_price_descending():
    assert resolve_sort("price", desc=True) == "priceDescending"


def test_price_sort_is_case_insensitive():
    assert resolve_sort("PRICE") == "priceAscending"


def test_relevance_maps_to_none_omit_param():
    # None => omit the `sort` param (Depop's own relevance default).
    assert resolve_sort("relevance") is None


# --- resolve_sort: fail-fast rejections ----------------------------------

def test_relevance_rejects_desc():
    with pytest.raises(SortError, match="--desc is not supported"):
        resolve_sort("relevance", desc=True)


def test_newest_rejected_with_chronological_message():
    with pytest.raises(SortError, match="chronological"):
        resolve_sort("newest")


def test_unknown_sort_rejected_with_valid_values():
    with pytest.raises(SortError) as exc:
        resolve_sort("bogus")
    msg = str(exc.value)
    assert "Invalid --sort 'bogus'" in msg
    assert "price" in msg and "relevance" in msg


def test_removed_legacy_values_are_now_invalid():
    # The old user-facing values were hard-replaced, not aliased.
    for legacy in ("price_asc", "price_desc"):
        with pytest.raises(SortError):
            resolve_sort(legacy)


# --- CLI surface ----------------------------------------------------------

def test_cli_rejects_bogus_sort_nonzero_exit():
    result = runner.invoke(app, ["search", "nike", "--sort", "bogus"])
    assert result.exit_code != 0


def test_cli_rejects_newest_sort_nonzero_exit():
    result = runner.invoke(app, ["search", "nike", "--sort", "newest"])
    assert result.exit_code != 0
