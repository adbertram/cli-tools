"""Repository path helpers for editable cli-tools checkouts."""

from pathlib import Path


def find_cli_tools_repo_root(start: Path | None = None) -> Path:
    """Return the containing cli-tools repo root for this editable checkout."""
    probe = (start or Path(__file__)).resolve()
    for candidate in (probe, *probe.parents):
        repo_dir = candidate / "_repo"
        if (
            (repo_dir / "cli-tools-shared" / "pyproject.toml").is_file()
            and (repo_dir / "_secret-manager" / "secrets.sh").is_file()
        ):
            return candidate
    raise RuntimeError(
        f"Could not find cli-tools repo root from {probe}. "
        "Install this CLI from a clone of the cli-tools repository."
    )


def secret_manager_script(start: Path | None = None) -> Path:
    """Return the repo-owned CLI-tools secret manager script."""
    script = find_cli_tools_repo_root(start) / "_repo" / "_secret-manager" / "secrets.sh"
    if not script.is_file():
        raise RuntimeError(f"CLI-tools secret manager not found: {script}")
    return script
