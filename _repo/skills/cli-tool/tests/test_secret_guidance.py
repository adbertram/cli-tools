"""Secret-storage guidance regression tests for CLI-tool lifecycle docs."""

from __future__ import annotations

import re
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def _read_skill(relative_path: str) -> str:
    return (SKILL_ROOT / relative_path).read_text()


def _read_repo(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def _resolve_referenced_skill_dirs(agent_text: str, skills_root: Path | None) -> list[Path]:
    """Resolve the skill directories a compacted agent definition points to.

    Handles both runtime formats:
    - TOML `[[skills.config]]` entries carry an absolute `path` to the skill's
      `SKILL.md`; the skill directory is that file's parent.
    - Markdown frontmatter lists bare skill names under `skills:`; each resolves
      to `<skills_root>/<name>`.

    A full (non-compacted) definition references no skills and yields an empty list.
    """
    skill_dirs: list[Path] = []

    for raw_path in re.findall(r'path\s*=\s*"([^"]+)"', agent_text):
        candidate = Path(raw_path)
        if candidate.name == "SKILL.md":
            skill_dirs.append(candidate.parent)

    frontmatter = re.match(r"^---\n(.*?)\n---\n", agent_text, re.DOTALL)
    if frontmatter and skills_root is not None:
        in_skills_block = False
        for line in frontmatter.group(1).splitlines():
            if re.match(r"^skills:\s*$", line):
                in_skills_block = True
                continue
            if in_skills_block:
                item = re.match(r"^\s*-\s*(\S+)\s*$", line)
                if item:
                    skill_dirs.append(skills_root / item.group(1))
                elif line.strip() and not line.startswith((" ", "\t", "-")):
                    in_skills_block = False

    return skill_dirs


def _effective_agent_text(agent_text: str, skills_root: Path | None) -> str:
    """Agent text plus every referenced skill's SKILL.md and references/*.md.

    The cli-tool-expert agent may be a full definition (rule inline) or a
    compacted pointer that preserves the original instructions in a referenced
    inst-skill. Concatenating both lets one assertion cover either shape.
    """
    parts = [agent_text]
    for skill_dir in _resolve_referenced_skill_dirs(agent_text, skills_root):
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            parts.append(skill_md.read_text())
        references_dir = skill_dir / "references"
        if references_dir.is_dir():
            for reference in sorted(references_dir.glob("*.md")):
                parts.append(reference.read_text())
    return "\n".join(parts)


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


def test_secret_guidance_shapes_expected_missing_has_checks():
    expected_marker = "EXPECTED_MISSING_SECRET:%s"
    expected_status = 'if [ "$rc" -eq 1 ]; then'
    expected_capture = '2>&1)"; then'
    expected_warning = "do not run\n`has <name>` as a bare command"

    secrets_text = _read_skill("references/secrets.md")
    assert expected_marker in secrets_text, (
        "secrets.md must provide a copyable marker for expected missing secrets."
    )
    assert expected_status in secrets_text, (
        "secrets.md must consume the expected `has` status 1 explicitly."
    )
    assert expected_capture in secrets_text, (
        "secrets.md must capture expected-missing Keychain diagnostics."
    )
    assert expected_warning in secrets_text, (
        "secrets.md must forbid bare `has` when missing secrets are expected."
    )

    secret_skill_text = _read_repo("_repo/skills/cli-tool-secrets/SKILL.md")
    assert expected_marker in secret_skill_text, (
        "cli-tool-secrets skill must provide a copyable marker for expected missing secrets."
    )
    assert expected_status in secret_skill_text, (
        "cli-tool-secrets skill must consume the expected `has` status 1 explicitly."
    )
    assert expected_capture in secret_skill_text, (
        "cli-tool-secrets skill must capture expected-missing Keychain diagnostics."
    )


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

    # The cli-tool-expert agent may be a full definition (rule inline) or a
    # compacted pointer that preserves the original instructions in a referenced
    # inst-skill. Either way the agent must carry the secret-manager rule, so
    # assert against the agent file plus any inst-skill it points to. Derive the
    # external skills root from the TOML's absolute `[[skills.config]]` path so
    # the Markdown agent's bare `skills:` names resolve to the same root.
    config_path = re.search(r'path\s*=\s*"([^"]+)"', toml_text)
    skills_root = Path(config_path.group(1)).parents[1] if config_path else None

    toml_effective = _effective_agent_text(toml_text, skills_root)
    markdown_effective = _effective_agent_text(markdown_text, skills_root)

    assert expected in toml_effective, (
        "cli-tool-expert.toml (or the inst-skill it points to) must require the "
        "secret manager instead of `.env` files."
    )
    assert expected in markdown_effective, (
        "cli-tool-expert.md (or the inst-skill it points to) must require the "
        "secret manager instead of `.env` files."
    )
