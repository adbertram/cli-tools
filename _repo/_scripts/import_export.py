#!/usr/bin/env python3
"""Import and export CLI-tools keychain/profile state."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SECRETS_SCRIPT = REPO_ROOT / "_repo" / "_secret-manager" / "secrets.sh"
SECRET_PREFIX = "secret://"
KEYCHAIN_PREFIX = "cli-tools.keychain-db"
SAFE_UNQUOTED = re.compile(r"^[A-Za-z0-9_./:@%+=,~-]*$")
NON_AUTH_BROWSER_DIR_NAMES = {
    "actorsafetylists",
    "amountextractionheuristicregexes",
    "captchaproviders",
    "certificaterevocation",
    "commerceheuristics",
    "crash reports",
    "crashpad",
    "crowd deny",
    "filetypepolicies",
    "firstpartysetspreloaded",
    "historysearch",
    "meipreload",
    "ondeviceheadsuggestmodel",
    "optimization_guide_model_store",
    "pkimetadata",
    "privacysandboxattestationspreloaded",
    "recoveryimproved",
    "safe browsing",
    "safetytips",
    "sslerrorassistant",
    "subresource filter",
    "trusttokenkeycommitments",
    "wasmttsengine",
    "widevinecdm",
    "zxcvbndata",
}
SENSITIVE_EXACT_FIELDS = {
    "API_KEY",
    "PERSONAL_ACCESS_TOKEN",
    "CLIENT_SECRET",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "USERNAME",
    "PASSWORD",
}
SENSITIVE_SUFFIXES = (
    "_API_KEY",
    "_PERSONAL_ACCESS_TOKEN",
    "_CLIENT_SECRET",
    "_ACCESS_TOKEN",
    "_REFRESH_TOKEN",
    "_USERNAME",
    "_PASSWORD",
)


def cli_tools_data_root() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "cli-tools"


def fail(message: str) -> None:
    raise SystemExit(f"import_export: {message}")


def normalize_secret_part(value: str) -> str:
    return value.lower().replace("_", "-")


def secret_name_for_field(tool_name: str, profile_name: str, field_name: str) -> str:
    tool_part = normalize_secret_part(tool_name)
    field_part = normalize_secret_part(field_name)
    prefix = f"{tool_part}-"
    if field_part.startswith(prefix):
        field_part = field_part[len(prefix) :]
    if normalize_secret_part(profile_name) == "default":
        return f"{tool_part}-{field_part}"
    return f"{tool_part}-{normalize_secret_part(profile_name)}-{field_part}"


def is_secret_placeholder(value: str) -> bool:
    return value.startswith(SECRET_PREFIX)


def secret_name_from_placeholder(value: str) -> str:
    if not is_secret_placeholder(value):
        fail(f"expected secret placeholder, got {value!r}")
    secret_name = value[len(SECRET_PREFIX) :]
    if not secret_name:
        fail("invalid empty secret placeholder")
    return secret_name


def is_sensitive_field(field_name: str) -> bool:
    return field_name in SENSITIVE_EXACT_FIELDS or field_name.endswith(SENSITIVE_SUFFIXES)


def read_secret(secrets_script: Path, secret_name: str) -> str:
    result = subprocess.run(
        [str(secrets_script), "get", secret_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"secret '{secret_name}' is missing from the CLI-tools keychain")
    value = result.stdout
    if value.endswith("\n"):
        value = value[:-1]
    if value.endswith("\r"):
        value = value[:-1]
    return value


def write_secret(secrets_script: Path, secret_name: str, value: str) -> None:
    result = subprocess.run(
        [str(secrets_script), "set", secret_name],
        input=value,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"failed to store secret '{secret_name}' in the CLI-tools keychain")


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        return None
    key, raw_value = line.split("=", 1)
    key = key.strip()
    value = raw_value.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]
    return key, value


def format_env_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        fail("profile .env values cannot contain newlines")
    if SAFE_UNQUOTED.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def replace_env_values(env_path: Path, replacements: dict[str, str]) -> None:
    lines = env_path.read_text().splitlines(keepends=True)
    updated: list[str] = []
    for line in lines:
        parsed = parse_env_line(line)
        if parsed is None:
            updated.append(line)
            continue
        key, _value = parsed
        if key not in replacements:
            updated.append(line)
            continue
        newline = "\n" if line.endswith("\n") else ""
        updated.append(f"{key}={format_env_value(replacements[key])}{newline}")
    env_path.write_text("".join(updated))


def iter_profile_env_files(data_root: Path) -> list[Path]:
    env_files: list[Path] = []
    for tool_dir in sorted(data_root.iterdir()):
        if not tool_dir.is_dir():
            continue
        profiles_dir = tool_dir / "authentication_profiles"
        if not profiles_dir.exists():
            continue
        env_files.extend(sorted(profiles_dir.glob("*/.env")))
    return env_files


def profile_parts(data_root: Path, env_path: Path) -> tuple[str, str]:
    relative = env_path.relative_to(data_root)
    if len(relative.parts) < 4 or relative.parts[1] != "authentication_profiles":
        fail(f"unexpected auth profile path: {env_path}")
    return relative.parts[0], relative.parts[2]


def copy_export_data(data_root: Path, export_data_root: Path) -> None:
    export_data_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(data_root.glob(f"{KEYCHAIN_PREFIX}*")):
        if source.is_file():
            shutil.copy2(source, export_data_root / source.name)
    for tool_dir in sorted(data_root.iterdir()):
        if not tool_dir.is_dir():
            continue
        target_tool_dir = export_data_root / tool_dir.name
        root_env = tool_dir / ".env"
        if root_env.exists():
            target_tool_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_env, target_tool_dir / ".env")
        profiles_dir = tool_dir / "authentication_profiles"
        if profiles_dir.exists():
            shutil.copytree(
                profiles_dir,
                target_tool_dir / "authentication_profiles",
                dirs_exist_ok=True,
                ignore=ignore_non_auth_browser_artifacts,
            )


def ignore_non_auth_browser_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        lower_name = name.lower()
        if lower_name.startswith("browser-data."):
            ignored.add(name)

    path_parts = [part.lower() for part in Path(directory).parts]
    if not any(part == "browser-data" for part in path_parts):
        return ignored

    for name in names:
        lower_name = name.lower()
        if "cache" in lower_name or lower_name in NON_AUTH_BROWSER_DIR_NAMES:
            ignored.add(name)
        elif lower_name in {"debug.log", "chrome_debug.log"}:
            ignored.add(name)
    return ignored


def inline_secret_placeholders(data_root: Path, secrets_script: Path) -> int:
    count = 0
    for env_path in iter_profile_env_files(data_root):
        replacements: dict[str, str] = {}
        for line in env_path.read_text().splitlines():
            parsed = parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            if not is_secret_placeholder(value):
                continue
            replacements[key] = read_secret(secrets_script, secret_name_from_placeholder(value))
        if replacements:
            replace_env_values(env_path, replacements)
            count += len(replacements)
    return count


def create_archive(source_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for child in sorted(source_dir.iterdir()):
            archive.add(child, arcname=child.name)


def safe_extract(archive_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                fail(f"archive contains unsupported link: {member.name}")
            target = (destination / member.name).resolve()
            if destination_resolved != target and destination_resolved not in target.parents:
                fail(f"archive contains unsafe path: {member.name}")
        archive.extractall(destination)


def copy_import_data(import_data_root: Path, data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(import_data_root.glob(f"{KEYCHAIN_PREFIX}*")):
        if source.is_file():
            shutil.copy2(source, data_root / source.name)
    for tool_dir in sorted(import_data_root.iterdir()):
        if not tool_dir.is_dir():
            continue
        target_tool_dir = data_root / tool_dir.name
        root_env = tool_dir / ".env"
        if root_env.exists():
            target_tool_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_env, target_tool_dir / ".env")
        profiles_dir = tool_dir / "authentication_profiles"
        if profiles_dir.exists():
            shutil.copytree(
                profiles_dir,
                target_tool_dir / "authentication_profiles",
                dirs_exist_ok=True,
            )


def placeholder_plain_text_profile_secrets(data_root: Path, secrets_script: Path) -> int:
    count = 0
    for env_path in iter_profile_env_files(data_root):
        tool_name, profile_name = profile_parts(data_root, env_path)
        replacements: dict[str, str] = {}
        for line in env_path.read_text().splitlines():
            parsed = parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            if not value or is_secret_placeholder(value) or not is_sensitive_field(key):
                continue
            secret_name = secret_name_for_field(tool_name, profile_name, key)
            write_secret(secrets_script, secret_name, value)
            replacements[key] = f"{SECRET_PREFIX}{secret_name}"
            count += 1
        if replacements:
            replace_env_values(env_path, replacements)
    return count


def command_export(args: argparse.Namespace) -> None:
    data_root = args.data_root.expanduser().resolve()
    archive_path = args.archive.expanduser().resolve()
    secrets_script = args.secrets_script.expanduser().resolve()
    if not data_root.exists():
        fail(f"data root does not exist: {data_root}")
    if not secrets_script.exists():
        fail(f"secret manager script does not exist: {secrets_script}")

    with tempfile.TemporaryDirectory(prefix="cli-tools-import-export.") as temp_dir:
        temp_root = Path(temp_dir)
        export_data_root = temp_root / "data"
        copy_export_data(data_root, export_data_root)
        inlined = 0
        if args.plain_text_secrets:
            inlined = inline_secret_placeholders(export_data_root, secrets_script)
        manifest = {
            "format": "cli-tools-import-export-v1",
            "plain_text_secrets": bool(args.plain_text_secrets),
            "inlined_profile_secrets": inlined,
        }
        (temp_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        create_archive(temp_root, archive_path)
    print(json.dumps({"archive": str(archive_path), "inlined_profile_secrets": inlined}))


def command_import(args: argparse.Namespace) -> None:
    data_root = args.data_root.expanduser().resolve()
    archive_path = args.archive.expanduser().resolve()
    secrets_script = args.secrets_script.expanduser().resolve()
    if not archive_path.exists():
        fail(f"archive does not exist: {archive_path}")
    if not secrets_script.exists():
        fail(f"secret manager script does not exist: {secrets_script}")

    with tempfile.TemporaryDirectory(prefix="cli-tools-import-export.") as temp_dir:
        temp_root = Path(temp_dir)
        safe_extract(archive_path, temp_root)
        import_data_root = temp_root / "data"
        if not import_data_root.exists():
            fail("archive is missing data/")
        copy_import_data(import_data_root, data_root)
    placeholdered = placeholder_plain_text_profile_secrets(data_root, secrets_script)
    print(json.dumps({"data_root": str(data_root), "placeholdered_profile_secrets": placeholdered}))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_export.py",
        description="Import and export CLI-tools keychain/profile state.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=cli_tools_data_root(),
        help="CLI-tools data root. Defaults to $XDG_DATA_HOME/cli-tools or ~/.local/share/cli-tools.",
    )
    parser.add_argument(
        "--secrets-script",
        type=Path,
        default=DEFAULT_SECRETS_SCRIPT,
        help="CLI-tools secret manager script.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    export_parser = subcommands.add_parser("export", help="Create an export archive.")
    export_parser.add_argument("archive", type=Path, help="Output .tar.gz archive path.")
    export_parser.add_argument(
        "--plain-text-secrets",
        action="store_true",
        help="Resolve auth profile secret:// placeholders into plain text inside the export archive.",
    )
    export_parser.set_defaults(func=command_export)

    import_parser = subcommands.add_parser("import", help="Import an export archive.")
    import_parser.add_argument("archive", type=Path, help="Input .tar.gz archive path.")
    import_parser.set_defaults(func=command_import)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
