"""The dependency repair refuses tampered downloads and unmanaged binaries."""
import importlib.util
import io
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("repair_lpass_tls", Path(__file__).parents[1] / "scripts/repair-lpass-tls.py")
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def test_digest_mismatch_does_not_overwrite_artifact(monkeypatch, tmp_path):
    target = tmp_path / "source.tar.gz"
    target.write_bytes(b"existing artifact")
    monkeypatch.setattr(repair.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"tampered download"))
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        repair.download("https://example.invalid/source", target, "0" * 64)
    assert target.read_bytes() == b"existing artifact"


def test_refuses_unmanaged_lpass_before_downloading(monkeypatch, tmp_path):
    unmanaged = tmp_path / "custom-lpass"
    unmanaged.write_bytes(b"do not replace")
    monkeypatch.setattr(repair.shutil, "which", lambda name: str(unmanaged) if name == "lpass" else "/synthetic/" + name)
    monkeypatch.setattr(repair.subprocess, "check_output", lambda *a, **k: str(tmp_path / "official-package"))
    monkeypatch.setattr(repair, "download", lambda *a: pytest.fail("Downloaded before verifying binary ownership"))
    with pytest.raises(SystemExit, match="outside the official Homebrew"):
        repair.main()
    assert unmanaged.read_bytes() == b"do not replace"
