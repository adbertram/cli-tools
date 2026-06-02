import pytest

from n8n_cli.package_inventory import (
    classify_package_metadata,
    follows_n8n_package_convention,
    node_belongs_to_package,
    package_base_name,
    resolve_installed_package_name,
)


def test_scoped_n8n_package_names_follow_convention():
    assert follows_n8n_package_convention("@chrishdx/n8n-nodes-codex-cli-lm")
    assert package_base_name("@chrishdx/n8n-nodes-codex-cli-lm") == "n8n-nodes-codex-cli-lm"


def test_invalid_scoped_package_name_fails_clearly():
    with pytest.raises(ValueError, match="Invalid scoped npm package name"):
        package_base_name("@chrishdx")


def test_resolve_installed_package_keeps_exact_scoped_name():
    packages = [{"packageName": "@chrishdx/n8n-nodes-codex-cli-lm"}]
    assert resolve_installed_package_name("@chrishdx/n8n-nodes-codex-cli-lm", packages) == "@chrishdx/n8n-nodes-codex-cli-lm"


def test_resolve_installed_package_supports_existing_short_custom_name():
    packages = [{"packageName": "n8n-nodes-brickowl"}]
    assert resolve_installed_package_name("brickowl", packages) == "n8n-nodes-brickowl"


def test_custom_marker_classifies_generated_package():
    package_json = {"n8nCliPackage": {"packageType": "custom"}}
    assert classify_package_metadata(package_json, has_bundled_cli=False) == "custom"


def test_bundled_cli_classifies_generated_package():
    assert classify_package_metadata({}, has_bundled_cli=True) == "custom"


def test_third_party_package_defaults_to_community():
    package_json = {
        "author": {"name": "Third Party"},
        "description": "Useful n8n integration",
        "repository": {"url": "https://github.com/example/n8n-nodes-example"},
    }
    assert classify_package_metadata(package_json, has_bundled_cli=False) == "community"


def test_package_without_marker_or_repository_defaults_to_community():
    package_json = {
        "author": {"name": "Example User"},
        "description": "n8n language model sub-node for Claude Code CLI",
        "repository": None,
    }
    assert classify_package_metadata(package_json, has_bundled_cli=False) == "community"


def test_node_type_matches_scoped_package_by_base_name():
    assert node_belongs_to_package(
        "n8n-nodes-codex-cli-lm.lmChatCodexCli",
        "@chrishdx/n8n-nodes-codex-cli-lm",
    )
