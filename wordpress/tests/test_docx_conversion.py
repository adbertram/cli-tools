from io import BytesIO
from zipfile import ZipFile

from wordpress_cli.utils.docx import _normalize_docx_relationship_targets


def test_should_normalize_parent_relative_docx_relationship_targets():
    source = BytesIO()
    relationships = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image.png"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image2.png"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/>
</Relationships>"""

    with ZipFile(source, "w") as archive:
        archive.writestr("word/_rels/document.xml.rels", relationships)
        archive.writestr("media/image.png", b"first")
        archive.writestr("media/image2.png", b"second")

    source.seek(0)

    normalized = _normalize_docx_relationship_targets(source)

    with ZipFile(normalized, "r") as archive:
        normalized_relationships = archive.read("word/_rels/document.xml.rels")
        assert b'Target="/media/image.png"' in normalized_relationships
        assert b'Target="/media/image2.png"' in normalized_relationships
        assert b'Target="https://example.com"' in normalized_relationships
        assert archive.read("media/image.png") == b"first"
