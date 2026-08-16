# Technical Research: BrickStore set contents

## Files Analyzed

| File | Key Functions | Notes |
|---|---|---|
| `brickstore/brickstore_cli/client.py` | `set_batch`, `_call_tool`, `validate_set_batch_numbers` | Current MCP path returns price-guide results only. |
| `brickstore/brickstore_cli/main.py` | `set_batch` | The flat app can add one focused command. |
| `brickstore/tests/test_client.py` | MCP fixture helpers | Tests assert full RPC arguments and source failures. |
| `brickstore/tests/test_main.py` | `CliRunner` command tests | Tests assert JSON stdout and fake-client calls. |
| `bricklink/bricklink_cli/client.py` | `get_subsets` | It calls `GET /items/{item_type}/{item_no}/subsets`. |
| `bricklink/bricklink_cli/commands/catalog.py` | `catalog_subsets` | It exposes the read-only catalog subsets command. |

## APIs and Tools Verified

| Tool or API | Verified signature | Notes |
|---|---|---|
| BrickStore MCP | `catalog_query`, `catalog_price_guide` | No read-only set-contents source exists. |
| BrickLink CLI | `bricklink catalog subsets SET <item_no> --limit <n>` | Live command returned a JSON array of subset records. |
| BrickLink auth | `bricklink auth status` | The default OAuth credential path returned authenticated true. |

## Integration Map

`brickstore set-contents` -> `BrickStoreClient.set_contents` -> installed `bricklink catalog subsets SET <set_id>` -> JSON subset records -> flattened entry records -> `{set_id, items}` array.

## Patterns to Follow

1. Use `ClientError` for child-process and JSON-contract failures.
2. Use `print_json` for default stdout.
3. Test exact child argv and malformed child JSON.
4. Keep `set-batch` unchanged.
