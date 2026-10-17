"""Command contracts: the mutation safeguard and argument validation.

Nothing here reaches a network: every case stops before the client is built,
which is exactly the guarantee the safeguard exists to make.
"""

import json

import pytest
from typer.testing import CliRunner

from garrul_cli import client as client_module
from garrul_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_client(monkeypatch):
    def refuse():
        raise AssertionError("the command tried to build a client")

    for module in ("comments", "users", "webhooks", "ops", "settings", "notes", "posts", "saved_replies", "subscriptions", "telegram"):
        monkeypatch.setattr(f"garrul_cli.commands.{module}.get_client", refuse)
    monkeypatch.setattr(client_module, "get_client", refuse)


MUTATIONS = [
    ["comments", "approve", "c1"],
    ["comments", "spam", "c1"],
    ["comments", "delete", "c1"],
    ["comments", "restore", "c1"],
    ["comments", "bulk", "spam", "c1", "c2"],
    ["comments", "reply", "c1", "--body-md", "hi"],
    ["comments", "resolve-reports", "c1"],
    ["posts", "close", "a-post"],
    ["posts", "open", "a-post"],
    ["users", "ban", "u1"],
    ["users", "unban", "u1"],
    ["users", "revoke-sessions", "u1"],
    ["users", "erase", "u1"],
    ["users", "role", "u1", "mod"],
    ["saved-replies", "create", "--title", "t", "--body-md", "b", "--scope", "shared"],
    ["saved-replies", "update", "r1", "--title", "t", "--body-md", "b", "--scope", "shared"],
    ["saved-replies", "delete", "r1"],
    ["notes", "create", "comment", "c1", "--body", "note"],
    ["notes", "delete", "n1"],
    ["webhooks", "create", "--url", "https://hooks.example.test/x", "--adapter", "generic"],
    ["webhooks", "update", "w1", "--url", "https://hooks.example.test/x", "--adapter", "generic"],
    ["webhooks", "delete", "w1"],
    ["subscriptions", "unsubscribe", "s1"],
    ["subscriptions", "resend", "s1"],
    ["settings", "update", "--flag", "comments_enabled=false"],
    ["settings", "reset"],
    ["telegram", "link"],
    ["telegram", "unlink"],
    ["telegram", "digest", "on"],
    ["ops", "rerender"],
    ["ops", "ip-retention"],
    ["ops", "audit-retention"],
    ["ops", "seed-demo"],
]


@pytest.mark.parametrize("argv", MUTATIONS, ids=lambda argv: " ".join(argv[:2]))
def test_every_mutation_refuses_without_yes(argv):
    result = runner.invoke(app, argv)
    assert result.exit_code == 1
    assert "without --yes or --dry-run" in result.output


@pytest.mark.parametrize("argv", MUTATIONS, ids=lambda argv: " ".join(argv[:2]))
def test_every_mutation_has_a_dry_run_that_sends_nothing(argv):
    result = runner.invoke(app, [*argv, "--dry-run"])
    assert result.exit_code == 0, result.output
    preview = json.loads(result.stdout)
    assert preview["dry_run"] is True
    assert preview["method"] in ("POST", "PATCH", "DELETE")
    assert preview["path"].startswith("/admin/")


def test_erase_dry_run_shows_the_confirmation_garrul_requires():
    result = runner.invoke(app, ["users", "erase", "u1", "--redact-bodies", "--dry-run"])
    assert json.loads(result.stdout)["body"] == {"confirm": "ERASE", "redact_bodies": True}


def test_import_refuses_without_yes_and_previews_headers(tmp_path):
    export = tmp_path / "export.xml"
    export.write_text("<disqus></disqus>")
    assert runner.invoke(app, ["ops", "import", "disqus", str(export)]).exit_code == 1
    result = runner.invoke(app, ["ops", "import", "disqus", str(export), "--plan", "--include-spam", "--dry-run"])
    preview = json.loads(result.stdout)
    assert preview["path"] == "/admin/api/ops/import-disqus"
    assert preview["headers"]["x-dry-run"] == "1" and preview["headers"]["x-include-spam"] == "1"


def test_webhook_secret_is_never_echoed():
    argv = ["webhooks", "create", "--url", "https://hooks.example.test/x", "--adapter", "generic", "--secret-stdin", "--dry-run"]
    result = runner.invoke(app, argv, input="super-secret-value-123456\n")
    assert "super-secret-value" not in result.output
    assert json.loads(result.stdout)["body"]["secret"] == "<redacted>"


def test_yes_and_dry_run_together_is_rejected():
    result = runner.invoke(app, ["comments", "approve", "c1", "--yes", "--dry-run"])
    assert result.exit_code == 1 and "not both" in result.output


@pytest.mark.parametrize(
    "argv, message",
    [
        (["comments", "list", "--status", "bogus"], "Invalid --status"),
        (["comments", "bulk", "explode", "c1", "--yes"], "Invalid action"),
        (["comments", "bulk", "spam", *[f"c{i}" for i in range(101)], "--yes"], "at most 100"),
        (["comments", "thread", "slug", "--sort", "sideways"], "Invalid --sort"),
        (["users", "role", "u1", "emperor", "--yes"], "Invalid role"),
        (["notes", "create", "post", "p1", "--body", "x", "--yes"], "Invalid target kind"),
        (["webhooks", "create", "--url", "https://x.example.test", "--adapter", "pager", "--yes"], "Invalid --adapter"),
        (["webhooks", "create", "--url", "https://x.example.test", "--adapter", "generic", "--event", "comment.exploded", "--yes"], "Unknown --event"),
        (["saved-replies", "create", "--title", "t", "--body-md", "b", "--scope", "public", "--yes"], "Invalid --scope"),
        (["settings", "update", "--flag", "comments_enabled=maybe", "--yes"], "must be true or false"),
        (["settings", "update", "--number", "comments_per_page=lots", "--yes"], "whole number"),
        (["settings", "update", "--yes"], "Nothing to update"),
        (["telegram", "digest", "sometimes", "--yes"], "Invalid state"),
        (["ops", "rerender", "--batch", "500", "--yes"], "between 1 and 100"),
        (["ops", "import", "wordpress", "/nonexistent", "--yes"], "Unknown import source"),
        (["audit", "list", "--target-kind", "planet"], "Invalid --target-kind"),
        (["subscriptions", "list", "--confirmed", "maybe"], "Invalid --confirmed"),
        (["comments", "list", "--filter", "status:bogusop:x"], "bogusop"),
    ],
)
def test_bad_arguments_fail_before_any_request(argv, message):
    result = runner.invoke(app, argv)
    assert result.exit_code == 1
    assert message in result.output


@pytest.mark.parametrize(
    "argv, message",
    [
        (["comments", "list", "-f", "nofield:eq:1"], "Cannot filter on nofield"),
        (["comments", "list", "-p", ",,"], "needs at least one field"),
        (["users", "list", "-f", "role:eq:admin"], "Cannot filter on role"),
        (["settings", "list", "-f", "name:eq:x"], "Cannot filter on name"),
        (["settings", "update", "--number", "comments_per_page=--5", "--yes"], "whole number"),
        (["settings", "update", "--number", "comments_per_page=\u00b2", "--yes"], "whole number"),
        (["settings", "update", "--flag", "a=true", "--flag", "a=false", "--yes"], "names a twice"),
    ],
)
def test_field_and_value_typos_fail_before_any_request(argv, message):
    result = runner.invoke(app, argv)
    assert result.exit_code == 1
    assert message in result.output


def test_dry_run_shows_the_encoded_path_the_real_request_uses():
    preview = json.loads(runner.invoke(app, ["comments", "delete", "a/b?x=1", "--dry-run"]).stdout)
    assert preview["path"] == "/admin/api/comments/a%2Fb%3Fx%3D1"
    empty = runner.invoke(app, ["comments", "delete", "", "--dry-run"])
    assert empty.exit_code == 1 and "empty" in empty.output


def test_table_output_neutralizes_terminal_escape_sequences(capsys):
    from garrul_cli.helpers import emit_rows

    emit_rows([{"id": "c1", "body_text": "hi \x1b]0;PWNED\x07\x1b[31mRED"}], [], 10, True, None, ["id", "body_text"], "none")
    shown = capsys.readouterr().out
    assert "\x1b" not in shown and "\x07" not in shown
    assert "\\x1b" in shown


def test_limit_is_applied_after_the_filter(capsys):
    from garrul_cli.helpers import emit_rows

    rows = [{"key": "a", "group": "flags"}, {"key": "b", "group": "numbers"}, {"key": "c", "group": "numbers"}]
    emit_rows(rows, ["group:eq:numbers"], 1, False, None, ["key"], "none")
    assert json.loads(capsys.readouterr().out) == [{"key": "b", "group": "numbers"}]


def test_unknown_property_warns_on_stderr_and_keeps_stdout_pure(capsys):
    """The cli-tools contract tolerates an unknown --properties field, so this warns instead of failing."""
    from garrul_cli.helpers import emit_rows, selected

    names = selected("id,nope", ["id", "status"])
    emit_rows([{"id": "c1", "status": "spam"}], [], 10, False, names, ["id"], "none")
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [{"id": "c1", "nope": None}]
    assert "No field named nope" in captured.err
