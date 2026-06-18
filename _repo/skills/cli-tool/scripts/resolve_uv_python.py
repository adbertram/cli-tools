#!/usr/bin/env python3
"""Resolve the interpreter that ``uv`` should use to install a CLI tool.

``uv tool install`` builds and resolves a tool against the interpreter it is
given. The cli-tools lifecycle scripts used to force ``--python <ambient
python3>``, which breaks whenever the ambient ``python3`` is older than a tool's
``requires-python`` (for example macOS system Python 3.9 against a ``>=3.11``
tool): uv then aborts with "requirements are unsatisfiable".

This resolver reads ``requires-python`` from a tool's ``pyproject.toml`` and
returns the value to pass to ``uv ... --python``:

* If the ambient interpreter already satisfies the constraint, return its path
  so installs keep using the contextual interpreter (the prior behavior, with no
  regression for shells whose ``python3`` is already new enough).
* Otherwise, derive a compatible CPython minor from the constraint and return a
  version request such as ``3.11`` so uv finds or downloads that interpreter.
* If there is no parseable constraint, return the ambient interpreter path.

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

import re
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


def resolve_uv_python_request(pyproject_path):
    """Resolve the ``--python`` value uv should use for this tool.

    Returns an interpreter path (the ambient interpreter already satisfies the
    constraint, or there is no constraint) or a ``3.<minor>`` version request
    (the ambient interpreter is missing or out of range). Returns an empty
    string only when there is neither an ambient interpreter nor a constraint,
    in which case the caller omits ``--python`` and lets uv discover one.
    """
    # The resolver is invoked by the same ``python3`` uv would otherwise inherit
    # (run directly by the shell scripts, imported by new-cli-tool), so its own
    # interpreter is the ambient one.
    ambient_path = sys.executable or ""
    ambient_minor = sys.version_info[1] if sys.version_info[0] == 3 else None

    lower, upper = _parse_minor_bounds(pyproject_path)

    # No declared constraint: keep installing against the ambient interpreter.
    if lower is None and upper is None:
        return ambient_path

    ambient_satisfies = (
        ambient_minor is not None
        and (lower is None or ambient_minor >= lower)
        and (upper is None or ambient_minor < upper)
    )
    if ambient_satisfies and ambient_path:
        return ambient_path

    # Ambient interpreter is missing or out of range. Derive a compatible minor
    # from the constraint and let uv find or download it.
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
    sys.stdout.write(resolve_uv_python_request(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
