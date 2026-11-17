import json
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from google_cli.commands import docs


@pytest.mark.parametrize(("args", "mode"), [
    ([], "PREVIEW_WITHOUT_SUGGESTIONS"),
    (["--include-suggestions"], "PREVIEW_SUGGESTIONS_ACCEPTED"),
])
def test_read_requests_a_clean_suggestions_view(monkeypatch, args, mode):
    service = Mock()
    get_document = service.documents.return_value.get
    get_document.return_value.execute.return_value = {
        "documentId": "document_TEST",
        "title": "Course requirements",
        "body": {"content": [{"paragraph": {"elements": [
            {"textRun": {"content": "Show the original objective.\n"}},
        ]}}]},
    }
    client = Mock()
    client.get_docs_service.return_value = service
    monkeypatch.setattr(docs, "get_client", Mock(return_value=client))

    result = CliRunner().invoke(docs.app, ["read", "document_TEST", *args])

    assert result.exit_code == 0, result.output
    get_document.assert_called_once_with(
        documentId="document_TEST",
        suggestionsViewMode=mode,
    )
    assert json.loads(result.stdout)["content"] == "Show the original objective.\n"
