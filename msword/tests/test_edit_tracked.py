"""Regression tests for MswordClient.apply_tracked_edits (docs edit-tracked).

Covers: plain-document batch edits produce well-formed w:ins/w:del pairs;
pre-existing comments AND pre-existing tracked changes survive a new batch
edit byte-for-byte; a batch containing an unmatched old_text raises
ClientError and leaves the file on disk unmodified; and multiple occurrences
of the same text within one batch each target the correct instance.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import docx
import pytest

from cli_tools_shared.exceptions import ClientError
from msword_cli.client import NSMAP, MswordClient

FIXTURE = Path(__file__).parent / "fixtures" / "tracked-changes-sample.docx"
W = NSMAP["w"]


def _make_doc(tmp_path: Path, name: str, text: str) -> Path:
    """Build a plain .docx with a single paragraph of text."""
    path = tmp_path / name
    doc = docx.Document()
    doc.add_paragraph(text)
    doc.save(path)
    return path


def _document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _find_all(root, tag):
    return root.findall(f".//{{{W}}}{tag}")


# ---------------------------------------------------------------------------
# 1. Plain document, no existing markup.
# ---------------------------------------------------------------------------


def test_batch_edits_produce_tracked_changes(tmp_path):
    path = _make_doc(
        tmp_path,
        "plain.docx",
        "The quick brown fox jumps over the lazy dog near the old barn.",
    )

    client = MswordClient()
    result = client.apply_tracked_edits(
        str(path),
        [
            {"old_text": "quick brown fox", "new_text": "swift red fox"},
            {"old_text": "lazy dog", "new_text": "sleepy cat"},
            {"old_text": "old barn", "new_text": "new shed"},
        ],
        author="Adam Bertram",
    )

    assert result.file == str(path)
    assert result.author == "Adam Bertram"
    assert result.edits_applied == 3
    assert [e.old_text for e in result.edits] == ["quick brown fox", "lazy dog", "old barn"]
    assert [e.new_text for e in result.edits] == ["swift red fox", "sleepy cat", "new shed"]

    # Every del/ins id is unique across the whole batch.
    ids = []
    for edit in result.edits:
        ids.extend([edit.del_id, edit.ins_id])
    assert len(ids) == len(set(ids))

    root = ET.fromstring(_document_xml(path))
    del_els = _find_all(root, "del")
    ins_els = _find_all(root, "ins")
    assert len(del_els) == 3
    assert len(ins_els) == 3

    for del_el, expected_old, expected_id in zip(
        del_els, ["quick brown fox", "lazy dog", "old barn"], [e.del_id for e in result.edits]
    ):
        assert del_el.get(f"{{{W}}}id") == expected_id
        assert del_el.get(f"{{{W}}}author") == "Adam Bertram"
        assert del_el.get(f"{{{W}}}date", "").endswith("Z")
        del_text_els = del_el.findall(f".//{{{W}}}delText")
        assert "".join(t.text or "" for t in del_text_els) == expected_old
        # No w:t should remain inside a w:del.
        assert del_el.findall(f".//{{{W}}}t") == []

    for ins_el, expected_new, expected_id in zip(
        ins_els, ["swift red fox", "sleepy cat", "new shed"], [e.ins_id for e in result.edits]
    ):
        assert ins_el.get(f"{{{W}}}id") == expected_id
        assert ins_el.get(f"{{{W}}}author") == "Adam Bertram"
        t_els = ins_el.findall(f".//{{{W}}}t")
        assert "".join(t.text or "" for t in t_els) == expected_new

    # The document still opens cleanly with python-docx afterward.
    reopened = docx.Document(str(path))
    assert reopened.paragraphs


# ---------------------------------------------------------------------------
# 2. Pre-existing comment AND pre-existing tracked change must survive.
# ---------------------------------------------------------------------------


def test_preexisting_comment_and_tracked_change_survive_new_edits(tmp_path):
    path = tmp_path / "existing-markup.docx"
    shutil.copyfile(FIXTURE, path)

    client = MswordClient()
    before_comments = client.extract_comments(str(path))
    assert len(before_comments) == 1
    assert before_comments[0].id == "5"

    before_root = ET.fromstring(_document_xml(path))
    before_del = _find_all(before_root, "del")[0]
    before_ins = _find_all(before_root, "ins")[0]
    assert before_del.get(f"{{{W}}}id") == "10"
    assert before_ins.get(f"{{{W}}}id") == "11"

    result = client.apply_tracked_edits(
        str(path),
        [{"old_text": "updated roadmap", "new_text": "revised roadmap"}],
        author="Adam Bertram",
    )
    assert result.edits_applied == 1
    # New ids must not collide with the existing comment (5) or tracked-change (10, 11) ids.
    assert result.edits[0].del_id not in {"5", "10", "11"}
    assert result.edits[0].ins_id not in {"5", "10", "11"}

    after_comments = client.extract_comments(str(path))
    assert after_comments == before_comments

    after_root = ET.fromstring(_document_xml(path))
    after_del = next(e for e in _find_all(after_root, "del") if e.get(f"{{{W}}}id") == "10")
    after_ins = next(e for e in _find_all(after_root, "ins") if e.get(f"{{{W}}}id") == "11")

    assert after_del.get(f"{{{W}}}author") == "Prior Author"
    assert after_ins.get(f"{{{W}}}author") == "Prior Author"
    assert "".join(t.text or "" for t in after_del.findall(f".//{{{W}}}delText")) == "old goal"
    assert "".join(t.text or "" for t in after_ins.findall(f".//{{{W}}}t")) == "new goal"

    # New del/ins pair exists for the new edit, attributed to the new author.
    new_del = next(e for e in _find_all(after_root, "del") if e.get(f"{{{W}}}id") == result.edits[0].del_id)
    new_ins = next(e for e in _find_all(after_root, "ins") if e.get(f"{{{W}}}id") == result.edits[0].ins_id)
    assert new_del.get(f"{{{W}}}author") == "Adam Bertram"
    assert new_ins.get(f"{{{W}}}author") == "Adam Bertram"

    reopened = docx.Document(str(path))
    assert reopened.paragraphs


# ---------------------------------------------------------------------------
# 3. Unmatched old_text raises ClientError and does not modify the file.
# ---------------------------------------------------------------------------


def test_unmatched_old_text_raises_and_leaves_file_unmodified(tmp_path):
    path = _make_doc(tmp_path, "unmatched.docx", "Alpha beta gamma delta.")
    original_bytes = path.read_bytes()

    client = MswordClient()
    with pytest.raises(ClientError, match="Reference text not found"):
        client.apply_tracked_edits(
            str(path),
            [
                {"old_text": "alpha beta", "new_text": "x"},
                {"old_text": "does-not-exist-anywhere", "new_text": "y"},
            ],
            author="Adam Bertram",
        )

    assert path.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# 4. Multiple occurrences of the same text, different occurrence values.
# ---------------------------------------------------------------------------


def test_multiple_occurrences_target_correct_instance(tmp_path):
    path = _make_doc(
        tmp_path,
        "occurrences.docx",
        "widget one. widget two. widget three.",
    )

    client = MswordClient()
    # Editing highest occurrence first keeps earlier occurrence numbers stable
    # for the edits that follow in the same batch (see apply_tracked_edits docstring).
    result = client.apply_tracked_edits(
        str(path),
        [
            {"old_text": "widget", "new_text": "gadget", "occurrence": 3},
            {"old_text": "widget", "new_text": "gizmo", "occurrence": 1},
        ],
        author="Adam Bertram",
    )
    assert result.edits_applied == 2

    root = ET.fromstring(_document_xml(path))
    ins_els = _find_all(root, "ins")
    # Elements appear in document order (occurrence 1 precedes occurrence 3),
    # regardless of the order edits were listed/applied in the batch.
    ins_texts = ["".join(t.text or "" for t in el.findall(f".//{{{W}}}t")) for el in ins_els]
    assert ins_texts == ["gizmo", "gadget"]

    del_els = _find_all(root, "del")
    assert len(del_els) == 2
    for el in del_els:
        assert "".join(t.text or "" for t in el.findall(f".//{{{W}}}delText")) == "widget"

    # "widget two" (the untouched middle occurrence) is still plain, unedited text.
    full_text = "".join(t.text or "" for t in _find_all(root, "t"))
    assert "widget two" in full_text
