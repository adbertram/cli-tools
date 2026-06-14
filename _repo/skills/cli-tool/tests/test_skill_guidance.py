"""The cli-tool guidance must reflect the lean CLI contract."""

from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (SKILL_ROOT / relative_path).read_text()


def _words(text: str) -> str:
    return " ".join(text.split())


def test_skill_no_longer_mandates_pydantic_models():
    text = _read("SKILL.md")
    forbidden = [
        "Model-Driven Architecture",
        "All CLI tools use Pydantic models",
        "Commands return typed models, not raw dicts",
        "uses requests, pydantic",
        "uses Playwright CLI with named sessions, BaseConfig, pydantic",
        "uses subprocess, pydantic",
        "Ensures models are defined and client returns models",
    ]
    found = [phrase for phrase in forbidden if phrase in text]
    assert found == [], (
        "SKILL.md still describes the old model-first template contract. "
        f"Remove or rewrite: {found}"
    )


def test_model_reference_describes_models_as_optional():
    text = _read("references/model-standards.md")
    forbidden = [
        "All CLI tools use Pydantic models",
        "All commands return Pydantic models | REQUIRED",
        "Client methods return typed models | REQUIRED",
        "Never return raw dicts from client | FORBIDDEN",
        "Every CLI must use Pydantic models",
    ]
    found = [phrase for phrase in forbidden if phrase in text]
    assert found == [], (
        "references/model-standards.md still treats local models as mandatory. "
        f"Remove or rewrite: {found}"
    )


def test_skill_places_usage_json_in_cli_skill_folder():
    text = _read("SKILL.md")

    assert "<cli-tools-root>/_repo/skills/<tool>-cli/usage.json" in text
    assert "Do not look for the command map in the CLI source folder" in text
    assert "scripts/regenerate-usage-json" in text
    assert "do not import `cli_test_utils` from ad-hoc Python" in text


def test_skill_requires_existing_path_operands_for_repo_probes():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Existing Path Operands Only" in text
    assert "prove each path exists" in text
    assert "Missing optional paths are command errors" in text
    assert "report skipped optional paths separately" in text
    assert "Do not rely on a downstream pipeline stage" in text
    assert "SKIPPED_MISSING_PATH" in text
    assert "NO_EXISTING_PATHS" in text
    assert "A no-match wrapper does not make missing operands safe" in text
    assert "Filter optional paths before the `rg` call" in text_words


def test_skill_requires_shaped_expected_no_match_searches():
    text = _read("SKILL.md")

    assert "Shape Expected No-Match Searches" in text
    assert "status `1` prints an explicit no-match marker and exits `0`" in text
    assert "An unguarded no-match status is a Tool Failure Protocol violation" in text
    assert "Do not use `|| true` unless the command immediately interprets" in text


def test_skill_requires_shaped_expected_live_api_probes():
    text = _read("SKILL.md")

    assert "Shape Expected Live API Probes" in text
    assert "fake or missing remote data to verify API wiring" in text
    assert "explicitly validate the expected exit status plus the expected error marker" in text
    assert "EXPECTED_FAILURE: fake field ID returned Airtable 404" in text
    assert "A bare CLI command that exits non-zero is a Tool Failure Protocol violation" in text


def test_skill_requires_literal_searches_for_template_tokens():
    text = _read("SKILL.md")

    assert "Literal Searches For Template Tokens" in text
    assert "`rg -n -F -- '{{description}}' <existing-path>`" in text
    assert "tokens such as `{{name}}`, `{{description}}`, or `{{AUTH_IMPORT}}`" in text
    assert "unless every regex metacharacter is intentionally escaped" in text


def test_skill_requires_per_tool_config_discovery_before_file_reads():
    text = _read("SKILL.md")

    assert "Per-Tool Project Config Discovery" in text
    assert "Do not assume `<cli-tools-root>/pyproject.toml` exists" in text
    assert "discover `<cli-tools-root>/<tool>/pyproject.toml`" in text
    assert "read it only after that exact file path exists" in text


def test_skill_requires_fresh_file_snapshot_before_patching():
    text = _read("SKILL.md")

    assert "Fresh File Snapshots Before Patching" in text
    assert "reread that exact file before preparing an `apply_patch` hunk" in text
    assert "current on-disk line" in text


def test_update_workflow_requires_current_ondisk_apply_patch_anchors():
    text = _read("workflows/update-cli.md")
    text_words = _words(text)

    assert "Patch Against Current File Anchors" in text
    assert "reread the exact target file" in text
    assert "Do not build a hunk from a sentence in the plan" in text_words


def test_test_workflow_documents_safe_harness_collection_command():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Harness-only collection" in text
    assert "python -m pytest --collect-only" in text
    assert "--force" in text
    assert "not a replacement" in text
    assert "test-cli-tool.sh --cli-name" in text
    assert "Targeted harness execution" in text
    assert "pass `--cli-name \"$TOOL_NAME\"`" in text_words
    assert "Use `--force` only for batch or collect-only harness" in text_words


def test_test_workflow_requires_serial_uv_validation():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "UV validation serialization" in text
    assert "Run `uv run`, `uv sync`, `uv lock`" in text
    assert "validation commands sequentially for this repo" in text_words
    assert "proven separate project directory, virtual environment, and `UV_CACHE_DIR`" in text_words
    assert "Do not launch multiple `uv run --project ... --with ...` pytest validations in parallel" in text_words
    assert "malformed `_uv_ephemeral_overlay.pth`" in text


def test_common_issues_uses_supported_test_cli_tool_invocation():
    text = _read("references/common-issues.md")

    assert "test-cli-tool.sh --cli-name myservice" in text
    assert "test-cli-tool.sh myservice" not in text


def test_common_issues_forbids_pip_inside_uv_tool_metadata_probes():
    text = _read("references/common-issues.md")
    text_words = _words(text)

    assert "Metadata Probe Fails: No module named pip" in text
    assert "Do not use `pip show`, `pip install`, or `python -m pip`" in text_words
    assert "inside a uv-managed CLI tool environment for diagnostics" in text_words
    assert "`importlib.metadata` from the launcher shebang interpreter" in text


def test_test_workflow_documents_harness_unit_monkeypatch_targets():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Harness unit monkeypatches" in text
    assert "patch the module object that owns the reference" in text_words
    assert "monkeypatch.setattr(sys.modules[__name__], \"run_cli_command\", fake)" in text_words
    assert 'Do not use a bare string target such as `"test_profiles.run_cli_command"`' in text_words
    assert "causing the real helper to execute" in text_words


def test_test_workflow_documents_live_auth_blockers():
    text = _read("workflows/test-cli.md")

    assert "LIVE_AUTH_BLOCKED" in text
    assert "Do not create fake credentials" in text
    assert "auth_required: true" in text
    assert "live compliance remains `LIVE_AUTH_BLOCKED`" in _read("workflows/create-cli.md")
    assert "live compliance remains `LIVE_AUTH_BLOCKED`" in _read("workflows/update-cli.md")


def test_browser_automation_requires_explicit_user_approval_after_api_discovery():
    skill = _read("SKILL.md")
    templates = _read("references/templates.md")
    create_workflow = _read("workflows/create-cli.md")
    update_workflow = _read("workflows/update-cli.md")
    auth_standards = _read("references/auth-standards.md")
    skill_words = _words(skill)
    templates_words = _words(templates)
    create_workflow_words = _words(create_workflow)
    update_workflow_words = _words(update_workflow)

    approval_question = (
        "No usable public or internal API path is available for this action. "
        "Should I make this command browser-driven?"
    )

    assert "Investigate public API, then internal APIs" in skill
    assert "stop before scaffolding or implementation" in skill_words
    assert approval_question in skill_words
    assert "Only use after confirming no public or internal API exists" in templates_words
    assert "explicitly approves making the command browser-driven" in templates
    assert "Do not auto-select **`browser` type**" in create_workflow
    assert "STOP: ask whether Adam wants a browser-driven command" in create_workflow
    assert "Browser Automation Approval Gate" in update_workflow
    assert "stop before adding browser code, browser credentials, or selectors" in update_workflow_words
    assert approval_question in create_workflow_words
    assert approval_question in update_workflow_words
    assert "explicitly approves the browser-driven command boundary" in auth_standards


def test_auth_guidance_documents_setup_instructions_and_non_secret_config_prompts():
    auth_standards = _read("references/auth-standards.md")
    templates = _read("references/templates.md")
    api_template = _read("templates/api/{{name}}_cli/config.py")

    assert "AUTH_CONFIG_PROMPTS" in auth_standards
    assert "AUTH_SETUP_INSTRUCTIONS" in auth_standards
    assert "Do not tell the user to edit `.env` manually" in auth_standards
    assert "AUTH_CONFIG_PROMPTS" in templates
    assert "AUTH_SETUP_INSTRUCTIONS" in templates
    assert "AUTH_CONFIG_PROMPTS" in api_template
    assert "AUTH_SETUP_INSTRUCTIONS" in api_template


def test_secret_guidance_documents_safe_prompt_automation():
    secrets = _read("references/secrets.md")

    assert "Interactive Prompt Automation" in secrets
    assert "Do not automate CLI credential prompts with `expect` while user logging is enabled" in secrets
    assert "log_user 0" in secrets
    assert "log_user 1" in secrets
    assert "Prefer non-echoing command input such as stdin, `SECRET_VALUE`, or a first-class CLI flag" in secrets
