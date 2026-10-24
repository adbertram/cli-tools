"""find-cli-tools.sh must skip tool folders that contain a DISABLED marker."""

import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _make_tool(root: Path, name: str, disabled: bool) -> None:
    tool_dir = root / name
    tool_dir.mkdir()
    (tool_dir / "pyproject.toml").write_text(f'[project]\nname = "{name}-cli"\n')
    (tool_dir / "README.md").write_text(f"# {name}\n\n## DESCRIPTION\n\nTool {name}.\n")
    if disabled:
        (tool_dir / "DISABLED").write_text("disabled for test\n")


def test_find_cli_tools_skips_disabled_tools(tmp_path):
    (tmp_path / "_repo/scripts").mkdir(parents=True)
    (tmp_path / "_repo/_scripts/lib").mkdir(parents=True)
    script = tmp_path / "_repo/scripts/find-cli-tools.sh"
    shutil.copy(REPO_ROOT / "_repo/scripts/find-cli-tools.sh", script)
    shutil.copy(REPO_ROOT / "_repo/_scripts/lib/log.sh", tmp_path / "_repo/_scripts/lib/log.sh")
    _make_tool(tmp_path, "alpha", disabled=False)
    _make_tool(tmp_path, "beta", disabled=True)

    result = subprocess.run([str(script), "--json"], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert [record["name"] for record in json.loads(result.stdout)] == ["alpha"]
