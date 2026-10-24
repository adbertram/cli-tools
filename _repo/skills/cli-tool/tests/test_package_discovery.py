"""Console entry points define the package inspected by compliance checks."""
from cli_test_utils import get_pkg_dir


def test_package_from_console_entry_point(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project.scripts]\ncoursecraft = "coursecraft.main:app"\n'
    )
    assert get_pkg_dir(tmp_path, "coursecraft") == tmp_path / "coursecraft"


def test_scaffold_package_without_script_metadata(tmp_path):
    assert get_pkg_dir(tmp_path, "example-tool") == tmp_path / "example_tool_cli"
