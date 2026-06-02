import json
import stat
import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "_repo" / "_scripts" / "import_export.py"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_secrets_script(path: Path, log_path: Path) -> None:
    _write_executable(
        path,
        """#!/usr/bin/env bash
set -euo pipefail
command="${1:?}"
name="${2:?}"
case "$command" in
  get)
    case "$name" in
      demo-api-key) printf 'demo-secret' ;;
      demo-client-secret) printf 'client secret with spaces' ;;
      *) exit 44 ;;
    esac
    ;;
  set)
    value="$(cat)"
    printf '%s=%s\n' "$name" "$value" >>"${SECRET_LOG:?}"
    ;;
  *)
    echo "unexpected command: $command" >&2
    exit 99
    ;;
esac
""",
    )


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = ["python3", str(SCRIPT), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False, env=env)


def _read_archive_file(archive_path: Path, member_name: str, extract_dir: Path) -> str:
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(extract_dir)
    return (extract_dir / member_name).read_text()


def test_export_plain_text_secrets_inlines_profile_placeholders(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data" / "cli-tools"
    profile = data_root / "demo" / "authentication_profiles" / "default" / ".env"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "ACTIVE=true\n"
        "API_KEY=secret://demo-api-key\n"
        "CLIENT_SECRET=secret://demo-client-secret\n"
        "CLIENT_ID=public-client\n"
    )
    browser_profile = profile.parent / "browser-data" / "chromium-profile"
    auth_files = [
        browser_profile / "Default" / "Cookies",
        browser_profile / "Default" / "Local Storage" / "leveldb" / "000003.log",
        browser_profile / "Default" / "IndexedDB" / "https_example.test_0.indexeddb.leveldb" / "000003.log",
        browser_profile / "Default" / "Service Worker" / "Database" / "CURRENT",
    ]
    cache_files = [
        browser_profile / "Default" / "Cache" / "Cache_Data" / "data_0",
        browser_profile / "Default" / "Code Cache" / "js" / "cached-code",
        browser_profile / "Default" / "Service Worker" / "CacheStorage" / "cache",
        browser_profile / "component_crx_cache" / "component",
        browser_profile / "optimization_guide_model_store" / "model",
    ]
    for path in auth_files + cache_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name)
    legacy_cache = (
        profile.parent
        / "browser-data.pre-legacy-20260521-091928"
        / "chromium-profile"
        / "Default"
        / "Cache"
        / "Cache_Data"
        / "data_0"
    )
    legacy_cache.parent.mkdir(parents=True)
    legacy_cache.write_text("legacy-cache")
    (data_root / "cli-tools.keychain-db").write_text("keychain")
    secrets_script = tmp_path / "secrets.sh"
    _fake_secrets_script(secrets_script, tmp_path / "secrets.log")
    monkeypatch.setenv("SECRET_LOG", str(tmp_path / "secrets.log"))

    archive_path = tmp_path / "export.tar.gz"
    result = _run(
        "--data-root",
        str(data_root),
        "--secrets-script",
        str(secrets_script),
        "export",
        str(archive_path),
        "--plain-text-secrets",
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["inlined_profile_secrets"] == 2
    exported_env = _read_archive_file(
        archive_path,
        "data/demo/authentication_profiles/default/.env",
        tmp_path / "extract",
    )
    assert "API_KEY=demo-secret" in exported_env
    assert 'CLIENT_SECRET="client secret with spaces"' in exported_env
    assert "CLIENT_ID=public-client" in exported_env
    assert (tmp_path / "extract" / "data" / "cli-tools.keychain-db").read_text() == "keychain"
    with tarfile.open(archive_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert "data/demo/authentication_profiles/default/browser-data/chromium-profile/Default/Cookies" in names
    assert (
        "data/demo/authentication_profiles/default/browser-data/chromium-profile/Default/Local Storage/leveldb/000003.log"
        in names
    )
    assert (
        "data/demo/authentication_profiles/default/browser-data/chromium-profile/Default/IndexedDB/https_example.test_0.indexeddb.leveldb/000003.log"
        in names
    )
    assert (
        "data/demo/authentication_profiles/default/browser-data/chromium-profile/Default/Service Worker/Database/CURRENT"
        in names
    )
    assert not any("/Cache/" in name or "/Code Cache/" in name for name in names)
    assert not any("/CacheStorage/" in name for name in names)
    assert not any("component_crx_cache" in name for name in names)
    assert not any("optimization_guide_model_store" in name for name in names)
    assert not any("browser-data.pre-legacy" in name for name in names)


def test_import_replaces_plain_text_profile_secrets_with_placeholders(
    tmp_path: Path,
    monkeypatch,
):
    archive_source = tmp_path / "archive-source"
    profile = archive_source / "data" / "demo" / "authentication_profiles" / "default" / ".env"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "ACTIVE=true\n"
        "API_KEY=demo-secret\n"
        'CLIENT_SECRET="client secret with spaces"\n'
        "DEMO_ACCESS_TOKEN=plain-token\n"
        "CLIENT_ID=public-client\n"
        "TOKEN_EXPIRES_AT=999\n"
    )
    (archive_source / "data" / "cli-tools.keychain-db").write_text("keychain")
    (archive_source / "manifest.json").write_text('{"format":"cli-tools-import-export-v1"}\n')
    archive_path = tmp_path / "import.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(archive_source / "data", arcname="data")
        archive.add(archive_source / "manifest.json", arcname="manifest.json")

    secret_log = tmp_path / "secrets.log"
    secrets_script = tmp_path / "secrets.sh"
    _fake_secrets_script(secrets_script, secret_log)
    monkeypatch.setenv("SECRET_LOG", str(secret_log))
    target_root = tmp_path / "target" / "cli-tools"

    result = _run(
        "--data-root",
        str(target_root),
        "--secrets-script",
        str(secrets_script),
        "import",
        str(archive_path),
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["placeholdered_profile_secrets"] == 3
    imported_env = (
        target_root / "demo" / "authentication_profiles" / "default" / ".env"
    ).read_text()
    assert "API_KEY=secret://demo-api-key" in imported_env
    assert "CLIENT_SECRET=secret://demo-client-secret" in imported_env
    assert "DEMO_ACCESS_TOKEN=secret://demo-access-token" in imported_env
    assert "CLIENT_ID=public-client" in imported_env
    assert "TOKEN_EXPIRES_AT=999" in imported_env
    assert (target_root / "cli-tools.keychain-db").read_text() == "keychain"
    assert secret_log.read_text().splitlines() == [
        "demo-api-key=demo-secret",
        "demo-client-secret=client secret with spaces",
        "demo-access-token=plain-token",
    ]


def test_import_uses_profile_name_in_secret_names(tmp_path: Path, monkeypatch):
    archive_source = tmp_path / "archive-source"
    profile = archive_source / "data" / "demo" / "authentication_profiles" / "prod" / ".env"
    profile.parent.mkdir(parents=True)
    profile.write_text("ACTIVE=true\nPASSWORD=plain-password\n")
    archive_path = tmp_path / "import.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(archive_source / "data", arcname="data")

    secret_log = tmp_path / "secrets.log"
    secrets_script = tmp_path / "secrets.sh"
    _fake_secrets_script(secrets_script, secret_log)
    monkeypatch.setenv("SECRET_LOG", str(secret_log))
    target_root = tmp_path / "target" / "cli-tools"

    result = _run(
        "--data-root",
        str(target_root),
        "--secrets-script",
        str(secrets_script),
        "import",
        str(archive_path),
    )

    assert result.returncode == 0, result.stderr
    imported_env = (
        target_root / "demo" / "authentication_profiles" / "prod" / ".env"
    ).read_text()
    assert "PASSWORD=secret://demo-prod-password" in imported_env
    assert secret_log.read_text() == "demo-prod-password=plain-password\n"
