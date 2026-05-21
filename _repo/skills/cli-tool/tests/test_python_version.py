"""Python version uniformity validation."""

import subprocess

import pytest

from cli_test_utils import get_python_version_from_venv, get_uv_tool_venv_dir


def test_cli_uses_system_python(cli_name, cli_dir, command_filter):
    """Validate CLI uses the system Python version.

    All CLIs should use whatever `python3` resolves to on the system.
    The install scripts pass `--python python3` to uv to ensure this.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    # Get system python3 version
    result = subprocess.run(
        ["python3", "--version"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.skip("python3 not available on system")

    system_version = result.stdout.strip()  # e.g. "Python 3.14.3"
    # Extract major.minor (e.g. "3.14")
    parts = system_version.replace("Python ", "").split(".")
    system_major_minor = f"{parts[0]}.{parts[1]}"

    # Check uv tool venv
    venv_path = get_uv_tool_venv_dir(cli_dir, cli_name)
    if venv_path is None:
        pytest.fail(
            f"uv tool venv not found for {cli_name}. "
            f"Fix: uv tool install -e {cli_dir} --force --refresh --python python3"
        )

    actual_version = get_python_version_from_venv(venv_path)

    assert system_major_minor in actual_version, (
        f"CLI uses {actual_version}, but system python3 is {system_version}. "
        f"Fix: uv tool install -e {cli_dir} --force --refresh --python python3"
    )
