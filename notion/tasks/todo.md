# Fix data-loss hazard in `notion pages content set`

## Problem
`content set` clears the page, THEN uploads. Notion rejects any rich_text
`text.content` > 2000 chars (and any rich_text array > 100 elements). A mid-upload
400 left the page EMPTY, destroying the original content. The CLI auto-chunked at
the 100-block level but never handled the per-block 2000-char limit.

## Root cause (verified)
- `notion_cli/commands/page.py` `content_set` (was line 1363-1364): `clear_page_content()`
  ran BEFORE `_upload_blocks_with_nesting()` (was line 1373), and no per-block
  2000-char split existed anywhere (grep for `2000` only hit `_chunk_code_content`,
  which applied to code blocks only).
- `notion_cli/client.py` `_upload_blocks_with_nesting` → `append_block_children_chunked`
  is the single upload path for set/append/import/replace-section/duplicate, and is
  where the 100-block chunk happens. The 2000-char split belongs at the same layer.
- `create_standalone_page`/`create_page` POST `children` inline (bypass the append
  path) — a second uncovered route.

## Plan
- [x] New pure transform module `notion_cli/block_limits.py`:
      `enforce_block_limits(blocks)` splits any oversize text segment on word
      boundaries, overflows >100-segment arrays into sibling blocks, recurses into
      children + table cells, preserves annotations/links, never mutates input.
      `find_oversize_rich_text(blocks)` = pre-clear validator.
- [x] Wire `enforce_block_limits` into `_upload_blocks_with_nesting` (depth-1) so
      ALL upload paths get both the 100-block AND 2000-char passes.
- [x] `content_set`: transform + validate BEFORE the clear; wrap upload so a true
      post-clear failure reports partial/empty state explicitly (fail-loud).
- [x] Enforce limits on inline `children` in `create_standalone_page`/`create_page`.
- [x] Consolidate the duplicate chunker: generalize `output.py` `_chunk_code_content`
      into `chunk_text_on_boundaries(content, max_length, boundary)`; block_limits
      reuses it (whitespace boundary), code/comments keep newline boundary.
- [x] Regression tests `tests/test_block_limits.py` (12) + reinstall + full suites.

## Review

Done. Data-loss hazard fixed at the source; per-block 2000-char + 100-element
limits now enforced on every upload path, non-destructively.

Files changed:
- notion_cli/block_limits.py — NEW pure transform + validator.
- notion_cli/client.py — import enforce_block_limits; apply in
  `_upload_blocks_with_nesting` (depth 1) and inline in
  `create_standalone_page` + `create_page`.
- notion_cli/commands/page.py — `content_set` transforms+validates before clear,
  fail-loud on post-clear upload error; import block_limits helpers.
- notion_cli/output.py — `_chunk_code_content` → thin wrapper over new
  `chunk_text_on_boundaries` (consolidation).
- tests/test_block_limits.py — NEW, 12 tests.
- README.md — documented non-destructive set + auto-split behavior.
- _repo/skills/notion-cli/usage.json — regenerated (also cleared pre-existing drift).

Validation:
- Per-tool suite: 48 passed (12 new), 0 failed.
- Compliance (test-cli-tool.sh): success=true, 222 passed, 0 failed, 0 errors, 22 skipped.
- Reinstall: success=true, help_works=true.
- Installed-launcher smoke (isolated XDG_DATA_HOME): `content set/append --help` exit 0;
  import graph loads.
- Offline transform sanity: word-split, hard-split, annotation/link preservation,
  >100-element sibling overflow, nested children, table cells, no input mutation,
  mention passthrough — all round-trip exactly.

No live Notion calls made (per instructions). No issues encountered.
