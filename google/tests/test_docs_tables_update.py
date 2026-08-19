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
