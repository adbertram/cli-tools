from notion_cli.output import blocks_to_markdown, text_to_blocks


def _paragraph_rich_text(block):
    assert block["type"] == "paragraph"
    return block["paragraph"]["rich_text"]


def _to_api_block_shape(blocks):
    """Reshape input blocks into the shape the Notion API returns from `get`.

    `text_to_blocks` emits create-shaped blocks (segments carry
    ``text.content``), while ``blocks_to_markdown`` reads the read-shaped output
    (segments carry ``plain_text`` plus an ``annotations`` dict and an optional
    ``href``). This bridges the two so a single round-trip assertion exercises
    both conversion directions exactly as a live set->get would.
    """
    reshaped = []
    for block in blocks:
        block_type = block["type"]
        body = block[block_type]
        segments = []
        for seg in body["rich_text"]:
            text = seg["text"]
            api_seg = {
                "plain_text": text["content"],
                "annotations": seg.get("annotations") or {},
            }
            link = text.get("link")
            if link:
                api_seg["href"] = link["url"]
            segments.append(api_seg)
        reshaped.append({"type": block_type, block_type: {"rich_text": segments}})
    return reshaped


def test_text_to_blocks_intraword_underscores_stay_literal():
    """env_prep.ps1, ai_validation_checks, foo_bar_baz must NOT become italic.

    Per CommonMark, an underscore flanked by alphanumerics on its inner side
    cannot open or close emphasis. Each token must collapse to a single literal
    text run with no italic annotation.
    """
    markdown = (
        "Run env_prep.ps1 then check ai_validation_checks in "
        "walkthrough-run.json and foo_bar_baz here."
    )

    blocks = text_to_blocks(markdown)

    rich_text = _paragraph_rich_text(blocks[0])
    assert len(rich_text) == 1
    segment = rich_text[0]
    assert segment["text"]["content"] == (
        "Run env_prep.ps1 then check ai_validation_checks in "
        "walkthrough-run.json and foo_bar_baz here."
    )
    assert segment.get("annotations") in (None, {})


def test_text_to_blocks_genuine_underscore_emphasis_still_italic():
    """Whitespace/punctuation-flanked _emphasis_ must still parse to italic."""
    blocks = text_to_blocks("This is _real emphasis_ that stays italic.")

    rich_text = _paragraph_rich_text(blocks[0])
    assert [seg["text"]["content"] for seg in rich_text] == [
        "This is ",
        "real emphasis",
        " that stays italic.",
    ]
    assert rich_text[0].get("annotations") in (None, {})
    assert rich_text[1]["annotations"] == {"italic": True}
    assert rich_text[2].get("annotations") in (None, {})


def test_set_get_roundtrip_preserves_intraword_underscore_tokens():
    """Tokens with intraword underscores survive set->get byte-for-byte.

    This mirrors a live ``pages content set`` followed by ``pages get -m`` by
    converting markdown -> create blocks -> API-shaped read blocks -> markdown.
    """
    for token in ("env_prep.ps1", "ai_validation_checks", "foo_bar_baz"):
        source = f"Use {token} to proceed."
        blocks = text_to_blocks(source)
        api_blocks = _to_api_block_shape(blocks)
        roundtripped = blocks_to_markdown(api_blocks)
        assert roundtripped == source, token


def test_text_to_blocks_code_inside_bold_is_code_only_not_bold():
    """A `code` token inside a **bold** span must NOT be marked bold too.

    Markdown has no syntax for a run that is BOTH code and bold, so a
    bold+code run round-trips as broken ``**`code`**`` and the adjacent bold
    delimiters collide into ``****``. The code run must be code-only; the
    surrounding runs stay bold.
    """
    source = "**Grounding (`clip-slide-plan.1`):** rest is plain."
    blocks = text_to_blocks(source)

    rich_text = _paragraph_rich_text(blocks[0])
    by_text = {seg["text"]["content"]: (seg.get("annotations") or {}) for seg in rich_text}
    # The code token is code-only, never bold.
    assert by_text["clip-slide-plan.1"] == {"code": True}
    # The surrounding runs inside the bold span stay bold.
    assert by_text["Grounding ("] == {"bold": True}
    assert by_text["):"] == {"bold": True}


def test_set_get_roundtrip_code_inside_bold_has_no_quadruple_asterisks():
    """set->get round-trip of `code` inside **bold** must not emit ``****``.

    Mirrors a live ``pages content set`` then ``pages get -m`` by converting
    markdown -> create blocks -> API-shaped read blocks -> markdown.
    """
    source = "**Grounding (`clip-slide-plan.1`):** the rest is bold too."
    blocks = text_to_blocks(source)
    api_blocks = _to_api_block_shape(blocks)
    roundtripped = blocks_to_markdown(api_blocks)

    assert "****" not in roundtripped
    assert "`clip-slide-plan.1`" in roundtripped


def test_text_to_blocks_nested_fenced_code_block_preserves_literal_content():
    markdown = (
        "- Example\n"
        "  ```json\n"
        '  {"my_key": "my_value", "script_path": "scripts/run_me.sh"}\n'
        "  ```\n"
    )

    blocks = text_to_blocks(markdown)

    assert len(blocks) == 1
    list_item = blocks[0]
    assert list_item["type"] == "bulleted_list_item"
    children = list_item["bulleted_list_item"]["children"]
    assert len(children) == 1
    code_block = children[0]
    assert code_block["type"] == "code"
    assert code_block["code"]["language"] == "json"
    assert (
        "".join(chunk["text"]["content"] for chunk in code_block["code"]["rich_text"])
        == '{"my_key": "my_value", "script_path": "scripts/run_me.sh"}'
    )


def test_text_to_blocks_maps_text_code_fence_to_notion_plain_text():
    markdown = "```text\nliteral output\n```"

    blocks = text_to_blocks(markdown)

    assert len(blocks) == 1
    code_block = blocks[0]
    assert code_block["type"] == "code"
    assert code_block["code"]["language"] == "plain text"
    assert code_block["code"]["rich_text"][0]["text"]["content"] == "literal output"


def test_blocks_to_markdown_exports_embed_and_link_preview_as_visible_links():
    blocks = [
        {
            "type": "embed",
            "embed": {"url": "https://x.com/adbertram/status/1740415005387002034"},
        },
        {
            "type": "link_preview",
            "link_preview": {"url": "https://github.com/adbertram/cli-tools"},
        },
    ]

    markdown = blocks_to_markdown(blocks)

    assert markdown == (
        "[Embed: https://x.com/adbertram/status/1740415005387002034]"
        "(https://x.com/adbertram/status/1740415005387002034)\n\n"
        "[Link preview: https://github.com/adbertram/cli-tools]"
        "(https://github.com/adbertram/cli-tools)"
    )
    assert "<!-- notion-embed:" not in markdown
    assert "<!-- notion-link_preview:" not in markdown


def test_text_to_blocks_reconstructs_visible_embed_and_link_preview_links():
    markdown = (
        "[Embed: https://x.com/adbertram/status/1740415005387002034]"
        "(https://x.com/adbertram/status/1740415005387002034)\n\n"
        "[Link preview: https://github.com/adbertram/cli-tools]"
        "(https://github.com/adbertram/cli-tools)"
    )

    blocks = text_to_blocks(markdown)

    assert blocks == [
        {
            "object": "block",
            "type": "embed",
            "embed": {"url": "https://x.com/adbertram/status/1740415005387002034"},
        },
        {
            "object": "block",
            "type": "link_preview",
            "link_preview": {"url": "https://github.com/adbertram/cli-tools"},
        },
    ]
