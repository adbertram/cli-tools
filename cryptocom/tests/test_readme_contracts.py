"""README contracts for cryptocom: credentials, Python floor, install path.

These pin the documentation against the contracts the code and packaging
actually enforce:

* reusable credentials go to the CLI-tools secret manager and the profile
  ``.env`` keeps only ``secret://`` references (``BaseConfig._validate_sensitive_placeholders``
  rejects a plain-text value in a sensitive field), and
* installation goes through the repo-owned installer, which pins the
  interpreter and overlays the repo-local editable ``cli-tools-shared``
  dependency declared in ``pyproject.toml``, and
* the order that installer is documented to follow is the order it actually
  performs: install the tool (creating the venv and launcher) before the shared
  overlay,
* ``BASE_URL`` is root config rather than profile state: the shared field
  splitter routes it to the tool root ``.env`` because the tool does not declare
  it as an authentication field, and a profile ``.env`` carrying it is rejected
  at load, and
* credential rotation goes through the CLI-tools secret manager:
  ``auth login --force`` clears only ephemeral auth state.
"""
import ast
import re
import tomllib
import types
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
INSTALLER_PATH = (
    TOOL_ROOT.parent / "_repo/skills/cli-tool/scripts/install-cli-tool.sh"
)
# The installer's two ordering steps: the tool install (which creates the venv
# and the launcher) and the repo-local editable cli-tools-shared overlay.
INSTALLER_TOOL_STEP = 'uv tool install -e "$TOOL_DIR" --force --refresh'
INSTALLER_SHARED_OVERLAY_STEP = (
    'uv pip install --python "$UV_VENV/bin/python3" '
    '--editable "$LOCAL_SHARED_DIR" --reinstall'
)
DOCUMENTED_WRONG_ORDER = "before creating the launcher"
DOCUMENTED_ORDER = "then overlays the repo-local editable `cli-tools-shared`"


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


def test_installation_documents_installer_step_order():
    """The documented order is the installer's order: tool first, then overlay."""
    assert INSTALLER_PATH.is_file(), (
        f"installer not found at {INSTALLER_PATH}; the documented install "
        "order cannot be checked against the script that performs it"
    )
    installer = INSTALLER_PATH.read_text(encoding="utf-8")

    tool_step_at = installer.find(INSTALLER_TOOL_STEP)
    assert tool_step_at != -1, (
        f"installer no longer runs {INSTALLER_TOOL_STEP!r}; update this contract "
        "with the installer's real step"
    )
    overlay_step_at = installer.find(INSTALLER_SHARED_OVERLAY_STEP)
    assert overlay_step_at != -1, (
        f"installer no longer runs {INSTALLER_SHARED_OVERLAY_STEP!r}; update "
        "this contract with the installer's real step"
    )
    assert tool_step_at < overlay_step_at, (
        "installer no longer installs the tool before the cli-tools-shared "
        "overlay"
    )

    installation = " ".join(section("Installation").split())
    assert DOCUMENTED_WRONG_ORDER not in installation, (
        "Installation says cli-tools-shared is installed before the launcher "
        "exists; the installer creates the venv and launcher with the tool "
        "install and overlays cli-tools-shared afterwards"
    )
    assert DOCUMENTED_ORDER in installation, (
        "Installation must state that the repo-local editable cli-tools-shared "
        "overlay runs after the tool install"
    )


# ---------------------------------------------------------------------------
# Configuration scoping: BASE_URL is root config, credentials are profile state
# ---------------------------------------------------------------------------

CONFIG_PATH = TOOL_ROOT / "cryptocom_cli" / "config.py"
SHARED_ROOT = TOOL_ROOT.parent / "_repo/cli-tools-shared/cli_tools_shared"
AUTH_COMMANDS_PATH = SHARED_ROOT / "auth_commands.py"
ENV_EXAMPLE_PATH = TOOL_ROOT / ".env.example"
PRODUCTION_BASE_URL = "https://api.crypto.com/exchange/v1"
UAT_BASE_URL = "https://uat-api.3ona.co/exchange/v1"

# The sentence the review found wrong: `auth login --force` cannot rotate a
# stored secret, so it must not be presented as the rotation path.
ROTATION_WRONG = (
    "To rotate a stored credential, run `cryptocom auth login --force` "
    "rather than editing the profile."
)
ROTATION_RIGHT = (
    "`cryptocom auth login --force` clears only ephemeral auth state and "
    "cannot replace an already-stored secret"
)
# The sentence the review found wrong: BASE_URL is root config, and a profile
# `.env` carrying it fails profile validation.
SANDBOX_WRONG = f"Then set `BASE_URL={UAT_BASE_URL}` in that profile."
SANDBOX_RIGHT = "`BASE_URL` is a root config variable, not a profile setting"


def declared_fields():
    """Return the field names ``config.py`` declares, read with ``ast``.

    The declarations are read from the source of the tool under test rather
    than from an installed copy, so the contract tracks the config the loader
    actually uses.
    """
    declared = {
        "CUSTOM_REQUIRED_FIELDS": [],
        "CUSTOM_ALL_FIELDS": [],
        "ROOT_CONFIG_FIELDS": [],
    }
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in declared:
                declared[target.id] = [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
    return declared


def env_example_split():
    """Split ``.env.example`` the way the profile bootstrap splits it."""
    from cli_tools_shared.config import (
        _read_env_values,
        _split_env_values,
        root_config_field_names_for,
    )

    declared = declared_fields()
    root_config_fields = root_config_field_names_for(
        types.SimpleNamespace(ROOT_CONFIG_FIELDS=tuple(declared["ROOT_CONFIG_FIELDS"]))
    )
    auth_fields = set(declared["CUSTOM_ALL_FIELDS"]) | set(
        declared["CUSTOM_REQUIRED_FIELDS"]
    )
    auth_values, config_values = _split_env_values(
        _read_env_values(ENV_EXAMPLE_PATH),
        auth_fields,
        root_config_fields,
    )
    return root_config_fields, auth_fields, auth_values, config_values


def test_base_url_is_root_config_and_credentials_are_profile_state():
    """``BASE_URL`` splits into the root config ``.env``, never a profile."""
    root_config_fields, auth_fields, auth_values, config_values = env_example_split()

    assert "BASE_URL" in root_config_fields, (
        "the shared root-config defaults must keep BASE_URL"
    )
    assert "BASE_URL" not in auth_fields, (
        "config.py declares BASE_URL as an authentication field, so the loader "
        "rejects it in the root config .env, the profile bootstrap writes it "
        "into the profile it is mounted on, and the profile is then refused at "
        "load with 'Root config .env contains authentication fields'"
    )
    assert config_values == {"BASE_URL": PRODUCTION_BASE_URL}, (
        f"the split sent {sorted(config_values)} to the root config .env; "
        "BASE_URL must be the root config value"
    )
    assert sorted(auth_values) == ["ACTIVE", "API_KEY", "API_SECRET"], (
        f"the split sent {sorted(auth_values)} to the profile .env; only "
        "ACTIVE and the credential fields belong there"
    )


def test_configuration_documents_base_url_in_the_root_config_block():
    """Each Configuration block lists only fields the loader accepts there."""
    root_config_fields, auth_fields, _auth_values, _config_values = env_example_split()
    configuration = section("Configuration")
    root_block, _, profile_block = configuration.partition(
        "Authentication profile variables"
    )

    assert "BASE_URL=" in root_block, (
        "BASE_URL is root config for this tool, so the root config block must "
        "document it"
    )
    documented_root = re.findall(r"^([A-Z_][A-Z0-9_]*)=", root_block, re.MULTILINE)
    for name in documented_root:
        assert name in root_config_fields, (
            f"Configuration documents {name} as root config, but the loader "
            "does not accept it in the root config .env"
        )
        assert name not in auth_fields, (
            f"Configuration documents {name} as root config, but this tool "
            "declares it as an authentication field"
        )

    documented_profile = re.findall(r"^([A-Z_][A-Z0-9_]*)=", profile_block, re.MULTILINE)
    for name in documented_profile:
        assert name == "ACTIVE" or name in auth_fields, (
            f"Configuration documents {name} in the profile block, but the "
            "loader rejects non-authentication fields in a profile .env"
        )

    assert SANDBOX_WRONG not in README, (
        "Configuration tells the reader to set BASE_URL in a profile .env, "
        "which profile validation rejects"
    )
    assert SANDBOX_RIGHT in " ".join(configuration.split()), (
        "Configuration must state that BASE_URL is a root config variable"
    )


def test_configuration_routes_credential_rotation_to_the_secret_manager():
    """``auth login --force`` clears ephemeral state and cannot rotate a secret.

    The shared ``--force`` branch clears exactly ``combined_ephemeral_fields``,
    this tool declares no ephemeral fields, and ``_prompt_and_save`` skips a
    field that already holds a value.
    """
    shared = AUTH_COMMANDS_PATH.read_text(encoding="utf-8")
    force_branch = shared.split("if force:", 1)[1].split("\n\n", 1)[0]
    assert "_clear_login_state" in force_branch, (
        "the shared --force branch no longer clears login state; update this "
        "contract with the rotation path the CLI actually takes"
    )
    clear_body = shared.split("def _clear_login_state", 1)[1].split("\ndef ", 1)[0]
    assert "combined_ephemeral_fields" in clear_body, (
        "the shared --force branch no longer clears ephemeral fields only"
    )
    assert "CUSTOM_EPHEMERAL_FIELDS" not in CONFIG_PATH.read_text(encoding="utf-8"), (
        "this tool declares no ephemeral auth fields, so --force clears nothing "
        "and cannot rotate a stored secret"
    )

    configuration = " ".join(section("Configuration").split())
    assert ROTATION_WRONG not in README, (
        "Configuration still presents `cryptocom auth login --force` as the "
        "credential rotation path"
    )
    assert ROTATION_RIGHT in configuration, (
        "Configuration must state that `auth login --force` cannot replace an "
        "already-stored secret"
    )
    assert "secrets.sh set cryptocom-api-key" in configuration, (
        "Configuration must name the secret-manager command that rotates the "
        "stored credential"
    )
