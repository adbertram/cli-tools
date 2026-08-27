"""Tests for `bricklink catalog part-out-value`."""
from unittest.mock import MagicMock

import pytest
import typer

from bricklink_cli.commands.catalog import _part_out_lots, catalog_part_out_value


SUBSETS = [
    {
        "match_no": 0,
        "entries": [
            {
                "item": {"no": "3001", "name": "Brick 2 x 4", "type": "PART", "category_id": 5},
                "color_id": 11,
                "quantity": 4,
                "extra_quantity": 1,
                "is_alternate": False,
                "is_counterpart": False,
            },
        ],
    },
    {
        "match_no": 1,
        "entries": [
            {
                "item": {"no": "3622", "name": "Brick 1 x 3", "type": "PART", "category_id": 5},
                "color_id": 86,
                "quantity": 2,
                "extra_quantity": 0,
                "is_alternate": False,
                "is_counterpart": False,
            },
            {
                "item": {"no": "3622b", "name": "Alt Brick", "type": "PART", "category_id": 5},
                "color_id": 86,
                "quantity": 2,
                "extra_quantity": 0,
                "is_alternate": True,
                "is_counterpart": False,
            },
        ],
    },
    {
        "match_no": 0,
        "entries": [
            {
                "item": {"no": "sw0139", "name": "Some Fig", "type": "MINIFIG", "category_id": 273},
                "color_id": 0,
                "quantity": 1,
                "extra_quantity": 0,
                "is_alternate": False,
                "is_counterpart": False,
            },
        ],
    },
]

PRICES = {
    ("PART", "3001", 11): {"avg_price": "0.1000", "unit_quantity": 500, "total_quantity": 4000},
    ("PART", "3622", 86): {"avg_price": "0.0500", "unit_quantity": 300, "total_quantity": 2000},
    ("MINIFIG", "sw0139", None): {"avg_price": "5.0000", "unit_quantity": 40, "total_quantity": 50},
}


def _mock_client(prices=PRICES, subsets=SUBSETS):
    client = MagicMock()
    client.get_subsets.return_value = subsets

    def _price_guide(item_type, item_no, color_id=None, **kwargs):
        return dict(prices[(item_type, item_no, color_id)])

    client.get_price_guide.side_effect = _price_guide
    return client


def _call(set_no, **kwargs):
    """Call the command directly with typer defaults resolved to real values."""
    params = dict(
        condition="U", sold=True, include_figs=True,
        country=None, region=None, currency=None, table=False,
    )
    params.update(kwargs)
    catalog_part_out_value(set_no, **params)


def _run(monkeypatch, client, **kwargs):
    printed = []
    monkeypatch.setattr("bricklink_cli.commands.catalog.get_client", lambda: client)
    monkeypatch.setattr("bricklink_cli.commands.catalog.print_json", printed.append)
    _call("7662-1", **kwargs)
    assert len(printed) == 1
    return printed[0]


def _expect_exit(monkeypatch, client, set_no="7662-1", **kwargs):
    monkeypatch.setattr("bricklink_cli.commands.catalog.get_client", lambda: client)
    with pytest.raises(typer.Exit) as exc_info:
        _call(set_no, **kwargs)
    assert exc_info.value.exit_code != 0


def test_part_out_lots_skips_alternates_and_sums_extra_quantity():
    lots = _part_out_lots(SUBSETS)
    assert lots == [
        {"type": "PART", "no": "3001", "color_id": 11, "qty": 5},
        {"type": "PART", "no": "3622", "color_id": 86, "qty": 2},
        {"type": "MINIFIG", "no": "sw0139", "color_id": 0, "qty": 1},
    ]


def test_part_out_value_totals_and_subtotals(monkeypatch):
    client = _mock_client()
    result = _run(monkeypatch, client)

    assert result["set_no"] == "7662-1"
    assert result["condition"] == "U"
    assert result["guide"] == "sold"
    assert result["parts"] == {"lots": 2, "pieces": 7, "value": 0.6}
    assert result["figs"] == {"lots": 1, "count": 1, "value": 5.0}
    assert result["total_value"] == 5.6
    assert result["unpriced"] == []
    assert result["unpriced_count"] == 0
    assert [r["no"] for r in result["rows"]] == ["sw0139", "3001", "3622"]
    row = next(r for r in result["rows"] if r["no"] == "3001")
    assert row == {
        "type": "PART", "no": "3001", "color_id": 11, "qty": 5,
        "avg_price": 0.1, "line_value": 0.5, "times_sold_or_qty_avail": 500,
    }

    # Subsets fetched once for the set; every price lookup is condition U + sold.
    client.get_subsets.assert_called_once_with("SET", "7662-1")
    for call in client.get_price_guide.call_args_list:
        assert call.kwargs["condition"] == "U"
        assert call.kwargs["guide_type"] == "sold"


def test_minifig_price_lookup_omits_color(monkeypatch):
    client = _mock_client()
    _run(monkeypatch, client)
    fig_call = next(
        call for call in client.get_price_guide.call_args_list
        if call.kwargs["item_type"] == "MINIFIG"
    )
    assert fig_call.kwargs["color_id"] is None


def test_exclude_figs_reports_figs_but_omits_from_total(monkeypatch):
    client = _mock_client()
    result = _run(monkeypatch, client, include_figs=False)
    assert result["figs"] == {"lots": 1, "count": 1, "value": 5.0}
    assert result["total_value"] == 0.6


def test_stock_guide_uses_total_quantity_for_availability(monkeypatch):
    client = _mock_client()
    result = _run(monkeypatch, client, sold=False)
    assert result["guide"] == "stock"
    row = next(r for r in result["rows"] if r["no"] == "3001")
    assert row["times_sold_or_qty_avail"] == 4000
    for call in client.get_price_guide.call_args_list:
        assert call.kwargs["guide_type"] == "stock"


def test_unpriced_lot_reported_and_excluded(monkeypatch):
    prices = dict(PRICES)
    prices[("PART", "3622", 86)] = {"avg_price": "0.0000", "unit_quantity": 0, "total_quantity": 0}
    client = _mock_client(prices=prices)
    result = _run(monkeypatch, client)
    assert result["unpriced"] == [{"type": "PART", "no": "3622", "color_id": 86, "qty": 2}]
    assert result["unpriced_count"] == 1
    assert result["parts"] == {"lots": 1, "pieces": 5, "value": 0.5}
    assert result["total_value"] == 5.5


def test_failed_price_lookup_lands_in_unpriced_with_error(monkeypatch):
    client = _mock_client()

    def _price_guide(item_type, item_no, color_id=None, **kwargs):
        if item_no == "3622":
            raise RuntimeError("Bricklink API error 429: quota exceeded")
        return dict(PRICES[(item_type, item_no, color_id)])

    client.get_price_guide.side_effect = _price_guide
    result = _run(monkeypatch, client)
    assert result["unpriced"] == [{
        "type": "PART", "no": "3622", "color_id": 86, "qty": 2,
        "error": "Bricklink API error 429: quota exceeded",
    }]
    assert result["unpriced_count"] == 1
    assert result["parts"] == {"lots": 1, "pieces": 5, "value": 0.5}


def test_condition_is_case_normalized(monkeypatch):
    client = _mock_client()
    result = _run(monkeypatch, client, condition="u")
    assert result["condition"] == "U"
    for call in client.get_price_guide.call_args_list:
        assert call.kwargs["condition"] == "U"


def test_aborts_when_majority_unpriced(monkeypatch):
    empty = {"avg_price": "0.0000", "unit_quantity": 0, "total_quantity": 0}
    prices = {key: empty for key in PRICES}
    _expect_exit(monkeypatch, _mock_client(prices=prices))


def test_aborts_when_subsets_call_fails(monkeypatch):
    from cli_tools_shared.exceptions import ClientError

    client = MagicMock()
    client.get_subsets.side_effect = ClientError("Bricklink API error 404: not found")
    _expect_exit(monkeypatch, client, set_no="bogus-1")
    client.get_price_guide.assert_not_called()


def test_rejects_invalid_condition(monkeypatch):
    _expect_exit(monkeypatch, _mock_client(), condition="X")
