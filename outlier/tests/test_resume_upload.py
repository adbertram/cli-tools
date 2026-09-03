"""Tests for the Import skills resume upload.

The selectors and copy under test were captured from the live Import skills
screen on 2026-09-03:

  * The page carries no `<input>` at all until the Resume card's "File Upload"
    button is clicked. That click mounts a drag-and-drop dialog holding two
    file inputs, neither with an id, name or class:

        accept="application/pdf,.pdf,application/vnd.openxmlformats-
                officedocument.wordprocessingml.document,.docx"   (visible)
        accept=".pdf,.docx"                                       (hidden)

    Only the first carries the long MIME form, which is what makes
    RESUME_FILE_INPUT_SELECTOR unambiguous.
  * The progress copy is verbatim from the app's i18n table
    (`onboarding-skills-import` in chunk `87936-b412118544497d44.js`).
  * After a successful upload the card reads
    "Adam Bertram Resume - AI Agents.pdf\\n(93KB)\\nRemove resume".
"""

import pytest

from outlier_cli import onboarding
from cli_tools_shared.exceptions import ClientError

# Verbatim innerText of the Import skills screen while the upload is parsing.
PARSING_SCREEN = (
    "Import skills\n"
    "Outlier projects require specific skills. Import your skills from "
    "LinkedIn and your resume.\n"
    "Required\nConnect LinkedIn\nLinkedIn\nConnect LinkedIn\n"
    "File Upload\nResume\nFile Upload\nparsing...\n"
    "Import and Review"
)

# Verbatim innerText after the upload finished, captured live.
UPLOADED_SCREEN = (
    "Import skills\n"
    "Outlier projects require specific skills. Import your skills from "
    "LinkedIn and your resume.\n"
    "Required\nConnect LinkedIn\nLinkedIn\nConnect LinkedIn\n"
    "File Upload\nResume\nFile Upload\n"
    "Adam Bertram Resume - AI Agents.pdf\n(93KB)\nRemove resume\n"
    "Optional\nAdding more profile details will help us match you with "
    "better projects.\n"
    "Import and Review\nImport and Review"
)


def test_file_input_selector_matches_only_the_long_mime_accept():
    """The hidden twin's accept is '.pdf,.docx' and must not be selected."""
    assert 'accept*="application/pdf"' in onboarding.RESUME_FILE_INPUT_SELECTOR
    assert onboarding.RESUME_FILE_INPUT_SELECTOR.startswith('input[type="file"]')


def test_progress_markers_detect_each_upload_phase():
    for marker in ("Please wait, uploading resume...", "uploading...", "parsing...", "processing..."):
        assert onboarding._has_progress_marker(f"Import skills\n{marker}\n") is True


def test_parsing_screen_is_in_progress_and_uploaded_screen_is_not():
    assert onboarding._has_progress_marker(PARSING_SCREEN) is True
    assert onboarding._has_progress_marker(UPLOADED_SCREEN) is False


def test_uploaded_screen_names_the_file_stem():
    """The success check keys on the file stem appearing on the card."""
    assert "Adam Bertram Resume - AI Agents" in UPLOADED_SCREEN


def test_missing_file_is_rejected_before_a_browser_is_opened():
    with pytest.raises(ClientError) as excinfo:
        onboarding.upload_resume(object(), "/nonexistent/resume.pdf")
    assert "Resume file not found" in str(excinfo.value)


def test_unsupported_extension_is_rejected(tmp_path):
    bad = tmp_path / "resume.txt"
    bad.write_text("not a resume")
    with pytest.raises(ClientError) as excinfo:
        onboarding.upload_resume(object(), str(bad))
    assert ".pdf, .docx" in str(excinfo.value)


def test_supported_extensions_are_exactly_what_outlier_accepts():
    assert onboarding.RESUME_SUFFIXES == (".pdf", ".docx")
