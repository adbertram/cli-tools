"""Tests for `notion pages blocks delete --recursive` fail-fast behavior.

The recursive child-delete used to wrap each delete in a bare
`except Exception: return False`, silently turning a genuine child-delete
failure (auth error, 5xx, an unexpected 4xx) into a smaller `deleted_count`
while still reporting success. These tests pin the corrected behavior:

  1. An already-archived child (the auto-archive cascade) is benign -- the
     command completes (exit 0) and counts it as already-gone, not failed.
  2. ANY OTHER delete error propagates out of the parallel executor and is
     surfaced as a non-zero exit -- it is never swallowed or miscounted.
"""
import pytest

from cli_tools_shared import output as shared_output
from notion_cli import client as client_mod
from notion_cli.commands import page


def _block(block_id, *, has_children=False, block_type="paragraph"):
    return {
        "id": block_id,
        "object": "block",
        "type": block_type,
        "has_children": has_children,
        block_type: {"rich_text": [{"plain_text": block_id}]},
    }


class RecursiveDeleteClient:
    """Drives page.blocks_delete with a parent that has children.

    delete_block_if_present mirrors the real client: it returns True when it
    archived the block this run, False for the already-archived cascade case,
    and raises for any other failure (configured per child id).
    """

    def __init__(self, *, already_gone=(), raise_for=None):
        self._already_gone = set(already_gone)
        self._raise_for = raise_for or {}
        self.parent_id = "parent-block"
        self.children = [_block("child-1"), _block("child-2"), _block("child-3")]
        self.if_present_calls = []
        self.deleted_blocks = []

    def get_block(self, block_id):
        if block_id == self.parent_id:
            return _block(self.parent_id, has_children=True, block_type="toggle")
        raise AssertionError(f"Unexpected get_block: {block_id}")

    def get_block_children_all(self, block_id, recursive=True):
        assert block_id == self.parent_id
        assert recursive is True
        return list(self.children)

    def delete_block_if_present(self, block_id):
        self.if_present_calls.append(block_id)
        if block_id in self._raise_for:
            raise self._raise_for[block_id]
        if block_id in self._already_gone:
            return False  # already archived (cascade) -- benign
        self.deleted_blocks.append(block_id)
        return True

    def delete_block(self, block_id):
        # The parent block delete (always the live, non-idempotent path).
        self.deleted_blocks.append(block_id)
        return _block(block_id)


def test_recursive_delete_succeeds_when_a_child_is_already_archived(monkeypatch):
    """A child already archived by the parent cascade must NOT fail the command.

    The command completes (exit 0), the already-gone child is counted as
    already-gone (not a deleted-this-run), and the parent is still deleted.
    """
    client = RecursiveDeleteClient(already_gone={"child-2"})
    printed_json = []
    successes = []

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_json", printed_json.append)
    monkeypatch.setattr(page, "print_success", successes.append)

    # force=True skips the confirm prompt; recursive=True triggers child delete.
    page.blocks_delete(client.parent_id, recursive=True, force=True)

    # Every child was attempted via the idempotent delete.
    assert sorted(client.if_present_calls) == ["child-1", "child-2", "child-3"]
    # Only the two live children + the parent were truly archived this run;
    # child-2 was already gone and was NOT re-deleted.
    assert sorted(client.deleted_blocks) == ["child-1", "child-3", "parent-block"]
    # The success message reports the truthful split (2 this run, 1 already gone)
    # over all 3 children -- no child silently dropped.
    assert successes, "expected a success message"
    msg = successes[-1]
    assert "3 child block(s)" in msg
    assert "2 archived this run" in msg
    assert "1 already gone" in msg


def test_recursive_delete_propagates_non_archived_child_error(monkeypatch):
    """A non-archived delete error must fail loud, not be counted as not-deleted.

    The bug was a bare `except Exception: return False` that turned this exact
    case into a silent smaller count. With the fix, the error propagates out of
    `list(executor.map(...))` and exits non-zero via the shared @command
    decorator's handle_error.
    """
    boom = client_mod.ClientError("API request failed: 500 - internal error")
    client = RecursiveDeleteClient(raise_for={"child-2": boom})
    captured_errors = []

    monkeypatch.setattr(page, "get_client", lambda: client)
    # handle_error is what the shared @command decorator calls; capture the
    # error it received and return a non-zero exit code so the command exits
    # non-zero. The decorator resolves it from cli_tools_shared.output.
    monkeypatch.setattr(shared_output, "handle_error", lambda e: captured_errors.append(e) or 1)
    monkeypatch.setattr(page, "print_json", lambda data: None)
    monkeypatch.setattr(page, "print_success", lambda msg: None)

    with pytest.raises(page.typer.Exit) as exc:
        page.blocks_delete(client.parent_id, recursive=True, force=True)

    # Non-zero exit -- the failure was NOT swallowed.
    assert exc.value.exit_code == 1
    # The genuine child error reached handle_error (not silently counted away).
    assert captured_errors == [boom]
    # The parent block was never deleted because the child failure aborted first.
    assert "parent-block" not in client.deleted_blocks
