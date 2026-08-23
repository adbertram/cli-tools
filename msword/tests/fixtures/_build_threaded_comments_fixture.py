#!/usr/bin/env python3
"""Generate a synthetic .docx fixture for the comment-extraction regression test.

The fixture reproduces the real-world shape that broke ``docs comments list``:

* It carries the sibling comment parts ``commentsIds``, ``commentsExtended``,
  and ``commentsExtensible`` whose relationship types all contain the substring
  ``comments``. A reader that selects the comments part with
  ``"comments" in rel.reltype`` grabs ``commentsIds`` (metadata, no
  ``w:comment`` elements) and returns ``[]``.
* ``word/comments.xml`` contains BOTH a classic comment (small integer
  ``w:id``) AND a modern threaded comment (large integer ``w:id``, a ``w:date``
  WITHOUT the trailing ``Z``, and a redundant ``xmlns:w`` redeclaration on the
  element, exactly as Word emits for collaborative/threaded replies).

All text is synthetic — no client content. Run this module to regenerate
``threaded-comments-sample.docx`` next to it.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

# Synthetic anchored sentences (one per comment) and the comment bodies.
ANCHOR_ONE = "The quarterly rollout plan needs a clearer owner."
ANCHOR_TWO = "We should pilot the new workflow before the full launch."

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
  <Override PartName="/word/commentsExtended.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"/>
  <Override PartName="/word/commentsIds.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.commentsIds+xml"/>
  <Override PartName="/word/commentsExtensible.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtensible+xml"/>
  <Override PartName="/word/people.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.peopleMetadata+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

# Sibling comment relationships are intentionally ordered BEFORE the real
# comments relationship so a buggy "first substring match" reader selects the
# wrong part.
DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId101" Type="http://schemas.microsoft.com/office/2016/09/relationships/commentsIds" Target="commentsIds.xml"/>
  <Relationship Id="rId102" Type="http://schemas.microsoft.com/office/2011/relationships/commentsExtended" Target="commentsExtended.xml"/>
  <Relationship Id="rId103" Type="http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible" Target="commentsExtensible.xml"/>
  <Relationship Id="rId104" Type="http://schemas.microsoft.com/office/2011/relationships/people" Target="people.xml"/>
  <Relationship Id="rId105" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>
"""

DOCUMENT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:commentRangeStart w:id="3"/>
      <w:r><w:t xml:space="preserve">{ANCHOR_ONE}</w:t></w:r>
      <w:commentRangeEnd w:id="3"/>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="3"/></w:r>
    </w:p>
    <w:p>
      <w:commentRangeStart w:id="1402838193"/>
      <w:r><w:t xml:space="preserve">{ANCHOR_TWO}</w:t></w:r>
      <w:commentRangeEnd w:id="1402838193"/>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="1402838193"/></w:r>
    </w:p>
  </w:body>
</w:document>
"""

# Classic comment: small integer id, w:date ends with "Z".
# Modern threaded comment: large integer id, w:date WITHOUT "Z", and a
# redundant xmlns:w redeclaration on the <w:comment> element.
COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">
  <w:comment w:id="3" w:author="Dana Lake" w:date="2026-01-05T09:30:00Z" w:initials="DL">
    <w:p>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r>
      <w:r><w:t xml:space="preserve">Please assign a single owner here.</w:t></w:r>
    </w:p>
  </w:comment>
  <w:comment w:id="1402838193" w:author="Priya Anand" w:date="2026-02-11T14:07:42" w:initials="PA" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:p w14:paraId="5AC10F22" w14:textId="5AC10F22" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:pPr><w:pStyle w:val="CommentText"/></w:pPr>
      <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r>
      <w:r><w:t xml:space="preserve">Agreed, a limited pilot first sounds right.</w:t></w:r>
    </w:p>
  </w:comment>
</w:comments>
"""

COMMENTS_EXTENDED = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w15:commentEx w15:paraId="5AC10F22" w15:done="0"/>
</w15:commentsEx>
"""

COMMENTS_IDS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cid:commentsIds xmlns:w16cid="http://schemas.microsoft.com/office/word/2016/wordml/cid">
  <w16cid:commentId w16cid:paraId="5AC10F22" w16cid:durableId="1A2B3C4D"/>
</w16cid:commentsIds>
"""

COMMENTS_EXTENSIBLE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cex:commentsExtensible xmlns:w16cex="http://schemas.microsoft.com/office/word/2018/wordml/cex"/>
"""

PEOPLE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w15:person w15:author="Priya Anand">
    <w15:presenceInfo w15:providerId="None" w15:userId="Priya Anand"/>
  </w15:person>
</w15:people>
"""

PARTS = {
    "[Content_Types].xml": CONTENT_TYPES,
    "_rels/.rels": ROOT_RELS,
    "word/_rels/document.xml.rels": DOCUMENT_RELS,
    "word/document.xml": DOCUMENT,
    "word/comments.xml": COMMENTS,
    "word/commentsExtended.xml": COMMENTS_EXTENDED,
    "word/commentsIds.xml": COMMENTS_IDS,
    "word/commentsExtensible.xml": COMMENTS_EXTENSIBLE,
    "word/people.xml": PEOPLE,
}


def build(output_path: Path) -> Path:
    """Write the synthetic fixture .docx to ``output_path``."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in PARTS.items():
            archive.writestr(name, content.strip() + "\n")
    return output_path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "threaded-comments-sample.docx"
    build(target)
    print(f"Wrote {target}")
