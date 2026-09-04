"""`versions registrars` is derived from the resolver table `versions sync` walks.

The framework's `file_registrar_mismatches` gate compares coverage-map.json's
`kind: file` declarations against the set of slugs this CLI can actually
resolve a path for, in both directions. It reads that set by running
`coursecraft versions registrars`, so the command must answer from the same
structure the sync walk iterates -- never from a literal list maintained
beside it. A second statement of the same fact is exactly the drift that once
let a slug be registered by the code while missing from the `sync --help`
enumeration.
"""

import json

import pytest
from typer.testing import CliRunner

from coursecraft_cli import artifact_versions
from coursecraft_cli.commands import versions as versions_command


EXPECTED_VERSIONS_SYNC_SLUGS = [
    "demo.automated_walkthrough",
    "demo.dictation_audio",
    "demo.environment_prep_script",
    "demo.host_requirements",
    "demo.manual_walkthrough",
    "module.powerpoint_deck",
]

# One record shape per registrar slug: (table, extra record fields,
# module_order, clip_order). Its keys are asserted to equal the resolver
# table's keys, so a new resolver with no fixture here fails rather than
# silently going untested.
RECORD_FIXTURES = {
    "demo.environment_prep_script": ("Demos", {}, None, None),
    "demo.host_requirements": ("Demos", {}, None, None),
    "demo.dictation_audio": ("Demos", {}, None, None),
    "demo.automated_walkthrough": (
        "Demos",
        {"Execution Method": versions_command.AUTOMATED_WALKTHROUGH_EXECUTION_METHOD},
        1,
        2,
    ),
    "demo.manual_walkthrough": ("Demos", {"Execution Method": "Manual"}, 1, 2),
    "module.powerpoint_deck": ("Modules", {"Order": 1}, None, None),
}

FOLDER_ROOT_FIELD = {"Demos": "Folder Root", "Modules": "Module Folder Root"}


def _run_registrars():
    result = CliRunner().invoke(versions_command.app, ["registrars"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_registrars_reports_every_file_slug_versions_sync_registers():
    assert _run_registrars() == {"versions_sync": EXPECTED_VERSIONS_SYNC_SLUGS}


def test_registrars_output_is_derived_from_the_resolver_table():
    """The emitted list is the table's keys, not a literal beside it."""
    assert _run_registrars()["versions_sync"] == sorted(versions_command.FILE_REGISTRARS)


def test_every_registrar_slug_has_a_record_fixture():
    assert set(RECORD_FIXTURES) == set(versions_command.FILE_REGISTRARS)


@pytest.mark.parametrize("slug", sorted(RECORD_FIXTURES))
def test_reported_slug_registers_through_the_sync_walk(slug, tmp_path, monkeypatch):
    """Every slug `registrars` reports really registers through the walk."""
    monkeypatch.setattr(artifact_versions, "COURSES_ROOT", tmp_path)
    table, extra_fields, module_order, clip_order = RECORD_FIXTURES[slug]
    folder = tmp_path / "a-course" / "m1" / "record"
    folder.mkdir(parents=True)
    fields = {FOLDER_ROOT_FIELD[table]: str(folder), **extra_fields}

    path = versions_command.FILE_REGISTRARS[slug]["path"](fields, module_order, clip_order)
    assert path is not None, f"{slug} resolved no path for its record fixture"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{slug} body\n", encoding="utf-8")

    updates = versions_command._seed_files(table, fields, {}, module_order, clip_order)

    assert slug in updates
    assert updates[slug]["path"] == str(path)
    assert updates[slug]["v"] == 1


def test_registrars_needs_no_airtable_client(monkeypatch):
    """The command must run offline -- the framework gate calls it with no auth."""
    def _explode(*args, **kwargs):
        raise AssertionError("versions registrars must not build an Airtable client")

    monkeypatch.setattr(versions_command, "get_client", _explode)

    assert _run_registrars() == {"versions_sync": EXPECTED_VERSIONS_SYNC_SLUGS}
