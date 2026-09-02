"""Every leaf subcommand runs once against the fixture project.

The command list is discovered from the Typer app, never hand-written, so a
new leaf fails `test_every_leaf_is_accounted_for` until it has a smoke case or
a stated skip. `discover` is smoke-run against an `account: false` site, which
executes no site CLI; the live branches are covered in `test_discover.py` with
a scripted runner.
"""

from __future__ import annotations

import json

import pytest

from conftest import SITES
from microworker_cli import envelope, paths
from microworker_cli.main import app

RUN = "20260902T000000Z"


def _walk(typer_app, prefix=()):
    for info in typer_app.registered_commands:
        name = info.name if info.name else info.callback.__name__.replace("_", "-")
        yield prefix + (name,)
    for group in typer_app.registered_groups:
        yield from _walk(group.typer_instance, prefix + (group.name,))


LEAVES = tuple(sorted(_walk(app)))


@pytest.fixture
def envelopes(project):
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
    return project


def cases():
    return {
        ("discover",): ["humanrail", "--run-id", RUN],
        ("merge",): [RUN],
        ("validate",): [str(paths.envelope_path(RUN, "humanrail"))],
        ("sites", "list"): [],
        ("sites", "get"): ["humanrail"],
    }


SKIPPED: dict[tuple[str, ...], str] = {}


def test_every_leaf_is_accounted_for(project):
    known = set(cases()) | set(SKIPPED)
    assert set(LEAVES) - known == set(), "leaf subcommands with neither a case nor a skip"
    assert known - set(LEAVES) == set(), "cases naming a subcommand that no longer exists"


@pytest.mark.parametrize("path", LEAVES, ids=lambda p: " ".join(p))
def test_leaf_subcommand_runs(path, runner, envelopes):
    if path in SKIPPED:
        pytest.skip(SKIPPED[path])
    argv = list(path) + cases()[path]
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 0, "microworker %s exited %s\noutput: %s\nraised: %r" % (
        " ".join(argv), outcome.exit_code, outcome.output[:2000], outcome.exception)
    json.loads(outcome.stdout)
