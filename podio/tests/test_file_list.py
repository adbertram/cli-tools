"""Regression tests for listing files attached to Podio objects."""

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from podio_cli.commands import file

runner = CliRunner()


@pytest.mark.parametrize(
    ("ref_type", "area", "method"),
    [
        ("item", "Item", "find"),
        ("task", "Task", "find"),
        ("comment", "Comment", "get"),
        ("status", "Status", "find"),
        ("space", "Space", "find"),
    ],
)
def test_file_list_reads_files_from_the_referenced_object(monkeypatch, ref_type, area, method):
    files = [{"file_id": 501, "name": f"{ref_type}.pdf"}]
    client = MagicMock()
    getattr(getattr(client, area), method).return_value = {"files": files}
    monkeypatch.setattr(file, "get_client", lambda: client)

    result = runner.invoke(file.app, ["list", ref_type, "123"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"file_id": 501, "id": 501, "name": f"{ref_type}.pdf"}]
    getattr(getattr(client, area), method).assert_called_once_with(123)
    assert not client.Files.transport.GET.called
