# Implementation Plan: BrickStore set contents

## Current State

`set-batch` returns an MCP price-guide envelope. It does not return set records with nested item data.

The current BrickStore MCP source has no read-only set-contents tool. The approved BrickLink CLI has an authenticated, read-only catalog subsets path.

## Implementation Steps

1. Add failing client tests for one and multiple set IDs.
   - Assert exact `bricklink catalog subsets SET <set_id>` argv.
   - Assert each result is `{set_id, items}`.
   - Assert entries flatten into `items` without entry-field changes.
   - Assert each item receives its source group `match_no` value.
   - Assert child command failures and malformed JSON become `ClientError` values.

2. Add failing command tests.
   - Assert one and multiple IDs produce a valid top-level JSON array.
   - Assert each array record has a nested `items` array.
   - Assert the command forwards IDs in order.

3. Extend `brickstore_cli/client.py`.
   - Reuse the existing one-to-25 unique-ID validator.
   - Run the installed `bricklink` launcher by a list-form subprocess call.
   - Parse only child stdout as JSON.
   - Validate the source array and each subset `entries` array.
   - Flatten entry objects into each set record's `items` array.
   - Copy each source group `match_no` into its flattened item records.
   - Keep `set-batch` unchanged.

4. Extend `brickstore_cli/main.py`.
   - Add `set-contents` with one or more positional set IDs.
   - Print the client result with `print_json`.

5. Update user guidance.
   - Document the new read-only command in `README.md`.
   - Update the repo-owned BrickStore skill after regenerated usage data proves the installed help.

6. Validate in order.
   - Run the focused tests and the full per-tool tests.
   - Run the code simplification reviews.
   - Reinstall with the documented script.
   - Regenerate `usage.json`.
   - Run the mandatory full CLI test script until it reports zero failures.
   - Run the usage stability check.
   - Run the installed command against the live BrickLink source.

## Integration Points

No new SDK, HTTP client, OAuth flow, secret, or direct BrickLink API code is needed. The BrickStore CLI invokes the approved installed BrickLink CLI, which owns OAuth and the actual read-only request.

## Breaking Changes

None. The existing `set-batch` command and its price-guide envelope stay unchanged.
