"""The cli-tool guidance must reflect the lean CLI contract."""

from __future__ import annotations

import json
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


def test_service_skills_reference_adjacent_usage_json_path():
    skills_root = SKILL_ROOT.parent
    service_skills = sorted(skills_root.glob("*-cli/SKILL.md"))
    assert service_skills

    ambiguous = [
        str(path.relative_to(skills_root))
        for path in service_skills
        if "**MANDATORY: Consult `usage.json` before executing ANY"
        in path.read_text()
    ]
    assert ambiguous == []

    google_skill = (skills_root / "google-cli" / "SKILL.md").read_text()
    assert (
        "Consult the adjacent `usage.json` at "
        "`<cli-tools-root>/_repo/skills/<tool>-cli/usage.json`"
    ) in google_skill


def test_service_router_requires_wrapper_contract_before_raw_syntax():
    text = _read("workflows/skill-router.md")
    text_words = _words(text)

    assert "For wrapper CLIs" in text
    assert "wrapper's selected skill, `usage.json`, and live help as authoritative" in text_words
    assert "Do not assume the upstream tool's raw syntax works through the wrapper" in text_words
    assert "prove the wrapper command shape first" in text_words


def test_notion_pages_get_out_file_is_not_json_stdout():
    notion_skill = (SKILL_ROOT.parent / "notion-cli" / "SKILL.md").read_text()
    notion_words = _words(notion_skill)

    assert "When `pages get` uses `--out-file`, the Markdown file is the command output." in notion_skill
    assert "Do not redirect stdout to a `.json` file" in notion_words
    assert "do not parse stdout with `python3 -m json.tool` or `jq`" in notion_words
    assert "that the `--out-file` path exists" in notion_words
    assert "Do not require the file to be non-empty" in notion_words
    assert "run a separate `notion pages get PAGE_ID` command without `--markdown` or `--out-file`" in notion_words


def test_skill_documents_find_cli_tools_json_array_contract():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "one JSON array of records" in text_words
    assert 'jq -e \'.[] | select(.name == "google")\' <file>' in text
    assert "Do not treat the output as JSONL records" in text_words


def test_update_workflow_discovers_source_directory_before_reads():
    text = _read("workflows/update-cli.md")
    text_words = _words(text)

    assert "Resolve and Navigate to CLI Source Directory" in text
    assert "Do not assume `<cli-tools-root>/<name>` exists" in text
    assert "Use `<cli-tools-root>/_repo/scripts/find-cli-tools.sh`" in text
    assert "derive the source directory from the matching record's `readme` parent" in text_words
    assert "Only after the source directory is proven" in text_words


def test_create_workflow_requires_lastpass_profile_live_smoke_for_non_wrappers():
    text = _read("workflows/create-cli.md")

    assert "Step 9.7: LastPass Credential Discovery And Live Auth Smoke" in text
    assert "API and browser service CLIs with any auth type other than `none`" in text
    assert "SKIPPED_WRAPPER_AUTH: underlying CLI owns auth" in text
    assert "lastpass auth status" in text
    assert "lastpass items list --filter \"name:like:%<service-name>%\"" in text
    assert "<cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool <name>" in text
    assert "<name> auth status --profile <profile-name>" in text
    assert "LIVE_AUTH_BLOCKED: LastPass has no usable" in text
    assert "Prompt Adam to authenticate" in text
    assert "save the auth profile through the CLI" in text
    assert "You are not done until the CLI has saved that authenticated profile" in text
    assert "At least one live read-only service smoke command succeeded" in text
    assert "test-cli-tool.sh --cli-name <name>` passed with the saved authenticated profile" in text


def test_wrapper_workflows_require_upstream_binary_provisioning():
    create_text = _read("workflows/create-cli.md")
    update_text = _read("workflows/update-cli.md")
    templates_text = _read("references/templates.md")
    templates_words = _words(templates_text)
    wrapper_readme = _read("templates/wrapper/README.md")

    assert "Wrapper Upstream CLI Provisioning Gate" in create_text
    assert "Wrapper Upstream CLI Provisioning Gate" in update_text
    assert "official upstream binary named by `CLI_COMMAND`" in create_text
    assert "Missing `CLI_COMMAND` is an implementation blocker" in update_text
    assert "Wrapper CLIs must provision the official upstream binary" in templates_text
    assert "npm, pipx, uv, or a vendor installer" in templates_words
    assert "Install that tool first" not in wrapper_readme
    assert "a missing `{{cli_command}}` binary is an implementation blocker" in wrapper_readme


def test_skill_requires_launcher_interpreter_for_cli_importing_task_scripts():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Use the CLI's Own Interpreter for Manual Imports" in text
    assert "task-workspace scripts that import CLI packages or internals" in text_words
    assert "run those scripts with the launcher shebang interpreter instead of ambient `python3`" in text_words
    assert '"$interpreter" path/to/task_script_that_imports_cli.py' in text


def test_skill_requires_bounded_schema_safe_usage_json_inspection():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Schema-Safe Usage JSON Inspection" in text
    assert "root type, root keys, and `commands` keys" in text
    assert "print only the current node type and keys before indexing" in text_words
    assert "Avoid full-map dumps, recursive walks, interactive extractors" in text_words
    assert "probes that can block or emit excessive output" in text_words
    assert "MISSING_JSON_PATH: commands.<group>.<subcommand>" in text_words
    assert "do not run `if key in node` until `node` has been proven to be a dict" in text_words
    assert "MISSING_JSON_PATH: commands.items.commands.search available=[create,get,list,password,username]" in text_words


def test_lastpass_skill_documents_search_via_items_list_filter():
    text = _read("../lastpass-cli/SKILL.md")
    usage = json.loads(_read("../lastpass-cli/usage.json"))
    text_words = _words(text)

    assert "Vault search uses `lastpass items list --filter`, not `lastpass items search`" in text_words
    assert "search" not in usage["commands"]["items"]["commands"]
    assert "list" in usage["commands"]["items"]["commands"]


def test_skill_requires_existing_path_operands_for_repo_probes():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Existing Path Operands Only" in text
    assert "prove each path exists" in text
    assert "absolute operands under `<cli-tools-root>`" in text
    assert "optional root children such as `<cli-tools-root>/scripts`" in text
    assert "filter glob and optional operands to regular files" in text
    assert "directories such as `__pycache__` are command errors" in text
    assert "Missing optional paths are command errors" in text
    assert "wrong-kind operands are command errors" in text
    assert "report skipped optional paths separately" in text
    assert "Shell globs used as search operands are optional paths too" in text
    assert "`*/*_cli`, `tests`, or `docs`" in text
    assert "unmatched glob stays literal" in text
    assert "ripgrep exits with status" in text
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


def test_skill_requires_shaped_expected_mutation_safeguard_probes():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Shape Expected Mutation-Safeguard Probes" in text
    assert "mutating command refuses" in text
    assert "explicitly validate the expected exit status plus the exact refusal message" in text_words
    assert "Refusing to issue refund without --yes or --dry-run" in text
    assert "EXPECTED_FAILURE: refund command refused to mutate without --yes or --dry-run." in text


def test_skill_requires_shaped_expected_auth_status_probes():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Shape Expected Auth Status Probes" in text
    assert "intentionally checks for an unauthenticated profile" in text_words
    assert "explicitly validate the expected exit status plus the status evidence" in text_words
    assert "authenticated: false" in text
    assert "EXPECTED_STATUS: paypal profile is unauthenticated" in text
    assert "Do not run bare commands such as `paypal auth status -t`" in text
    assert "copilot auth status --profile default" in text
    assert "can exit `2` while returning structured JSON" in text


def test_test_workflow_shapes_auth_status_probe():
    text = _read("workflows/test-cli.md")

    forbidden_bare_probe = "$TOOL_NAME auth status " + "2>/dev/null"
    assert forbidden_bare_probe not in text
    assert "EXPECTED_STATUS: %s profile is unauthenticated." in text
    assert "\"authenticated\"[[:space:]]*:[[:space:]]*false" in text
    assert "other non-zero statuses remain tool failures" in text


def test_test_workflow_documents_direct_typer_exit_assertions():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Direct Typer command calls" in text
    assert "assert `pytest.raises(typer.Exit)` or `pytest.raises(click.exceptions.Exit)`" in text
    assert "`typer.Exit` is Click's `Exit` exception and is not a `SystemExit`" in text_words
    assert "wrappers such as `run_app(app)`" in text


def test_config_standards_forbid_arbitrary_config_auth_probes():
    text = _read("references/config-standards.md")
    text_words = _words(text)

    assert "Do not inspect arbitrary `Config` instance attributes" in text
    assert "cfg.active" in text
    assert "`<tool> auth status` JSON" in text
    assert "`ProfileStore`/`list_profiles`" in text


def test_copilot_guidance_forbids_inferred_format_flags():
    text = _read("../copilot-cli/SKILL.md")
    text_words = _words(text)
    usage = json.loads(_read("../copilot-cli/usage.json"))
    agent_list_options = {
        option["name"]
        for option in usage["commands"]["agent"]["commands"]["list"]["options"]
    }

    assert "--format" not in agent_list_options
    assert "--table" in agent_list_options
    assert "Do not add `--format json`" in text_words
    assert "JSON is already the default" in text_words
    assert "`copilot agent --help` is group help only" in text_words
    assert "`copilot agent list --help`" in text_words


def test_playwright_cli_guidance_distinguishes_eval_from_run_code():
    text = _read("../playwright-cli/SKILL.md")
    text_words = _words(text)

    assert "Eval Versus Run-Code" in text
    assert "`eval` executes JavaScript in the browser DOM context" in text
    assert "It does not receive a Playwright `page` object" in text_words
    assert "Do not pass `async (page) => page.locator(...)` to `eval`" in text_words
    assert "use `run-code` with `async (page) => { ... }`" in text_words


def test_playwright_cli_run_code_wrapper_surfaces_failure_stdout():
    text = _read("../playwright-cli/SKILL.md")
    text_words = _words(text)

    assert "print stdout as failure evidence" in text_words
    assert "because `run-code` writes markdown `### Error` output to stdout" in text_words
    assert 'printf \'PLAYWRIGHT_FAILED:%s rc=%s stdout=%s stderr=%s\\n\'' in text
    assert '[ -s "$out" ] && sed -n \'1,80p\' "$out" >&2' in text


def test_skill_requires_structured_cli_json_parsing_from_files():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "Structured CLI JSON Parsing" in text
    assert "save stdout to" in text_words
    assert "verify the command status and non-empty file" in text_words
    assert "az account list --all --output json | python3 - <<'PY'" in text
    assert "az account show --output json | python3 - <<'PY'" in text
    assert "json.load(sys.stdin)" in text
    assert "JSONDecodeError: Expecting value: line 1 column 1 (char 0)" in text
    assert "Broken pipe" in text
    assert "Before redirecting CLI JSON into a task-workspace artifact" in text
    assert 'mkdir -p "$workspace"' in text
    assert 'python3 - "$json_file"' in text
    assert "GET /api/providers" in text_words
    assert "MISSING_JSON_PATH: providers[0].config" in text
    assert "JSON_CONTRACT_MISMATCH: expected list root, got object keys=[...]" in text
    assert "rows[:10]" in text


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
    assert "<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name" in text
    assert "validation through `test-cli-tool.sh --cli-name" not in text
    assert "Targeted harness execution" in text
    assert "pass `--cli-name \"$TOOL_NAME\"`" in text_words
    assert "Use `--force` only for batch or collect-only harness" in text_words


def test_test_workflow_documents_safe_harness_batch_command():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Harness batch execution" in text
    assert "uv run --project <cli-tools-root>/_repo/skills/cli-tool python -m pytest <cli-tools-root>/_repo/skills/cli-tool/tests --force" in text_words
    assert "Do not run `python3 -m pytest <cli-tools-root>/_repo/skills/cli-tool/tests`" in text
    assert "bypasses the skill project's declared `cli-tools-shared` dependency" in text_words
    assert "CLI-dependent tests are only valid without `--cli-name` when `--force`" in text_words


def test_test_workflow_requires_shared_harness_path_discovery_before_reads():
    text = _read("workflows/test-cli.md")

    assert "Apply the same rule to shared harness paths" in text
    assert "Do not assume root-level paths such" in text
    assert "<cli-tools-root>/tests/conftest.py" in text
    assert "<cli-tools-root>/_repo/skills/cli-tool/tests" in text
    assert "<cli-tools-root>/_repo/cli-tools-shared/tests" in text
    assert "keep only proven regular files" in text


def test_test_workflow_requires_serial_uv_validation():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "UV validation serialization" in text
    assert "Run `uv run`, `uv sync`, `uv lock`" in text
    assert "validation commands sequentially for this repo" in text_words
    assert "proven separate project directory, virtual environment, and `UV_CACHE_DIR`" in text_words
    assert "Do not launch multiple `uv run --project ... --with ...` pytest validations in parallel" in text_words
    assert "malformed `_uv_ephemeral_overlay.pth`" in text


def test_test_workflow_documents_shared_package_pytest_command():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Direct shared-package pytest execution" in text
    assert "`<cli-tools-root>/_repo/cli-tools-shared`" in text
    assert "Do not run `uv run pytest` from inside" in text_words
    assert "ModuleNotFoundError:" in text
    assert "cli_tools_shared" in text_words
    assert "uv run --project <cli-tools-root>/_repo/cli-tools-shared --with pytest python -m pytest" in text_words
    assert "Do not combine shared-package test paths and per-tool test paths in one pytest invocation" in text_words
    assert "each suite resolves imports through its own uv project" in text_words


def test_skill_requires_tool_scoped_uv_for_python_source_introspection():
    text = _read("SKILL.md")
    text_words = _words(text)

    assert "tool-scoped Python introspection" in text
    assert "uv run --project <tool-dir> python" in text_words
    assert "not run system `python3` or bare `python`" in text_words


def test_test_workflow_requires_expected_red_wrapper_for_test_first_runs():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Expected-red test-first runs" in text
    assert "intended to fail before implementation" in text_words
    assert "do not run the bare pytest command" in text_words
    assert "validate the expected failure text" in text_words
    assert "EXPECTED_RED: test-first failure confirmed before implementation." in text
    assert "UNEXPECTED_PASS: test-first run passed before implementation." in text
    assert "do not key the wrapper only to directional pytest diff prose" in text_words
    assert "Left contains one more item" in text
    assert "Right contains one more item" in text


def test_test_workflow_documents_table_output_assertion_boundaries():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Table-output assertions" in text
    assert "Table output is display-only and may shorten cell values" in text_words
    assert "Do not assert full untruncated URLs, UUIDs, descriptions" in text_words
    assert "Assert those full values against default JSON output instead" in text_words
    assert "cell-level ellipsis is acceptable" in text_words


def test_test_workflow_documents_typer_parser_error_assertion_boundaries():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Typer/Rich parser-error assertions" in text
    assert "Removed command or option tests should assert the stable behavior" in text_words
    assert 'such as `"No such option"` or `"No such command"`' in text_words
    assert 'Do not assert exact formatted strings such as' in text
    assert '"No such option: --status"' in text
    assert "no mutation on the fake client" in text_words


def test_test_workflow_warns_about_direct_typer_command_calls():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Direct Typer command calls" in text
    assert "pass every Typer argument and option parameter explicitly" in text_words
    assert "typer.models.OptionInfo" in text
    assert "Prefer extracting a pure helper for command logic" in text_words


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


def test_test_workflow_documents_command_fake_lifecycle_methods():
    text = _read("workflows/test-cli.md")
    text_words = _words(text)

    assert "Command test fake lifecycle methods" in text
    assert "including cleanup methods reached in `finally` blocks such as `close()`" in text_words
    assert "Missing lifecycle methods are test-fixture bugs" in text_words
    assert "add the method to the fake instead of changing the production cleanup path" in text_words


def test_test_workflow_documents_live_auth_blockers():
    text = _read("workflows/test-cli.md")

    assert "LIVE_AUTH_BLOCKED" in text
    assert "Do not create fake credentials" in text
    assert "auth_required: true" in text
    assert "live compliance remains `LIVE_AUTH_BLOCKED`" in _read("workflows/create-cli.md")
    assert "live compliance remains `LIVE_AUTH_BLOCKED`" in _read("workflows/update-cli.md")


def test_dry_run_preview_guidance_requires_auth_free_isolated_launcher_smoke():
    test_workflow = _read("workflows/test-cli.md")
    auth_standards = _read("references/auth-standards.md")
    test_workflow_words = _words(test_workflow)
    auth_standards_words = _words(auth_standards)

    assert "Verify dry-run/preview commands that do not call live APIs run auth-free with isolated profile data" in test_workflow
    assert "CRITICAL dry-run/preview auth requirements" in test_workflow
    assert 'XDG_DATA_HOME="$tmpdir" <tool> <command> --dry-run' in test_workflow
    assert "fix the command credential declaration or shared registration path" in test_workflow_words
    assert 'COMMAND_CREDENTIALS = {"<command>": ["no_auth"]}' in test_workflow
    assert "registration-time\n  credential checks" in auth_standards
    assert "Map it to `[\"no_auth\"]`" in auth_standards_words
    assert "isolated profile data" in auth_standards_words


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
