"""Regression tests for `google docs tables update` cell-skip behavior."""
from google_cli.commands.docs import _find_tables_in_document


def _text_elem(text, start):
    return {"startIndex": start, "endIndex": start + len(text), "textRun": {"content": text}}


def _paragraph(text, start):
    return {"startIndex": start, "endIndex": start + len(text), "paragraph": {"elements": [_text_elem(text, start)]}}


def _multi_paragraph_cell_document():
    """One table whose target cell holds three paragraphs."""
    paragraphs = []
    index = 10
    for text in ("PARA ONE\n", "EXTRA SECTION\n", "MORE EXTRA\n"):
        paragraphs.append(_paragraph(text, index))
        index += len(text)

    return {
        "body": {
            "content": [
                {
                    "startIndex": 1,
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"startIndex": 2, "endIndex": 9, "content": [_paragraph("Target Row\n", 3)]},
                                    {"startIndex": 9, "endIndex": index, "content": paragraphs},
                                ]
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_cell_content_spans_every_paragraph_not_just_the_first():
    """The skip comparison and the replace range must measure the same text."""
    cell = _find_tables_in_document(_multi_paragraph_cell_document())[0]["rows"][0][1]

    assert cell["content"] == "PARA ONE\nEXTRA SECTION\nMORE EXTRA"
    # text_start/text_end span the whole cell, so a write replaces all three
    # paragraphs. A new value equal to only the first paragraph is therefore a
    # real change and must not be skipped as "content unchanged".
    assert cell["content"].strip() != "PARA ONE"
    assert cell["text_start"] == 10
    assert cell["text_end"] == 10 + len("PARA ONE\nEXTRA SECTION\nMORE EXTRA\n")


def test_identical_full_cell_content_is_still_recognized_as_unchanged():
    document = _multi_paragraph_cell_document()
    cell = _find_tables_in_document(document)[0]["rows"][0][1]

    assert cell["content"].strip() == "PARA ONE\nEXTRA SECTION\nMORE EXTRA"


# --- CLI-level tests against a mocked Docs service -------------------------

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from google_cli.commands import docs

DOC_ID = "DOC_TEST"


def _table(start, rows):
    """Build a Docs API table element with real index arithmetic.

    rows is a list of rows, each a list of cell paragraph texts (each ending in
    "\\n"). An empty cell is the newline-only paragraph "\\n".
    """
    index = start + 1
    table_rows = []
    for row in rows:
        index += 1  # row marker
        cells = []
        for text in row:
            cell_start = index
            paragraph = _paragraph(text, cell_start + 1)
            index = paragraph["endIndex"]
            cells.append({"startIndex": cell_start, "endIndex": index, "content": [paragraph]})
        table_rows.append({"tableCells": cells})
    return {"startIndex": start, "endIndex": index + 1, "table": {"tableRows": table_rows}}


class _FakeDocsService:
    def __init__(self, document):
        self.document = document
        self.batches = []

    def documents(self):
        return self

    def get(self, documentId):
        return SimpleNamespace(execute=lambda: self.document)

    def batchUpdate(self, documentId, body):
        self.batches.append(body)
        return SimpleNamespace(execute=lambda: {})


def _install(monkeypatch, *tables):
    service = _FakeDocsService({"title": "Test Doc", "body": {"content": list(tables)}})
    monkeypatch.setattr(docs, "get_client", lambda **kwargs: SimpleNamespace(get_docs_service=lambda: service))
    return service


def _invoke(*args):
    return CliRunner().invoke(docs.app, ["tables", *args])


def test_empty_cell_range_is_its_newline_paragraph():
    """Issue #554 shape: cell 5396-5398 holding one "\\n" run at 5397-5398."""
    cell = _find_tables_in_document({"body": {"content": [_table(5379, [["Phase\n"], ["Done\n"], ["\n"]])]}})[0]["rows"][2][0]

    assert (cell["start_index"], cell["end_index"]) == (5396, 5398)
    assert (cell["text_start"], cell["text_end"]) == (5397, 5398)
    assert cell["content"] == ""


def test_single_update_into_empty_cell_inserts_at_paragraph_start(monkeypatch):
    service = _install(monkeypatch, _table(5379, [["Phase\n"], ["Done\n"], ["\n"]]))

    result = _invoke("update", DOC_ID, "--table", "0", "--row", "2", "--col", "0", "--content", "Enabling")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["updates"] == 1
    assert service.batches == [{"requests": [{"insertText": {"location": {"index": 5397}, "text": "Enabling"}}]}]


def test_batch_update_mixing_empty_and_filled_cells_orders_requests_descending(monkeypatch):
    # Cells: (0,0) "Name" 103-108, (0,1) empty 109-110, (1,0) empty 112-113, (1,1) "Old" 114-118.
    service = _install(monkeypatch, _table(100, [["Name\n", "\n"], ["\n", "Old\n"]]))
    data = json.dumps([
        {"table": 0, "row": 0, "col": 1, "content": "Alpha"},
        {"table": 0, "row": 1, "col": 1, "content": "New"},
        {"table": 0, "row": 1, "col": 0, "content": "Beta"},
        {"table": 0, "row": 0, "col": 0, "content": "Name"},
    ])

    result = _invoke("update", DOC_ID, "--data", data)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["updates"] == 3
    assert service.batches == [{"requests": [
        {"deleteContentRange": {"range": {"startIndex": 114, "endIndex": 117}}},
        {"insertText": {"location": {"index": 114}, "text": "New"}},
        {"insertText": {"location": {"index": 112}, "text": "Beta"}},
        {"insertText": {"location": {"index": 109}, "text": "Alpha"}},
    ]}]


def test_empty_cell_left_empty_is_unchanged(monkeypatch):
    service = _install(monkeypatch, _table(100, [["Name\n", "\n"]]))

    result = _invoke("update", DOC_ID, "--table", "0", "--row", "0", "--col", "1", "--content", "")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["updates"] == 0
    assert service.batches == []


def test_cell_without_paragraph_text_fails_instead_of_reporting_zero_updates(monkeypatch):
    table = _table(100, [["Name\n", "\n"]])
    table["table"]["tableRows"][0]["tableCells"][1]["content"] = []
    service = _install(monkeypatch, table)

    result = _invoke("update", DOC_ID, "--table", "0", "--row", "0", "--col", "1", "--content", "Value")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Cannot resolve the text range of table 0 row 0 col 1" in result.stderr
    assert service.batches == []


def _insert_row_request(table_start, row, below):
    return {"insertTableRow": {
        "tableCellLocation": {"tableStartLocation": {"index": table_start}, "rowIndex": row, "columnIndex": 0},
        "insertBelow": below,
    }}


def test_insert_rows_defaults_to_one_row_below(monkeypatch):
    service = _install(monkeypatch, _table(1, [["A\n"]]), _table(100, [["Name\n", "\n"], ["\n", "Old\n"]]))

    result = _invoke("insert-rows", DOC_ID, "--table", "1", "--row", "1")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "documentId": DOC_ID,
        "title": "Test Doc",
        "url": f"https://docs.google.com/document/d/{DOC_ID}/edit",
        "rowsInserted": 1,
    }
    assert service.batches == [{"requests": [_insert_row_request(100, 1, True)]}]


def test_insert_rows_multiple_above(monkeypatch):
    service = _install(monkeypatch, _table(100, [["Name\n", "\n"], ["\n", "Old\n"]]))

    result = _invoke("insert-rows", DOC_ID, "--table", "0", "--row", "0", "--count", "3", "--above")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["rowsInserted"] == 3
    assert service.batches == [{"requests": [_insert_row_request(100, 0, False)] * 3}]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--table", "1", "--row", "0"], "Table 1 not found (document has 1 tables)"),
        (["--table", "-1", "--row", "0"], "Table -1 not found (document has 1 tables)"),
        (["--table", "0", "--row", "2"], "Row 2 not found in table 0 (table has 2 rows)"),
        (["--table", "0", "--row", "-1"], "Row -1 not found in table 0 (table has 2 rows)"),
        (["--table", "0", "--row", "0", "--count", "0"], "--count must be at least 1 (got 0)"),
    ],
)
def test_insert_rows_rejects_out_of_bounds_input(monkeypatch, args, message):
    service = _install(monkeypatch, _table(100, [["Name\n", "\n"], ["\n", "Old\n"]]))

    result = _invoke("insert-rows", DOC_ID, *args)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert message in result.stderr
    assert service.batches == []
