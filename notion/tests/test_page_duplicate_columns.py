"""Regression tests for duplicating pages with column_list / column layouts.

Bug: `notion pages duplicate` failed with
`400 - body.children[N].column_list.children[0].column.children should be
defined, instead was undefined`.

Root cause: `_upload_blocks_with_nesting` treated every direct child of a
child-required block the same way — it popped the child's children to re-attach
them after creation. But a `column` inside a `column_list` is itself a
child-required type: Notion refuses to create a childless column, so popping
the column's content produced `column: {}` and the API rejected the payload.

The fix keeps the required descendant chain (column_list -> column -> content)
inline and pops children only from descendants that can be created childless,
re-attaching them by resolving the created blocks' index paths.
"""

import copy

from notion_cli.client import NotionClient


# ---------------------------------------------------------------------------
# Block builders (raw API shape, as returned by get_block_children_all)
# ---------------------------------------------------------------------------

def raw_heading(text):
    return {
        "id": f"src-heading-{text}",
        "object": "block",
        "type": "heading_2",
        "has_children": False,
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}, "plain_text": text}]},
    }


def raw_divider():
    return {
        "id": "src-divider",
        "object": "block",
        "type": "divider",
        "has_children": False,
        "divider": {},
    }


def raw_bullet(text, children=None):
    block = {
        "id": f"src-bullet-{text}",
        "object": "block",
        "type": "bulleted_list_item",
        "has_children": bool(children),
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}, "plain_text": text}]
        },
    }
    if children:
        block["children"] = children
    return block


def raw_column(index, children):
    return {
        "id": f"src-column-{index}",
        "object": "block",
        "type": "column",
        "has_children": True,
        "column": {},
        "children": children,
    }


def raw_column_list(columns):
    return {
        "id": "src-column-list",
        "object": "block",
        "type": "column_list",
        "has_children": True,
        "column_list": {},
        "children": columns,
    }


def raw_callout(children):
    return {
        "id": "src-callout",
        "object": "block",
        "type": "callout",
        "has_children": True,
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": "note"}, "plain_text": "note"}]
        },
        "children": children,
    }


# ---------------------------------------------------------------------------
# Fake Notion server: records appends, registers created blocks (including
# inline nested children), and serves _fetch_block_children_flat lookups.
# ---------------------------------------------------------------------------

class FakeServer:
    def __init__(self):
        self.blocks = {}
        self.children = {}
        self.append_calls = []
        self._counter = 0

    def _register(self, parent_id, block):
        self._counter += 1
        block_id = f"srv-{self._counter}"
        self.blocks[block_id] = block
        self.children.setdefault(parent_id, []).append(block_id)
        block_type = block.get("type", "")
        type_data = block.get(block_type) if block_type else None
        if isinstance(type_data, dict) and isinstance(type_data.get("children"), list):
            inline = type_data["children"]
        elif isinstance(block.get("children"), list):
            inline = block["children"]
        else:
            inline = []
        for child in inline:
            self._register(block_id, child)
        return block_id

    def append_block_children_chunked(
        self, block_id, children, chunk_size=100, progress_callback=None, after=None
    ):
        self.append_calls.append(
            {"parent_id": block_id, "blocks": copy.deepcopy(children), "after": after}
        )
        ids = [self._register(block_id, copy.deepcopy(b)) for b in children]
        return (len(children), ids)

    def fetch_flat(self, block_id):
        return [
            {"id": cid, "type": self.blocks[cid].get("type", "")}
            for cid in self.children.get(block_id, [])
        ]


def make_client(server):
    client = NotionClient.__new__(NotionClient)
    client.append_block_children_chunked = server.append_block_children_chunked
    client._fetch_block_children_flat = server.fetch_flat
    return client


def assert_columns_have_children(blocks, path="blocks"):
    """Walk an upload payload and assert every column_list/column carries children."""
    for i, block in enumerate(blocks):
        block_type = block.get("type", "")
        here = f"{path}[{i}].{block_type}"
        if block_type in ("column_list", "column"):
            type_data = block.get(block_type, {})
            children = type_data.get("children")
            assert isinstance(children, list) and children, (
                f"{here}.children should be defined and non-empty, got {children!r}"
            )
        type_data = block.get(block_type)
        if isinstance(type_data, dict) and isinstance(type_data.get("children"), list):
            assert_columns_have_children(type_data["children"], f"{here}.children")


def server_texts(server, parent_id):
    """Plain-text contents of a server block's children, in order."""
    texts = []
    for cid in server.children.get(parent_id, []):
        block = server.blocks[cid]
        block_type = block.get("type", "")
        rich = block.get(block_type, {}).get("rich_text", [])
        texts.append("".join(seg.get("text", {}).get("content", "") for seg in rich))
    return texts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_duplicate_column_list_keeps_column_children_inline():
    """The bug scenario: 5 columns each holding heading + divider + bullets."""
    columns = [
        raw_column(i, [raw_heading(f"H{i}"), raw_divider(), raw_bullet(f"B{i}")])
        for i in range(5)
    ]
    raw = [raw_column_list(columns)]

    server = FakeServer()
    client = make_client(server)

    cleaned = client._clean_blocks_recursive(copy.deepcopy(raw))
    total, top_ids = client._upload_blocks_with_nesting("new-page", cleaned)

    # First append: the column_list with every column's content inline.
    first_payload = server.append_calls[0]["blocks"]
    assert first_payload[0]["type"] == "column_list"
    assert len(first_payload[0]["column_list"]["children"]) == 5
    assert_columns_have_children(first_payload)

    # Server-side tree: column_list -> 5 columns -> 3 content blocks each.
    column_list_id = top_ids[0]
    column_ids = [c["id"] for c in server.fetch_flat(column_list_id)]
    assert len(column_ids) == 5
    for i, column_id in enumerate(column_ids):
        content = server.fetch_flat(column_id)
        assert [b["type"] for b in content] == ["heading_2", "divider", "bulleted_list_item"]

    # Count reflects top-level appends only: the whole layout rides inline in
    # one column_list block, with no deferred follow-up appends needed.
    assert total == 1
    assert len(server.append_calls) == 1


def test_duplicate_column_content_with_nested_children_reattaches_by_path():
    """Sub-bullets inside a column are deferred and re-attached to the right block."""
    nested = raw_bullet("parent-bullet", children=[raw_bullet("sub-bullet")])
    columns = [
        raw_column(0, [raw_heading("H0"), nested]),
        raw_column(1, [raw_bullet("B1")]),
    ]
    raw = [raw_column_list(columns)]

    server = FakeServer()
    client = make_client(server)

    cleaned = client._clean_blocks_recursive(copy.deepcopy(raw))
    client._upload_blocks_with_nesting("new-page", cleaned)

    # The inline payload must not carry the sub-bullet (deferred past the
    # required chain), but every column must still carry its direct children.
    first_payload = server.append_calls[0]["blocks"]
    assert_columns_have_children(first_payload)
    inline_parent = first_payload[0]["column_list"]["children"][0]["column"]["children"][1]
    assert "children" not in inline_parent
    assert "children" not in inline_parent["bulleted_list_item"]

    # A follow-up append must attach the sub-bullet under the created
    # parent bullet (column 0 -> child index 1).
    column_list_id = server.children["new-page"][0]
    column0_id = server.children[column_list_id][0]
    parent_bullet_id = server.children[column0_id][1]
    assert server_texts(server, parent_bullet_id) == ["sub-bullet"]


def test_duplicate_callout_children_still_appended_after_creation():
    """Callouts can be created childless; children are appended afterwards."""
    raw = [raw_callout([raw_bullet("inside-callout")])]

    server = FakeServer()
    client = make_client(server)

    cleaned = client._clean_blocks_recursive(copy.deepcopy(raw))
    client._upload_blocks_with_nesting("new-page", cleaned)

    # First append: callout without children (popped for later).
    first_payload = server.append_calls[0]["blocks"]
    assert first_payload[0]["type"] == "callout"
    assert "children" not in first_payload[0]
    assert "children" not in first_payload[0]["callout"]

    # Second append: the child arrives under the created callout's ID.
    callout_id = server.children["new-page"][0]
    assert server_texts(server, callout_id) == ["inside-callout"]


def test_pop_optional_descendants_keeps_required_chain():
    client = NotionClient.__new__(NotionClient)
    block = {
        "type": "column_list",
        "column_list": {
            "children": [
                {
                    "type": "column",
                    "column": {
                        "children": [
                            {
                                "type": "paragraph",
                                "paragraph": {"rich_text": []},
                                "children": [{"type": "paragraph", "paragraph": {"rich_text": []}}],
                            }
                        ]
                    },
                }
            ]
        },
    }

    deferred = client._pop_optional_descendants(block)

    # The column keeps its paragraph; only the paragraph's children are popped,
    # addressed by path [column_index, content_index].
    assert [path for path, _blocks in deferred] == [[0, 0]]
    column = block["column_list"]["children"][0]
    assert len(column["column"]["children"]) == 1
    assert "children" not in column["column"]["children"][0]


def test_apply_text_replacements_reaches_type_nested_children():
    """--replace must reach content nested inside cleaned container blocks."""
    client = NotionClient.__new__(NotionClient)
    blocks = [
        {
            "type": "column_list",
            "column_list": {
                "children": [
                    {
                        "type": "column",
                        "column": {
                            "children": [
                                {
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [
                                            {"type": "text", "text": {"content": "year 2025"}}
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        }
    ]

    client._apply_text_replacements(blocks, [("2025", "2026")])

    nested_text = (
        blocks[0]["column_list"]["children"][0]["column"]["children"][0]
        ["paragraph"]["rich_text"][0]["text"]["content"]
    )
    assert nested_text == "year 2026"
