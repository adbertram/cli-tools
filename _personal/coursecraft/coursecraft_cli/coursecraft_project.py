"""Access to the CourseCraft project checkout and the course folder tree.

A few CourseCraft writes are governed by contracts that have exactly one home in
the CourseCraft repository (the Demo Script cue contract, the proven-walk
contract). This CLI loads those contracts from the checkout instead of keeping a
second copy of the rule here, so the CLI and the artifact validators can never
disagree.

The same principle covers the executor verbs (``artifacts validate``,
``artifacts preflight``, ``status get``, ``courses scaffold``). The CLI is the
standard executor SURFACE; the domain logic stays in the CourseCraft checkout.
``run_coursecraft_script`` is the one dispatch seam those verbs share.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

DEFAULT_COURSECRAFT_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/CourseCraft")
DEFAULT_COURSES_ROOT = Path("/Users/adam/courses")
# The marker coursecraft-validation's `_shared.discover_repo_root` walks for. Both
# resolvers must agree on the same file, or a caller that honors one signal ladder
# can bind a different checkout than a caller that honors the other -- see
# `coursecraft_project_root` below.
_REPO_ROOT_MARKER = "course-pipeline.json"
# Course artifacts live outside the checkout. The CourseCraft repo reads the same
# override (scripts/validate_artifact.py, preflight_lib.py, the scaffolder), so the
# CLI and the repo resolve a relative course path to the same directory.
COURSES_ROOT = Path(
    os.environ.get("COURSECRAFT_COURSES_ROOT", str(DEFAULT_COURSES_ROOT))
).expanduser()


class CourseCraftProjectError(ValueError):
    """The CourseCraft checkout, or a script inside it, is unavailable.

    A ValueError so the existing callers that already catch ValueError around
    ``load_coursecraft_module`` keep reporting an unavailable checkout the same
    way they always have.
    """


def _find_repo_root_marker(start: Path) -> Path | None:
    """Walk ``start`` and its ancestors for the CourseCraft repo-root marker.

    Mirrors the marker coursecraft-validation's ``_shared.discover_repo_root``
    walks for, so a candidate that is not actually a CourseCraft checkout (for
    instance CLAUDE_PROJECT_DIR naming an unrelated project's directory) is never
    mistaken for one; it is skipped in favor of the next signal instead.
    """
    for candidate in (start, *start.parents):
        if (candidate / _REPO_ROOT_MARKER).is_file():
            return candidate
    return None


def coursecraft_project_root() -> Path:
    """The CourseCraft checkout.

    COURSECRAFT_PROJECT_ROOT wins outright when set -- this is what the Claude
    stop-gate hook pins before shelling this CLI out, and every explicit override
    must be honored exactly, never second-guessed against cwd.

    When it is unset, the CLI must not silently assume the well-known main
    checkout: a caller invoked from inside a CourseCraft *worktree* checkout has
    exactly one right answer, its own, not the main checkout that happens to sit
    at ``DEFAULT_COURSECRAFT_ROOT``. A worktree run with no env pin previously
    fell straight through to that default, silently borrowed the main checkout's
    scripts and venvs, and could report PASS on checks the worktree's own
    checkout would fail (or vice versa) -- one artifact, two verdicts, depending
    on which checkout happened to answer.

    So the remaining signals mirror coursecraft-validation's
    ``_shared.discover_repo_root`` ladder: CLAUDE_PROJECT_DIR (the harness's
    per-session, per-worktree project directory), then this process's own cwd.
    Each is accepted only if `course-pipeline.json` -- the same repo marker
    discover_repo_root walks for -- is found at that path or an ancestor, so a
    signal that names a directory outside any CourseCraft checkout is skipped
    rather than trusted. Only once neither signal names a real checkout does the
    well-known default apply.

    Raises CourseCraftProjectError when no signal -- including the default --
    resolves to a directory: a missing checkout is a hard failure, never a path
    that silently reads empty.
    """
    explicit = os.environ.get("COURSECRAFT_PROJECT_ROOT")
    if explicit:
        root = Path(explicit).expanduser()
        if not root.is_dir():
            raise CourseCraftProjectError(
                f"CourseCraft project root is unavailable: {root}. "
                "Set COURSECRAFT_PROJECT_ROOT to the CourseCraft project root."
            )
        return root

    for signal in (os.environ.get("CLAUDE_PROJECT_DIR"), str(Path.cwd())):
        if not signal:
            continue
        found = _find_repo_root_marker(Path(signal).expanduser())
        if found is not None:
            return found

    if DEFAULT_COURSECRAFT_ROOT.is_dir():
        return DEFAULT_COURSECRAFT_ROOT
    raise CourseCraftProjectError(
        f"CourseCraft project root is unavailable: {DEFAULT_COURSECRAFT_ROOT}. "
        "Set COURSECRAFT_PROJECT_ROOT to the CourseCraft project root."
    )


def python3_interpreter() -> str:
    """The interpreter that runs CourseCraft repo scripts.

    NOT ``sys.executable``: inside an installed CLI that is the uv tool venv,
    which holds this CLI's dependencies and none of the repo's. The wrapped
    scripts are stdlib-only, so the PATH ``python3`` is the correct interpreter
    and the one every direct caller already uses.
    """
    interpreter = shutil.which("python3")
    if interpreter is None:
        raise CourseCraftProjectError(
            "python3 is not on PATH; CourseCraft repo scripts cannot be run."
        )
    return interpreter


def coursecraft_cli_launcher() -> str:
    """This CLI's own launcher path, for scripts that shell ``coursecraft`` back.

    A wrapped script that calls the CLI must call THIS CLI, not whatever
    ``coursecraft`` PATH happens to resolve to in the child environment. The
    value is exported as COURSECRAFT_CLI, which those scripts already honor.
    """
    existing = os.environ.get("COURSECRAFT_CLI")
    if existing:
        return existing
    launcher = shutil.which("coursecraft")
    return launcher or "coursecraft"


def script_flags(pairs: Sequence[tuple[str, Any]]) -> list[str]:
    """Command-line flags for the option values a caller actually supplied.

    One builder for every executor verb: a True boolean becomes a bare flag, a
    value becomes a flag/value pair, and an unset option contributes nothing. A
    verb never invents a default the wrapped script did not ask for.
    """
    args: list[str] = []
    for flag, value in pairs:
        if value is True:
            args.append(flag)
        elif value is None or value is False or value == "":
            continue
        else:
            args.extend([flag, str(value)])
    return args


def run_coursecraft_script(
    relative_path: Union[str, Path],
    args: Sequence[str],
    *,
    timeout: int,
    interpreter: Sequence[str] | None = None,
    env_overrides: Mapping[str, str] | None = None,
) -> int:
    """Run a CourseCraft repo script and return its exit code verbatim.

    The script owns its stdout, its stderr, and its exit-code contract. This
    runner captures nothing and rewrites nothing:

    - stdout and stderr stream through unmerged, so a JSON consumer reads the
      script's bytes and a stderr-substring consumer still sees stderr alone;
    - the child's exit code is returned as-is, which preserves every 0/1/2
      trichotomy the CourseCraft scripts define;
    - stdin is /dev/null: an executor verb never prompts;
    - cwd is the repo root and COURSECRAFT_CLI names this CLI's launcher, so a
      script that shells the CLI back reaches the same build.

    Args:
        relative_path: Script path relative to the CourseCraft project root.
        args: Arguments passed to the script.
        timeout: Seconds to wait before killing the child.
        interpreter: Command prefix; defaults to the PATH ``python3``.
        env_overrides: Explicit record context or other child-only environment.

    Returns:
        The child's exit code.

    Raises:
        CourseCraftProjectError: The checkout or the script is unavailable, or
            the child exceeded ``timeout``.
    """
    root = coursecraft_project_root()
    script = root / relative_path
    if not script.is_file():
        raise CourseCraftProjectError(
            f"CourseCraft script is unavailable: {script}. "
            "Set COURSECRAFT_PROJECT_ROOT to the CourseCraft project root."
        )

    command = [*(interpreter or [python3_interpreter()]), str(script), *args]
    env = dict(os.environ)
    env["COURSECRAFT_CLI"] = coursecraft_cli_launcher()
    env["COURSECRAFT_PROJECT_ROOT"] = str(root)
    if env_overrides:
        env.update(env_overrides)
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CourseCraftProjectError(
            f"{script} timed out after {timeout}s."
        )
    return completed.returncode


def load_coursecraft_module(relative_path: Union[str, Path], module_name: str) -> Any:
    """Import a CourseCraft-owned contract module by its path in the checkout."""
    module_path = coursecraft_project_root() / relative_path
    if not module_path.is_file():
        raise ValueError(
            f"CourseCraft contract is unavailable: {module_path}. "
            "Set COURSECRAFT_PROJECT_ROOT to the CourseCraft project root."
        )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load CourseCraft contract: {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: contract modules declare dataclasses, and
    # @dataclass resolves field types through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def resolve_course_folder(folder_root: str) -> Path:
    """Resolve an Airtable ``Folder Root`` value to a directory on disk."""
    folder = Path(folder_root).expanduser()
    if not folder.is_absolute():
        folder = COURSES_ROOT / folder
    return folder
