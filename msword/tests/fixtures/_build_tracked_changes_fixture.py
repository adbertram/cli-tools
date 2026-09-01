#!/usr/bin/env python3
"""Generate a synthetic .docx fixture for the edit-tracked regression tests.

The fixture carries BOTH an existing comment (word/comments.xml plus
commentRangeStart/commentRangeEnd/commentReference markers, id=5, author
"Original Reviewer") AND an existing tracked-change replacement (w:del id=10 /
w:ins id=11, author "Prior Author") alongside plain untouched text that a new
batch of ``docs edit-tracked`` edits can target. Tests must prove both the
pre-existing comment and the pre-existing tracked change survive a new batch
edit byte-for-byte, and that new w:ins/w:del ids never collide with 5/10/11.

All text is synthetic — no client content. Run this module to regenerate
``tracked-changes-sample.docx`` next to it.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

COMMENT_ANCHOR = "The quarterly rollout plan needs a clearer owner."
PRIOR_DELETED = "old goal"
PRIOR_INSERTED = "new goal"
TARGET_SENTENCE = "Please review the updated roadmap carefully before the meeting."

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
</Relationships>
"""

DOCUMENT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:commentRangeStart w:id="5"/>
      <w:r><w:t xml:space="preserve">{COMMENT_ANCHOR}</w:t></w:r>
      <w:commentRangeEnd w:id="5"/>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="5"/></w:r>
    </w:p>
    <w:p>
      <w:r><w:t xml:space="preserve">Team, please align on the </w:t></w:r>
      <w:del w:id="10" w:author="Prior Author" w:date="2026-01-02T08:00:00Z"><w:r><w:delText>{PRIOR_DELETED}</w:delText></w:r></w:del>
      <w:ins w:id="11" w:author="Prior Author" w:date="2026-01-02T08:00:00Z"><w:r><w:t>{PRIOR_INSERTED}</w:t></w:r></w:ins>
      <w:r><w:t xml:space="preserve"> before Friday.</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t xml:space="preserve">{TARGET_SENTENCE}</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:comment w:id="5" w:author="Original Reviewer" w:date="2026-01-05T09:30:00Z" w:initials="OR">
    <w:p>
      <w:r><w:t xml:space="preserve">Please assign a single owner here.</w:t></w:r>
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
    target = Path(__file__).resolve().parent / "tracked-changes-sample.docx"
    build(target)
    print(f"Wrote {target}")
