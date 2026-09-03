#!/usr/bin/env python3
"""Generate a synthetic .docx fixture for the edit-tracked hyperlink regression tests.

Reproduces the false-positive "an existing comment or tracked-change marker
sits inside the matched text" refusal that fired for any old_text spanning a
plain run, into a w:hyperlink's nested w:r, and back out to a trailing plain
run -- even when no comment or tracked change is anywhere near that text. The
fixture carries THREE paragraphs:

1. A comment (id=99) anchored to unrelated text, far from every edit target,
   so a regression that starts silently ignoring real comment overlaps would
   not be caught by the other two paragraphs alone.
2. HYPERLINK_TARGET: a plain run, then a w:hyperlink wrapping one w:r, then a
   trailing plain run. old_text spanning the full paragraph must cross the
   hyperlink boundary on both sides (the "whole wrapper consumed" case) and
   must succeed without touching comment 99.
3. TRUE_OVERLAP_TARGET: plain text with a *real* commentRangeStart/End
   (id=77) sitting inside it. A tracked edit whose old_text spans that text
   must still be refused -- this is the genuine protection the false-positive
   check exists for, and the hyperlink fix must not weaken it.

All text is synthetic -- no client content. Run this module to regenerate
``hyperlink-sample.docx`` next to it.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

UNRELATED_COMMENT_ANCHOR = "This sentence has nothing to do with the edits below."
HYPERLINK_BEFORE = "Before text "
HYPERLINK_TEXT = "link anchor text"
HYPERLINK_AFTER = " after text."
HYPERLINK_TARGET = HYPERLINK_BEFORE + HYPERLINK_TEXT + HYPERLINK_AFTER
TRUE_OVERLAP_TARGET = "alpha beta gamma."

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId105" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
  <Relationship Id="rId50" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/anchor" TargetMode="External"/>
</Relationships>
"""

DOCUMENT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p>
      <w:commentRangeStart w:id="99"/>
      <w:r><w:t xml:space="preserve">{UNRELATED_COMMENT_ANCHOR}</w:t></w:r>
      <w:commentRangeEnd w:id="99"/>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="99"/></w:r>
    </w:p>
    <w:p>
      <w:r><w:t xml:space="preserve">{HYPERLINK_BEFORE}</w:t></w:r>
      <w:hyperlink r:id="rId50"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t>{HYPERLINK_TEXT}</w:t></w:r></w:hyperlink>
      <w:r><w:t xml:space="preserve">{HYPERLINK_AFTER}</w:t></w:r>
    </w:p>
    <w:p>
      <w:commentRangeStart w:id="77"/>
      <w:r><w:t xml:space="preserve">alpha</w:t></w:r>
      <w:commentRangeEnd w:id="77"/>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="77"/></w:r>
      <w:r><w:t xml:space="preserve"> beta gamma.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:comment w:id="99" w:author="Original Reviewer" w:date="2026-01-05T09:30:00Z" w:initials="OR">
    <w:p>
      <w:r><w:t xml:space="preserve">Unrelated note, far from the hyperlink paragraph.</w:t></w:r>
    </w:p>
  </w:comment>
  <w:comment w:id="77" w:author="Original Reviewer" w:date="2026-01-05T09:31:00Z" w:initials="OR">
    <w:p>
      <w:r><w:t xml:space="preserve">This one genuinely overlaps the edit target.</w:t></w:r>
    </w:p>
  </w:comment>
</w:comments>
"""

PARTS = {
    "[Content_Types].xml": CONTENT_TYPES,
    "_rels/.rels": ROOT_RELS,
    "word/_rels/document.xml.rels": DOCUMENT_RELS,
    "word/document.xml": DOCUMENT,
    "word/comments.xml": COMMENTS,
}


def build(output_path: Path) -> Path:
    """Write the synthetic fixture .docx to ``output_path``."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in PARTS.items():
            archive.writestr(name, content.strip() + "\n")
    return output_path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "hyperlink-sample.docx"
    build(target)
    print(f"Wrote {target}")
