from pathlib import Path

import notion_cli


def test_notion_cli_imports_from_this_project():
    project_root = Path(__file__).resolve().parents[1]
    imported_package = Path(notion_cli.__file__).resolve().parent

    assert imported_package == project_root / "notion_cli"
