"""Msword client for reading, converting, and extracting comments from Word documents."""
import os
from datetime import datetime, timezone
from typing import List
from xml.etree import ElementTree as ET

import docx
import mammoth
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .models import Comment, DocumentContent, ConvertedDocument, AddCommentResult

from cli_tools_shared.exceptions import ClientError

# Word XML namespaces
NSMAP = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
}

for _prefix, _uri in NSMAP.items():
    ET.register_namespace(_prefix, _uri)
ET.register_namespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')

COMMENTS_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"


def _validate_file(file_path: str) -> str:
    """Validate that the file exists and is a .docx file."""
    path = os.path.expanduser(file_path)
    if not os.path.isfile(path):
        raise ClientError(f"File not found: {path}")
    if not path.lower().endswith(".docx"):
        raise ClientError(f"Not a Word document (.docx): {path}")
    return path


class MswordClient:
    """Client for processing Word documents."""

    def read_document(self, file_path: str) -> DocumentContent:
        """Read text content from a Word document.

        Args:
            file_path: Path to the .docx file

        Returns:
            DocumentContent model with full text
        """
        path = _validate_file(file_path)
        doc = docx.Document(path)

        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)

        return DocumentContent(
            file=path,
            paragraphs=len(paragraphs),
            content="\n\n".join(paragraphs),
        )

    def convert_to_markdown(self, file_path: str) -> ConvertedDocument:
        """Convert a Word document to Markdown.

        Args:
            file_path: Path to the .docx file

        Returns:
            ConvertedDocument model with markdown content
        """
        path = _validate_file(file_path)

        with open(path, "rb") as f:
            result = mammoth.convert_to_markdown(f)

        return ConvertedDocument(
            file=path,
            markdown=result.value,
            messages=[str(m) for m in result.messages],
        )

    def extract_comments(self, file_path: str) -> List[Comment]:
        """Extract comments with their referenced context from a Word document.

        Parses the document XML to find comment markers and extracts
        the text between commentRangeStart and commentRangeEnd elements.

        Args:
            file_path: Path to the .docx file

        Returns:
            List of Comment models with context
        """
        path = _validate_file(file_path)
        doc = docx.Document(path)

        # Extract comments from comments.xml part
        comments_part = None
        for rel in doc.part.rels.values():
            if "comments" in rel.reltype:
                comments_part = rel.target_part
                break

        if comments_part is None:
            return []

        # Parse comments XML
        comments_xml = ET.fromstring(comments_part.blob)
        comment_data = {}
        for comment_el in comments_xml.findall("w:comment", NSMAP):
            cid = comment_el.get(f'{{{NSMAP["w"]}}}id')
            author = comment_el.get(f'{{{NSMAP["w"]}}}author', "Unknown")
            date = comment_el.get(f'{{{NSMAP["w"]}}}date')

            # Get comment text from all paragraphs/runs
            texts = []
            for t_el in comment_el.iter(f'{{{NSMAP["w"]}}}t'):
                if t_el.text:
                    texts.append(t_el.text)

            comment_data[cid] = {
                "id": cid,
                "author": author,
                "date": date,
                "text": " ".join(texts),
            }

        # Extract context for each comment from the document body
        body_xml = doc.element.body
        context_map = self._extract_comment_contexts(body_xml)

        # Build Comment models
        comments = []
        for cid, data in comment_data.items():
            context = context_map.get(cid)
            comments.append(
                Comment(
                    id=data["id"],
                    author=data["author"],
                    date=data["date"],
                    text=data["text"],
                    context=context,
                )
            )

        return comments

    def get_comment(self, file_path: str, comment_id: str) -> Comment:
        """Return a single comment by ID from a Word document."""
        comments = self.extract_comments(file_path)
        for comment in comments:
            if comment.id == comment_id:
                return comment
        raise ClientError(f"Comment not found: {comment_id}")

    def add_comment(
        self, file_path: str, text: str, author: str, reference_text: str, occurrence: int = 1
    ) -> AddCommentResult:
        """Add an inline comment anchored to specific text in a Word document."""
        if not reference_text:
            raise ClientError("reference_text cannot be empty")
        if not text.strip():
            raise ClientError("Comment text cannot be empty")
        if not author.strip():
            raise ClientError("Author cannot be empty")
        if occurrence < 1:
            raise ClientError("occurrence must be a positive integer")

        path = _validate_file(file_path)
        doc = docx.Document(path)

        start_el, end_el = self._find_reference_text(doc, reference_text, occurrence)

        comments_part = self._get_comments_part(doc)
        next_id = self._get_next_comment_id(doc, comments_part)

        self._add_comment_xml(comments_part, next_id, text, author)
        self._insert_comment_markers(start_el, end_el, next_id)

        doc.save(path)

        return AddCommentResult(
            file=path,
            comment_id=str(next_id),
            author=author,
            text=text,
            reference_text=reference_text,
        )

    def _find_reference_text(self, doc, reference_text: str, occurrence: int):
        """Find and isolate the run elements containing the target text.

        Searches body paragraphs, table cells, headers, and footers.
        Returns (start_run_el, end_run_el) after splitting boundary runs.
        """
        count = 0
        for para_el in self._iter_paragraph_elements(doc):
            run_els = list(para_el.iter(qn("w:r")))
            if not run_els:
                continue
            runs_text = "".join(self._run_el_text(r) for r in run_els)
            start = 0
            while True:
                idx = runs_text.find(reference_text, start)
                if idx == -1:
                    break
                count += 1
                if count == occurrence:
                    end_pos = idx + len(reference_text)
                    return self._isolate_match_runs(run_els, idx, end_pos)
                start = idx + 1

        raise ClientError(
            f"Reference text not found: '{reference_text}'"
            + (f" (occurrence {occurrence})" if occurrence > 1 else "")
        )

    def _iter_paragraph_elements(self, doc):
        """Yield all w:p elements: body (including tables), headers, footers."""
        for p_el in doc.element.body.iter(qn("w:p")):
            yield p_el
        seen = set()
        for section in doc.sections:
            for part in (section.header, section.footer):
                if part is None:
                    continue
                el_id = id(part._element)
                if el_id in seen:
                    continue
                seen.add(el_id)
                for p_el in part._element.iter(qn("w:p")):
                    yield p_el

    def _run_el_text(self, run_el):
        """Get text from a w:r element's w:t children."""
        return "".join(t.text for t in run_el.findall(qn("w:t")) if t.text)

    def _isolate_match_runs(self, run_els, match_start: int, match_end: int):
        """Find which runs contain the match, split at boundaries, return (start_el, end_el).

        Handles both single-run and multi-run matches by splitting boundary runs
        so that only the matched text is inside the returned range.
        """
        current_pos = 0
        first_idx = last_idx = None
        first_local_start = last_local_end = 0

        for i, run_el in enumerate(run_els):
            text_len = len(self._run_el_text(run_el))
            if first_idx is None and current_pos + text_len > match_start:
                first_idx = i
                first_local_start = match_start - current_pos
            if current_pos + text_len >= match_end:
                last_idx = i
                last_local_end = match_end - current_pos
                break
            current_pos += text_len

        if first_idx is None or last_idx is None:
            raise ClientError("Failed to map reference text to document runs")

        first_el = run_els[first_idx]
        last_el = run_els[last_idx]

        if first_local_start > 0:
            first_text = self._run_el_text(first_el)
            before_run = self._clone_run(first_el, first_text[:first_local_start])
            first_el.addprevious(before_run)
            self._set_run_text(first_el, first_text[first_local_start:])
            if first_idx == last_idx:
                last_local_end -= first_local_start

        last_text = self._run_el_text(last_el)
        if last_local_end < len(last_text):
            after_run = self._clone_run(last_el, last_text[last_local_end:])
            last_el.addnext(after_run)
            self._set_run_text(last_el, last_text[:last_local_end])

        return first_el, last_el

    def _set_run_text(self, run_el, text: str):
        """Set run text by replacing w:t elements only, preserving w:br/w:tab/etc."""
        for t in list(run_el.findall(qn("w:t"))):
            run_el.remove(t)
        new_t = OxmlElement("w:t")
        new_t.text = text
        if text and (text[0] == " " or text[-1] == " "):
            new_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        rPr = run_el.find(qn("w:rPr"))
        if rPr is not None:
            rPr.addnext(new_t)
        else:
            run_el.insert(0, new_t)

    def _clone_run(self, source_run_el, new_text: str):
        """Clone a run element with new text, preserving formatting."""
        import copy
        new_run = copy.deepcopy(source_run_el)
        self._set_run_text(new_run, new_text)
        return new_run

    def _get_comments_part(self, doc):
        """Get existing comments part or create a new one."""
        for rel in doc.part.rels.values():
            if "comments" in rel.reltype:
                return rel.target_part

        from docx.oxml import parse_xml

        w_ns = NSMAP["w"]
        xml_bytes = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:comments xmlns:w="{w_ns}"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
            "/>"
        ).encode("utf-8")

        element = parse_xml(xml_bytes)
        from docx.opc.part import XmlPart

        part = XmlPart(
            PackURI("/word/comments.xml"),
            COMMENTS_CONTENT_TYPE,
            element,
            doc.part.package,
        )
        doc.part.relate_to(part, COMMENTS_REL_TYPE)
        return part

    def _get_next_comment_id(self, doc, comments_part) -> int:
        """Get the next available comment ID by checking comments.xml and body markers."""
        max_id = 0

        for comment_el in comments_part.element.findall(qn("w:comment")):
            cid = comment_el.get(qn("w:id"))
            if cid is not None:
                max_id = max(max_id, int(cid))

        for el in doc.element.body.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
                cid = el.get(qn("w:id"))
                if cid is not None:
                    max_id = max(max_id, int(cid))

        return max_id + 1

    def _add_comment_xml(self, comments_part, comment_id: int, text: str, author: str):
        """Add a comment element to the comments XML part's element tree."""
        root = comments_part.element

        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        initials = "".join(word[0].upper() for word in author.split() if word)

        comment_el = OxmlElement("w:comment")
        comment_el.set(qn("w:id"), str(comment_id))
        comment_el.set(qn("w:author"), author)
        comment_el.set(qn("w:date"), date)
        comment_el.set(qn("w:initials"), initials)

        p_el = OxmlElement("w:p")
        r_el = OxmlElement("w:r")
        t_el = OxmlElement("w:t")
        t_el.text = text
        r_el.append(t_el)
        p_el.append(r_el)
        comment_el.append(p_el)
        root.append(comment_el)

    def _insert_comment_markers(self, start_run_el, end_run_el, comment_id: int):
        """Insert commentRangeStart, commentRangeEnd, and commentReference.

        Places markers outside any existing comment markers so overlapping
        comments produce flat sibling sequences rather than nested ranges.
        """
        range_start = OxmlElement("w:commentRangeStart")
        range_start.set(qn("w:id"), str(comment_id))

        range_end = OxmlElement("w:commentRangeEnd")
        range_end.set(qn("w:id"), str(comment_id))

        ref_run = OxmlElement("w:r")
        ref_rpr = OxmlElement("w:rPr")
        ref_style = OxmlElement("w:rStyle")
        ref_style.set(qn("w:val"), "CommentReference")
        ref_rpr.append(ref_style)
        ref_run.append(ref_rpr)
        ref_el = OxmlElement("w:commentReference")
        ref_el.set(qn("w:id"), str(comment_id))
        ref_run.append(ref_el)

        insert_before = start_run_el
        while True:
            prev = insert_before.getprevious()
            if prev is None:
                break
            tag = prev.tag.split("}")[-1] if "}" in prev.tag else prev.tag
            if tag != "commentRangeStart":
                break
            insert_before = prev
        insert_before.addprevious(range_start)

        insert_after = end_run_el
        while True:
            nxt = insert_after.getnext()
            if nxt is None:
                break
            tag = nxt.tag.split("}")[-1] if "}" in nxt.tag else nxt.tag
            if tag not in ("commentRangeEnd", "r"):
                break
            if tag == "r":
                has_ref = nxt.find(qn("w:commentReference")) is not None
                if not has_ref:
                    break
            insert_after = nxt
        insert_after.addnext(ref_run)
        ref_run.addprevious(range_end)

    def _extract_comment_contexts(self, body: ET.Element) -> dict:
        """Extract the text between commentRangeStart and commentRangeEnd markers.

        Args:
            body: The document body XML element

        Returns:
            Dict mapping comment ID to context text
        """
        # Flatten all elements in document order
        all_elements = list(body.iter())

        # Find comment range markers
        range_starts = {}
        range_ends = {}

        for i, el in enumerate(all_elements):
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "commentRangeStart":
                cid = el.get(f'{{{NSMAP["w"]}}}id')
                if cid:
                    range_starts[cid] = i
            elif tag == "commentRangeEnd":
                cid = el.get(f'{{{NSMAP["w"]}}}id')
                if cid:
                    range_ends[cid] = i

        # Extract text between start and end markers
        context_map = {}
        for cid, start_idx in range_starts.items():
            end_idx = range_ends.get(cid)
            if end_idx is None:
                continue

            texts = []
            for el in all_elements[start_idx:end_idx + 1]:
                tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                if tag == "t" and el.text:
                    texts.append(el.text)

            context = "".join(texts).strip()
            if context:
                context_map[cid] = context

        return context_map


_client = None


def get_client() -> MswordClient:
    """Get or create the global MswordClient instance."""
    global _client
    if _client is None:
        _client = MswordClient()
    return _client
