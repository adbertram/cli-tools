"""Server-side n8n community package inventory helpers."""
import json
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

from .server import run_on_server_raw


N8N_NODES_DIR = str(Path.home() / ".n8n" / "nodes")
CUSTOM_PACKAGE_MARKER = "n8nCliPackage"


def package_base_name(package_name: str) -> str:
    """Return the npm package basename without scope or version."""
    name = package_name.strip()
    if not name:
        raise ValueError("Package name is required")
    if name.startswith("@"):
        parts = name.split("/", 1)
        if len(parts) != 2 or not parts[0][1:] or not parts[1]:
            raise ValueError(f"Invalid scoped npm package name: {package_name}")
        return parts[1].rsplit("@", 1)[0]
    return name.rsplit("@", 1)[0]


def follows_n8n_package_convention(package_name: str) -> bool:
    """Return true when the npm package basename follows n8n node naming."""
    base = package_base_name(package_name)
    return base.startswith("n8n-nodes-") or base.startswith("n8n-node-")


def classify_package_metadata(package_json: Dict[str, Any], has_bundled_cli: bool) -> str:
    """Classify a package as generated custom code or third-party community."""
    marker = package_json.get(CUSTOM_PACKAGE_MARKER) or {}
    if marker.get("packageType") == "custom":
        return "custom"
    if has_bundled_cli:
        return "custom"

    return "community"


def resolve_installed_package_name(package_name: str, packages: List[Dict[str, Any]]) -> str:
    """Resolve exact npm names and existing short custom names to installed packages."""
    requested = package_name.strip()
    if not requested:
        raise ValueError("Package name is required")

    installed = {pkg["packageName"] for pkg in packages}
    if requested in installed:
        return requested

    if not requested.startswith("@") and not requested.startswith("n8n-nodes-"):
        candidate = f"n8n-nodes-{requested}"
        if candidate in installed:
            return candidate

    return requested


def node_belongs_to_package(node_name: str, package_name: str) -> bool:
    """Match loaded n8n node type names to npm package names."""
    base = package_base_name(package_name)
    return node_name.startswith(f"{package_name}.") or node_name.startswith(f"{base}.")


def list_server_packages(nodes_dir: str = N8N_NODES_DIR) -> List[Dict[str, Any]]:
    """Read installed n8n community package metadata from the server runtime."""
    from .config import get_config

    get_config()
    script = r'''
import json
from pathlib import Path

root = Path(%(nodes_dir)r) / "node_modules"
packages = []

if root.exists():
    package_dirs = []
    for child in root.iterdir():
        if child.name.startswith("@") and child.is_dir():
            package_dirs.extend(p for p in child.iterdir() if p.is_dir())
        elif child.is_dir():
            package_dirs.append(child)

    for package_dir in sorted(package_dirs, key=lambda p: str(p)):
        package_json_path = package_dir / "package.json"
        if not package_json_path.exists():
            continue
        try:
            package_json = json.loads(package_json_path.read_text())
        except json.JSONDecodeError:
            continue
        n8n_meta = package_json.get("n8n") or {}
        keywords = package_json.get("keywords") or []
        if "n8n-community-node-package" not in keywords and not n8n_meta.get("nodes"):
            continue
        packages.append({
            "packageName": package_json.get("name") or package_dir.name,
            "installedVersion": package_json.get("version", ""),
            "description": package_json.get("description", ""),
            "authorName": (
                package_json.get("author", {}).get("name")
                if isinstance(package_json.get("author"), dict)
                else package_json.get("author")
            ),
            "repository": package_json.get("repository"),
            "keywords": keywords,
            "n8n": n8n_meta,
            "hasBundledCli": (package_dir / "cli" / "pyproject.toml").exists(),
            "marker": package_json.get(%(marker)r) or {},
        })

print(json.dumps(packages))
''' % {
        "nodes_dir": nodes_dir,
        "marker": CUSTOM_PACKAGE_MARKER,
    }
    command = f"python3 - <<'PY'\n{script}\nPY"
    result = run_on_server_raw(command, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)

    packages = json.loads(result.stdout)
    for package in packages:
        package["packageType"] = classify_package_metadata(
            {
                "author": {"name": package.get("authorName")},
                "description": package.get("description"),
                "repository": package.get("repository"),
                CUSTOM_PACKAGE_MARKER: package.get("marker"),
            },
            bool(package.get("hasBundledCli")),
        )
    return packages


def package_map(packages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index package metadata by package name."""
    return {pkg["packageName"]: pkg for pkg in packages}


def installed_package(package_name: str, packages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find an installed package by exact npm package name."""
    resolved = resolve_installed_package_name(package_name, packages)
    for package in packages:
        if package["packageName"] == resolved:
            return package
    return None


def npm_install_command(package_name: str) -> str:
    """Build the server npm install command for explicit manual package work."""
    return f"cd {shlex.quote(N8N_NODES_DIR)} && npm install {shlex.quote(package_name)} --save"
