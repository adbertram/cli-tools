"""Secret-storage guidance regression tests for CLI-tool lifecycle docs."""

from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def _read_skill(relative_path: str) -> str:
    return (SKILL_ROOT / relative_path).read_text()


def _read_repo(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def test_cli_tool_skill_requires_secret_manager_for_reusable_credentials():
    skill_text = _read_skill("SKILL.md")
    assert (
        "Do not instruct users or agents to place reusable credentials in any `.env` file."
        in skill_text
    ), "SKILL.md must forbid storing reusable credentials in `.env` files."

    config_text = _read_skill("references/config-standards.md")
    assert (
        "Reusable raw credentials do not belong in any `.env` file." in config_text
    ), "config-standards.md must define the secret-manager boundary for reusable credentials."

    secrets_text = _read_skill("references/secrets.md")
    assert (
        "Do not tell users or agents to place those secrets in any `.env` file."
        in secrets_text
    ), "secrets.md must explicitly forbid `.env` storage for reusable secrets."
    assert (
        "The canonical naming schema is `<cli-tool>-<type>`." in secrets_text
    ), "secrets.md must define the canonical CLI-tool secret naming schema."
    assert (
        "secrets.sh set --tool <cli-tool> --type <type>" in secrets_text
    ), "secrets.md must document the tool/type set path."

    secret_skill_text = _read_repo("_repo/skills/cli-tool-secrets/SKILL.md")
    assert (
        "The canonical naming schema is `<cli-tool>-<type>`." in secret_skill_text
    ), "cli-tool-secrets skill must define the canonical naming schema."
    assert (
        "secrets.sh set --tool <cli-tool> --type <type>" in secret_skill_text
    ), "cli-tool-secrets skill must document the tool/type set path."


def test_cli_tool_workflows_include_secret_storage_review_rule():
    create_text = _read_skill("workflows/create-cli.md")
    assert (
        "must not be written into `.env.example` or any other `.env` file by an agent or human"
        in create_text
    ), "create-cli.md must forbid writing reusable secrets into `.env` files."
    assert (
        "Secret storage guidance: [Reusable credentials routed to secret manager / VIOLATION: guidance stores secrets in `.env`]"
        in create_text
    ), "create-cli.md AI review must verify secret-manager guidance."

    update_text = _read_skill("workflows/update-cli.md")
    assert (
        "must not be stored in any `.env` file by an agent or human" in update_text
    ), "update-cli.md must forbid storing reusable secrets in `.env` files."

    test_text = _read_skill("workflows/test-cli.md")
    assert (
        'AI Review: Verify reusable credentials are routed through the CLI-tools secret manager, not any `.env` file'
        in test_text
    ), "test-cli.md must include an AI review item for secret-manager enforcement."
    assert (
        "Reusable human-supplied secrets (API keys, usernames, passwords, client secrets, long-lived bearer tokens) MUST be stored and retrieved through the CLI-tools secret manager"
        in test_text
    ), "test-cli.md must define the secret-storage review requirement."


def test_readme_templates_route_reusable_credentials_to_secret_manager():
    template_paths = [
        "templates/README_TEMPLATE.md",
        "templates/api/README.md",
        "templates/browser/README.md",
        "templates/wrapper/README.md",
    ]
    for relative_path in template_paths:
        text = _read_skill(relative_path)
        assert (
            "Do not put reusable credentials in any `.env` file." in text
        ), f"{relative_path} must tell users to keep reusable credentials out of `.env`."


def test_secret_manager_policy_uses_cli_tools_profile_keychain():
    policy_text = _read_repo("_repo/_secret-manager/access-policy.conf")
    assert (
        "keychain ~/.local/share/cli-tools/cli-tools.keychain-db" in policy_text
    ), "secret-manager access policy must target the CLI-tools user profile keychain."
    assert (
        "keychain ~/Library/Keychains/login.keychain-db" not in policy_text
    ), "secret-manager access policy must not target the login keychain."


def test_readme_templates_do_not_show_inline_or_env_secret_examples():
    forbidden_snippets = {
        "templates/README_TEMPLATE.md": [
            "auth login -u your@email.com -p yourpassword",
            "{TOOLNAME}_API_KEY=your_api_key",
            "{TOOLNAME}_CLIENT_SECRET=your_client_secret",
            "You can also set these as environment variables directly.",
        ],
        "templates/api/README.md": [
            "auth login --api-key YOUR_API_KEY",
            "{{NAME}}_API_KEY=your_api_key",
            "{{NAME}}_CLIENT_SECRET=your_client_secret",
        ],
        "templates/browser/README.md": [
            "{{NAME}}_USERNAME=your_username",
            "{{NAME}}_PASSWORD=your_password",
        ],
    }
    for relative_path, snippets in forbidden_snippets.items():
        text = _read_skill(relative_path)
        for snippet in snippets:
            assert snippet not in text, (
                f"{relative_path} still demonstrates reusable secret storage or "
                f"inline credential passing: {snippet}"
            )


def test_cli_tool_expert_agent_carries_secret_manager_rule():
    expected = (
        "Do not store or document API keys, usernames, passwords, client secrets, "
        "or other reusable credentials in any `.env` file."
    )
    toml_text = _read_repo("_repo/agents/cli-tool-expert.toml")
    markdown_text = _read_repo("_repo/agents/cli-tool-expert.md")
    assert expected in toml_text, (
        "cli-tool-expert.toml must require the secret manager instead of `.env` files."
    )
    assert expected in markdown_text, (
        "cli-tool-expert.md must require the secret manager instead of `.env` files."
    )
