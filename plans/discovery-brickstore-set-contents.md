# Discovery: BrickStore set contents

## Codebase Context

- `brickstore/brickstore_cli/client.py` owns MCP calls and existing price-guide methods.
- `brickstore/brickstore_cli/main.py` owns the flat Typer command surface.
- `brickstore/tests/test_client.py` tests exact source arguments and failure paths.
- `brickstore/tests/test_main.py` tests command JSON and Typer parsing.
- `brickstore` MCP only exposes price-guide and catalog-query tools.
- The installed `bricklink` CLI exposes `catalog subsets SET <item_no>`.

## Q&A Results

### Wave: Contract

**Q:** What command shape must the feature use?

**A:** `brickstore set-contents <set-id> [<set-id> ...]`.

**Q:** What must default stdout contain?

**A:** One top-level JSON array. Each record has `set_id` and `items`.

**Q:** Which source supplies the items?

**A:** The approved, authenticated `bricklink catalog subsets SET <set-id>` path.

**Q:** Can the command change data?

**A:** No. It uses the BrickLink read-only catalog subsets operation.

**Q:** Can this change alter `set-batch`?

**A:** No.

## Key Decisions

- Use the installed BrickLink CLI rather than a direct BrickLink API client.
- Preserve each BrickLink entry record inside the `items` array.
- Validate one to 25 unique set IDs before child-process work.
- Test the public command and the subprocess boundary before implementation.
