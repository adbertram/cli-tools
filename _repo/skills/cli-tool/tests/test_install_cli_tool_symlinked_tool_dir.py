"""install-cli-tool.sh must handle a tool directory that is a symlink.

``<cli-tools-root>/coursecraft`` is a symlink to the CourseCraft repository's
``tools/coursecraft`` checkout, and that checkout was installed with
``uv tool install -e <real path> --with-editable <ronin> --with-editable
<tether> ...``. The installer used to compare the symlink spelling of the tool
directory against the editable location uv reports (the real path), so the
health check never matched and every run fell through to a bare
``uv tool install -e`` that dropped the receipt's ``--with-editable`` entries
and failed with ``tether was not found in the package registry``.

Each test builds a fake cli-tools root whose tool directory is a symlink into
an external checkout, redirects ``HOME`` so the uv registry lives in the
fixture, and runs the real installer against a spying ``uv`` stub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
TOOL = "faketool"

FAKE_UV = """#!/usr/bin/env bash
set -uo pipefail
printf '%s\\n' "$*" >> "$UV_LOG"
case "${1:-} ${2:-}" in
    "tool install")
        mkdir -p "$HOME/.local/share/uv/tools/$FAKE_TOOL_NAME/bin" "$HOME/.local/bin"
        target="$HOME/.local/bin/.$FAKE_TOOL_NAME-real"
        printf '%s\\n' '#!/usr/bin/env bash' 'exit 0' > "$target"
        chmod +x "$target"
        ln -sf "$target" "$HOME/.local/bin/$FAKE_TOOL_NAME"
        exit 0
        ;;
    "pip show")
        if [ "${3:-}" = "$FAKE_TOOL_NAME" ]; then
            printf 'Name: %s\\nEditable project location: %s\\n' "$FAKE_TOOL_NAME" "$FAKE_EDITABLE_LOCATION"
            exit 0
        fi
        exit 1
        ;;
    "pip install")
        exit 0
        ;;
esac
printf 'unexpected uv args: %s\\n' "$*" >&2
exit 9
"""


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "fakeroot"
        skill_dir = self.root / "_repo" / "skills" / "cli-tool"
        shutil.copytree(SCRIPTS_DIR, skill_dir / "scripts")
        self.installer = skill_dir / "scripts" / "install-cli-tool.sh"

        self.real_tool_dir = tmp_path / "external" / TOOL
        self.real_tool_dir.mkdir(parents=True)
        (self.real_tool_dir / "pyproject.toml").write_text(
            '[project]\nname = "faketool"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
        )
        (self.root / TOOL).symlink_to(self.real_tool_dir)

        self.home = tmp_path / "home"
        self.venv = self.home / ".local" / "share" / "uv" / "tools" / TOOL
        (self.venv / "bin").mkdir(parents=True)
        bin_dir = self.home / ".local" / "bin"
        bin_dir.mkdir(parents=True)

        python_request = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "resolve_uv_python.py"), str(self.real_tool_dir / "pyproject.toml")],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        venv_python = self.venv / "bin" / "python3"
        if python_request.startswith("/"):
            venv_python.symlink_to(python_request)
        else:
            venv_python.write_text(f"#!/usr/bin/env bash\nprintf 'Python {python_request}.0\\n'\n")
            venv_python.chmod(0o755)

        launcher_target = bin_dir / f".{TOOL}-real"
        launcher_target.write_text("#!/usr/bin/env bash\nexit 0\n")
        launcher_target.chmod(0o755)
        (bin_dir / TOOL).symlink_to(launcher_target)

        self.uv_log = tmp_path / "uv.log"
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_uv = fake_bin / "uv"
        fake_uv.write_text(FAKE_UV)
        fake_uv.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "UV_LOG": str(self.uv_log),
            "FAKE_TOOL_NAME": TOOL,
            "FAKE_EDITABLE_LOCATION": str(self.real_tool_dir),
            "CLI_TOOLS_ALLOW_WORKTREE_INSTALL": "1",
        }

    def write_receipt(self, extras: list[str]) -> None:
        entries = [f'    {{ name = "{TOOL}", editable = "{self.real_tool_dir}" }},']
        entries += [f'    {{ name = "{Path(path).name}", editable = "{path}" }},' for path in extras]
        (self.venv / "uv-receipt.toml").write_text(
            "[tool]\nrequirements = [\n" + "\n".join(entries) + "\n]\n"
            'python = "/usr/bin/python3"\n'
            f'entrypoints = [\n    {{ name = "{TOOL}", install-path = "{self.home}/.local/bin/{TOOL}", from = "{TOOL}" }},\n]\n'
        )

    def run(self, *args: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        result = subprocess.run(
            [str(self.installer), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        uv_calls = self.uv_log.read_text().splitlines() if self.uv_log.exists() else []
        return result, uv_calls


def test_health_check_matches_editable_location_through_symlinked_tool_dir(tmp_path):
    fixture = Fixture(tmp_path)
    fixture.write_receipt(extras=[])

    result, uv_calls = fixture.run(TOOL)
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["success"] is True
    assert payload["install_output"] == "Existing editable install is healthy; skipped uv tool force refresh."
    assert payload["editable_location"] == str(fixture.real_tool_dir)
    assert not [call for call in uv_calls if call.startswith("tool install")], uv_calls


def test_reinstall_preserves_receipt_editable_requirements(tmp_path):
    fixture = Fixture(tmp_path)
    extras = [str(tmp_path / "external" / "ronin"), str(tmp_path / "external" / "tether")]
    fixture.write_receipt(extras=extras)

    result, uv_calls = fixture.run("--force-refresh", TOOL)
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["success"] is True
    install_calls = [call for call in uv_calls if call.startswith("tool install")]
    assert len(install_calls) == 1, uv_calls
    assert install_calls[0].startswith(
        f"tool install -e {fixture.real_tool_dir} "
        f"--with-editable {extras[0]} --with-editable {extras[1]} --force --refresh --python "
    ), install_calls[0]


def test_reinstall_without_extra_requirements_adds_no_with_editable(tmp_path):
    fixture = Fixture(tmp_path)
    (fixture.venv / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "{TOOL}", editable = "{fixture.real_tool_dir}" }}]\n'
        'python = "/usr/bin/python3"\n'
        f'entrypoints = [\n    {{ name = "{TOOL}", install-path = "{fixture.home}/.local/bin/{TOOL}", from = "{TOOL}" }},\n]\n'
    )

    result, uv_calls = fixture.run("--force-refresh", TOOL)
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["success"] is True
    install_calls = [call for call in uv_calls if call.startswith("tool install")]
    assert len(install_calls) == 1, uv_calls
    assert "--with-editable" not in install_calls[0]
    assert install_calls[0].startswith(f"tool install -e {fixture.real_tool_dir} --force --refresh --python ")
