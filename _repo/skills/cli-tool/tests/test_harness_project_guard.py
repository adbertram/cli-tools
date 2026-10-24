"""test-cli-tool.sh must refuse a harness copy whose uv project cannot supply its dependencies."""
import json
import shutil
import subprocess
from pathlib import Path


def test_unusable_harness_environment_fails_with_explicit_error(tmp_path):
    skill = Path(__file__).resolve().parents[1]
    # A partial copy of the skill: scripts only, no pyproject.toml, as on a host
    # where the project files were never deployed.
    copy = tmp_path / "_repo" / "skills" / "cli-tool"
    (copy / "scripts").mkdir(parents=True)
    script = copy / "scripts" / "test-cli-tool.sh"
    shutil.copy(skill / "scripts" / "test-cli-tool.sh", script)
    tool = tmp_path / "demo"
    executable = tool / ".venv" / "bin" / "demo"
    executable.parent.mkdir(parents=True)
    (tool / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    (tool / "README.md").write_text("# Demo\n\n## DESCRIPTION\n\nDemo CLI. Use it to test the harness.\n")
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(script), "--cli-name", "demo", "--cli-executable", str(executable)],
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env={"HOME": str(tmp_path / "home"), "PATH": str(Path(shutil.which("uv")).parent) + ":/usr/bin:/bin"},
    )
    assert result.returncode == 1
    error = json.loads(result.stderr.strip().splitlines()[-1])["error"]
    assert "harness environment is unusable" in error and "No module named" in error
