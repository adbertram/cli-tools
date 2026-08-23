"""Tests for the cashflow command group.

Regression coverage for the date-ranged aggregate bug: the
``Web_GetCashFlowPage`` aggregates response nests the category group under
``groupBy.categoryGroup`` and the per-group total under ``summary.sum`` (and the
overall summary under ``summary[0].summary``). The old parser read those at the
top level of each element, so every row came back with an empty id/group and
``sum: 0``. The fixtures below mirror the real GraphQL shape captured live for
CY2025.
"""
import json

from typer.testing import CliRunner

from monarch_cli.commands import cashflow


runner = CliRunner()


def _by_category_group_response():
    """Real-shaped get_cashflow() response (subset of byCategoryGroup rows)."""
    return {
        "byCategory": [],
        "byCategoryGroup": [
            {
                "groupBy": {
                    "categoryGroup": {
                        "id": "189590009008460626",
                        "name": "Income",
                        "type": "income",
                        "__typename": "CategoryGroup",
                    },
                    "__typename": "AggregateGroupBy",
                },
                "summary": {"sum": 402405.56, "__typename": "TransactionsSummary"},
                "__typename": "AggregateData",
            },
            {
                "groupBy": {
                    "categoryGroup": {
                        "id": "189590009008460629",
                        "name": "Housing",
                        "type": "expense",
                        "__typename": "CategoryGroup",
                    },
                    "__typename": "AggregateGroupBy",
                },
                "summary": {"sum": -37704.02, "__typename": "TransactionsSummary"},
                "__typename": "AggregateData",
            },
            {
                "groupBy": {
                    "categoryGroup": {
                        "id": "189590009008460637",
                        "name": "Financial",
                        "type": "expense",
                        "__typename": "CategoryGroup",
                    },
                    "__typename": "AggregateGroupBy",
                },
                "summary": {"sum": -70475.56, "__typename": "TransactionsSummary"},
                "__typename": "AggregateData",
            },
        ],
        "byMerchant": [],
        "summary": [],
    }


def _summary_response():
    """Real-shaped get_cashflow_summary() response for a date range."""
    return {
        "summary": [
            {
                "summary": {
                    "sumIncome": 402405.56,
                    "sumExpense": -273585.70,
                    "savings": 128819.86,
                    "savingsRate": 0.32012445354880287,
                    "__typename": "TransactionsSummary",
                },
                "__typename": "AggregateData",
            }
        ]
    }


class FakeCashflowClient:
    """Records the dates it was called with so range plumbing can be asserted."""

    def __init__(self):
        self.cashflow_calls = []
        self.summary_calls = []

    def get_cashflow(self, limit=100, start_date=None, end_date=None):
        self.cashflow_calls.append(
            {"limit": limit, "start_date": start_date, "end_date": end_date}
        )
        return _by_category_group_response()

    def get_cashflow_summary(self, start_date=None, end_date=None):
        self.summary_calls.append({"start_date": start_date, "end_date": end_date})
        return _summary_response()


# ---------------------------------------------------------------------------
# cashflow list
# ---------------------------------------------------------------------------


def test_cashflow_list_returns_nonempty_grouped_rows(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app, ["list", "--start", "2025-01-01", "--end", "2025-12-31"]
    )

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    # Real per-category-group rows: non-empty id, group name, non-zero sum.
    assert rows == [
        {"id": "189590009008460626", "group": "Income", "sum": 402405.56},
        {"id": "189590009008460629", "group": "Housing", "sum": -37704.02},
        {"id": "189590009008460637", "group": "Financial", "sum": -70475.56},
    ]
    # The income-group total lands near the ~$402K CY2025 figure.
    income = next(r for r in rows if r["group"] == "Income")
    assert income["sum"] > 400000


def test_cashflow_list_passes_date_range_to_client(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app, ["list", "--start", "2025-01-01", "--end", "2025-12-31"]
    )

    assert result.exit_code == 0
    assert fake.cashflow_calls[0]["start_date"] == "2025-01-01"
    assert fake.cashflow_calls[0]["end_date"] == "2025-12-31"


def test_cashflow_list_filter_group_income(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app,
        [
            "list",
            "--start",
            "2025-01-01",
            "--end",
            "2025-12-31",
            "--filter",
            "group:Income",
        ],
    )

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows == [
        {"id": "189590009008460626", "group": "Income", "sum": 402405.56}
    ]


def test_cashflow_list_table_renders_income(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app,
        ["list", "--start", "2025-01-01", "--end", "2025-12-31", "--table"],
    )

    assert result.exit_code == 0
    assert "Income" in result.stdout
    assert "402405.56" in result.stdout.replace(",", "")


# ---------------------------------------------------------------------------
# cashflow summary
# ---------------------------------------------------------------------------


def test_cashflow_summary_range_returns_totals(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app, ["summary", "--start", "2025-01-01", "--end", "2025-12-31"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["sumIncome"] == 402405.56
    assert data["sumExpense"] == -273585.70
    assert data["savings"] == 128819.86


def test_cashflow_summary_passes_date_range_to_client(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app, ["summary", "--start", "2025-01-01", "--end", "2025-12-31"]
    )

    assert result.exit_code == 0
    assert fake.summary_calls[0] == {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
    }


def test_cashflow_summary_no_dates_still_works(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(cashflow.app, ["summary"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["sumIncome"] == 402405.56
    # No dates flow through as None so the SDK applies its current-month default.
    assert fake.summary_calls[0] == {"start_date": None, "end_date": None}


def test_cashflow_summary_table_savings_rate_is_percent(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app,
        ["summary", "--start", "2025-01-01", "--end", "2025-12-31", "--table"],
    )

    assert result.exit_code == 0
    # savingsRate 0.3201 must render as 32.0%, not 0.3%.
    assert "32.0%" in result.stdout


# ---------------------------------------------------------------------------
# cashflow get
# ---------------------------------------------------------------------------


def test_cashflow_get_resolves_group_by_id(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(
        cashflow.app,
        ["get", "189590009008460626", "--start", "2025-01-01", "--end", "2025-12-31"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "id": "189590009008460626",
        "group": "Income",
        "sum": 402405.56,
    }


def test_cashflow_get_unknown_group_exits_nonzero(monkeypatch):
    fake = FakeCashflowClient()
    monkeypatch.setattr(cashflow, "get_client", lambda: fake)

    result = runner.invoke(cashflow.app, ["get", "does-not-exist"])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# parser unit coverage
# ---------------------------------------------------------------------------


def test_extract_group_rows_reads_nested_paths():
    rows = cashflow._extract_group_rows(_by_category_group_response())
    assert rows[0] == {"id": "189590009008460626", "group": "Income", "sum": 402405.56}
    # Every row has a real id and non-placeholder group name.
    assert all(r["id"] and r["group"] for r in rows)


def test_extract_summary_reads_nested_path():
    summary = cashflow._extract_summary(_summary_response())
    assert summary["sumIncome"] == 402405.56
    assert summary["sumExpense"] == -273585.70
