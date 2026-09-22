"""README contracts for cryptocom: credentials, Python floor, install path.

These pin the documentation against the contracts the code and packaging
actually enforce:

* reusable credentials go to the CLI-tools secret manager and the profile
  ``.env`` keeps only ``secret://`` references (``BaseConfig._validate_sensitive_placeholders``
  rejects a plain-text value in a sensitive field), and
* installation goes through the repo-owned installer, which pins the
  interpreter and overlays the repo-local editable ``cli-tools-shared``
  dependency declared in ``pyproject.toml``.
"""
import re
import tomllib
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]
README_PATH = TOOL_ROOT / "README.md"
README = README_PATH.read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((TOOL_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

SECRET_MANAGER_RULE = (
    "Do not put reusable credentials in any `.env` file. Store and retrieve them "
    "through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`."
)
INSTALL_COMMAND = (
    "<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh "
    "--force-refresh cryptocom"
)


def section(title):
    """Return the body of one `## <title>` README section."""
    match = re.search(
        rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)",
        README,
        re.DOTALL | re.MULTILINE,
    )
    assert match, f"README.md has no '## {title}' section"
    return match.group(1)


def test_requirements_python_floor_matches_pyproject():
    """The documented Python floor is the packaging floor."""
    requires_python = PYPROJECT["project"]["requires-python"]
    match = re.fullmatch(r">=\s*(\d+\.\d+)", requires_python.strip())
    assert match, f"unexpected requires-python form: {requires_python!r}"
    floor = match.group(1)

    requirements = section("Requirements")
    assert f"Python {floor}+" in requirements, (
        f"Requirements must state 'Python {floor}+' (pyproject requires-python "
        f"is {requires_python!r})"
    )

    claimed = re.findall(r"Python (\d+\.\d+)\+", README)
    assert claimed == [floor], (
        f"README claims Python floors {claimed}; only {floor} (the packaging "
        "floor) is supported"
    )


def test_configuration_routes_reusable_credentials_to_secret_manager():
    """Credentials live in the secret manager, never as plain `.env` values."""
    configuration = section("Configuration")

    assert SECRET_MANAGER_RULE in configuration, (
        "Configuration must route reusable credentials to the CLI-tools secret "
        "manager instead of `.env` files"
    )
    assert "Credentials are stored in profile-aware `.env` files" not in README, (
        "the reported stale sentence still claims credentials are stored in "
        "profile `.env` files"
    )

    assert "API_KEY=secret://cryptocom-api-key" in configuration
    assert "API_SECRET=secret://cryptocom-api-secret" in configuration

    # Every API_KEY / API_SECRET assignment shown must be a secret:// reference,
    # because a plain-text sensitive value fails profile validation at load time.
    for field_name in ("API_KEY", "API_SECRET"):
        values = re.findall(rf"^{field_name}=(\S*)$", configuration, re.MULTILINE)
        assert values, f"Configuration shows no {field_name} assignment"
        assert all(value.startswith("secret://") for value in values), (
            f"Configuration shows a plain-text {field_name} value: {values}"
        )


def test_installation_uses_canonical_installer_with_shared_dependency():
    """Install goes through the installer, which overlays cli-tools-shared."""
    installation = section("Installation")

    assert INSTALL_COMMAND in installation, (
        "Installation must use the repo-owned installer pinned to the system "
        "interpreter"
    )
    assert "uv tool install" not in README, (
        "a bare `uv tool install -e <tool dir>` omits the repo-local editable "
        "cli-tools-shared dependency overlay"
    )

    dependencies = PYPROJECT["project"]["dependencies"]
    assert any(
        dependency.split(">=")[0].strip() == "cli-tools-shared"
        for dependency in dependencies
    ), "pyproject.toml must declare the cli-tools-shared dependency"
    assert "cli-tools-shared" in installation, (
        "Installation must say the shared dependency is installed"
    )
