import pytest
from typer.testing import CliRunner

from coursecraft_cli import main
from coursecraft_cli import google_docs
from coursecraft_cli.commands import course_outline
from coursecraft_cli.commands.course_outline import _parse_markdown_to_outline_update
from coursecraft_cli.google_docs import (
    LearningObjectivesParseError,
    build_module_table_updates,
    build_table_updates_from_fields,
    outline_table_indices_from_document,
    parse_course_outline,
    parse_learning_objective_entries,
)


runner = CliRunner()


def _cell(text):
    return {
        "content": [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": text}},
                    ]
                }
            }
        ]
    }


def _table(rows):
    return {
        "tableRows": [
            {"tableCells": [_cell(cell) for cell in row]}
            for row in rows
        ]
    }


def _document_with_shifted_outline_tables():
    return {
        "body": {
            "content": [
                {"table": _table([["Approved Date", "YYYY-MM-DD"]])},
                {
                    "table": _table([
                        ["Course Information \x0bInstructions", ""],
                        ["Course Title", "Old title"],
                        ["Length in minutes", "60"],
                    ])
                },
                {
                    "table": _table([
                        ["Course Planning \x0bInstructions", ""],
                        ["Learner Profile\x0bWho is this for?", "Old profile"],
                        ["Purpose\x0bWhat problem does this solve?", "Old purpose"],
                        ["Author Notes\x0bAdditional resources", "Example: old note"],
                        ["Short Description\x0bClear summary", "Old short"],
                    ])
                },
                {
                    "table": _table([
                        ["Learning Objectives \x0bInstructions", ""],
                        ["Type", "Objectives"],
                        ["Terminal", "Old terminal"],
                        ["Enabling", "Old enabling"],
                    ])
                },
                {
                    "table": _table([
                        ["Course Organization", "", ""],
                        ["10", "Module 10", "10 min"],
                        ["1", "Module 1", "15 min"],
                    ])
                },
            ]
        }
    }


def test_course_outline_singular_command_is_registered():
    result = runner.invoke(main.app, ["course-outline", "--help"])

    assert result.exit_code == 0
    assert "Manage course outline documents" in result.output


def test_course_outline_update_rejects_removed_database_target():
    result = runner.invoke(
        main.app,
        [
            "course-outline",
            "update",
            "openai-codex-advanced-features",
            "--type",
            "database",
            "--course-outline-file",
            "outline.md",
        ],
    )

    assert result.exit_code == 1
    assert "Invalid type(s): database" in result.output


def test_build_table_updates_uses_detected_tables_and_rows():
    document = _document_with_shifted_outline_tables()
    table_indices = outline_table_indices_from_document(document)

    updates = build_table_updates_from_fields(
        {
            "Target Length (Min)": 60,
            "Learner Profile": "Intermediate developers using Codex.",
            "Storyline": "A practical Codex workflow decision course.",
            "Author Notes": " ",
            "Short Description": "Learn advanced Codex workflows.",
            "Learning Objectives": "Terminal 1: Manage parallel work.\n- Use worktrees safely.",
        },
        document=document,
        table_indices=table_indices,
    )

    assert table_indices == {
        "course_info": 1,
        "course_planning": 2,
        "learning_objectives": 3,
        "course_organization": 4,
    }
    assert {"table": 1, "row": 2, "col": 1, "content": "60 minutes"} in updates
    assert {
        "table": 2,
        "row": 1,
        "col": 1,
        "content": "Intermediate developers using Codex.",
    } in updates
    assert {
        "table": 2,
        "row": 2,
        "col": 1,
        "content": "A practical Codex workflow decision course.",
    } in updates
    assert {"table": 2, "row": 3, "col": 1, "content": " "} in updates
    assert {"table": 3, "row": 2, "col": 0, "content": "Terminal"} in updates
    assert {"table": 3, "row": 2, "col": 1, "content": "Manage parallel work."} in updates
    assert {"table": 3, "row": 3, "col": 0, "content": "Enabling"} in updates
    assert {"table": 3, "row": 3, "col": 1, "content": "Use worktrees safely."} in updates
    assert all("label" not in update for update in updates)


def test_field_with_no_row_names_the_field_and_the_documents_real_rows():
    """The current Pluralsight template dropped the Platform/Tool Versions row."""
    document = _document_with_shifted_outline_tables()
    table_indices = outline_table_indices_from_document(document)

    with pytest.raises(RuntimeError) as excinfo:
        build_table_updates_from_fields(
            {"Platform/Tool Versions": "Cursor desktop app (latest)"},
            document=document,
            table_indices=table_indices,
        )

    message = str(excinfo.value)
    assert "Field 'Platform/Tool Versions' has no target row" in message
    assert "'course_planning' table" in message
    assert "Purpose What problem does this solve?" in message


class _FakeClient:
    def resolve_course_id(self, course):
        return "recFAKECOURSE0001"

    def get_record(self, table, record_id):
        return {
            "id": record_id,
            "fields": {
                "Platform": "Pluralsight",
                "Course Requirements Link": (
                    "https://docs.google.com/document/d/doc-under-test/edit"
                ),
            },
        }


@pytest.fixture
def _current_template_doc(monkeypatch):
    document = _document_with_shifted_outline_tables()
    monkeypatch.setattr(course_outline, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(google_docs, "get_document_structure", lambda _doc_id: document)
    monkeypatch.setattr(
        course_outline, "get_document_structure", lambda _doc_id: document
    )
    return document


def test_validate_only_fails_on_a_field_with_no_row(_current_template_doc):
    result = runner.invoke(
        main.app,
        [
            "course-outline", "update", "any-course",
            "--type", "google_doc",
            "--validate-only",
            "--platform-versions", "Cursor desktop app (latest)",
        ],
    )

    assert result.exit_code == 1
    assert "Field 'Platform/Tool Versions' has no target row" in result.output
    assert "Validation passed" not in result.output


def test_validate_only_passes_for_a_field_that_resolves(_current_template_doc):
    result = runner.invoke(
        main.app,
        [
            "course-outline", "update", "any-course",
            "--type", "google_doc",
            "--validate-only",
            "--storyline", "A practical Codex workflow decision course.",
        ],
    )

    assert result.exit_code == 0
    assert "Validation passed" in result.output
    assert "1 Google Doc table cell(s)" in result.output


def test_validate_only_agrees_with_the_write_path(_current_template_doc, monkeypatch):
    """A write must never be attempted for input --validate-only accepted, and vice versa."""
    def _refuse_write(*args, **kwargs):
        raise AssertionError("write attempted after row resolution failed")

    monkeypatch.setattr(course_outline, "_apply_table_updates", _refuse_write)

    write_result = runner.invoke(
        main.app,
        [
            "course-outline", "update", "any-course",
            "--type", "google_doc",
            "--platform-versions", "Cursor desktop app (latest)",
        ],
    )
    validate_result = runner.invoke(
        main.app,
        [
            "course-outline", "update", "any-course",
            "--type", "google_doc",
            "--validate-only",
            "--platform-versions", "Cursor desktop app (latest)",
        ],
    )

    assert write_result.exit_code == validate_result.exit_code == 1
    assert "Field 'Platform/Tool Versions' has no target row" in write_result.output
    assert "Field 'Platform/Tool Versions' has no target row" in validate_result.output


# --- Post-write verification (a write that changed nothing is never success) ---


def _doc_with_cell(text):
    return {"body": {"content": [{"table": _table([["Target Row", text]])}]}}


def test_verifier_rejects_a_cell_that_holds_more_than_was_written(monkeypatch):
    """A new value that is a prefix of the cell must not pass as 'already there'."""
    monkeypatch.setattr(
        course_outline,
        "get_document_structure",
        lambda _doc_id: _doc_with_cell("PARA ONE\nEXTRA SECTION\nMORE EXTRA"),
    )

    with pytest.raises(RuntimeError) as excinfo:
        course_outline._verify_table_updates(
            "doc-under-test",
            [{"table": 0, "row": 0, "col": 1, "content": "PARA ONE"}],
        )

    assert "expected 'PARA ONE' got 'PARA ONE EXTRA SECTION MORE EXTRA'" in str(excinfo.value)


def test_verifier_still_tolerates_google_docs_whitespace_reformatting(monkeypatch):
    monkeypatch.setattr(
        course_outline,
        "get_document_structure",
        lambda _doc_id: _doc_with_cell("PARA ONE\n"),
    )

    course_outline._verify_table_updates(
        "doc-under-test",
        [{"table": 0, "row": 0, "col": 1, "content": "PARA  ONE"}],
    )


def test_zero_applied_cells_passes_when_content_verifies(monkeypatch):
    """`updates: 0` is an idempotent no-op, not a failure.

    The applied-cell COUNT was replaced by content verification: what matters is
    that every targeted cell holds the requested content afterwards, which
    ``_verify_table_updates`` re-fetches and asserts. A document already holding
    the right content reports zero writes and is still correct.
    """
    class _Result:
        returncode = 0
        stdout = '{"documentId": "doc-under-test", "updates": 0}'
        stderr = ""

    verified = []
    monkeypatch.setattr(course_outline.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(
        course_outline, "_verify_table_updates", lambda *a, **k: verified.append(a)
    )

    payload = course_outline._apply_table_updates(
        "doc-under-test",
        [{"table": 0, "row": 0, "col": 1, "content": "PARA ONE"}],
    )

    assert payload == {"documentId": "doc-under-test", "updates": 0}
    assert verified, "every apply must re-verify the targeted cells"


def test_apply_table_updates_propagates_verification_failure(monkeypatch):
    """A cell that does not hold the requested content still fails loudly."""
    class _Result:
        returncode = 0
        stdout = '{"documentId": "doc-under-test", "updates": 1}'
        stderr = ""

    def _boom(*_a, **_k):
        raise RuntimeError("table cell mismatch")

    monkeypatch.setattr(course_outline.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(course_outline, "_verify_table_updates", _boom)

    with pytest.raises(RuntimeError) as excinfo:
        course_outline._apply_table_updates(
            "doc-under-test",
            [{"table": 0, "row": 0, "col": 1, "content": "PARA ONE"}],
        )

    assert "table cell mismatch" in str(excinfo.value)


def test_build_module_updates_finds_module_row_by_first_cell_not_position():
    document = _document_with_shifted_outline_tables()
    course_org_table = document["body"]["content"][4]["table"]

    updates = build_module_table_updates(
        module_number=1,
        content="Module 1 content",
        duration="15",
        table_index=4,
        table=course_org_table,
    )

    assert updates == [
        {"table": 4, "row": 2, "col": 1, "content": "Module 1 content"},
        {"table": 4, "row": 2, "col": 2, "content": "15 min"},
    ]

    updates = build_module_table_updates(
        module_number=1,
        duration="15 minutes",
        table_index=4,
        table=course_org_table,
    )

    assert updates == [
        {"table": 4, "row": 2, "col": 2, "content": "15 min"},
    ]


def test_build_module_updates_clears_all_module_cells():
    table = _table([
        ["Course Organization", "", ""],
        ["1", "Module 1", "15 min"],
        ["2", "Module 2", "15 min"],
        ["3", "Module 3", "15 min"],
        ["4", "Placeholder module", "10 min"],
    ])

    updates = build_module_table_updates(
        module_number=4,
        clear=True,
        table_index=4,
        table=table,
    )

    assert updates == [
        {"table": 4, "row": 4, "col": 0, "content": " "},
        {"table": 4, "row": 4, "col": 1, "content": " "},
        {"table": 4, "row": 4, "col": 2, "content": " "},
    ]


def test_build_module_updates_restores_a_cleared_module_slot():
    table = _table([
        ["Course Organization", "", ""],
        ["1", "Module 1", "15 min"],
        ["2", "Module 2", "15 min"],
        ["3", "Module 3", "15 min"],
        ["", "", ""],
    ])

    updates = build_module_table_updates(
        module_number=4,
        content="Restored Module 4",
        duration="10",
        table_index=4,
        table=table,
    )

    assert updates == [
        {"table": 4, "row": 4, "col": 0, "content": "4"},
        {"table": 4, "row": 4, "col": 1, "content": "Restored Module 4"},
        {"table": 4, "row": 4, "col": 2, "content": "10 min"},
    ]


def test_build_module_updates_rejects_a_nonempty_unidentified_slot():
    table = _table([
        ["Course Organization", "", ""],
        ["1", "Module 1", "15 min"],
        ["2", "Module 2", "15 min"],
        ["3", "Module 3", "15 min"],
        ["Unused", "Stale content", "10 min"],
    ])

    with pytest.raises(RuntimeError, match="Could not find Module 4 row or cleared slot"):
        build_module_table_updates(
            module_number=4,
            content="Restored Module 4",
            table_index=4,
            table=table,
        )


def test_clear_module_requires_module_number():
    result = runner.invoke(
        main.app,
        ["course-outline", "update", "any-course", "--type", "google_doc", "--clear-module"],
    )

    assert result.exit_code == 1
    assert "--clear-module requires --module" in result.output


def test_clear_module_rejects_module_content_options():
    result = runner.invoke(
        main.app,
        [
            "course-outline", "update", "any-course",
            "--type", "google_doc",
            "--module", "4",
            "--clear-module",
            "--module-duration", "10",
        ],
    )

    assert result.exit_code == 1
    assert "cannot be combined with module content or duration options" in result.output


# The Google Doc build consumes the approved course.outline_draft artifact.
def test_parse_course_outline_draft_markdown_for_google_doc_update(tmp_path):
    draft = tmp_path / "course_outline_draft.md"
    draft.write_text(
        """# Course Outline Draft - OpenAI Codex Advanced Features

## Course Description

**Short Description:** Learn advanced Codex workflows.

**Long Description:** Use worktrees, subagents, Computer Use, and skills to choose the right Codex workflow.

## Learner Context

**Learner Profile:** Intermediate developers who already use Codex.

**Prerequisites:**
- Prior use of Codex.
- Strong Git fluency.

## Module 1 - Managing Parallel Coding Work with Codex Worktrees

**Total Length:** 15 minutes

**Terminal Objective:** Demonstrate how to manage parallel coding tasks using Git worktrees in the Codex app.

**Enabling Learning Objectives:**
- Explain Local and Worktree mode.
- Start a thread in Worktree mode.

**Clips:**
- **Choosing Worktree Mode When You Need Parallel Safety** (3.5 minutes): Learners decide when isolation is useful.
- **Starting an Isolated Thread from the Right Base Branch** (4 minutes): Learners select a base branch.
""",
        encoding="utf-8",
    )

    parsed = _parse_markdown_to_outline_update(draft)

    assert parsed["fields"]["Short Description"] == "Learn advanced Codex workflows."
    assert parsed["fields"]["Storyline"] == parsed["fields"]["Long Description"]
    assert parsed["fields"]["Author Notes"] == " "
    assert parsed["fields"]["Learner Profile"] == "Intermediate developers who already use Codex."
    assert "- Strong Git fluency." in parsed["fields"]["(Required) Learner Prerequisites"]
    assert "Terminal 1: Demonstrate how to manage parallel coding tasks" in parsed["fields"]["Learning Objectives"]
    assert parsed["modules"][0]["module_number"] == 1
    assert parsed["modules"][0]["duration"] == "15 minutes"
    assert "Module 1 - Managing Parallel Coding Work" in parsed["modules"][0]["content"]
    assert "Clip 2: Starting an Isolated Thread from the Right Base Branch" in parsed["modules"][0]["content"]


# --- Learning Objectives parsing (both Pluralsight template shapes) ---

# Current template: every objective is a bullet line inside one cell, tagged
# with an inline marker. Google Docs delivers the soft breaks as \x0b.
_MARKER_BULLET_CELL = (
    "• [Terminal] Demonstrate how to extend Cursor AI's context using web search\x0b\x0b"
    "• [Enabling] Identify scenarios where the @Web feature provides value.\x0b\x0b"
    "• [Enabling] Show how to use @Web within the chat interface.\x0b\x0b"
    "• [Terminal] Demonstrate how to customize and extend Cursor AI\x0b\x0b"
    "• [Enabling] Demonstrate how to install a plugin from the marketplace.\x0b\x0b"
)


def _document_with_learning_objectives_table(rows):
    return {
        "title": "cursor-ai-advanced-features",
        "body": {
            "content": [
                {
                    "table": _table([
                        ["Course Information \x0bInstructions", ""],
                        ["Course Title", "Advanced Features of Cursor AI"],
                    ])
                },
                {"table": _table(rows)},
            ]
        },
    }


def _parse_objectives(rows, doc_id="doc-under-test"):
    document = _document_with_learning_objectives_table(rows)
    original = google_docs.get_document_structure
    google_docs.get_document_structure = lambda _doc_id: document
    try:
        return parse_course_outline(doc_id)
    finally:
        google_docs.get_document_structure = original


def test_current_template_marker_bullets_parse_into_objectives():
    parsed = _parse_objectives([
        ["Learning Objectives \x0bThis section is completed by Curriculum", ""],
        [_MARKER_BULLET_CELL, ""],
    ])

    assert parsed["fields"]["Learning Objectives"] == (
        "Terminal 1: Demonstrate how to extend Cursor AI's context using web search\n"
        "- Identify scenarios where the @Web feature provides value.\n"
        "- Show how to use @Web within the chat interface.\n"
        "\n"
        "Terminal 2: Demonstrate how to customize and extend Cursor AI\n"
        "- Demonstrate how to install a plugin from the marketplace."
    )


def test_older_template_terminal_enabling_rows_still_parse():
    parsed = _parse_objectives([
        ["Learning Objectives      What are objectives?", ""],
        ["Terminal", "1. Leverage Cursor's external documentation features."],
        ["Enabling", "- Identify scenarios where @Docs provides value.\n- Add a documentation source."],
        ["Terminal", "2. Manage and secure the use of Cursor AI for enterprises."],
        ["Enabling", "- Enable and enforce privacy mode organization-wide."],
    ])

    assert parsed["fields"]["Learning Objectives"] == (
        "Terminal 1: Leverage Cursor's external documentation features.\n"
        "- Identify scenarios where @Docs provides value.\n"
        "- Add a documentation source.\n"
        "\n"
        "Terminal 2: Manage and secure the use of Cursor AI for enterprises.\n"
        "- Enable and enforce privacy mode organization-wide."
    )


def test_parsed_objectives_round_trip_back_into_table_entries():
    """Output must stay readable by the doc-writeback parser."""
    parsed = _parse_objectives([
        ["Learning Objectives \x0bThis section is completed by Curriculum", ""],
        [_MARKER_BULLET_CELL, ""],
    ])

    entries = parse_learning_objective_entries(parsed["fields"]["Learning Objectives"])

    assert [entry["type"] for entry in entries] == [
        "Terminal", "Enabling", "Enabling", "Terminal", "Enabling",
    ]
    assert entries[1]["objective"] == "Identify scenarios where the @Web feature provides value."


def test_populated_but_unrecognized_objectives_table_raises():
    with pytest.raises(LearningObjectivesParseError) as excinfo:
        _parse_objectives(
            [
                ["Learning Objectives \x0bThis section is completed by Curriculum", ""],
                ["Some objective prose with no Terminal or Enabling marker at all.", ""],
            ],
            doc_id="1R67w9H-unrecognized",
        )

    message = str(excinfo.value)
    assert "1R67w9H-unrecognized" in message
    assert "Some objective prose with no Terminal or Enabling marker" in message


def test_genuinely_empty_objectives_table_returns_empty_string():
    parsed = _parse_objectives([
        ["Learning Objectives \x0bThis section is completed by Curriculum", ""],
        ["", ""],
    ])

    assert parsed["fields"]["Learning Objectives"] == ""


def test_course_outline_read_exits_non_zero_when_objectives_are_unparsed(monkeypatch):
    document = _document_with_learning_objectives_table([
        ["Learning Objectives \x0bThis section is completed by Curriculum", ""],
        ["Objective prose with no recognizable marker.", ""],
    ])
    monkeypatch.setattr(google_docs, "get_document_structure", lambda _doc_id: document)

    result = runner.invoke(
        main.app,
        ["course-outline", "read", "-l", "1R67w9H-unrecognized"],
    )

    assert result.exit_code == 1
    assert "1R67w9H-unrecognized" in result.output
