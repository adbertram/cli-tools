import pytest

from notion_cli.code_languages import (
    MARKDOWN_FENCE_LANGUAGE_ALIASES,
    SUPPORTED_CODE_LANGUAGES,
    markdown_fence_language,
    normalize_code_language,
)
from notion_cli.output import blocks_to_markdown, text_to_blocks


def _api_rich_text(segments):
    """Convert create-shaped rich_text segments to the shape `get` returns."""
    converted = []
    for segment in segments:
        text = segment["text"]
        api_segment = {
            "plain_text": text["content"],
            "annotations": segment.get("annotations") or {},
        }
        link = text.get("link")
        if link:
            api_segment["href"] = link["url"]
        converted.append(api_segment)
    return converted


def _as_api_blocks(blocks):
    """Reshape any create-shaped block list into the Notion `get` read shape.

    Mirrors the live API: rich_text segments carry ``plain_text``/``annotations``
    instead of ``text.content``, and a container block's children are returned at
    the block level (``block["children"]``) rather than inside the type body.
    Round-tripping through this function is what makes a single assertion cover
    both `content set` (markdown -> blocks) and `content get` (blocks ->
    markdown).
    """
    reshaped = []
    for block in blocks:
        block_type = block["type"]
        body = dict(block[block_type])
        children = body.pop("children", None)
        if "rich_text" in body:
            body["rich_text"] = _api_rich_text(body["rich_text"])
        if "caption" in body:
            body["caption"] = _api_rich_text(body["caption"])
        if block_type == "table_row":
            body["cells"] = [_api_rich_text(cell) for cell in body["cells"]]
        api_block = {"type": block_type, block_type: body}
        if children is not None:
            api_block["children"] = _as_api_blocks(children)
        reshaped.append(api_block)
    return reshaped


def _roundtrip(markdown, image_uploads=None):
    """Run markdown through `content set` conversion and back out via `get`."""
    return blocks_to_markdown(
        _as_api_blocks(text_to_blocks(markdown, image_uploads=image_uploads))
    )


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


# ---------------------------------------------------------------------------
# Image round trip: `![alt](src)` must never degrade into `[Image: src]`
# ---------------------------------------------------------------------------


def test_image_with_unresolvable_src_roundtrips_with_alt_text():
    """A pipeline IMAGE_PLACEHOLDER src keeps its `![alt](src)` syntax.

    Notion has no image block for a src that is neither an http(s) URL nor an
    uploaded file. The importer used to rewrite the line to a `[Image: src]`
    paragraph, destroying both the markdown image syntax and the alt text, so a
    later phase that edited the exported body published a post with no images.
    """
    source = "![HITL workflow architecture](IMAGE_PLACEHOLDER: workflow architecture diagram)"

    blocks = text_to_blocks(source)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"
    assert "[Image:" not in str(blocks[0])

    assert _roundtrip(source) == source


def test_image_roundtrip_is_stable_across_repeated_syncs():
    """Re-importing the exported body must not drift on the second cycle."""
    source = "![Teams approval card](IMAGE_PLACEHOLDER: Teams adaptive card approval)"

    once = _roundtrip(source)
    assert _roundtrip(once) == source


def test_external_image_url_roundtrips_alt_text_as_caption():
    """An http(s) src becomes a real image block whose caption is the alt text."""
    source = "![HITL workflow architecture](https://cdn.example.com/hitl.png)"

    blocks = text_to_blocks(source)
    assert blocks[0]["type"] == "image"
    assert blocks[0]["image"]["external"]["url"] == "https://cdn.example.com/hitl.png"

    assert _roundtrip(source) == source


# ---------------------------------------------------------------------------
# Code fence round trip: Notion's "plain text" is not a markdown info-string
# ---------------------------------------------------------------------------


def test_text_code_fence_roundtrips_as_text_not_plain_text():
    """```text must come back as ```text, never the invalid ```plain text.

    A markdown info-string is a single token, so ```plain text is read by a
    highlighter as language "plain" with the rest discarded.
    """
    source = "```text\nAPPROVED by adam@example.com\n```"

    blocks = text_to_blocks(source)
    assert blocks[0]["code"]["language"] == "plain text"

    exported = _roundtrip(source)
    assert "```plain text" not in exported
    assert exported == source


def test_known_code_fence_language_roundtrips_unchanged():
    source = "```json\n{\"a\": 1}\n```"
    assert _roundtrip(source) == source


def test_every_supported_notion_language_exports_a_single_token_fence():
    """No Notion language may export an info-string a highlighter mis-reads."""
    for language in SUPPORTED_CODE_LANGUAGES:
        token = markdown_fence_language(language)
        assert token, language
        assert len(token.split()) == 1, language
        assert "/" not in token, language


def test_every_exported_fence_token_reimports_to_its_notion_language():
    """The export alias table must be reversible by normalize_code_language."""
    for language, token in MARKDOWN_FENCE_LANGUAGE_ALIASES.items():
        if language == "java/c/c++/c#":
            # Notion's legacy combined value has no markdown equivalent; it
            # deliberately collapses to its first member.
            assert normalize_code_language(token) == "java"
            continue
        assert normalize_code_language(token) == language


def test_markdown_fence_language_fails_fast_on_missing_language():
    with pytest.raises(ValueError, match="no language"):
        markdown_fence_language(None)
    with pytest.raises(ValueError, match="no language"):
        markdown_fence_language("")


def test_markdown_fence_language_fails_fast_on_unmapped_multi_token_language():
    with pytest.raises(ValueError, match="not a valid markdown fence"):
        markdown_fence_language("some new language")


# ---------------------------------------------------------------------------
# Table column alignment round trip
# ---------------------------------------------------------------------------


LEFT_ALIGNED_TABLE = (
    "| Decision style | Handled by | Example |\n"
    "| :--- | :--- | :--- |\n"
    "| Rules-based | Power Automate | Auto-approved |"
)


def test_left_aligned_table_roundtrips_alignment_markers():
    """`| :--- |` must survive; Notion tables store no per-column alignment."""
    assert _roundtrip(LEFT_ALIGNED_TABLE) == LEFT_ALIGNED_TABLE


def test_mixed_alignment_table_roundtrips_each_column():
    source = (
        "| Metric | Count | Notes |\n"
        "| :--- | ---: | :---: |\n"
        "| Approvals | 12 | steady |"
    )
    assert _roundtrip(source) == source


def test_aligned_table_stores_one_marker_block_before_the_table():
    blocks = text_to_blocks(LEFT_ALIGNED_TABLE)

    assert [block["type"] for block in blocks] == ["paragraph", "table"]
    marker_text = blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]
    assert marker_text == "<!-- notion-table-align: :---|:---|:--- -->"


def test_unaligned_table_adds_no_marker_block_and_roundtrips():
    source = (
        "| Decision style | Handled by |\n"
        "| --- | --- |\n"
        "| Rules-based | Power Automate |"
    )

    blocks = text_to_blocks(source)
    assert [block["type"] for block in blocks] == ["table"]
    assert _roundtrip(source) == source


def test_table_alignment_roundtrip_is_stable_across_repeated_syncs():
    once = _roundtrip(LEFT_ALIGNED_TABLE)
    assert _roundtrip(once) == LEFT_ALIGNED_TABLE


def test_orphaned_alignment_marker_fails_fast_on_export():
    """A marker whose table was deleted in Notion must not be dropped silently."""
    blocks = _as_api_blocks(text_to_blocks(LEFT_ALIGNED_TABLE))
    orphaned = [blocks[0]]

    with pytest.raises(ValueError, match="no table after it"):
        blocks_to_markdown(orphaned)


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
