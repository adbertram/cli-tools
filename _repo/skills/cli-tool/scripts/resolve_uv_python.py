#!/usr/bin/env python3
"""Resolve the interpreter that ``uv`` should use to install a CLI tool.

``uv tool install`` builds and resolves a tool against the interpreter it is
given. The cli-tools lifecycle scripts used to force ``--python <ambient
python3>``, which breaks whenever the ambient ``python3`` is older than a tool's
``requires-python`` (for example macOS system Python 3.9 against a ``>=3.11``
tool): uv then aborts with "requirements are unsatisfiable".

This resolver reads ``requires-python`` from a tool's ``pyproject.toml`` and
returns the value to pass to ``uv ... --python``:

* If the system ``python3`` already satisfies the constraint, return its
  absolute path so the installed CLI matches the interpreter the compliance
  test ``test_python_version.py::test_cli_uses_system_python`` measures.
* Otherwise, derive a compatible CPython minor from the constraint and return a
  version request such as ``3.11`` so uv finds or downloads that interpreter.
* If there is no parseable constraint, return the system ``python3`` path.

The interpreter is the absolute path of ``python3`` on PATH, not
``sys.executable``. Those two diverge whenever the caller launches a lifecycle
script with a non-system interpreter (an activated venv, a uv-managed
interpreter, an editor Python), and pinning the caller's interpreter then
installs the CLI against the wrong Python.

This resolver never returns an empty request. An empty request makes callers
drop ``--python`` entirely, and uv's default ``python-preference = "managed"``
then installs against a uv-managed interpreter (observed: CPython 3.12.10)
instead of the system one, which fails the compliance test with no obvious
cause. A missing or unusable ``python3`` raises instead.

Only the ``>=3.X`` lower bound and the ``<3.X`` exclusive upper bound are
parsed, which covers every constraint shape used in this repo (all tools pin a
single ``>=3.11`` lower bound). Anything uv cannot satisfy still surfaces as a
loud ``uv`` install failure in the caller; this resolver never suppresses it.

The resolver is stdlib-only and runs on Python 3.9 (the ambient interpreter that
invokes it), so it deliberately parses ``requires-python`` with a regex instead
of ``tomllib`` (3.11+).

Usage (shell):   resolve_uv_python.py <pyproject-path>
Usage (import):  resolve_uv_python_request(pyproject_path) -> str
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# These tools target CPython only, so the major version is always 3 and we
# reason purely about the minor version.
_REQUIRES_PYTHON = re.compile(r"""^\s*requires-python\s*=\s*["']([^"']+)["']""")
_LOWER_BOUND = re.compile(r">=\s*3\.(\d+)")
_UPPER_BOUND = re.compile(r"<\s*3\.(\d+)")


def _parse_minor_bounds(pyproject_path):
    """Return ``(lower_minor, upper_exclusive_minor)`` from requires-python.

    Either element is ``None`` when that bound is absent or unparseable.
    """
    spec = ""
    path = Path(pyproject_path)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _REQUIRES_PYTHON.match(line)
            if match:
                spec = match.group(1)
                break
    if not spec:
        return None, None
    lower = _LOWER_BOUND.search(spec)
    upper = _UPPER_BOUND.search(spec)
    return (
        int(lower.group(1)) if lower else None,
        int(upper.group(1)) if upper else None,
    )


def system_path_entries():
    """Return PATH entries as the CLI compliance tests see them.

    ``tests/cli_test_utils._clean_path`` drops the active virtualenv's ``bin``
    and prepends ``~/.local/bin`` before it measures ``python3 --version``. The
    installer must pin the same interpreter that test measures, so it applies
    the same two edits here.
    """
    entries = os.environ.get("PATH", "").split(os.pathsep)
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        venv_bin = os.path.join(virtual_env, "bin")
        entries = [entry for entry in entries if entry != venv_bin]
    user_bin = str(Path.home() / ".local" / "bin")
    if user_bin not in entries:
        entries.insert(0, user_bin)
    return entries


def system_python3_path():
    """Return the absolute path of the system ``python3``.

    Raises ``RuntimeError`` when PATH holds no ``python3``. Returning nothing
    would make the caller drop ``--python`` and let uv silently install against
    its own managed interpreter.
    """
    resolved = shutil.which("python3", path=os.pathsep.join(system_path_entries()))
    if not resolved:
        raise RuntimeError(
            "SYSTEM_PYTHON3_UNRESOLVED: no `python3` found on PATH after removing "
            "the active virtualenv bin. uv would then install the CLI against a "
            "uv-managed interpreter and fail "
            "tests/test_python_version.py::test_cli_uses_system_python. "
            "Put a python3 on PATH and retry."
        )
    return os.path.abspath(resolved)


def system_python3_minor(interpreter_path):
    """Return the CPython minor version of ``interpreter_path``.

    Returns ``None`` when the interpreter is not CPython 3.x. Raises
    ``RuntimeError`` when the interpreter cannot report its version.
    """
    result = subprocess.run(
        [interpreter_path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "SYSTEM_PYTHON3_UNUSABLE: {} could not report its version (exit {}): {}".format(
                interpreter_path, result.returncode, (result.stderr or "").strip()
            )
        )
    major, minor = result.stdout.split()
    if int(major) != 3:
        return None
    return int(minor)


def resolve_uv_python_request(pyproject_path):
    """Resolve the ``--python`` value uv should use for this tool.

    Returns the absolute system ``python3`` path (it already satisfies the
    constraint, or there is no constraint) or a ``3.<minor>`` version request
    (the system interpreter is out of range for ``requires-python``). Never
    returns an empty string; a missing or unusable ``python3`` raises
    ``RuntimeError``.
    """
    # The system python3 on PATH is the interpreter the compliance test
    # measures, and it is not necessarily the interpreter running this
    # resolver.
    system_path = system_python3_path()

    lower, upper = _parse_minor_bounds(pyproject_path)

    # No declared constraint: install against the system interpreter.
    if lower is None and upper is None:
        return system_path

    system_minor = system_python3_minor(system_path)
    system_satisfies = (
        system_minor is not None
        and (lower is None or system_minor >= lower)
        and (upper is None or system_minor < upper)
    )
    if system_satisfies:
        return system_path

    # System interpreter is out of range for requires-python. Derive a
    # compatible minor from the constraint and let uv find or download it.
    if upper is not None:
        target_minor = upper - 1
        if lower is not None and target_minor < lower:
            target_minor = lower
    else:
        target_minor = lower
    return "3.{}".format(target_minor)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: resolve_uv_python.py <pyproject-path>\n")
        return 2
    try:
        request = resolve_uv_python_request(argv[1])
    except RuntimeError as exc:
        sys.stderr.write("{}\n".format(exc))
        return 1
    sys.stdout.write(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
