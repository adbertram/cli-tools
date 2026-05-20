# AGENTS.md

## Scripted task completion -- prefer `--match-*` over positional index

`brickfreedom task complete <N>` takes a 1-based position from `brickfreedom task list`. Completing a task shifts every higher-indexed task down by one. Callers (agents, workflows) that capture an index before mutating the list will complete the wrong task on the next call.

**For ANY non-interactive workflow, use match-mode:**

```bash
brickfreedom task complete \
    --match-platform bricklink \
    --match-order-id 30823995 \
    --match-item-number 75270-1
# Add --match-quantity to disambiguate when multiple rows match.
```

Match mode:

- Re-fetches the live task list (bypassing the response cache) immediately before clicking.
- Filters parsed `MissingPart` entries by all provided `--match-*` flags (case-insensitive `platform`, exact `order_id`, exact `item_number`, exact `quantity`).
- Excludes already-completed tasks.
- **Single match:** clicks the freshly-resolved index; exit 0; JSON includes `{index, platform, orderId, itemNumber, quantity, success, message}`.
- **Zero matches:** exit 1; JSON `{"success": false, "error": "no matching missing-part task", "matchCriteria": {...}}`.
- **Multiple matches:** exit 1; JSON `{"success": false, "error": "ambiguous match -- N tasks matched", "matchCriteria": {...}, "matches": [{index, platform, orderId, itemNumber, quantity}, ...]}` -- pass more `--match-*` flags (typically `--match-quantity`) to disambiguate.
- Mixing positional `INDEX` with `--match-*` flags is rejected fail-fast. No fallback. No "best guess." No auto-disambiguation.

Positional `brickfreedom task complete <N>` and `--bulk` still work unchanged.

## Silently dropped task rows are now visible

`brickfreedom task list --type missing-part` exposes parser coverage:

- JSON output includes top-level `"unparsed_count": <N>`.
- Stderr warning when `unparsed_count > 0`: `[brickfreedom] WARNING: N task row(s) did not match any known missing-part format and were dropped.`
- `brickfreedom task list --type missing-part --debug-unparsed` prints each raw unparsed task text to stderr, one per line, prefixed `[unparsed] `. Use this when BF ships a new dashboard task text shape -- you can see the raw rows that need a new parser branch without scraping the dashboard yourself.

## Parser tests

`tests/test_missing_part_parser.py` pins all four `MissingPart.from_task_text` branches plus the `task complete --match-*` semantics (single match completes resolved index, zero matches errors, multiple matches errors with candidates listed, positional + match mixing is rejected, `--match-quantity` disambiguation). Any future change to the parser or the match-mode behavior must keep these tests green.

Run them with:

```bash
cd <cli-tools-root>/brickfreedom && \
  UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/brickfreedom-tests \
  uv run --with pytest python -m pytest tests/ -v
```

Do **not** run bare `uv run` from inside this repo -- it creates a forbidden `.venv` in the source tree and the cli-tools-shared compliance test will fail.
