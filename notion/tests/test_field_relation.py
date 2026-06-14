"""Tests for relation properties on EXISTING databases via `notion field`.

API 2025-09-03 requires `relation.data_source_id` (NOT the legacy
`relation.database_id`). These tests assert the outgoing PATCH payload for
`field add` / `field update` carries `data_source_id`, mirroring the
database-create relation test. The Notion API is never hit: the client's
`_make_request` is replaced with a fake that resolves IDs and records the
PATCH body.
"""
import pytest
import typer

from notion_cli.client import NotionClient, NotFoundError
from notion_cli.commands import field as field_cmd


# Canonical fixture: a target database container "TARGET_DB" exposing a single
# data source "target-ds-1", and the database being edited "EDIT_DB" exposing
# data source "edit-ds-1".
CONTAINERS = {
    "target-db-container": {
        "object": "database",
        "id": "target-db-container",
        "data_sources": [{"id": "target-ds-1", "name": "Shared Context"}],
    },
    "edit-db-container": {
        "object": "database",
        "id": "edit-db-container",
        "data_sources": [{"id": "edit-ds-1", "name": "Build Products"}],
    },
}

# Data sources that exist as bare data_source IDs.
DATA_SOURCES = {
    "target-ds-1": {
        "object": "data_source",
        "id": "target-ds-1",
        "properties": {},
    },
    "edit-ds-1": {
        "object": "data_source",
        "id": "edit-ds-1",
        "properties": {
            "Project": {
                "id": "rel%3A",
                "type": "relation",
                "relation": {
                    "data_source_id": "old-target-ds",
                    "type": "dual_property",
                    "dual_property": {},
                },
            }
        },
    },
}


def make_client(patches):
    """Build a NotionClient whose _make_request is faked + records PATCHes."""
    client = NotionClient.__new__(NotionClient)
    client._resolution_cache = {}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        if method == "GET" and endpoint.startswith("/databases/"):
            db_id = endpoint.split("/databases/")[1]
            if db_id in CONTAINERS:
                return CONTAINERS[db_id]
            raise NotFoundError(f"no container {db_id}")
        if method == "GET" and endpoint.startswith("/data_sources/"):
            ds_id = endpoint.split("/data_sources/")[1]
            if ds_id in DATA_SOURCES:
                return DATA_SOURCES[ds_id]
            raise NotFoundError(f"no data source {ds_id}")
        if method == "PATCH" and endpoint.startswith("/data_sources/"):
            patches.append({"endpoint": endpoint, "data": data})
            # Echo back the updated property so the command can read it.
            props = (data or {}).get("properties", {})
            return {"object": "data_source", "id": endpoint.split("/")[-1],
                    "properties": props}
        raise AssertionError(f"unexpected request: {method} {endpoint}")

    client._make_request = fake_make_request
    return client


def run_add(monkeypatch, patches, **overrides):
    client = make_client(patches)
    monkeypatch.setattr(field_cmd, "get_client", lambda: client)
    monkeypatch.setattr(field_cmd, "print_json", lambda payload: None)
    monkeypatch.setattr(field_cmd, "print_success", lambda message: None)
    monkeypatch.setattr(field_cmd, "print_warning", lambda message: None)

    kwargs = dict(
        database_id="edit-db-container",
        name="Imports",
        prop_type="relation",
        options=None,
        formula_expression=None,
        relation_database="target-db-container",
        relation_type="dual_property",
        number_format=None,
    )
    kwargs.update(overrides)
    field_cmd.field_add(**kwargs)
    return patches


def run_update(monkeypatch, patches, **overrides):
    client = make_client(patches)
    monkeypatch.setattr(field_cmd, "get_client", lambda: client)
    monkeypatch.setattr(field_cmd, "print_json", lambda payload: None)
    monkeypatch.setattr(field_cmd, "print_success", lambda message: None)
    monkeypatch.setattr(field_cmd, "print_warning", lambda message: None)

    kwargs = dict(
        database_id="edit-db-container",
        name="Project",
        new_name=None,
        options=None,
        number_format=None,
        formula_expression=None,
        relation_database="target-db-container",
        relation_type=None,
    )
    kwargs.update(overrides)
    field_cmd.field_update(**kwargs)
    return patches


# --------------------------------------------------------------------------
# field add: relation -> data_source_id (not database_id)
# --------------------------------------------------------------------------


def test_field_add_relation_sends_data_source_id(monkeypatch):
    patches = run_add(monkeypatch, [])

    assert len(patches) == 1
    patch = patches[0]
    assert patch["endpoint"] == "/data_sources/edit-ds-1"
    imports = patch["data"]["properties"]["Imports"]["relation"]
    # The legacy key must NOT be present.
    assert "database_id" not in imports
    assert imports["data_source_id"] == "target-ds-1"
    assert imports["type"] == "dual_property"
    assert imports["dual_property"] == {}


def test_field_add_relation_accepts_bare_data_source_id(monkeypatch):
    # Passing the target's data_source ID directly must also resolve to it.
    patches = run_add(monkeypatch, [], relation_database="target-ds-1")

    imports = patches[0]["data"]["properties"]["Imports"]["relation"]
    assert imports["data_source_id"] == "target-ds-1"
    assert "database_id" not in imports


def test_field_add_relation_single_property(monkeypatch):
    patches = run_add(monkeypatch, [], relation_type="single_property")

    imports = patches[0]["data"]["properties"]["Imports"]["relation"]
    assert imports["type"] == "single_property"
    assert imports["single_property"] == {}
    assert imports["data_source_id"] == "target-ds-1"


def test_field_add_relation_requires_target(monkeypatch):
    with pytest.raises(typer.Exit):
        run_add(monkeypatch, [], relation_database=None)


# --------------------------------------------------------------------------
# field update: relation edits stay on data_source_id
# --------------------------------------------------------------------------


def test_field_update_relation_sends_data_source_id(monkeypatch):
    patches = run_update(monkeypatch, [])

    assert len(patches) == 1
    project = patches[0]["data"]["properties"]["Project"]["relation"]
    assert "database_id" not in project
    assert project["data_source_id"] == "target-ds-1"
    # Defaults to the existing relation type when only the target changes.
    assert project["type"] == "dual_property"


def test_field_update_relation_type_only_keeps_existing_target(monkeypatch):
    patches = run_update(
        monkeypatch, [], relation_database=None, relation_type="single_property"
    )

    project = patches[0]["data"]["properties"]["Project"]["relation"]
    assert project["data_source_id"] == "old-target-ds"
    assert project["type"] == "single_property"
    assert "database_id" not in project


# --------------------------------------------------------------------------
# build_property_schema unit coverage
# --------------------------------------------------------------------------


def test_build_property_schema_relation_uses_data_source_id():
    schema = field_cmd.build_property_schema(
        prop_type="relation",
        relation_data_source_id="ds-xyz",
        relation_type="dual_property",
    )
    assert schema == {
        "relation": {
            "data_source_id": "ds-xyz",
            "type": "dual_property",
            "dual_property": {},
        }
    }
    assert "database_id" not in schema["relation"]


def test_build_property_schema_relation_requires_target():
    with pytest.raises(ValueError):
        field_cmd.build_property_schema(prop_type="relation")
