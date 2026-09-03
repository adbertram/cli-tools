"""Repo-root resolution: coursecraft_project_root.

Regression coverage for the worktree-checkout defect reproduced 2026-09-03:
``coursecraft artifacts validate``, run from inside a CourseCraft *worktree*
checkout with COURSECRAFT_PROJECT_ROOT unset, silently resolved the CourseCraft
repo root to the hardcoded main checkout (DEFAULT_COURSECRAFT_ROOT) instead of
the worktree the caller was actually standing in -- borrowing the main
checkout's scripts and venvs and reporting a verdict that disagreed with the
Claude stop-gate hook, which pins COURSECRAFT_PROJECT_ROOT explicitly and
therefore resolved (correctly) to the worktree.

These tests never touch DEFAULT_COURSECRAFT_ROOT itself (a real, machine-specific
path); they only exercise the signal ladder ahead of it.
"""
from pathlib import Path

import pytest

from coursecraft_cli import coursecraft_project


@pytest.fixture(autouse=True)
def _clear_root_env(monkeypatch):
    """No ambient COURSECRAFT_PROJECT_ROOT/CLAUDE_PROJECT_DIR leaks into a test."""
    monkeypatch.delenv("COURSECRAFT_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


def _make_checkout(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "course-pipeline.json").write_text("{}\n")
    return root


def test_explicit_env_wins_outright_even_over_a_marker_at_cwd(tmp_path, monkeypatch):
    """COURSECRAFT_PROJECT_ROOT is honored exactly, never second-guessed against cwd."""
    explicit_root = _make_checkout(tmp_path / "explicit")
    other_checkout = _make_checkout(tmp_path / "elsewhere")
    monkeypatch.setenv("COURSECRAFT_PROJECT_ROOT", str(explicit_root))
    monkeypatch.chdir(other_checkout)

    assert coursecraft_project.coursecraft_project_root() == explicit_root


def test_explicit_env_set_but_not_a_directory_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("COURSECRAFT_PROJECT_ROOT", str(tmp_path / "absent"))

    with pytest.raises(coursecraft_project.CourseCraftProjectError):
        coursecraft_project.coursecraft_project_root()


def test_unset_env_resolves_to_the_worktree_cwd_is_standing_in(tmp_path, monkeypatch):
    """The reproduced defect: no env pin, cwd inside a worktree checkout.

    Previously this fell straight through to the hardcoded DEFAULT_COURSECRAFT_ROOT.
    A worktree checkout carries its own course-pipeline.json, so the cwd-marker
    walk must resolve to it instead.
    """
    worktree = _make_checkout(tmp_path / "worktrees" / "some-branch")
    (worktree / "sub").mkdir(parents=True)
    monkeypatch.chdir(worktree / "sub")

    assert coursecraft_project.coursecraft_project_root() == worktree


def test_unset_env_prefers_claude_project_dir_over_cwd(tmp_path, monkeypatch):
    """CLAUDE_PROJECT_DIR (the harness's per-session project dir) outranks cwd,
    matching coursecraft-validation's discover_repo_root signal order."""
    harness_root = _make_checkout(tmp_path / "harness-project")
    unrelated_cwd = _make_checkout(tmp_path / "unrelated")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(harness_root))
    monkeypatch.chdir(unrelated_cwd)

    assert coursecraft_project.coursecraft_project_root() == harness_root


def test_claude_project_dir_pointing_outside_any_checkout_falls_through_to_cwd(
    tmp_path, monkeypatch
):
    """CLAUDE_PROJECT_DIR is only ever a generic harness variable: it may name an
    unrelated project's directory when this CLI is invoked from a non-CourseCraft
    session. That must not be mistaken for the CourseCraft root -- it is
    marker-checked and skipped in favor of the next signal."""
    unrelated_project = tmp_path / "some-other-repo"
    unrelated_project.mkdir()
    worktree = _make_checkout(tmp_path / "worktree")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(unrelated_project))
    monkeypatch.chdir(worktree)

    assert coursecraft_project.coursecraft_project_root() == worktree


def test_unset_env_and_no_marker_anywhere_falls_back_to_the_default(tmp_path, monkeypatch):
    """No env pin, cwd outside any checkout: the well-known default still applies."""
    monkeypatch.chdir(tmp_path)

    assert (
        coursecraft_project.coursecraft_project_root()
        == coursecraft_project.DEFAULT_COURSECRAFT_ROOT
    )


def test_find_repo_root_marker_walks_ancestors(tmp_path):
    checkout = _make_checkout(tmp_path / "checkout")
    nested = checkout / "a" / "b" / "c"
    nested.mkdir(parents=True)

    assert coursecraft_project._find_repo_root_marker(nested) == checkout


def test_find_repo_root_marker_returns_none_when_absent(tmp_path):
    assert coursecraft_project._find_repo_root_marker(tmp_path) is None
