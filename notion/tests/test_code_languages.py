"""Regression tests for code-fence language normalization.

Notion's API rejects a ``code`` block whose ``language`` is not in its supported
set (e.g. ``kql``). The CLI used to forward the language verbatim, 400ing the
request -- and on the non-atomic ``replace-section`` path that rejection
corrupted the page. The fix normalizes any unsupported language to
``"plain text"`` on every upload transform path, while preserving known
languages and the ``text`` -> ``plain text`` markdown alias.

These tests cover the two transform chokepoints:
- ``text_to_blocks`` (markdown -> blocks), used by ``content set``/``append``/
  ``replace-section``/``import``/``database page create --content-file``.
- ``enforce_block_limits`` (raw-block enforcement), the universal pre-upload
  step that also covers raw-JSON paths (``--json-file``, ``duplicate``) which
  never run through markdown conversion.
"""
import pytest

from notion_cli.code_languages import (
    PLAIN_TEXT_LANGUAGE,
    SUPPORTED_CODE_LANGUAGES,
    normalize_code_language,
)
from notion_cli.block_limits import enforce_block_limits
from notion_cli.output import text_to_blocks


def _code_languages(blocks):
    return [b["code"]["language"] for b in blocks if b.get("type") == "code"]


# ---------------------------------------------------------------------------
# normalize_code_language: the single data-driven chokepoint
# ---------------------------------------------------------------------------


def test_unknown_language_normalizes_to_plain_text():
    assert normalize_code_language("kql") == PLAIN_TEXT_LANGUAGE


def test_known_languages_pass_through_unchanged():
    for lang in ["bash", "python", "json", "sql", "yaml", "powershell", "javascript"]:
        assert normalize_code_language(lang) == lang
        assert lang in SUPPORTED_CODE_LANGUAGES


def test_text_alias_maps_to_plain_text():
    assert normalize_code_language("text") == PLAIN_TEXT_LANGUAGE


def test_known_language_match_is_case_insensitive():
    assert normalize_code_language("Bash") == "bash"
    assert normalize_code_language("PYTHON") == "python"


def test_empty_or_missing_language_becomes_plain_text():
    assert normalize_code_language("") == PLAIN_TEXT_LANGUAGE
    assert normalize_code_language("   ") == PLAIN_TEXT_LANGUAGE
    assert normalize_code_language(None) == PLAIN_TEXT_LANGUAGE


def test_plain_text_itself_is_supported_and_unchanged():
    assert normalize_code_language("plain text") == "plain text"
    assert "plain text" in SUPPORTED_CODE_LANGUAGES


# ---------------------------------------------------------------------------
# markdown path: text_to_blocks normalizes fence info-strings
# ---------------------------------------------------------------------------


def test_text_to_blocks_normalizes_unknown_fence_language():
    md = "```kql\nStormEvents | take 10\n```"
    blocks = text_to_blocks(md)
    assert _code_languages(blocks) == [PLAIN_TEXT_LANGUAGE]


def test_text_to_blocks_preserves_known_fence_language_and_maps_text():
    md = (
        "```bash\necho hi\n```\n\n"
        "```text\nplain\n```\n\n"
        "```kql\nq\n```\n\n"
        "```python\nprint(1)\n```"
    )
    blocks = text_to_blocks(md)
    assert _code_languages(blocks) == [
        "bash",
        PLAIN_TEXT_LANGUAGE,  # text -> plain text alias
        PLAIN_TEXT_LANGUAGE,  # kql -> plain text (unsupported)
        "python",
    ]


# ---------------------------------------------------------------------------
# raw-block path: enforce_block_limits normalizes languages on raw JSON blocks
# (covers --json-file and duplicate, which never call text_to_blocks)
# ---------------------------------------------------------------------------


def _code_block(language):
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": "x"}}],
            "language": language,
        },
    }


def test_enforce_block_limits_normalizes_unknown_raw_code_language():
    out = enforce_block_limits([_code_block("kql")])
    assert out[0]["code"]["language"] == PLAIN_TEXT_LANGUAGE


def test_enforce_block_limits_preserves_known_raw_code_language():
    out = enforce_block_limits([_code_block("powershell")])
    assert out[0]["code"]["language"] == "powershell"


def test_enforce_block_limits_normalizes_language_in_nested_children():
    block = {
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "Toggle"}}],
            "children": [_code_block("kql")],
        },
    }
    out = enforce_block_limits([block])
    assert out[0]["toggle"]["children"][0]["code"]["language"] == PLAIN_TEXT_LANGUAGE


def test_enforce_block_limits_does_not_mutate_input_code_language():
    import copy

    block = _code_block("kql")
    snapshot = copy.deepcopy(block)
    enforce_block_limits([block])
    assert block == snapshot  # input untouched
