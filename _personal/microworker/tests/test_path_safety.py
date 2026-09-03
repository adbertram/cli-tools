"""A run id and a site name are path segments, and they stay inside the project.

Both arrive as CLI operands and are interpolated straight into a filesystem
path, so both are constrained to a shape that cannot contain a separator or a
`..`, and every constructed path is asserted to resolve under the project root.
Without that, a site named `../../../../../../tmp/evil` writes its envelope
outside `$MICROWORKER_ROOT`, and `merge ../../../../tmp/mwtrav` reads envelopes
from an arbitrary directory and stores the traversal string as a `runs.run_id`.
"""

from __future__ import annotations

import json

import pytest
from cli_tools_shared.exceptions import ClientError

from conftest import SITES, write_config
from microworker_cli import discover, envelope, paths, runner as runner_module
from microworker_cli.main import app

RUN = "20260902T000000Z"

TRAVERSING_RUN_IDS = [
    "../../../../tmp/mwtrav",
    "..",
    "/tmp/mwtrav",
    "run/../../etc",
    "20260902T000000Z/../..",
]
BAD_SHAPE_RUN_IDS = ["A", "R1", "SEED", "never-ran", "2026-09-02T00:00:00Z", ""]


@pytest.mark.parametrize("run_id", TRAVERSING_RUN_IDS + BAD_SHAPE_RUN_IDS)
def test_run_dir_rejects_anything_that_is_not_a_timestamp(project, run_id):
    with pytest.raises(ClientError, match="invalid run id"):
        paths.run_dir(run_id)


def test_run_dir_accepts_the_documented_shape(project):
    expected = (project / "agent_workspaces" / "discovery" / RUN)
    assert paths.run_dir(RUN) == expected


@pytest.mark.parametrize("site", [
    "../../../../../../tmp/evil",
    "..",
    "/tmp/evil",
    "Microworkers",
    "micro workers",
    "-leading-hyphen",
    "",
])
def test_envelope_path_rejects_a_site_that_is_not_one_segment(project, site):
    with pytest.raises(ClientError, match="invalid site name"):
        paths.envelope_path(RUN, site)


@pytest.mark.parametrize("site", ["microworkers", "trainee-digital", "atlas-capture"])
def test_envelope_path_accepts_real_config_site_names(project, site):
    assert paths.envelope_path(RUN, site) == paths.run_dir(RUN) / f"{site}.json"


def test_discover_cannot_write_outside_the_project_root(project, tmp_path, monkeypatch):
    """A traversing site name in config.json fails before any envelope is written."""
    escape = tmp_path.parent / "mw-escape"
    sites = dict(SITES)
    sites[f"../../../../../../{escape.name}"] = {
        "cli": None, "account": False, "lastpass_item": None, "auth_command": None}
    write_config(project, sites)
    monkeypatch.setattr(runner_module, "run",
                        lambda argv, timeout: pytest.fail("no site CLI may run"))

    with pytest.raises(ClientError, match="invalid site name"):
        discover.discover(f"../../../../../../{escape.name}", RUN, 7)
    assert not escape.exists()


def test_merge_rejects_a_traversing_run_id_and_stores_nothing(project, runner):
    outcome = runner.invoke(app, ["merge", "../../../../tmp/mwtrav"])
    assert outcome.exit_code == 2, outcome.output
    assert "invalid run id" in outcome.output
    assert not paths.db_path().exists()


def test_discover_cli_rejects_a_traversing_run_id(project, runner):
    outcome = runner.invoke(app, ["discover", "humanrail",
                                  "--run-id", "../../../../tmp/mwtrav"])
    assert outcome.exit_code == 2, outcome.output
    assert "invalid run id" in outcome.output


def test_a_run_directory_relocated_outside_the_root_is_refused(
        project, monkeypatch, tmp_path):
    """The resolve-under-root assertion, independent of the shape patterns.

    A symlinked `agent_workspaces/discovery` would satisfy both regexes and
    still land the run outside the project, so the check is on the resolved
    path, not on the operand text.
    """
    outside = tmp_path.parent / "mw-outside"
    outside.mkdir(exist_ok=True)
    workspaces = project / "agent_workspaces"
    workspaces.mkdir(parents=True, exist_ok=True)
    (workspaces / "discovery").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ClientError, match="resolves outside"):
        paths.run_dir(RUN)


def test_merge_never_stores_a_traversal_string_as_a_run_id(project, runner):
    """The full path: envelopes exist, but the run id itself is refused."""
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
    assert runner.invoke(app, ["merge", RUN]).exit_code == 0
    outcome = runner.invoke(app, ["merge", "20260902T000000Z/../../.."])
    assert outcome.exit_code == 2, outcome.output
    rows = json.loads(runner.invoke(app, ["runs", "list"]).stdout)
    assert [row["run_id"] for row in rows] == [RUN]
