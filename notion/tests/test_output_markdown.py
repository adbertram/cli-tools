from notion_cli.output import text_to_blocks


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
