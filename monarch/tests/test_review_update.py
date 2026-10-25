"""Review clearing must survive the actual Typer option parser."""
from unittest.mock import Mock

from typer.testing import CliRunner

from monarch_cli.commands import transactions


def test_review_status_true_false_and_omitted(monkeypatch):
    client = Mock()
    client.update_transaction.return_value = {"id": "txn"}
    monkeypatch.setattr(transactions, "get_client", lambda: client)
    for options, expected in [([], None), (["--needs-review"], True), (["--no-needs-review"], False)]:
        result = CliRunner().invoke(transactions.app, ["update", "txn", "--category", "cat", *options])
        assert result.exit_code == 0, result.output
        assert client.update_transaction.call_args.kwargs["needs_review"] is expected
