from pathlib import Path
import tomllib


def test_collision_safe_gemini_api_console_script_is_installed() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]

    assert project["scripts"]["gemini-api"] == "gemini_cli.main:app"
    assert project["scripts"]["gemini"] == "gemini_cli.main:app"