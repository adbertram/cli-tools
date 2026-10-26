# Studio consolidation review

Read-only review of `tiktok_cli/studio.py`, Studio client methods, `commands/videos.py`, and `tests/test_studio.py`.

## Finding

`validate_page()` rejects `extra.fatal_item_ids` only when its value is truthy. Malformed falsy values such as `null`, `0`, `""`, or `{}` pass validation, so a terminal page could be treated as complete and support a false `studio_video_not_found`. If the field is present, require a list and reject nonempty lists.

## Fixture-only coverage

`test_advancing_pagination_uses_only_server_cursor` verifies a synthetic second page through `FakePage`. It does not prove live multipage response behavior. Label this as fixture-only coverage; the single live route capture does not demonstrate a real second-page response.

## Other checks

No repeated 3+ line logic worth extracting found. Cleanup runs in `finally`; scan and response bounds are explicit; malformed cursors and duplicate IDs fail inconclusively. Owner ID checks preserve 64-bit values because account payload is parsed from response text in Python, and Studio rechecks the same numeric owner after reading.

The requested `work/tiktok-readback/before` snapshots were absent from this checkout, so comparison used current files and Git history.
