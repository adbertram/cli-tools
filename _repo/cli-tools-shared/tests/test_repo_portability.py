"""Fresh-clone portability checks for the cli-tools monorepo."""

from pathlib import Path
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "templates",
    "venv",
}


def _pyprojects() -> list[Path]:
    projects = []
    for pyproject in sorted(REPO_ROOT.rglob("pyproject.toml")):
        rel_parts = pyproject.relative_to(REPO_ROOT).parts
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel_parts):
            continue
        projects.append(pyproject)
    return projects


def _lockfiles() -> list[Path]:
    lockfiles = []
    for lockfile in sorted(REPO_ROOT.rglob("uv.lock")):
        rel_parts = lockfile.relative_to(REPO_ROOT).parts
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel_parts):
            continue
        lockfiles.append(lockfile)
    return lockfiles


@pytest.fixture(params=_pyprojects(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def pyproject(request) -> Path:
    return request.param


@pytest.fixture(params=_lockfiles(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def lockfile(request) -> Path:
    return request.param


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_uv_path_sources_stay_inside_repo(pyproject: Path):
    """Local uv source paths must resolve inside this clone."""
    data = _load_toml(pyproject)
    sources = (
        data.get("tool", {})
        .get("uv", {})
        .get("sources", {})
    )

    for package_name, source in sources.items():
        entries = source if isinstance(source, list) else [source]
        for entry in entries:
            if not isinstance(entry, dict) or "path" not in entry:
                continue

            source_path = entry["path"]
            assert not source_path.startswith("~"), (
                f"{pyproject.relative_to(REPO_ROOT)} source {package_name} uses a home-relative path: "
                f"{source_path}"
            )

            raw_path = Path(source_path)
            assert not raw_path.is_absolute(), (
                f"{pyproject.relative_to(REPO_ROOT)} source {package_name} uses an absolute path: "
                f"{source_path}"
            )

            resolved = (pyproject.parent / raw_path).resolve()
            assert resolved == REPO_ROOT or REPO_ROOT in resolved.parents, (
                f"{pyproject.relative_to(REPO_ROOT)} source {package_name} resolves outside the repo: "
                f"{source_path} -> {resolved}"
            )
            assert resolved.exists(), (
                f"{pyproject.relative_to(REPO_ROOT)} source {package_name} points to a missing repo path: "
                f"{source_path}"
            )


def test_project_dependencies_do_not_use_local_file_urls(pyproject: Path):
    """Project dependencies must not depend on machine-local file URLs."""
    data = _load_toml(pyproject)
    dependencies = data.get("project", {}).get("dependencies", [])
    offenders = [
        dependency
        for dependency in dependencies
        if isinstance(dependency, str) and "file:" in dependency
    ]

    assert not offenders, (
        f"{pyproject.relative_to(REPO_ROOT)} has machine-local dependency references: {offenders}"
    )


def test_project_dependencies_do_not_use_git_urls(pyproject: Path):
    """Deployed CLI dependencies must not require Git."""
    data = _load_toml(pyproject)
    dependencies = data.get("project", {}).get("dependencies", [])
    dependency_offenders = [
        dependency
        for dependency in dependencies
        if isinstance(dependency, str) and "git+" in dependency
    ]

    sources = (
        data.get("tool", {})
        .get("uv", {})
        .get("sources", {})
    )
    source_offenders = []
    for package_name, source in sources.items():
        entries = source if isinstance(source, list) else [source]
        for entry in entries:
            if isinstance(entry, dict) and "git" in entry:
                source_offenders.append(package_name)

    assert not dependency_offenders, (
        f"{pyproject.relative_to(REPO_ROOT)} has Git dependency references: "
        f"{dependency_offenders}"
    )
    assert not source_offenders, (
        f"{pyproject.relative_to(REPO_ROOT)} has Git uv sources: {source_offenders}"
    )


def test_lockfiles_do_not_use_git_sources(lockfile: Path):
    """Resolved CLI environments must not depend on Git sources."""
    offenders = [
        line.strip()
        for line in lockfile.read_text().splitlines()
        if 'git = "' in line
    ]

    assert not offenders, (
        f"{lockfile.relative_to(REPO_ROOT)} has Git-locked package sources: {offenders}"
    )


def test_setuptools_package_data_does_not_escape_package(pyproject: Path):
    """Package data globs must stay inside their owning package directory."""
    data = _load_toml(pyproject)
    package_data = (
        data.get("tool", {})
        .get("setuptools", {})
        .get("package-data", {})
    )

    offenders = []
    for package_name, patterns in package_data.items():
        for pattern in patterns:
            if ".." in Path(pattern).parts:
                offenders.append(f"{package_name}: {pattern}")

    assert not offenders, (
        f"{pyproject.relative_to(REPO_ROOT)} has package-data entries that escape the package: "
        f"{offenders}"
    )
